"""Causal deterministic non-zone control construction."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide
from libs.models.sr.research.replay.candidates import CandidateReplay

from .contracts import (
    CONTROL_SIDE_ORDER,
    ControlAccounting,
    ControlAnchor,
    ControlBuildResult,
    ControlEligibilityReason,
    ControlOutcome,
    FoldControlAccounting,
    BaselineAdequacyConfig,
)


def _fold_for(timestamp: datetime, config: BaselineAdequacyConfig) -> str | None:
    for fold in config.folds:
        if fold.start <= timestamp < fold.end:
            return fold.name
    return None


def _finite_positive(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and number > 0


def _previous_snapshot(replay: CandidateReplay, model_index: int):
    if model_index <= 0:
        return None
    expected_as_of = replay.model_bars[model_index - 1].closed_at
    matches = tuple(snapshot for snapshot in replay.snapshots if snapshot.as_of == expected_as_of)
    if len(matches) != 1:
        return None
    return matches[0]


def _intersects_visible_zone(bar: Any, snapshot: Any, config: BaselineAdequacyConfig) -> bool:
    for record in snapshot.zones:
        if record.runtime.status not in config.entry_visible_states:
            continue
        lower = record.definition.geometry.lower_bound
        upper = record.definition.geometry.upper_bound
        if bar.high >= lower and bar.low <= upper:
            return True
    return False


def _anchor_reason(
    replay: CandidateReplay,
    model_index: int,
    *,
    config: BaselineAdequacyConfig,
) -> tuple[str | None, ControlEligibilityReason, float | None]:
    bar = replay.model_bars[model_index]
    previous = _previous_snapshot(replay, model_index)
    if previous is None:
        return None, ControlEligibilityReason.NO_PREVIOUS_MODEL_SNAPSHOT, None
    fold = _fold_for(bar.closed_at, config)
    if fold is None or bar.closed_at < config.source_start:
        return fold, ControlEligibilityReason.OUTSIDE_FOLD_OR_WARMUP, None
    reference_atr = replay.reference_atr[model_index] if model_index < len(replay.reference_atr) else None
    if not _finite_positive(reference_atr):
        return fold, ControlEligibilityReason.ATR_UNAVAILABLE_OR_INVALID, None
    if _intersects_visible_zone(bar, previous, config):
        return fold, ControlEligibilityReason.ENTRY_VISIBLE_ZONE_INTERSECTION, float(reference_atr)
    start_index = model_index + config.outcome_start_offset_bars
    end_index = start_index + config.outcome_horizon_bars
    if end_index > len(replay.model_bars) or any(replay.model_bars[index].closed_at >= next(item.end for item in config.folds if item.name == fold) for index in range(start_index, min(end_index, len(replay.model_bars)))):
        return fold, ControlEligibilityReason.INCOMPLETE_SAME_FOLD_HORIZON, float(reference_atr)
    return fold, ControlEligibilityReason.ELIGIBLE, float(reference_atr)


def _make_anchor(
    replay: CandidateReplay,
    model_index: int,
    *,
    config: BaselineAdequacyConfig,
) -> ControlAnchor:
    bar = replay.model_bars[model_index]
    fold, reason, reference_atr = _anchor_reason(replay, model_index, config=config)
    return ControlAnchor(
        asset=config.asset,
        timeframe=config.timeframe,
        fold=fold,
        bar_id=bar.bar_id,
        anchor_at=bar.closed_at,
        model_index=model_index,
        anchor_open=bar.open,
        anchor_high=bar.high,
        anchor_low=bar.low,
        anchor_close=bar.close,
        reference_atr_14=reference_atr,
        eligible=reason is ControlEligibilityReason.ELIGIBLE,
        reason=reason,
        config_hash=config.config_hash,
    )


def _outcome(
    anchor: ControlAnchor,
    side: ZoneSide,
    replay: CandidateReplay,
    *,
    config: BaselineAdequacyConfig,
) -> ControlOutcome:
    if not anchor.eligible or anchor.fold is None or anchor.reference_atr_14 is None:
        raise ContractValidationError("control outcome requires eligible anchor")
    start_index = anchor.model_index + config.outcome_start_offset_bars
    end_index = start_index + config.outcome_horizon_bars
    horizon = replay.model_bars[start_index:end_index]
    if len(horizon) != config.outcome_horizon_bars:
        raise ContractValidationError("control outcome horizon is incomplete")
    if side is ZoneSide.SUPPORT:
        favorable_raw = max(max(bar.high for bar in horizon) - anchor.anchor_close, 0.0)
        adverse_raw = max(anchor.anchor_close - min(bar.low for bar in horizon), 0.0)
    elif side is ZoneSide.RESISTANCE:
        favorable_raw = max(anchor.anchor_close - min(bar.low for bar in horizon), 0.0)
        adverse_raw = max(max(bar.high for bar in horizon) - anchor.anchor_close, 0.0)
    else:  # pragma: no cover - ZoneSide contract makes this unreachable.
        raise ContractValidationError("unsupported control side")
    reference = anchor.reference_atr_14
    favorable = favorable_raw / reference
    adverse = adverse_raw / reference
    quality = favorable - adverse
    if not all(math.isfinite(value) for value in (favorable, adverse, quality)):
        raise ContractValidationError("control outcome metrics must be finite")
    return ControlOutcome(
        anchor_id=anchor.anchor_id,
        asset=anchor.asset,
        timeframe=anchor.timeframe,
        fold=anchor.fold,
        bar_id=anchor.bar_id,
        anchor_at=anchor.anchor_at,
        side=side,
        anchor_close=anchor.anchor_close,
        reference_atr_14=reference,
        outcome_start_offset_bars=config.outcome_start_offset_bars,
        outcome_horizon_bars=config.outcome_horizon_bars,
        tenth_outcome_bar_closed_at=horizon[-1].closed_at,
        favorable_reference_atr=favorable,
        adverse_reference_atr=adverse,
        quality_reference_atr=quality,
        config_hash=config.config_hash,
    )


def build_controls(
    replay: CandidateReplay,
    *,
    config: BaselineAdequacyConfig,
) -> ControlBuildResult:
    """Build every bar decision using only its immediately prior snapshot."""
    if type(replay) is not CandidateReplay:
        raise ContractValidationError("controls require exactly CandidateReplay")
    if replay.period != config.atr_period or replay.reference_period != config.atr_period or replay.common_start_index != config.common_start_period:
        raise ContractValidationError("control replay is not frozen ATR(14)/common-start protocol")
    anchors = tuple(_make_anchor(replay, index, config=config) for index in range(len(replay.model_bars)))
    outcomes: list[ControlOutcome] = []
    for anchor in anchors:
        if anchor.eligible:
            outcomes.extend(_outcome(anchor, side, replay, config=config) for side in CONTROL_SIDE_ORDER)

    reasons = tuple(reason for reason in config.rejection_reason_precedence if reason is not ControlEligibilityReason.ELIGIBLE)
    counter = Counter(anchor.reason for anchor in anchors if anchor.reason is not ControlEligibilityReason.ELIGIBLE)
    rejected = tuple((reason, counter.get(reason, 0)) for reason in reasons)
    fold_rows: list[FoldControlAccounting] = []
    for fold in config.folds:
        fold_anchors = tuple(anchor for anchor in anchors if anchor.fold == fold.name)
        fold_counter = Counter(anchor.reason for anchor in fold_anchors if anchor.reason is not ControlEligibilityReason.ELIGIBLE)
        fold_rows.append(FoldControlAccounting(fold=fold.name, considered=len(fold_anchors), eligible=sum(item.eligible for item in fold_anchors), rejected=tuple((reason, fold_counter.get(reason, 0)) for reason in reasons)))
    outside = tuple(anchor for anchor in anchors if anchor.fold is None)
    if outside:
        outside_counter = Counter(anchor.reason for anchor in outside if anchor.reason is not ControlEligibilityReason.ELIGIBLE)
        fold_rows.append(FoldControlAccounting(fold=None, considered=len(outside), eligible=0, rejected=tuple((reason, outside_counter.get(reason, 0)) for reason in reasons)))
    accounting = ControlAccounting(total_considered=len(anchors), total_eligible=sum(anchor.eligible for anchor in anchors), rejected=rejected, folds=tuple(fold_rows))
    return ControlBuildResult(anchors=anchors, outcomes=tuple(outcomes), accounting=accounting)


__all__ = ["build_controls"]
