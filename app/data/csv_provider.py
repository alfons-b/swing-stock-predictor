from datetime import date
from pathlib import Path
from typing import Any
import pandas as pd

from app.data.provider import MarketDataProvider


class CSVProvider(MarketDataProvider):
    name = "csv"

    def __init__(self, directory: str = "data/raw"):
        self.directory = Path(directory)

    def get_universe(self) -> list[dict[str, Any]]:
        path = self.directory / "universe.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path)
        return df.to_dict("records")

    def get_prices(self, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
        path = self.directory / f"{ticker}.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        return df.to_dict("records")

    def get_actions(self, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
        path = self.directory / "corporate_actions.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path)
        df["action_date"] = pd.to_datetime(df["action_date"]).dt.date
        df = df[
            (df["ticker"] == ticker)
            & (df["action_date"] >= start)
            & (df["action_date"] <= end)
        ]
        return df.to_dict("records")
