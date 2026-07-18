from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from libs.models.sr.association import match_candidate
from libs.models.sr.config.models import AssociationConfig
from libs.models.sr.domain import create_initial_state
from libs.models.sr.domain.contracts import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    SREvent,
    SREventType,
    SRState,
    SRSnapshot,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
)
from libs.models.sr.scripts.baseline_trial.config import load_resolved_sr_config
from libs.models.sr.research.studies.candidate_reinforcement_audit import audit
from libs.models.sr.research.studies.candidate_reinforcement_audit.audit import (
    _ReplayPass,
    _accounting,
    _decision,
    _fold_for,
    _observed_events,
    _run_pass,
)
from libs.models.sr.scripts.candidate_reinforcement_audit.contracts import (
    AuditAccounting,
    AuditDecision,
    AuditDisposition,
    FoldAccounting,
    GateResult,
    ReinforcementZoneCount,
    StatusCount,
)
from libs.models.sr.scripts.candidate_reinforcement_audit.config import FOLD_NAMES

from .conftest import BASE, STATE_KEY, digest, make_created, make_match


def _model_bars() -> tuple[ClosedBar, ...]:
    values = (
        100, 101, 102, 103, 104, 105, 104, 103, 102, 101,
        100, 99, 98, 97, 96, 95, 96, 97, 98, 99,
        100, 101, 102, 103, 104, 105, 104, 103, 102, 101,
        100, 99, 98, 97, 96, 95, 96, 97, 98, 99,
        100, 101, 102, 103, 104, 105, 104, 103, 102, 101,
    )
    return tuple(
        ClosedBar(
            state_key=STATE_KEY,
            bar_id=f"model-bar-{index}",
            closed_at=datetime(2024, 4, 11, tzinfo=timezone.utc) + timedelta(days=index),
            open=value,
            high=value + 1,
            low=value - 1,
            close=value,
            atr_at_close=2.0,
        )
        for index, value in enumerate(values)
    )


@pytest.fixture(scope="module")
def resolved_sr():
    return load_resolved_sr_config("configs/sr.yaml", asset="TAOUSDT", timeframe="1d")


def test_first_eligible_confirmation_assigns_one_fold_only(candidate_config):
    seed = make_created()
    early = make_match(seed, match_name="early", fold="2024_q3")
    late = make_match(
        seed,
        match_name="late",
        fold="2024_q4",
        formed=datetime(2024, 10, 2, tzinfo=timezone.utc),
        available=datetime(2024, 10, 3, tzinfo=timezone.utc),
    )

    accounting = _accounting((seed, early, late), 36, candidate_config)
    by_fold = {item.fold: item for item in accounting.folds}

    assert accounting.eligible_reinforcement_count == 2
    assert accounting.unique_reinforced_zone_count == 1
    assert by_fold["2024_q3"].eligible_match_count == 1
    assert by_fold["2024_q3"].unique_reinforced_zone_count == 1
    assert by_fold["2024_q4"].eligible_match_count == 1
    assert by_fold["2024_q4"].unique_reinforced_zone_count == 0


def test_contract_recomputation_rejects_later_fold_unique_inflation(
    candidate_config, synthetic_audit
):
    seed = make_created()
    early = make_match(seed, match_name="early", fold="2024_q3")
    late = make_match(
        seed,
        match_name="late",
        fold="2024_q4",
        formed=datetime(2024, 10, 2, tzinfo=timezone.utc),
        available=datetime(2024, 10, 3, tzinfo=timezone.utc),
    )
    candidates = (seed, early, late)
    accounting = _accounting(candidates, 36, candidate_config)
    valid = replace(
        synthetic_audit,
        candidates=candidates,
        accounting=accounting,
        decision=_decision(accounting, candidate_config),
    )
    q4 = next(item for item in accounting.folds if item.fold == "2024_q4")
    inflated = replace(
        accounting,
        folds=tuple(
            replace(item, unique_reinforced_zone_count=1)
            if item.fold == q4.fold
            else item
            for item in accounting.folds
        ),
    )

    with pytest.raises(ContractValidationError, match="fold accounting"):
        replace(valid, accounting=inflated)


