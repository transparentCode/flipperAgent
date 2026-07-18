"""Pure causal pivot-rejection band detection for the frozen V2.1 study.

This detector is deliberately unregistered.  It shares the strict V1 pivot
confirmation rule but owns a different, observed-wick geometry contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.candidates import CandidateLevel
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.geometry import ZoneGeometry
from libs.models.sr.domain.zones import ZoneSide


_SOURCE = "pivot_rejection_v2_1"


@dataclass(frozen=True)
class PivotRejectionConfig:
    """Detector-local, explicit confirmation span."""

    pivot_span_bars: int

    def __post_init__(self) -> None:
        if type(self.pivot_span_bars) is not int or self.pivot_span_bars < 1:
            raise ContractValidationError("pivot_span_bars must be a positive integer")

    def to_payload(self) -> dict[str, int]:
        return {"pivot_span_bars": self.pivot_span_bars}


def _validate_bars(bars: tuple[ClosedBar, ...]) -> None:
    if type(bars) is not tuple:
        raise ContractValidationError("bars must be exactly a tuple")
    if not bars:
        return
    state_key = bars[0].state_key
    seen: set[str] = set()
    previous = None
    for index, bar in enumerate(bars):
        if type(bar) is not ClosedBar:
            raise ContractValidationError(f"bars[{index}] must be exactly ClosedBar")
        if bar.state_key != state_key:
            raise ContractValidationError(
                f"bars[{index}].state_key must match pivot window state_key"
            )
        if bar.bar_id in seen:
            raise ContractValidationError(
                f"duplicate bar_id in pivot window: {bar.bar_id}"
            )
        if previous is not None and bar.closed_at <= previous:
            raise ContractValidationError(
                "pivot window timestamps must be strictly increasing"
            )
        seen.add(bar.bar_id)
        previous = bar.closed_at


def _candidate(
    pivot: ClosedBar, confirmation: ClosedBar, side: ZoneSide
) -> CandidateLevel | None:
    lower, upper = (
        (max(pivot.open, pivot.close), pivot.high)
        if side is ZoneSide.RESISTANCE
        else (pivot.low, min(pivot.open, pivot.close))
    )
    if not all(
        math.isfinite(value) for value in (lower, upper, confirmation.atr_at_close)
    ):
        raise ContractValidationError("pivot-rejection geometry and ATR must be finite")
    width = upper - lower
    if not math.isfinite(width):
        raise ContractValidationError("pivot-rejection wick width must be finite")
    if width <= 0.0:
        return None
    center = (lower + upper) / 2.0
    half_width = width / 2.0
    if not all(math.isfinite(value) for value in (center, half_width)):
        raise ContractValidationError("pivot-rejection derived geometry must be finite")
    geometry = ZoneGeometry(center=center, half_width=half_width)
    if not math.isfinite(geometry.lower_bound) or not math.isfinite(
        geometry.upper_bound
    ):
        raise ContractValidationError("pivot-rejection geometry bounds must be finite")
    return CandidateLevel(
        state_key=pivot.state_key,
        side=side,
        geometry=geometry,
        source=_SOURCE,
        formed_at=pivot.closed_at,
        available_at=confirmation.closed_at,
        atr_at_creation=confirmation.atr_at_close,
    )


def detect_pivot_rejection_bands(
    bars: tuple[ClosedBar, ...], config: PivotRejectionConfig
) -> tuple[CandidateLevel, ...]:
    """Return all strict pivot rejection bands confirmed in ``bars``."""
    _validate_bars(bars)
    if type(config) is not PivotRejectionConfig:
        raise ContractValidationError("config must be exactly PivotRejectionConfig")
    span = config.pivot_span_bars
    width = 2 * span + 1
    candidates: list[CandidateLevel] = []
    for confirmation_index in range(width - 1, len(bars)):
        window = bars[confirmation_index - width + 1 : confirmation_index + 1]
        pivot = window[span]
        other = window[:span] + window[span + 1 :]
        confirmation = window[-1]
        if all(pivot.high > bar.high for bar in other):
            candidate = _candidate(pivot, confirmation, ZoneSide.RESISTANCE)
            if candidate is not None:
                candidates.append(candidate)
        if all(pivot.low < bar.low for bar in other):
            candidate = _candidate(pivot, confirmation, ZoneSide.SUPPORT)
            if candidate is not None:
                candidates.append(candidate)
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.available_at,
                0 if item.side is ZoneSide.RESISTANCE else 1,
                item.candidate_id,
            ),
        )
    )


__all__ = ["PivotRejectionConfig", "detect_pivot_rejection_bands"]
