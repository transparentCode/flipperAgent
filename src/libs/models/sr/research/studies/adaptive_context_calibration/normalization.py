"""Causal, asset/timeframe-local swing salience normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import require_utc, utc_isoformat

from .contracts import NormalizationStatus, SalienceBucket


HISTORY_DAYS = 365


@dataclass(frozen=True)
class SaliencePoint:
    asset: str
    timeframe: str
    confirmation_at: datetime
    raw_salience_atr: float

    def __post_init__(self) -> None:
        if type(self.asset) is not str or not self.asset or type(self.timeframe) is not str or not self.timeframe:
            raise ContractValidationError("salience point asset/timeframe must be non-empty strings")
        object.__setattr__(self, "confirmation_at", require_utc(self.confirmation_at, field_name="salience.confirmation_at"))
        try:
            value = float(self.raw_salience_atr)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractValidationError("salience raw value must be finite") from exc
        if not math.isfinite(value) or value < 0.0:
            raise ContractValidationError("salience raw value must be finite and non-negative")
        object.__setattr__(self, "raw_salience_atr", 0.0 if value == 0.0 else value)


@dataclass(frozen=True)
class NormalizationResult:
    status: NormalizationStatus
    percentile: float | None
    bucket: SalienceBucket | None
    prior_count: int

    def __post_init__(self) -> None:
        if type(self.status) is not NormalizationStatus:
            raise ContractValidationError("normalization status is invalid")
        if type(self.prior_count) is not int or self.prior_count < 0:
            raise ContractValidationError("normalization prior_count must be non-negative")
        if self.status is NormalizationStatus.NORMALIZATION_WARMUP:
            if self.prior_count != 0 or self.percentile is not None or self.bucket is not None:
                raise ContractValidationError("normalization warmup result is inconsistent")
        else:
            if self.prior_count <= 0 or self.percentile is None or type(self.bucket) is not SalienceBucket:
                raise ContractValidationError("ready normalization result is incomplete")
            if not 0.0 <= self.percentile <= 1.0:
                raise ContractValidationError("normalization percentile must be in [0, 1]")

    def to_payload(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "percentile": self.percentile,
            "bucket": None if self.bucket is None else self.bucket.value,
            "prior_count": self.prior_count,
        }


def midrank_percentile(current: float, prior_values: tuple[float, ...]) -> float:
    """Return the deterministic midrank percentile for a non-empty history."""

    try:
        current_value = float(current)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractValidationError("current salience must be finite") from exc
    if not math.isfinite(current_value) or current_value < 0.0:
        raise ContractValidationError("current salience must be finite and non-negative")
    if type(prior_values) is not tuple or not prior_values:
        raise ContractValidationError("midrank percentile requires prior observations")
    values = []
    for value in prior_values:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractValidationError("prior salience must be finite") from exc
        if not math.isfinite(number) or number < 0.0:
            raise ContractValidationError("prior salience must be finite and non-negative")
        values.append(number)
    lower = sum(value < current_value for value in values)
    ties = sum(value == current_value for value in values)
    return (lower + 0.5 * ties) / len(values)


def salience_bucket(percentile: float) -> SalienceBucket:
    value = float(percentile)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ContractValidationError("salience percentile must be in [0, 1]")
    if value < 0.25:
        return SalienceBucket.Q1
    if value < 0.50:
        return SalienceBucket.Q2
    if value < 0.75:
        return SalienceBucket.Q3
    return SalienceBucket.Q4


def normalize_salience(
    current: SaliencePoint,
    history: tuple[SaliencePoint, ...],
    *,
    history_days: int = HISTORY_DAYS,
) -> NormalizationResult:
    """Normalize against only prior same-asset/timeframe observations."""

    if type(current) is not SaliencePoint or type(history) is not tuple or any(type(item) is not SaliencePoint for item in history):
        raise ContractValidationError("normalization requires typed salience points")
    if history_days != HISTORY_DAYS:
        raise ContractValidationError("V2.3 normalization history is fixed at 365 days")
    lower_bound = current.confirmation_at - timedelta(days=HISTORY_DAYS)
    prior = tuple(
        item.raw_salience_atr
        for item in history
        if item.asset == current.asset
        and item.timeframe == current.timeframe
        and lower_bound <= item.confirmation_at < current.confirmation_at
        and math.isfinite(item.raw_salience_atr)
    )
    if not prior:
        return NormalizationResult(NormalizationStatus.NORMALIZATION_WARMUP, None, None, 0)
    percentile = midrank_percentile(current.raw_salience_atr, prior)
    return NormalizationResult(NormalizationStatus.READY, percentile, salience_bucket(percentile), len(prior))


def point_payload(point: SaliencePoint) -> dict[str, object]:
    if type(point) is not SaliencePoint:
        raise ContractValidationError("point must be exactly SaliencePoint")
    return {
        "asset": point.asset,
        "timeframe": point.timeframe,
        "confirmation_at": utc_isoformat(point.confirmation_at),
        "raw_salience_atr": point.raw_salience_atr,
    }


__all__ = [
    "HISTORY_DAYS",
    "NormalizationResult",
    "SaliencePoint",
    "midrank_percentile",
    "normalize_salience",
    "point_payload",
    "salience_bucket",
]
