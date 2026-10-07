"""Skema database (§20) — didefinisikan sekali, di-render ke SQLite atau PostgreSQL.

Tipe logis → fisik:
  ID     : INTEGER PRIMARY KEY AUTOINCREMENT | BIGSERIAL PRIMARY KEY
  TEXT, INT(BIGINT), REAL(DOUBLE PRECISION), DATE (TEXT ISO | DATE), TS (TEXT ISO | TIMESTAMPTZ),
  BOOL (INTEGER 0/1 | BOOLEAN), JSON (TEXT | JSONB→disimpan TEXT agar portabel), BLOB (BLOB | BYTEA)
Migrasi bersifat additive & idempoten (CREATE ... IF NOT EXISTS), dicatat di `schema_migrations`.
"""
from __future__ import annotations

from app.database.db import Database

SCHEMA_VERSION = 1

TYPES = {
    "sqlite": {"ID": "INTEGER PRIMARY KEY AUTOINCREMENT", "TEXT": "TEXT", "INT": "INTEGER", "REAL": "REAL",
               "DATE": "TEXT", "TS": "TEXT", "BOOL": "INTEGER", "JSON": "TEXT", "BLOB": "BLOB"},
    "postgres": {"ID": "BIGSERIAL PRIMARY KEY", "TEXT": "TEXT", "INT": "BIGINT", "REAL": "DOUBLE PRECISION",
                 "DATE": "DATE", "TS": "TIMESTAMPTZ", "BOOL": "BOOLEAN", "JSON": "TEXT", "BLOB": "BYTEA"},
}

