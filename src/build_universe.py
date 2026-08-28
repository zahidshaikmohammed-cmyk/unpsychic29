from __future__ import annotations

import argparse
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

NIFTY500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
DHAN_INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
MIN_EXPECTED_NIFTY500 = 450
MAX_EXPECTED_NIFTY500 = 550


def fetch_csv(session: requests.Session, url: str, label: str, timeout: int = 60) -> pd.DataFrame:
    response = session.get(url, timeout=timeout, headers={"User-Agent": "UNPSYCHIC29/1.0"})
    response.raise_for_status()
    if len(response.content) < 1024:
        raise RuntimeError(f"{label} response is unexpectedly small.")
    try:
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)
    except Exception as exc:
        raise RuntimeError(f"Could not parse {label} CSV: {exc}") from exc


def normalize_nifty500(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"NIFTY 500 CSV is missing columns: {sorted(missing)}")

    out = frame[["Company Name", "Industry", "Symbol", "Series", "ISIN Code"]].copy()
    out["symbol"] = out["Symbol"].astype(str).str.strip().str.upper()
    out["series"] = out["Series"].astype(str).str.strip().str.upper()
    out = out[out["symbol"].ne("") & out["symbol"].ne("NAN")].copy()
    out = out[out["series"].eq("EQ")].copy()
    if out["symbol"].duplicated().any():
        duplicates = sorted(out.loc[out["symbol"].duplicated(keep=False), "symbol"].unique())
        raise RuntimeError(f"NIFTY 500 contains duplicate symbols: {duplicates}")
    if not MIN_EXPECTED_NIFTY500 <= len(out) <= MAX_EXPECTED_NIFTY500:
        raise RuntimeError(f"Unexpected NIFTY 500 constituent count after EQ filtering: {len(out)}")
    return out.reset_index(drop=True)


def resolve_against_dhan(nifty: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    required = {
        "SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_SMST_SECURITY_ID",
        "SEM_INSTRUMENT_NAME", "SEM_TRADING_SYMBOL",
    }
    missing = required.difference(master.columns)
    if missing:
        raise RuntimeError(f"Dhan instrument master is missing columns: {sorted(missing)}")

    m = master[
        (master["SEM_EXM_EXCH_ID"].astype(str).str.upper() == "NSE")
        & (master["SEM_SEGMENT"].astype(str).str.upper() == "E")
        & (master["SEM_INSTRUMENT_NAME"].astype(str).str.upper() == "EQUITY")
    ].copy()
    m["symbol"] = m["SEM_TRADING_SYMBOL"].astype(str).str.strip().str.upper()
    m["security_id"] = m["SEM_SMST_SECURITY_ID"].astype(str).str.strip()
    m = m[m["symbol"].ne("") & m["security_id"].ne("")].copy()
    m = m.sort_values(["symbol", "security_id"]).drop_duplicates("symbol", keep="last")

    merged = nifty.merge(
        m[["symbol", "security_id"]],
        on="symbol",
        how="left",
        validate="one_to_one",
    )
    missing_symbols = sorted(merged.loc[merged["security_id"].isna(), "symbol"].tolist())
    if missing_symbols:
        raise RuntimeError(
            f"NIFTY 500 -> Dhan NSE_EQ resolution failed for {len(missing_symbols)} symbols: "
            + ", ".join(missing_symbols)
        )
    if merged["security_id"].duplicated().any():
        duplicates = sorted(merged.loc[merged["security_id"].duplicated(keep=False), "security_id"].unique())
        raise RuntimeError(f"Dhan security IDs are not one-to-one in the resolved universe: {duplicates}")

    merged["exchange_segment"] = "NSE_EQ"
    merged["instrument"] = "EQUITY"
    merged["universe"] = "NIFTY500"
    return merged[
        ["symbol", "security_id", "exchange_segment", "instrument", "universe", "Company Name", "Industry", "Series", "ISIN Code"]
    ].sort_values("symbol").reset_index(drop=True)


def build_universe(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    print("Downloading current NSE NIFTY 500 constituent file...")
    nifty_raw = fetch_csv(session, NIFTY500_CSV_URL, "NIFTY 500 constituent")
    nifty = normalize_nifty500(nifty_raw)

    print(f"NIFTY 500 constituent count: {len(nifty)}")
    print("Downloading Dhan instrument master...")
    dhan_master = fetch_csv(session, DHAN_INSTRUMENT_MASTER_URL, "Dhan instrument master")
    resolved = resolve_against_dhan(nifty, dhan_master)

    nifty.to_csv(output_dir / "nifty500_constituents.csv", index=False)
    resolved.to_csv(output_dir / "candidate_universe.csv", index=False)

    manifest = {
        "project": "UNPSYCHIC29",
        "stage": 2,
        "stage_name": "candidate-universe-construction",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe_source": NIFTY500_CSV_URL,
        "instrument_source": DHAN_INSTRUMENT_MASTER_URL,
        "selection_basis": "Current NIFTY 500 constituent universe; intraday liquidity is NOT assumed and will be measured in Stage 3.",
        "constituent_count": int(len(nifty)),
        "resolved_count": int(len(resolved)),
        "unresolved_count": int(nifty["symbol"].isin(set(nifty["symbol"]) - set(resolved["symbol"])).sum()),
        "unique_security_ids": int(resolved["security_id"].nunique()),
    }
    (output_dir / "universe_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if len(resolved) != len(nifty) or resolved["security_id"].nunique() != len(resolved):
        raise RuntimeError("Universe integrity gate failed.")

    print("\nSTAGE 2 UNIVERSE GATE: PASS")
    print(json.dumps(manifest, indent=2))
    print("\nCandidate universe preview:")
    print(resolved[["symbol", "security_id", "Industry"]].head(20).to_string(index=False))


def self_test() -> None:
    sample_nifty = pd.DataFrame(
        {
            "Company Name": ["Alpha", "Beta"],
            "Industry": ["X", "Y"],
            "Symbol": ["ALPHA", "BETA"],
            "Series": ["EQ", "EQ"],
            "ISIN Code": ["INEA", "INEB"],
        }
    )
    sample_master = pd.DataFrame(
        {
            "SEM_EXM_EXCH_ID": ["NSE", "NSE"],
            "SEM_SEGMENT": ["E", "E"],
            "SEM_SMST_SECURITY_ID": ["101", "102"],
            "SEM_INSTRUMENT_NAME": ["EQUITY", "EQUITY"],
            "SEM_TRADING_SYMBOL": ["ALPHA", "BETA"],
        }
    )
    original_min, original_max = MIN_EXPECTED_NIFTY500, MAX_EXPECTED_NIFTY500
    globals()["MIN_EXPECTED_NIFTY500"] = 2
    globals()["MAX_EXPECTED_NIFTY500"] = 2
    try:
        nifty = normalize_nifty500(sample_nifty)
        resolved = resolve_against_dhan(nifty, sample_master)
        assert len(resolved) == 2
        assert resolved["security_id"].tolist() == ["101", "102"]
    finally:
        globals()["MIN_EXPECTED_NIFTY500"] = original_min
        globals()["MAX_EXPECTED_NIFTY500"] = original_max
    print("Universe self-test: PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/universe")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    build_universe(Path(args.output))


if __name__ == "__main__":
    main()
