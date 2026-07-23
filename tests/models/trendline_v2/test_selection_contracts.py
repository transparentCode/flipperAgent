from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendline_v2.domain import (
    AbstentionReason,
    AnchorRef,
    CandidateEvidence,
    DiscoverySnapshot,
    DiscoveryStatus,
    LineCandidate,
    LineGeometry,
    LineRole,
)
from libs.models.trendline_v2.domain.identity import deterministic_hash, provider_identity
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.selection import (
    CandidateSelectionDecision,
    CandidateSelectionSnapshot,
    LatestValidPredecessorPolicy,
    SelectionDiagnostics,
    SelectionStatus,
    candidate_set_identity,
)


UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)
PROVIDER_ID = provider_identity("confirmed_extrema_pair", "v1")


def _hash(value: str) -> str:
    return deterministic_hash("trendline_v2_selection_test", value)


def _anchor(name: str, offset: int, price: float) -> AnchorRef:
    pivot = BASE + timedelta(hours=offset)
    return AnchorRef(
        anchor_id=_hash(f"anchor:{name}"),
        pivot_time=pivot,
        confirmation_time=pivot + timedelta(hours=1),
        price=price,
    )


def _candidate(
    name: str,
    *,
    role: LineRole = LineRole.SUPPORT,
    first_offset: int = 1,
    second_offset: int = 10,
    second_name: str = "second",
    second_price: float = 100.0,
    provider_name: str = "confirmed_extrema_pair",
    provider_version: str = "v1",
    extra_anchor: bool = False,
) -> LineCandidate:
    first = _anchor(f"{name}:first", first_offset, 90.0)
    second = _anchor(f"{second_name}:second", second_offset, second_price)
    anchors = (first, second)
    if extra_anchor:
        anchors = (first, _anchor(f"{name}:middle", 5, 95.0), second)
    geometry = LineGeometry(
        start_time=anchors[0].pivot_time,
        end_time=anchors[-1].pivot_time,
        start_price=anchors[0].price,
        end_price=anchors[-1].price,
    )
    evidence = CandidateEvidence(
        anchor_count=len(anchors),
        distinct_anchor_timestamps=len({anchor.pivot_time for anchor in anchors}),
        anchor_span_seconds=(anchors[-1].pivot_time - anchors[0].pivot_time).total_seconds(),
    )
    return LineCandidate.create(
        asset="BTCUSDT",
        timeframe="4h",
        role=role,
        geometry=geometry,
        anchors=anchors,
        evidence=evidence,
        observed_at=BASE + timedelta(hours=20),
        provider_name=provider_name,
        provider_version=provider_version,
    )


def _snapshot(
    candidates: tuple[LineCandidate, ...] = (),
    *,
    status: DiscoveryStatus = DiscoveryStatus.VALID,
    reason: AbstentionReason | None = None,
    provider_id: str = PROVIDER_ID,
) -> DiscoverySnapshot:
    return DiscoverySnapshot(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=BASE + timedelta(hours=20),
        input_identity=_hash("input"),
        config_identity=_hash("config"),
        provider_identity=provider_id,
        status=status,
        candidates=tuple(sorted(candidates, key=lambda item: (item.role.value, item.candidate_id))),
        reason=reason,
    )


def test_policy_payload_and_identity_are_exact() -> None:
    policy = LatestValidPredecessorPolicy()

    assert policy.to_dict() == {
        "policy_name": "latest_valid_predecessor",
        "policy_version": "v1",
        "research_family_id": "latest_valid_predecessor_v1",
        "supported_provider": {"name": "confirmed_extrema_pair", "version": "v1"},
        "required_anchor_count": 2,
        "grouping_key": ["role", "second_anchor_id"],
        "primary_order": "maximum_first_anchor_pivot_time",
        "tie_break_order": ["first_anchor_id", "candidate_id"],
        "output_cardinality": "one_per_nonempty_group",
    }
    assert policy.policy_identity == (
        "3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc"
    )
    assert policy.supported_provider_identity == PROVIDER_ID
    assert LatestValidPredecessorPolicy.from_dict(policy.to_dict()) == policy


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_name", "other"),
        ("policy_version", "v2"),
        ("research_family_id", "other_v1"),
        ("supported_provider_name", "other"),
        ("required_anchor_count", 3),
        ("primary_order", "minimum_first_anchor_pivot_time"),
        ("output_cardinality", "all"),
    ],
)
def test_policy_rejects_semantic_deviations(field: str, value: object) -> None:
    with pytest.raises(ContractValidationError):
        replace(LatestValidPredecessorPolicy(), **{field: value})