def test_fold_assignment_is_half_open(candidate_config):
    folds = candidate_config.replay.folds
    for index, fold in enumerate(folds):
        assert _fold_for(fold.start, candidate_config) == fold.name
        expected_after_end = folds[index + 1].name if index + 1 < len(folds) else None
        assert _fold_for(fold.end, candidate_config) == expected_after_end


def _decision_accounting(unique: int, fold_unique: tuple[int, ...]) -> AuditAccounting:
    zone_counts = tuple(
        sorted(
            (
                ReinforcementZoneCount(digest(f"decision-zone-{index}"), 1)
                for index in range(unique)
            ),
            key=lambda item: item.zone_id,
        )
    )
    return AuditAccounting(
        source_case_count=36,
        total_candidates=unique,
        created_zone_count=0,
        matched_start_zone_suppressed=unique,
        matched_same_batch_zone_suppressed=0,
        capacity_suppressed=0,
        eligible_reinforcement_count=unique,
        unique_reinforced_zone_count=unique,
        one_reinforcement_zone_count=unique,
        two_reinforcement_zone_count=0,
        three_or_more_reinforcement_zone_count=0,
        support_candidate_count=unique,
        resistance_candidate_count=0,
        out_of_fold_candidate_count=0,
        unmatched_reconciliation_count=0,
        target_post_advance_status_counts=tuple(StatusCount(status, 0) for status in ZoneStatus),
        reinforcement_zone_counts=zone_counts,
        folds=tuple(
            FoldAccounting(
                fold=fold_name,
                candidate_count=unique,
                created_zone_count=0,
                eligible_match_count=fold_count,
                unique_reinforced_zone_count=fold_count,
            )
            for fold_name, fold_count in zip(FOLD_NAMES, fold_unique)
        ),
    )


@pytest.mark.parametrize(
    ("unique", "fold_unique", "expected"),
    (
        (16, (2, 2, 2, 2, 0, 0), AuditDisposition.READY_FOR_REINFORCEMENT_DETECTOR_CHALLENGER),
        (15, (2, 2, 2, 2, 0, 0), AuditDisposition.INSUFFICIENT_REINFORCEMENT_EVIDENCE),
        (16, (2, 2, 2, 1, 0, 0), AuditDisposition.INSUFFICIENT_REINFORCEMENT_EVIDENCE),
        (16, (1, 1, 1, 1, 0, 0), AuditDisposition.INSUFFICIENT_REINFORCEMENT_EVIDENCE),
    ),
)
def test_decision_gates_cover_readiness_boundaries(candidate_config, unique, fold_unique, expected):
    decision = _decision(_decision_accounting(unique, fold_unique), candidate_config)
    assert decision.disposition is expected


def test_invalid_evidence_has_highest_disposition_precedence():
    gates = (
        GateResult("readiness.unique_reinforced_zones", "readiness", 16, 16, ">=", True, "pass"),
        GateResult("readiness.comparable_folds", "readiness", 4, 4, ">=", True, "pass"),
        GateResult("readiness.minimum_reinforced_zones_per_comparable_fold", "readiness", 2, 2, ">=", True, "pass"),
    )
    decision = AuditDecision(False, AuditDisposition.INVALID_EVIDENCE, gates, "contract failure")
    assert decision.disposition is AuditDisposition.INVALID_EVIDENCE


def test_run_pass_reconstructs_creation_and_start_match(candidate_config, resolved_sr):
    bars = _model_bars()
    initial = create_initial_state(STATE_KEY, resolved_sr)
    replay = _run_pass(bars, resolved_sr, candidate_config, initial_state=initial)

    assert replay.states
    assert replay.snapshots
    assert any(item.decision.value == "CREATED_ZONE" for item in replay.candidates)
    assert any(item.decision.value == "MATCHED_START_ZONE_SUPPRESSED" for item in replay.candidates)
    assert len(replay.lineage) == len({item.created_zone_id for item in replay.candidates if item.created_zone_id})


