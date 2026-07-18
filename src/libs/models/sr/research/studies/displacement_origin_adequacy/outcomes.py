"""Causal raw-zone first-touch outcomes and matched controls for SR-V2.0."""

from __future__ import annotations

from datetime import datetime
import math

from libs.models.sr.detection.displacement_origin import detect_displacement_origins
from libs.models.sr.domain import ClosedBar, ContractValidationError, SRStateKey, ZoneSide
from libs.models.sr.research.evidence.baseline_adequacy.contracts import (
    ControlAnchor,
    ControlEligibilityReason,
)
from libs.models.sr.research.evidence.baseline_adequacy.controls import (
    compute_control_outcome,
)
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.replay.atr import compute_atr_series
from libs.models.sr.research.source.capsules import SourceCapsule

from .config import DisplacementOriginAdequacyConfig
from .contracts import CandidateCase, MatchedControl, OutcomeStatus


def build_model_bars(
    capsule: SourceCapsule,
    *,
    config: DisplacementOriginAdequacyConfig,
) -> tuple[ClosedBar, ...]:
    """Build the point-in-time ATR-aligned closed-bar sequence once."""
    if type(capsule) is not SourceCapsule:
        raise ContractValidationError("V2.0 model requires exactly SourceCapsule")
    if type(config) is not DisplacementOriginAdequacyConfig:
        raise ContractValidationError("V2.0 model requires typed configuration")
    atr_values = compute_atr_series(capsule, config.atr.period)
    if len(atr_values) != len(capsule.bars) or len(capsule.bars) <= config.atr.common_start_index:
        raise ContractValidationError("frozen source cannot satisfy common ATR start")
    state_key = SRStateKey(config.venue, config.asset, config.timeframe)
    bars: list[ClosedBar] = []
    for source_index in range(config.atr.common_start_index, len(capsule.bars)):
        source = capsule.bars[source_index]
        atr = atr_values[source_index]
        if atr is None:
            raise ContractValidationError("ATR is unavailable at the frozen common start")
        bars.append(
            ClosedBar(
                state_key=state_key,
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


def _fold_for(timestamp: datetime, config: DisplacementOriginAdequacyConfig) -> str | None:
    for fold in config.folds:
        if fold.start <= timestamp < fold.end:
            return fold.name
    return None


def _fold_end(fold_name: str, config: DisplacementOriginAdequacyConfig) -> datetime:
    for fold in config.folds:
        if fold.name == fold_name:
            return fold.end
    raise ContractValidationError("case references an unknown V2.0 fold")


def _intersection(bar: ClosedBar, *, lower: float, upper: float) -> bool:
    return bar.high >= lower and bar.low <= upper


def _outcome(
    *,
    candidate_id: str,
    side: ZoneSide,
    touch: ClosedBar,
    touch_index: int,
    fold_end: datetime,
    bars: tuple[ClosedBar, ...],
    config: DisplacementOriginAdequacyConfig,
) -> FirstTouchOutcome:
    start_index = touch_index + config.outcome.first_touch_offset_bars
    end_index = start_index + config.outcome.horizon_bars
    horizon = bars[start_index:end_index]
    if len(horizon) != config.outcome.horizon_bars or any(
        bar.closed_at >= fold_end for bar in horizon
    ):
        return FirstTouchOutcome(
            zone_id=candidate_id,
            side=side,
            first_touch_at=touch.closed_at,
            touch_bar_id=touch.bar_id,
            anchor_close=touch.close,
            reference_atr_14=touch.atr_at_close,
            completed=False,
            right_censored=True,
            tenth_outcome_bar_closed_at=None,
            favorable_reference_atr=None,
            adverse_reference_atr=None,
            quality_reference_atr=None,
            invalidated=False,
        )
    if side is ZoneSide.SUPPORT:
        favorable_raw = max(max(bar.high for bar in horizon) - touch.close, 0.0)
        adverse_raw = max(touch.close - min(bar.low for bar in horizon), 0.0)
    elif side is ZoneSide.RESISTANCE:
        favorable_raw = max(touch.close - min(bar.low for bar in horizon), 0.0)
        adverse_raw = max(max(bar.high for bar in horizon) - touch.close, 0.0)
    else:  # pragma: no cover - ZoneSide is closed.
        raise ContractValidationError("unsupported candidate side")
    favorable = favorable_raw / touch.atr_at_close
    adverse = adverse_raw / touch.atr_at_close
    quality = favorable - adverse
    if not all(math.isfinite(value) for value in (favorable, adverse, quality)):
        raise ContractValidationError("V2.0 outcome metrics must be finite")
    return FirstTouchOutcome(
        zone_id=candidate_id,
        side=side,
        first_touch_at=touch.closed_at,
        touch_bar_id=touch.bar_id,
        anchor_close=touch.close,
        reference_atr_14=touch.atr_at_close,
        completed=True,
        right_censored=False,
        tenth_outcome_bar_closed_at=horizon[-1].closed_at,
        favorable_reference_atr=favorable,
        adverse_reference_atr=adverse,
        quality_reference_atr=quality,
        invalidated=False,
    )


def evaluate_candidates(
    bars: tuple[ClosedBar, ...],
    *,
    config: DisplacementOriginAdequacyConfig,
) -> tuple[CandidateCase, ...]:
    """Evaluate raw candidate bands without lifecycle or association mutation."""
    if type(bars) is not tuple or any(type(bar) is not ClosedBar for bar in bars):
        raise ContractValidationError("V2.0 candidates require ClosedBar tuple")
    candidates = detect_displacement_origins(bars, config.detector)
    positions = {bar.closed_at: index for index, bar in enumerate(bars)}
    cases: list[CandidateCase] = []
    for candidate in candidates:
        confirmation_index = positions.get(candidate.available_at)
        base_index = positions.get(candidate.formed_at)
        if confirmation_index is None or base_index is None or base_index >= confirmation_index:
            raise ContractValidationError("candidate timing cannot be aligned to V2.0 bars")
        fold = _fold_for(candidate.available_at, config)
        width_atr = (candidate.geometry.upper_bound - candidate.geometry.lower_bound) / candidate.atr_at_creation
        if not math.isfinite(width_atr) or width_atr <= 0.0:
            raise ContractValidationError("candidate zone width in ATR must be finite and positive")
        if fold is None:
            cases.append(
                CandidateCase(
                    candidate=candidate,
                    confirmation_bar_id=bars[confirmation_index].bar_id,
                    confirmation_index=confirmation_index,
                    base_distance_bars=confirmation_index - base_index,
                    fold=None,
                    status=OutcomeStatus.OUTSIDE_FOLDS,
                    outcome=None,
                    zone_width_atr=width_atr,
                )
            )
            continue
        fold_end = _fold_end(fold, config)
        start = confirmation_index + config.outcome.first_touch_offset_bars
        stop = min(start + config.outcome.touch_search_bars, len(bars))
        touch_index = next(
            (
                index
                for index in range(start, stop)
                if bars[index].closed_at < fold_end
                and _intersection(
                    bars[index],
                    lower=candidate.geometry.lower_bound,
                    upper=candidate.geometry.upper_bound,
                )
            ),
            None,
        )
        if touch_index is None:
            cases.append(
                CandidateCase(
                    candidate=candidate,
                    confirmation_bar_id=bars[confirmation_index].bar_id,
                    confirmation_index=confirmation_index,
                    base_distance_bars=confirmation_index - base_index,
                    fold=fold,
                    status=OutcomeStatus.NO_TOUCH,
                    outcome=None,
                    zone_width_atr=width_atr,
                )
            )
            continue
        outcome = _outcome(
            candidate_id=candidate.candidate_id,
            side=candidate.side,
            touch=bars[touch_index],
            touch_index=touch_index,
            fold_end=fold_end,
            bars=bars,
            config=config,
        )
        cases.append(
            CandidateCase(
                candidate=candidate,
                confirmation_bar_id=bars[confirmation_index].bar_id,
                confirmation_index=confirmation_index,
                base_distance_bars=confirmation_index - base_index,
                fold=fold,
                status=(OutcomeStatus.COMPLETED if outcome.completed else OutcomeStatus.RIGHT_CENSORED),
                outcome=outcome,
                zone_width_atr=width_atr,
            )
        )
    if len({item.candidate.candidate_id for item in cases}) != len(cases):
        raise ContractValidationError("V2.0 candidates must be unique")
    return tuple(cases)


def build_matched_controls(
    cases: tuple[CandidateCase, ...],
    bars: tuple[ClosedBar, ...],
    *,
    config: DisplacementOriginAdequacyConfig,
) -> tuple[MatchedControl, ...]:
    """Create pseudo-support and pseudo-resistance for every completed touch."""
    if type(cases) is not tuple or any(type(item) is not CandidateCase for item in cases):
        raise ContractValidationError("V2.0 controls require CandidateCase tuple")
    if type(bars) is not tuple or any(type(item) is not ClosedBar for item in bars):
        raise ContractValidationError("V2.0 controls require ClosedBar tuple")
    positions = {bar.bar_id: index for index, bar in enumerate(bars)}
    controls: list[MatchedControl] = []
    for case in cases:
        if case.status is not OutcomeStatus.COMPLETED:
            continue
        assert case.outcome is not None  # enforced by CandidateCase.
        touch_index = positions.get(case.outcome.touch_bar_id)
        if touch_index is None or case.fold is None:
            raise ContractValidationError("completed real outcome cannot be aligned for controls")
        touch = bars[touch_index]
        anchor = ControlAnchor(
            asset=config.asset,
            timeframe=config.timeframe,
            fold=case.fold,
            bar_id=touch.bar_id,
            anchor_at=touch.closed_at,
            model_index=touch_index,
            anchor_open=touch.open,
            anchor_high=touch.high,
            anchor_low=touch.low,
            anchor_close=touch.close,
            reference_atr_14=touch.atr_at_close,
            eligible=True,
            reason=ControlEligibilityReason.ELIGIBLE,
            config_hash=config.config_hash,
        )
        for side in config.control_side_order:
            outcome = compute_control_outcome(
                anchor,
                side,
                bars,
                outcome_start_offset_bars=config.outcome.first_touch_offset_bars,
                outcome_horizon_bars=config.outcome.horizon_bars,
                config_hash=config.config_hash,
            )
            if outcome.tenth_outcome_bar_closed_at >= _fold_end(case.fold, config):
                raise ContractValidationError("matched control crosses the real outcome fold boundary")
            controls.append(
                MatchedControl(
                    real_case_id=case.case_id,
                    candidate_id=case.candidate.candidate_id,
                    zone_width_atr=case.zone_width_atr,
                    outcome=outcome,
                )
            )
    if len(controls) != len(
        tuple(item for item in cases if item.status is OutcomeStatus.COMPLETED)
    ) * config.controls_per_real_touch:
        raise ContractValidationError("matched control count does not reconcile to completed real outcomes")
    return tuple(controls)


__all__ = ["build_matched_controls", "build_model_bars", "evaluate_candidates"]
