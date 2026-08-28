from __future__ import annotations

import unittest

import pandas as pd

from src.research_metrics import daily_features


class ResearchMetricTests(unittest.TestCase):
    def _day(self, missing_opening_minute: bool = False) -> pd.DataFrame:
        ts = pd.date_range(
            "2026-08-28 09:15:00+05:30",
            "2026-08-28 15:29:00+05:30",
            freq="min",
        )
        if missing_opening_minute:
            ts = ts[ts != pd.Timestamp("2026-08-28 09:18:00+05:30")]
        n = len(ts)
        return pd.DataFrame(
            {
                "symbol": ["TEST"] * n,
                "timestamp": ts,
                "open": [100.0 + i * 0.01 for i in range(n)],
                "high": [100.1 + i * 0.01 for i in range(n)],
                "low": [99.9 + i * 0.01 for i in range(n)],
                "close": [100.05 + i * 0.01 for i in range(n)],
                "volume": [1000] * n,
            }
        )

    def test_complete_first_ten_minutes_are_used(self) -> None:
        features = daily_features(self._day())
        self.assertEqual(len(features), 1)
        self.assertEqual(bool(features.iloc[0]["opening10_complete"]), True)
        self.assertEqual(float(features.iloc[0]["first10_volume"]), 10000.0)

    def test_missing_opening_minute_is_not_compressed_into_first_ten(self) -> None:
        features = daily_features(self._day(missing_opening_minute=True))
        self.assertTrue(features.empty)


if __name__ == "__main__":
    unittest.main()
