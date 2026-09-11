"""Closed canonical bars consumed by SR v2 kernels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..contracts import require_utc


def _decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(f"{field_name} must be a finite Decimal")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class SRBar:
    timeframe: str
    bar_open_at: datetime
    bar_close_at: datetime
    market_as_of: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    taker_buy_base: Decimal | None = None
    closed: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise ValueError("timeframe must be non-empty")
        require_utc(self.bar_open_at, field_name="bar_open_at")
        require_utc(self.bar_close_at, field_name="bar_close_at")
        require_utc(self.market_as_of, field_name="market_as_of")
        if self.bar_close_at <= self.bar_open_at:
            raise ValueError("bar_close_at must be after bar_open_at")
        if not self.closed or self.market_as_of != self.bar_close_at:
            raise ValueError("SR v2 consumes closed bars at their close cutoff")
        values = {
            field_name: _decimal(getattr(self, field_name), field_name)
            for field_name in ("open", "high", "low", "close", "volume")
        }
        if values["low"] > values["high"]:
            raise ValueError("low must be <= high")
        if not values["low"] <= values["open"] <= values["high"]:
            raise ValueError("open must lie inside high/low")
        if not values["low"] <= values["close"] <= values["high"]:
            raise ValueError("close must lie inside high/low")
        if values["volume"] < 0:
            raise ValueError("volume must be non-negative")
        if self.taker_buy_base is not None:
            taker = _decimal(self.taker_buy_base, "taker_buy_base")
            if taker < 0 or taker > values["volume"]:
                raise ValueError("taker_buy_base must be between zero and volume")

    @property
    def identity(self) -> str:
        return (
            f"{self.timeframe}:{self.bar_open_at.isoformat()}"
            f":{self.bar_close_at.isoformat()}"
        )

__all__ = ["SRBar"]