def test_decision_identity_is_deterministic_and_strict() -> None:
    candidate = _candidate("one")
    decision = CandidateSelectionDecision.create(
        role=candidate.role,
        second_anchor_id=candidate.anchors[1].anchor_id,
        second_anchor_time=candidate.anchors[1].pivot_time,
        considered_candidate_ids=(candidate.candidate_id,),
        selected_candidate_id=candidate.candidate_id,
        selected_first_anchor_id=candidate.anchors[0].anchor_id,
        selected_first_anchor_time=candidate.anchors[0].pivot_time,
        latest_timestamp_tie_count=1,
        selection_policy_identity=LatestValidPredecessorPolicy().policy_identity,
    )

    assert decision.decision_id == decision.expected_decision_id
    assert CandidateSelectionDecision.from_dict(decision.to_dict()) == decision
    with pytest.raises(ContractValidationError):
        replace(decision, considered_candidate_ids=(candidate.candidate_id, candidate.candidate_id))
    with pytest.raises(ContractValidationError):
        replace(decision, selected_candidate_id=_hash("not-considered"))


def test_diagnostics_enforce_exact_arithmetic() -> None:
    diagnostics = SelectionDiagnostics(5, 2, 2, 3, 1, 1, 0)
    assert diagnostics.to_dict()["rejected_candidate_count"] == 3
    with pytest.raises(ContractValidationError):
        SelectionDiagnostics(5, 2, 2, 2, 1, 1, 0)
    with pytest.raises(ContractValidationError):
        SelectionDiagnostics(5, 2, 2, 3, 2, 1, 0)


def test_source_outcome_snapshot_contract_is_empty_and_reasoned() -> None:
    policy = LatestValidPredecessorPolicy()
    source = _snapshot(
        status=DiscoveryStatus.ABSTAINED,
        reason=AbstentionReason.NO_CANDIDATES,
    )
    selection = CandidateSelectionSnapshot(
        asset=source.asset,
        timeframe=source.timeframe,
        observed_at=source.observed_at,
        source_snapshot_id=source.snapshot_id,
        input_identity=source.input_identity,
        discovery_config_identity=source.config_identity,
        provider_identity=source.provider_identity,
        selection_policy_identity=policy.policy_identity,
        status=SelectionStatus.SOURCE_ABSTAINED,
        source_reason=source.reason,
        source_candidate_set_identity=candidate_set_identity(()),
        selected_candidates=(),
        decisions=(),
        diagnostics=SelectionDiagnostics(0, 0, 0, 0, 0, 0, 0),
    )
    assert CandidateSelectionSnapshot.from_dict(selection.to_dict()) == selection
    with pytest.raises(ContractValidationError):
        replace(selection, source_reason=None)
    with pytest.raises(ContractValidationError):
        replace(selection, status=SelectionStatus.SOURCE_FAILED)


