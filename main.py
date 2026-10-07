"""CLI — Swing Stock Predictor (BEI).

Production: GitHub Actions menjalankan `python main.py daily` (terjadwal atau manual). Tidak ada scheduler lokal.

  python main.py health            python main.py setup             python main.py daily
  python main.py update-data       python main.py validate-data     python main.py features
  python main.py train             python main.py evaluate          python main.py backtest
  python main.py scan              python main.py predict BBCA      python main.py models
  python main.py make-sample       python main.py db-schema

Opsi global: --config DIR  --set key=value  --as-of YYYY-MM-DD (simulasi tanggal; untuk test/backfill)
Exit code: 0 sukses, 1 gagal (GitHub Actions → FAILED), 2 config salah, 3 health kritis gagal.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from app.config import ConfigError, get, load_config, resolve_path  # noqa: E402
from app.utils.logging_utils import get_logger, setup_logging  # noqa: E402

log = get_logger("cli")


def _ctx(cfg):
    from app.pipeline.context import AppContext
    return AppContext.create(cfg)


def _print_summary(s: dict) -> None:
    if s.get("data_warning"):
        print("!! " + s["data_warning"])
    f = s["data_freshness"]
    print(f"\n{s['date']} | Regime {s['market_regime']} | Data {f['status']} (DB {f['latest_database_date']}, "
          f"ekspektasi {f['latest_expected_market_date']}) | Model {s['model_version']}")
    print(f"Discan {s['universe_scanned']}, tradeable {s['tradeable']} | {s['decision_counts']}")
    print(f"\n{s['headline']}")
    if s["recommendations"]:
        print(f"{'#':>2} {'Ticker':<6} {'Setup':<22} {'Skor':>4} {'P(bull)':>7} {'Entry':>15} {'SL':>8} {'TP1':>8} {'TP2':>8} {'R/R':>5} {'Lot':>5} Decision")
        for r in s["recommendations"]:
            print(f"{r['rank']:>2} {r['ticker']:<6} {r['setup']:<22} {r['score']:>4.0f} {r['probability_bullish']:>7.0%} "
                  f"{r['entry_low']:>7,.0f}-{r['entry_high']:<7,.0f} {r['stop_loss']:>8,.0f} {r['take_profit_1']:>8,.0f} "
                  f"{r['take_profit_2']:>8,.0f} {r['risk_reward']:>5.2f} {r['lots']:>5} {r['decision']}")
    if s.get("watchlist"):
        print("Watchlist: " + ", ".join(f"{w['ticker']}({w['setup']})" for w in s["watchlist"][:8]))
    print(s["disclaimer"])


def cmd_health(cfg, a):
    from app.pipeline.health import format_health, health_check, health_json
    ctx = _ctx(cfg)
    h = health_check(ctx, check_provider=not a.no_provider)
    print(health_json(h) if a.json else format_health(h))
    return 0 if h["ok"] else 3


def cmd_setup(cfg, a):
    from app.pipeline.jobs import job_setup
    out = job_setup(_ctx(cfg), skip_backtest=a.skip_backtest)
    tr = out["train"]
    print(f"Setup selesai. Model {tr['version']}: {tr['decision']} {('— ' + '; '.join(tr['reasons'])) if tr.get('reasons') else ''}")
    ing = out["ingest"]["ingestion"]
    print(f"Data: +{ing['rows_inserted']} baris, {ing['stocks_processed']} emiten, gagal {ing['stocks_failed']}")
    if "backtest" in out:
        for k, v in out["backtest"].items():
            if v and "strategy" in v:
                print(f"Backtest {k}: return {v['strategy'].get('total_return', 0):+.1%} vs IHSG {v['ihsg_buy_hold'].get('total_return', 0):+.1%}, "
                      f"trades {v['strategy'].get('number_of_trades', 0)}")
    return 0


def cmd_daily(cfg, a):
    from app.pipeline.jobs import job_daily
    s = job_daily(_ctx(cfg), skip_ingest=a.skip_ingest)
    _print_summary(s)
    print(f"\nRun {s['run_id']}: {s['run_status']}")
    return 0


def cmd_update_data(cfg, a):
    from app.pipeline.jobs import job_update_data
    out = job_update_data(_ctx(cfg), full_actions=a.actions)
    i = out["ingestion"]
    print(f"Ekspektasi tanggal bursa: {i['expected_date']} | IHSG +{i['index_rows']} | emiten diminta {i['stocks_requested']}, "
          f"up-to-date {i['stocks_up_to_date']}, diproses {i['stocks_processed']}, gagal {i['stocks_failed']}")
    print(f"Baris: +{i['rows_inserted']} baru, {i['rows_updated']} diperbarui, {i['rows_rejected']} ditolak validasi"
          + (f" | unduh ulang (split): {i['refetched']}" if i["refetched"] else ""))
    return 0


def cmd_validate(cfg, a):
    from app.pipeline.jobs import job_validate
    rep = job_validate(_ctx(cfg))
    for r in rep.itertuples():
        print(f"[{r.severity:<5}] {r.check:<36} {r.count:>7}  {r.detail or ''} {list(r.tickers)[:5] if len(r.tickers) else ''}")
    return 0


def cmd_features(cfg, a):
    from app.pipeline.jobs import job_features
    print(json.dumps(job_features(_ctx(cfg)), indent=2))
    return 0


def cmd_train(cfg, a):
    from app.pipeline.jobs import job_train
    out = job_train(_ctx(cfg), force=not a.if_due, compare=not a.skip_compare)
    if out["decision"] == "SKIPPED":
        print(out["reason"])
        return 0
    m = out["metrics"]
    print(f"{out['version']}: {out['decision']} (sebelumnya aktif: {out['previous_active']})")
    print(f"Model {m['classifiers']} | AUC {m['auc_mean']:.3f} ± {m['auc_std']:.3f} | ECE {m['ece_bullish']:.3f} | "
          f"fold proxy positif {m['positive_fold_ratio']:.0%}")
    if m.get("head_to_head"):
        print(f"Head-to-head holdout: {m['head_to_head']}")
    for r in out["reasons"]:
        print("  - " + r)
    return 0


def cmd_backtest(cfg, a):
    from app.pipeline.jobs import job_backtest
    out = job_backtest(_ctx(cfg), last_n_folds=a.folds, live=not a.no_live)
    for k, v in out.items():
        if not v:
            print(f"{k}: tidak ada data")
            continue
        s, b = v["strategy"], v.get("ihsg_buy_hold", {})
        t = v.get("technical_only")
        print(f"\n[{k}] {s.get('start')}..{s.get('end')} (setelah biaya)")
        print(f"  Strategi : return {s.get('total_return', 0):+.1%} | CAGR {s.get('cagr', 0):+.1%} | MaxDD {s.get('max_drawdown', 0):.1%} | "
              f"Sharpe {s.get('sharpe', 0):.2f} | trades {s.get('number_of_trades', 0)} | win {s.get('win_rate', float('nan')):.0%} | "
              f"PF {s.get('profit_factor', float('nan')):.2f}")
        if t:
            print(f"  Teknikal : return {t.get('total_return', 0):+.1%} | Sharpe {t.get('sharpe', 0):.2f} | trades {t.get('number_of_trades', 0)}")
        if b:
            print(f"  IHSG B&H : return {b.get('total_return', 0):+.1%} | MaxDD {b.get('max_drawdown', 0):.1%} | Sharpe {b.get('sharpe', 0):.2f}")
    return 0


def cmd_scan(cfg, a):
    from app.pipeline.jobs import job_scan
    s = job_scan(_ctx(cfg), date=a.date, save=not a.no_save)
    _print_summary(s)
    if a.json:
        print(json.dumps(s, indent=2, default=str, ensure_ascii=False))
    return 0


def cmd_predict(cfg, a):
    from app.pipeline.jobs import job_predict
    from app.scanner.scanner import format_analysis
    rec = job_predict(_ctx(cfg), a.ticker, a.date)
    print(format_analysis(rec))
    print(f"Status data: {rec['data_freshness']}")
    if a.json:
        print(json.dumps(rec, indent=2, default=str, ensure_ascii=False))
    return 0


def cmd_evaluate(cfg, a):
    from app.pipeline.jobs import job_evaluate
    print(json.dumps(job_evaluate(_ctx(cfg)), indent=2, default=str))
    return 0


def cmd_models(cfg, a):
    ctx = _ctx(cfg)
    if a.promote:
        ctx.models.promote(a.promote, "manual override")
        print(f"{a.promote} sekarang ACTIVE")
    v = ctx.models.list_versions()
    print(v[["version", "status", "created_at", "train_end", "classifiers", "storage_backend", "artifact_bytes", "notes"]].to_string(index=False)
          if len(v) else "Belum ada model.")
    return 0


def cmd_make_sample(cfg, a):
    from app.data.sample import generate_sample_dataset
    out = resolve_path(cfg, a.out)
    generate_sample_dataset(out, n_tickers=a.tickers, start=a.start, end=a.end, seed=a.seed)
    print(f"Dataset CONTOH (sintetis) dibuat di {out}")
    return 0


def cmd_db_schema(cfg, a):
    from app.database.schema import postgres_sql_file
    p = resolve_path(cfg, "sql/schema_postgres.sql")
    p.write_text(postgres_sql_file(), encoding="utf-8")
    print(f"Skema PostgreSQL ditulis ke {p}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="Swing Stock Predictor — BEI")
    p.add_argument("--config", default=None, help="folder config (default: config/)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--as-of", default=None, help="simulasikan tanggal (YYYY-MM-DD)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("health"); s.add_argument("--json", action="store_true"); s.add_argument("--no-provider", action="store_true"); s.set_defaults(fn=cmd_health)
    s = sub.add_parser("setup"); s.add_argument("--skip-backtest", action="store_true"); s.set_defaults(fn=cmd_setup)
    s = sub.add_parser("daily"); s.add_argument("--skip-ingest", action="store_true"); s.set_defaults(fn=cmd_daily)
    s = sub.add_parser("update-data"); s.add_argument("--actions", action="store_true", help="cek corporate action semua emiten"); s.set_defaults(fn=cmd_update_data)
    sub.add_parser("validate-data").set_defaults(fn=cmd_validate)
    sub.add_parser("features").set_defaults(fn=cmd_features)
    s = sub.add_parser("train"); s.add_argument("--if-due", action="store_true", help="hanya bila model aktif sudah tua")
    s.add_argument("--skip-compare", action="store_true"); s.set_defaults(fn=cmd_train)
    s = sub.add_parser("backtest"); s.add_argument("--folds", type=int, default=None); s.add_argument("--no-live", action="store_true"); s.set_defaults(fn=cmd_backtest)
    s = sub.add_parser("scan"); s.add_argument("--date"); s.add_argument("--json", action="store_true"); s.add_argument("--no-save", action="store_true"); s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("predict"); s.add_argument("ticker"); s.add_argument("--date"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_predict)
    sub.add_parser("evaluate").set_defaults(fn=cmd_evaluate)
    s = sub.add_parser("models"); s.add_argument("--promote", metavar="VERSION"); s.set_defaults(fn=cmd_models)
    s = sub.add_parser("make-sample"); s.add_argument("--out", default="data/raw/sample"); s.add_argument("--tickers", type=int, default=45)
    s.add_argument("--start", default="2017-01-02"); s.add_argument("--end", default="2026-10-02"); s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_make_sample)
    sub.add_parser("db-schema").set_defaults(fn=cmd_db_schema)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config, args.set)
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 2
    if args.as_of:
        cfg["_as_of"] = args.as_of
    setup_logging(get(cfg, "project.log_level", "INFO"), resolve_path(cfg, "data/cache/logs"))
    try:
        return int(args.fn(cfg, args) or 0)
    except Exception as e:  # error handling terpusat; traceback lengkap ada di log & system_logs
        log.exception("Perintah '%s' gagal: %s", args.cmd, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
