from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from libs.models.trendline_v2.domain import LineRole, ProviderInput
from libs.models.trendline_v2.domain.identity import deterministic_hash, provider_identity
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.selection import SelectionStatus
from libs.models.trendline_v2.tracking import (
    ExactSelectedStructureTrackingPolicy,
    FamilyTrackingTransitionType,
    TrackingStatus,
    track_selected_trendlines,
)

from test_tracking_contracts import (
    BASE,
    _candidate,
    _selection,
    _unavailable,
)


POLICY = ExactSelectedStructureTrackingPolicy()


def _provider_input(row_count: int) -> ProviderInput:
    base_ns = int(BASE.timestamp()) * 1_000_000_000
    timestamps = tuple(base_ns + index * 3_600_000_000_000 for index in range(row_count))
    confirmed_through = BASE + timedelta(hours=row_count - 1)
    return ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=confirmed_through,
        confirmed_through=confirmed_through,
        timestamps=timestamps,
        open=(10.0,) * row_count,
        high=(11.0,) * row_count,
        low=(9.0,) * row_count,
        close=(10.0,) * row_count,
        volume=(1.0,) * row_count,
    )


NEXT_INPUT_ID = _provider_input(3).input_identity
LATEST_INPUT_ID = _provider_input(4).input_identity


def test_initial_selected_snapshot_creates_all_births() -> None:
    selection = _selection((_candidate(), _candidate(role=LineRole.RESISTANCE)))
    snapshot = track_selected_trendlines(selection, previous=None, policy=POLICY)
    assert snapshot.status is TrackingStatus.UPDATED
    assert len(snapshot.active_families) == 2
    assert snapshot.diagnostics.birth_count == 2
    assert all(
        transition.transition_type is FamilyTrackingTransitionType.BIRTH
        for transition in snapshot.transitions
    )


def test_exact_structure_continues_across_candidate_id_turnover() -> None:
    first_selection = _selection()
    first = track_selected_trendlines(first_selection, previous=None, policy=POLICY)
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    later_selection = _selection(
        (later_candidate,),
        observed_at=later_candidate.observed_at,
        input_identity=NEXT_INPUT_ID,
    )
    later = track_selected_trendlines(later_selection, previous=first, policy=POLICY)
    assert later.active_families[0].family_id == first.active_families[0].family_id
    assert later.active_families[0].version == 2
    assert later.active_families[0].observation_count == 2
    assert later.active_families[0].first_seen_at == first.active_families[0].first_seen_at
    assert later.active_families[0].last_seen_at == later.observed_at
    assert later.transitions[0].transition_type is FamilyTrackingTransitionType.CONTINUE
    assert later.active_families[0].current_candidate.candidate_id != (
        first.active_families[0].current_candidate.candidate_id
    )


def test_advancing_provider_inputs_change_identity_and_continue() -> None:
    first_input = _provider_input(2)
    later_input = _provider_input(3)
    assert first_input.input_identity != later_input.input_identity

    first = track_selected_trendlines(
        _selection(input_identity=first_input.input_identity),
        previous=None,
        policy=POLICY,
    )
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    later = track_selected_trendlines(
        _selection(
            (later_candidate,),
            observed_at=later_candidate.observed_at,
            input_identity=later_input.input_identity,
        ),
        previous=first,
        policy=POLICY,
    )
    assert later.status is TrackingStatus.UPDATED
    assert later.input_identity == later_input.input_identity
    assert later.active_families[0].family_id == first.active_families[0].family_id
    assert later.transitions[0].transition_type is FamilyTrackingTransitionType.CONTINUE


@pytest.mark.parametrize("status", [SelectionStatus.SOURCE_ABSTAINED, SelectionStatus.SOURCE_FAILED])
def test_source_unavailable_carries_advancing_input_identity(status: SelectionStatus) -> None:
    first_input = _provider_input(2)
    later_input = _provider_input(3)
    first = track_selected_trendlines(
        _selection(input_identity=first_input.input_identity),
        previous=None,
        policy=POLICY,
    )
    carried = track_selected_trendlines(
        _unavailable(status=status, input_identity=later_input.input_identity),
        previous=first,
        policy=POLICY,
    )
    assert carried.input_identity == later_input.input_identity
    assert carried.active_families == first.active_families


