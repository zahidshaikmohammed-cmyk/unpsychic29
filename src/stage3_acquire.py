from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from zoneinfo import ZoneInfo

try:
    from .dhan_historical import (
        canonical_session_mask,
        check_dhan_access,
        date_chunks,
        fetch_chunk,
        require_access_token,
        validate_frame,
    )
    from .research_metrics import daily_features
except ImportError:
    from dhan_historical import (
        canonical_session_mask,
        check_dhan_access,
        date_chunks,
        fetch_chunk,
        require_access_token,
        validate_frame,
    )
    from research_metrics import daily_features

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_CHUNK_DAYS = 30
DEFAULT_BATCH_SIZE = 50


def load_universe(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"security_id": str, "symbol": str})
    required = {"symbol", "security_id", "exchange_segment", "instrument"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"Candidate universe missing columns: {sorted(missing)}")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["security_id"] = frame["security_id"].astype(str).str.strip()
    if frame.empty:
        raise RuntimeError("Candidate universe is empty.")
    if frame["symbol"].duplicated().any() or frame["security_id"].duplicated().any():
        raise RuntimeError("Candidate universe contains duplicate symbols or Security IDs.")
    if set(frame["exchange_segment"]) != {"NSE_EQ"} or set(frame["instrument"]) != {"EQUITY"}:
        raise RuntimeError("Candidate universe contains non-NSE_EQ/non-EQUITY instruments.")
    return frame.sort_values("symbol").reset_index(drop=True)


def select_batch(universe: pd.DataFrame, batch_number: int, batch_size: int) -> pd.DataFrame:
    if batch_number < 1:
        raise ValueError("batch_number must be >= 1")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    start = (batch_number - 1) * batch_size
    batch = universe.iloc[start : start + batch_size].copy()
    if batch.empty:
        raise RuntimeError(f"Batch {batch_number} is outside the universe (size={len(universe)}).")
    batch["batch_number"] = batch_number
    batch["batch_size"] = batch_size
    return batch


