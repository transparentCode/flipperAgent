"""Causal candidates, matched controls, and first-revisit outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from libs.models.sr.detection.causal_swing_salience import (
    SwingSalienceConfirmation,
    detect_causal_swing_salience,
)
from libs.models.sr.domain import ClosedBar, ContractValidationError, SRStateKey, ZoneSide
from libs.models.sr.research.metrics.first_revisit import first_revisit_outcome, prior_close_control_candidate
from libs.models.sr.research.replay.atr import compute_atr_series

from .config import AdaptiveContextCalibrationConfig
from .contracts import (
    CANONICAL_COHORTS,
    CandidateCase,
    ControlRecord,
    NormalizationStatus,
    OutcomeStatus,
    SwingObservation,
    V23SourceMember,
)
from .normalization import NormalizationResult


@dataclass(frozen=True)
class CandidateOutcomeBundle:
    status: OutcomeStatus
    outcome: object | None
    controls: tuple[ControlRecord, ...]
    zone_width_atr: float


def _member_bars(member: V23SourceMember) -> tuple:
    if type(member) is not V23SourceMember:
        raise ContractValidationError("model source requires a V2.3 source member")
    return member.bars


def build_model_bars(
    member: V23SourceMember,
    *,
    config: AdaptiveContextCalibrationConfig,
) -> tuple[ClosedBar, ...]:
    """Compute locked ATR(14) and convert either source cadence to ClosedBar."""

    if type(config) is not AdaptiveContextCalibrationConfig:
        raise ContractValidationError("model bars require typed V2.3 configuration")
    source_bars = _member_bars(member)
    atr_values = compute_atr_series(source_bars, config.atr.expected["period"])
    common_start = config.atr.expected["common_start_index"]
    if len(atr_values) != len(source_bars) or len(source_bars) <= common_start:
        raise ContractValidationError("source cannot satisfy the common ATR start")
    key = SRStateKey(config.venue, member.asset, member.timeframe)
    bars: list[ClosedBar] = []
    for index in range(common_start, len(source_bars)):
        atr = atr_values[index]
        if atr is None:
            raise ContractValidationError("ATR is unavailable at the common start")
        source = source_bars[index]
        bars.append(
            ClosedBar(
                state_key=key,
                bar_id=source.bar_id,
                closed_at=source.closed_at,
                open=source.open,
                high=source.high,
                low=source.low,
                close=source.close,
                atr_at_close=atr,
            )
        )
    return tuple(bars)


def build_swing_observations(
    member: V23SourceMember,
    bars: tuple[ClosedBar, ...],
) -> tuple[tuple[SwingObservation, ...], tuple[SwingSalienceConfirmation, ...]]:
    if type(member) is not V23SourceMember or type(bars) is not tuple or any(type(bar) is not ClosedBar for bar in bars):
        raise ContractValidationError("swing observations require typed source/member bars")
    confirmations = detect_causal_swing_salience(bars)
    observations = tuple(
        SwingObservation(
            asset=member.asset,
            timeframe=member.timeframe,
            side=item.side,
            extreme_bar_id=bars[item.extreme_index].bar_id,
            confirmation_bar_id=bars[item.confirmation_index].bar_id,
            extreme_index=item.extreme_index,
            confirmation_index=item.confirmation_index,
            extreme_atr=item.extreme_atr,
            raw_salience_atr=item.raw_salience_atr,
            state_before=item.state_before.value,
            state_after=item.state_after.value,
            candidate=item.candidate,
        )
        for item in confirmations
    )
    return observations, confirmations


def _fold_for(timestamp: datetime, config: AdaptiveContextCalibrationConfig) -> str | None:
    return next((fold.name for fold in config.folds if fold.start <= timestamp < fold.end), None)


def _fold_end(name: str, config: AdaptiveContextCalibrationConfig) -> datetime:
    for fold in config.folds:
        if fold.name == name:
            return fold.end
    raise ContractValidationError(f"unknown V2.3 fold: {name}")


def _status_and_outcome(
    candidate,
    *,
    confirmation_index: int,
    fold: str,
    bars: tuple[ClosedBar, ...],
    config: AdaptiveContextCalibrationConfig,
) -> tuple[OutcomeStatus, object | None]:
    payload = config.outcome.expected
    outcome = first_revisit_outcome(
        candidate,
        confirmation_index=confirmation_index,
        fold_end=_fold_end(fold, config),
        bars=bars,
        first_touch_offset_bars=payload["first_touch_offset_bars"],
        touch_search_bars=payload["touch_search_bars"],
        horizon_bars=payload["horizon_bars"],
    )
    if outcome is None:
        return OutcomeStatus.NO_TOUCH, None
    return (OutcomeStatus.COMPLETED if outcome.completed else OutcomeStatus.RIGHT_CENSORED), outcome


def evaluate_candidate_outcomes(
    candidate,
    *,
    confirmation_index: int,
    fold: str,
    bars: tuple[ClosedBar, ...],
    config: AdaptiveContextCalibrationConfig,
) -> CandidateOutcomeBundle:
    if confirmation_index <= 0 or confirmation_index >= len(bars):
        raise ContractValidationError("candidate confirmation index is invalid")
    if candidate.available_at != bars[confirmation_index].closed_at:
        raise ContractValidationError("candidate availability does not match confirmation bar")
    width = (candidate.geometry.upper_bound - candidate.geometry.lower_bound) / candidate.atr_at_creation
    if not math.isfinite(width) or width <= 0.0:
        raise ContractValidationError("candidate width in ATR must be finite and positive")
    status, outcome = _status_and_outcome(
        candidate,
        confirmation_index=confirmation_index,
        fold=fold,
        bars=bars,
        config=config,
    )
    prior = bars[confirmation_index - 1]
    controls = []
    for side in (ZoneSide.SUPPORT, ZoneSide.RESISTANCE):
        control_candidate = prior_close_control_candidate(
            candidate,
            prior_bar=prior,
            side=side,
            source="prior_close_naive_v2_3",
        )
        control_status, control_outcome = _status_and_outcome(
            control_candidate,
            confirmation_index=confirmation_index,
            fold=fold,
            bars=bars,
            config=config,
        )
        controls.append(ControlRecord(side, control_candidate, control_status, control_outcome, width))
    return CandidateOutcomeBundle(status, outcome, tuple(controls), width)


def build_candidate_cases(
    member: V23SourceMember,
    bars: tuple[ClosedBar, ...],
    observations: tuple[SwingObservation, ...],
    *,
    config: AdaptiveContextCalibrationConfig,
    normalized: dict[tuple[str, str, str], NormalizationResult],
) -> tuple[CandidateCase, ...]:
    """Build all in-fold real candidates; normalization is supplied causally."""

    if tuple((member.asset, member.timeframe)) not in CANONICAL_COHORTS:
        raise ContractValidationError("member is outside canonical V2.3 cohorts")
    cases = []
    for observation in observations:
        candidate = observation.candidate
        if candidate is None:
            continue
        fold = _fold_for(candidate.available_at, config)
        if fold is None:
            continue
        result = normalized[(member.asset, member.timeframe, observation.confirmation_bar_id)]
        bundle = evaluate_candidate_outcomes(
            candidate,
            confirmation_index=observation.confirmation_index,
            fold=fold,
            bars=bars,
            config=config,
        )
        controls = bundle.controls
        same_side = next(item for item in controls if item.side is candidate.side)
        paired_excess = None
        label = None
        label_at = None
        if bundle.status is OutcomeStatus.COMPLETED and same_side.status is OutcomeStatus.COMPLETED:
            real_outcome = bundle.outcome
            control_outcome = same_side.outcome
            if real_outcome is None or control_outcome is None:
                raise ContractValidationError("completed pair is missing an outcome")
            paired_excess = real_outcome.quality_reference_atr - control_outcome.quality_reference_atr
            label = int(paired_excess > 0.0)
            label_at = max(real_outcome.tenth_outcome_bar_closed_at, control_outcome.tenth_outcome_bar_closed_at)
        cases.append(
            CandidateCase(
                asset=member.asset,
                timeframe=member.timeframe,
                fold=fold,
                confirmation_bar_id=observation.confirmation_bar_id,
                confirmation_index=observation.confirmation_index,
                extreme_bar_id=observation.extreme_bar_id,
                extreme_index=observation.extreme_index,
                candidate=candidate,
                raw_salience_atr=observation.raw_salience_atr,
                percentile=result.percentile,
                bucket=result.bucket,
                normalization_status=result.status,
                real_status=(
                    OutcomeStatus.NORMALIZATION_WARMUP
                    if result.status is NormalizationStatus.NORMALIZATION_WARMUP
                    else bundle.status
                ),
                real_outcome=bundle.outcome,
                controls=controls,
                paired_excess_quality_atr=paired_excess,
                label=label,
                label_available_at=label_at,
                zone_width_atr=bundle.zone_width_atr,
            )
        )
    return tuple(cases)


__all__ = [
    "CandidateOutcomeBundle",
    "build_candidate_cases",
    "build_model_bars",
    "build_swing_observations",
    "evaluate_candidate_outcomes",
]
