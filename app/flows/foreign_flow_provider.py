"""ForeignFlowProvider + ingest incremental ke `foreign_flow_history`.

Fakta sumber data (diverifikasi): BEI mempublikasikan foreign buy/sell harian per emiten dalam LEMBAR di
"Ringkasan Saham" (idx.co.id → Data Pasar → Ringkasan Perdagangan → Ringkasan Saham). Situs BEI memblokir akses
otomatis dari IP datacenter (GitHub Actions) dan tidak menyediakan API publik resmi. Karena itu urutan sumber:

1. IDXStockSummaryFileProvider — file Ringkasan Saham (.xlsx/.csv) yang Anda unduh manual, satu file per hari,
   disimpan di data/raw/foreign_flow (bisa di-commit ke repo privat atau diunggah ke bucket). Tanggal diambil dari
   nama file (YYYYMMDD / YYYY-MM-DD) — kolom "Tanggal Perdagangan Terakhir" BUKAN tanggal file (emiten yang tidak
   diperdagangkan menampilkan tanggal transaksi terakhirnya).
2. CSVForeignFlowProvider — CSV kanonik dari vendor/ekspor lain.
3. HTTPForeignFlowProvider — API JSON pihak ketiga berlisensi (URL + API key dari GitHub Secrets).
4. IDXEndpointProvider — sengaja TIDAK mengambil data: ketentuan situs & blokir datacenter. Selalu DISABLED.

Tanpa sumber AVAILABLE → status FOREIGN_FLOW_UNAVAILABLE (bukan nol).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.config import get, resolve_path
from app.database.repository import Repository, now_utc
from app.flows.flow_normalizer import CANON, normalize
from app.utils.logging_utils import get_logger

log = get_logger(__name__)
_DATE_IN_NAME = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


class ForeignFlowProvider:
    name = "base"

    def __init__(self, entry: dict, cfg: dict):
        self.entry, self.cfg = entry, cfg
        self.name = entry.get("name", self.name)
        self.priority = int(entry.get("priority", 50))

    def availability(self) -> tuple[str, str]:
        return "AVAILABLE", ""

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Data kanonik (lihat flow_normalizer.CANON) untuk start ≤ date ≤ end."""
        raise NotImplementedError


def file_date(path: Path) -> pd.Timestamp | None:
    m = _DATE_IN_NAME.search(path.stem)
    if not m:
        return None
    try:
        return pd.Timestamp(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    except ValueError:
        return None


class IDXStockSummaryFileProvider(ForeignFlowProvider):
    name = "idx_stock_summary_file"

    def __init__(self, entry, cfg):
        super().__init__(entry, cfg)
        self.dir = resolve_path(cfg, str(entry.get("dir", "data/raw/foreign_flow")))

    def _files(self):
        if not self.dir.exists():
            return []
        return sorted(p for p in self.dir.iterdir() if p.suffix.lower() in (".xlsx", ".csv") and not p.name.startswith("~"))

    def availability(self):
        files = self._files()
        if not files:
            return "NOT_CONFIGURED", f"tidak ada file Ringkasan Saham di {self.dir}"
        undated = [p.name for p in files if file_date(p) is None]
        if undated:
            return "AVAILABLE", f"{len(files)} file; {len(undated)} tanpa tanggal di nama file (dilewati): {undated[:3]}"
        return "AVAILABLE", f"{len(files)} file"

    @staticmethod
    def read_file(path: Path) -> pd.DataFrame:
        from app.data.universe_file import read_table
        return read_table(path)

    def fetch(self, start, end):
        frames = []
        for p in self._files():
            d = file_date(p)
            if d is None or not (pd.Timestamp(start) <= d <= pd.Timestamp(end)):
                continue
            try:
                raw = self.read_file(p)
            except Exception as e:
                log.warning("Ringkasan Saham %s tidak terbaca: %s", p.name, e)
                continue
            raw = raw.copy()
            raw["date"] = d
            raw["market_segment"] = "TOTAL"
            norm = normalize(raw, self.name)
            norm["source_timestamp"] = d.strftime("%Y-%m-%d")
            frames.append(norm)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CANON)


class CSVForeignFlowProvider(ForeignFlowProvider):
    name = "csv_foreign_flow"

    def __init__(self, entry, cfg):
        super().__init__(entry, cfg)
        self.dir = resolve_path(cfg, str(entry.get("dir", "data/raw/foreign_flow_csv")))

    def _files(self):
        return sorted(self.dir.glob("*.csv")) if self.dir.exists() else []

    def availability(self):
        return ("AVAILABLE", f"{len(self._files())} file") if self._files() else \
            ("NOT_CONFIGURED", f"tidak ada CSV di {self.dir}")

    def fetch(self, start, end):
        frames = [normalize(pd.read_csv(p), self.name) for p in self._files()]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CANON)
        return df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]


