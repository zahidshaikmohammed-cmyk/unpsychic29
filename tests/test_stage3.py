from __future__ import annotations

import unittest

import pandas as pd

from src.stage3_acquire import load_universe, select_batch


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


if __name__ == "__main__":
    unittest.main()