def test_new_line_birth_and_valid_source_disappearance_are_lineage_events_only() -> None:
    first_selection = _selection(
        (_candidate(), _candidate(role=LineRole.RESISTANCE)),
    )
    first = track_selected_trendlines(first_selection, previous=None, policy=POLICY)
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    later_selection = _selection(
        (later_candidate,),
        observed_at=later_candidate.observed_at,
        input_identity=NEXT_INPUT_ID,
    )
    later = track_selected_trendlines(later_selection, previous=first, policy=POLICY)
    assert later.diagnostics.continuation_count == 1
    assert later.diagnostics.source_removed_count == 1
    assert len(later.removed_family_ids) == 1
    assert any(
        transition.transition_type is FamilyTrackingTransitionType.SOURCE_REMOVED
        for transition in later.transitions
    )

    newest = _candidate(
        observed_at=BASE + timedelta(hours=12),
        role=LineRole.RESISTANCE,
    )
    with pytest.raises(ContractValidationError, match="unsupported_removed_family_reappearance"):
        track_selected_trendlines(
            _selection(
                (newest,),
                observed_at=newest.observed_at,
                input_identity=LATEST_INPUT_ID,
            ),
            previous=later,
            policy=POLICY,
        )


def test_source_unavailable_carries_active_state_byte_for_byte() -> None:
    first = track_selected_trendlines(_selection(), previous=None, policy=POLICY)
    unavailable = _unavailable(
        observed_at=BASE + timedelta(hours=8),
        input_identity=NEXT_INPUT_ID,
    )
    carried = track_selected_trendlines(unavailable, previous=first, policy=POLICY)
    assert carried.status is TrackingStatus.SOURCE_UNAVAILABLE
    assert carried.active_families is first.active_families
    assert carried.removed_family_ids is first.removed_family_ids
    assert carried.transitions == ()
    assert carried.diagnostics.carried_forward_count == 1
    assert carried.active_families[0].version == first.active_families[0].version


def test_source_failure_also_carries_state_without_advancing_versions() -> None:
    first = track_selected_trendlines(_selection(), previous=None, policy=POLICY)
    failed = track_selected_trendlines(
        _unavailable(
            status=SelectionStatus.SOURCE_FAILED,
            observed_at=BASE + timedelta(hours=8),
            input_identity=NEXT_INPUT_ID,
        ),
        previous=first,
        policy=POLICY,
    )
    assert failed.status is TrackingStatus.SOURCE_UNAVAILABLE
    assert failed.source_selection_status is SelectionStatus.SOURCE_FAILED
    assert failed.active_families == first.active_families


@pytest.mark.parametrize(
    "selection_time",
    [BASE + timedelta(hours=4), BASE + timedelta(hours=3, minutes=30)],
)
def test_observation_time_must_increase(selection_time) -> None:
    first = track_selected_trendlines(_selection(), previous=None, policy=POLICY)
    candidate = _candidate(observed_at=selection_time)
    with pytest.raises(ContractValidationError, match="strictly increasing"):
        track_selected_trendlines(
            _selection((candidate,), observed_at=selection_time),
            previous=first,
            policy=POLICY,
        )


@pytest.mark.parametrize(
    "status",
    [SelectionStatus.SOURCE_ABSTAINED, SelectionStatus.SOURCE_FAILED],
)
def test_same_input_identity_is_rejected_for_later_source_outcomes(
    status: SelectionStatus,
) -> None:
    first = track_selected_trendlines(_selection(), previous=None, policy=POLICY)
    with pytest.raises(ContractValidationError, match="input identity must advance"):
        track_selected_trendlines(
            _unavailable(status=status, observed_at=BASE + timedelta(hours=8)),
            previous=first,
            policy=POLICY,
        )


