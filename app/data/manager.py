from datetime import date, timedelta
from typing import Any
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database.models import Stock, PriceHistory, CorporateAction
from app.database.session import get_engine
from app.data.yahoo import YahooFinanceProvider
from app.data.csv_provider import CSVProvider


def get_provider(name: str):
    if name == "yahoo_finance":
        return YahooFinanceProvider()
    if name == "csv":
        return CSVProvider()
    raise ValueError(f"Unsupported provider: {name}")


def latest_price_date(session: Session, stock_id: int):
    return session.scalar(
        select(func.max(PriceHistory.date)).where(PriceHistory.stock_id == stock_id)
    )


def validate_price(row: dict[str, Any]) -> None:
    required = ["date", "close"]
    if any(row.get(k) is None for k in required):
        raise ValueError("Missing required price field")
    if row.get("high") is not None and row.get("low") is not None:
        if row["high"] < row["low"]:
            raise ValueError("High < low")
    if row.get("volume") is not None and row["volume"] < 0:
        raise ValueError("Negative volume")


def upsert_price(session: Session, stock: Stock, row: dict[str, Any], source_id=None):
    validate_price(row)
    existing = session.scalar(
        select(PriceHistory).where(
            PriceHistory.stock_id == stock.id,
            PriceHistory.date == row["date"],
        )
    )
    values = {
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "close": row.get("close"),
        "adjusted_close": row.get("adjusted_close"),
        "volume": row.get("volume"),
        "source_id": source_id,
    }
    if existing:
        for k, v in values.items():
            setattr(existing, k, v)
        return "updated"
    session.add(PriceHistory(stock_id=stock.id, date=row["date"], **values))
    return "inserted"


def ingest_ticker(ticker: str, provider_name="yahoo_finance", start=None, end=None) -> dict[str, int]:
    provider = get_provider(provider_name)
    today = end or date.today()
    session = Session(get_engine())
    try:
        stock = session.scalar(select(Stock).where(Stock.ticker == ticker))
        if not stock:
            stock = Stock(ticker=ticker, name=ticker, is_active=True)
            session.add(stock)
            session.flush()

        latest = latest_price_date(session, stock.id)
        if start is None:
            start = (latest + timedelta(days=1)) if latest else today - timedelta(days=365 * 10)

        if start > today:
            return {"inserted": 0, "updated": 0, "skipped": 0}

        rows = provider.get_prices(ticker, start, today)
        inserted = updated = 0
        for row in rows:
            result = upsert_price(session, stock, row)
            if result == "inserted":
                inserted += 1
            else:
                updated += 1

        session.commit()
        return {"inserted": inserted, "updated": updated, "skipped": 0}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
