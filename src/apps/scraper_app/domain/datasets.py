"""Dataset catalog types: what is fetched, how it is shaped, how long a bar lasts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Shape(StrEnum):
    """Bar layout: ``ohlcv`` carries volume, ``ohlc`` does not."""

    OHLCV = "ohlcv"
    OHLC = "ohlc"


# The interval tables are the single place that maps configuration names to
# durations and TradingView resolution codes. An unknown name is a
# configuration error, never a default.
INTERVAL_SECONDS: dict[str, int] = {"1h": 3600, "4h": 14400, "1D": 86400}
TV_RESOLUTION: dict[str, str] = {"1h": "60", "4h": "240", "1D": "1D"}

# TradingView sends ``[time, o, h, l, c]`` or ``[time, o, h, l, c, volume]``.
_VALUES_PER_BAR: dict[Shape, int] = {Shape.OHLCV: 6, Shape.OHLC: 5}


# Bars requested beyond the computed window: absorbs clock skew and a bar that
# closes while the request is in flight.
SIZING_MARGIN_BARS = 3


def interval_seconds(interval: str) -> int:
    try:
        return INTERVAL_SECONDS[interval]
    except KeyError:
        raise ValueError(f"unknown interval: {interval!r}") from None


def tv_resolution(interval: str) -> str:
    try:
        return TV_RESOLUTION[interval]
    except KeyError:
        raise ValueError(f"unknown interval: {interval!r}") from None


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """One configured dataset."""

    id: str
    request_symbol: str
    canonical_symbol: str
    interval: str
    shape: Shape
    contiguous: bool
    non_negative: bool
    finality_horizon_seconds: int
    revision_watch_seconds: int
    max_live_lag_seconds: int = 7800
    initial_bars: int = 5000

    @property
    def interval_seconds(self) -> int:
        return interval_seconds(self.interval)

    @property
    def resolution(self) -> str:
        return tv_resolution(self.interval)

    @property
    def values_per_bar(self) -> int:
        """Values per bar on the wire, including the bar time."""
        return _VALUES_PER_BAR[self.shape]


__all__ = [
    "INTERVAL_SECONDS",
    "SIZING_MARGIN_BARS",
    "TV_RESOLUTION",
    "DatasetSpec",
    "Shape",
    "interval_seconds",
    "tv_resolution",
]
