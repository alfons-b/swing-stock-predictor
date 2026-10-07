"""IDXProvider — modular, aktif hanya bila credentials/subscription tersedia.

- Universe: endpoint publik situs BEI (tanpa jaminan; sering diblokir proteksi bot dari IP datacenter).
- Harga: BEI tidak menyediakan API histori publik resmi. Implementasikan `_fetch_prices` terhadap feed
  berlisensi Anda (MARKET_DATA_API_KEY). Tanpa itu, provider melempar ProviderUnavailable → fallback.
Sistem TIDAK mengklaim akses resmi tanpa credentials.
"""
from __future__ import annotations

import json
import urllib.request

import pandas as pd

from app.data.providers.base import MarketDataProvider, ProviderError, ProviderUnavailable
from app.data.schema import conform_universe
from app.data.tickers import normalize_ticker

IDX_SECURITIES_URL = "https://www.idx.co.id/primary/StockData/GetSecuritiesStock?start=0&length=9999"


class IDXProvider(MarketDataProvider):
    type = "idx"

    def get_universe(self):
        req = urllib.request.Request(IDX_SECURITIES_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                rows = json.loads(resp.read().decode("utf-8")).get("data") or []
        except Exception as e:
            raise ProviderError(f"Universe BEI tidak dapat diambil: {type(e).__name__}") from e
        if not rows:
            raise ProviderError("Respons universe BEI kosong / format berubah")
        df = pd.DataFrame(rows).rename(columns={"Code": "ticker", "Name": "name", "ListingDate": "listing_date",
                                                "ListingBoard": "board"})
        df["ticker"] = df["ticker"].map(normalize_ticker)
        return conform_universe(df)

    def _require_key(self):
        if not self.entry.get("api_key"):
            raise ProviderUnavailable("IDX price feed membutuhkan MARKET_DATA_API_KEY / subscription")

    def get_prices(self, ticker, start, end):
        self._require_key()
        raise ProviderUnavailable("Implementasikan IDXProvider._fetch_prices untuk feed berlisensi Anda")

    def get_actions(self, ticker, start, end):
        self._require_key()
        raise ProviderUnavailable("Corporate action feed IDX belum dikonfigurasi")

    def get_index(self, start, end):
        self._require_key()
        raise ProviderUnavailable("Index feed IDX belum dikonfigurasi")
