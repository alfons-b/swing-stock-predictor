import unittest

import numpy as np
import pandas as pd

from app.features import indicators as ind
from app.features.builder import build_features, feature_columns
from tests.test_no_data_leakage import load_market


class TestIndicators(unittest.TestCase):
    def test_basic_indicators(self):
        s = pd.Series(np.arange(1, 61, dtype=float))
        self.assertAlmostEqual(ind.sma(s, 5).iloc[-1], 58.0)
        self.assertTrue(np.isnan(ind.sma(s, 5).iloc[3]))
        self.assertEqual(ind.rsi(s, 14).iloc[-1], 100.0)        # naik terus → RSI 100
        h, l, c = s + 1, s - 1, s
        self.assertAlmostEqual(ind.atr(h, l, c, 14).iloc[-1], 2.0, places=6)

    def test_feature_set(self):
        cfg = __import__("tests.helpers", fromlist=["x"]).make_cfg()
        df = build_features(load_market(cfg), cfg)
        f = feature_columns(df)
        for name in ("f_dist_sma200", "f_rsi14", "f_adx", "f_macd_hist_slope", "f_atr_pct", "f_volume_ratio", "f_rs20",
                     "f_rs_sector20", "f_regime_score", "f_sector_score", "f_ret60", "f_bb_width"):
            self.assertIn(name, f)
        for raw in ("sma5", "sma100", "ema9", "res20", "higher_high", "lower_low", "obv" if "obv" in df else "f_obv_slope"):
            self.assertIn(raw, df.columns)
        self.assertTrue(set(df["market_regime"]) <= {"STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "STRONG_BEAR"})


if __name__ == "__main__":
    unittest.main()
