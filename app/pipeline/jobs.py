"""Orkestrasi job (§6, §11, §16, §17). Hanya mengorkestrasi — logika ada di layer masing-masing (§46).

Setiap job: START → PROCESS → SAVE → EXIT (§55). Tidak ada proses yang dibiarkan hidup.
"""
from __future__ import annotations

import json

import pandas as pd

from app import FEATURE_VERSION
from app.config import get
from app.data.ingestion import run_ingestion
from app.data.universe import UniverseManager
from app.data.validator import issues_to_frame, validate_prices
from app.pipeline.context import AppContext, PipelineRun
from app.pipeline.evaluate import evaluate_predictions
from app.pipeline.freshness import data_freshness
from app.pipeline.health import check_environment, health_check
from app.pipeline.market_data import build_dataset
from app.reporting.daily_report import html_report, markdown_report, predictions_csv, sector_table
from app.scanner.scanner import analyze_ticker, scan_day, summarize_scan
from app.utils.logging_utils import get_logger

log = get_logger(__name__)


class PipelineAbort(RuntimeError):
    pass


# ---------------------------------------------------------------------------------- helpers
def _ingest(ctx: AppContext, run: PipelineRun, full_actions: bool = False) -> dict:
    try:
        uni = UniverseManager(ctx.cfg, ctx.repo, ctx.chain).update()
    except Exception as e:  # universe gagal → lanjut dengan universe di DB (bila ada)
        if ctx.db.scalar("SELECT COUNT(*) FROM stocks") == 0:
            raise
        log.warning("Update universe gagal, memakai universe di database: %s", e)
        uni = {"error": str(e)}
    st = run_ingestion(ctx.cfg, ctx.repo, ctx.chain, ctx.calendar, full_actions=full_actions)
    run.stats.update({"stocks_processed": st.stocks_processed, "stocks_failed": st.stocks_failed,
                      "rows_inserted": st.rows_inserted, "rows_updated": st.rows_updated,
                      "market_date": st.expected_date})
    log.info("Ingestion: %d emiten diproses, %d gagal, %d up-to-date, +%d baris, %d diperbarui, %d ditolak validasi",
             st.stocks_processed, st.stocks_failed, st.stocks_up_to_date, st.rows_inserted, st.rows_updated,
             st.rows_rejected, extra={"persist": True})
    if st.failed:
        log.warning("Ticker gagal (%d): %s", len(st.failed), ", ".join(list(st.failed)[:30]))
    if st.stocks_requested and st.stocks_failed / st.stocks_requested > float(get(ctx.cfg, "pipeline.max_failed_ticker_ratio", 0.5)):
        raise PipelineAbort(f"{st.stocks_failed}/{st.stocks_requested} ticker gagal diunduh — provider bermasalah")
    if st.stocks_failed:
        run.status = "PARTIAL_SUCCESS"
    return {"universe": uni, "ingestion": st.as_dict()}


def _load_model(ctx: AppContext):
    model, active = ctx.models.load_active_model()
    if active.get("feature_version") != FEATURE_VERSION:
        raise PipelineAbort(f"Model {active['version']} memakai feature_version {active.get('feature_version')} "
                            f"≠ {FEATURE_VERSION}. Jalankan workflow retrain.")
    return model, active["version"]


def _driver_features(ctx, model) -> list[str]:
    ic = ctx.cfg.get("_ic_order") or []
    return [f for f in ic if f in model.features][:15] or model.features[:15]


