from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendline_v2.domain import (
    AbstentionReason,
    AnchorRef,
    CandidateEvidence,
    LineCandidate,
    LineGeometry,
    LineRole,
)
from libs.models.trendline_v2.domain.identity import deterministic_hash, provider_identity
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.selection import (
    CandidateSelectionDecision,
    CandidateSelectionSnapshot,
    SelectionDiagnostics,
    SelectionStatus,
    candidate_set_identity,
)
from libs.models.trendline_v2.tracking import (
    EXPECTED_TRACKING_POLICY_IDENTITY,
    ExactSelectedStructureTrackingPolicy,
    FamilyTrackingTransition,
    FamilyTrackingTransitionType,
    TrackingStatus,
    TrendlineTrackingSnapshot,
    tracked_family_id,
)
from libs.models.trendline_v2.tracking.exact_lineage import track_selected_trendlines


UTC = timezone.utc
BASE = datetime(2024, 1, 1, tzinfo=UTC)
SELECTION_POLICY_ID = (
    "3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc"
)
INPUT_ID = deterministic_hash("test_tracking_input", {"value": 1})
CONFIG_ID = deterministic_hash("test_tracking_config", {"value": 1})
PROVIDER_ID = provider_identity("confirmed_extrema_pair", "v1")


def _candidate(
    *,
    observed_at: datetime = BASE + timedelta(hours=4),
    role: LineRole = LineRole.SUPPORT,
    geometry_delta: float = 2.0,
    anchor_delta: float = 0.0,
    provider_name: str = "confirmed_extrema_pair",
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
) -> LineCandidate:
    first = BASE
    second = BASE + timedelta(hours=2)
    anchors = (
        AnchorRef(
            anchor_id=deterministic_hash("test_anchor", {"side": "first", "delta": anchor_delta}),
            pivot_time=first,
            confirmation_time=first + timedelta(hours=1),
            price=100.0 + anchor_delta,
        ),
        AnchorRef(
            anchor_id=deterministic_hash("test_anchor", {"side": "second", "delta": anchor_delta}),
            pivot_time=second,
            confirmation_time=second + timedelta(hours=1),
            price=102.0 + anchor_delta,
        ),
    )
    evidence = CandidateEvidence(
        anchor_count=2,
        distinct_anchor_timestamps=2,
        anchor_span_seconds=(second - first).total_seconds(),
    )
    return LineCandidate.create(
        asset=asset,
        timeframe=timeframe,
        role=role,
        geometry=LineGeometry(
            start_time=first,
            end_time=second,
            start_price=100.0 + anchor_delta,
            end_price=100.0 + geometry_delta + anchor_delta,
        ),
        anchors=anchors,
        evidence=evidence,
        observed_at=observed_at,
        provider_name=provider_name,
        provider_version="v1",
    )


def _selection(
    candidates: tuple[LineCandidate, ...] = (_candidate(),),
    *,
    observed_at: datetime | None = None,
    source_snapshot_id: str | None = None,
    selection_policy_identity: str = SELECTION_POLICY_ID,
    input_identity: str = INPUT_ID,
) -> CandidateSelectionSnapshot:
    observed_at = observed_at or candidates[0].observed_at
    source_snapshot_id = source_snapshot_id or deterministic_hash(
        "test_selection_source", {"observed_at": observed_at}
    )
    decisions = tuple(
        CandidateSelectionDecision.create(
            role=candidate.role,
            second_anchor_id=candidate.anchors[1].anchor_id,
            second_anchor_time=candidate.anchors[1].pivot_time,
            considered_candidate_ids=(candidate.candidate_id,),
            selected_candidate_id=candidate.candidate_id,
            selected_first_anchor_id=candidate.anchors[0].anchor_id,
            selected_first_anchor_time=candidate.anchors[0].pivot_time,
            latest_timestamp_tie_count=1,
            selection_policy_identity=selection_policy_identity,
        )
        for candidate in candidates
    )
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.role.value,
                item.anchors[1].pivot_time,
                item.anchors[1].anchor_id,
                item.candidate_id,
            ),
        )
    )
    decisions = tuple(
        sorted(
            decisions,
            key=lambda item: (
                item.role.value,
                item.second_anchor_time,
                item.second_anchor_id,
                item.selected_candidate_id,
            ),
        )
    )
    return CandidateSelectionSnapshot(
        asset=candidates[0].asset,
        timeframe=candidates[0].timeframe,
        observed_at=observed_at,
        source_snapshot_id=source_snapshot_id,
        input_identity=input_identity,
        discovery_config_identity=CONFIG_ID,
        provider_identity=provider_identity(
            candidates[0].provider_name, candidates[0].provider_version
        ),
        selection_policy_identity=selection_policy_identity,
        status=SelectionStatus.SELECTED,
        source_reason=None,
        source_candidate_set_identity=candidate_set_identity(
            tuple(candidate.candidate_id for candidate in ordered)
        ),
        selected_candidates=ordered,
        decisions=decisions,
        diagnostics=SelectionDiagnostics(
            source_candidate_count=len(ordered),
            source_group_count=len(ordered),
            selected_candidate_count=len(ordered),
            rejected_candidate_count=0,
            support_selected_count=sum(candidate.role is LineRole.SUPPORT for candidate in ordered),
            resistance_selected_count=sum(
                candidate.role is LineRole.RESISTANCE for candidate in ordered
            ),
            latest_timestamp_tie_group_count=0,
        ),
    )