def test_checkpoint_replay_and_canonical_trace_parity(candidate_config, resolved_sr):
    bars = _model_bars()
    initial = create_initial_state(STATE_KEY, resolved_sr)
    full = _run_pass(bars, resolved_sr, candidate_config, initial_state=initial)
    split = len(bars) // 2
    first = _run_pass(bars[:split], resolved_sr, candidate_config, initial_state=initial)
    second = _run_pass(
        bars[split:],
        resolved_sr,
        candidate_config,
        initial_state=first.final_state,
        lineage=first.lineage,
    )
    checkpoint = _ReplayPass(
        initial_state=initial,
        final_state=second.final_state,
        states=first.states + second.states,
        snapshots=first.snapshots + second.snapshots,
        events=first.events + second.events,
        candidates=first.candidates + second.candidates,
        lineage=second.lineage,
    )
    canonical = SimpleNamespace(
        model_bars=bars,
        initial_state=initial,
        snapshots=full.snapshots,
        final_state=full.final_state,
        trace=SimpleNamespace(events=_observed_events(full.snapshots, full.events)),
    )

    parity = audit._parity(full, checkpoint, bars, canonical)
    assert parity.passed
    assert parity.checkpoint_state_digest == parity.state_digest
    assert parity.checkpoint_snapshot_digest == parity.snapshot_digest


def test_same_batch_match_is_diagnostic_only(candidate_config):
    seed = make_created()
    same_batch = make_match(seed, same_batch=True, eligible=False)
    accounting = _accounting((seed, same_batch), 36, candidate_config)

    assert same_batch.eligible_reinforcement is False
    assert accounting.eligible_reinforcement_count == 0
    assert accounting.unique_reinforced_zone_count == 0


def test_run_pass_classifies_same_batch_match_after_prior_creation(
    monkeypatch, candidate_config, resolved_sr
):
    bar = ClosedBar(
        STATE_KEY,
        "same-batch-bar",
        BASE + timedelta(days=10),
        100.0,
        101.0,
        99.0,
        100.0,
        2.0,
    )
    candidates = tuple(
        CandidateLevel(
            state_key=STATE_KEY,
            side=ZoneSide.SUPPORT,
            geometry=ZoneGeometry(center=center, half_width=0.5),
            source="pivot_v1",
            formed_at=bar.closed_at,
            available_at=bar.closed_at,
            atr_at_creation=2.0,
        )
        for center in (100.0, 100.25)
    )
    candidates = tuple(sorted(candidates, key=lambda item: item.candidate_id))

    class FakeEngine:
        def step(self, state, current_bar, config):
            created = audit._new_zone(candidates[0], config)
            next_state = SRState(
                schema_version=state.schema_version,
                state_key=state.state_key,
                config_hash=state.config_hash,
                last_processed_bar=current_bar.bar_id,
                zones=(created,),
                recent_bars=(current_bar,),
            )
            event = SREvent(
                zone_id=created.definition.zone_id,
                event_type=SREventType.CREATED,
                timestamp=current_bar.closed_at,
                price=created.definition.geometry.center,
                bar_id=current_bar.bar_id,
            )
            snapshot = SRSnapshot(
                schema_version=next_state.schema_version,
                state_key=next_state.state_key,
                config_hash=next_state.config_hash,
                as_of=current_bar.closed_at,
                zones=next_state.zones,
                events=(event,),
            )
            return next_state, snapshot, (event,)

    monkeypatch.setattr(audit, "detect_confirmed_pivots", lambda *_args: candidates)
    monkeypatch.setattr(audit, "SREngine", FakeEngine)

    replay = _run_pass(
        (bar,),
        resolved_sr,
        candidate_config,
        initial_state=create_initial_state(STATE_KEY, resolved_sr),
    )

    assert [item.decision.value for item in replay.candidates] == [
        "CREATED_ZONE",
        "MATCHED_SAME_BATCH_ZONE_SUPPRESSED",
    ]
    assert not replay.candidates[1].eligible_reinforcement


