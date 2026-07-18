"""Causal raw-band outcomes and independent prior-close naïve controls."""

from __future__ import annotations

from datetime import datetime
import math

from libs.models.sr.detection.displacement_origin import detect_displacement_origins
from libs.models.sr.domain import CandidateLevel, ClosedBar, ContractValidationError, SRStateKey, ZoneGeometry, ZoneSide
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.metrics.first_revisit import intersects_band
from libs.models.sr.research.replay.atr import compute_atr_series
from libs.models.sr.research.source.capsules import SourceCapsule

from .config import DisplacementOriginAdequacyConfig
from .contracts import CandidateCase, NaiveControl, OutcomeStatus


_NAIVE_SOURCE = "prior_close_naive_v2"


def build_model_bars(capsule: SourceCapsule, *, config: DisplacementOriginAdequacyConfig) -> tuple[ClosedBar, ...]:
    if type(capsule) is not SourceCapsule or type(config) is not DisplacementOriginAdequacyConfig:
        raise ContractValidationError("V2.0 model requires typed capsule/configuration")
    atr_values = compute_atr_series(capsule, config.atr.period)
    if len(atr_values) != len(capsule.bars) or len(capsule.bars) <= config.atr.common_start_index:
        raise ContractValidationError("frozen source cannot satisfy common ATR start")
    state_key = SRStateKey(config.venue, config.asset, config.timeframe)
    result: list[ClosedBar] = []
    for index in range(config.atr.common_start_index, len(capsule.bars)):
        source, atr = capsule.bars[index], atr_values[index]
        if atr is None:
            raise ContractValidationError("ATR is unavailable at frozen common start")
        result.append(ClosedBar(state_key=state_key, bar_id=source.bar_id, closed_at=source.closed_at, open=source.open, high=source.high, low=source.low, close=source.close, atr_at_close=atr))
    return tuple(result)


def _fold_for(timestamp: datetime, config: DisplacementOriginAdequacyConfig) -> str | None:
    return next((fold.name for fold in config.folds if fold.start <= timestamp < fold.end), None)


def _fold_end(fold_name: str, config: DisplacementOriginAdequacyConfig) -> datetime:
    for fold in config.folds:
        if fold.name == fold_name:
            return fold.end
    raise ContractValidationError("band references unknown V2.0 fold")


def _intersection(bar: ClosedBar, candidate: CandidateLevel) -> bool:
    return intersects_band(bar, candidate)


def _outcome(*, candidate: CandidateLevel, touch: ClosedBar, touch_index: int, fold_end: datetime, bars: tuple[ClosedBar, ...], config: DisplacementOriginAdequacyConfig) -> FirstTouchOutcome:
    horizon = bars[touch_index + config.outcome.first_touch_offset_bars : touch_index + config.outcome.first_touch_offset_bars + config.outcome.horizon_bars]
    if len(horizon) != config.outcome.horizon_bars or any(bar.closed_at >= fold_end for bar in horizon):
        return FirstTouchOutcome(zone_id=candidate.candidate_id, side=candidate.side, first_touch_at=touch.closed_at, touch_bar_id=touch.bar_id, anchor_close=touch.close, reference_atr_14=touch.atr_at_close, completed=False, right_censored=True, tenth_outcome_bar_closed_at=None, favorable_reference_atr=None, adverse_reference_atr=None, quality_reference_atr=None, invalidated=False)
    if candidate.side is ZoneSide.SUPPORT:
        favorable_raw = max(max(bar.high for bar in horizon) - touch.close, 0.0)
        adverse_raw = max(touch.close - min(bar.low for bar in horizon), 0.0)
    else:
        favorable_raw = max(touch.close - min(bar.low for bar in horizon), 0.0)
        adverse_raw = max(max(bar.high for bar in horizon) - touch.close, 0.0)
    favorable, adverse = favorable_raw / touch.atr_at_close, adverse_raw / touch.atr_at_close
    quality = favorable - adverse
    if not all(math.isfinite(value) for value in (favorable, adverse, quality)):
        raise ContractValidationError("V2.0 outcome metrics must be finite")
    return FirstTouchOutcome(zone_id=candidate.candidate_id, side=candidate.side, first_touch_at=touch.closed_at, touch_bar_id=touch.bar_id, anchor_close=touch.close, reference_atr_14=touch.atr_at_close, completed=True, right_censored=False, tenth_outcome_bar_closed_at=horizon[-1].closed_at, favorable_reference_atr=favorable, adverse_reference_atr=adverse, quality_reference_atr=quality, invalidated=False)


