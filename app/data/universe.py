"""UniverseManager (§19): listing baru, emiten tidak aktif, perubahan kode, perubahan sektor, delisting.

Prinsip: histori TIDAK pernah dihapus. Emiten yang hilang dari daftar → is_active = false.
Pengaman: bila daftar baru jauh lebih kecil dari jumlah aktif (respons parsial), deaktivasi dibatalkan.
"""
from __future__ import annotations

import pandas as pd
import yaml

from app.config import get, resolve_path
from app.data.schema import conform_universe
from app.data.tickers import normalize_ticker
from app.database.repository import Repository, now_utc
from app.utils.logging_utils import get_logger

log = get_logger(__name__)


class UniverseManager:
    def __init__(self, cfg: dict, repo: Repository, chain):
        self.cfg, self.repo, self.chain = cfg, repo, chain

    def fetch_universe(self) -> tuple[pd.DataFrame, str]:
        for src in get(self.cfg, "universe.sources", ["idx", "csv_file"]):
            if src == "csv_file":
                p = resolve_path(self.cfg, get(self.cfg, "universe.file", "config/universe.csv"))
                # provider CSV (data contoh / feed ekspor) punya universe sendiri yang lebih lengkap
                for prov in self.chain.providers:
                    if prov.type == "csv":
                        try:
                            return prov.get_universe(), prov.name
                        except Exception:
                            pass
                if p.exists():
                    u = pd.read_csv(p, dtype=str)
                    u["ticker"] = u["ticker"].map(normalize_ticker)
                    return conform_universe(u), f"file:{p.name}"
                continue
            for prov in self.chain.providers:
                if prov.type == src:
                    try:
                        return prov.get_universe(), prov.name
                    except Exception as e:
                        log.warning("Universe dari %s gagal: %s", prov.name, e)
            if src == "idx" and not any(p.type == "idx" for p in self.chain.providers):
                try:
                    from app.data.providers.idx_provider import IDXProvider
                    return IDXProvider({"name": "idx_public"}, self.cfg).get_universe(), "idx_public"
                except Exception as e:
                    log.warning("Universe BEI publik gagal: %s", e)
        raise RuntimeError("Universe tidak bisa diambil dari sumber mana pun")

    def apply_ticker_changes(self) -> list[str]:
        p = resolve_path(self.cfg, get(self.cfg, "universe.ticker_changes_file", "config/ticker_changes.yaml"))
        if not p.exists():
            return []
        changes = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("changes") or []
        done = []
        for c in changes:
            old, new = normalize_ticker(c["old"]), normalize_ticker(c["new"])
            if self.repo.rename_ticker(old, new):
                done.append(f"{old}->{new}")
        return done

    def update(self) -> dict:
        renamed = self.apply_ticker_changes()
        fresh, source = self.fetch_universe()
        existing = self.repo.stocks()
        now = now_utc()
        fresh = fresh.copy()
        fresh["is_active"] = fresh["delisting_date"].isna() | (fresh["delisting_date"] > pd.Timestamp.today())
        fresh["last_seen"], fresh["updated_at"], fresh["first_seen"] = now, now, now
        # jangan timpa metadata yang sudah ada dengan nilai kosong
        if len(existing):
            ex = existing.set_index("ticker")
            for col in ("name", "sector", "subsector", "board"):
                blank = fresh[col].isna() | fresh[col].isin(["", "Unknown"]) | (fresh[col].astype(str) == fresh["ticker"])
                fresh.loc[blank, col] = fresh.loc[blank, "ticker"].map(ex[col]) if col in ex else None
        for c in ("listing_date", "delisting_date"):
            fresh[c] = pd.to_datetime(fresh[c]).dt.strftime("%Y-%m-%d").where(fresh[c].notna(), None)
        new = sorted(set(fresh["ticker"]) - set(existing["ticker"])) if len(existing) else sorted(fresh["ticker"])
        sector_changes = []
        if len(existing):
            m = fresh.merge(existing[["ticker", "sector"]], on="ticker", how="inner", suffixes=("", "_old"))
            sector_changes = m.loc[m["sector"].notna() & m["sector_old"].notna() & (m["sector"] != m["sector_old"]), "ticker"].tolist()
        ins, upd = self.repo.upsert_stocks(fresh)
        # emiten hilang dari daftar → nonaktif (dengan pengaman respons parsial)
        active_before = existing[existing["is_active"]]["ticker"].tolist() if len(existing) else []
        missing = sorted(set(active_before) - set(fresh["ticker"]))
        deactivated = []
        ratio = len(fresh) / max(1, len(active_before))
        if missing and ratio >= float(get(self.cfg, "universe.min_ratio_to_deactivate", 0.5)):
            self.repo.set_inactive(missing)
            deactivated = missing
        elif missing:
            log.warning("Daftar universe hanya %d vs %d aktif — deaktivasi %d emiten DITUNDA (kemungkinan respons parsial)",
                        len(fresh), len(active_before), len(missing))
        delisted = fresh.loc[~fresh["is_active"], "ticker"].tolist()
        self._enrich_metadata()
        out = {"source": source, "total": len(fresh), "new_listings": new, "inserted": ins, "updated": upd,
               "deactivated": deactivated, "delisted": delisted, "renamed": renamed, "sector_changes": sector_changes}
        log.info("Universe (%s): %d emiten, %d baru, %d dinonaktifkan, %d rename", source, len(fresh), len(new),
                 len(deactivated), len(renamed))
        return out

    def _enrich_metadata(self) -> None:
        st = self.repo.stocks(active_only=True)
        missing = st[st["sector"].isna() | (st["sector"].astype(str).isin(["", "Unknown", "None"]))]["ticker"].tolist()
        if not missing:
            return
        for prov in self.chain.providers:
            try:
                e = prov.enrich_universe(missing)
            except Exception:
                continue
            e = e.dropna(subset=["sector"])
            if len(e):
                cur = st.set_index("ticker").loc[e["ticker"]].reset_index()
                for col in ("name", "sector", "subsector"):
                    if col in e:
                        cur[col] = e.set_index("ticker").loc[cur["ticker"], col].values
                cur["updated_at"] = now_utc()
                self.repo.upsert_stocks(cur)
                missing = [t for t in missing if t not in set(e["ticker"])]
            if not missing:
                break
