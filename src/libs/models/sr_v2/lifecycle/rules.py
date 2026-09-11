"""Runtime lifecycle hypothesis values."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleRules:
    break_buffer_atr: Decimal
    break_confirmation_bars: int
    expiry: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.break_buffer_atr, Decimal) or self.break_buffer_atr <= 0:
            raise ValueError("break_buffer_atr must be positive Decimal")
        if isinstance(self.break_confirmation_bars, bool) or self.break_confirmation_bars <= 0:
            raise ValueError("break_confirmation_bars must be positive")
        if not isinstance(self.expiry, timedelta) or self.expiry <= timedelta(0):
            raise ValueError("expiry must be positive")


__all__ = ["LifecycleRules"]
