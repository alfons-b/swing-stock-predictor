"""Database abstraction — SQLite (dev/test/CI) dan PostgreSQL (production / Supabase).

Keputusan desain: lapisan tipis di atas DB-API (sqlite3 / psycopg 3), bukan ORM.
- Semua SQL ditulis dengan placeholder `?`; dikonversi ke `%s` untuk Postgres.
- UPSERT memakai `INSERT ... ON CONFLICT (...) DO UPDATE`, didukung keduanya → idempoten.
- Skema didefinisikan sekali (schema.py) lalu di-render per dialek.
"""
from __future__ import annotations

import datetime
import decimal
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from app.utils.logging_utils import get_logger

log = get_logger(__name__)


class DatabaseError(RuntimeError):
    pass


def _py(v):
    """Konversi nilai numpy/pandas ke tipe Python yang diterima driver DB."""
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else (v.strftime("%Y-%m-%d") if v == v.normalize() else v.isoformat())
    if v is pd.NaT:
        return None
    if isinstance(v, datetime.datetime):  # PostgreSQL mengembalikan objek tanggal; SQLite mengembalikan teks
        return v.isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


class Database:
    dialect = "base"
    placeholder = "?"

    def __init__(self, url: str):
        self.url = url
        self._conn = None

    # ------------------------------------------------------------------ factory
    @staticmethod
    def from_url(url: str, root: str | Path | None = None) -> "Database":
        if not url:
            raise DatabaseError("DATABASE_URL kosong")
        if url.startswith("sqlite"):
            return SQLiteDatabase(url, root)
        if url.startswith(("postgres://", "postgresql://")):
            return PostgresDatabase(url)
        raise DatabaseError(f"Skema URL database tidak didukung: {url.split(':')[0]}")

    # ------------------------------------------------------------------ core
    def connect(self):
        raise NotImplementedError

    @property
    def conn(self):
        if self._conn is None:
            self._conn = self.connect()
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _sql(self, sql: str) -> str:
        return sql if self.placeholder == "?" else sql.replace("?", self.placeholder)

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), [_py(p) for p in params])
        n = cur.rowcount
        self.conn.commit()
        return n

    def executescript(self, statements: list[str]) -> None:
        cur = self.conn.cursor()
        for st in statements:
            cur.execute(st)
        self.conn.commit()

    def query(self, sql: str, params: tuple | list = ()) -> list[tuple]:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), [_py(p) for p in params])
        return cur.fetchall()

    def query_df(self, sql: str, params: tuple | list = (), parse_dates: list[str] | None = None) -> pd.DataFrame:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), [_py(p) for p in params])
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
        for c in parse_dates or []:
            if c in df:
                df[c] = pd.to_datetime(df[c])
        return df

    def scalar(self, sql: str, params: tuple | list = ()):
        rows = self.query(sql, params)
        return rows[0][0] if rows else None

    @contextmanager
    def transaction(self):
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------ upsert
    def upsert(self, table: str, df: pd.DataFrame | list[dict], keys: list[str], update: list[str] | None = None,
               batch_size: int = 2000, count: bool = True) -> tuple[int, int]:
        """Idempotent UPSERT. Return (inserted, updated).

        Menjalankan dua kali dengan data sama → tidak ada duplikat (unique constraint pada `keys`).
        """
        if isinstance(df, list):
            df = pd.DataFrame(df)
        if df is None or len(df) == 0:
            return 0, 0
        df = df.drop_duplicates(subset=keys, keep="last")
        cols = list(df.columns)
        update = [c for c in (update if update is not None else cols) if c not in keys]
        ph = ", ".join([self.placeholder] * len(cols))
        conflict = ", ".join(keys)
        if update:
            set_clause = ", ".join(f"{c} = excluded.{c}" for c in update)
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
        else:
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph}) ON CONFLICT ({conflict}) DO NOTHING"
        existing = self._count_existing(table, df, keys) if count else 0
        rows = [tuple(_py(v) for v in r) for r in df.itertuples(index=False, name=None)]
        cur = self.conn.cursor()
        try:
            for i in range(0, len(rows), batch_size):
                cur.executemany(sql, rows[i:i + batch_size])
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return len(rows) - existing, existing if update else 0

    def _count_existing(self, table: str, df: pd.DataFrame, keys: list[str]) -> int:
        """Hitung baris yang sudah ada (untuk statistik inserted vs updated)."""
        k0 = keys[0]
        vals = [_py(v) for v in pd.unique(df[k0])]
        total = 0
        want = set(tuple(_py(v) for v in r) for r in df[keys].itertuples(index=False, name=None))
        extra, params = "", []
        if len(keys) > 1 and keys[1] in ("date", "prediction_date", "signal_date"):
            extra = f" AND {keys[1]} >= ? AND {keys[1]} <= ?"
            col = df[keys[1]]
            params = [_py(col.min()), _py(col.max())]
        for i in range(0, len(vals), 500):
            chunk = vals[i:i + 500]
            ph = ", ".join([self.placeholder] * len(chunk))
            sql = f"SELECT {', '.join(keys)} FROM {table} WHERE {k0} IN ({ph}){extra.replace('?', self.placeholder)}"
            cur = self.conn.cursor()
            cur.execute(sql, chunk + params)
            for r in cur.fetchall():
                if tuple(_py(v) if not isinstance(v, (bytes, memoryview)) else v for v in r) in want:
                    total += 1
        return total


class SQLiteDatabase(Database):
    dialect = "sqlite"
    placeholder = "?"

    def __init__(self, url: str, root=None):
        super().__init__(url)
        path = url.split("sqlite:///", 1)[-1] if "sqlite:///" in url else url.split("sqlite://", 1)[-1]
        if path in ("", ":memory:"):
            self.path = ":memory:"
        else:
            p = Path(path)
            if not p.is_absolute() and root is not None:
                p = Path(root) / p
            p.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(p)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL") if self.path != ":memory:" else None
        return conn

    def describe(self) -> str:
        return f"sqlite:{self.path}"


class PostgresDatabase(Database):
    dialect = "postgres"
    placeholder = "%s"

    def connect(self):
        try:
            import psycopg
        except ImportError as e:  # pragma: no cover
            raise DatabaseError("psycopg belum terpasang: pip install 'psycopg[binary]'") from e
        last = None
        for attempt in range(3):  # Supabase pooler kadang menolak koneksi sesaat
            try:
                return psycopg.connect(self.url, connect_timeout=20, prepare_threshold=None)
            except Exception as e:  # pragma: no cover - jaringan
                last = e
                time.sleep(2 ** attempt)
        raise DatabaseError(f"Gagal konek ke PostgreSQL: {type(last).__name__}") from last

    def describe(self) -> str:
        u = urlparse(self.url)
        return f"postgres:{u.hostname}:{u.port or 5432}{u.path}"  # tanpa user/password
