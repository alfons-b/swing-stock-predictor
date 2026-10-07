"""Incremental ingestion (§10), failure recovery (§52), kalender (§24), freshness (§23)."""
import unittest

import pandas as pd

from app.data.ingestion import run_ingestion, validate_new_rows
from app.data.universe import UniverseManager
from app.market.calendar import TradingCalendar
from app.pipeline.freshness import data_freshness
from tests.helpers import make_cfg, make_ctx


def ingest(cfg, ctx=None):
    ctx = ctx or make_ctx(cfg)
    ctx.cfg = cfg
    ctx._chain = ctx._calendar = None
    UniverseManager(cfg, ctx.repo, ctx.chain).update()
    return ctx, run_ingestion(cfg, ctx.repo, ctx.chain, ctx.calendar)


class TestIncremental(unittest.TestCase):
    def test_downloads_only_missing_and_is_idempotent(self):
        cfg = make_cfg(as_of="2019-06-28")
        ctx, st1 = ingest(cfg)
        n1 = ctx.repo.price_counts()
        self.assertEqual(str(ctx.repo.max_price_date().date()), "2019-06-28")
        self.assertGreater(st1.rows_inserted, 1000)
        # hari berikutnya: hanya 1 hari bursa baru per emiten aktif
        cfg2 = dict(cfg, _as_of="2019-07-01")
        ctx, st2 = ingest(cfg2, ctx)
        n_active = int(ctx.db.scalar("SELECT COUNT(*) FROM stocks WHERE is_active = ?", (True,)))
        self.assertLessEqual(st2.rows_inserted, n_active)
        self.assertGreater(st2.rows_inserted, 0)
        self.assertEqual(st2.rows_updated, 0)                     # tidak mengunduh ulang histori
        # dijalankan ulang di hari yang sama → tidak ada yang diunduh, tidak ada duplikat
        ctx, st3 = ingest(cfg2, ctx)
        self.assertEqual((st3.rows_inserted, st3.stocks_requested), (0, 0))
        c = ctx.repo.price_counts()
        self.assertEqual(c["duplicates"], 0)
        self.assertEqual(c["rows"], n1["rows"] + st2.rows_inserted)

    def test_catch_up_after_missed_runs(self):
        cfg = make_cfg(as_of="2019-06-03")
        ctx, _ = ingest(cfg)
        # pipeline gagal/tidak jalan selama 2 minggu → run berikutnya mengejar semua hari yang hilang
        ctx, st = ingest(dict(cfg, _as_of="2019-06-17"), ctx)
        self.assertEqual(str(ctx.repo.max_price_date().date()), "2019-06-17")
        self.assertEqual(ctx.repo.price_counts()["duplicates"], 0)
        self.assertGreater(st.rows_inserted, 5 * 9)

    def test_delisted_history_is_kept(self):
        cfg = make_cfg(as_of="2020-12-31")
        ctx, _ = ingest(cfg)
        row = ctx.db.query("SELECT s.is_active, COUNT(p.id) FROM stocks s LEFT JOIN price_history p ON p.stock_id = s.id "
                           "WHERE s.ticker = 'ZDEL' GROUP BY s.is_active")[0]
        self.assertFalse(bool(row[0]))
        self.assertGreater(row[1], 100)  # histori emiten delisting tetap ada (anti survivorship bias)

    def test_validate_new_rows(self):
        df = pd.DataFrame({"ticker": "A", "date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-04"]),
                           "open": [10, 10, -1, 10], "high": [11, 11, 11, 9], "low": [9, 9, 9, 10], "close": [10, 10, 10, None],
                           "volume": [1, 1, 1, 1]})
        clean, rejected = validate_new_rows(df)
        self.assertEqual((len(clean), rejected), (1, 3))


class TestCalendarFreshness(unittest.TestCase):
    def test_expected_market_date(self):
        cal = TradingCalendar(make_cfg())
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Jakarta")
        self.assertEqual(cal.expected_latest_market_date(datetime(2026, 10, 4, 12, tzinfo=tz)), pd.Timestamp("2026-10-02"))  # Minggu
        self.assertEqual(cal.expected_latest_market_date(datetime(2026, 10, 5, 10, tzinfo=tz)), pd.Timestamp("2026-10-02"))  # Senin pagi
        self.assertEqual(cal.expected_latest_market_date(datetime(2026, 10, 5, 19, tzinfo=tz)), pd.Timestamp("2026-10-05"))  # Senin malam

    def test_learns_holidays_from_index(self):
        days = [d for d in pd.bdate_range("2024-12-23", "2024-12-31") if d != pd.Timestamp("2024-12-25")]
        cal = TradingCalendar(make_cfg(), days)
        self.assertFalse(cal.is_trading_day("2024-12-25"))
        self.assertEqual(cal.previous_trading_day("2024-12-26"), pd.Timestamp("2024-12-24"))

    def test_freshness_statuses(self):
        cfg = make_cfg(as_of="2019-06-28")
        ctx, _ = ingest(cfg)
        self.assertEqual(data_freshness(cfg, ctx.repo, ctx.calendar)["status"], "UP_TO_DATE")
        later = dict(cfg, _as_of="2019-07-02")
        cal = TradingCalendar(later, ctx.repo.index_dates("COMPOSITE"))
        f = data_freshness(later, ctx.repo, cal)
        self.assertEqual((f["status"], f["lag_trading_days"], f["trading_allowed"]), ("UPDATE_REQUIRED", 2, True))
        cal = TradingCalendar(dict(cfg, _as_of="2019-07-15"), ctx.repo.index_dates("COMPOSITE"))
        f = data_freshness(cfg, ctx.repo, cal)
        self.assertEqual((f["status"], f["trading_allowed"]), ("STALE", False))


if __name__ == "__main__":
    unittest.main()
