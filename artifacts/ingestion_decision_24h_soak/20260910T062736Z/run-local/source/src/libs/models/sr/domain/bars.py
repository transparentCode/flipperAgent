"""SR state-key and closed-bar contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._validation import _number, _string
from .errors import ContractValidationError
from .identity import require_utc


@dataclass(frozen=True)
class SRStateKey:
    venue: str
    symbol: str
    timeframe: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _string(self.venue, field_name="venue"))
        object.__setattr__(self, "symbol", _string(self.symbol, field_name="symbol"))
        object.__setattr__(
            self, "timeframe", _string(self.timeframe, field_name="timeframe")
        )


def _state_key(value: object) -> SRStateKey:
    if isinstance(value, SRStateKey):
        return value
    raise ContractValidationError("value must be SRStateKey")


@dataclass(frozen=True)
class ClosedBar:
    state_key: SRStateKey
    bar_id: str
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    atr_at_close: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(self, "bar_id", _string(self.bar_id, field_name="bar_id"))
        object.__setattr__(
            self,
            "closed_at",
            require_utc(self.closed_at, field_name="closed_at"),
        )
        for field_name in ("open", "high", "low", "close"):
            value = _number(
                getattr(self, field_name),
                field_name=field_name,
                minimum=0.0,
            )
            if value <= 0:
                raise ContractValidationError(f"{field_name} must be positive")
            object.__setattr__(self, field_name, value)
        if self.low > self.high:
            raise ContractValidationError("low must be <= high")
        if not self.low <= self.open <= self.high:
            raise ContractValidationError("open must be between low and high")
        if not self.low <= self.close <= self.high:
            raise ContractValidationError("close must be between low and high")
        atr_at_close = _number(
            self.atr_at_close,
            field_name="atr_at_close",
            minimum=0.0,
        )
        if atr_at_close <= 0:
            raise ContractValidationError("atr_at_close must be positive")
        object.__setattr__(self, "atr_at_close", atr_at_close)


__all__ = ["ClosedBar", "SRStateKey"]
