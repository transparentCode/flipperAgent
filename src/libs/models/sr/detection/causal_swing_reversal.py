"""Pure, non-repainting causal swing-reversal wick-band detection for V2.2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.candidates import CandidateLevel
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.geometry import ZoneGeometry
from libs.models.sr.domain.zones import ZoneSide


_SOURCE = "causal_swing_reversal_v2_2"


class SwingMode(str, Enum):
    UNSEEDED = "UNSEEDED"
    SEEK_HIGH = "SEEK_HIGH"
    SEEK_LOW = "SEEK_LOW"


@dataclass(frozen=True)
class CausalSwingReversalConfig:
    reversal_atr: float

    def __post_init__(self) -> None:
        if type(self.reversal_atr) not in (int, float) or isinstance(
            self.reversal_atr, bool
        ):
            raise ContractValidationError("reversal_atr must be a finite number")
        value = float(self.reversal_atr)
        if not math.isfinite(value) or value <= 0.0:
            raise ContractValidationError("reversal_atr must be positive and finite")
        object.__setattr__(self, "reversal_atr", 0.0 if value == 0.0 else value)

    def to_payload(self) -> dict[str, float]:
        return {"reversal_atr": self.reversal_atr}


@dataclass(frozen=True)
class SwingConfirmation:
    """One causally confirmed alternating swing, whether or not wick emits."""

    side: ZoneSide
    extreme_index: int
    confirmation_index: int
    extreme_atr: float
    candidate: CandidateLevel | None

    def __post_init__(self) -> None:
        if type(self.side) is not ZoneSide:
            raise ContractValidationError("swing side must be exactly ZoneSide")
        for name in ("extreme_index", "confirmation_index"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ContractValidationError(
                    f"swing {name} must be a non-negative integer"
                )
        if self.extreme_index >= self.confirmation_index:
            raise ContractValidationError("swing extreme must precede confirmation")
        if type(self.extreme_atr) not in (int, float) or isinstance(
            self.extreme_atr, bool
        ):
            raise ContractValidationError("swing extreme_atr must be a finite number")
        extreme_atr = float(self.extreme_atr)
        if not math.isfinite(extreme_atr) or extreme_atr <= 0.0:
            raise ContractValidationError(
                "swing extreme_atr must be positive and finite"
            )
        object.__setattr__(self, "extreme_atr", extreme_atr)
        if self.candidate is not None:
            if (
                type(self.candidate) is not CandidateLevel
                or self.candidate.side is not self.side
            ):
                raise ContractValidationError(
                    "swing candidate side/type does not reconcile"
                )


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
                f"bars[{index}].state_key must match swing state_key"
            )
        if bar.bar_id in seen:
            raise ContractValidationError(
                f"duplicate bar_id in swing bars: {bar.bar_id}"
            )
        if previous is not None and bar.closed_at <= previous:
            raise ContractValidationError(
                "swing bar timestamps must be strictly increasing"
            )
        seen.add(bar.bar_id)
        previous = bar.closed_at


def _candidate(
    extreme: ClosedBar, confirmation: ClosedBar, side: ZoneSide
) -> CandidateLevel | None:
    lower, upper = (
        (max(extreme.open, extreme.close), extreme.high)
        if side is ZoneSide.RESISTANCE
        else (extreme.low, min(extreme.open, extreme.close))
    )
    values = (lower, upper, confirmation.atr_at_close)
    if not all(math.isfinite(value) for value in values):
        raise ContractValidationError(
            "swing geometry and confirmation ATR must be finite"
        )
    width = upper - lower
    if not math.isfinite(width):
        raise ContractValidationError("swing wick width must be finite")
    if width <= 0.0:
        return None
    center, half_width = (lower + upper) / 2.0, width / 2.0
    if not all(math.isfinite(value) for value in (center, half_width)):
        raise ContractValidationError("swing derived geometry must be finite")
    geometry = ZoneGeometry(center=center, half_width=half_width)
    if not all(
        math.isfinite(value) for value in (geometry.lower_bound, geometry.upper_bound)
    ):
        raise ContractValidationError("swing geometry bounds must be finite")
    return CandidateLevel(
        state_key=extreme.state_key,
        side=side,
        geometry=geometry,
        source=_SOURCE,
        formed_at=extreme.closed_at,
        available_at=confirmation.closed_at,
        atr_at_creation=confirmation.atr_at_close,
    )


def _seed_extreme(bars: tuple[ClosedBar, ...], index: int, mode: SwingMode) -> int:
    if mode is SwingMode.SEEK_HIGH:
        return max(range(index + 1), key=lambda item: bars[item].high)
    return min(range(index + 1), key=lambda item: bars[item].low)


def detect_causal_swing_reversals(
    bars: tuple[ClosedBar, ...], config: CausalSwingReversalConfig
) -> tuple[SwingConfirmation, ...]:
    """Return alternating, point-in-time swing confirmations.

    ``candidate`` remains ``None`` for a zero directional wick; transition
    state remains recorded so later swings cannot be altered by geometry.
    """
    _validate_bars(bars)
    if type(config) is not CausalSwingReversalConfig:
        raise ContractValidationError(
            "config must be exactly CausalSwingReversalConfig"
        )
    mode = SwingMode.UNSEEDED
    extreme_index = 0
    confirmations: list[SwingConfirmation] = []
    for index in range(1, len(bars)):
        bar = bars[index]
        if mode is SwingMode.UNSEEDED:
            previous = bars[index - 1]
            if bar.close > previous.close:
                mode = SwingMode.SEEK_HIGH
                extreme_index = _seed_extreme(bars, index, mode)
            elif bar.close < previous.close:
                mode = SwingMode.SEEK_LOW
                extreme_index = _seed_extreme(bars, index, mode)
            continue

        extreme = bars[extreme_index]
        if mode is SwingMode.SEEK_HIGH:
            if bar.high > extreme.high:
                extreme_index = index
                continue
            threshold = extreme.high - config.reversal_atr * extreme.atr_at_close
            if not math.isfinite(threshold):
                raise ContractValidationError(
                    "swing high reversal threshold must be finite"
                )
            if bar.close <= threshold:
                confirmations.append(
                    SwingConfirmation(
                        side=ZoneSide.RESISTANCE,
                        extreme_index=extreme_index,
                        confirmation_index=index,
                        extreme_atr=extreme.atr_at_close,
                        candidate=_candidate(extreme, bar, ZoneSide.RESISTANCE),
                    )
                )
                mode, extreme_index = SwingMode.SEEK_LOW, index
            continue

        if bar.low < extreme.low:
            extreme_index = index
            continue
        threshold = extreme.low + config.reversal_atr * extreme.atr_at_close
        if not math.isfinite(threshold):
            raise ContractValidationError("swing low reversal threshold must be finite")
        if bar.close >= threshold:
            confirmations.append(
                SwingConfirmation(
                    side=ZoneSide.SUPPORT,
                    extreme_index=extreme_index,
                    confirmation_index=index,
                    extreme_atr=extreme.atr_at_close,
                    candidate=_candidate(extreme, bar, ZoneSide.SUPPORT),
                )
            )
            mode, extreme_index = SwingMode.SEEK_HIGH, index
    return tuple(confirmations)


def detect_causal_swing_reversal_bands(
    bars: tuple[ClosedBar, ...], config: CausalSwingReversalConfig
) -> tuple[CandidateLevel, ...]:
    """Return deterministic emitted wick bands from confirmed swings."""
    return tuple(
        sorted(
            (
                item.candidate
                for item in detect_causal_swing_reversals(bars, config)
                if item.candidate is not None
            ),
            key=lambda item: (
                item.available_at,
                0 if item.side is ZoneSide.RESISTANCE else 1,
                item.candidate_id,
            ),
        )
    )


__all__ = [
    "CausalSwingReversalConfig",
    "SwingConfirmation",
    "SwingMode",
    "detect_causal_swing_reversal_bands",
    "detect_causal_swing_reversals",
]