def _unavailable(
    *,
    status: SelectionStatus = SelectionStatus.SOURCE_ABSTAINED,
    observed_at: datetime = BASE + timedelta(hours=8),
    input_identity: str = INPUT_ID,
) -> CandidateSelectionSnapshot:
    return CandidateSelectionSnapshot(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=observed_at,
        source_snapshot_id=deterministic_hash("test_unavailable", {"at": observed_at}),
        input_identity=input_identity,
        discovery_config_identity=CONFIG_ID,
        provider_identity=PROVIDER_ID,
        selection_policy_identity=SELECTION_POLICY_ID,
        status=status,
        source_reason=(
            AbstentionReason.INSUFFICIENT_DATA
            if status is SelectionStatus.SOURCE_ABSTAINED
            else AbstentionReason.PROVIDER_FAILURE
        ),
        source_candidate_set_identity=candidate_set_identity(()),
        selected_candidates=(),
        decisions=(),
        diagnostics=SelectionDiagnostics(0, 0, 0, 0, 0, 0, 0),
    )


def _initial_snapshot() -> TrendlineTrackingSnapshot:
    return track_selected_trendlines(
        _selection(),
        previous=None,
        policy=ExactSelectedStructureTrackingPolicy(),
    )


def test_tracking_policy_identity_and_payload_are_exact() -> None:
    policy = ExactSelectedStructureTrackingPolicy()
    assert policy.policy_identity == EXPECTED_TRACKING_POLICY_IDENTITY
    assert ExactSelectedStructureTrackingPolicy.from_dict(policy.to_dict()) == policy


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_name": "other"},
        {"policy_version": "v2"},
        {"supported_selection_policy_identity": deterministic_hash("other", {})},
    ],
)
def test_tracking_policy_rejects_semantic_deviation(changes: dict[str, str]) -> None:
    with pytest.raises(ContractValidationError):
        ExactSelectedStructureTrackingPolicy(**changes)


def test_family_id_excludes_candidate_id_and_observation_time() -> None:
    candidate = _candidate()
    later = _candidate(observed_at=BASE + timedelta(hours=8))
    kwargs = {
        "provider_identity": PROVIDER_ID,
        "discovery_config_identity": CONFIG_ID,
        "selection_policy_identity": SELECTION_POLICY_ID,
        "tracking_policy_identity": ExactSelectedStructureTrackingPolicy().policy_identity,
    }
    assert candidate.candidate_id != later.candidate_id
    assert tracked_family_id(candidate, **kwargs) == tracked_family_id(later, **kwargs)


@pytest.mark.parametrize(
    "changes",
    [
        {"geometry_delta": 3.0},
        {"anchor_delta": 1.0},
        {"role": LineRole.RESISTANCE},
    ],
)
def test_family_id_changes_for_structural_changes(changes: dict[str, object]) -> None:
    base = _candidate()
    changed = _candidate(**changes)  # type: ignore[arg-type]
    kwargs = {
        "provider_identity": PROVIDER_ID,
        "discovery_config_identity": CONFIG_ID,
        "selection_policy_identity": SELECTION_POLICY_ID,
        "tracking_policy_identity": ExactSelectedStructureTrackingPolicy().policy_identity,
    }
    assert tracked_family_id(base, **kwargs) != tracked_family_id(changed, **kwargs)