def _save_scan(ctx: AppContext, res: dict, summary: dict, run_id: str, model_version: str) -> dict:
    cfg, repo = ctx.cfg, ctx.repo
    sig, ranked = res["signals"], res["ranked"]
    ids = repo.stock_ids()
    h = cfg["labels"]["SWING_HORIZON"]
    d = res["date"].strftime("%Y-%m-%d")
    rich = sig["decision"].isin(["BUY", "WATCHLIST"])
    from app.strategy.explain import build_reasoning
    reasons = [build_reasoning(r) if k else ([], []) for (_, r), k in zip(sig.iterrows(), rich)]
    pred = pd.DataFrame({
        "prediction_date": d, "stock_id": sig["ticker"].map(ids), "ticker": sig["ticker"], "model_version": model_version,
        "horizon": h, "decision": sig["decision"], "setup": sig["setup_type"], "score": sig["final_score"],
        "market_regime": sig["market_regime"], "prob_bearish": sig["probability_bearish"],
        "prob_neutral": sig["probability_neutral"], "prob_bullish": sig["probability_bullish"],
        "expected_return": sig.get(f"expected_return_{h}d"), "prob_hit_tp": sig.get("prob_hit_tp"),
        "entry_low": sig["entry_low"], "entry_ideal": sig["entry_ideal"], "entry_high": sig["entry_high"],
        "stop_loss": sig["stop_loss"], "tp1": sig["take_profit_1"], "tp2": sig["take_profit_2"],
        "risk_reward": sig["risk_reward"], "position_size": sig["position_size"], "lots": sig["position_lots"],
        "capital_required": sig["capital_required"], "estimated_loss": sig["estimated_loss"],
        "confidence": sig["confidence"], "close_price": sig["close"],
        "data_status": summary["data_freshness"]["status"],
        "reasons": [json.dumps(r[0], ensure_ascii=False) if k else None for r, k in zip(reasons, rich)],
        "risks": [json.dumps(r[1], ensure_ascii=False) if k else None for r, k in zip(reasons, rich)],
        "reject_reasons": sig["reject_reasons"].map(json.dumps), "run_id": run_id,
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")})
    pi, pu = repo.save_predictions(pred)
    sg = pd.DataFrame({"signal_date": d, "stock_id": ranked["ticker"].map(ids), "ticker": ranked["ticker"],
                       "rank": ranked["rank"], "decision": ranked["decision"], "setup": ranked["setup_type"],
                       "score": ranked["final_score"], "prob_bullish": ranked["probability_bullish"],
                       "expected_return": ranked.get(f"expected_return_{h}d"), "entry_low": ranked["entry_low"],
                       "entry_ideal": ranked["entry_ideal"], "entry_high": ranked["entry_high"],
                       "stop_loss": ranked["stop_loss"], "tp1": ranked["take_profit_1"], "tp2": ranked["take_profit_2"],
                       "risk_reward": ranked["risk_reward"], "lots": ranked["position_lots"],
                       "confidence": ranked["confidence"], "model_version": model_version, "run_id": run_id})
    repo.save_signals(sg, d)
    sec = sector_table(sig)
    repo.save_sector_data(sec.rename(columns={"score": "score"}).assign(date=d)[
        ["date", "sector", "ret5", "ret20", "ret60", "breadth", "volume_mom", "rs20", "score", "rank", "n_stocks"]])
    snap_cols = ["close", "ema20", "ema50", "sma200", "rsi14", "adx", "atr_pct", "volume_ratio", "f_rs20", "f_rs60",
                 "sector_score", "liquidity_score", "setup_type", "setup_score", "final_score", "technical_score", "ml_score"]
    feats = pd.DataFrame({"stock_id": sig["ticker"].map(ids), "date": d, "feature_version": FEATURE_VERSION,
                          "payload": sig[snap_cols].apply(lambda r: json.dumps({k: (None if pd.isna(v) else v) for k, v in r.items()},
                                                                               default=str), axis=1)})
    repo.save_features_snapshot(feats, int(get(cfg, "pipeline.features_snapshot_days", 5)))
    log.info("Tersimpan: %d prediksi (+%d baru), %d sinyal ranking, %d sektor", len(pred), pi, len(sg), len(sec),
             extra={"persist": True})
    return {"predictions": len(pred), "signals": len(sg)}


def _write_reports(ctx: AppContext, summary: dict, res: dict, df: pd.DataFrame, run_id: str, evaluation=None) -> list[str]:
    ds = summary["date"].replace("-", "")
    sec = sector_table(res["signals"])
    files = [("predictions_csv", f"daily_predictions_{ds}.csv", predictions_csv(res["signals"], ctx.cfg["labels"]["SWING_HORIZON"])),
             ("html", f"daily_report_{ds}.html", html_report(summary, sec, df, evaluation).encode("utf-8")),
             ("markdown", f"daily_report_{ds}.md", markdown_report(summary, sec).encode("utf-8")),
             ("summary_json", f"daily_summary_{ds}.json", json.dumps(summary, default=str, ensure_ascii=False, indent=2).encode())]
    uris = [ctx.reports.save(summary["date"], kind, fn, content, run_id) for kind, fn, content in files]
    log.info("Report dibuat: %s", ", ".join(fn for _, fn, _ in files), extra={"persist": True})
    return uris


# ---------------------------------------------------------------------------------- jobs
def job_daily(ctx: AppContext, skip_ingest: bool = False) -> dict:
    with PipelineRun(ctx, "daily") as run:
        h = health_check(ctx, check_provider=False)
        if not h["ok"]:
            raise PipelineAbort("Health check gagal: " + json.dumps({k: v for k, v in h["checks"].items() if v["status"] == "FAIL"}))
        ingest = {} if skip_ingest else _ingest(ctx, run)
        fresh = data_freshness(ctx.cfg, ctx.repo, ctx.calendar)
        run.stats["data_status"] = fresh["status"]
        if fresh["status"] == "UNAVAILABLE":
            raise PipelineAbort("Tidak ada data harga di database")
        df = build_dataset(ctx.cfg, ctx.repo, int(get(ctx.cfg, "pipeline.scan_lookback_trading_days", 520)), labels=False)
        model, version = _load_model(ctx)
        run.stats["model_version"] = version
        res = scan_day(ctx.cfg, df, model, fresh)
        summary = summarize_scan(ctx.cfg, res, model, version, fresh, ctx.is_synthetic(), _driver_features(ctx, model))
        saved = _save_scan(ctx, res, summary, run.run_id, version)
        evaluation = evaluate_predictions(ctx.cfg, ctx.repo)
        uris = _write_reports(ctx, summary, res, df, run.run_id, evaluation)
        run.stats["summary"] = {"headline": summary["headline"], "date": summary["date"], "regime": summary["market_regime"],
                                "top": [r["ticker"] for r in summary["recommendations"]], "freshness": fresh, "saved": saved,
                                "evaluation": evaluation, "reports": uris, "ingestion": ingest.get("ingestion", {}).get("provider_stats")}
        try:
            from app.notifications.notify import notify_daily
            notify_daily(summary)
        except Exception as e:
            log.warning("Notifikasi gagal: %s", e)
        if run.status == "RUNNING":  # status final ditulis saat keluar dari `with`; nilai yang sama ditampilkan CLI
            run.status = "SUCCESS"
        summary["run_id"] = run.run_id
        summary["run_status"] = run.status
        return summary


def job_update_data(ctx: AppContext, full_actions: bool = False) -> dict:
    with PipelineRun(ctx, "update_data") as run:
        out = _ingest(ctx, run, full_actions=full_actions)
        run.stats["summary"] = out["ingestion"]
        return out


def job_validate(ctx: AppContext) -> pd.DataFrame:
    with PipelineRun(ctx, "validate_data") as run:
        prices = ctx.repo.load_prices()
        st = ctx.repo.stocks()
        uni = st[["ticker", "listing_date", "delisting_date"]].copy()
        ca = ctx.repo.load_actions()
        rep = issues_to_frame(validate_prices(prices, uni, ca, ctx.cfg))
        counts = ctx.repo.price_counts()
        rep = pd.concat([rep, pd.DataFrame([{"check": "db_duplicate_stock_date", "severity": "OK" if not counts["duplicates"] else "ERROR",
                                              "count": counts["duplicates"], "detail": "unique(stock_id, date)", "tickers": []}])])
        run.stats["summary"] = {"issues": rep[rep["severity"].isin(["WARN", "ERROR"])].to_dict(orient="records"), **counts}
        if (rep["severity"] == "ERROR").any():
            run.status = "PARTIAL_SUCCESS"
        return rep


def job_features(ctx: AppContext) -> dict:
    with PipelineRun(ctx, "features") as run:
        df = build_dataset(ctx.cfg, ctx.repo, int(get(ctx.cfg, "pipeline.scan_lookback_trading_days", 520)), labels=False)
        last = df[df["date"] == df["date"].max()]
        out = {"rows": len(df), "stocks": int(df["ticker"].nunique()), "date": str(df["date"].max().date()),
               "features": int(sum(c.startswith("f_") for c in df.columns)), "tradeable_today": int(last["is_tradeable"].sum()),
               "regime_today": last["market_regime"].iloc[0]}
        run.stats["summary"] = out
        return out


def job_train(ctx: AppContext, force: bool = True, compare: bool = True) -> dict:
    from app.models.retrain import retrain
    with PipelineRun(ctx, "retrain") as run:
        df = build_dataset(ctx.cfg, ctx.repo, None, labels=True)
        out = retrain(ctx.cfg, df, ctx.models, force=force, compare=compare)
        run.stats["model_version"] = out.get("version") or out.get("active_version")
        run.stats["summary"] = {k: v for k, v in out.items() if k != "metrics"}
        return out


def job_backtest(ctx: AppContext, last_n_folds: int | None = None, live: bool = True) -> dict:
    from app.backtest.runner import live_backtest, walk_forward_backtest
    with PipelineRun(ctx, "backtest") as run:
        model, version = _load_model(ctx)
        df = build_dataset(ctx.cfg, ctx.repo, None, labels=True)
        n = last_n_folds if last_n_folds is not None else get(ctx.cfg, "backtest.weekly_validation_folds")
        out = walk_forward_backtest(ctx.cfg, df, model.meta["classifiers"], model.features, ctx.repo, version, n)
        if live:
            out["live"] = live_backtest(ctx.cfg, ctx.repo, df)
        run.stats["model_version"] = version
        run.stats["summary"] = {k: {kk: vv for kk, vv in (v or {}).items() if kk in ("run_id", "strategy", "ihsg_buy_hold")}
                                for k, v in out.items()}
        return out


def job_scan(ctx: AppContext, date: str | None = None, save: bool = True) -> dict:
    with PipelineRun(ctx, "scan") as run:
        fresh = data_freshness(ctx.cfg, ctx.repo, ctx.calendar)
        df = build_dataset(ctx.cfg, ctx.repo, int(get(ctx.cfg, "pipeline.scan_lookback_trading_days", 520)),
                           labels=False, end=date)
        model, version = _load_model(ctx)
        if date:  # scan historis: freshness tidak relevan, tetapi ditandai
            fresh = {**fresh, "status": "HISTORICAL", "trading_allowed": True, "latest_database_date": date}
        res = scan_day(ctx.cfg, df, model, fresh)
        summary = summarize_scan(ctx.cfg, res, model, version, fresh, ctx.is_synthetic(), _driver_features(ctx, model))
        if save and not date:
            _save_scan(ctx, res, summary, run.run_id, version)
        run.stats.update({"model_version": version, "data_status": fresh["status"],
                          "summary": {"headline": summary["headline"], "date": summary["date"]}})
        return summary


def job_predict(ctx: AppContext, ticker: str, date: str | None = None) -> dict:
    fresh = data_freshness(ctx.cfg, ctx.repo, ctx.calendar)
    df = build_dataset(ctx.cfg, ctx.repo, int(get(ctx.cfg, "pipeline.scan_lookback_trading_days", 520)), labels=False, end=date)
    model, version = _load_model(ctx)
    res = scan_day(ctx.cfg, df, model, fresh)
    rec = analyze_ticker(ctx.cfg, res, ticker, model, version, ctx.is_synthetic())
    rec["data_freshness"] = fresh["status"]
    return rec


def job_evaluate(ctx: AppContext) -> dict:
    with PipelineRun(ctx, "evaluate") as run:
        ev = evaluate_predictions(ctx.cfg, ctx.repo)
        h = ctx.repo.prediction_history(100000)
        done = h[h["outcome"].notna()]
        out = {"evaluation": ev, "n_predictions": int(len(h)), "n_evaluated": int(len(done))}
        if len(done):
            done = done.copy()
            for c in ("hit_stop", "hit_tp1", "hit_tp2", "prediction_correct"):
                done[c] = done[c].astype(float)
            out["all"] = {"accuracy": float(done["prediction_correct"].mean()),
                          "avg_predicted_return": float(done["expected_return"].mean()),
                          "avg_actual_return_5d": float(done["actual_return_5d"].mean())}
            buys = done[done["decision"] == "BUY"]
            if len(buys):
                out["buy"] = {"n": int(len(buys)), "hit_tp1": float(buys["hit_tp1"].mean()), "hit_tp2": float(buys["hit_tp2"].mean()),
                              "hit_stop": float(buys["hit_stop"].mean()), "avg_actual_return_5d": float(buys["actual_return_5d"].mean()),
                              "avg_mfe": float(buys["mfe"].mean()), "avg_mae": float(buys["mae"].mean())}
        run.stats["summary"] = out
        return out


def job_setup(ctx: AppContext, skip_backtest: bool = False) -> dict:
    """First initialization (§11, §66). Idempoten: aman dijalankan ulang."""
    out = {}
    env = check_environment(ctx.cfg)
    if env:
        raise PipelineAbort("Environment tidak valid: " + "; ".join(env))
    ctx.db.scalar("SELECT 1")
    with PipelineRun(ctx, "setup") as run:
        out["ingest"] = _ingest(ctx, run, full_actions=True)
        run.stats["summary"] = {"ingestion": {k: v for k, v in out["ingest"]["ingestion"].items() if k != "failed"}}
    out["validation"] = job_validate(ctx)[["check", "severity", "count"]].to_dict(orient="records")
    out["features"] = job_features(ctx)
    from app.models.retrain import retrain
    with PipelineRun(ctx, "retrain") as run:
        df = build_dataset(ctx.cfg, ctx.repo, None, labels=True)
        tr = retrain(ctx.cfg, df, ctx.models, force=True)
        if tr["decision"] == "REJECTED" and ctx.models.active_version() is None:
            # Model pertama: perlu model ACTIVE agar daily bisa berjalan. Ditandai BASELINE dan
            # dilaporkan health check (MODEL STATUS: WARN) — filter NO-TRADE tetap berlaku.
            ctx.models.promote(tr["version"], "BASELINE (gerbang promosi gagal: " + "; ".join(tr["reasons"]) + ")")
            tr["decision"] = "PROMOTED_AS_BASELINE"
        run.stats["model_version"] = tr["version"]
        run.stats["summary"] = {k: v for k, v in tr.items() if k != "metrics"}
        out["train"] = tr
    if not skip_backtest:
        out["backtest"] = job_backtest(ctx, live=False)
    return out