def reconcile_duplicate_timestamps(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if frame.empty or not frame["timestamp"].duplicated().any():
        return frame, 0
    value_columns = ["open", "high", "low", "close", "volume", "security_id"]
    conflicting: list[str] = []
    removed = 0
    for timestamp, group in frame[frame["timestamp"].duplicated(keep=False)].groupby("timestamp", sort=False):
        if any(group[column].nunique(dropna=False) > 1 for column in value_columns):
            conflicting.append(str(timestamp))
        removed += len(group) - 1
    if conflicting:
        raise RuntimeError(f"Conflicting duplicate candles detected at {len(conflicting)} timestamps; first={conflicting[:5]}")
    return frame.drop_duplicates("timestamp", keep="first").sort_values("timestamp").reset_index(drop=True), removed


def acquire_symbol(
    session: requests.Session,
    token: str,
    symbol: str,
    security_id: str,
    start: date,
    end: date,
    chunk_days: int,
) -> tuple[pd.DataFrame, list[dict], int]:
    parts: list[pd.DataFrame] = []
    chunk_reports: list[dict] = []
    chunks = list(date_chunks(start, end, chunk_days))
    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        print(f"  {symbol}: chunk {index}/{len(chunks)} {chunk_start} -> {chunk_end}")
        frame = fetch_chunk(session, token, security_id, chunk_start, chunk_end, interval="1")
        chunk_reports.append({
            "symbol": symbol,
            "security_id": security_id,
            "chunk_index": index,
            "chunk_count": len(chunks),
            "from_date": chunk_start.isoformat(),
            "to_date_exclusive": chunk_end.isoformat(),
            "rows": int(len(frame)),
        })
        if not frame.empty:
            frame.insert(0, "symbol", symbol)
            parts.append(frame)
        time.sleep(0.30)
    if not parts:
        raise RuntimeError(f"Dhan returned no 1-minute candles for {symbol} in the requested period.")
    raw = pd.concat(parts, ignore_index=True)
    raw, duplicate_rows_removed = reconcile_duplicate_timestamps(raw)
    return raw, chunk_reports, duplicate_rows_removed


def write_temp_frame(frame: pd.DataFrame, symbol: str) -> Path:
    path = Path("/tmp") / f"unpsychic29_{symbol}.parquet"
    frame.to_parquet(path, index=False)
    return path


def run(universe_path: Path, batch_number: int, batch_size: int, lookback_days: int, chunk_days: int, output_dir: Path) -> None:
    if lookback_days < 300:
        raise RuntimeError("Stage 3 requires at least 300 calendar days; use ~365 for the production run.")
    token = require_access_token()
    universe = load_universe(universe_path)
    batch = select_batch(universe, batch_number, batch_size)

    session = requests.Session()
    session.headers.update({"User-Agent": "UNPSYCHIC29/1.0"})
    profile = check_dhan_access(session, token)

    end = datetime.now(IST).date() + timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    output_dir.mkdir(parents=True, exist_ok=True)

    daily_parts: list[pd.DataFrame] = []
    validations: list[dict] = []
    chunks: list[dict] = []
    acquisition_rows: list[dict] = []

    print(f"Stage 3 batch {batch_number}: {len(batch)} symbols; {start} -> {end} (exclusive)")
    print(f"Dhan profile preflight: PASS; client={profile.get('dhanClientId')}; dataPlan={profile.get('dataPlan')}")

    for row in batch.itertuples(index=False):
        print(f"\n[{row.symbol}] securityId={row.security_id}")
        raw, symbol_chunks, duplicate_rows_removed = acquire_symbol(
            session, token, row.symbol, row.security_id, start, end, chunk_days
        )
        chunks.extend(symbol_chunks)

        temp = write_temp_frame(raw, row.symbol)
        try:
            report = validate_frame(temp)
        finally:
            temp.unlink(missing_ok=True)

        report["duplicate_rows_removed_after_chunk_reconciliation"] = duplicate_rows_removed
        validations.append(report)
        if report["status"] != "OK":
            # Structural corruption is a hard failure. Market-session warnings are not.
            raise RuntimeError(f"Structural data validation failed for {row.symbol}: {json.dumps(report, default=str)}")

        session_mask = canonical_session_mask(raw["timestamp"])
        clean = raw.loc[session_mask].copy()
        clean = clean.sort_values("timestamp").reset_index(drop=True)
        features = daily_features(clean)
        feature_days = int(features["trade_date"].nunique()) if not features.empty else 0
        acquisition_rows.append({
            "symbol": row.symbol,
            "security_id": str(row.security_id),
            "acquisition_status": "ACQUIRED",
            "structural_validation": report["status"],
            "raw_rows": int(report["rows"]),
            "session_rows": int(report["rows_after_session_filter"]),
            "trading_days": int(report["trading_days"]),
            "bar_coverage_pct": float(report["bar_coverage_pct"]),
            "out_of_session_rows_quarantined": int(report["out_of_session_rows"]),
            "duplicate_rows_removed": int(duplicate_rows_removed),
            "max_intraday_gap_minutes": float(report["max_intraday_gap_minutes"]),
            "feature_days_with_complete_opening10": feature_days,
            "feature_status": "AVAILABLE" if feature_days else "NO_COMPLETE_OPENING_DAYS",
            "warning_reasons": ";".join(report.get("warning_reasons", [])),
        })
        if not features.empty:
            features["batch_number"] = batch_number
            daily_parts.append(features)
        print(
            f"{row.symbol}: PASS | {report['rows']} raw candles | {report['trading_days']} trading days | "
            f"{report['bar_coverage_pct']:.2f}% regular-session coverage | {feature_days} feature days"
        )

    validation = pd.DataFrame(validations).sort_values("symbol")
    acquisition = pd.DataFrame(acquisition_rows).sort_values("symbol")
    chunk_log = pd.DataFrame(chunks)
    if daily_parts:
        daily = pd.concat(daily_parts, ignore_index=True).sort_values(["symbol", "trade_date"])
    else:
        daily = pd.DataFrame()

    if len(validation) != len(batch):
        raise RuntimeError("Validation row count does not equal batch size.")
    if len(acquisition) != len(batch) or acquisition["acquisition_status"].ne("ACQUIRED").any():
        raise RuntimeError("Acquisition coverage does not equal the requested batch.")
    if (validation["status"] != "OK").any():
        raise RuntimeError("One or more symbols has structural data-quality failures.")

    batch.to_csv(output_dir / "batch_universe.csv", index=False)
    validation.to_csv(output_dir / "download_validation.csv", index=False)
    acquisition.to_csv(output_dir / "acquisition_quality.csv", index=False)
    if not daily.empty:
        daily.to_parquet(output_dir / "daily_features.parquet", index=False)
        daily.to_csv(output_dir / "daily_features.csv", index=False)
    else:
        raise RuntimeError("No daily behavioural features were produced for the entire batch.")
    chunk_log.to_csv(output_dir / "chunk_log.csv", index=False)

    manifest = {
        "project": "UNPSYCHIC29",
        "stage": 3,
        "stage_name": "one-year-1min-acquisition-and-feature-extraction",
        "generated_at_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
        "batch_number": batch_number,
        "batch_size_requested": batch_size,
        "batch_symbol_count": len(batch),
        "universe_symbol_count": len(universe),
        "lookback_calendar_days": lookback_days,
        "from_date": start.isoformat(),
        "to_date_exclusive": end.isoformat(),
        "chunk_days": chunk_days,
        "raw_1min_data_persisted": False,
        "raw_1min_data_processed_in_memory": True,
        "raw_1min_data_storage_policy": "Raw minute data is processed in memory; compact quality and daily-feature artifacts are persisted. Full minute data will be reacquired for finalists.",
        "all_symbols_acquired": True,
        "validated_symbol_count": len(validation),
        "symbols_with_session_warnings": int((acquisition["warning_reasons"] != "").sum()),
        "symbols_with_complete_opening10_features": int((acquisition["feature_status"] == "AVAILABLE").sum()),
        "total_1min_rows_processed": int(validation["rows"].sum()),
        "total_regular_session_rows": int(validation["rows_after_session_filter"].sum()),
        "total_daily_feature_rows": int(len(daily)),
    }
    (output_dir / "stage3_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\nSTAGE 3 BATCH GATE: PASS")
    print(json.dumps(manifest, indent=2))


def self_test() -> None:
    sample = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-02 09:15:00", "2026-01-02 09:15:00", "2026-01-02 09:16:00"], utc=True),
        "open": [100.0, 100.0, 101.0],
        "high": [101.0, 101.0, 102.0],
        "low": [99.0, 99.0, 100.0],
        "close": [100.5, 100.5, 101.5],
        "volume": [1000, 1000, 1100],
        "security_id": ["1", "1", "1"],
    })
    clean, removed = reconcile_duplicate_timestamps(sample)
    assert len(clean) == 2 and removed == 1
    selected = select_batch(pd.DataFrame({"symbol": ["AAA", "BBB", "CCC"], "security_id": ["1", "2", "3"], "exchange_segment": ["NSE_EQ"] * 3, "instrument": ["EQUITY"] * 3}), 2, 2)
    assert selected["symbol"].tolist() == ["CCC"]
    print("Stage 3 self-test: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="artifacts/universe/candidate_universe.csv")
    parser.add_argument("--batch-number", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--chunk-days", type=int, default=DEFAULT_CHUNK_DAYS)
    parser.add_argument("--output", default="artifacts/stage3")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        run(Path(args.universe), args.batch_number, args.batch_size, args.lookback_days, args.chunk_days, Path(args.output))
