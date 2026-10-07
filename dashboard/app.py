"""Dashboard production (§44, §45) — membaca database cloud (Supabase), bukan file lokal.

Deploy sebagai WEB SERVICE terpisah dari daily job (Streamlit Community Cloud / Render / Docker).
Credential: DATABASE_URL dari st.secrets (Streamlit Cloud) atau environment. Dashboard hanya membaca.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

try:  # Streamlit Cloud: secrets → environment (sebelum config dimuat)
    for k in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_KEY", "APP_ENV"):
        if k in st.secrets and not os.environ.get(k):
            os.environ[k] = str(st.secrets[k])
except Exception:
    pass

from app.config import get, load_config  # noqa: E402
from app.pipeline.context import AppContext  # noqa: E402

UP, DOWN, ACCENT, INK = "#12805C", "#C23B32", "#2E5AAC", "#15232D"
st.set_page_config(page_title="Swing Stock Predictor — BEI", layout="wide")


@st.cache_resource
def ctx() -> AppContext:
    return AppContext.create(load_config(ROOT / "config"), migrate_db=False)


@st.cache_data(ttl=300)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return ctx().db.query_df(sql, params)


@st.cache_data(ttl=600)
def stock_frame(ticker: str, days: int = 400) -> pd.DataFrame:
    from app.features.technical import compute_stock_features
    df = q("SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.value FROM price_history p JOIN stocks s ON s.id = p.stock_id "
           "WHERE s.ticker = ? ORDER BY p.date DESC LIMIT ?", (ticker, days))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").assign(ticker=ticker)
    for c in ("open", "high", "low", "close", "volume", "value"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return compute_stock_features(df, ctx().cfg)


def jl(v):
    try:
        return json.loads(v) if isinstance(v, str) else (v or [])
    except Exception:
        return []


try:
    c = ctx()
    c.db.scalar("SELECT 1")
except Exception as e:
    st.error(f"Database tidak bisa diakses: {type(e).__name__}. Set DATABASE_URL di secrets.")
    st.stop()

PAGES = ["Market Overview", "Top Swing Stocks", "Sector Strength", "Stock Detail", "Prediction History", "Backtest",
         "Model Performance", "Pipeline Status", "Data Health"]
page = st.sidebar.radio("Halaman", PAGES)
st.sidebar.caption("Analytical decision support — bukan jaminan profit. Bukan nasihat investasi.")

last_sig_date = c.db.scalar("SELECT MAX(signal_date) FROM trading_signals") or c.db.scalar("SELECT MAX(prediction_date) FROM predictions")

if page == "Market Overview":
    ix = q("SELECT date, close FROM market_index WHERE symbol = ? ORDER BY date DESC LIMIT 500", (get(c.cfg, "data.index_id"),))
    run = q("SELECT run_id, status, started_at, data_status, market_date, summary FROM pipeline_runs WHERE run_type = 'daily' "
            "ORDER BY started_at DESC LIMIT 1")
    s = jl(run["summary"].iloc[0]) if len(run) and run["summary"].iloc[0] else {}
    st.title(f"Pasar {last_sig_date or '–'}: {s.get('regime', 'n/a')}")
    k = st.columns(4)
    k[0].metric("Status pipeline terakhir", run["status"].iloc[0] if len(run) else "–")
    k[1].metric("Data", run["data_status"].iloc[0] if len(run) else "–")
    k[2].metric("Headline", s.get("headline", "–")[:30])
    k[3].metric("Rekomendasi", len(s.get("top", [])))
    if len(ix):
        ix = ix.sort_values("date")
        st.plotly_chart(go.Figure(go.Scatter(x=pd.to_datetime(ix["date"]), y=pd.to_numeric(ix["close"]), line=dict(color=INK)))
                        .update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), title="IHSG"), use_container_width=True)
    rep = c.reports.latest("html")
    if rep:
        with st.expander(f"Daily report terbaru ({rep[0]})"):
            st.components.v1.html(rep[1].decode("utf-8"), height=900, scrolling=True)

elif page == "Top Swing Stocks":
    st.title(f"Top swing stocks — {last_sig_date or '–'}")
    sig = q("SELECT * FROM trading_signals WHERE signal_date = ? ORDER BY rank", (last_sig_date,)) if last_sig_date else pd.DataFrame()
    if sig.empty:
        st.subheader("NO HIGH-CONVICTION SETUP TODAY")
        st.write("Tidak ada saham yang lolos semua filter risiko. Menunggu adalah posisi yang sah.")
    else:
        st.dataframe(sig[["rank", "ticker", "setup", "score", "prob_bullish", "expected_return", "entry_low", "entry_ideal", "entry_high",
                          "stop_loss", "tp1", "tp2", "risk_reward", "lots", "confidence", "decision"]], hide_index=True, use_container_width=True)
        det = q("SELECT ticker, reasons, risks FROM predictions WHERE prediction_date = ? AND decision = 'BUY'", (last_sig_date,))
        for r in det.itertuples():
            with st.expander(r.ticker):
                a, b = st.columns(2)
                a.markdown("**Alasan**\n" + "\n".join(f"- {x}" for x in jl(r.reasons)))
                b.markdown("**Risiko**\n" + ("\n".join(f"- {x}" for x in jl(r.risks)) or "- tidak ada yang menonjol"))
    w = q("SELECT ticker, setup, score, prob_bullish, reject_reasons FROM predictions WHERE prediction_date = ? AND decision = 'WATCHLIST' "
          "ORDER BY score DESC LIMIT 15", (last_sig_date,)) if last_sig_date else pd.DataFrame()
    if len(w):
        st.subheader("Watchlist")
        st.dataframe(w.assign(reject_reasons=w["reject_reasons"].map(lambda v: ", ".join(jl(v)))), hide_index=True, use_container_width=True)

elif page == "Sector Strength":
    d = c.db.scalar("SELECT MAX(date) FROM sector_data")
    sec = q("SELECT * FROM sector_data WHERE date = ? ORDER BY rank", (d,)) if d else pd.DataFrame()
    st.title(f"Kekuatan sektor — {d or '–'}")
    if len(sec):
        st.plotly_chart(go.Figure(go.Bar(x=pd.to_numeric(sec["score"]), y=sec["sector"], orientation="h", marker_color=ACCENT))
                        .update_layout(height=420, yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=10, b=10)),
                        use_container_width=True)
        st.dataframe(sec.drop(columns=["id"]), hide_index=True, use_container_width=True)

elif page == "Stock Detail":
    tickers = q("SELECT ticker FROM stocks WHERE is_active = ? ORDER BY ticker", (True,))["ticker"].tolist()
    if not tickers:
        st.stop()
    tk = st.selectbox("Saham", tickers)
    g = stock_frame(tk)
    p = q("SELECT * FROM predictions WHERE ticker = ? ORDER BY prediction_date DESC LIMIT 1", (tk,))
    if g.empty:
        st.warning("Belum ada data harga.")
        st.stop()
    g = g.tail(160)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.18, 0.22], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(x=g["date"], open=g["open"], high=g["high"], low=g["low"], close=g["close"], name=tk,
                                 increasing_line_color=UP, decreasing_line_color=DOWN), 1, 1)
    for col, color in (("ema20", ACCENT), ("ema50", "#7A5BA6"), ("ema200", INK)):
        fig.add_trace(go.Scatter(x=g["date"], y=g[col], name=col.upper(), line=dict(color=color, width=1.2)), 1, 1)
    if len(p):
        r = p.iloc[0]
        for name, col, color in (("Entry", "entry_ideal", ACCENT), ("SL", "stop_loss", DOWN), ("TP1", "tp1", UP), ("TP2", "tp2", "#0B5A40")):
            v = pd.to_numeric(r[col], errors="coerce")
            if pd.notna(v):
                fig.add_hline(y=float(v), line=dict(color=color, dash="dash", width=1), annotation_text=f"{name} {v:,.0f}", row=1, col=1)
    for name, col in (("Support", "sup20"), ("Resistance", "res50")):
        v = g[col].iloc[-1]
        if pd.notna(v):
            fig.add_hline(y=float(v), line=dict(color="#8A6D1F", dash="dot", width=1), annotation_text=name, row=1, col=1)
    fig.add_trace(go.Bar(x=g["date"], y=g["volume"], marker_color=np.where(g["close"] >= g["open"], UP, DOWN), name="Volume"), 2, 1)
    fig.add_trace(go.Scatter(x=g["date"], y=g["rsi14"], line=dict(color=INK, width=1), name="RSI14"), 3, 1)
    fig.update_layout(height=720, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
    if len(p):
        r = p.iloc[0]
        k = st.columns(4)
        k[0].metric("Keputusan", r["decision"])
        k[1].metric("P(bullish)", f"{float(r['prob_bullish']):.0%}")
        k[2].metric("Risk/reward", f"{float(r['risk_reward']):.2f}" if pd.notna(r["risk_reward"]) else "n/a")
        k[3].metric("Model", r["model_version"])
        st.caption(f"Prediksi {r['prediction_date']} · data {r['data_status']}")

elif page == "Prediction History":
    st.title("Riwayat prediksi")
    dec = st.multiselect("Keputusan", ["BUY", "WATCHLIST", "WAIT", "AVOID"], default=["BUY", "WATCHLIST"])
    h = c.repo.prediction_history(20000)
    h = h[h["decision"].isin(dec)]
    ev = h[h["outcome"].notna()]
    if len(ev):
        k = st.columns(4)
        k[0].metric("Terevaluasi", len(ev))
        k[1].metric("Prediksi benar", f"{ev['prediction_correct'].astype(float).mean():.0%}")
        k[2].metric("Kena TP1", f"{ev['hit_tp1'].astype(float).mean():.0%}")
        k[3].metric("Kena SL", f"{ev['hit_stop'].astype(float).mean():.0%}")
    st.dataframe(h, hide_index=True, use_container_width=True)

elif page == "Backtest":
    st.title("Backtest")
    runs = c.repo.backtest_runs(30)
    if runs.empty:
        st.info("Belum ada backtest (workflow Weekly Backtest).")
        st.stop()
    rid = st.selectbox("Run", runs["run_id"])
    r = runs[runs["run_id"] == rid].iloc[0]
    m, b = jl(r["metrics"]), jl(r["benchmark"])
    if isinstance(m, dict):
        k = st.columns(5)
        k[0].metric("Total return", f"{m.get('total_return', 0):+.1%}")
        k[1].metric("Max drawdown", f"{m.get('max_drawdown', 0):.1%}")
        k[2].metric("Sharpe", f"{m.get('sharpe', 0):.2f}")
        k[3].metric("Trades", m.get("number_of_trades", 0))
        bh = (b or {}).get("ihsg_buy_hold", {}) if isinstance(b, dict) else {}
        k[4].metric("IHSG buy & hold", f"{bh.get('total_return', 0):+.1%}" if bh else "n/a")
        st.json({"strategy": m, "benchmark": b})
    t = q("SELECT * FROM backtest_trades WHERE backtest_run_id = ? ORDER BY entry_date", (rid,))
    st.dataframe(t, hide_index=True, use_container_width=True)

elif page == "Model Performance":
    st.title("Model")
    v = c.models.list_versions()
    st.dataframe(v.drop(columns=["metrics"]), hide_index=True, use_container_width=True)
    if len(v):
        ver = st.selectbox("Versi", v["version"])
        m = jl(v[v["version"] == ver]["metrics"].iloc[0])
        if isinstance(m, dict) and m.get("folds"):
            st.subheader("Walk-forward per fold")
            st.dataframe(pd.DataFrame(m["folds"]), hide_index=True, use_container_width=True)
            st.json({k: m.get(k) for k in ("auc_mean", "auc_std", "ece_bullish", "positive_fold_ratio", "head_to_head", "test_sealed")})

elif page == "Pipeline Status":
    st.title("Pipeline runs")
    runs = c.repo.pipeline_runs(100)
    st.dataframe(runs.drop(columns=["summary"], errors="ignore"), hide_index=True, use_container_width=True)
    logs = q("SELECT ts, level, logger, message, run_id FROM system_logs ORDER BY ts DESC LIMIT 200")
    st.subheader("Log penting")
    st.dataframe(logs, hide_index=True, use_container_width=True)

elif page == "Data Health":
    from app.pipeline.health import health_check
    st.title("Data health")
    h = health_check(c, check_provider=False)
    st.dataframe(pd.DataFrame([{"check": k, **v} for k, v in h["checks"].items()]), hide_index=True, use_container_width=True)
    st.json(c.repo.price_counts())
    st.subheader("Sumber data")
    st.dataframe(q("SELECT name, type, priority, enabled, last_success_at, last_error_at, last_error, rows_fetched_total FROM data_sources"),
                 hide_index=True, use_container_width=True)
