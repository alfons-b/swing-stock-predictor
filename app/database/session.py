from functools import lru_cache
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_settings


def _normalize_url(url: str) -> str:
    # Accept common Supabase/Postgres URLs while making the driver explicit.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = _normalize_url(settings.database_url)

    kwargs = {"pool_pre_ping": True}

    if url.startswith("sqlite://"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = 3
        kwargs["max_overflow"] = 2

    return create_engine(url, **kwargs)


def database_health() -> dict[str, str]:
    settings = get_settings()
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    return {
        "status": "OK",
        "dialect": engine.dialect.name,
        "environment": settings.app_env,
        "timezone": settings.timezone,
    }
