from __future__ import annotations

import unittest

import pandas as pd

from src.stage3_acquire import load_universe, reconcile_duplicate_timestamps, select_batch


class Stage3Tests(unittest.TestCase):
    def test_batch_selection_is_deterministic(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "CCC", "DDD", "EEE"],
                "security_id": ["1", "2", "3", "4", "5"],
                "exchange_segment": ["NSE_EQ"] * 5,
                "instrument": ["EQUITY"] * 5,
            }
        )
        self.assertEqual(select_batch(frame, 1, 2)["symbol"].tolist(), ["AAA", "BBB"])
        self.assertEqual(select_batch(frame, 2, 2)["symbol"].tolist(), ["CCC", "DDD"])
        self.assertEqual(select_batch(frame, 3, 2)["symbol"].tolist(), ["EEE"])

    def test_duplicate_symbols_are_rejected(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["AAA", "AAA"],
                "security_id": ["1", "2"],
                "exchange_segment": ["NSE_EQ", "NSE_EQ"],
                "instrument": ["EQUITY", "EQUITY"],
            }
        )
        with self.assertRaises(RuntimeError):
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "universe.csv"
                frame.to_csv(path, index=False)
                load_universe(path)

    def test_exact_duplicate_candles_are_reconciled(self) -> None:
        ts = pd.Timestamp("2026-08-28 09:15:00", tz="Asia/Kolkata")
        frame = pd.DataFrame(
            {
                "timestamp": [ts, ts, ts + pd.Timedelta(minutes=1)],
                "open": [100.0, 100.0, 101.0],
                "high": [101.0, 101.0, 102.0],
                "low": [99.0, 99.0, 100.0],
                "close": [100.5, 100.5, 101.5],
                "volume": [1000, 1000, 1100],
                "security_id": ["1", "1", "1"],
            }
        )
        clean, removed = reconcile_duplicate_timestamps(frame)
        self.assertEqual(len(clean), 2)
        self.assertEqual(removed, 1)

    def test_conflicting_duplicate_candles_are_rejected(self) -> None:
        ts = pd.Timestamp("2026-08-28 09:15:00", tz="Asia/Kolkata")
        frame = pd.DataFrame(
            {
                "timestamp": [ts, ts],
                "open": [100.0, 100.5],
                "high": [101.0, 101.5],
                "low": [99.0, 99.5],
                "close": [100.5, 101.0],
                "volume": [1000, 1100],
                "security_id": ["1", "1"],
            }
        )
        with self.assertRaises(RuntimeError):
            reconcile_duplicate_timestamps(frame)


if __name__ == "__main__":
    unittest.main()