# (nama_tabel, [(kolom, tipe, constraint)], [unique keys], [index columns])
TABLES = [
    ("stocks", [("id", "ID", ""), ("ticker", "TEXT", "NOT NULL"), ("name", "TEXT", ""), ("sector", "TEXT", ""),
                ("subsector", "TEXT", ""), ("board", "TEXT", ""), ("listing_date", "DATE", ""),
                ("delisting_date", "DATE", ""), ("is_active", "BOOL", "NOT NULL"), ("previous_ticker", "TEXT", ""),
                ("first_seen", "TS", ""), ("last_seen", "TS", ""), ("updated_at", "TS", "")],
     [["ticker"]], [["is_active"], ["sector"]]),
    ("price_history", [("id", "ID", ""), ("stock_id", "INT", "NOT NULL REFERENCES stocks(id)"), ("date", "DATE", "NOT NULL"),
                       ("open", "REAL", ""), ("high", "REAL", ""), ("low", "REAL", ""), ("close", "REAL", ""),
                       ("volume", "REAL", ""), ("value", "REAL", ""), ("frequency", "REAL", ""),
                       ("is_adjusted", "BOOL", ""), ("source", "TEXT", ""), ("ingested_at", "TS", "")],
     [["stock_id", "date"]], [["date"]]),
    ("corporate_actions", [("id", "ID", ""), ("stock_id", "INT", "NOT NULL REFERENCES stocks(id)"), ("ex_date", "DATE", "NOT NULL"),
                           ("action", "TEXT", "NOT NULL"), ("ratio", "REAL", ""), ("amount", "REAL", ""),
                           ("source", "TEXT", ""), ("processed_at", "TS", "")],
     [["stock_id", "ex_date", "action"]], [["ex_date"]]),
    ("market_index", [("id", "ID", ""), ("symbol", "TEXT", "NOT NULL"), ("date", "DATE", "NOT NULL"), ("open", "REAL", ""),
                      ("high", "REAL", ""), ("low", "REAL", ""), ("close", "REAL", ""), ("volume", "REAL", ""),
                      ("source", "TEXT", ""), ("ingested_at", "TS", "")],
     [["symbol", "date"]], [["date"]]),
    ("sector_data", [("id", "ID", ""), ("date", "DATE", "NOT NULL"), ("sector", "TEXT", "NOT NULL"), ("ret5", "REAL", ""),
                     ("ret20", "REAL", ""), ("ret60", "REAL", ""), ("breadth", "REAL", ""), ("volume_mom", "REAL", ""),
                     ("rs20", "REAL", ""), ("score", "REAL", ""), ("rank", "INT", ""), ("n_stocks", "INT", "")],
     [["date", "sector"]], [["date"]]),
    ("features", [("id", "ID", ""), ("stock_id", "INT", "NOT NULL REFERENCES stocks(id)"), ("date", "DATE", "NOT NULL"),
                  ("feature_version", "TEXT", "NOT NULL"), ("payload", "JSON", "")],
     [["stock_id", "date", "feature_version"]], [["date"]]),
    ("predictions", [("id", "ID", ""), ("prediction_date", "DATE", "NOT NULL"), ("stock_id", "INT", "NOT NULL REFERENCES stocks(id)"),
                     ("ticker", "TEXT", "NOT NULL"), ("model_version", "TEXT", "NOT NULL"), ("horizon", "INT", ""),
                     ("decision", "TEXT", ""), ("setup", "TEXT", ""), ("score", "REAL", ""), ("market_regime", "TEXT", ""),
                     ("prob_bearish", "REAL", ""), ("prob_neutral", "REAL", ""), ("prob_bullish", "REAL", ""),
                     ("expected_return", "REAL", ""), ("prob_hit_tp", "REAL", ""), ("entry_low", "REAL", ""),
                     ("entry_ideal", "REAL", ""), ("entry_high", "REAL", ""), ("stop_loss", "REAL", ""), ("tp1", "REAL", ""),
                     ("tp2", "REAL", ""), ("risk_reward", "REAL", ""), ("position_size", "INT", ""), ("lots", "INT", ""),
                     ("capital_required", "REAL", ""), ("estimated_loss", "REAL", ""), ("confidence", "TEXT", ""),
                     ("close_price", "REAL", ""), ("data_status", "TEXT", ""), ("reasons", "JSON", ""), ("risks", "JSON", ""),
                     ("reject_reasons", "JSON", ""), ("run_id", "TEXT", ""), ("created_at", "TS", "")],
     [["prediction_date", "stock_id", "model_version"]], [["ticker"], ["decision"], ["model_version"]]),
    ("prediction_evaluations", [("id", "ID", ""), ("prediction_id", "INT", "NOT NULL REFERENCES predictions(id)"),
                                ("evaluated_at", "TS", ""), ("actual_return_3d", "REAL", ""), ("actual_return_5d", "REAL", ""),
                                ("actual_return_10d", "REAL", ""), ("mfe", "REAL", ""), ("mae", "REAL", ""),
                                ("entry_filled", "BOOL", ""), ("hit_stop", "BOOL", ""), ("hit_tp1", "BOOL", ""),
                                ("hit_tp2", "BOOL", ""), ("actual_class", "INT", ""), ("prediction_correct", "BOOL", ""),
                                ("outcome", "TEXT", "")],
     [["prediction_id"]], []),
    ("trading_signals", [("id", "ID", ""), ("signal_date", "DATE", "NOT NULL"), ("stock_id", "INT", "NOT NULL REFERENCES stocks(id)"),
                         ("ticker", "TEXT", "NOT NULL"), ("rank", "INT", ""), ("decision", "TEXT", ""), ("setup", "TEXT", ""),
                         ("score", "REAL", ""), ("prob_bullish", "REAL", ""), ("expected_return", "REAL", ""),
                         ("entry_low", "REAL", ""), ("entry_ideal", "REAL", ""), ("entry_high", "REAL", ""),
                         ("stop_loss", "REAL", ""), ("tp1", "REAL", ""), ("tp2", "REAL", ""), ("risk_reward", "REAL", ""),
                         ("lots", "INT", ""), ("confidence", "TEXT", ""), ("model_version", "TEXT", ""), ("run_id", "TEXT", "")],
     [["signal_date", "stock_id"]], [["signal_date"]]),
    ("backtest_runs", [("id", "ID", ""), ("run_id", "TEXT", "NOT NULL"), ("created_at", "TS", ""), ("kind", "TEXT", ""),
                       ("period_start", "DATE", ""), ("period_end", "DATE", ""), ("model_version", "TEXT", ""),
                       ("config_hash", "TEXT", ""), ("metrics", "JSON", ""), ("benchmark", "JSON", ""), ("status", "TEXT", "")],
     [["run_id"]], [["created_at"]]),
    ("backtest_trades", [("id", "ID", ""), ("backtest_run_id", "TEXT", "NOT NULL"), ("ticker", "TEXT", ""), ("setup", "TEXT", ""),
                         ("entry_date", "DATE", ""), ("exit_date", "DATE", ""), ("entry_price", "REAL", ""),
                         ("exit_price", "REAL", ""), ("shares", "INT", ""), ("net_pnl", "REAL", ""), ("net_return", "REAL", ""),
                         ("r_multiple", "REAL", ""), ("exit_reason", "TEXT", ""), ("fees", "REAL", "")],
     [["backtest_run_id", "ticker", "entry_date"]], [["backtest_run_id"]]),
    ("model_versions", [("id", "ID", ""), ("version", "TEXT", "NOT NULL"), ("status", "TEXT", "NOT NULL"), ("created_at", "TS", ""),
                        ("promoted_at", "TS", ""), ("train_start", "DATE", ""), ("train_end", "DATE", ""),
                        ("feature_version", "TEXT", ""), ("config_hash", "TEXT", ""), ("classifiers", "TEXT", ""),
                        ("metrics", "JSON", ""), ("storage_backend", "TEXT", ""), ("storage_uri", "TEXT", ""),
                        ("artifact", "BLOB", ""), ("artifact_sha256", "TEXT", ""), ("artifact_bytes", "INT", ""), ("notes", "TEXT", "")],
     [["version"]], [["status"]]),
    ("pipeline_runs", [("id", "ID", ""), ("run_id", "TEXT", "NOT NULL"), ("run_type", "TEXT", "NOT NULL"), ("started_at", "TS", ""),
                       ("finished_at", "TS", ""), ("status", "TEXT", ""), ("stocks_processed", "INT", ""),
                       ("stocks_failed", "INT", ""), ("rows_inserted", "INT", ""), ("rows_updated", "INT", ""),
                       ("model_version", "TEXT", ""), ("data_status", "TEXT", ""), ("market_date", "DATE", ""),
                       ("trigger", "TEXT", ""), ("summary", "JSON", ""), ("error_message", "TEXT", ""), ("created_at", "TS", "")],
     [["run_id"]], [["run_type", "started_at"]]),
    ("data_sources", [("id", "ID", ""), ("name", "TEXT", "NOT NULL"), ("type", "TEXT", ""), ("priority", "INT", ""),
                      ("enabled", "BOOL", ""), ("last_success_at", "TS", ""), ("last_error_at", "TS", ""),
                      ("last_error", "TEXT", ""), ("rows_fetched_total", "INT", "")],
     [["name"]], []),
    ("system_logs", [("id", "ID", ""), ("run_id", "TEXT", ""), ("ts", "TS", ""), ("level", "TEXT", ""), ("logger", "TEXT", ""),
                     ("message", "TEXT", "")],
     [], [["run_id"], ["ts"]]),
    ("reports", [("id", "ID", ""), ("report_date", "DATE", "NOT NULL"), ("kind", "TEXT", "NOT NULL"), ("filename", "TEXT", "NOT NULL"),
                 ("content", "BLOB", ""), ("content_type", "TEXT", ""), ("storage_backend", "TEXT", ""),
                 ("storage_uri", "TEXT", ""), ("run_id", "TEXT", ""), ("created_at", "TS", "")],
     [["report_date", "kind", "filename"]], [["report_date"]]),
    ("schema_migrations", [("version", "INT", "PRIMARY KEY"), ("applied_at", "TS", "")], [], []),
]

