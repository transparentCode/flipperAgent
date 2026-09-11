"""Causal price features used by SR v2 kernels."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from ..domain.bars import SRBar


def true_range(current: SRBar, previous_close: Decimal | None = None) -> Decimal:
    if not isinstance(current, SRBar):
        raise TypeError("current must be SRBar")
    reference = current.open if previous_close is None else previous_close
    if not isinstance(reference, Decimal) or not reference.is_finite():
        raise TypeError("previous_close must be a finite Decimal")
    return max(current.high - current.low, abs(current.high - reference), abs(current.low - reference))


def wilder_atr(bars: Sequence[SRBar], period: int) -> Decimal:
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("period must be positive")
    values = tuple(bars)
    if len(values) < period:
        raise ValueError("insufficient bars for ATR")
    ranges = [
        true_range(bar, values[index - 1].close if index else None)
        for index, bar in enumerate(values)
    ]
    atr = sum(ranges[:period], Decimal(0)) / Decimal(period)
    for item in ranges[period:]:
        atr = ((atr * Decimal(period - 1)) + item) / Decimal(period)
    if atr <= 0:
        raise ValueError("ATR must be positive")
    return atr


__all__ = ["true_range", "wilder_atr"]
