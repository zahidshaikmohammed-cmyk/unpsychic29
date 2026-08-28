from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

IST = "Asia/Kolkata"
MARKET_OPEN_MINUTE = 9 * 60 + 15
MARKET_CLOSE_MINUTE_EXCLUSIVE = 15 * 60 + 30
EXPECTED_BARS_PER_SESSION = 375


def session_filter(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert(IST)
    minute = frame["timestamp"].dt.hour * 60 + frame["timestamp"].dt.minute
    return frame[(minute >= MARKET_OPEN_MINUTE) & (minute < MARKET_CLOSE_MINUTE_EXCLUSIVE)].copy()


def opening_window(day: pd.DataFrame, minutes: int = 10) -> pd.DataFrame:
    day = day.sort_values("timestamp")
    start = day["timestamp"].dt.normalize().iloc[0] + pd.Timedelta(minutes=MARKET_OPEN_MINUTE)
    expected = pd.date_range(start=start, periods=minutes, freq="min", tz=IST)
    indexed = day.set_index("timestamp")
    return indexed.reindex(expected).reset_index(names="timestamp")


def daily_features(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    required = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"Research input is missing columns: {sorted(missing)}")

    frame = session_filter(frame)
    if frame.empty:
        return pd.DataFrame()
    frame["trade_date"] = frame["timestamp"].dt.date

    rows = []
    for symbol, symbol_frame in frame.groupby("symbol", sort=True):
        previous_close = None
        for trade_date, day in symbol_frame.groupby("trade_date", sort=True):
            day = day.sort_values("timestamp").copy()
            if len(day) < 30:
                continue

            first10 = opening_window(day, 10)
            opening_complete = bool(first10[["open", "high", "low", "close", "volume"]].notna().all().all())
            opening_missing_bars = int(first10["close"].isna().sum())
            if not opening_complete:
                # The first 10-minute behaviour is a core research variable. Never compress
                # missing minutes and pretend later candles are the opening ten minutes.
                previous_close = float(day.iloc[-1]["close"])
                continue

            opening = first10.iloc[0]
            close10 = float(first10.iloc[-1]["close"])
            day_close = float(day.iloc[-1]["close"])
            day_high = float(day["high"].max())
            day_low = float(day["low"].min())
            open_price = float(opening["open"])
            first10_high = float(first10["high"].max())
            first10_low = float(first10["low"].min())
            first10_return = (close10 / open_price - 1.0) if open_price else 0.0
            first10_range = (first10_high - first10_low) / open_price if open_price else 0.0

            post10 = day[day["timestamp"] >= first10.iloc[-1]["timestamp"] + pd.Timedelta(minutes=1)]
            post10_up = (float(post10["high"].max()) / close10 - 1.0) if not post10.empty and close10 else 0.0
            post10_down = (float(post10["low"].min()) / close10 - 1.0) if not post10.empty and close10 else 0.0
            day_range = (day_high - day_low) / open_price if open_price else 0.0
            traded_value = float((day["close"] * day["volume"]).sum())
            gap = None if previous_close is None else (open_price / previous_close - 1.0)

            direction = 1 if first10_return > 0 else -1 if first10_return < 0 else 0
            continuation = None
            if direction > 0:
                continuation = float(day_close > close10)
            elif direction < 0:
                continuation = float(day_close < close10)

            reversal = 0
            if direction > 0 and post10_down < -max(abs(first10_return) * 0.75, 0.0025):
                reversal = 1
            elif direction < 0 and post10_up > max(abs(first10_return) * 0.75, 0.0025):
                reversal = 1

            rows.append({
                "symbol": symbol,
                "trade_date": trade_date,
                "previous_close": previous_close,
                "open": open_price,
                "close": day_close,
                "gap_pct": gap,
                "first10_return_pct": first10_return * 100,
                "first10_range_pct": first10_range * 100,
                "first10_volume": float(first10["volume"].sum()),
                "day_volume": float(day["volume"].sum()),
                "traded_value": traded_value,
                "day_range_pct": day_range * 100,
                "post10_max_up_pct": post10_up * 100,
                "post10_max_down_pct": post10_down * 100,
                "first10_direction": direction,
                "close_continuation_after10": continuation,
                "reversal_flag": reversal,
                "bars": len(day),
                "session_coverage_pct": len(day) / EXPECTED_BARS_PER_SESSION * 100.0,
                "opening10_complete": True,
                "opening10_missing_bars": opening_missing_bars,
            })
            previous_close = day_close
    return pd.DataFrame(rows)


def summarize(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()

    def q(series: pd.Series, quantile: float) -> float:
        clean = pd.to_numeric(series, errors="coerce").dropna()
        return float(clean.quantile(quantile)) if not clean.empty else float("nan")

    grouped = []
    for symbol, g in daily.groupby("symbol", sort=True):
        directional = g[g["first10_direction"] != 0]
        cont = directional["close_continuation_after10"].dropna()
        grouped.append({
            "symbol": symbol,
            "days": len(g),
            "median_traded_value": q(g["traded_value"], 0.50),
            "median_day_range_pct": q(g["day_range_pct"], 0.50),
            "median_first10_range_pct": q(g["first10_range_pct"], 0.50),
            "p90_first10_range_pct": q(g["first10_range_pct"], 0.90),
            "median_abs_gap_pct": q(g["gap_pct"].abs(), 0.50),
            "p90_abs_gap_pct": q(g["gap_pct"].abs(), 0.90),
            "large_gap_rate_ge_1pct": float((g["gap_pct"].abs() >= 0.01).mean()),
            "large_gap_rate_ge_2pct": float((g["gap_pct"].abs() >= 0.02).mean()),
            "opening_shock_rate_ge_1pct_range": float((g["first10_range_pct"] >= 1.0).mean()),
            "opening_shock_rate_ge_2pct_range": float((g["first10_range_pct"] >= 2.0).mean()),
            "median_first10_volume_share": q(g["first10_volume"] / g["day_volume"].replace(0, pd.NA), 0.50),
            "continuation_rate_after10": float(cont.mean()) if not cont.empty else float("nan"),
            "reversal_rate": float(g["reversal_flag"].mean()),
            "directional_days_rate": float((g["first10_direction"] != 0).mean()),
            "median_session_coverage_pct": q(g["session_coverage_pct"], 0.50),
            "p10_session_coverage_pct": q(g["session_coverage_pct"], 0.10),
            "opening10_complete_rate": float(g["opening10_complete"].mean()),
        })
    return pd.DataFrame(grouped)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="artifacts/raw_1min")
    parser.add_argument("--output", default="artifacts/research")
    args = parser.parse_args()
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(input_dir.glob("*.parquet"))
    if not paths:
        raise RuntimeError("No parquet datasets were found for research.")

    daily_parts = []
    for path in paths:
        frame = pd.read_parquet(path)
        features = daily_features(frame)
        if not features.empty:
            daily_parts.append(features)
    if not daily_parts:
        raise RuntimeError("No valid daily behavioural features could be produced from the downloaded datasets.")

    daily = pd.concat(daily_parts, ignore_index=True)
    summary = summarize(daily)
    if summary.empty:
        raise RuntimeError("Research summary is empty.")
    daily.to_parquet(output_dir / "daily_features.parquet", index=False)
    daily.to_csv(output_dir / "daily_features.csv", index=False)
    summary.to_csv(output_dir / "stock_behaviour_summary.csv", index=False)
    print("\nInitial behaviour summary (descriptive only; not final PSY29 ranking):")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