TABLE_NAMES = [t[0] for t in TABLES]


def render_ddl(dialect: str) -> list[str]:
    types = TYPES[dialect]
    out = []
    for name, cols, uniques, indexes in TABLES:
        defs = [f"{c} {types[t]} {cons}".strip() for c, t, cons in cols]
        for u in uniques:
            defs.append(f"UNIQUE ({', '.join(u)})")
        out.append(f"CREATE TABLE IF NOT EXISTS {name} (\n  " + ",\n  ".join(defs) + "\n)")
        for idx in indexes:
            out.append(f"CREATE INDEX IF NOT EXISTS ix_{name}_{'_'.join(idx)} ON {name} ({', '.join(idx)})")
    return out


def migrate(db: Database) -> int:
    """Buat tabel yang belum ada. Aman dijalankan berulang (setiap run daily memanggilnya)."""
    db.executescript(render_ddl(db.dialect))
    current = db.scalar("SELECT MAX(version) FROM schema_migrations") or 0
    if current < SCHEMA_VERSION:
        from datetime import datetime, timezone
        db.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                   (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return SCHEMA_VERSION


def postgres_sql_file() -> str:
    head = ("-- Skema PostgreSQL untuk Supabase (dihasilkan oleh `python main.py db-schema`).\n"
            "-- Opsional: jalankan di Supabase SQL Editor. `python main.py setup` juga membuatnya otomatis.\n\n")
    return head + ";\n\n".join(render_ddl("postgres")) + ";\n"
