"""Fitur foreign flow per emiten per hari bursa (point-in-time: data hari D dipublikasikan setelah penutupan D,
sama seperti harga penutupan → dipakai untuk keputusan setelah penutupan D, tidak lebih awal).

Jendela dihitung dalam HARI BURSA emiten (dari price_history), bukan hari kalender. Hari tanpa data flow dihitung
sebagai TIDAK ADA DATA (bukan nol) → `flow_coverage_{w}` = hari dengan data / hari bursa.

Kolom keluaran (prefiks flow_, BUKAN f_ → tidak mengubah fitur model ML aktif):
  flow_net_shares_{w}     jumlah net beli asing (lembar)
  flow_net_ratio_{w}      net lembar / volume total jendela (−1..1)
  flow_participation_{w}  (beli + jual asing) / (2 × volume)
  flow_buy_days_ratio_20  porsi hari net beli dalam 20 hari (dari hari yang punya data)
  flow_streak             hari net beli (+) / net jual (−) beruntun
  flow_net_value_{w}      nilai net (IDR); flow_value_type_{w} = ACTUAL_VALUE bila semua hari punya nilai resmi,
                          selain itu ESTIMATED_VALUE (lembar × VWAP harian = value/volume, atau close)
  flow_coverage_{w}
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_flow_features(prices: pd.DataFrame, flows: pd.DataFrame, windows=(5, 20, 60)) -> pd.DataFrame:
    """prices: ticker,date,close,volume[,value]; flows: keluaran load_flows (segmen TOTAL atau REGULAR)."""
    base = prices[["ticker", "date", "close", "volume"] + (["value"] if "value" in prices else [])].copy()
    base["date"] = pd.to_datetime(base["date"])
    if flows is None or flows.empty:
        out = base[["ticker", "date"]].copy()
        for w in windows:
            out[f"flow_coverage_{w}"] = 0.0
        return out
    f = flows.copy()
    if "market_segment" in f and f["market_segment"].nunique() > 1:
        # satu segmen per emiten-hari: utamakan REGULAR (pasar reguler), lalu TOTAL
        order = {"REGULAR": 0, "TOTAL": 1, "NEGOTIATED": 2, "CASH": 3}
        f = f.assign(_o=f["market_segment"].map(order).fillna(9)).sort_values("_o").drop_duplicates(["ticker", "date"])
    f = f[f.get("quality_status", "OK") != "CHECK"] if "quality_status" in f else f
    cols = ["ticker", "date", "foreign_buy_shares", "foreign_sell_shares", "net_foreign_shares", "net_foreign_value"]
    d = base.merge(f[[c for c in cols if c in f]], on=["ticker", "date"], how="left").sort_values(["ticker", "date"])
    d["has_flow"] = d["net_foreign_shares"].notna().astype(float)
    vwap = (d["value"] / d["volume"]).where((d.get("value", 0) > 0) & (d["volume"] > 0)) if "value" in d else np.nan
    vwap = pd.Series(vwap, index=d.index).fillna(d["close"])
    d["_est_val"] = d["net_foreign_shares"] * vwap
    d["_act"] = d["net_foreign_value"].notna().astype(float)
    d["_val"] = d["net_foreign_value"].where(d["net_foreign_value"].notna(), d["_est_val"])
    d["_vol_f"] = d["volume"].where(d["has_flow"] > 0)
    d["_gross"] = (d["foreign_buy_shares"] + d["foreign_sell_shares"])
    d["_buy_day"] = np.where(d["has_flow"] > 0, (d["net_foreign_shares"] > 0).astype(float), np.nan)
    g = d.groupby("ticker", sort=False)

    def roll(col, w, how="sum", min_periods=1):
        r = g[col].rolling(w, min_periods=min_periods)
        return getattr(r, how)().reset_index(level=0, drop=True).reindex(d.index)

    out = d[["ticker", "date"]].copy()
    for w in windows:
        cov = roll("has_flow", w) / w
        net, vol = roll("net_foreign_shares", w), roll("_vol_f", w)
        out[f"flow_coverage_{w}"] = cov
        out[f"flow_net_shares_{w}"] = net.where(cov > 0)
        out[f"flow_net_ratio_{w}"] = (net / vol.replace(0, np.nan)).clip(-1, 1).where(cov > 0)
        out[f"flow_participation_{w}"] = (roll("_gross", w) / (2 * vol.replace(0, np.nan))).clip(0, 1).where(cov > 0)
        out[f"flow_net_value_{w}"] = roll("_val", w).where(cov > 0)
        out[f"flow_value_type_{w}"] = np.where(roll("_act", w, "min") >= 1, "ACTUAL_VALUE", "ESTIMATED_VALUE")
    out["flow_buy_days_ratio_20"] = roll("_buy_day", 20, "mean", 5)
    sign = np.sign(d["net_foreign_shares"]).fillna(0)
    streak = []
    for _, s in sign.groupby(d["ticker"], sort=False):
        run, prev = [], 0
        for v in s.values:
            prev = (prev + v if np.sign(prev) == v and v != 0 else v)
            run.append(prev)
        streak.extend(run)
    out["flow_streak"] = pd.Series(streak, index=d.index)
    return out.reset_index(drop=True)