def test_canonical_matcher_order_is_distance_then_zone_id():
    candidate = CandidateLevel(
        state_key=STATE_KEY,
        side=ZoneSide.SUPPORT,
        geometry=ZoneGeometry(center=100.0, half_width=1.0),
        source="pivot_v1",
        formed_at=BASE,
        available_at=BASE,
        atr_at_creation=10.0,
    )
    definitions = tuple(
        ZoneDefinition(
            state_key=STATE_KEY,
            side=ZoneSide.SUPPORT,
            geometry=ZoneGeometry(center=center, half_width=1.0),
            source="pivot_v1",
            created_at=BASE,
            available_at=BASE,
            atr_at_creation=2.0,
            config_hash="a" * 64,
        )
        for center in (101.0, 99.0)
    )
    zones = tuple(
        ZoneRecord(
            definition=definition,
            runtime=ZoneRuntimeState(
                zone_id=definition.zone_id,
                status=ZoneStatus.ACTIVE,
                touch_count=0,
                fakeout_count=0,
                pending_breach_count=0,
                age_bars=0,
                last_interaction_at=None,
                updated_at=BASE,
            ),
        )
        for definition in definitions
    )
    expected = min(zones, key=lambda zone: zone.definition.zone_id)

    assert match_candidate(candidate, tuple(reversed(zones)), AssociationConfig(0.5)) is expected


def test_run_pass_capacity_is_checked_after_no_match(monkeypatch, candidate_config, resolved_sr):
    previous = ClosedBar(STATE_KEY, "previous", BASE + timedelta(days=10), 100.0, 101.0, 99.0, 100.0, 2.0)
    current = ClosedBar(STATE_KEY, "current", BASE + timedelta(days=11), 100.0, 101.0, 99.0, 100.0, 2.0)
    seeds = tuple(
        CandidateLevel(
            state_key=STATE_KEY,
            side=ZoneSide.SUPPORT,
            geometry=ZoneGeometry(center=200.0 + index * 10.0, half_width=0.5),
            source="pivot_v1",
            formed_at=BASE,
            available_at=BASE + timedelta(days=1),
            atr_at_creation=2.0,
        )
        for index in range(8)
    )
    definitions = tuple(
        ZoneDefinition(
            state_key=seed.state_key,
            side=seed.side,
            geometry=seed.geometry,
            source=seed.source,
            created_at=seed.formed_at,
            available_at=seed.available_at,
            atr_at_creation=seed.atr_at_creation,
            config_hash=resolved_sr.resolved_config_hash,
        )
        for seed in seeds
    )
    zones = tuple(
        ZoneRecord(
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
        for definition in definitions
    )
    initial = replace(
        create_initial_state(STATE_KEY, resolved_sr),
        last_processed_bar=previous.bar_id,
        zones=zones,
        recent_bars=(previous,),
    )
    candidate = CandidateLevel(
        state_key=STATE_KEY,
        side=ZoneSide.SUPPORT,
        geometry=ZoneGeometry(center=100.0, half_width=0.5),
        source="pivot_v1",
        formed_at=previous.closed_at,
        available_at=current.closed_at,
        atr_at_creation=2.0,
    )
    monkeypatch.setattr(audit, "detect_confirmed_pivots", lambda *_args: (candidate,))

    replay = _run_pass((current,), resolved_sr, candidate_config, initial_state=initial)

    assert len(replay.candidates) == 1
    assert replay.candidates[0].decision.value == "CAPACITY_SUPPRESSED"
    assert replay.candidates[0].active_zone_count_before_capacity == 8
