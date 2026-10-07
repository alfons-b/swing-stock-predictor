from datetime import date
from typing import Any
import pandas as pd
import yfinance as yf

from app.data.provider import MarketDataProvider


class YahooFinanceProvider(MarketDataProvider):
    name = "yahoo_finance"

    def _symbol(self, ticker: str) -> str:
        return ticker if ticker.endswith(".JK") else f"{ticker}.JK"

    def get_universe(self) -> list[dict[str, Any]]:
        # Yahoo does not expose an authoritative IDX universe endpoint.
        # Universe discovery therefore remains explicit/configurable.
        return []

    def get_prices(self, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
        symbol = self._symbol(ticker)
        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=(pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat(),
            auto_adjust=False,
            progress=False,
            actions=False,
        )
        if df.empty:
            return []

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        rows = []
        for idx, row in df.iterrows():
            rows.append({
                "ticker": ticker.replace(".JK", ""),
                "date": pd.Timestamp(idx).date(),
                "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
                "high": float(row["High"]) if pd.notna(row["High"]) else None,
                "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
                "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
                "adjusted_close": float(row["Adj Close"]) if pd.notna(row["Adj Close"]) else None,
                "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            })
        return rows

    def get_actions(self, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
        symbol = self._symbol(ticker)
        actions = yf.Ticker(symbol).actions
        if actions is None or actions.empty:
            return []
        actions.index = pd.to_datetime(actions.index)
        actions = actions.loc[
            (actions.index.date >= start) & (actions.index.date <= end)
        ]
        rows = []
        for idx, row in actions.iterrows():
            if pd.notna(row.get("Dividends")) and float(row["Dividends"]) != 0:
                rows.append({
                    "ticker": ticker.replace(".JK", ""),
                    "action_date": idx.date(),
                    "action_type": "DIVIDEND",
                    "ratio": float(row["Dividends"]),
                    "description": "Yahoo Finance dividend action",
                })
            if pd.notna(row.get("Stock Splits")) and float(row["Stock Splits"]) != 0:
                rows.append({
                    "ticker": ticker.replace(".JK", ""),
                    "action_date": idx.date(),
                    "action_type": "SPLIT",
                    "ratio": float(row["Stock Splits"]),
                    "description": "Yahoo Finance stock split",
                })
        return rows