def test_family_id_changes_for_identity_inputs() -> None:
    candidate = _candidate()
    policy_id = ExactSelectedStructureTrackingPolicy().policy_identity
    base = tracked_family_id(
        candidate,
        provider_identity=PROVIDER_ID,
        discovery_config_identity=CONFIG_ID,
        selection_policy_identity=SELECTION_POLICY_ID,
        tracking_policy_identity=policy_id,
    )
    for field, value in (
        ("provider_identity", provider_identity("other_provider", "v1")),
        ("discovery_config_identity", deterministic_hash("config", {})),
        ("selection_policy_identity", deterministic_hash("selection", {})),
        ("tracking_policy_identity", deterministic_hash("tracking", {})),
    ):
        values = {
            "provider_identity": PROVIDER_ID,
            "discovery_config_identity": CONFIG_ID,
            "selection_policy_identity": SELECTION_POLICY_ID,
            "tracking_policy_identity": policy_id,
        }
        values[field] = value
        candidate_value = (
            _candidate(provider_name="other_provider")
            if field == "provider_identity"
            else candidate
        )
        assert tracked_family_id(candidate_value, **values) != base


def test_tracked_family_and_snapshot_round_trip() -> None:
    snapshot = _initial_snapshot()
    assert TrendlineTrackingSnapshot.from_dict(snapshot.to_dict()) == snapshot
    assert snapshot.active_families[0].to_dict() == snapshot.active_families[0].to_dict()


def test_family_id_mismatch_and_last_seen_mismatch_rejected() -> None:
    snapshot = _initial_snapshot()
    family = snapshot.active_families[0]
    with pytest.raises(ContractValidationError):
        replace(family, family_id=deterministic_hash("wrong", {}))
    with pytest.raises(ContractValidationError):
        replace(family, last_seen_at=family.last_seen_at + timedelta(hours=1))


def test_transition_types_have_exact_field_semantics() -> None:
    snapshot = _initial_snapshot()
    family = snapshot.active_families[0]
    policy_id = ExactSelectedStructureTrackingPolicy().policy_identity
    birth = snapshot.transitions[0]
    assert birth.transition_type is FamilyTrackingTransitionType.BIRTH
    continued = FamilyTrackingTransition.create(
        family_id=family.family_id,
        transition_type=FamilyTrackingTransitionType.CONTINUE,
        observed_at=BASE + timedelta(hours=8),
        previous_family_version=1,
        current_family_version=2,
        previous_candidate_id=family.current_candidate.candidate_id,
        current_candidate_id=deterministic_hash("current_candidate", {}),
        previous_selection_snapshot_id=family.current_selection_snapshot_id,
        current_selection_snapshot_id=deterministic_hash("current_selection", {}),
        tracking_policy_identity=policy_id,
    )
    removed = FamilyTrackingTransition.create(
        family_id=family.family_id,
        transition_type=FamilyTrackingTransitionType.SOURCE_REMOVED,
        observed_at=BASE + timedelta(hours=8),
        previous_family_version=1,
        current_family_version=None,
        previous_candidate_id=family.current_candidate.candidate_id,
        current_candidate_id=None,
        previous_selection_snapshot_id=family.current_selection_snapshot_id,
        current_selection_snapshot_id=deterministic_hash("current_selection", {}),
        tracking_policy_identity=policy_id,
    )
    assert continued.current_family_version == 2
    assert removed.current_candidate_id is None
    with pytest.raises(ContractValidationError):
        FamilyTrackingTransition.create(
            family_id=family.family_id,
            transition_type=FamilyTrackingTransitionType.BIRTH,
            observed_at=BASE,
            previous_family_version=1,
            current_family_version=2,
            previous_candidate_id=None,
            current_candidate_id=deterministic_hash("candidate", {}),
            previous_selection_snapshot_id=None,
            current_selection_snapshot_id=deterministic_hash("snapshot", {}),
            tracking_policy_identity=policy_id,
        )


