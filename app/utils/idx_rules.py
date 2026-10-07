"""Aturan perdagangan BEI yang relevan untuk eksekusi order.

- Fraksi harga (tick size) sesuai ketentuan BEI untuk saham.
- 1 lot = 100 lembar.
Harga entry/SL/TP selalu dibulatkan ke fraksi valid agar order dapat dieksekusi.
"""
from __future__ import annotations

import math

import numpy as np

BOARD_LOT = 100

# (batas_atas_eksklusif, tick)
_TICKS = [(200, 1), (500, 2), (2000, 5), (5000, 10), (float("inf"), 25)]


def tick_size(price: float) -> int:
    for upper, tick in _TICKS:
        if price < upper:
            return tick
    return 25


def round_to_tick(price: float, mode: str = "nearest") -> float:
    """mode: nearest | down | up."""
    if price is None or not np.isfinite(price) or price <= 0:
        return float("nan")
    t = tick_size(price)
    q = price / t
    if mode == "down":
        v = math.floor(q + 1e-9) * t
    elif mode == "up":
        v = math.ceil(q - 1e-9) * t
    else:
        v = round(q) * t
    # pembulatan bisa memindahkan harga ke band tick lain — ulangi sekali
    t2 = tick_size(v)
    if t2 != t:
        q2 = price / t2
        v = (math.floor(q2 + 1e-9) if mode == "down" else math.ceil(q2 - 1e-9) if mode == "up" else round(q2)) * t2
    return float(v)


round_to_tick_vec = np.vectorize(round_to_tick, otypes=[float])


def shares_to_lots(shares: float, lot: int = BOARD_LOT) -> int:
    if shares is None or not np.isfinite(shares) or shares <= 0:
        return 0
    return int(shares // lot)