def test_selected_snapshot_round_trip_and_identity_changes() -> None:
    candidate = _candidate("one")
    policy = LatestValidPredecessorPolicy()
    decision = CandidateSelectionDecision.create(
        role=candidate.role,
        second_anchor_id=candidate.anchors[1].anchor_id,
        second_anchor_time=candidate.anchors[1].pivot_time,
        considered_candidate_ids=(candidate.candidate_id,),
        selected_candidate_id=candidate.candidate_id,
        selected_first_anchor_id=candidate.anchors[0].anchor_id,
        selected_first_anchor_time=candidate.anchors[0].pivot_time,
        latest_timestamp_tie_count=1,
        selection_policy_identity=policy.policy_identity,
    )
    snapshot = CandidateSelectionSnapshot(
        asset=candidate.asset,
        timeframe=candidate.timeframe,
        observed_at=candidate.observed_at,
        source_snapshot_id=_hash("source-snapshot"),
        input_identity=_hash("input"),
        discovery_config_identity=_hash("config"),
        provider_identity=PROVIDER_ID,
        selection_policy_identity=policy.policy_identity,
        status=SelectionStatus.SELECTED,
        source_reason=None,
        source_candidate_set_identity=candidate_set_identity((candidate.candidate_id,)),
        selected_candidates=(candidate,),
        decisions=(decision,),
        diagnostics=SelectionDiagnostics(1, 1, 1, 0, 1, 0, 0),
    )

    assert CandidateSelectionSnapshot.from_dict(snapshot.to_dict()) == snapshot
    assert replace(snapshot, source_snapshot_id=_hash("other-source")).snapshot_id != snapshot.snapshot_id
    other_policy_identity = _hash("other-policy")
    with pytest.raises(ContractValidationError, match="decision policy identity"):
        replace(snapshot, selection_policy_identity=other_policy_identity)
    rebound_decision = CandidateSelectionDecision.create(
        role=candidate.role,
        second_anchor_id=candidate.anchors[1].anchor_id,
        second_anchor_time=candidate.anchors[1].pivot_time,
        considered_candidate_ids=(candidate.candidate_id,),
        selected_candidate_id=candidate.candidate_id,
        selected_first_anchor_id=candidate.anchors[0].anchor_id,
        selected_first_anchor_time=candidate.anchors[0].pivot_time,
        latest_timestamp_tie_count=1,
        selection_policy_identity=other_policy_identity,
    )
    rebound = replace(
        snapshot,
        selection_policy_identity=other_policy_identity,
        decisions=(rebound_decision,),
    )
    assert rebound.snapshot_id != snapshot.snapshot_id
    assert rebound.selection_policy_identity == other_policy_identity
    assert rebound.decisions[0].selection_policy_identity == other_policy_identity
    with pytest.raises(ContractValidationError, match="tie-group"):
        replace(
            snapshot,
            diagnostics=SelectionDiagnostics(1, 1, 1, 0, 1, 0, 1),
        )
    with pytest.raises(ContractValidationError):
        replace(snapshot, source_candidate_set_identity=candidate_set_identity((_hash("missing"),)))


def _manual_selected_snapshot(
    candidates: tuple[LineCandidate, ...],
    *,
    policy: LatestValidPredecessorPolicy | None = None,
) -> CandidateSelectionSnapshot:
    active_policy = policy or LatestValidPredecessorPolicy()
    ordered = tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.role.value,
                candidate.anchors[1].pivot_time,
                candidate.anchors[1].anchor_id,
                candidate.candidate_id,
            ),
        )
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
            selection_policy_identity=active_policy.policy_identity,
        )
        for candidate in ordered
    )
    support_count = sum(candidate.role is LineRole.SUPPORT for candidate in ordered)
    resistance_count = sum(candidate.role is LineRole.RESISTANCE for candidate in ordered)
    return CandidateSelectionSnapshot(
        asset=ordered[0].asset,
        timeframe=ordered[0].timeframe,
        observed_at=ordered[0].observed_at,
        source_snapshot_id=_hash("manual-source"),
        input_identity=_hash("manual-input"),
        discovery_config_identity=_hash("manual-config"),
        provider_identity=PROVIDER_ID,
        selection_policy_identity=active_policy.policy_identity,
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
            support_selected_count=support_count,
            resistance_selected_count=resistance_count,
            latest_timestamp_tie_group_count=0,
        ),
    )


def test_snapshot_rejects_duplicate_role_and_second_anchor_group() -> None:
    first = _candidate("duplicate-first", first_offset=1)
    second = _candidate("duplicate-second", first_offset=2)

    with pytest.raises(ContractValidationError, match="unique role/second-anchor"):
        _manual_selected_snapshot((first, second))


def test_snapshot_allows_same_second_anchor_across_roles() -> None:
    support = _candidate("same-second-support", role=LineRole.SUPPORT)
    resistance = _candidate("same-second-resistance", role=LineRole.RESISTANCE)

    snapshot = _manual_selected_snapshot((support, resistance))

    assert snapshot.diagnostics.source_group_count == 2
    assert tuple(
        (decision.role, decision.second_anchor_id)
        for decision in snapshot.decisions
    ) == tuple(
        (candidate.role, candidate.anchors[1].anchor_id)
        for candidate in snapshot.selected_candidates
    )


def test_snapshot_allows_same_role_across_second_anchors() -> None:
    first = _candidate("different-second-first")
    second = _candidate(
        "different-second-second",
        second_name="other-second",
    )

    snapshot = _manual_selected_snapshot((first, second))

    assert snapshot.diagnostics.source_group_count == len(snapshot.decisions) == 2
    assert len({
        (decision.role, decision.second_anchor_id)
        for decision in snapshot.decisions
    }) == 2