def test_same_input_identity_is_rejected_for_later_selected_source() -> None:
    first = track_selected_trendlines(_selection(), previous=None, policy=POLICY)
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    with pytest.raises(ContractValidationError, match="input identity must advance"):
        track_selected_trendlines(
            _selection((later_candidate,), observed_at=later_candidate.observed_at),
            previous=first,
            policy=POLICY,
        )


@pytest.mark.parametrize(
    "field, value",
    [
        ("asset", "ETHUSDT"),
        ("timeframe", "1h"),
        ("discovery_config_identity", deterministic_hash("other_config", {})),
        ("provider_identity", provider_identity("other_provider", "v1")),
        ("selection_policy_identity", deterministic_hash("other_selection", {})),
    ],
)
def test_identity_drift_is_rejected(field: str, value: str) -> None:
    first = track_selected_trendlines(_selection(), previous=None, policy=POLICY)
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    selection = _selection((later_candidate,), observed_at=later_candidate.observed_at)
    previous = first
    if field == "asset":
        changed = _candidate(observed_at=BASE + timedelta(hours=8), asset=value)
        selection = _selection((changed,), observed_at=changed.observed_at)
    elif field == "timeframe":
        changed = _candidate(observed_at=BASE + timedelta(hours=8), timeframe=value)
        selection = _selection((changed,), observed_at=changed.observed_at)
    elif field == "provider_identity":
        changed = _candidate(
            observed_at=BASE + timedelta(hours=8), provider_name="other_provider"
        )
        selection = _selection((changed,), observed_at=changed.observed_at)
    elif field == "selection_policy_identity":
        selection = _selection(
            (later_candidate,),
            observed_at=later_candidate.observed_at,
            selection_policy_identity=value,
        )
    else:
        selection = replace(selection, discovery_config_identity=value)
    with pytest.raises(ContractValidationError):
        track_selected_trendlines(selection, previous=previous, policy=POLICY)


def test_input_selection_and_previous_are_not_mutated() -> None:
    selection = _selection()
    first = track_selected_trendlines(selection, previous=None, policy=POLICY)
    selection_dict = selection.to_dict()
    first_dict = first.to_dict()
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    track_selected_trendlines(
        _selection(
            (later_candidate,),
            observed_at=later_candidate.observed_at,
            input_identity=NEXT_INPUT_ID,
        ),
        previous=first,
        policy=POLICY,
    )
    assert selection.to_dict() == selection_dict
    assert first.to_dict() == first_dict


def test_input_order_does_not_change_snapshot_identity() -> None:
    candidates = (_candidate(), _candidate(role=LineRole.RESISTANCE))
    first = track_selected_trendlines(_selection(candidates), previous=None, policy=POLICY)
    reversed_selection = _selection(tuple(reversed(candidates)))
    second = track_selected_trendlines(reversed_selection, previous=None, policy=POLICY)
    assert first.snapshot_id == second.snapshot_id
    assert first.to_dict() == second.to_dict()


def test_invalid_inputs_require_explicit_contract_types() -> None:
    with pytest.raises(ContractValidationError):
        track_selected_trendlines(object(), previous=None, policy=POLICY)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError):
        track_selected_trendlines(_selection(), previous=object(), policy=POLICY)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError):
        track_selected_trendlines(_selection(), previous=None, policy=object())  # type: ignore[arg-type]


def test_near_geometry_does_not_match_exact_family() -> None:
    first = track_selected_trendlines(_selection(), previous=None, policy=POLICY)
    near = _candidate(observed_at=BASE + timedelta(hours=8), geometry_delta=2.000001)
    next_snapshot = track_selected_trendlines(
        _selection(
            (near,),
            observed_at=near.observed_at,
            input_identity=NEXT_INPUT_ID,
        ),
        previous=first,
        policy=POLICY,
    )
    assert next_snapshot.diagnostics.birth_count == 1
    assert next_snapshot.diagnostics.source_removed_count == 1


def test_pure_replay_is_deterministic() -> None:
    selection = _selection()
    left = track_selected_trendlines(selection, previous=None, policy=POLICY)
    right = track_selected_trendlines(selection, previous=None, policy=POLICY)
    assert left.snapshot_id == right.snapshot_id
    assert left.to_dict() == right.to_dict()