class HTTPForeignFlowProvider(ForeignFlowProvider):
    """API JSON berlisensi: GET {url}?date=YYYY-MM-DD, header Authorization: Bearer <api_key>.

    Respons: list record dengan kolom yang dikenali flow_normalizer (ticker, foreign_buy_shares, ...).
    Sesuaikan `_get` dengan kontrak vendor Anda. Kredensial hanya dari environment/GitHub Secrets.
    """
    name = "http_foreign_flow"

    def availability(self):
        if not self.entry.get("url") or not self.entry.get("api_key"):
            return "NOT_CONFIGURED", "FOREIGN_FLOW_API_URL / FOREIGN_FLOW_API_KEY belum diisi (GitHub Secrets)"
        return "AVAILABLE", "API pihak ketiga"

    def _get(self, day: pd.Timestamp) -> list[dict]:
        import requests
        r = requests.get(self.entry["url"], params={"date": day.strftime("%Y-%m-%d")},
                         headers={"Authorization": f"Bearer {self.entry['api_key']}"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("data", data) if isinstance(data, dict) else data

    def fetch(self, start, end):
        frames = []
        for day in pd.bdate_range(start, end):
            recs = self._get(day)
            if recs:
                df = pd.DataFrame(recs)
                df["date"] = df.get("date", day)
                frames.append(normalize(df, self.name))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CANON)


class IDXEndpointProvider(ForeignFlowProvider):
    name = "idx_endpoint"

    def availability(self):
        return "DISABLED", ("Pengambilan otomatis dari situs BEI tidak diimplementasikan: IP datacenter diblokir dan "
                            "ketentuan situs tidak mengizinkan pengambilan massal. Pakai file Ringkasan Saham / vendor.")

    def fetch(self, start, end):
        return pd.DataFrame(columns=CANON)


CLASSES = {"idx_file": IDXStockSummaryFileProvider, "csv": CSVForeignFlowProvider, "http": HTTPForeignFlowProvider,
           "idx_endpoint": IDXEndpointProvider}


def make_flow_providers(cfg: dict) -> list[ForeignFlowProvider]:
    out = []
    for e in get(cfg, "foreign_flow.providers", []) or []:
        cls = CLASSES.get(e.get("type"))
        if cls is None:
            continue
        p = cls(e, cfg)
        p.enabled = str(e.get("enabled", True)).lower() in ("true", "1", "yes")
        out.append(p)
    return sorted(out, key=lambda p: p.priority)


FLOW_COLS = [c for c in CANON if c != "ticker"] + ["stock_id", "retrieved_at"]


def store_flows(repo: Repository, df: pd.DataFrame) -> int:
    if df is None or df.empty:
        return 0
    ids = repo.stock_ids()
    d = df.copy()
    d["stock_id"] = d["ticker"].map(ids)
    unknown = d["stock_id"].isna().sum()
    if unknown:
        log.debug("foreign flow: %d baris untuk emiten di luar universe dilewati", unknown)
    d = d.dropna(subset=["stock_id"])
    d["stock_id"] = d["stock_id"].astype(int)
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d["retrieved_at"] = now_utc()
    repo.db.upsert("foreign_flow_history", d.reindex(columns=FLOW_COLS), keys=["stock_id", "date", "market_segment"],
                   count=False)
    return len(d)


def update_foreign_flow(cfg: dict, repo: Repository, today, lookback_days: int = 10, full: bool = False) -> dict:
    """Incremental: ambil dari tanggal terakhir tersimpan − lookback (koreksi data) s.d. hari ini."""
    today = pd.Timestamp(today).normalize()
    stats = {"providers": {}, "rows": 0, "status": "FOREIGN_FLOW_UNAVAILABLE"}
    if not get(cfg, "foreign_flow.enabled", True):
        stats["status"] = "DISABLED"
        return stats
    last = repo.db.scalar("SELECT MAX(date) FROM foreign_flow_history")
    start = pd.Timestamp("2000-01-01") if (full or not last) else pd.Timestamp(last) - pd.Timedelta(days=lookback_days)
    for p in make_flow_providers(cfg):
        status, detail = p.availability() if getattr(p, "enabled", True) else ("DISABLED", "enabled: false")
        stats["providers"][p.name] = {"status": status, "detail": detail}
        repo.set_source_availability(p.name, "foreign_flow", status, detail, p.priority)
        if status != "AVAILABLE":
            continue
        try:
            df = p.fetch(start, today)
        except Exception as e:
            stats["providers"][p.name] = {"status": "ERROR", "detail": str(e)[:300]}
            repo.set_source_availability(p.name, "foreign_flow", "ERROR", str(e), p.priority)
            log.warning("foreign flow %s gagal: %s", p.name, e)
            continue
        n = store_flows(repo, df)
        stats["rows"] += n
        stats["providers"][p.name]["rows"] = n
    if repo.db.scalar("SELECT COUNT(*) FROM foreign_flow_history WHERE date >= ?",
                      ((today - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),)):
        stats["status"] = "AVAILABLE"
    elif repo.db.scalar("SELECT COUNT(*) FROM foreign_flow_history"):
        stats["status"] = "STALE"
    log.info("Foreign flow: %s (%d baris baru/diperbarui)", stats["status"], stats["rows"], extra={"persist": True})
    return stats


def load_flows(repo: Repository, start=None, end=None, segment: str | None = None) -> pd.DataFrame:
    sql = ("SELECT s.ticker, f.date, f.market_segment, f.foreign_buy_shares, f.foreign_sell_shares, f.net_foreign_shares, "
           "f.foreign_buy_value, f.foreign_sell_value, f.net_foreign_value, f.value_type, f.total_volume_shares, "
           "f.quality_status, f.source FROM foreign_flow_history f JOIN stocks s ON s.id = f.stock_id WHERE 1=1")
    params = []
    if start is not None:
        sql += " AND f.date >= ?"
        params.append(pd.Timestamp(start).strftime("%Y-%m-%d"))
    if end is not None:
        sql += " AND f.date <= ?"
        params.append(pd.Timestamp(end).strftime("%Y-%m-%d"))
    if segment:
        sql += " AND f.market_segment = ?"
        params.append(segment)
    df = repo.db.query_df(sql, params, parse_dates=["date"])
    for c in ("foreign_buy_shares", "foreign_sell_shares", "net_foreign_shares", "foreign_buy_value", "foreign_sell_value",
              "net_foreign_value", "total_volume_shares"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return df
