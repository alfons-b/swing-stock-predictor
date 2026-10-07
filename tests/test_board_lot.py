import unittest

import numpy as np

from app.utils.idx_rules import round_to_tick, shares_to_lots, tick_size
from tests.test_position_sizing import size


class TestBoardLot(unittest.TestCase):
    def test_position_multiple_of_lot(self):
        for e, s in ((1234, 1180), (87, 80), (5125, 4900), (312, 296)):
            r = size(e, s)
            self.assertEqual(r["position_size"] % 100, 0)
            self.assertEqual(r["lots"] if "lots" in r else r["position_lots"], r["position_size"] // 100)

    def test_tick_size_rules(self):
        self.assertEqual([tick_size(p) for p in (150, 350, 1250, 3000, 9000)], [1, 2, 5, 10, 25])
        for p in np.random.default_rng(0).uniform(50, 20000, 300):
            for mode in ("down", "up", "nearest"):
                v = round_to_tick(p, mode)
                self.assertEqual(v % tick_size(v), 0)
        self.assertEqual(shares_to_lots(1999), 19)


if __name__ == "__main__":
    unittest.main()
