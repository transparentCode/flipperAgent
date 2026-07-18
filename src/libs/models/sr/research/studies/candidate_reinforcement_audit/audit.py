"""Causal V1.12 candidate ledger reconstruction around the frozen SR engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from libs.models.sr.association import match_candidate
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.detection import detect_confirmed_pivots
from libs.models.sr.domain import create_initial_state
from libs.models.sr.domain import (
    ClosedBar,
    ContractValidationError,
    SREvent,
    SREventType,
    SRState,
    SRSnapshot,
    ZoneDefinition,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneStatus,
)
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.lifecycle.engine import SREngine
from libs.models.sr.evaluation import ObservedEvent

from .config import CandidateAuditConfig, FOLD_NAMES
from .contracts import (
    AuditAccounting,
    AuditDecision,
    AuditDisposition,
    CandidateDecisionRecord,
    CandidateReinforcementAudit,
    DecisionCategory,
    FoldAccounting,
    GateResult,
    ReinforcementZoneCount,
    ReplayParity,
    StatusCount,
    ZoneSeedLineage,
    _first_confirmation_by_zone,
)


@dataclass(frozen=True)
class _ReplayPass:
    initial_state: SRState
    final_state: SRState
    states: tuple[SRState, ...]
    snapshots: tuple[SRSnapshot, ...]
    events: tuple[tuple[SREvent, ...], ...]
    candidates: tuple[CandidateDecisionRecord, ...]
    lineage: tuple[ZoneSeedLineage, ...]


def _fold_for(timestamp: Any, config: CandidateAuditConfig) -> str | None:
    for fold in config.replay.folds:
        if fold.start <= timestamp < fold.end:
            return fold.name
    return None


def _new_zone(candidate: Any, resolved_config: ResolvedSRConfig) -> ZoneRecord:
    definition = ZoneDefinition(
        state_key=candidate.state_key,
        side=candidate.side,
        geometry=candidate.geometry,
        source=candidate.source,
        created_at=candidate.formed_at,
        available_at=candidate.available_at,
        atr_at_creation=candidate.atr_at_creation,
        config_hash=resolved_config.resolved_config_hash,
    )
    return ZoneRecord(
        definition=definition,
        runtime=ZoneRuntimeState(
            zone_id=definition.zone_id,
            status=ZoneStatus.ACTIVE,
            touch_count=0,
            fakeout_count=0,
            pending_breach_count=0,
            age_bars=0,
            last_interaction_at=None,
            updated_at=definition.available_at,
        ),
    )


def _bar_id_for_timestamp(bars: tuple[ClosedBar, ...], timestamp: Any, *, field_name: str) -> str:
    matches = tuple(bar.bar_id for bar in bars if bar.closed_at == timestamp)
    if len(matches) != 1:
        raise ContractValidationError(f"{field_name} does not align to exactly one replay bar")
    return matches[0]


def _run_pass(
    bars: tuple[ClosedBar, ...],
    resolved_config: ResolvedSRConfig,
    config: CandidateAuditConfig,
    *,
    initial_state: SRState,
    lineage: tuple[ZoneSeedLineage, ...] = (),
) -> _ReplayPass:
    if not bars:
        raise ContractValidationError("candidate audit replay requires non-empty bars")
    engine = SREngine()
    state = initial_state
    states: list[SRState] = []
    snapshots: list[SRSnapshot] = []
    events_by_bar: list[tuple[SREvent, ...]] = []
    records: list[CandidateDecisionRecord] = []
    lineage_by_zone = {item.zone_id: item for item in lineage}
    seed_by_candidate = {item.seed_candidate_id: item for item in lineage}
    bar_ids = {bar.bar_id for bar in bars}

    for bar in bars:
        detection_bars = state.recent_bars + (bar,)
        detected = tuple(
            sorted(
                detect_confirmed_pivots(detection_bars, resolved_config.detection),
                key=lambda item: (item.formed_at, item.available_at, item.candidate_id),
            )
        )
        start_ids = {
            record.definition.zone_id
            for record in state.zones
            if record.runtime.status not in {ZoneStatus.BROKEN, ZoneStatus.EXPIRED}
        }
        previous_by_zone = {record.definition.zone_id: record for record in state.zones}
        next_state, snapshot, emitted = engine.step(state, bar, resolved_config)
        association_pool = tuple(
            record
            for record in snapshot.zones
            if record.definition.zone_id in start_ids
        )
        created_records: list[ZoneRecord] = []
        current_created_ids: set[str] = set()
        created_event_ids = {
            event.zone_id
            for event in snapshot.events
            if event.event_type is SREventType.CREATED and event.bar_id == bar.bar_id
        }
        for candidate in detected:
            if candidate.available_at > bar.closed_at:
                raise ContractValidationError("detector emitted candidate before availability bar close")
            match_pool = association_pool + tuple(created_records)
            target = match_candidate(candidate, match_pool, resolved_config.association)
            active_before_capacity = sum(
                record.runtime.status not in {ZoneStatus.BROKEN, ZoneStatus.EXPIRED}
                for record in association_pool
            ) + len(created_records)
            fold = _fold_for(candidate.available_at, config)
            formed_bar_id = _bar_id_for_timestamp(detection_bars, candidate.formed_at, field_name="candidate.formed_at")
            available_bar_id = _bar_id_for_timestamp(bars, candidate.available_at, field_name="candidate.available_at")
            threshold = resolved_config.association.merge_distance_atr * candidate.atr_at_creation

            if target is not None:
                target_zone_id = target.definition.zone_id
                same_batch = target_zone_id in current_created_ids
                category = DecisionCategory.MATCHED_SAME_BATCH_ZONE_SUPPRESSED if same_batch else DecisionCategory.MATCHED_START_ZONE_SUPPRESSED
                seed = lineage_by_zone.get(target_zone_id)
                if seed is None:
                    raise ContractValidationError("matched target has no proven seed lineage")
                previous = previous_by_zone.get(target_zone_id)
                distance = abs(candidate.geometry.center - target.definition.geometry.center)
                eligible = (
                    category is DecisionCategory.MATCHED_START_ZONE_SUPPRESSED
                    and candidate.candidate_id != seed.seed_candidate_id
                    and candidate.formed_at > seed.formed_at
                    and candidate.available_at > seed.available_at
                    and target.runtime.status not in {ZoneStatus.BROKEN, ZoneStatus.EXPIRED}
                    and candidate.state_key == target.definition.state_key
                    and candidate.side is target.definition.side
                    and fold is not None
                )
                record = CandidateDecisionRecord(
                    candidate_id=candidate.candidate_id,
                    state_key=candidate.state_key,
                    side=candidate.side,
                    source=candidate.source,
                    formed_at=candidate.formed_at,
                    available_at=candidate.available_at,
                    formed_bar_id=formed_bar_id,
                    available_bar_id=available_bar_id,
                    replay_bar_id=bar.bar_id,
                    replay_closed_at=bar.closed_at,
                    center=candidate.geometry.center,
                    half_width=candidate.geometry.half_width,
                    lower_bound=candidate.geometry.lower_bound,
                    upper_bound=candidate.geometry.upper_bound,
                    atr_at_creation=candidate.atr_at_creation,
                    decision=category,
                    target_zone_id=target_zone_id,
                    created_zone_id=None,
                    target_seed_candidate_id=seed.seed_candidate_id,
                    target_pre_advance_status=None if same_batch else (previous.runtime.status if previous is not None else None),
                    target_post_advance_status=target.runtime.status,
                    center_distance=distance,
                    center_distance_atr=distance / candidate.atr_at_creation,
                    merge_threshold_price=threshold,
                    merge_distance_atr=resolved_config.association.merge_distance_atr,
                    active_zone_count_before_capacity=active_before_capacity,
                    fold=fold,
                    eligible_reinforcement=eligible,
                )
                records.append(record)
                continue

            if active_before_capacity >= resolved_config.runtime.max_active_zones:
                records.append(
                    CandidateDecisionRecord(
                        candidate_id=candidate.candidate_id,
                        state_key=candidate.state_key,
                        side=candidate.side,
                        source=candidate.source,
                        formed_at=candidate.formed_at,
                        available_at=candidate.available_at,
                        formed_bar_id=formed_bar_id,
                        available_bar_id=available_bar_id,
                        replay_bar_id=bar.bar_id,
                        replay_closed_at=bar.closed_at,
                        center=candidate.geometry.center,
                        half_width=candidate.geometry.half_width,
                        lower_bound=candidate.geometry.lower_bound,
                        upper_bound=candidate.geometry.upper_bound,
                        atr_at_creation=candidate.atr_at_creation,
                        decision=DecisionCategory.CAPACITY_SUPPRESSED,
                        target_zone_id=None,
                        created_zone_id=None,
                        target_seed_candidate_id=None,
                        target_pre_advance_status=None,
                        target_post_advance_status=None,
                        center_distance=None,
                        center_distance_atr=None,
                        merge_threshold_price=threshold,
                        merge_distance_atr=resolved_config.association.merge_distance_atr,
                        active_zone_count_before_capacity=active_before_capacity,
                        fold=fold,
                        eligible_reinforcement=False,
                    )
                )
                continue

            expected = _new_zone(candidate, resolved_config)
            actual = next((item for item in snapshot.zones if item.definition.zone_id == expected.definition.zone_id), None)
            if actual is None or actual != expected:
                raise ContractValidationError("created zone does not reconcile with canonical engine output")
            created_records.append(actual)
            current_created_ids.add(actual.definition.zone_id)
            lineage_record = ZoneSeedLineage(
                zone_id=actual.definition.zone_id,
                seed_candidate_id=candidate.candidate_id,
                state_key=candidate.state_key,
                side=candidate.side,
                formed_at=candidate.formed_at,
                available_at=candidate.available_at,
            )
            if actual.definition.zone_id in lineage_by_zone or candidate.candidate_id in seed_by_candidate:
                raise ContractValidationError("zone seed lineage is not one-to-one")
            lineage_by_zone[actual.definition.zone_id] = lineage_record
            seed_by_candidate[candidate.candidate_id] = lineage_record
            records.append(
                CandidateDecisionRecord(
                    candidate_id=candidate.candidate_id,
                    state_key=candidate.state_key,
                    side=candidate.side,
                    source=candidate.source,
                    formed_at=candidate.formed_at,
                    available_at=candidate.available_at,
                    formed_bar_id=formed_bar_id,
                    available_bar_id=available_bar_id,
                    replay_bar_id=bar.bar_id,
                    replay_closed_at=bar.closed_at,
                    center=candidate.geometry.center,
                    half_width=candidate.geometry.half_width,
                    lower_bound=candidate.geometry.lower_bound,
                    upper_bound=candidate.geometry.upper_bound,
                    atr_at_creation=candidate.atr_at_creation,
                    decision=DecisionCategory.CREATED_ZONE,
                    target_zone_id=None,
                    created_zone_id=actual.definition.zone_id,
                    target_seed_candidate_id=None,
                    target_pre_advance_status=None,
                    target_post_advance_status=None,
                    center_distance=None,
                    center_distance_atr=None,
                    merge_threshold_price=threshold,
                    merge_distance_atr=resolved_config.association.merge_distance_atr,
                    active_zone_count_before_capacity=active_before_capacity,
                    fold=fold,
                    eligible_reinforcement=False,
                )
            )

        actual_created_ids = {
            event.zone_id
            for event in snapshot.events
            if event.event_type is SREventType.CREATED and event.bar_id == bar.bar_id
        }
        if actual_created_ids != current_created_ids or actual_created_ids != created_event_ids:
            raise ContractValidationError("created-zone event/ledger reconciliation failed")
        if any(record.replay_bar_id not in bar_ids for record in records[-len(detected):] if detected):
            raise ContractValidationError("candidate replay bar identity is unknown")
        states.append(next_state)
        snapshots.append(snapshot)
        events_by_bar.append(tuple(emitted))
        state = next_state

    return _ReplayPass(
        initial_state=initial_state,
        final_state=state,
        states=tuple(states),
        snapshots=tuple(snapshots),
        events=tuple(events_by_bar),
        candidates=tuple(records),
        lineage=tuple(sorted(lineage_by_zone.values(), key=lambda item: item.zone_id)),
    )


def _flatten_events(events: tuple[tuple[SREvent, ...], ...]) -> tuple[SREvent, ...]:
    return tuple(event for per_bar in events for event in per_bar)


def _observed_events(
    snapshots: tuple[SRSnapshot, ...],
    events: tuple[tuple[SREvent, ...], ...],
) -> tuple[ObservedEvent, ...]:
    if len(snapshots) != len(events):
        raise ContractValidationError("candidate audit event/snapshot lengths do not reconcile")
    return tuple(
        ObservedEvent(
            snapshot_id=snapshot.snapshot_id,
            snapshot_as_of=snapshot.as_of,
            event_id=event.event_id,
            zone_id=event.zone_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            price=event.price,
            bar_id=event.bar_id,
        )
        for snapshot, per_bar in zip(snapshots, events)
        for event in per_bar
    )


def _digest(values: Any) -> str:
    return deterministic_hash(values)


def _parity(
    full: _ReplayPass,
    checkpoint: _ReplayPass,
    bars: tuple[ClosedBar, ...],
    canonical_replay: Any,
) -> ReplayParity:
    if len(full.states) != len(checkpoint.states) or full.states != checkpoint.states or full.snapshots != checkpoint.snapshots or full.events != checkpoint.events or full.candidates != checkpoint.candidates or full.lineage != checkpoint.lineage:
        raise ContractValidationError("uninterrupted/checkpoint replay parity failed")
    canonical_events = _flatten_events(full.events)
    observed_events = _observed_events(full.snapshots, full.events)
    approved = canonical_replay
    canonical_checks = {
        "model_bars": approved.model_bars == bars,
        "initial_state": approved.initial_state == full.initial_state,
        "snapshots": approved.snapshots == full.snapshots,
        "final_state": approved.final_state == full.final_state,
        "events": tuple(approved.trace.events) == observed_events,
    }
    if not all(canonical_checks.values()):
        failed = ",".join(name for name, passed in canonical_checks.items() if not passed)
        raise ContractValidationError(f"candidate audit replay is not canonical V1 replay: {failed}")
    split = len(bars) // 2
    return ReplayParity(
        passed=True,
        bar_count=len(bars),
        checkpoint_split_index=split,
        state_digest=_digest([state for state in full.states]),
        snapshot_digest=_digest([snapshot for snapshot in full.snapshots]),
        event_digest=_digest([event for event in canonical_events]),
        candidate_digest=_digest([item.to_payload() for item in full.candidates]),
        checkpoint_state_digest=_digest([state for state in checkpoint.states]),
        checkpoint_snapshot_digest=_digest([snapshot for snapshot in checkpoint.snapshots]),
        checkpoint_event_digest=_digest([event for event in _flatten_events(checkpoint.events)]),
        checks=(
            "state_identity_payload_each_bar",
            "snapshot_identity_payload_each_bar",
            "event_order_and_payload_each_bar",
            "candidate_order_each_bar",
            "created_zone_ids",
            "terminal_statuses",
            "final_state",
            "checkpoint_resume",
            "canonical_v1_replay",
        ),
    )

def _accounting(
    candidates: tuple[CandidateDecisionRecord, ...],
    source_case_count: int,
    config: CandidateAuditConfig,
) -> AuditAccounting:
    eligible = tuple(item for item in candidates if item.eligible_reinforcement)
    by_zone: dict[str, int] = {}
    for item in eligible:
        if item.target_zone_id is None:
            raise ContractValidationError("eligible reinforcement lacks target zone")
        by_zone[item.target_zone_id] = by_zone.get(item.target_zone_id, 0) + 1
    zone_counts = tuple(ReinforcementZoneCount(zone_id, count) for zone_id, count in sorted(by_zone.items()))
    first_confirmations = _first_confirmation_by_zone(candidates)
    folds = tuple(
        FoldAccounting(
            fold=fold,
            candidate_count=sum(item.fold == fold for item in candidates),
            created_zone_count=sum(item.fold == fold and item.decision is DecisionCategory.CREATED_ZONE for item in candidates),
            eligible_match_count=sum(item.fold == fold for item in eligible),
            unique_reinforced_zone_count=sum(item.fold == fold for item in first_confirmations.values()),
        )
        for fold in FOLD_NAMES
    )
    status_counts = tuple(StatusCount(status, sum(item.target_post_advance_status is status for item in candidates if item.target_post_advance_status is not None)) for status in ZoneStatus)
    counts = [item.eligible_match_count for item in zone_counts]
    return AuditAccounting(
        source_case_count=source_case_count,
        total_candidates=len(candidates),
        created_zone_count=sum(item.decision is DecisionCategory.CREATED_ZONE for item in candidates),
        matched_start_zone_suppressed=sum(item.decision is DecisionCategory.MATCHED_START_ZONE_SUPPRESSED for item in candidates),
        matched_same_batch_zone_suppressed=sum(item.decision is DecisionCategory.MATCHED_SAME_BATCH_ZONE_SUPPRESSED for item in candidates),
        capacity_suppressed=sum(item.decision is DecisionCategory.CAPACITY_SUPPRESSED for item in candidates),
        eligible_reinforcement_count=len(eligible),
        unique_reinforced_zone_count=len(zone_counts),
        one_reinforcement_zone_count=sum(count == 1 for count in counts),
        two_reinforcement_zone_count=sum(count == 2 for count in counts),
        three_or_more_reinforcement_zone_count=sum(count >= 3 for count in counts),
        support_candidate_count=sum(item.side.value == "SUPPORT" for item in candidates),
        resistance_candidate_count=sum(item.side.value == "RESISTANCE" for item in candidates),
        out_of_fold_candidate_count=sum(item.fold is None for item in candidates),
        unmatched_reconciliation_count=0,
        target_post_advance_status_counts=status_counts,
        reinforcement_zone_counts=zone_counts,
        folds=folds,
    )


def _decision(accounting: AuditAccounting, config: CandidateAuditConfig) -> AuditDecision:
    comparable = sum(item.unique_reinforced_zone_count >= config.readiness.minimum_reinforced_zones_per_comparable_fold for item in accounting.folds)
    minimum = min((item.unique_reinforced_zone_count for item in accounting.folds if item.unique_reinforced_zone_count >= config.readiness.minimum_reinforced_zones_per_comparable_fold), default=0)
    gates = (
        GateResult("readiness.unique_reinforced_zones", "readiness", accounting.unique_reinforced_zone_count, config.readiness.unique_reinforced_zones, ">=", accounting.unique_reinforced_zone_count >= config.readiness.unique_reinforced_zones, "unique reinforced zones meet readiness threshold"),
        GateResult("readiness.comparable_folds", "readiness", comparable, config.readiness.comparable_folds, ">=", comparable >= config.readiness.comparable_folds, "comparable fold count meets readiness threshold"),
        GateResult("readiness.minimum_reinforced_zones_per_comparable_fold", "readiness", minimum, config.readiness.minimum_reinforced_zones_per_comparable_fold, ">=", minimum >= config.readiness.minimum_reinforced_zones_per_comparable_fold, "comparable folds contain enough unique confirmations"),
    )
    if all(item.passed for item in gates):
        disposition = AuditDisposition.READY_FOR_REINFORCEMENT_DETECTOR_CHALLENGER
        reason = "all reinforcement population readiness gates pass"
    else:
        disposition = AuditDisposition.INSUFFICIENT_REINFORCEMENT_EVIDENCE
        reason = "reinforcement population readiness gates are not satisfied"
    return AuditDecision(contract_valid=True, disposition=disposition, gates=gates, reason=reason)


def build_audit(
    model_bars: tuple[ClosedBar, ...],
    resolved_config: ResolvedSRConfig,
    *,
    config: CandidateAuditConfig,
    source_case_count: int,
    canonical_replay: Any,
    implementation_commit: str,
) -> CandidateReinforcementAudit:
    if type(model_bars) is not tuple or any(type(bar) is not ClosedBar for bar in model_bars):
        raise ContractValidationError("V1.12 model bars must be a ClosedBar tuple")
    if len(model_bars) < 2 or model_bars[0].state_key.symbol != config.asset:
        raise ContractValidationError("V1.12 model bars are outside trial scope")
    initial = create_initial_state(model_bars[0].state_key, resolved_config)
    full = _run_pass(model_bars, resolved_config, config, initial_state=initial)
    split = len(model_bars) // 2
    first = _run_pass(model_bars[:split], resolved_config, config, initial_state=initial)
    second = _run_pass(model_bars[split:], resolved_config, config, initial_state=first.final_state, lineage=first.lineage)
    checkpoint = _ReplayPass(
        initial_state=initial,
        final_state=second.final_state,
        states=first.states + second.states,
        snapshots=first.snapshots + second.snapshots,
        events=first.events + second.events,
        candidates=first.candidates + second.candidates,
        lineage=second.lineage,
    )
    parity = _parity(full, checkpoint, model_bars, canonical_replay)
    candidates = full.candidates
    accounting = _accounting(candidates, source_case_count, config)
    decision = _decision(accounting, config)
    return CandidateReinforcementAudit(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        v11_bundle_id=config.v11.bundle_id,
        v11_study_id=config.v11.study_id,
        v19_bundle_id=config.v19.bundle_id,
        v19_study_id=config.v19.study_id,
        v10_bundle_id=config.v10.bundle_id,
        v10_audit_id=config.v10.audit_id,
        source_bundle_id=config.source.source_bundle_id,
        upstream_source_bundle_id=config.source.upstream_source_bundle_id,
        source_id=config.source.source_id,
        bars_sha256=config.source.bars_sha256,
        candidates=candidates,
        lineage=full.lineage,
        accounting=accounting,
        parity=parity,
        decision=decision,
    )


__all__ = ["build_audit"]
