from __future__ import annotations

import io
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from zoneinfo import ZoneInfo

DHAN_INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"
INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = "09:15:00"
MARKET_CLOSE = "15:30:00"


def require_access_token() -> str:
    token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DHAN_ACCESS_TOKEN GitHub secret/environment variable is missing.")
    return token


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["timestamp", "open", "high", "low", "close", "volume", "security_id"]
    )


def fetch_instrument_master(session: requests.Session) -> pd.DataFrame:
    response = session.get(INSTRUMENT_MASTER_URL, timeout=60)
    response.raise_for_status()
    return pd.read_csv(io.BytesIO(response.content), low_memory=False)


def resolve_equities(master: pd.DataFrame, symbols: Iterable[str]) -> pd.DataFrame:
    required = {
        "SEM_EXM_EXCH_ID",
        "SEM_SEGMENT",
        "SEM_SMST_SECURITY_ID",
        "SEM_INSTRUMENT_NAME",
        "SEM_TRADING_SYMBOL",
    }
    missing = required.difference(master.columns)
    if missing:
        raise RuntimeError(f"Dhan instrument master is missing columns: {sorted(missing)}")

    symbols = [s.strip().upper() for s in symbols if s.strip()]
    rows = master[
        (master["SEM_EXM_EXCH_ID"].astype(str).str.upper() == "NSE")
        & (master["SEM_SEGMENT"].astype(str).str.upper() == "E")
        & (master["SEM_INSTRUMENT_NAME"].astype(str).str.upper() == "EQUITY")
        & (master["SEM_TRADING_SYMBOL"].astype(str).str.upper().isin(symbols))
    ].copy()

    rows["symbol"] = rows["SEM_TRADING_SYMBOL"].astype(str).str.upper()
    rows["security_id"] = rows["SEM_SMST_SECURITY_ID"].astype(str)
    rows["exchange_segment"] = "NSE_EQ"
    rows["instrument"] = "EQUITY"

    # Suspended/legacy rows can occasionally share a trading symbol. Keep one
    # deterministic security ID, while preserving the full master in the artifact.
    rows = rows.sort_values(["symbol", "security_id"]).drop_duplicates("symbol", keep="last")

    missing_symbols = sorted(set(symbols) - set(rows["symbol"]))
    if missing_symbols:
        raise RuntimeError(
            "Could not resolve these NSE equity symbols in Dhan's instrument master: "
            + ", ".join(missing_symbols)
        )

    output_columns = ["symbol", "security_id", "exchange_segment", "instrument"]
    for optional in ["SEM_CUSTOM_SYMBOL", "SM_SYMBOL_NAME"]:
        if optional in rows.columns:
            output_columns.append(optional)
    return rows[output_columns]


def date_chunks(start: date, end: date, chunk_days: int) -> Iterable[tuple[date, date]]:
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        yield cursor, chunk_end
        cursor = chunk_end


def fetch_chunk(
    session: requests.Session,
    access_token: str,
    security_id: str,
    start: date,
    end: date,
    interval: str = "1",
    max_retries: int = 6,
) -> pd.DataFrame:
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "interval": str(interval),
        "oi": False,
        "fromDate": f"{start.isoformat()} {MARKET_OPEN}",
        "toDate": f"{end.isoformat()} {MARKET_CLOSE}",
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "access-token": access_token,
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = session.post(
                DHAN_INTRADAY_URL,
                json=payload,
                headers=headers,
                timeout=120,
            )

            # Authentication, authorization and request errors are not retryable.
            if response.status_code in {401, 403}:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text[:500]
                raise RuntimeError(
                    f"Dhan authentication/data-access failure for securityId {security_id}: "
                    f"HTTP {response.status_code}; {detail}"
                )

            if response.status_code == 429 or response.status_code >= 500:
                if attempt == max_retries:
                    raise RuntimeError(
                        f"Dhan temporary/server failure after {max_retries} attempts: "
                        f"HTTP {response.status_code}; {response.text[:500]}"
                    )
                time.sleep(min(2 ** (attempt - 1), 20))
                continue

            if response.status_code != 200:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text[:500]
                raise RuntimeError(
                    f"Dhan historical request rejected for securityId {security_id}: "
                    f"HTTP {response.status_code}; {detail}"
                )

            body = response.json()
            if not isinstance(body, dict):
                raise RuntimeError("Dhan returned a non-object response.")
            if body.get("errorCode") or body.get("errorMessage"):
                raise RuntimeError(f"Dhan API error: {body}")
            return response_to_frame(body, security_id)

        except requests.RequestException as exc:
            if attempt == max_retries:
                raise RuntimeError(
                    f"Dhan network request failed after {max_retries} attempts: {exc}"
                ) from exc
            time.sleep(min(2 ** (attempt - 1), 20))

    raise AssertionError("unreachable")


def response_to_frame(body: dict, security_id: str) -> pd.DataFrame:
    columns = ["open", "high", "low", "close", "volume", "timestamp"]
    missing = [key for key in columns if key not in body]
    if missing:
        raise RuntimeError(f"Dhan response is missing candle arrays: {missing}")

    lengths = {key: len(body[key]) for key in columns}
    if max(lengths.values(), default=0) == 0:
        return empty_frame()
    if len(set(lengths.values())) != 1:
        raise RuntimeError(f"Dhan returned mismatched candle array lengths: {lengths}")

    frame = pd.DataFrame({key: body[key] for key in columns})
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True).dt.tz_convert(IST)
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame["security_id"] = str(security_id)
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    return frame[["timestamp", "open", "high", "low", "close", "volume", "security_id"]]