def test_non_birth_transitions_require_advancing_source_and_candidate_ids() -> None:
    snapshot = _initial_snapshot()
    family = snapshot.active_families[0]
    policy_id = ExactSelectedStructureTrackingPolicy().policy_identity
    with pytest.raises(ContractValidationError):
        FamilyTrackingTransition.create(
            family_id=family.family_id,
            transition_type=FamilyTrackingTransitionType.CONTINUE,
            observed_at=BASE + timedelta(hours=8),
            previous_family_version=1,
            current_family_version=2,
            previous_candidate_id=family.current_candidate.candidate_id,
            current_candidate_id=deterministic_hash("current_candidate", {}),
            previous_selection_snapshot_id=family.current_selection_snapshot_id,
            current_selection_snapshot_id=family.current_selection_snapshot_id,
            tracking_policy_identity=policy_id,
        )

    valid = FamilyTrackingTransition.create(
        family_id=family.family_id,
        transition_type=FamilyTrackingTransitionType.CONTINUE,
        observed_at=BASE + timedelta(hours=8),
        previous_family_version=1,
        current_family_version=2,
        previous_candidate_id=family.current_candidate.candidate_id,
        current_candidate_id=deterministic_hash("current_candidate", {}),
        previous_selection_snapshot_id=family.current_selection_snapshot_id,
        current_selection_snapshot_id=deterministic_hash("current_selection", {}),
        tracking_policy_identity=policy_id,
    )
    payload = valid.to_dict()
    payload["current_selection_snapshot_id"] = payload["previous_selection_snapshot_id"]
    with pytest.raises(ContractValidationError):
        FamilyTrackingTransition.from_dict(payload)
    with pytest.raises(ContractValidationError):
        FamilyTrackingTransition.create(
            family_id=family.family_id,
            transition_type=FamilyTrackingTransitionType.CONTINUE,
            observed_at=BASE + timedelta(hours=8),
            previous_family_version=1,
            current_family_version=2,
            previous_candidate_id=family.current_candidate.candidate_id,
            current_candidate_id=family.current_candidate.candidate_id,
            previous_selection_snapshot_id=family.current_selection_snapshot_id,
            current_selection_snapshot_id=deterministic_hash("current_selection", {}),
            tracking_policy_identity=policy_id,
        )
    with pytest.raises(ContractValidationError):
        FamilyTrackingTransition.create(
            family_id=family.family_id,
            transition_type=FamilyTrackingTransitionType.SOURCE_REMOVED,
            observed_at=BASE + timedelta(hours=8),
            previous_family_version=1,
            current_family_version=None,
            previous_candidate_id=family.current_candidate.candidate_id,
            current_candidate_id=None,
            previous_selection_snapshot_id=family.current_selection_snapshot_id,
            current_selection_snapshot_id=family.current_selection_snapshot_id,
            tracking_policy_identity=policy_id,
        )


