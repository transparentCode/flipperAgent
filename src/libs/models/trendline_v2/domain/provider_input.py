"""Immutable primitive input exposed to candidate providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from numbers import Integral
from typing import Any, Sequence

from .identity import deterministic_hash
from .validation import (
    ContractValidationError,
    primitive,
    require_number,
    require_string,
    require_utc,
)


def _tuple_of_numbers(value: Sequence[Any], *, field_name: str) -> tuple[float, ...]:
    try:
        result = tuple(
            require_number(item, field_name=f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    except TypeError as exc:
        raise ContractValidationError(f"{field_name} must be a numeric sequence") from exc
    if not result:
        raise ContractValidationError(f"{field_name} must be non-empty")
    return result


def _tuple_of_timestamps(value: Sequence[Any]) -> tuple[int, ...]:
    try:
        raw = tuple(value)
    except TypeError as exc:
        raise ContractValidationError(
            "provider_input.timestamps must be a sequence"
        ) from exc
    if not raw or any(isinstance(item, bool) or not isinstance(item, Integral) for item in raw):
        raise ContractValidationError("provider_input.timestamps must be non-empty integers")
    result = tuple(int(item) for item in raw)
    if tuple(sorted(result)) != result or len(set(result)) != len(result):
        raise ContractValidationError("provider_input.timestamps must be strictly increasing")
    return result


@dataclass(frozen=True, slots=True)
class ProviderInput:
    """The complete normalized causal data a provider may inspect."""

    asset: str
    timeframe: str
    observed_at: datetime
    confirmed_through: datetime
    timestamps: tuple[int, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]

    def __post_init__(self) -> None:
        asset = require_string(self.asset, field_name="provider_input.asset")
        timeframe = require_string(self.timeframe, field_name="provider_input.timeframe")
        observed = require_utc(self.observed_at, field_name="provider_input.observed_at")
        confirmed = require_utc(
            self.confirmed_through, field_name="provider_input.confirmed_through"
        )
        if confirmed > observed:
            raise ContractValidationError(
                "provider_input.confirmed_through cannot be after observed_at"
            )
        timestamps = _tuple_of_timestamps(self.timestamps)
        values = {
            name: _tuple_of_numbers(getattr(self, name), field_name=f"provider_input.{name}")
            for name in ("open", "high", "low", "close", "volume")
        }
        if any(len(value) != len(timestamps) for value in values.values()):
            raise ContractValidationError("provider_input arrays must have equal lengths")
        epoch = datetime(1970, 1, 1, tzinfo=confirmed.tzinfo)
        elapsed = confirmed - epoch
        confirmed_ns = (
            (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000
            + elapsed.microseconds * 1_000
        )
        if any(timestamp > confirmed_ns for timestamp in timestamps):
            raise ContractValidationError(
                "provider_input contains a bar after confirmed_through"
            )
        if any(
            high < low or high < open_value or high < close or low > open_value or low > close
            for open_value, high, low, close in zip(
                values["open"], values["high"], values["low"], values["close"]
            )
        ):
            raise ContractValidationError("provider_input OHLC values violate candle bounds")
        if any(item < 0.0 for item in values["volume"]):
            raise ContractValidationError("provider_input.volume cannot be negative")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "confirmed_through", confirmed)
        object.__setattr__(self, "timestamps", timestamps)
        for name, value in values.items():
            object.__setattr__(self, name, value)

    @property
    def row_count(self) -> int:
        return len(self.timestamps)

    @property
    def input_identity(self) -> str:
        return deterministic_hash("trendline_v2_provider_input", self._identity_payload())

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "observed_at": self.observed_at,
            "confirmed_through": self.confirmed_through,
            "timestamps": self.timestamps,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self), "input_identity": self.input_identity}


__all__ = ["ProviderInput"]
