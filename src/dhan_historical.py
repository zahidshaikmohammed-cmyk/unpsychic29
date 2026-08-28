from __future__ import annotations

import io
import os
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from zoneinfo import ZoneInfo

DHAN_INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"
INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
IST = ZoneInfo("Asia/Kolkata")


def require_access_token() -> str:
    token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DHAN_ACCESS_TOKEN GitHub secret/environment variable is missing.")
    return token


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

    # A tiny number of legacy/suspended instruments can share symbols. Prefer
    # active-looking rows and keep one deterministic row per requested symbol.
    rows = rows.sort_values(["symbol", "security_id"]).drop_duplicates("symbol", keep="last")

    missing_symbols = sorted(set(symbols) - set(rows["symbol"]))
    if missing_symbols:
        raise RuntimeError(
            "Could not resolve these NSE equity symbols in Dhan's instrument master: "
            + ", ".join(missing_symbols)
        )
    return rows[["symbol", "security_id", "exchange_segment", "instrument", "SEM_CUSTOM_SYMBOL", "SM_SYMBOL_NAME"]]


def date_chunks(start: date, end: date, chunk_days: int) -> Iterable[tuple[date, date]]:
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        yield cursor, chunk_end
        cursor = chunk_end


def fetch_chunk(
    session: requests.Session,
    access_token: str,
    security_id: str,
    exchange_segment: str,
    instrument: str,
    start: date,
    end: date,
    interval: str = "1",
    max_retries: int = 5,
) -> pd.DataFrame:
    payload = {
        "securityId": str(security_id),
        "exchangeSegment": exchange_segment,
        "instrument": instrument,
        "interval": str(interval),
        "oi": False,
        "fromDate": f"{start.isoformat()} 09:00:00",
        "toDate": f"{end.isoformat()} 16:00:00",
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "access-token": access_token,
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = session.post(DHAN_INTRADAY_URL, json=payload, headers=headers, timeout=90)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == max_retries:
                    response.raise_for_status()
                time.sleep(min(2 ** (attempt - 1), 16))
                continue
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise RuntimeError("Dhan returned a non-object response.")
            if body.get("errorCode") or body.get("errorMessage"):
                raise RuntimeError(f"Dhan API error: {body}")
            return response_to_frame(body, security_id)
        except (requests.RequestException, ValueError) as exc:
            if attempt == max_retries:
                raise RuntimeError(f"Dhan request failed after {max_retries} attempts: {exc}") from exc
            time.sleep(min(2 ** (attempt - 1), 16))
    raise AssertionError("unreachable")


def response_to_frame(body: dict, security_id: str) -> pd.DataFrame:
    columns = ["open", "high", "low", "close", "volume", "timestamp"]
    lengths = [len(body.get(key, [])) for key in columns]
    if not lengths or max(lengths) == 0:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "security_id"])
    if len(set(lengths)) != 1:
        raise RuntimeError(f"Dhan returned mismatched candle array lengths: {dict(zip(columns, lengths))}")

    frame = pd.DataFrame({key: body.get(key, []) for key in columns})
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
    for chunk_start, chunk_end in date_chunks(start, end, chunk_days):
        print(f"  {symbol}: {chunk_start} -> {chunk_end}")
        frame = fetch_chunk(
            session,
            access_token,
            security_id,
            "NSE_EQ",
            "EQUITY",
            chunk_start,
            chunk_end,
            interval="1",
        )
        if not frame.empty:
            parts.append(frame)
        # Dhan's documented Data API rate limit is 5 requests/second.
        time.sleep(0.25)

    if parts:
        result = pd.concat(parts, ignore_index=True)
        result = result.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    else:
        result = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "security_id"])

    result.insert(0, "symbol", symbol)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{symbol}.parquet"
    result.to_parquet(path, index=False)
    return path


def validate_frame(path: Path) -> dict:
    frame = pd.read_parquet(path)
    if frame.empty:
        return {"symbol": path.stem, "rows": 0, "status": "EMPTY"}

    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    duplicate_count = int(timestamps.duplicated().sum())
    bad_ohlc = int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    invalid_range = int((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).sum())
    invalid_low = int((frame["low"] > frame[["open", "close", "high"]].min(axis=1)).sum())
    return {
        "symbol": path.stem,
        "rows": int(len(frame)),
        "first_timestamp": str(frame["timestamp"].min()),
        "last_timestamp": str(frame["timestamp"].max()),
        "duplicate_timestamps": duplicate_count,
        "bad_ohlc_rows": bad_ohlc,
        "invalid_high_rows": invalid_range,
        "invalid_low_rows": invalid_low,
        "status": "OK" if duplicate_count == 0 and bad_ohlc == 0 and invalid_range == 0 and invalid_low == 0 else "CHECK",
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
    max_symbols = args.max_symbols if args.max_symbols is not None else config.get("max_symbols")
    chunk_days = int(config.get("chunk_days", 20))

    end = datetime.now(IST).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    symbols = config["test_symbols"]
    if max_symbols:
        symbols = symbols[:max_symbols]

    session = requests.Session()
    print("Downloading Dhan instrument master...")
    master = fetch_instrument_master(session)
    Path("artifacts").mkdir(exist_ok=True)
    master.to_csv("artifacts/dhan_instrument_master.csv", index=False)
    resolved = resolve_equities(master, symbols)
    resolved.to_csv("artifacts/resolved_test_universe.csv", index=False)
    print("Resolved universe:")
    print(resolved[["symbol", "security_id"]].to_string(index=False))

    output_dir = Path(args.output)
    reports = []
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
        reports.append(validate_frame(path))

    validation = pd.DataFrame(reports)
    validation.to_csv("artifacts/download_validation.csv", index=False)
    print("\nValidation:")
    print(validation.to_string(index=False))

    if not validation.empty and (validation["status"] != "OK").any():
        raise RuntimeError("One or more downloaded datasets failed validation. See artifacts/download_validation.csv")


if __name__ == "__main__":
    main()
