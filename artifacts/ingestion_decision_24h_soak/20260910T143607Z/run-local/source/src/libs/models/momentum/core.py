"""Pure deterministic semantic core for the Momentum model."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from numbers import Real

from libs.models.momentum.config import MomentumConfig


def coerce_numeric_evidence(value: object, *, field_name: str) -> float:
    """Normalize one Momentum numeric evidence value or reject it."""

    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise TypeError(f"{field_name} must be a finite numeric value")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class MomentumObservation:
    """The complete feature evidence consumed by one Momentum evaluation."""

    rsi: float
    macd_histogram: float
    macd_line: float | None = None

    def __post_init__(self) -> None:
        rsi = coerce_numeric_evidence(self.rsi, field_name="rsi")
        macd_histogram = coerce_numeric_evidence(
            self.macd_histogram,
            field_name="macd_histogram",
        )
        macd_line = (
            None
            if self.macd_line is None
            else coerce_numeric_evidence(self.macd_line, field_name="macd_line")
        )
        if not 0.0 <= rsi <= 100.0:
            raise ValueError("rsi must be between 0 and 100")
        object.__setattr__(self, "rsi", rsi)
        object.__setattr__(self, "macd_histogram", macd_histogram)
        object.__setattr__(self, "macd_line", macd_line)


@dataclass(frozen=True, slots=True)
class MomentumResult:
    """Stable output of one Momentum evaluation."""

    direction: int
    conviction: float
    score: float

    def __post_init__(self) -> None:
        if isinstance(self.direction, bool) or self.direction not in {-1, 0, 1}:
            raise ValueError("direction must be -1, 0, or 1")
        conviction = coerce_numeric_evidence(self.conviction, field_name="conviction")
        score = coerce_numeric_evidence(self.score, field_name="score")
        if not 0.0 <= conviction <= 1.0:
            raise ValueError("conviction must be between 0 and 1")
        if score != self.direction * conviction:
            raise ValueError("score must equal direction * conviction")
        if self.direction == 0 and (conviction != 0.0 or score != 0.0):
            raise ValueError("neutral results must have zero conviction and score")
        object.__setattr__(self, "conviction", conviction)
        object.__setattr__(self, "score", score)

    @classmethod
    def neutral(cls) -> MomentumResult:
        return cls(direction=0, conviction=0.0, score=0.0)


def _result(direction: int, conviction: float) -> MomentumResult:
    return MomentumResult(
        direction=direction,
        conviction=conviction,
        score=direction * conviction,
    )


def evaluate_momentum(
    observation: MomentumObservation,
    config: MomentumConfig,
) -> MomentumResult:
    """Evaluate the frozen RSI/MACD directional confirmation rule."""

    if not isinstance(observation, MomentumObservation):
        raise TypeError("observation must be a MomentumObservation")
    if not isinstance(config, MomentumConfig):
        raise TypeError("config must be a MomentumConfig")

    histogram_qualifies = abs(observation.macd_histogram) >= config.histogram_min_abs
    if (
        observation.rsi > config.rsi_long_threshold
        and observation.macd_histogram > 0
        and histogram_qualifies
        and (
            not config.require_macd_positive
            or (observation.macd_line is not None and observation.macd_line > 0)
        )
    ):
        return _result(1, min(1.0, (observation.rsi - 50.0) / 50.0))

    if (
        observation.rsi < config.rsi_short_threshold
        and observation.macd_histogram < 0
        and histogram_qualifies
        and (
            not config.require_macd_positive
            or (observation.macd_line is not None and observation.macd_line < 0)
        )
    ):
        return _result(-1, min(1.0, (50.0 - observation.rsi) / 50.0))

    return MomentumResult.neutral()


__all__ = [
    "MomentumObservation",
    "MomentumResult",
    "coerce_numeric_evidence",
    "evaluate_momentum",
]
