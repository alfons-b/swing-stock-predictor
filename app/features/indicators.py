"""Indikator teknikal murni (input Series → output Series). SEMUA hanya memakai data <= t:
rolling/ewm pandas selalu backward-looking, dan tidak ada `shift(-n)` di modul ini.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = wilder(d.clip(lower=0), n)
    dn = wilder((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0).where(up.notna())


def true_range(h, l, c):
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def atr(h, l, c, n: int = 14) -> pd.Series:
    return wilder(true_range(h, l, c), n)


def adx(h, l, c, n: int = 14):
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    tr = wilder(true_range(h, l, c), n)
    pdi = 100 * wilder(plus_dm, n) / tr
    mdi = 100 * wilder(minus_dm, n) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return wilder(dx, n), pdi, mdi


def stochastic(h, l, c, k: int = 14, d: int = 3):
    lo = l.rolling(k, min_periods=k).min()
    hi = h.rolling(k, min_periods=k).max()
    pk = 100 * (c - lo) / (hi - lo).replace(0, np.nan)
    return pk, pk.rolling(d, min_periods=d).mean()


def williams_r(h, l, c, n: int = 14):
    hi = h.rolling(n, min_periods=n).max()
    lo = l.rolling(n, min_periods=n).min()
    return -100 * (hi - c) / (hi - lo).replace(0, np.nan)


def macd(c, fast=12, slow=26, signal=9):
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger_width(c, n=20, k=2.0):
    m = sma(c, n)
    sd = c.rolling(n, min_periods=n).std()
    return (2 * k * sd) / m


def obv(c, v):
    return (np.sign(c.diff()).fillna(0) * v).cumsum()


def rolling_pct_rank(s: pd.Series, n: int) -> pd.Series:
    """Persentil nilai hari ini terhadap n hari terakhir (inklusif) — tanpa data masa depan."""
    return s.rolling(n, min_periods=max(20, n // 3)).rank(pct=True)


def slope(s: pd.Series, n: int) -> pd.Series:
    return s / s.shift(n) - 1
