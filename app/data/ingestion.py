"""Incremental ingestion (§10, §52).

DB latest date (per ticker) → expected market date → unduh HANYA yang hilang → validasi → UPSERT.
Tidak mengasumsikan run sebelumnya berhasil: titik awal selalu dihitung dari isi database, sehingga
run yang terlewat/gagal otomatis di-catch-up pada run berikutnya.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.config import get
from app.data.providers.chain import ProviderChain
from app.database.repository import Repository
from app.market.calendar import TradingCalendar
from app.utils.logging_utils import get_logger

log = get_logger(__name__)


@dataclass
class IngestStats:
    expected_date: str = ""
    index_rows: int = 0
    stocks_requested: int = 0
    stocks_up_to_date: int = 0
    stocks_processed: int = 0
    stocks_failed: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_rejected: int = 0
    refetched: list = field(default_factory=list)
    failed: dict = field(default_factory=dict)
    provider_stats: dict = field(default_factory=dict)
    actions_inserted: int = 0

    def as_dict(self):
        d = self.__dict__.copy()
        d["failed"] = dict(list(self.failed.items())[:50])
        return d


def validate_new_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Validasi batch baru sebelum masuk DB: duplikat, missing, OHLC tidak valid, volume negatif."""
    n0 = len(df)
    d = df.drop_duplicates(["ticker", "date"], keep="last").dropna(subset=["open", "high", "low", "close", "volume"])
    bad = (d[["open", "high", "low", "close"]] <= 0).any(axis=1) | (d["high"] < d["low"]) | (d["volume"] < 0)
    d = d[~bad].copy()
    d["high"] = d[["open", "high", "low", "close"]].max(axis=1)
    d["low"] = d[["open", "high", "low", "close"]].min(axis=1)
    return d, n0 - len(d)


def initial_start(cfg: dict, cal: TradingCalendar) -> pd.Timestamp:
    s = get(cfg, "data.start_date")
    if s:
        return pd.Timestamp(s)
    return pd.Timestamp(cal.now().date()) - pd.DateOffset(years=int(get(cfg, "data.initial_history_years", 10)))


def ingest_index(cfg, repo: Repository, chain: ProviderChain, cal: TradingCalendar, expected) -> int:
    sym = get(cfg, "data.index_id", "COMPOSITE")
    last = repo.max_index_date(sym)
    if last is not None and last >= expected:
        return 0
    start = last + pd.Timedelta(days=1) if last is not None else initial_start(cfg, cal)
    df, src = chain.fetch_index(start, expected)
    df = df[(df["date"] >= start) & (df["date"] <= expected)].dropna(subset=["close"])
    df = df[df["close"] > 0]
    ins, _ = repo.upsert_index(df, sym, src)
    log.info("IHSG: %d baris baru (%s) dari %s", ins, f"{start.date()}..{expected.date()}", src)
    return ins


