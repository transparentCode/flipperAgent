"""Phase-G aggregate snapshot identity audit coverage."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from libs.models.trendline_family.contracts import (
    ContractValidationError,
    FamilySourceGroupAudit,
    FamilyTransition,
    TrendlineFamilySnapshot,
    compute_trendline_family_snapshot_id,
    deterministic_hash,
    deterministic_id,
    trendline_family_snapshot_has_phase_g_evidence,
)
from libs.models.trendline_family.repository import (
    InMemoryTrendlineFamilyRepository,
    SnapshotVersionError,
    _phase_g_enabled,
    serialize_snapshot,
)
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import (
    SequenceProvider,
    candidate,
    timestamp,
    tracker_config,
    tracker_ohlcv,
    valid_result,
)


def _phase_g_snapshot() -> TrendlineFamilySnapshot:
    config = tracker_config()
    observed_at = timestamp()
    return TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(candidate(config, observed_at)),)),
        config=config,
    ).update(tracker_ohlcv(observed_at)).snapshot


def _markerless_diagnostics(
    snapshot: TrendlineFamilySnapshot,
    *,
    retain_phase_g_diagnostics: bool = False,
) -> dict[str, Any]:
    diagnostics = dict(snapshot.diagnostics)
    diagnostics.pop("rail_grouping_enabled")
    if not retain_phase_g_diagnostics:
        for key in (
            "rail_group_count",
            "rail_grouping_rejection_reasons",
            "family_corridor_count",
            "singleton_family_count",
            "multi_rail_family_count",
            "total_rail_count",
            "representative_change_count",
        ):
            diagnostics.pop(key)
    return diagnostics


def _multi_rail_snapshot() -> TrendlineFamilySnapshot:
    config = tracker_config(
        rails={
            "minimum_spacing_atr": 0.01,
            "max_adjacent_gap_atr": 0.50,
            "max_corridor_width_atr": 1.00,
        }
    )
    observed_at = timestamp()
    candidates = (
        candidate(config, observed_at, candidate_id="left", reference_price=100.0),
        candidate(config, observed_at, candidate_id="right", reference_price=100.4),
    )
    return TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(*candidates),)),
        config=config,
    ).update(tracker_ohlcv(observed_at)).snapshot


def _snapshot_id(snapshot: TrendlineFamilySnapshot, **changes: object) -> str:
    fields = (
        "asset",
        "timeframe",
        "timestamp",
        "previous_snapshot_id",
        "model_version",
        "config_version",
        "resolved_config_hash",
        "active_families",
        "dormant_families",
        "transitions",
        "source_group_audits",
        "corridors",
        "observations",
        "interaction_events",
        "interaction_event_transitions",
        "diagnostics",
    )
    return compute_trendline_family_snapshot_id(
        **{field: changes.get(field, getattr(snapshot, field)) for field in fields}
    )


def _reidentified_transition(
    snapshot: TrendlineFamilySnapshot,
    transition: FamilyTransition,
    **changes: object,
) -> FamilyTransition:
    provisional = replace(transition, **changes)
    payload = provisional.to_dict()
    payload.pop("transition_id")
    resulting_family = next(
        family
        for family in snapshot.active_families + snapshot.dormant_families
        if family.family_id == provisional.family_id
    )
    return replace(
        provisional,
        transition_id=deterministic_id(
            "family-transition",
            {
                "transition": payload,
                "resulting_family_state": resulting_family.to_dict(),
            },
        ),
    )


def _changed_source_audit(
    snapshot: TrendlineFamilySnapshot,
) -> tuple[FamilySourceGroupAudit, FamilyTransition]:
    original = snapshot.source_group_audits[0]
    changed_candidate = replace(
        original.candidates[0],
        diagnostics=replace(
            original.candidates[0].diagnostics,
            raw_score=original.candidates[0].diagnostics.raw_score + 0.01,
        ),
    )
    candidate_hashes = (deterministic_hash(changed_candidate.to_dict()),)
    identity_payload = {
        "asset": original.asset,
        "timeframe": original.timeframe,
        "role": original.role.value,
        "observed_at": original.observed_at,
        "candidate_ids": original.candidate_ids,
        "candidate_content_hashes": candidate_hashes,
        "model_version": original.model_version,
        "config_version": original.config_version,
        "resolved_config_hash": original.resolved_config_hash,
    }
    changed_audit = FamilySourceGroupAudit(
        source_group_id=deterministic_id("family-source-group-audit", identity_payload),
        asset=original.asset,
        timeframe=original.timeframe,
        role=original.role,
        observed_at=original.observed_at,
        candidate_ids=original.candidate_ids,
        candidates=(changed_candidate,),
        candidate_content_hashes=candidate_hashes,
        model_version=original.model_version,
        config_version=original.config_version,
        resolved_config_hash=original.resolved_config_hash,
    )
    changed_transition = _reidentified_transition(
        snapshot,
        snapshot.transitions[0],
        source_group_id=changed_audit.source_group_id,
    )
    return changed_audit, changed_transition


def test_tracker_phase_g_snapshot_id_matches_existing_canonical_algorithm() -> None:
    snapshot = _phase_g_snapshot()

    assert snapshot.snapshot_id == "be628af8-a752-545d-9466-122df5853355"
    assert snapshot.snapshot_id == _snapshot_id(snapshot)


def test_phase_g_snapshot_id_is_byte_identical_on_deterministic_replay() -> None:
    assert _phase_g_snapshot().snapshot_id == _phase_g_snapshot().snapshot_id


def test_phase_g_snapshot_rejects_arbitrary_snapshot_id() -> None:
    snapshot = _phase_g_snapshot()

    with pytest.raises(ContractValidationError, match="snapshot_id must bind"):
        replace(snapshot, snapshot_id="arbitrary-phase-g-id")


@pytest.mark.parametrize(
    "evidence",
    ("corridor", "membership", "multi_member", "diagnostics", "source_audit"),
)
def test_phase_g_structural_evidence_requires_explicit_marker(evidence: str) -> None:
    snapshot = _multi_rail_snapshot() if evidence == "multi_member" else _phase_g_snapshot()
    diagnostics = _markerless_diagnostics(
        snapshot,
        retain_phase_g_diagnostics=evidence == "diagnostics",
    )
    changes: dict[str, Any] = {"diagnostics": diagnostics}
    if evidence != "source_audit":
        changes["source_group_audits"] = ()
    if evidence != "corridor":
        changes["corridors"] = ()
    if evidence != "membership":
        changes["transitions"] = ()

    with pytest.raises(ContractValidationError, match="Phase-G evidence requires"):
        replace(snapshot, **changes)


def test_marker_stripping_cannot_bypass_stale_phase_g_snapshot_identity() -> None:
    snapshot = _phase_g_snapshot()
    corrupted = replace(snapshot)
    object.__setattr__(corrupted, "diagnostics", _markerless_diagnostics(snapshot))
    object.__setattr__(corrupted, "source_group_audits", ())
    repository = InMemoryTrendlineFamilyRepository()
    repository.save_snapshot(snapshot)
    before = repository.latest_snapshot(snapshot.asset, snapshot.timeframe)
    assert before is not None

    with pytest.raises(SnapshotVersionError, match="Phase-G evidence requires"):
        repository.save_snapshot(corrupted)

    after = repository.latest_snapshot(snapshot.asset, snapshot.timeframe)
    assert after is not None
    assert serialize_snapshot(after) == serialize_snapshot(before)


def test_shared_phase_g_classifier_matches_contract_and_repository(snapshot) -> None:
    phase_g_snapshot = _phase_g_snapshot()

    assert trendline_family_snapshot_has_phase_g_evidence(phase_g_snapshot)
    assert _phase_g_enabled(phase_g_snapshot)
    assert not trendline_family_snapshot_has_phase_g_evidence(snapshot)
    assert not _phase_g_enabled(snapshot)


def test_historical_snapshot_without_phase_g_evidence_remains_persistable(snapshot) -> None:
    repository = InMemoryTrendlineFamilyRepository()

    assert not trendline_family_snapshot_has_phase_g_evidence(snapshot)
    repository.save_snapshot(snapshot)
    assert repository.latest_snapshot(snapshot.asset, snapshot.timeframe) == snapshot


def test_phase_g_snapshot_rejects_stale_id_after_reidentified_source_audit() -> None:
    snapshot = _phase_g_snapshot()
    changed_audit, changed_transition = _changed_source_audit(snapshot)

    assert _snapshot_id(
        snapshot,
        source_group_audits=(changed_audit,),
        transitions=(changed_transition,),
    ) != snapshot.snapshot_id
    with pytest.raises(ContractValidationError, match="snapshot_id must bind"):
        replace(
            snapshot,
            source_group_audits=(changed_audit,),
            transitions=(changed_transition,),
        )


def test_phase_g_snapshot_accepts_recomputed_id_after_source_audit_change() -> None:
    snapshot = _phase_g_snapshot()
    changed_audit, changed_transition = _changed_source_audit(snapshot)
    changed_id = _snapshot_id(
        snapshot,
        source_group_audits=(changed_audit,),
        transitions=(changed_transition,),
    )

    changed = replace(
        snapshot,
        snapshot_id=changed_id,
        source_group_audits=(changed_audit,),
        transitions=(changed_transition,),
    )

    assert changed.snapshot_id == changed_id
    assert changed.snapshot_id != snapshot.snapshot_id


@pytest.mark.parametrize(
    "payload_part",
    ("transition", "corridor", "observation_event", "diagnostics"),
)
def test_phase_g_snapshot_id_binds_each_aggregate_payload_part(payload_part: str) -> None:
    snapshot = _phase_g_snapshot()

    if payload_part == "transition":
        transition = _reidentified_transition(
            snapshot,
            snapshot.transitions[0],
            reason_codes=snapshot.transitions[0].reason_codes + ("tampered",),
        )
        changes: dict[str, Any] = {"transitions": (transition,)}
    elif payload_part == "corridor":
        corridor = replace(snapshot.corridors[0])
        object.__setattr__(corridor, "corridor_id", "tampered-corridor")
        changes = {"corridors": (corridor,)}
    elif payload_part == "observation_event":
        observation = replace(snapshot.observations[0])
        event = replace(snapshot.interaction_events[0])
        object.__setattr__(observation, "observation_id", "tampered-observation")
        object.__setattr__(event, "last_observation_id", "tampered-observation")
        changes = {
            "observations": (observation,),
            "interaction_events": (event,),
        }
    else:
        changes = {"diagnostics": {**snapshot.diagnostics, "tampered": True}}

    with pytest.raises(ContractValidationError, match="snapshot_id must bind"):
        replace(snapshot, **changes)


def test_repository_rejects_stale_phase_g_id_before_replacing_head() -> None:
    snapshot = _phase_g_snapshot()
    changed_audit, changed_transition = _changed_source_audit(snapshot)
    corrupted = replace(snapshot)
    object.__setattr__(corrupted, "source_group_audits", (changed_audit,))
    object.__setattr__(corrupted, "transitions", (changed_transition,))
    repository = InMemoryTrendlineFamilyRepository()
    repository.save_snapshot(snapshot)
    before = repository.latest_snapshot(snapshot.asset, snapshot.timeframe)
    assert before is not None

    with pytest.raises(SnapshotVersionError, match="snapshot_id must bind"):
        repository.save_snapshot(corrupted)

    after = repository.latest_snapshot(snapshot.asset, snapshot.timeframe)
    assert after is not None
    assert serialize_snapshot(after) == serialize_snapshot(before)
