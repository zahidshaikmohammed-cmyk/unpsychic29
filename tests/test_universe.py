from __future__ import annotations

import unittest

import pandas as pd

from src.build_universe import normalize_nifty500, resolve_against_dhan


class UniverseTests(unittest.TestCase):
    def setUp(self) -> None:
        import src.build_universe as module
        self.module = module
        self.old_min = module.MIN_EXPECTED_NIFTY500
        self.old_max = module.MAX_EXPECTED_NIFTY500
        module.MIN_EXPECTED_NIFTY500 = 2
        module.MAX_EXPECTED_NIFTY500 = 2

    def tearDown(self) -> None:
        self.module.MIN_EXPECTED_NIFTY500 = self.old_min
        self.module.MAX_EXPECTED_NIFTY500 = self.old_max

    def test_normalize_filters_non_eq(self) -> None:
        frame = pd.DataFrame(
            {
                "Company Name": ["Alpha", "Beta", "Gamma"],
                "Industry": ["X", "Y", "Z"],
                "Symbol": ["ALPHA", "BETA", "GAMMA"],
                "Series": ["EQ", "BE", "EQ"],
                "ISIN Code": ["A", "B", "C"],
            }
        )
        out = normalize_nifty500(frame)
        self.assertEqual(out["symbol"].tolist(), ["ALPHA", "GAMMA"])

    def test_resolution_is_one_to_one(self) -> None:
        nifty = pd.DataFrame(
            {
                "Company Name": ["Alpha", "Beta"],
                "Industry": ["X", "Y"],
                "Symbol": ["ALPHA", "BETA"],
                "Series": ["EQ", "EQ"],
                "ISIN Code": ["A", "B"],
            }
        )
        master = pd.DataFrame(
            {
                "SEM_EXM_EXCH_ID": ["NSE", "NSE"],
                "SEM_SEGMENT": ["E", "E"],
                "SEM_SMST_SECURITY_ID": ["101", "102"],
                "SEM_INSTRUMENT_NAME": ["EQUITY", "EQUITY"],
                "SEM_TRADING_SYMBOL": ["ALPHA", "BETA"],
            }
        )
        normalized = normalize_nifty500(nifty)
        resolved = resolve_against_dhan(normalized, master)
        self.assertEqual(resolved["security_id"].tolist(), ["101", "102"])

    def test_missing_dhan_symbol_is_rejected(self) -> None:
        nifty = pd.DataFrame(
            {
                "Company Name": ["Alpha", "Beta"],
                "Industry": ["X", "Y"],
                "Symbol": ["ALPHA", "BETA"],
                "Series": ["EQ", "EQ"],
                "ISIN Code": ["A", "B"],
            }
        )
        master = pd.DataFrame(
            {
                "SEM_EXM_EXCH_ID": ["NSE"],
                "SEM_SEGMENT": ["E"],
                "SEM_SMST_SECURITY_ID": ["101"],
                "SEM_INSTRUMENT_NAME": ["EQUITY"],
                "SEM_TRADING_SYMBOL": ["ALPHA"],
            }
        )
        normalized = normalize_nifty500(nifty)
        with self.assertRaises(RuntimeError):
            resolve_against_dhan(normalized, master)


if __name__ == "__main__":
    unittest.main()