def _evaluate_band(*, candidate: CandidateLevel, confirmation_index: int, fold: str, bars: tuple[ClosedBar, ...], config: DisplacementOriginAdequacyConfig) -> tuple[OutcomeStatus, FirstTouchOutcome | None]:
    fold_end = _fold_end(fold, config)
    start = confirmation_index + config.outcome.first_touch_offset_bars
    stop = min(start + config.outcome.touch_search_bars, len(bars))
    touch_index = next((index for index in range(start, stop) if bars[index].closed_at < fold_end and _intersection(bars[index], candidate)), None)
    if touch_index is None:
        return OutcomeStatus.NO_TOUCH, None
    outcome = _outcome(candidate=candidate, touch=bars[touch_index], touch_index=touch_index, fold_end=fold_end, bars=bars, config=config)
    return (OutcomeStatus.COMPLETED if outcome.completed else OutcomeStatus.RIGHT_CENSORED), outcome


def evaluate_candidates(bars: tuple[ClosedBar, ...], *, config: DisplacementOriginAdequacyConfig) -> tuple[CandidateCase, ...]:
    if type(bars) is not tuple or any(type(bar) is not ClosedBar for bar in bars):
        raise ContractValidationError("V2.0 candidates require ClosedBar tuple")
    positions = {bar.closed_at: index for index, bar in enumerate(bars)}
    cases: list[CandidateCase] = []
    for candidate in detect_displacement_origins(bars, config.detector):
        confirmation_index, base_index = positions.get(candidate.available_at), positions.get(candidate.formed_at)
        if confirmation_index is None or base_index is None or base_index >= confirmation_index:
            raise ContractValidationError("candidate timing cannot be aligned to V2.0 bars")
        width_atr = (candidate.geometry.upper_bound - candidate.geometry.lower_bound) / candidate.atr_at_creation
        if not math.isfinite(width_atr) or width_atr <= 0.0:
            raise ContractValidationError("candidate zone width in ATR must be finite and positive")
        fold = _fold_for(candidate.available_at, config)
        if fold is None:
            status, outcome = OutcomeStatus.OUTSIDE_FOLDS, None
        else:
            status, outcome = _evaluate_band(candidate=candidate, confirmation_index=confirmation_index, fold=fold, bars=bars, config=config)
        cases.append(CandidateCase(candidate=candidate, confirmation_bar_id=bars[confirmation_index].bar_id, confirmation_index=confirmation_index, base_distance_bars=confirmation_index - base_index, fold=fold, status=status, outcome=outcome, zone_width_atr=width_atr))
    if len({item.candidate.candidate_id for item in cases}) != len(cases):
        raise ContractValidationError("V2.0 candidates must be unique")
    return tuple(cases)


def build_naive_controls(cases: tuple[CandidateCase, ...], bars: tuple[ClosedBar, ...], *, config: DisplacementOriginAdequacyConfig) -> tuple[NaiveControl, ...]:
    """Build two prior-close bands for every in-fold candidate before outcomes pair."""
    if type(cases) is not tuple or any(type(item) is not CandidateCase for item in cases):
        raise ContractValidationError("V2.0 controls require CandidateCase tuple")
    if type(bars) is not tuple or any(type(item) is not ClosedBar for item in bars):
        raise ContractValidationError("V2.0 controls require ClosedBar tuple")
    controls: list[NaiveControl] = []
    for case in cases:
        if case.fold is None:
            continue
        if case.confirmation_index <= 0 or bars[case.confirmation_index].bar_id != case.confirmation_bar_id:
            raise ContractValidationError("control confirmation cannot be aligned")
        prior = bars[case.confirmation_index - 1]
        for side in config.control_side_order:
            candidate = CandidateLevel(state_key=case.candidate.state_key, side=side, geometry=ZoneGeometry(center=prior.close, half_width=case.candidate.geometry.half_width), source=_NAIVE_SOURCE, formed_at=prior.closed_at, available_at=case.candidate.available_at, atr_at_creation=case.candidate.atr_at_creation)
            status, outcome = _evaluate_band(candidate=candidate, confirmation_index=case.confirmation_index, fold=case.fold, bars=bars, config=config)
            controls.append(
                NaiveControl(
                    real_confirmation_id=case.confirmation_id,
                    candidate=candidate,
                    confirmation_bar_id=case.confirmation_bar_id,
                    confirmation_index=case.confirmation_index,
                    fold=case.fold,
                    status=status,
                    outcome=outcome,
                    zone_width_atr=case.zone_width_atr,
                )
            )
    if len(controls) != sum(case.fold is not None for case in cases) * config.controls_per_real_candidate:
        raise ContractValidationError("naive control count does not reconcile to in-fold candidates")
    return tuple(controls)


__all__ = ["build_model_bars", "build_naive_controls", "evaluate_candidates"]
