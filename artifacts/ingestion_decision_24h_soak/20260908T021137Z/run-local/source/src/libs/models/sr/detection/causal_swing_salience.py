"""Parameter-free causal swing salience detection for SR-V2.3."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from libs.models.sr.domain import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    ZoneGeometry,
    ZoneSide,
)


SOURCE = "causal_swing_salience_v2_3"


class SwingSalienceState(str, Enum):
    """Causal state of the alternating swing stream."""

    UNSEEDED = "UNSEEDED"
    SEEK_HIGH = "SEEK_HIGH"
    SEEK_LOW = "SEEK_LOW"


@dataclass(frozen=True)
class SwingSalienceConfirmation:
    """One confirmed reversal, including zero-wick transitions."""

    side: ZoneSide
    extreme_index: int
    confirmation_index: int
    extreme_atr: float
    raw_salience_atr: float
    state_before: SwingSalienceState
    state_after: SwingSalienceState
    candidate: CandidateLevel | None

    def __post_init__(self) -> None:
        if type(self.side) is not ZoneSide:
            raise ContractValidationError("swing side must be exactly ZoneSide")
        for name in ("extreme_index", "confirmation_index"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ContractValidationError(f"swing {name} must be a non-negative integer")
        if self.extreme_index >= self.confirmation_index:
            raise ContractValidationError("swing extreme must precede confirmation")
        for name in ("extreme_atr", "raw_salience_atr"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContractValidationError(f"swing {name} must be numeric")
            value = float(value)
            if not math.isfinite(value) or value < 0.0:
                raise ContractValidationError(f"swing {name} must be finite and non-negative")
            object.__setattr__(self, name, 0.0 if value == 0.0 else value)
        if self.extreme_atr <= 0.0:
            raise ContractValidationError("swing extreme_atr must be positive")
        if type(self.state_before) is not SwingSalienceState:
            raise ContractValidationError("swing state_before must be exactly SwingSalienceState")
        if type(self.state_after) is not SwingSalienceState:
            raise ContractValidationError("swing state_after must be exactly SwingSalienceState")
        expected = (
            (ZoneSide.RESISTANCE, SwingSalienceState.SEEK_HIGH, SwingSalienceState.SEEK_LOW),
            (ZoneSide.SUPPORT, SwingSalienceState.SEEK_LOW, SwingSalienceState.SEEK_HIGH),
        )
        if (self.side, self.state_before, self.state_after) not in expected:
            raise ContractValidationError("swing state transition does not match side")
        if self.candidate is not None:
            if type(self.candidate) is not CandidateLevel or self.candidate.side is not self.side:
                raise ContractValidationError("swing candidate side/type does not reconcile")

    def to_payload(self) -> dict[str, object]:
        return {
            "side": self.side.value,
            "extreme_index": self.extreme_index,
            "confirmation_index": self.confirmation_index,
            "extreme_atr": self.extreme_atr,
            "raw_salience_atr": self.raw_salience_atr,
            "state_before": self.state_before.value,
            "state_after": self.state_after.value,
            "candidate_id": None if self.candidate is None else self.candidate.candidate_id,
        }


def _validate_bars(bars: tuple[ClosedBar, ...]) -> None:
    if type(bars) is not tuple:
        raise ContractValidationError("bars must be exactly a tuple")
    if not bars:
        return
    state_key = bars[0].state_key
    previous = None
    ids: set[str] = set()
    for index, bar in enumerate(bars):
        if type(bar) is not ClosedBar:
            raise ContractValidationError(f"bars[{index}] must be exactly ClosedBar")
        if bar.state_key != state_key:
            raise ContractValidationError("swing bars must share one state key")
        if bar.bar_id in ids:
            raise ContractValidationError("swing bars must have unique bar IDs")
        if previous is not None and bar.closed_at <= previous:
            raise ContractValidationError("swing bars must have increasing closed_at values")
        ids.add(bar.bar_id)
        previous = bar.closed_at


def _seed_extreme(bars: tuple[ClosedBar, ...], index: int, state: SwingSalienceState) -> int:
    if state is SwingSalienceState.SEEK_HIGH:
        return max(range(index + 1), key=lambda item: bars[item].high)
    return min(range(index + 1), key=lambda item: bars[item].low)


def _candidate(
    extreme: ClosedBar,
    confirmation: ClosedBar,
    side: ZoneSide,
) -> CandidateLevel | None:
    lower, upper = (
        (max(extreme.open, extreme.close), extreme.high)
        if side is ZoneSide.RESISTANCE
        else (extreme.low, min(extreme.open, extreme.close))
    )
    if not all(math.isfinite(value) for value in (lower, upper, confirmation.atr_at_close)):
        raise ContractValidationError("swing geometry and confirmation ATR must be finite")
    width = upper - lower
    if not math.isfinite(width):
        raise ContractValidationError("swing wick width must be finite")
    if width <= 0.0:
        return None
    geometry = ZoneGeometry(center=(lower + upper) / 2.0, half_width=width / 2.0)
    return CandidateLevel(
        state_key=extreme.state_key,
        side=side,
        geometry=geometry,
        source=SOURCE,
        formed_at=extreme.closed_at,
        available_at=confirmation.closed_at,
        atr_at_creation=confirmation.atr_at_close,
    )


def detect_causal_swing_salience(
    bars: tuple[ClosedBar, ...],
) -> tuple[SwingSalienceConfirmation, ...]:
    """Return every valid alternating causal swing confirmation.

    The first strict close direction seeds the state.  Reversal magnitude is
    continuous salience, not a detector threshold.  A zero directional wick
    still confirms and transitions state, but has no emitted candidate.
    """

    _validate_bars(bars)
    state = SwingSalienceState.UNSEEDED
    extreme_index = 0
    confirmations: list[SwingSalienceConfirmation] = []
    for index in range(1, len(bars)):
        bar = bars[index]
        if state is SwingSalienceState.UNSEEDED:
            previous = bars[index - 1]
            if bar.close > previous.close:
                state = SwingSalienceState.SEEK_HIGH
                extreme_index = _seed_extreme(bars, index, state)
            elif bar.close < previous.close:
                state = SwingSalienceState.SEEK_LOW
                extreme_index = _seed_extreme(bars, index, state)
            continue

        extreme = bars[extreme_index]
        state_before = state
        if state is SwingSalienceState.SEEK_HIGH:
            if bar.high > extreme.high:
                extreme_index = index
                continue
            if bar.close >= bars[index - 1].close:
                continue
            raw_salience = (extreme.high - bar.close) / extreme.atr_at_close
            next_state = SwingSalienceState.SEEK_LOW
            side = ZoneSide.RESISTANCE
        else:
            if bar.low < extreme.low:
                extreme_index = index
                continue
            if bar.close <= bars[index - 1].close:
                continue
            raw_salience = (bar.close - extreme.low) / extreme.atr_at_close
            next_state = SwingSalienceState.SEEK_HIGH
            side = ZoneSide.SUPPORT

        if not math.isfinite(raw_salience) or raw_salience < 0.0:
            raise ContractValidationError("raw swing salience must be finite and non-negative")
        confirmations.append(
            SwingSalienceConfirmation(
                side=side,
                extreme_index=extreme_index,
                confirmation_index=index,
                extreme_atr=extreme.atr_at_close,
                raw_salience_atr=raw_salience,
                state_before=state_before,
                state_after=next_state,
                candidate=_candidate(extreme, bar, side),
            )
        )
        state, extreme_index = next_state, index
    return tuple(confirmations)


__all__ = [
    "SOURCE",
    "SwingSalienceConfirmation",
    "SwingSalienceState",
    "detect_causal_swing_salience",
]
