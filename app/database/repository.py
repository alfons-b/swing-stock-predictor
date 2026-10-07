"""Repository — semua akses tabel lewat sini (persistence layer). Modul lain tidak menulis SQL."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.database.db import Database


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(v) -> str | None:
    if v is None:
        return None
    return json.dumps(v, default=str, ensure_ascii=False)


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ================================================================ stocks / universe
    def stocks(self, active_only: bool = False) -> pd.DataFrame:
        sql = "SELECT * FROM stocks" + (" WHERE is_active = ?" if active_only else "") + " ORDER BY ticker"
        df = self.db.query_df(sql, (True,) if active_only else (), parse_dates=["listing_date", "delisting_date"])
        if len(df):
            df["is_active"] = df["is_active"].astype(bool)
        return df

    def upsert_stocks(self, df: pd.DataFrame) -> tuple[int, int]:
        cols = ["ticker", "name", "sector", "subsector", "board", "listing_date", "delisting_date", "is_active",
                "previous_ticker", "listed_shares", "first_seen", "last_seen", "updated_at"]
        d = df.reindex(columns=cols)
        return self.db.upsert("stocks", d, keys=["ticker"],
                              update=[c for c in cols if c not in ("first_seen", "previous_ticker")])

    def stock_ids(self) -> dict[str, int]:
        return {t: int(i) for i, t in self.db.query("SELECT id, ticker FROM stocks")}

    def set_inactive(self, tickers: list[str], when: str | None = None) -> int:
        n = 0
        for t in tickers:
            n += self.db.execute("UPDATE stocks SET is_active = ?, updated_at = ? WHERE ticker = ?", (False, when or now_utc(), t))
        return n

    def rename_ticker(self, old: str, new: str) -> bool:
        if self.db.scalar("SELECT COUNT(*) FROM stocks WHERE ticker = ?", (new,)):
            return False  # kode baru sudah ada — jangan menimpa
        n = self.db.execute("UPDATE stocks SET ticker = ?, previous_ticker = ?, updated_at = ? WHERE ticker = ?",
                            (new, old, now_utc(), old))
        return n > 0

    # ================================================================ prices
    def latest_price_dates(self) -> pd.DataFrame:
        return self.db.query_df("SELECT s.id AS stock_id, s.ticker, MAX(p.date) AS last_date, COUNT(p.id) AS n_rows "
                                "FROM stocks s LEFT JOIN price_history p ON p.stock_id = s.id GROUP BY s.id, s.ticker",
                                parse_dates=["last_date"])

    def max_price_date(self):
        v = self.db.scalar("SELECT MAX(date) FROM price_history")
        return pd.Timestamp(v) if v else None

    def upsert_prices(self, df: pd.DataFrame) -> tuple[int, int]:
        cols = ["stock_id", "date", "open", "high", "low", "close", "volume", "value", "frequency", "is_adjusted",
                "source", "ingested_at"]
        d = df.reindex(columns=cols).copy()
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        d["ingested_at"] = now_utc()
        return self.db.upsert("price_history", d, keys=["stock_id", "date"])

    def delete_prices(self, stock_id: int) -> int:
        return self.db.execute("DELETE FROM price_history WHERE stock_id = ?", (stock_id,))

    def load_prices(self, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        sql = ("SELECT s.ticker, p.date, p.open, p.high, p.low, p.close, p.volume, p.value, p.frequency, p.is_adjusted "
               "FROM price_history p JOIN stocks s ON s.id = p.stock_id WHERE 1=1")
        params = []
        if start:
            sql += " AND p.date >= ?"
            params.append(str(pd.Timestamp(start).date()))
        if end:
            sql += " AND p.date <= ?"
            params.append(str(pd.Timestamp(end).date()))
        df = self.db.query_df(sql + " ORDER BY s.ticker, p.date", params, parse_dates=["date"])
        for c in ("open", "high", "low", "close", "volume", "value", "frequency"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        df["is_adjusted"] = df["is_adjusted"].fillna(False).astype(bool)
        df["ticker"] = df["ticker"].astype(object)
        return df

    def price_counts(self) -> dict:
        r = self.db.query("SELECT COUNT(*), COUNT(DISTINCT stock_id), MIN(date), MAX(date) FROM price_history")[0]
        dup = self.db.scalar("SELECT COUNT(*) FROM (SELECT stock_id, date FROM price_history GROUP BY stock_id, date "
                             "HAVING COUNT(*) > 1) x")
        return {"rows": r[0], "stocks": r[1], "min_date": r[2], "max_date": r[3], "duplicates": dup}

    # ================================================================ index
    def max_index_date(self, symbol: str):
        v = self.db.scalar("SELECT MAX(date) FROM market_index WHERE symbol = ?", (symbol,))
        return pd.Timestamp(v) if v else None

    def upsert_index(self, df: pd.DataFrame, symbol: str, source: str) -> tuple[int, int]:
        d = df[["date", "open", "high", "low", "close", "volume"]].copy()
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        d["symbol"], d["source"], d["ingested_at"] = symbol, source, now_utc()
        return self.db.upsert("market_index", d, keys=["symbol", "date"])

    def load_index(self, symbol: str, start: str | None = None) -> pd.DataFrame:
        sql, params = "SELECT date, open, high, low, close, volume FROM market_index WHERE symbol = ?", [symbol]
        if start:
            sql += " AND date >= ?"
            params.append(str(pd.Timestamp(start).date()))
        df = self.db.query_df(sql + " ORDER BY date", params, parse_dates=["date"])
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
        return df

    def index_dates(self, symbol: str) -> list[pd.Timestamp]:
        return [pd.Timestamp(r[0]) for r in self.db.query("SELECT date FROM market_index WHERE symbol = ? ORDER BY date", (symbol,))]

    # ================================================================ corporate actions
    def upsert_actions(self, df: pd.DataFrame) -> tuple[int, int]:
        if df is None or df.empty:
            return 0, 0
        d = df.reindex(columns=["stock_id", "ex_date", "action", "ratio", "amount", "source"]).copy()
        d["ex_date"] = pd.to_datetime(d["ex_date"]).dt.strftime("%Y-%m-%d")
        return self.db.upsert("corporate_actions", d, keys=["stock_id", "ex_date", "action"])

    def load_actions(self) -> pd.DataFrame:
        df = self.db.query_df("SELECT s.ticker, c.ex_date, c.action, c.ratio, c.amount, c.processed_at "
                              "FROM corporate_actions c JOIN stocks s ON s.id = c.stock_id", parse_dates=["ex_date"])
        df["ticker"] = df["ticker"].astype(object)
        return df

    def mark_actions_processed(self, ticker: str) -> None:
        self.db.execute("UPDATE corporate_actions SET processed_at = ? WHERE stock_id = (SELECT id FROM stocks WHERE ticker = ?)",
                        (now_utc(), ticker))

    # ================================================================ analytics snapshots
    def save_sector_data(self, df: pd.DataFrame) -> tuple[int, int]:
        return self.db.upsert("sector_data", df, keys=["date", "sector"])

    def save_features_snapshot(self, df: pd.DataFrame, keep_days: int) -> tuple[int, int]:
        res = self.db.upsert("features", df, keys=["stock_id", "date", "feature_version"])
        dates = [r[0] for r in self.db.query("SELECT DISTINCT date FROM features ORDER BY date DESC")]
        if len(dates) > keep_days:
            self.db.execute("DELETE FROM features WHERE date < ?", (dates[keep_days - 1],))
        return res

    # ================================================================ predictions
    def save_predictions(self, df: pd.DataFrame) -> tuple[int, int]:
        return self.db.upsert("predictions", df, keys=["prediction_date", "stock_id", "model_version"])

    def save_signals(self, df: pd.DataFrame, signal_date: str) -> tuple[int, int]:
        self.db.execute("DELETE FROM trading_signals WHERE signal_date = ?", (signal_date,))  # ranking hari itu diganti utuh
        if df.empty:
            return 0, 0
        return self.db.upsert("trading_signals", df, keys=["signal_date", "stock_id"])

    def pending_evaluations(self) -> pd.DataFrame:
        return self.db.query_df(
            "SELECT p.id, p.prediction_date, p.ticker, p.stock_id, p.decision, p.prob_bearish, p.prob_neutral, p.prob_bullish, "
            "p.entry_high, p.stop_loss, p.tp1, p.tp2, p.close_price FROM predictions p "
            "LEFT JOIN prediction_evaluations e ON e.prediction_id = p.id WHERE e.id IS NULL", parse_dates=["prediction_date"])

    def save_evaluations(self, df: pd.DataFrame) -> tuple[int, int]:
        return self.db.upsert("prediction_evaluations", df, keys=["prediction_id"])

    def prediction_history(self, limit: int = 5000) -> pd.DataFrame:
        return self.db.query_df(
            "SELECT p.prediction_date, p.ticker, p.decision, p.setup, p.score, p.prob_bullish, p.expected_return, "
            "p.entry_ideal, p.stop_loss, p.tp1, p.tp2, p.risk_reward, p.model_version, e.actual_return_5d, e.mfe, e.mae, "
            "e.hit_stop, e.hit_tp1, e.hit_tp2, e.prediction_correct, e.outcome FROM predictions p "
            "LEFT JOIN prediction_evaluations e ON e.prediction_id = p.id "
            f"ORDER BY p.prediction_date DESC, p.score DESC LIMIT {int(limit)}", parse_dates=["prediction_date"])

    def latest_signals(self) -> pd.DataFrame:
        d = self.db.scalar("SELECT MAX(signal_date) FROM trading_signals")
        if not d:
            return pd.DataFrame()
        return self.db.query_df("SELECT * FROM trading_signals WHERE signal_date = ? ORDER BY rank", (d,))

    # ================================================================ backtest
    def save_backtest(self, run_id: str, kind: str, metrics: dict, benchmark: dict, trades: pd.DataFrame,
                      model_version: str, cfg_hash: str) -> None:
        self.db.upsert("backtest_runs", [{"run_id": run_id, "created_at": now_utc(), "kind": kind,
                                          "period_start": metrics.get("start"), "period_end": metrics.get("end"),
                                          "model_version": model_version, "config_hash": cfg_hash,
                                          "metrics": _json(metrics), "benchmark": _json(benchmark), "status": "DONE"}],
                       keys=["run_id"], count=False)
        if trades is not None and len(trades):
            t = trades.rename(columns={"avg_exit_price": "exit_price"}).reindex(
                columns=["ticker", "setup", "entry_date", "exit_date", "entry_price", "exit_price", "shares", "net_pnl",
                         "net_return", "r_multiple", "exit_reason", "fees"]).copy()
            for c in ("entry_date", "exit_date"):
                t[c] = pd.to_datetime(t[c]).dt.strftime("%Y-%m-%d")
            t["backtest_run_id"] = run_id
            self.db.upsert("backtest_trades", t, keys=["backtest_run_id", "ticker", "entry_date"], count=False)

    def backtest_runs(self, limit: int = 20) -> pd.DataFrame:
        return self.db.query_df(f"SELECT run_id, created_at, kind, period_start, period_end, model_version, metrics, benchmark "
                                f"FROM backtest_runs ORDER BY created_at DESC LIMIT {int(limit)}")

    # ================================================================ pipeline runs & logs
    def start_run(self, run_id: str, run_type: str, trigger: str) -> None:
        self.db.upsert("pipeline_runs", [{"run_id": run_id, "run_type": run_type, "started_at": now_utc(), "status": "RUNNING",
                                          "trigger": trigger, "created_at": now_utc()}], keys=["run_id"], count=False)

    def finish_run(self, run_id: str, **fields) -> None:
        fields = {k: (_json(v) if k == "summary" else v) for k, v in fields.items()}
        fields["finished_at"] = now_utc()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE pipeline_runs SET {sets} WHERE run_id = ?", list(fields.values()) + [run_id])

    def pipeline_runs(self, limit: int = 50) -> pd.DataFrame:
        return self.db.query_df(f"SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT {int(limit)}")

    def last_run(self, run_type: str | None = None, status: str | None = None) -> dict | None:
        sql, params = "SELECT * FROM pipeline_runs WHERE 1=1", []
        if run_type:
            sql += " AND run_type = ?"
            params.append(run_type)
        if status:
            sql += " AND status = ?"
            params.append(status)
        df = self.db.query_df(sql + " ORDER BY started_at DESC LIMIT 1", params)
        return df.iloc[0].to_dict() if len(df) else None

    def write_logs(self, rows: list[dict]) -> None:
        if rows:
            cur = self.db.conn.cursor()
            sql = self.db._sql("INSERT INTO system_logs (run_id, ts, level, logger, message) VALUES (?, ?, ?, ?, ?)")
            cur.executemany(sql, [(r["run_id"], r["ts"], r["level"], r["logger"], r["message"][:4000]) for r in rows])
            self.db.conn.commit()

    def source_status(self, name: str, type_: str, priority: int, enabled: bool, ok: bool, error: str | None = None,
                      rows: int = 0) -> None:
        prev = self.db.scalar("SELECT rows_fetched_total FROM data_sources WHERE name = ?", (name,)) or 0
        row = {"name": name, "type": type_, "priority": priority, "enabled": enabled, "rows_fetched_total": int(prev) + rows}
        if ok:
            row["last_success_at"] = now_utc()
        else:
            row["last_error_at"], row["last_error"] = now_utc(), (error or "")[:1000]
        self.db.upsert("data_sources", [row], keys=["name"], count=False)
