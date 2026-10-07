"""Health check (§53) — dipakai CLI `health`, awal pipeline daily, dan dashboard (halaman Data Health)."""
from __future__ import annotations

import json
import sys

import pandas as pd

from app import FEATURE_VERSION
from app.config import get, is_production
from app.pipeline.freshness import data_freshness

REQUIRED_PACKAGES = ["numpy", "pandas", "sklearn", "scipy", "yaml", "joblib"]


def check_environment(cfg: dict) -> list[str]:
    problems = []
    if sys.version_info < (3, 10):
        problems.append(f"Python >= 3.10 dibutuhkan (sekarang {sys.version.split()[0]})")
    import importlib
    for p in REQUIRED_PACKAGES:
        try:
            importlib.import_module(p)
        except ImportError:
            problems.append(f"Paket {p} belum terpasang")
    url = str(get(cfg, "database.url", ""))
    if is_production(cfg) and not url.startswith(("postgres://", "postgresql://")):
        problems.append("environment=production tetapi DATABASE_URL bukan PostgreSQL (set GitHub Secret DATABASE_URL)")
    if url.startswith(("postgres://", "postgresql://")):
        try:
            importlib.import_module("psycopg")
        except ImportError:
            problems.append("psycopg belum terpasang (pip install 'psycopg[binary]')")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(get(cfg, "calendar.timezone", "Asia/Jakarta"))
    except Exception:
        problems.append("Timezone Asia/Jakarta tidak tersedia (Windows: pip install tzdata)")
    return problems


def health_check(ctx, check_provider: bool = True) -> dict:
    cfg, repo = ctx.cfg, ctx.repo
    out: dict = {"checks": {}}

    def put(name, status, detail=""):
        out["checks"][name] = {"status": status, "detail": detail}

    env = check_environment(cfg)
    put("ENVIRONMENT", "OK" if not env else "FAIL", "; ".join(env))
    try:
        ctx.db.scalar("SELECT 1")
        put("DATABASE", "OK", ctx.db.describe())
    except Exception as e:
        put("DATABASE", "FAIL", f"{type(e).__name__}: {e}"[:200])
        out["ok"] = False
        return out

    provider_latest = None
    if check_provider:
        try:
            provider_latest, src = ctx.chain.latest_available_date()
            put("MARKET DATA PROVIDER", "OK" if provider_latest is not None else "FAIL",
                f"{src}: data terakhir {provider_latest.date()}" if provider_latest is not None else "tidak ada provider yang merespons")
        except Exception as e:
            put("MARKET DATA PROVIDER", "FAIL", f"{type(e).__name__}: {e}"[:200])
    n_active = int(ctx.db.scalar("SELECT COUNT(*) FROM stocks WHERE is_active = ?", (True,)) or 0)
    put("UNIVERSE", "OK" if n_active > 0 else "EMPTY", f"{n_active} emiten aktif")

    fr = data_freshness(cfg, repo, ctx.calendar, provider_latest)
    out["freshness"] = fr
    put("LATEST MARKET DATE", "INFO", fr["latest_expected_market_date"])
    put("DATABASE LATEST DATE", "INFO", str(fr["latest_database_date"]))
    put("DATA FRESHNESS", {"UP_TO_DATE": "OK", "UPDATE_REQUIRED": "WARN"}.get(fr["status"], "FAIL"), fr["status"])

    try:
        active = ctx.models.active_version()
    except Exception as e:
        active = None
        put("ACTIVE MODEL", "FAIL", str(e)[:200])
    if active:
        put("ACTIVE MODEL", "OK", active["version"])
        age = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(active["promoted_at"] or active["created_at"])).days
        status, detail = "OK", f"umur {age} hari, train s/d {active['train_end']}"
        if active.get("feature_version") != FEATURE_VERSION:
            status, detail = "INCOMPATIBLE", f"feature_version {active.get('feature_version')} != {FEATURE_VERSION} — retrain"
        elif age > 2 * int(get(cfg, "model.retrain_frequency_days", 30)):
            status = "STALE"
        elif "BASELINE" in str(ctx.db.scalar("SELECT notes FROM model_versions WHERE version = ?", (active["version"],)) or ""):
            status, detail = "WARN", detail + " (baseline: gerbang promosi belum lolos)"
        put("MODEL STATUS", status, detail)
        out["active_model"] = active["version"]
    else:
        put("ACTIVE MODEL", "MISSING", "jalankan `python main.py setup` / workflow Setup")
        put("MODEL STATUS", "MISSING", "")
    last = repo.last_run("daily")
    put("LAST PIPELINE", last["status"] if last else "NONE",
        f"{last['run_id']} @ {last['started_at']}" if last else "belum pernah dijalankan")
    critical = ["ENVIRONMENT", "DATABASE"]
    out["ok"] = all(out["checks"][c]["status"] == "OK" for c in critical if c in out["checks"])
    return out


def format_health(h: dict) -> str:
    lines = []
    for name, c in h["checks"].items():
        d = f"  ({c['detail']})" if c["detail"] and c["status"] not in ("INFO",) else ""
        val = c["detail"] if c["status"] == "INFO" else c["status"]
        lines.append(f"{name + ':':<24}{val}{d}")
    return "\n".join(lines)


def health_json(h: dict) -> str:
    return json.dumps(h, default=str, indent=2)
