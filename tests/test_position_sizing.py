import unittest

import pandas as pd

from app.risk.position_sizing import compute_position_size
from tests.helpers import make_cfg


def size(entry, stop, regime="BULL", adv=50e9, pv=100_000_000):
    df = pd.DataFrame({"market_regime": [regime], "avg_value20": [adv]})
    return compute_position_size(df, pd.DataFrame({"entry_ideal": [entry]}), pd.DataFrame({"stop_loss": [stop]}), make_cfg(), pv).iloc[0]


class TestPositionSizing(unittest.TestCase):
    def test_risk_based(self):
        s = size(1000, 950)  # 1% x 100jt = 1jt / 50 = 20.000 lembar, tapi max 20% portofolio = 20.000 lembar
        self.assertEqual(s["position_size"], 20000)
        self.assertLessEqual(s["risk_amount"], 1_000_000 + 1e-6)
        self.assertAlmostEqual(s["capital_required"], 20000 * 1000)
        self.assertAlmostEqual(s["estimated_loss"], 20000 * 50)

    def test_regime_reduces_size(self):
        self.assertGreater(size(1000, 900)["position_size"], size(1000, 900, "STRONG_BEAR")["position_size"])

    def test_liquidity_cap(self):
        self.assertLessEqual(size(500, 480, adv=1e8, pv=1e9)["capital_required"], 0.05 * 1e8 + 1)


if __name__ == "__main__":
    unittest.main()
