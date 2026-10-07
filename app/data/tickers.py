"""Normalisasi ticker. Internal: `BBCA`. Provider-specific: `BBCA.JK` (Yahoo), dst."""
from __future__ import annotations

import re

_VALID = re.compile(r"^[A-Z0-9]{3,6}$")


def normalize_ticker(raw: str) -> str:
    """Ubah berbagai format (`bbca.jk`, `IDX:BBCA`, ` BBCA `) menjadi `BBCA`."""
    if raw is None:
        raise ValueError("Ticker kosong")
    t = str(raw).strip().upper()
    if ":" in t:
        t = t.split(":")[-1]
    if "." in t:
        t = t.split(".")[0]
    t = t.replace(" ", "")
    if not _VALID.match(t):
        raise ValueError(f"Ticker tidak valid: {raw!r}")
    return t


def to_provider_symbol(ticker: str, suffix: str = "") -> str:
    return f"{normalize_ticker(ticker)}{suffix}"


def from_provider_symbol(symbol: str) -> str:
    return normalize_ticker(symbol)
