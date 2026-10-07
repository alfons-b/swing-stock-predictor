"""Engine backtest diuji dengan skenario harga buatan tangan → hasil bisa dihitung manual."""
import unittest

import numpy as np
import pandas as pd

from app.backtest.engine import BacktestEngine
from app.backtest.metrics import compute_metrics
from app.backtest.walk_forward import make_folds
from tests.helpers import make_cfg


def _cfg(**kw):
    cfg = make_cfg()
    cfg["backtest"].update({"TRANSACTION_FEE_BUY": 0.0015, "TRANSACTION_FEE_SELL": 0.0025, "SLIPPAGE_BPS": 0})
    cfg["strategy"]["max_holding_days"] = 10
    for k, v in kw.items():
        sec, key = k.split("__")
        cfg[sec][key] = v
    return cfg


def _bars(rows):
    d = pd.bdate_range("2024-01-01", periods=len(rows))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["date"], df["ticker"], df["is_suspended"] = d, "AAAA", False
    return df


SIG = {"ticker": "AAAA", "market_regime": "BULL", "setup_type": "BREAKOUT", "entry_low": 990.0, "entry_ideal": 1000.0,
       "entry_high": 1010.0, "stop_loss": 950.0, "take_profit_1": 1075.0, "take_profit_2": 1125.0, "avg_value20": 1e12}


class TestEngine(unittest.TestCase):
    def run_case(self, rows, **kw):
        bars = _bars(rows)
        sig = pd.DataFrame([{**SIG, "date": bars["date"].iloc[0]}])
        return BacktestEngine(_cfg(**kw)).run(sig, bars)

    def test_gap_down_through_stop_exits_at_open(self):
        r = self.run_case([(1000, 1005, 995, 1000), (1000, 1005, 998, 1002), (930, 940, 920, 925), (925, 930, 920, 925)])
        t = r["trades"].iloc[0]
        self.assertEqual(t["exit_reason"], "STOP")
        self.assertEqual(t["avg_exit_price"], 930.0)  # bukan 950: gap down dihitung penuh
        self.assertLess(t["r_multiple"], -1.0)

    def test_partial_tp_then_breakeven(self):
        r = self.run_case([(1000, 1005, 995, 1000), (1000, 1005, 998, 1002), (1010, 1080, 1005, 1070),
                           (1060, 1065, 990, 995), (995, 1000, 990, 995)])
        t = r["trades"].iloc[0]
        self.assertEqual(t["exit_reason"], "TP1+BREAKEVEN_STOP")
        self.assertGreater(t["net_pnl"], 0)

    def test_fees_applied(self):
        r = self.run_case([(1000, 1005, 995, 1000), (1000, 1005, 998, 1000)] + [(1000, 1005, 995, 1000)] * 12)
        t = r["trades"].iloc[0]
        self.assertEqual(t["exit_reason"], "TIME_EXIT")
        expected = t["shares"] * 1000 * (1 - 0.0025) - t["shares"] * 1000 * (1 + 0.0015)
        self.assertAlmostEqual(t["net_pnl"], expected, places=4)

    def test_same_bar_stop_first(self):
        r = self.run_case([(1000, 1005, 995, 1000), (1000, 1005, 998, 1002), (1000, 1200, 900, 1100), (1100, 1100, 1100, 1100)])
        self.assertEqual(r["trades"].iloc[0]["exit_reason"], "STOP")

    def test_no_fill_if_price_runs_away(self):
        r = self.run_case([(1000, 1005, 995, 1000), (1050, 1100, 1040, 1090), (1090, 1100, 1080, 1090)])
        self.assertEqual(len(r["trades"]), 0)

    def test_lot_size(self):
        r = self.run_case([(1000, 1005, 995, 1000), (1000, 1005, 998, 1002), (930, 940, 920, 925)])
        self.assertEqual(r["trades"].iloc[0]["shares"] % 100, 0)

    def test_metrics_drawdown(self):
        eq = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=4), "equity": [100, 120, 90, 110], "exposure": 0.5})
        m = compute_metrics(eq, pd.DataFrame(), 100)
        self.assertAlmostEqual(m["max_drawdown"], 90 / 120 - 1)


class TestWalkForward(unittest.TestCase):
    def test_rolling_embargo_and_order(self):
        cfg = _cfg()
        cfg["split"].update({"test_months": 6, "validation_folds": 4, "fold_months": 6})
        dates = pd.Series(pd.bdate_range("2016-01-01", "2026-09-30"))
        folds = make_folds(dates, cfg)
        self.assertEqual([f.kind for f in folds], ["validation"] * 4 + ["test"])
        for f in folds:
            self.assertLess(f.train_end, f.eval_start)
            self.assertGreaterEqual(((dates > f.train_end) & (dates < f.eval_start)).sum(), max(cfg["labels"]["HORIZONS"]))
        for f in folds[:-1]:
            self.assertLess(f.eval_end, folds[-1].eval_start, "validasi tidak boleh menyentuh test")


class TestConsistency(unittest.TestCase):
    def test_prediction_columns_match_model_output(self):
        """Regresi: backtest wajib meneruskan semua kolom yang dihasilkan SwingModel.predict ke pipeline sinyal."""
        from app.backtest.runner import prediction_columns
        cols = ["probability_bearish", "probability_neutral", "probability_bullish", "prob_dispersion", "base_rate_bullish",
                "expected_return_5d", "prob_hit_tp", "y_class", "ticker"]
        out = prediction_columns(pd.DataFrame(columns=cols))
        self.assertIn("base_rate_bullish", out)
        self.assertNotIn("y_class", out)
