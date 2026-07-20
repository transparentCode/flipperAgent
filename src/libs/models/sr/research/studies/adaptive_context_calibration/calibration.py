"""Causal hierarchical Beta calibration and the declared base-rate null."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from scipy.stats import beta as beta_distribution

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import require_utc, utc_isoformat

from .contracts import PosteriorState, SalienceBucket


HISTORY_DAYS = 365
PRIOR_ALPHA = 0.5
PRIOR_BETA = 0.5


@dataclass(frozen=True)
class HistoricalLabel:
    asset: str
    timeframe: str
    bucket: SalienceBucket
    label: int
    label_available_at: datetime
    paired_excess_quality_atr: float

    def __post_init__(self) -> None:
        if type(self.asset) is not str or not self.asset or type(self.timeframe) is not str or not self.timeframe:
            raise ContractValidationError("historical label asset/timeframe must be non-empty strings")
        if type(self.bucket) is not SalienceBucket or self.label not in (0, 1):
            raise ContractValidationError("historical label bucket/label is invalid")
        object.__setattr__(self, "label_available_at", require_utc(self.label_available_at, field_name="label.label_available_at"))
        try:
            excess = float(self.paired_excess_quality_atr)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractValidationError("historical label paired excess must be finite") from exc
        if not math.isfinite(excess):
            raise ContractValidationError("historical label paired excess must be finite")
        object.__setattr__(self, "paired_excess_quality_atr", excess)

    def to_payload(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "bucket": self.bucket.value,
            "label": self.label,
            "label_available_at": utc_isoformat(self.label_available_at),
            "paired_excess_quality_atr": self.paired_excess_quality_atr,
        }


@dataclass(frozen=True)
class CalibrationResult:
    global_state: PosteriorState
    asset_state: PosteriorState
    final_state: PosteriorState
    null_state: PosteriorState
    global_counts: tuple[int, int]
    asset_counts: tuple[int, int]
    local_counts: tuple[int, int]
    null_counts: tuple[int, int]

    def __post_init__(self) -> None:
        states = (self.global_state, self.asset_state, self.final_state, self.null_state)
        if any(type(state) is not PosteriorState for state in states):
            raise ContractValidationError("calibration result contains invalid posterior state")
        for name in ("global_counts", "asset_counts", "local_counts", "null_counts"):
            value = getattr(self, name)
            if type(value) is not tuple or len(value) != 2 or any(type(item) is not int or item < 0 for item in value):
                raise ContractValidationError(f"{name} must be a non-negative success/failure pair")

    def to_payload(self) -> dict[str, object]:
        return {
            "global": self.global_state.to_payload(),
            "asset": self.asset_state.to_payload(),
            "final": self.final_state.to_payload(),
            "null": self.null_state.to_payload(),
            "global_counts": list(self.global_counts),
            "asset_counts": list(self.asset_counts),
            "local_counts": list(self.local_counts),
            "null_counts": list(self.null_counts),
        }


def _count(labels: tuple[HistoricalLabel, ...]) -> tuple[int, int]:
    successes = sum(item.label == 1 for item in labels)
    return successes, len(labels) - successes


def _posterior(successes: int, failures: int, alpha: float, beta: float) -> PosteriorState:
    if alpha <= 0.0 or beta <= 0.0 or not math.isfinite(alpha) or not math.isfinite(beta):
        raise ContractValidationError("posterior parameters must be finite and positive")
    probability = alpha / (alpha + beta)
    lower = float(beta_distribution.ppf(0.05, alpha, beta))
    upper = float(beta_distribution.ppf(0.95, alpha, beta))
    if not all(math.isfinite(value) for value in (probability, lower, upper)):
        raise ContractValidationError("Beta credible interval is not finite")
    return PosteriorState(successes, failures, alpha, beta, probability, lower, upper)


def _eligible(
    labels: tuple[HistoricalLabel, ...],
    *,
    prediction_at: datetime,
    history_days: int,
) -> tuple[HistoricalLabel, ...]:
    lower = prediction_at - timedelta(days=history_days)
    return tuple(item for item in labels if lower <= item.label_available_at < prediction_at)


def calibrate(
    *,
    target_asset: str,
    target_timeframe: str,
    bucket: SalienceBucket,
    prediction_at: datetime,
    labels: tuple[HistoricalLabel, ...],
    history_days: int = HISTORY_DAYS,
) -> CalibrationResult:
    """Compute the fixed external-asset, asset, local, and null posteriors."""

    if type(bucket) is not SalienceBucket or type(labels) is not tuple or any(type(item) is not HistoricalLabel for item in labels):
        raise ContractValidationError("calibration requires typed bucket/labels")
    if type(target_asset) is not str or not target_asset or type(target_timeframe) is not str or not target_timeframe:
        raise ContractValidationError("calibration target asset/timeframe must be non-empty strings")
    prediction_at = require_utc(prediction_at, field_name="calibration.prediction_at")
    if history_days != HISTORY_DAYS:
        raise ContractValidationError("V2.3 calibration history is fixed at 365 days")
    eligible = _eligible(labels, prediction_at=prediction_at, history_days=HISTORY_DAYS)
    bucketed = tuple(item for item in eligible if item.bucket is bucket)
    other_asset = tuple(item for item in bucketed if item.asset != target_asset)
    other_timeframe = tuple(item for item in bucketed if item.asset == target_asset and item.timeframe != target_timeframe)
    local = tuple(item for item in bucketed if item.asset == target_asset and item.timeframe == target_timeframe)
    all_labels = eligible
    global_successes, global_failures = _count(other_asset)
    if global_successes + global_failures:
        mu = (PRIOR_ALPHA + global_successes) / (PRIOR_ALPHA + PRIOR_BETA + global_successes + global_failures)
        kappa = math.sqrt(global_successes + global_failures)
        alpha_0, beta_0 = mu * kappa, (1.0 - mu) * kappa
    else:
        alpha_0, beta_0 = PRIOR_ALPHA, PRIOR_BETA
    asset_successes, asset_failures = _count(other_timeframe)
    local_successes, local_failures = _count(local)
    null_successes, null_failures = _count(all_labels)
    global_state = _posterior(global_successes, global_failures, alpha_0, beta_0)
    asset_state = _posterior(asset_successes, asset_failures, alpha_0 + asset_successes, beta_0 + asset_failures)
    final_state = _posterior(local_successes, local_failures, alpha_0 + asset_successes + local_successes, beta_0 + asset_failures + local_failures)
    null_state = _posterior(null_successes, null_failures, PRIOR_ALPHA + null_successes, PRIOR_BETA + null_failures)
    return CalibrationResult(
        global_state=global_state,
        asset_state=asset_state,
        final_state=final_state,
        null_state=null_state,
        global_counts=(global_successes, global_failures),
        asset_counts=(asset_successes, asset_failures),
        local_counts=(local_successes, local_failures),
        null_counts=(null_successes, null_failures),
    )


def brier_loss(probability: float, label: int) -> float:
    if label not in (0, 1) or not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise ContractValidationError("Brier loss requires a finite probability in (0, 1) and a binary label")
    return (probability - label) ** 2


def log_loss(probability: float, label: int) -> float:
    if label not in (0, 1) or not math.isfinite(probability) or not 0.0 < probability < 1.0:
        raise ContractValidationError("log loss requires a finite probability in (0, 1) and a binary label")
    return -math.log(probability if label else 1.0 - probability)


__all__ = [
    "CalibrationResult",
    "HistoricalLabel",
    "brier_loss",
    "calibrate",
    "log_loss",
]
