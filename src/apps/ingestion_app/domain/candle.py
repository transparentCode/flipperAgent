"""Immutable candle observation and canonical candle contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from .instrument import MarketLane


def _require_non_empty_string(value: object, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_utc(value: object, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _require_decimal(value: object, *, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")


def _require_lane(value: object) -> None:
    if not isinstance(value, MarketLane):
        raise TypeError("lane must be a MarketLane")


def _validate_candle_values(
    *,
    open_price: object,
    high: object,
    low: object,
    close: object,
    volume: object,
    taker_buy_base: object | None,
) -> None:
    _require_decimal(open_price, field_name="open")
    _require_decimal(high, field_name="high")
    _require_decimal(low, field_name="low")
    _require_decimal(close, field_name="close")
    _require_decimal(volume, field_name="volume")
    if taker_buy_base is not None:
        _require_decimal(taker_buy_base, field_name="taker_buy_base")

    if low > high:
        raise ValueError("low must be less than or equal to high")
    if not low <= open_price <= high:
        raise ValueError("open must be between low and high")
    if not low <= close <= high:
        raise ValueError("close must be between low and high")
    if volume < 0:
        raise ValueError("volume must be non-negative")
    if taker_buy_base is not None and taker_buy_base < 0:
        raise ValueError("taker_buy_base must be non-negative")


@dataclass(frozen=True, slots=True)
class CandleObservation:
    """A finalized candle observation received from an external provider."""

    lane: MarketLane
    provider_id: str
    provider_symbol: str
    transport: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    taker_buy_base: Decimal | None
    received_at: datetime
    provider_close_time: datetime | None = None
    provider_event_id: str | None = None

    def __post_init__(self) -> None:
        _require_lane(self.lane)
        for field_name in ("provider_id", "provider_symbol", "transport"):
            _require_non_empty_string(getattr(self, field_name), field_name=field_name)
        _require_utc(self.open_time, field_name="open_time")
        _require_utc(self.close_time, field_name="close_time")
        _require_utc(self.received_at, field_name="received_at")
        if self.provider_close_time is not None:
            _require_utc(self.provider_close_time, field_name="provider_close_time")
        if self.provider_event_id is not None:
            _require_non_empty_string(
                self.provider_event_id,
                field_name="provider_event_id",
            )
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        _validate_candle_values(
            open_price=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            taker_buy_base=self.taker_buy_base,
        )


@dataclass(frozen=True, slots=True)
class CanonicalCandle:
    """A provider or internally derived canonical candle."""

    lane: MarketLane
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    taker_buy_base: Decimal | None
    source_type: Literal["provider", "derived"]
    source_provider: str | None
    source_timeframe: str | None

    def __post_init__(self) -> None:
        _require_lane(self.lane)
        _require_utc(self.open_time, field_name="open_time")
        _require_utc(self.close_time, field_name="close_time")
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        _validate_candle_values(
            open_price=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            taker_buy_base=self.taker_buy_base,
        )

        _require_non_empty_string(self.source_type, field_name="source_type")
        if self.source_type == "provider":
            if self.source_provider is None:
                raise ValueError("provider candles require source_provider")
            _require_non_empty_string(
                self.source_provider,
                field_name="source_provider",
            )
            if self.source_timeframe is not None:
                raise ValueError("provider candles require source_timeframe to be None")
        elif self.source_type == "derived":
            if self.source_provider is not None:
                raise ValueError("derived candles require source_provider to be None")
            if self.source_timeframe is None:
                raise ValueError("derived candles require source_timeframe")
            _require_non_empty_string(
                self.source_timeframe,
                field_name="source_timeframe",
            )
        else:
            raise ValueError("source_type must be 'provider' or 'derived'")


__all__ = ["CandleObservation", "CanonicalCandle"]
