"""Strict, model-owned configuration for the Momentum rule."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from typing import Any

_CONFIG_KEYS = frozenset(
    {
        "rsi_long_threshold",
        "rsi_short_threshold",
        "require_macd_positive",
        "histogram_min_abs",
    }
)


def _strict_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an int")
    return value


def _strict_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


def _finite_real(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a finite numeric value")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class MomentumConfig:
    """Validated semantic parameters for the stateless Momentum rule."""

    rsi_long_threshold: int = 55
    rsi_short_threshold: int = 45
    require_macd_positive: bool = False
    histogram_min_abs: float = 0.0

    def __post_init__(self) -> None:
        long_threshold = _strict_int(
            self.rsi_long_threshold,
            field_name="rsi_long_threshold",
        )
        short_threshold = _strict_int(
            self.rsi_short_threshold,
            field_name="rsi_short_threshold",
        )
        require_line = _strict_bool(
            self.require_macd_positive,
            field_name="require_macd_positive",
        )
        histogram_min_abs = _finite_real(
            self.histogram_min_abs,
            field_name="histogram_min_abs",
        )

        for field_name, threshold in (
            ("rsi_long_threshold", long_threshold),
            ("rsi_short_threshold", short_threshold),
        ):
            if not 0 <= threshold <= 100:
                raise ValueError(f"{field_name} must be between 0 and 100")
        if short_threshold >= long_threshold:
            raise ValueError(
                "rsi_short_threshold must be less than rsi_long_threshold, got "
                f"{short_threshold} >= {long_threshold}"
            )
        if histogram_min_abs < 0:
            raise ValueError("histogram_min_abs must be non-negative")

        object.__setattr__(self, "rsi_long_threshold", long_threshold)
        object.__setattr__(self, "rsi_short_threshold", short_threshold)
        object.__setattr__(self, "require_macd_positive", require_line)
        object.__setattr__(self, "histogram_min_abs", histogram_min_abs)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> MomentumConfig:
        """Build a config while rejecting unknown or malformed parameters."""

        if not isinstance(values, Mapping):
            raise TypeError("MomentumConfig values must be a mapping")
        if any(not isinstance(key, str) for key in values):
            raise TypeError("MomentumConfig parameter names must be strings")
        unknown = sorted(set(values) - _CONFIG_KEYS)
        if unknown:
            raise ValueError(f"unknown MomentumConfig parameters: {unknown}")
        defaults = cls()
        return cls(
            rsi_long_threshold=values.get(
                "rsi_long_threshold", defaults.rsi_long_threshold
            ),
            rsi_short_threshold=values.get(
                "rsi_short_threshold", defaults.rsi_short_threshold
            ),
            require_macd_positive=values.get(
                "require_macd_positive", defaults.require_macd_positive
            ),
            histogram_min_abs=values.get(
                "histogram_min_abs", defaults.histogram_min_abs
            ),
        )

    def to_mapping(self) -> dict[str, int | bool | float]:
        """Return a stable primitive mapping for legacy callers and tests."""

        return {
            "rsi_long_threshold": self.rsi_long_threshold,
            "rsi_short_threshold": self.rsi_short_threshold,
            "require_macd_positive": self.require_macd_positive,
            "histogram_min_abs": self.histogram_min_abs,
        }


__all__ = ["MomentumConfig"]