def test_snapshot_rejects_current_selection_binding_drift() -> None:
    first = _initial_snapshot()
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    later = track_selected_trendlines(
        _selection(
            (later_candidate,),
            observed_at=later_candidate.observed_at,
            input_identity=deterministic_hash("later_input", {}),
        ),
        previous=first,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    bad_family = replace(
        later.active_families[0],
        current_selection_snapshot_id=deterministic_hash("unrelated_selection", {}),
    )
    with pytest.raises(ContractValidationError, match="updated family selection"):
        replace(later, active_families=(bad_family,))

    payload = later.to_dict()
    payload["active_families"][0]["current_selection_snapshot_id"] = (
        deterministic_hash("unrelated_selection", {})
    )
    with pytest.raises(ContractValidationError):
        TrendlineTrackingSnapshot.from_dict(payload)


def test_unavailable_snapshot_rejects_current_source_binding() -> None:
    first = _initial_snapshot()
    unavailable = track_selected_trendlines(
        _unavailable(
            observed_at=BASE + timedelta(hours=8),
            input_identity=deterministic_hash("unavailable_input", {}),
        ),
        previous=first,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    bad_family = replace(
        first.active_families[0],
        current_selection_snapshot_id=unavailable.source_selection_snapshot_id,
    )
    with pytest.raises(ContractValidationError, match="unavailable source"):
        replace(unavailable, active_families=(bad_family,))

    payload = unavailable.to_dict()
    payload["active_families"][0]["current_selection_snapshot_id"] = (
        unavailable.source_selection_snapshot_id
    )
    with pytest.raises(ContractValidationError):
        TrendlineTrackingSnapshot.from_dict(payload)


@pytest.mark.parametrize(
    "source_status, source_reason",
    [
        (SelectionStatus.SOURCE_FAILED, AbstentionReason.NO_CANDIDATES),
        (SelectionStatus.SOURCE_ABSTAINED, AbstentionReason.PROVIDER_FAILURE),
    ],
)
def test_unavailable_snapshot_rejects_impossible_source_status_reason(
    source_status: SelectionStatus,
    source_reason: AbstentionReason,
) -> None:
    snapshot = track_selected_trendlines(
        _unavailable(),
        previous=None,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    with pytest.raises(ContractValidationError):
        replace(
            snapshot,
            source_selection_status=source_status,
            source_reason=source_reason,
        )

    payload = snapshot.to_dict()
    payload["source_selection_status"] = source_status.value
    payload["source_reason"] = source_reason.value
    with pytest.raises(ContractValidationError):
        TrendlineTrackingSnapshot.from_dict(payload)


def test_unavailable_snapshot_rejects_future_carried_family() -> None:
    first = _initial_snapshot()
    future_candidate = _candidate(observed_at=BASE + timedelta(hours=12))
    future = track_selected_trendlines(
        _selection(
            (future_candidate,),
            observed_at=future_candidate.observed_at,
            input_identity=deterministic_hash("future_input", {}),
        ),
        previous=first,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    unavailable = track_selected_trendlines(
        _unavailable(
            observed_at=BASE + timedelta(hours=8),
            input_identity=deterministic_hash("unavailable_input", {}),
        ),
        previous=first,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    with pytest.raises(ContractValidationError, match="precede unavailable"):
        replace(unavailable, active_families=future.active_families)

    payload = unavailable.to_dict()
    payload["active_families"] = [family.to_dict() for family in future.active_families]
    with pytest.raises(ContractValidationError):
        TrendlineTrackingSnapshot.from_dict(payload)


@pytest.mark.parametrize("status", [TrackingStatus.UPDATED, TrackingStatus.SOURCE_UNAVAILABLE])
def test_initial_snapshot_rejects_phantom_removed_families(status: TrackingStatus) -> None:
    if status is TrackingStatus.UPDATED:
        snapshot = _initial_snapshot()
    else:
        snapshot = track_selected_trendlines(
            _unavailable(), previous=None, policy=ExactSelectedStructureTrackingPolicy()
        )
    removed_id = deterministic_hash("phantom_removed", {})
    with pytest.raises(ContractValidationError, match="initial tracking snapshot"):
        replace(
            snapshot,
            removed_family_ids=(removed_id,),
            diagnostics=replace(snapshot.diagnostics, cumulative_removed_count=1),
        )
    payload = snapshot.to_dict()
    payload["removed_family_ids"] = [removed_id]
    payload["diagnostics"]["cumulative_removed_count"] = 1
    with pytest.raises(ContractValidationError):
        TrendlineTrackingSnapshot.from_dict(payload)


def test_snapshot_contract_rejects_duplicate_families_transitions_and_overlap() -> None:
    snapshot = _initial_snapshot()
    family = snapshot.active_families[0]
    with pytest.raises(ContractValidationError):
        replace(
            snapshot,
            active_families=(family, family),
            diagnostics=replace(
                snapshot.diagnostics,
                current_active_count=2,
                source_selected_candidate_count=2,
                birth_count=2,
            ),
        )
    with pytest.raises(ContractValidationError):
        replace(
            snapshot,
            removed_family_ids=(family.family_id,),
        )
    with pytest.raises(ContractValidationError):
        replace(snapshot, transitions=(snapshot.transitions[0], snapshot.transitions[0]))


def test_snapshot_identity_changes_when_lineage_changes() -> None:
    snapshot = _initial_snapshot()
    assert replace(
        snapshot,
        previous_tracking_snapshot_id=deterministic_hash("previous", {}),
    ).snapshot_id != snapshot.snapshot_id


def test_source_unavailable_snapshot_contract_is_empty_initially() -> None:
    snapshot = track_selected_trendlines(
        _unavailable(),
        previous=None,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    assert snapshot.active_families == ()
    assert snapshot.transitions == ()
    assert snapshot.diagnostics.carried_forward_count == 0
