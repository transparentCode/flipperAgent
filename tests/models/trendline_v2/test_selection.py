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
    LatestValidPredecessorPolicy,
    SelectionStatus,
    select_latest_valid_predecessors,
)


UTC = timezone.utc
BASE = datetime(2026, 2, 1, tzinfo=UTC)
POLICY = LatestValidPredecessorPolicy()
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
    second_override: AnchorRef | None = None,
    extra_anchor: bool = False,
) -> LineCandidate:
    first = _anchor(f"{name}:first", first_offset, 90.0)
    second = second_override or _anchor(f"{second_name}:second", second_offset, second_price)
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
    candidates: tuple[LineCandidate, ...],
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


def test_selects_one_latest_candidate_per_role_and_second_anchor() -> None:
    support_old = _candidate("support-old", first_offset=1)
    support_latest = _candidate("support-latest", first_offset=6)
    resistance = _candidate("resistance", role=LineRole.RESISTANCE, second_name="resistance-second")
    separate_second = _candidate("separate", second_name="other-second")

    result = select_latest_valid_predecessors(
        _snapshot((support_old, support_latest, resistance, separate_second)),
        policy=POLICY,
    )

    assert result.status is SelectionStatus.SELECTED
    assert result.diagnostics.source_candidate_count == 4
    assert result.diagnostics.source_group_count == 3
    assert result.diagnostics.selected_candidate_count == 3
    assert support_latest.candidate_id in {
        candidate.candidate_id for candidate in result.selected_candidates
    }
    assert support_old.candidate_id not in {
        candidate.candidate_id for candidate in result.selected_candidates
    }
    assert {candidate.role for candidate in result.selected_candidates} == {
        LineRole.SUPPORT,
        LineRole.RESISTANCE,
    }
    assert sum(len(decision.considered_candidate_ids) for decision in result.decisions) == 4


def test_tie_uses_first_anchor_then_candidate_id() -> None:
    first = _candidate("tie-a", first_offset=5)
    second = _candidate("tie-b", first_offset=5)
    result = select_latest_valid_predecessors(_snapshot((first, second)), policy=POLICY)

    expected = min(
        (first, second),
        key=lambda candidate: (candidate.anchors[0].anchor_id, candidate.candidate_id),
    )
    assert result.selected_candidates == (expected,)
    assert result.decisions[0].latest_timestamp_tie_count == 2
    assert result.diagnostics.latest_timestamp_tie_group_count == 1


def test_input_order_and_source_snapshot_replay_do_not_change_selection() -> None:
    candidates = (
        _candidate("a", first_offset=1),
        _candidate("b", first_offset=6),
        _candidate("c", second_name="other", first_offset=2),
    )
    first = select_latest_valid_predecessors(_snapshot(candidates), policy=POLICY)
    second = select_latest_valid_predecessors(
        _snapshot(tuple(reversed(candidates))),
        policy=POLICY,
    )
    assert first.to_dict() == second.to_dict()
    assert tuple(candidate.candidate_id for candidate in first.selected_candidates) == tuple(
        candidate.candidate_id for candidate in second.selected_candidates
    )


@pytest.mark.parametrize("status,reason,expected", [
    (DiscoveryStatus.ABSTAINED, AbstentionReason.NO_CANDIDATES, SelectionStatus.SOURCE_ABSTAINED),
    (DiscoveryStatus.FAILED, AbstentionReason.PROVIDER_FAILURE, SelectionStatus.SOURCE_FAILED),
])
def test_source_status_and_reason_pass_through(
    status: DiscoveryStatus,
    reason: AbstentionReason,
    expected: SelectionStatus,
) -> None:
    result = select_latest_valid_predecessors(
        _snapshot((), status=status, reason=reason),
        policy=POLICY,
    )
    assert result.status is expected
    assert result.source_reason is reason
    assert not result.selected_candidates
    assert not result.decisions
    assert result.diagnostics.source_candidate_count == 0


def test_exact_two_anchor_requirement_is_enforced() -> None:
    with pytest.raises(ContractValidationError, match="exactly two"):
        select_latest_valid_predecessors(
            _snapshot((_candidate("three", extra_anchor=True),)),
            policy=POLICY,
        )


def test_unsupported_provider_is_rejected() -> None:
    other = _candidate("other", provider_name="other_provider", provider_version="v1")
    other_identity = provider_identity("other_provider", "v1")
    with pytest.raises(ContractValidationError, match="unsupported"):
        select_latest_valid_predecessors(
            _snapshot((other,), provider_id=other_identity),
            policy=POLICY,
        )


def test_inconsistent_second_anchor_representation_is_rejected() -> None:
    shared_id = _anchor("shared:second", 10, 100.0)
    changed = _anchor("shared:second", 10, 101.0)
    first = _candidate("first", second_override=shared_id)
    second = _candidate("second", first_offset=2, second_override=changed)
    with pytest.raises(ContractValidationError, match="second-anchor"):
        select_latest_valid_predecessors(_snapshot((first, second)), policy=POLICY)


def test_selector_does_not_mutate_source_or_candidate_objects() -> None:
    source_candidates = (_candidate("one"), _candidate("two", first_offset=4))
    source = _snapshot(source_candidates)
    before = source.to_dict()
    result = select_latest_valid_predecessors(source, policy=POLICY)

    assert source.to_dict() == before
    assert result.selected_candidates[0] in source.candidates
    assert result.snapshot_id == result.snapshot_id


def test_selector_rejects_invalid_input_types_and_no_implicit_policy() -> None:
    with pytest.raises(ContractValidationError):
        select_latest_valid_predecessors(object(), policy=POLICY)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError):
        select_latest_valid_predecessors(_snapshot((_candidate("one"),)), policy=object())  # type: ignore[arg-type]


def test_policy_identity_is_not_derived_from_research_fields() -> None:
    candidate = _candidate("one")
    source = _snapshot((candidate,))
    result = select_latest_valid_predecessors(source, policy=POLICY)
    assert "candidate_structure_id" not in result.to_dict()
    assert "quality" not in result.to_dict()
    assert "future" not in result.to_dict()


def test_selected_snapshot_rejects_decision_candidate_mismatch() -> None:
    result = select_latest_valid_predecessors(_snapshot((_candidate("one"),)), policy=POLICY)
    bad_decision = replace(result.decisions[0])
    object.__setattr__(bad_decision, "selected_first_anchor_id", _hash("other-anchor"))
    with pytest.raises(ContractValidationError, match="decision anchor fields"):
        replace(result, decisions=(bad_decision,))
