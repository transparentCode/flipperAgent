"""Build the deterministic V1.10 ledger from validated frozen replay objects."""

from __future__ import annotations

from statistics import median
from typing import Any, Iterable

from libs.models.sr.domain import ContractValidationError, SREventType
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.evidence.baseline_adequacy.contracts import (
    BaselineAdequacyStudy,
    RealOutcomeRecord,
)
from libs.models.sr.research.source.contracts import SourceBar
from libs.models.sr.research.cohort.contracts import AssetEvaluation

from .config import (
    APPROVED_ASSET,
    APPROVED_ATR_PERIOD,
    APPROVED_FOLD_NAMES,
    APPROVED_SOURCE_END,
    APPROVED_SOURCE_ROWS,
    APPROVED_SOURCE_START,
    APPROVED_TIMEFRAME,
    APPROVED_VENUE,
    ContextAuditConfig,
)
from .contracts import (
    AuditResult,
    CaseLedger,
    CloseLocation,
    ComparisonView,
    HorizonLifecycleClass,
    LifecycleEventView,
    SIDE_VALUES,
    OutcomeView,
    TouchBarView,
    ZoneCaseView,
)


def _median_or_none(values: Iterable[float]) -> float | None:
    values = tuple(values)
    return None if not values else float(median(values))


def _outcome_view(outcome: FirstTouchOutcome) -> OutcomeView:
    return OutcomeView(
        completed=outcome.completed,
        right_censored=outcome.right_censored,
        invalidated=outcome.invalidated,
        tenth_outcome_bar_closed_at=outcome.tenth_outcome_bar_closed_at,
        anchor_close=outcome.anchor_close,
        reference_atr_14=outcome.reference_atr_14,
        favorable_reference_atr=outcome.favorable_reference_atr,
        adverse_reference_atr=outcome.adverse_reference_atr,
        quality_reference_atr=outcome.quality_reference_atr,
    )


