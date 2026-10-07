from datetime import date
from app.market.calendar import TradingCalendar


def test_weekend_is_not_trading_day():
    cal = TradingCalendar()
    assert not cal.is_trading_day(date(2026, 10, 3))  # Saturday


def test_previous_trading_day():
    cal = TradingCalendar()
    assert cal.previous_trading_day(date(2026, 10, 5)).weekday() == 4
