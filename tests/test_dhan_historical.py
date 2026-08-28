from __future__ import annotations

import unittest

from src.dhan_historical import date_chunks, response_to_frame


class DhanHistoricalTests(unittest.TestCase):
    def test_date_chunks_are_contiguous_and_end_exclusive(self) -> None:
        chunks = list(date_chunks(__import__("datetime").date(2026, 1, 1), __import__("datetime").date(2026, 2, 1), 20))
        self.assertEqual(chunks[0][0].isoformat(), "2026-01-01")
        self.assertEqual(chunks[-1][1].isoformat(), "2026-02-01")
        for previous, current in zip(chunks, chunks[1:]):
            self.assertEqual(previous[1], current[0])

    def test_response_to_frame_preserves_one_row_per_timestamp(self) -> None:
        body = {
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.5, 100.5],
            "close": [100.5, 101.5],
            "volume": [1000, 1200],
            "timestamp": [1770000000, 1770000060],
        }
        frame = response_to_frame(body, "123")
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["security_id"].tolist(), ["123", "123"])
        self.assertTrue(frame["timestamp"].is_monotonic_increasing)

    def test_mismatched_arrays_are_rejected(self) -> None:
        body = {
            "open": [100.0],
            "high": [101.0, 102.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1000],
            "timestamp": [1770000000],
        }
        with self.assertRaises(RuntimeError):
            response_to_frame(body, "123")


if __name__ == "__main__":
    unittest.main()