def ingest_prices(cfg, repo: Repository, chain: ProviderChain, cal: TradingCalendar, expected,
                  tickers: list[str] | None = None) -> IngestStats:
    st = IngestStats(expected_date=str(pd.Timestamp(expected).date()))
    latest = repo.latest_price_dates().set_index("ticker")
    allst = repo.stocks()
    # Emiten aktif + emiten NONAKTIF yang belum punya histori (backfill s/d tanggal delisting).
    # Tanpa ini, saham yang sudah delisting tidak pernah masuk → survivorship bias di backtest.
    no_hist = allst["ticker"].map(lambda t: (latest.at[t, "n_rows"] if t in latest.index else 0) == 0)
    stocks = allst[allst["is_active"] | (no_hist & allst["delisting_date"].notna())]
    if tickers:
        stocks = stocks[stocks["ticker"].isin(tickers)]
    end_for = {r.ticker: min(pd.Timestamp(expected), pd.Timestamp(r.delisting_date)) if pd.notna(r.delisting_date) else pd.Timestamp(expected)
               for r in stocks.itertuples()}
    overlap = int(get(cfg, "data.overlap_days", 0))
    first = initial_start(cfg, cal)
    requests, last_close = {}, {}
    for t in stocks["ticker"]:
        last = latest.at[t, "last_date"] if t in latest.index else pd.NaT
        if pd.notna(last) and pd.Timestamp(last) >= end_for[t]:
            st.stocks_up_to_date += 1
            continue
        start = (pd.Timestamp(last) + pd.Timedelta(days=1) - pd.Timedelta(days=overlap)) if pd.notna(last) else first
        requests[t] = start
    st.stocks_requested = len(requests)
    if not requests:
        log.info("Semua %d emiten aktif sudah up-to-date (%s)", st.stocks_up_to_date, st.expected_date)
        return st
    # harga penutupan terakhir di DB → deteksi split yang belum tercatat
    if latest["n_rows"].fillna(0).sum() > 0:
        lc = repo.db.query_df("SELECT s.ticker, p.close FROM price_history p JOIN stocks s ON s.id = p.stock_id "
                              "JOIN (SELECT stock_id, MAX(date) AS d FROM price_history GROUP BY stock_id) m "
                              "ON m.stock_id = p.stock_id AND m.d = p.date")
        last_close = dict(zip(lc["ticker"], pd.to_numeric(lc["close"])))
    log.info("Mengunduh data hilang untuk %d emiten (s/d %s)", len(requests), st.expected_date)
    res = chain.fetch_prices(requests, expected)
    st.provider_stats = res.provider_stats
    ids = repo.stock_ids()
    max_jump = float(get(cfg, "quality.max_abs_daily_return", 0.35))
    for t, f in res.frames.items():
        try:
            f = f[(f["date"] >= requests[t]) & (f["date"] <= end_for[t])]
            f, rejected = validate_new_rows(f)
            st.rows_rejected += rejected
            if f.empty:
                continue
            prev = last_close.get(t)
            first_close = f.sort_values("date")["close"].iloc[0]
            if prev and res.adjusted.get(t) and get(cfg, "data.refetch_on_split", True) and \
                    abs(first_close / prev - 1) > max_jump:
                # provider split-adjusted + lonjakan tak wajar → skala histori berubah: unduh ulang penuh
                full = chain.fetch_prices({t: first}, expected)
                if t in full.frames:
                    f, rej = validate_new_rows(full.frames[t])
                    st.rows_rejected += rej
                    repo.delete_prices(ids[t])
                    st.refetched.append(t)
                    log.warning("%s: lonjakan %.0f%% vs close terakhir → histori diunduh ulang (kemungkinan split)",
                                t, (first_close / prev - 1) * 100)
            rows = f.assign(stock_id=ids[t], is_adjusted=bool(res.adjusted.get(t)), source=res.sources[t])
            ins, upd = repo.upsert_prices(rows)
            st.rows_inserted += ins
            st.rows_updated += upd
            st.stocks_processed += 1
        except Exception as e:  # satu ticker gagal tidak membatalkan pipeline
            res.failed[t] = f"upsert: {type(e).__name__}: {e}"[:300]
    no_data = {t: m for t, m in res.failed.items() if t not in res.frames}
    # "tidak ada data baru" untuk ticker yang mungkin suspensi bukan kegagalan teknis
    st.failed = {t: m for t, m in no_data.items() if "tidak ada data baru" not in m}
    st.stocks_failed = len(st.failed)
    for prov in chain.providers:
        s = res.provider_stats.get(prov.name)
        if s:
            repo.source_status(prov.name, prov.type, prov.priority, True, ok=s["errors"] == 0 or s["ok"] > 0,
                               error=None if s["errors"] == 0 else f"{s['errors']} batch error", rows=s["rows"])
    return st


def ingest_actions(cfg, repo: Repository, chain: ProviderChain, tickers: list[str], start=None, end=None) -> int:
    ids = repo.stock_ids()
    total = 0
    for t in tickers:
        try:
            a = chain.fetch_actions(t, start, end)
        except Exception:
            continue
        if a is None or a.empty:
            continue
        a = a.assign(stock_id=ids[t], source="provider")
        ins, _ = repo.upsert_actions(a)
        total += ins
    return total


def suspected_action_tickers(repo: Repository, since) -> list[str]:
    """Ticker dengan lonjakan harga harian > 25% sejak `since` → cek corporate action."""
    df = repo.load_prices(start=pd.Timestamp(since) - pd.Timedelta(days=10))
    if df.empty:
        return []
    r = df.groupby("ticker")["close"].pct_change().abs()
    return sorted(df.loc[(r > 0.25) & (df["date"] >= pd.Timestamp(since)), "ticker"].unique().tolist())


def run_ingestion(cfg, repo: Repository, chain: ProviderChain, cal: TradingCalendar,
                  full_actions: bool = False) -> IngestStats:
    expected = cal.expected_latest_market_date()
    st_index = ingest_index(cfg, repo, chain, cal, expected)
    cal.learn_from_trading_days(repo.index_dates(get(cfg, "data.index_id", "COMPOSITE")))
    expected = cal.expected_latest_market_date()  # setelah belajar hari libur dari IHSG
    before = repo.max_price_date()
    st = ingest_prices(cfg, repo, chain, cal, expected)
    st.index_rows = st_index
    active = repo.stocks(active_only=True)["ticker"].tolist()
    if full_actions or before is None:
        targets = active
    else:
        targets = suspected_action_tickers(repo, before)
    st.actions_inserted = ingest_actions(cfg, repo, chain, targets)
    return st