def download_symbol(
    session: requests.Session,
    access_token: str,
    symbol: str,
    security_id: str,
    start: date,
    end: date,
    chunk_days: int,
    output_dir: Path,
) -> Path:
    parts: list[pd.DataFrame] = []
    chunks = list(date_chunks(start, end, chunk_days))
    if not chunks:
        raise RuntimeError(f"No date range generated for {symbol}: {start} -> {end}")

    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        print(f"  {symbol}: chunk {index}/{len(chunks)} {chunk_start} -> {chunk_end}")
        frame = fetch_chunk(session, access_token, security_id, chunk_start, chunk_end)
        if not frame.empty:
            parts.append(frame)
        # Stay comfortably below Dhan's documented 5 requests/second data limit.
        time.sleep(0.30)

    result = pd.concat(parts, ignore_index=True) if parts else empty_frame()
    if not result.empty:
        result = result.sort_values("timestamp").drop_duplicates("timestamp", keep="last")

    result.insert(0, "symbol", symbol)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{symbol}.parquet"
    result.to_parquet(path, index=False)
    return path


def validate_frame(path: Path) -> dict:
    frame = pd.read_parquet(path)
    if frame.empty:
        return {
            "symbol": path.stem,
            "rows": 0,
            "status": "EMPTY",
            "reason": "Dhan returned no candles for the requested period.",
        }

    timestamps = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(IST)
    duplicate_count = int(timestamps.duplicated().sum())
    bad_ohlc = int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    invalid_high = int((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).sum())
    invalid_low = int((frame["low"] > frame[["open", "close", "high"]].min(axis=1)).sum())
    null_volume = int(frame["volume"].isna().sum())

    in_session = (timestamps.dt.time >= pd.Timestamp(MARKET_OPEN).time()) & (
        timestamps.dt.time <= pd.Timestamp(MARKET_CLOSE).time()
    )
    out_of_session = int((~in_session).sum())

    # A 1-minute feed should not contain repeated timestamps. We deliberately
    # report missing minute gaps but do not treat weekends/holidays as gaps.
    by_day = frame.assign(_ts=timestamps).sort_values("_ts").groupby(timestamps.dt.date)
    max_intraday_gap_minutes = 0.0
    for _, day in by_day:
        diffs = day["_ts"].diff().dt.total_seconds().div(60).dropna()
        if not diffs.empty:
            max_intraday_gap_minutes = max(max_intraday_gap_minutes, float(diffs.max()))

    checks = [duplicate_count == 0, bad_ohlc == 0, invalid_high == 0, invalid_low == 0, out_of_session == 0]
    return {
        "symbol": path.stem,
        "rows": int(len(frame)),
        "first_timestamp": str(timestamps.min()),
        "last_timestamp": str(timestamps.max()),
        "trading_days": int(timestamps.dt.date.nunique()),
        "duplicate_timestamps": duplicate_count,
        "bad_ohlc_rows": bad_ohlc,
        "invalid_high_rows": invalid_high,
        "invalid_low_rows": invalid_low,
        "null_volume_rows": null_volume,
        "out_of_session_rows": out_of_session,
        "max_intraday_gap_minutes": max_intraday_gap_minutes,
        "status": "OK" if all(checks) else "CHECK",
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/research.json")
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--output", default="artifacts/raw_1min")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    access_token = require_access_token()

    lookback_days = int(args.days if args.days is not None else config["lookback_days"])
    if lookback_days <= 0:
        raise ValueError("--days must be positive")

    max_symbols = args.max_symbols if args.max_symbols is not None else config.get("max_symbols")
    if max_symbols is not None and int(max_symbols) <= 0:
        raise ValueError("--max-symbols must be positive")

    chunk_days = int(config.get("chunk_days", 20))
    end = datetime.now(IST).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)

    symbols = [str(s).upper() for s in config["test_symbols"]]
    if max_symbols:
        symbols = symbols[: int(max_symbols)]
    if not symbols:
        raise RuntimeError("No test symbols configured.")

    session = requests.Session()
    session.headers.update({"User-Agent": "UNPSYCHIC29/1.0"})

    print("Downloading Dhan instrument master...")
    master = fetch_instrument_master(session)
    Path("artifacts").mkdir(exist_ok=True)
    master.to_csv("artifacts/dhan_instrument_master.csv", index=False)

    resolved = resolve_equities(master, symbols)
    resolved.to_csv("artifacts/resolved_test_universe.csv", index=False)
    print("Resolved universe:")
    print(resolved[["symbol", "security_id"]].to_string(index=False))

    output_dir = Path(args.output)
    reports: list[dict] = []
    for row in resolved.itertuples(index=False):
        path = download_symbol(
            session,
            access_token,
            row.symbol,
            row.security_id,
            start,
            end,
            chunk_days,
            output_dir,
        )
        report = validate_frame(path)
        reports.append(report)
        print(f"  {row.symbol}: {report['status']} ({report['rows']} rows)")

    validation = pd.DataFrame(reports)
    validation.to_csv("artifacts/download_validation.csv", index=False)

    if len(validation) != len(resolved):
        raise RuntimeError("Validation report does not contain one result for every resolved symbol.")
    if (validation["status"] != "OK").any():
        bad = validation.loc[validation["status"] != "OK", "symbol"].tolist()
        raise RuntimeError(
            "Historical-data validation failed for: " + ", ".join(bad)
        )

    print("\nHistorical download validation: PASS")
    print(validation.to_string(index=False))


if __name__ == "__main__":
    main()
