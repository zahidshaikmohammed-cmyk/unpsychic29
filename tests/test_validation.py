from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.dhan_historical import validate_frame


class ValidationTests(unittest.TestCase):
    def _write(self, frame: pd.DataFrame, root: Path) -> Path:
        path = root / "TEST.parquet"
        frame.to_parquet(path, index=False)
        return path

    def _base(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": pd.Series(pd.to_datetime(
                    ["2026-08-28 09:15:00+05:30", "2026-08-28 09:16:00+05:30"]
                )),
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [1000, 1100],
                "security_id": ["1", "1"],
            }
        )

    def test_regular_session_is_0915_inclusive_and_1530_exclusive(self) -> None:
        timestamps = pd.Series(pd.to_datetime([
            "2026-08-28 09:14:00+05:30",
            "2026-08-28 09:15:00+05:30",
            "2026-08-28 15:29:00+05:30",
            "2026-08-28 15:30:00+05:30",
        ]))
        minute = timestamps.dt.hour * 60 + timestamps.dt.minute
        regular = timestamps[(minute >= 9 * 60 + 15) & (minute < 15 * 60 + 30)]
        self.assertEqual(regular.tolist(), [
            pd.Timestamp("2026-08-28 09:15:00+05:30"),
            pd.Timestamp("2026-08-28 15:29:00+05:30"),
        ])

    def test_clean_frame_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_frame(self._write(self._base(), Path(tmp)))
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["failure_reasons"], [])
        self.assertEqual(report["warning_reasons"], [])

    def test_invalid_high_fails_without_relaxation(self) -> None:
        frame = self._base()
        frame.loc[0, "high"] = 98.0
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_frame(self._write(frame, Path(tmp)))
        self.assertEqual(report["status"], "CHECK")
        self.assertIn("invalid_high", report["failure_reasons"])
        self.assertGreater(report["invalid_high_rows"], 0)

    def test_out_of_session_is_quarantined_as_warning(self) -> None:
        timestamps = list(pd.date_range(
            "2026-08-28 09:15:00+05:30",
            "2026-08-28 15:29:00+05:30",
            freq="min",
        ))
        timestamps.append(pd.Timestamp("2026-08-28 15:31:00+05:30"))
        n = len(timestamps)
        frame = pd.DataFrame({
            "timestamp": timestamps,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000] * n,
            "security_id": ["1"] * n,
        })
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_frame(self._write(frame, Path(tmp)))
        self.assertEqual(report["status"], "OK")
        self.assertEqual(report["failure_reasons"], [])
        self.assertIn("out_of_session_rows_quarantined", report["warning_reasons"])
        self.assertEqual(report["out_of_session_rows"], 1)
        self.assertEqual(report["rows_after_session_filter"], 375)

    def test_excessive_out_of_session_data_fails(self) -> None:
        frame = pd.concat([self._base()] * 100, ignore_index=True)
        frame["timestamp"] = pd.date_range("2026-08-28 00:00:00+05:30", periods=len(frame), freq="min")
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_frame(self._write(frame, Path(tmp)))
        self.assertEqual(report["status"], "CHECK")
        self.assertIn("excessive_out_of_session_rows", report["failure_reasons"])

    def test_null_volume_fails(self) -> None:
        frame = self._base()
        frame.loc[0, "volume"] = None
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_frame(self._write(frame, Path(tmp)))
        self.assertEqual(report["status"], "CHECK")
        self.assertIn("null_volume", report["failure_reasons"])


if __name__ == "__main__":
    unittest.main()