def _source_bar_payload(bar: SourceBar) -> dict[str, Any]:
    return {
        "bar_id": bar.bar_id,
        "open_time": bar.open_time,
        "closed_at": bar.closed_at,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _close_location(close: float, lower: float, upper: float) -> CloseLocation:
    if close < lower:
        return CloseLocation.BELOW_BAND
    if close > upper:
        return CloseLocation.ABOVE_BAND
    return CloseLocation.INSIDE_BAND


def _lifecycle_class(events: tuple[LifecycleEventView, ...]) -> HorizonLifecycleClass:
    types = {event.event_type for event in events}
    if SREventType.BREAK_CONFIRMED in types:
        return HorizonLifecycleClass.BREAK_CONFIRMED
    if SREventType.FALSE_BREAKOUT in types:
        return HorizonLifecycleClass.FALSE_BREAKOUT_NO_CONFIRMED_BREAK
    if SREventType.EXPIRED in types:
        return HorizonLifecycleClass.EXPIRED_NO_BREAK_OR_FALSE_BREAKOUT
    return HorizonLifecycleClass.NO_TERMINAL_OR_FAKEOUT_EVENT


def _event_view(event) -> LifecycleEventView:
    return LifecycleEventView(
        event_id=event.event_id,
        snapshot_id=event.snapshot_id,
        snapshot_as_of=event.snapshot_as_of,
        zone_id=event.zone_id,
        event_type=event.event_type,
        timestamp=event.timestamp,
        price=event.price,
        bar_id=event.bar_id,
    )


def _find_one(values: Iterable[Any], *, description: str) -> Any:
    values = tuple(values)
    if len(values) != 1:
        raise ContractValidationError(f"expected exactly one {description}, found {len(values)}")
    return values[0]


def _build_case(
    record: RealOutcomeRecord,
    pooled: FirstTouchOutcome,
    comparison,
    *,
    baseline: AssetEvaluation,
    source_bars: tuple[SourceBar, ...],
    config: ContextAuditConfig,
) -> CaseLedger:
    outcome = record.outcome
    replay = baseline.replay
    trace = replay.trace
    if outcome.zone_id != pooled.zone_id or outcome.touch_bar_id != pooled.touch_bar_id or outcome.first_touch_at != pooled.first_touch_at or outcome.side is not pooled.side:
        raise ContractValidationError("pooled and fold-local outcome identities do not reconcile")
    model_bar = _find_one((bar for bar in replay.model_bars if bar.bar_id == outcome.touch_bar_id), description="touch model bar")
    source_bar = _find_one((bar for bar in source_bars if bar.bar_id == outcome.touch_bar_id), description="touch source bar")
    if model_bar.closed_at != outcome.first_touch_at or source_bar.closed_at != model_bar.closed_at:
        raise ContractValidationError("touch outcome does not map to the causal model/source bar")
    model_position = {bar.bar_id: index for index, bar in enumerate(replay.model_bars)}
    reference_atr = replay.reference_atr[model_position[model_bar.bar_id]]
    if reference_atr != outcome.reference_atr_14 or reference_atr != pooled.reference_atr_14:
        raise ContractValidationError("touch reference ATR does not reconcile to replay ownership")

    snapshot_position = {reference.snapshot_id: index for index, reference in enumerate(trace.snapshots)}
    touch_reference = _find_one((reference for reference in trace.snapshots if reference.as_of == outcome.first_touch_at), description="touch snapshot")
    touch_position = snapshot_position[touch_reference.snapshot_id]
    if touch_position == 0:
        raise ContractValidationError("touch has no immediately preceding aligned snapshot")
    previous_reference = trace.snapshots[touch_position - 1]
    observations = tuple(item for item in trace.zone_observations if item.zone_id == outcome.zone_id)
    if not observations:
        raise ContractValidationError("outcome zone has no replay observations")
    touch_observation = _find_one((item for item in observations if item.snapshot_id == touch_reference.snapshot_id), description="touch zone observation")
    previous_observation = _find_one((item for item in observations if item.snapshot_id == previous_reference.snapshot_id), description="preceding zone observation")
    horizon = pooled.tenth_outcome_bar_closed_at
    if horizon is None:
        raise ContractValidationError("approved pooled outcome lacks tenth horizon")
    horizon_reference = _find_one((reference for reference in trace.snapshots if reference.as_of == horizon), description="horizon snapshot")
    horizon_observation = _find_one((item for item in observations if item.snapshot_id == horizon_reference.snapshot_id), description="horizon zone observation")
    zone_first = observations[0]
    visible_until_values = tuple(item.visible_until for item in observations if item.visible_until is not None)
    if visible_until_values and any(value != visible_until_values[0] for value in visible_until_values):
        raise ContractValidationError("zone visible interval changes across observations")
    creation_events = tuple(item for item in trace.events if item.zone_id == outcome.zone_id and item.event_type is SREventType.CREATED)
    creation_event = _find_one(creation_events, description="zone CREATED event")
    if (
        creation_event.timestamp != zone_first.available_at
        or creation_event.snapshot_id != zone_first.snapshot_id
        or creation_event.snapshot_as_of != zone_first.as_of
    ):
        raise ContractValidationError("CREATED event does not match zone availability")
    window_events = tuple(
        _event_view(item)
        for item in trace.events
        if item.zone_id == outcome.zone_id
        and item.event_type is not SREventType.CREATED
        and outcome.first_touch_at <= item.timestamp <= horizon
    )
    if any(item.timestamp < outcome.first_touch_at or item.timestamp > horizon for item in window_events):
        raise ContractValidationError("lifecycle event escaped the approved horizon window")
    source_payload = _source_bar_payload(source_bar)
    close_location = _close_location(source_bar.close, touch_observation.lower_bound, touch_observation.upper_bound)
    touch_bar = TouchBarView(
        **source_payload,
        reference_atr_14=reference_atr,
        close_location=close_location,
    )
    zone = ZoneCaseView(
        zone_id=zone_first.zone_id,
        side=zone_first.side,
        source=zone_first.source,
        render_kind=zone_first.render_kind,
        lower_bound=zone_first.lower_bound,
        center=zone_first.center,
        upper_bound=zone_first.upper_bound,
        atr_at_creation=zone_first.atr_at_creation,
        created_at=zone_first.created_at,
        available_at=zone_first.available_at,
        visible_from=zone_first.visible_from,
        visible_until=None if not visible_until_values else visible_until_values[0],
        age_bars_at_touch=touch_observation.age_bars,
        touch_count_at_touch=touch_observation.touch_count,
        fakeout_count_at_touch=touch_observation.fakeout_count,
        pending_breach_count_at_touch=touch_observation.pending_breach_count,
    )
    comparison_view = None if comparison is None else ComparisonView(
        real_outcome_id=comparison.real_outcome_id,
        fold=comparison.fold,
        side=comparison.side,
        real_quality=comparison.real_quality,
        null_median=comparison.null_median,
        excess_quality=comparison.excess_quality,
    )
    return CaseLedger(
        record_id=record.record_id,
        comparison_real_outcome_id=None if comparison_view is None else comparison_view.real_outcome_id,
        zone_id=outcome.zone_id,
        side=outcome.side,
        fold=record.fold,
        touch_bar_id=outcome.touch_bar_id,
        first_touch_at=outcome.first_touch_at,
        zone=zone,
        touch_bar=touch_bar,
        entering_status=previous_observation.status,
        after_touch_status=touch_observation.status,
        pooled_outcome=_outcome_view(pooled),
        fold_local_outcome=_outcome_view(outcome),
        comparison=comparison_view,
        creation_event=_event_view(creation_event),
        lifecycle_events=window_events,
        horizon_lifecycle_class=_lifecycle_class(window_events),
        status_after_horizon=horizon_observation.status,
    )


def _parity(study: BaselineAdequacyStudy) -> dict[str, Any]:
    comparisons = tuple(study.comparisons)
    return {
        "approved_pooled": study.aggregate.approved_pooled.to_payload(),
        "fold_local": study.aggregate.fold_local.to_payload(),
        "comparable_mapped": study.aggregate.comparable_mapped.to_payload(),
        "aggregate": study.aggregate.to_payload(),
        "fold_metrics": [item.to_payload() for item in study.fold_metrics],
        "fold_side_nulls": [item.to_payload() for item in study.fold_side_nulls],
        "comparisons": [item.to_payload() for item in comparisons],
        "control_accounting": study.control_accounting.to_payload(),
        "gates": [item.to_payload() for item in study.decision.gates],
        "disposition": study.decision.to_payload(),
    }


def _case_group_value(case: CaseLedger, key_name: str) -> str:
    if key_name == "fold":
        return case.fold
    if key_name == "horizon_lifecycle_class":
        return case.horizon_lifecycle_class.value
    if key_name == "close_location":
        return case.touch_bar.close_location.value
    raise ContractValidationError(f"unsupported diagnostic grouping: {key_name}")


def _group_rows(cases: tuple[CaseLedger, ...], *, key_name: str, key_values: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for key in key_values:
        for side in SIDE_VALUES:
            group = tuple(case for case in cases if _case_group_value(case, key_name) == key and case.side is side)
            mapped = tuple(case for case in group if case.comparison is not None)
            pooled_completed = tuple(case for case in group if case.pooled_outcome.completed)
            local_completed = sum(case.fold_local_outcome.completed for case in group)
            row = {
                key_name: key,
                "side": side.value,
                "approved_pooled_case_count": len(group),
                "fold_local_completed_count": local_completed,
                "fold_local_censored_count": sum(case.fold_local_outcome.right_censored for case in group),
                "comparable_mapped_count": len(mapped),
                "median_favorable_reference_atr": _median_or_none(item.pooled_outcome.favorable_reference_atr for item in pooled_completed if item.pooled_outcome.favorable_reference_atr is not None),
                "median_adverse_reference_atr": _median_or_none(item.pooled_outcome.adverse_reference_atr for item in pooled_completed if item.pooled_outcome.adverse_reference_atr is not None),
                "median_quality_reference_atr": _median_or_none(item.pooled_outcome.quality_reference_atr for item in pooled_completed if item.pooled_outcome.quality_reference_atr is not None),
                "median_persisted_excess": _median_or_none(item.comparison.excess_quality for item in mapped if item.comparison is not None),
            }
            rows.append(row)
    return tuple(rows)


def _zone_age_rows(cases: tuple[CaseLedger, ...]) -> tuple[dict[str, Any], ...]:
    rows = []
    for side in SIDE_VALUES:
        ages = [case.zone.age_bars_at_touch for case in cases if case.side is side]
        if not ages:
            rows.append({"side": side.value, "count": 0, "minimum_age_bars": None, "median_age_bars": None, "maximum_age_bars": None})
        else:
            rows.append({"side": side.value, "count": len(ages), "minimum_age_bars": min(ages), "median_age_bars": float(median(ages)), "maximum_age_bars": max(ages)})
    return tuple(rows)


def build_audit(
    config: ContextAuditConfig,
    *,
    study: BaselineAdequacyStudy,
    baseline: AssetEvaluation,
    source_bars: tuple[SourceBar, ...],
    implementation_commit: str,
) -> AuditResult:
    """Map the validated V1.9 study to its causal replay and build all tables."""
    if type(config) is not ContextAuditConfig or type(study) is not BaselineAdequacyStudy or type(baseline) is not AssetEvaluation:
        raise ContractValidationError("context audit requires typed frozen inputs")
    if baseline.asset != APPROVED_ASSET or baseline.replay.period != APPROVED_ATR_PERIOD or baseline.replay.trace.state_key.venue != APPROVED_VENUE or baseline.replay.trace.state_key.symbol != APPROVED_ASSET or baseline.replay.trace.state_key.timeframe != APPROVED_TIMEFRAME:
        raise ContractValidationError("baseline replay scope is outside the approved TAOUSDT/1d audit")
    if type(source_bars) is not tuple or len(source_bars) != APPROVED_SOURCE_ROWS:
        raise ContractValidationError("audit source must contain exactly 629 frozen bars")
    if source_bars[0].open_time != APPROVED_SOURCE_START or source_bars[-1].closed_at != APPROVED_SOURCE_END:
        raise ContractValidationError("audit source endpoints do not match the frozen grid")
    if study.config_hash != config.v19_config_hash:
        raise ContractValidationError("V1.9 study config identity mismatch")
    if study.study_id != config.v19_study_id or study.decision.disposition.value != config.v19_disposition:
        raise ContractValidationError("V1.9 study identity or disposition mismatch")
    records = tuple(study.real_outcomes)
    if len(records) != 36:
        raise ContractValidationError("V1.9 fold-local outcome universe is not exactly 36 records")
    pooled_asset = _find_one((asset for asset in (baseline,) if asset.asset == APPROVED_ASSET), description="baseline asset")
    pooled_by_key = {(item.zone_id, item.touch_bar_id, item.first_touch_at, item.side): item for item in pooled_asset.metrics.pooled.outcomes}
    if len(pooled_by_key) != 36:
        raise ContractValidationError("approved pooled outcome universe is not exactly 36 unique records")
    comparison_by_id = {item.real_outcome_id: item for item in study.comparisons}
    if len(comparison_by_id) != 31:
        raise ContractValidationError("V1.9 comparison universe is not exactly 31 records")
    cases = []
    for record in records:
        key = (record.outcome.zone_id, record.outcome.touch_bar_id, record.outcome.first_touch_at, record.outcome.side)
        pooled = pooled_by_key.get(key)
        if pooled is None:
            raise ContractValidationError("fold-local outcome cannot map to approved pooled outcome")
        cases.append(_build_case(record, pooled, comparison_by_id.get(record.record_id), baseline=baseline, source_bars=source_bars, config=config))
    cases = tuple(sorted(cases, key=lambda item: (item.first_touch_at, item.zone_id)))
    if len({case.case_id for case in cases}) != len(cases):
        raise ContractValidationError("case identity collision")
    if sum(case.comparison is not None for case in cases) != 31:
        raise ContractValidationError("comparison mapping count does not reconcile")
    fold_rows = _group_rows(cases, key_name="fold", key_values=APPROVED_FOLD_NAMES)
    lifecycle_values = tuple(item.value for item in HorizonLifecycleClass)
    close_values = tuple(item.value for item in CloseLocation)
    lifecycle_rows = _group_rows(cases, key_name="horizon_lifecycle_class", key_values=lifecycle_values)
    close_rows = _group_rows(cases, key_name="close_location", key_values=close_values)
    parity = _parity(study)
    controls = {
        "anchor_count": len(study.control_anchors),
        "outcome_count": len(study.control_outcomes),
        "accounting": study.control_accounting.to_payload(),
    }
    return AuditResult(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        v19_bundle_id=config.v19_bundle_id,
        v19_study_id=config.v19_study_id,
        v19_disposition=config.v19_disposition,
        source_bundle_id=config.v17_source_bundle_id,
        source_id=baseline.source_id,
        trace_id=baseline.trace_id,
        audit_status=config.audit_status,
        cases=cases,
        v19_parity=parity,
        fold_side_decomposition=fold_rows,
        lifecycle_decomposition=lifecycle_rows,
        touch_close_decomposition=close_rows,
        zone_age_summary=_zone_age_rows(cases),
        controls=controls,
    )


def build_chart_payload(config: ContextAuditConfig, audit: AuditResult, source_bars: tuple[SourceBar, ...]) -> dict[str, Any]:
    from libs.models.sr.research.viewer.casebook_payload import build_casebook_chart_payload

    return build_casebook_chart_payload(
        trial_name=config.trial_name,
        bundle_id=None,
        viewer=config.viewer.to_payload(),
        source_bars=source_bars,
        audit=audit.to_payload(),
        sr_config_hash=config.production_sr_config_hash,
        input_hash=config.frozen_input_hash,
    )


__all__ = ["build_audit", "build_chart_payload"]