def test_snapshot_deserialization_rejects_duplicate_group() -> None:
    support = _candidate("deserialize-support", role=LineRole.SUPPORT)
    resistance = _candidate("deserialize-resistance", role=LineRole.RESISTANCE)
    valid = _manual_selected_snapshot((support, resistance))
    payload = valid.to_dict()
    original = valid.decisions[0]
    forged = CandidateSelectionDecision.create(
        role=LineRole.SUPPORT,
        second_anchor_id=original.second_anchor_id,
        second_anchor_time=original.second_anchor_time,
        considered_candidate_ids=original.considered_candidate_ids,
        selected_candidate_id=original.selected_candidate_id,
        selected_first_anchor_id=original.selected_first_anchor_id,
        selected_first_anchor_time=original.selected_first_anchor_time,
        latest_timestamp_tie_count=original.latest_timestamp_tie_count,
        selection_policy_identity=original.selection_policy_identity,
    )
    payload["decisions"][0] = forged.to_dict()

    with pytest.raises(ContractValidationError, match="invalid selection snapshot payload"):
        CandidateSelectionSnapshot.from_dict(payload)


def test_snapshot_rejects_zero_tie_diagnostic_for_tied_decision() -> None:
    first = _candidate("tie-a", first_offset=5)
    second = _candidate("tie-b", first_offset=5)
    policy = LatestValidPredecessorPolicy()
    decision = CandidateSelectionDecision.create(
        role=first.role,
        second_anchor_id=first.anchors[1].anchor_id,
        second_anchor_time=first.anchors[1].pivot_time,
        considered_candidate_ids=tuple(sorted((first.candidate_id, second.candidate_id))),
        selected_candidate_id=first.candidate_id,
        selected_first_anchor_id=first.anchors[0].anchor_id,
        selected_first_anchor_time=first.anchors[0].pivot_time,
        latest_timestamp_tie_count=2,
        selection_policy_identity=policy.policy_identity,
    )
    kwargs = {
        "asset": first.asset,
        "timeframe": first.timeframe,
        "observed_at": first.observed_at,
        "source_snapshot_id": _hash("source"),
        "input_identity": _hash("input"),
        "discovery_config_identity": _hash("config"),
        "provider_identity": PROVIDER_ID,
        "selection_policy_identity": policy.policy_identity,
        "status": SelectionStatus.SELECTED,
        "source_reason": None,
        "source_candidate_set_identity": candidate_set_identity(
            (first.candidate_id, second.candidate_id)
        ),
        "selected_candidates": (first,),
        "decisions": (decision,),
    }
    with pytest.raises(ContractValidationError, match="tie-group"):
        CandidateSelectionSnapshot(
            **kwargs,
            diagnostics=SelectionDiagnostics(2, 1, 1, 1, 1, 0, 0),
        )
    valid = CandidateSelectionSnapshot(
        **kwargs,
        diagnostics=SelectionDiagnostics(2, 1, 1, 1, 1, 0, 1),
    )
    assert valid.diagnostics.latest_timestamp_tie_group_count == 1


def test_snapshot_rejects_overlapping_decision_partitions() -> None:
    first = _candidate("first")
    second = _candidate("second", first_offset=2)
    policy = LatestValidPredecessorPolicy()
    first_decision = CandidateSelectionDecision.create(
        role=first.role,
        second_anchor_id=first.anchors[1].anchor_id,
        second_anchor_time=first.anchors[1].pivot_time,
        considered_candidate_ids=(first.candidate_id, second.candidate_id),
        selected_candidate_id=first.candidate_id,
        selected_first_anchor_id=first.anchors[0].anchor_id,
        selected_first_anchor_time=first.anchors[0].pivot_time,
        latest_timestamp_tie_count=1,
        selection_policy_identity=policy.policy_identity,
    )
    object.__setattr__(
        first_decision,
        "considered_candidate_ids",
        (first.candidate_id, second.candidate_id, second.candidate_id),
    )
    with pytest.raises(ContractValidationError):
        CandidateSelectionSnapshot(
            asset="BTCUSDT",
            timeframe="4h",
            observed_at=first.observed_at,
            source_snapshot_id=_hash("source"),
            input_identity=_hash("input"),
            discovery_config_identity=_hash("config"),
            provider_identity=PROVIDER_ID,
            selection_policy_identity=policy.policy_identity,
            status=SelectionStatus.SELECTED,
            source_reason=None,
            source_candidate_set_identity=candidate_set_identity(
                (first.candidate_id, second.candidate_id)
            ),
            selected_candidates=(first,),
            decisions=(first_decision,),
            diagnostics=SelectionDiagnostics(3, 1, 1, 2, 1, 0, 0),
        )
