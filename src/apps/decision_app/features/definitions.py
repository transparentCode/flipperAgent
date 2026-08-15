"""Small app-owned feature definitions used by D7 real-model adapters."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from math import isfinite
from typing import Any

from apps.decision_app.features.planning import (
    FeatureHistoryRequirement,
    SharedFeatureDefinition,
)
from libs.contracts.decision import CausalBarView

SR_ATR_NAME = "ATR"
SR_ATR_VERSION = "1"
SR_ATR_PERIOD = 14
SR_ATR_HISTORY_BARS = SR_ATR_PERIOD + 1


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def calculate_sr_atr(context: Any) -> float:
    """Calculate the deterministic Wilder ATR value at the causal cutoff.

    The D4 engine supplies exactly the bounded history declared below.  This
    pure implementation intentionally mirrors the established ATR batch
    recurrence without carrying mutable indicator state between evaluations.
    """

    if not hasattr(context, "histories") or not hasattr(context, "decision_timeframe"):
        raise TypeError("ATR calculator requires a SharedFeatureContext")
    bars = context.histories.get(context.decision_timeframe)
    if not isinstance(bars, Sequence) or len(bars) != SR_ATR_HISTORY_BARS:
        raise ValueError(
            f"ATR requires exactly {SR_ATR_HISTORY_BARS} decision-timeframe bars"
        )
    if any(not isinstance(bar, CausalBarView) for bar in bars):
        raise TypeError("ATR history must contain CausalBarView values")

    highs = [_finite_float(bar.high, field_name="high") for bar in bars]
    lows = [_finite_float(bar.low, field_name="low") for bar in bars]
    closes = [_finite_float(bar.close, field_name="close") for bar in bars]
    true_ranges = [highs[0] - lows[0]]
    true_ranges.extend(
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(bars))
    )
    current = sum(true_ranges[1 : SR_ATR_PERIOD + 1]) / SR_ATR_PERIOD
    if not isfinite(current) or current <= 0:
        raise ValueError("ATR must be finite and positive")
    return current


SR_ATR_DEFINITION = SharedFeatureDefinition(
    name=SR_ATR_NAME,
    version=SR_ATR_VERSION,
    calculator=calculate_sr_atr,
    history_requirements=(
        FeatureHistoryRequirement(
            source="decision",
            bars=SR_ATR_HISTORY_BARS,
        ),
    ),
)


__all__ = [
    "SR_ATR_DEFINITION",
    "SR_ATR_HISTORY_BARS",
    "SR_ATR_NAME",
    "SR_ATR_PERIOD",
    "SR_ATR_VERSION",
    "calculate_sr_atr",
]
