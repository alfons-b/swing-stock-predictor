"""Evaluasi out-of-sample model challenger dengan definisi yang SAMA seperti model aktif (numpy/pandas saja).

Dipakai ulang dari app/models: `classification_metrics` (roc_auc_bullish, log_loss, brier), `expected_calibration_error`,
`topk_trading_proxy` (top-k per hari, setelah biaya round-trip) dan baris yang dinilai (`y_class` ada & is_tradeable).
Tambahan untuk prakiraan distribusi: IC harian (Spearman lintas emiten), cakupan interval 80%, pinball loss, kualitas σ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import get
from app.models.evaluation import classification_metrics, expected_calibration_error, topk_trading_proxy
from app.models.trainer import round_trip_cost

FORECAST_COLS = ["exp_return", "prob_up", "prob_bullish", "prob_bearish", "vol", "q10", "q50", "q90"]


def to_eval_frame(panel, rows: np.ndarray, fc: dict) -> pd.DataFrame:
    """Gabungkan prakiraan (dict array dari dist.summarize_quantiles) dengan label asli baris `rows`."""
    out = pd.DataFrame({"date": pd.to_datetime(panel.dates[rows]), "ticker": panel.tickers[rows],
                        "is_tradeable": panel.tradeable[rows], "y_class": panel.y_class[rows], "y_ret": panel.y_ret[rows]})
    for k in FORECAST_COLS + ["prob_neutral"]:
        if k in fc:
            out[k] = np.asarray(fc[k], float)
    return out


def daily_ic(df: pd.DataFrame, score: str, target: str = "y_ret", min_names: int = 20) -> pd.Series:
    d = df[["date", score, target]].dropna()
    ranked = d.groupby("date")[[score, target]].rank()
    ranked["date"] = d["date"]
    counts = d.groupby("date").size()
    ok = counts[counts >= min_names].index
    ranked = ranked[ranked["date"].isin(ok)]
    return ranked.groupby("date").apply(lambda g: g[score].corr(g[target]), include_groups=False).dropna()


def _ic_summary(ic: pd.Series, horizon: int) -> dict:
    if len(ic) < 5:
        return {"ic_mean": None, "ic_t": None, "ic_pos_ratio": None, "ic_days": int(len(ic))}
    # tanggal bertumpuk (target H hari) → t-stat dikoreksi kasar dengan √H agar tidak terlalu optimistis
    t = float(ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic) / max(1, horizon))) if ic.std(ddof=1) > 0 else 0.0
    return {"ic_mean": float(ic.mean()), "ic_t": t, "ic_pos_ratio": float((ic > 0).mean()), "ic_days": int(len(ic))}


def _pinball(y: np.ndarray, q: np.ndarray, level: float) -> float:
    d = y - q
    return float(np.mean(np.maximum(level * d, (level - 1) * d)))


def evaluate_forecasts(ev: pd.DataFrame, cfg: dict) -> dict:
    """Metrik OOS. `ev` dari `to_eval_frame`. Baris dinilai = y_class ada & is_tradeable (sama dengan model aktif)."""
    h = int(get(cfg, "labels.SWING_HORIZON", 5))
    k = int(get(cfg, "model.comparison_top_k", 5))
    cost = round_trip_cost(cfg)
    p = ev[ev["y_class"].notna() & ev["is_tradeable"].astype(bool)].copy()
    out: dict = {"n": int(len(p)), "eval_start": str(p["date"].min().date()) if len(p) else None,
                 "eval_end": str(p["date"].max().date()) if len(p) else None}
    if len(p) < 50:
        out["status"] = "INSUFFICIENT_DATA"
        return out
    P = p[["prob_bearish", "prob_neutral", "prob_bullish"]].to_numpy(dtype=float)
    P = P / P.sum(axis=1, keepdims=True)
    y = p["y_class"].astype(int).to_numpy()
    cm = classification_metrics(y, P)
    out.update({k_: cm[k_] for k_ in ("roc_auc_bullish", "pr_auc_bullish", "log_loss", "brier_bullish", "base_rate_bullish")})
    out["ece_bullish"] = expected_calibration_error((y == 2).astype(int), P[:, 2])
    p["y_ret_h"] = p["y_ret"]
    tk = topk_trading_proxy(p.assign(probability_bullish=P[:, 2]), "probability_bullish", "y_ret_h", k, cost)
    out.update(tk)                                                     # topk_mean_net_return = definisi model aktif
    tk_er = topk_trading_proxy(p, "exp_return", "y_ret_h", k, cost)
    out["topk_by_exp_return_net"] = tk_er["topk_mean_net_return"]
    up = (p["y_ret"] > 0).astype(int)
    if 0 < up.sum() < len(up):
        from sklearn.metrics import roc_auc_score
        out["auc_up"] = float(roc_auc_score(up, p["prob_up"]))
    out.update(_ic_summary(daily_ic(p, "exp_return"), h))
    yl = np.log1p(p["y_ret"].to_numpy(float))
    q10, q50, q90 = (np.log1p(p[c].to_numpy(float)) for c in ("q10", "q50", "q90"))
    out["coverage_80"] = float(np.mean((yl >= q10) & (yl <= q90)))
    out["pinball_mean"] = float(np.mean([_pinball(yl, q10, 0.1), _pinball(yl, q50, 0.5), _pinball(yl, q90, 0.9)]))
    vol_ic = pd.Series(p["vol"].to_numpy()).corr(pd.Series(np.abs(yl)), method="spearman")
    out["vol_rank_corr"] = None if pd.isna(vol_ic) else float(vol_ic)
    out["status"] = "OK"
    return {k_: (None if isinstance(v, float) and not np.isfinite(v) else v) for k_, v in out.items()}


def baseline_metrics(ev: pd.DataFrame, cfg: dict, feature_values: np.ndarray | None) -> dict:
    """Pembanding sederhana pada baris yang SAMA: momentum (fitur baseline), reversal (kebalikannya), rata-rata universe."""
    h = int(get(cfg, "labels.SWING_HORIZON", 5))
    k = int(get(cfg, "model.comparison_top_k", 5))
    cost = round_trip_cost(cfg)
    p = ev[ev["y_class"].notna() & ev["is_tradeable"].astype(bool)].copy()
    if len(p) < 50 or feature_values is None:
        return {}
    p["mom"] = np.asarray(feature_values, float)[ev.index.get_indexer(p.index)]
    p["rev"] = -p["mom"]
    p["y_ret_h"] = p["y_ret"]
    out = {}
    for name in ("mom", "rev"):
        tk = topk_trading_proxy(p, name, "y_ret_h", k, cost)
        ic = _ic_summary(daily_ic(p, name), h)
        out[f"{'momentum' if name == 'mom' else 'reversal'}"] = {"topk_mean_net_return": tk["topk_mean_net_return"],
                                                                 "ic_mean": ic["ic_mean"], "ic_t": ic["ic_t"]}
        out["universe_mean_net_return"] = tk["universe_mean_return"]
    return out


def verdict(metrics: dict, baselines: dict, active: dict | None) -> list[str]:
    """Kalimat jujur: apakah challenger mengungguli pembanding pada periode test yang sama."""
    if metrics.get("status") != "OK":
        return ["Data evaluasi tidak cukup."]
    msgs = []
    tk = metrics.get("topk_mean_net_return")
    auc = metrics.get("roc_auc_bullish")
    if auc is not None:
        msgs.append(f"AUC bullish {auc:.3f} ({'di atas' if auc > 0.52 else 'TIDAK di atas'} ambang promosi 0,52)")
    for name in ("momentum", "reversal"):
        b = (baselines or {}).get(name, {})
        if b.get("topk_mean_net_return") is not None and tk is not None:
            better = tk > b["topk_mean_net_return"]
            msgs.append(f"top-k net {tk:+.2%} vs baseline {name} {b['topk_mean_net_return']:+.2%} "
                        f"→ {'lebih baik' if better else 'TIDAK lebih baik'}")
    if active:
        a_tk, a_auc = active.get("topk_mean_net_return"), active.get("roc_auc_bullish")
        if a_tk is not None and tk is not None:
            auc_txt = f", AUC {auc:.3f} vs {a_auc:.3f}" if auc is not None and a_auc is not None else ""
            msgs.append(f"vs model aktif ({active.get('version')}): top-k net {tk:+.2%} vs {a_tk:+.2%}{auc_txt} "
                        f"(periode test model aktif {active.get('eval_start')}..{active.get('eval_end')})")
    if tk is not None and tk <= 0:
        msgs.append("Top-k net return ≤ 0 setelah biaya: tidak layak dipakai untuk keputusan transaksi.")
    return msgs
