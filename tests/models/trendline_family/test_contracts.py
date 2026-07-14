from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType

import pytest

from libs.models.trendline_family.contracts import (
    AnchorRef,
    ContractValidationError,
    FamilyLifecycleState,
    FamilyRole,
    FamilyTransitionType,
    InteractionZone,
    LineCandidate,
    LineDiagnostics,
    LineGeometry,
    LineUncertainty,
    TrendlineFamilyOutput,
    canonical_json,
    deterministic_id,
)


def _candidate(timestamp, anchors, **overrides):
    payload = {
        "candidate_id": "candidate-1",
        "asset": "BTCUSDT",
        "timeframe": "4h",
        "observed_at": timestamp,
        "geometry": LineGeometry(timestamp - timedelta(hours=4), 100.0, 0.001),
        "anchors": anchors,
        "role": FamilyRole.SUPPORT,
        "method": "pathfinding",
        "provider": "native",
        "diagnostics": LineDiagnostics(0.7, 0.7, 3, 3, 0.5),
    }
    payload.update(overrides)
    return LineCandidate(**payload)


def test_line_geometry_projects_in_timestamp_space(timestamp) -> None:
    assert LineGeometry(timestamp, 100.0, 0.01).value_at(timestamp + timedelta(hours=1)) == pytest.approx(136.0)


def test_contracts_require_utc_timestamps() -> None:
    with pytest.raises(ContractValidationError, match="UTC"):
        LineGeometry(datetime(2024, 1, 1), 100.0, 0.01)
    with pytest.raises(ContractValidationError, match="UTC"):
        LineGeometry(datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=1))), 100.0, 0.01)


def test_candidate_requires_causal_unique_anchor_pair(timestamp, anchors) -> None:
    assert _candidate(timestamp, anchors).anchors == anchors
    with pytest.raises(ContractValidationError, match="at least two anchors"):
        _candidate(timestamp, (anchors[0],))
    with pytest.raises(ContractValidationError, match="unique"):
        _candidate(timestamp, (anchors[0], anchors[0]))
    future_anchor = AnchorRef("anchor-3", timestamp, 102.0, "low", timestamp + timedelta(hours=4))
    with pytest.raises(ContractValidationError, match="after observed_at"):
        _candidate(timestamp, (anchors[0], future_anchor))
    with pytest.raises(ContractValidationError, match="source_line_index"):
        _candidate(timestamp, anchors, source_line_index=-1)


def test_snapshot_output_round_trip_is_deterministic(snapshot) -> None:
    output = TrendlineFamilyOutput(snapshot, ("family-1",), (), "family-1", None, {"trendline_family_valid": True})
    assert TrendlineFamilyOutput.from_dict(output.to_dict()).to_dict() == output.to_dict()
    assert canonical_json(output.to_dict()) == canonical_json(output.to_dict())
    assert deterministic_id("candidate", {"b": 2, "a": 1}) == deterministic_id("candidate", {"a": 1, "b": 2})


def test_diagnostic_bounds_and_counter_relationships_are_enforced() -> None:
    with pytest.raises(ContractValidationError, match="normalized_quality"):
        LineDiagnostics(0.0, 1.1, 1, 1, 0.5)
    with pytest.raises(ContractValidationError, match="coverage"):
        LineDiagnostics(0.0, 0.5, 1, 1, -0.1)
    with pytest.raises(ContractValidationError, match="effective_touch_count"):
        LineDiagnostics(0.0, 0.5, 1, 2, 0.5)
    with pytest.raises(ContractValidationError, match="r_squared"):
        LineDiagnostics(0.0, 0.5, 1, 1, 0.5, r_squared=1.1)
    with pytest.raises(ContractValidationError, match="estimated_width_atr"):
        LineUncertainty(estimated_width_atr=-0.1)
    with pytest.raises(ContractValidationError, match="integer"):
        LineDiagnostics(0.0, 0.0, True, 0, 0.5)
    with pytest.raises(ContractValidationError, match="finite"):
        LineGeometry(datetime(2024, 1, 1, tzinfo=timezone.utc), math.nan, 0.0)


def test_interaction_zone_is_separate_from_exact_line(timestamp) -> None:
    zone = InteractionZone("family-1", timestamp, 100.0, 98.0, 102.0, 0.25, "atr")
    assert zone.center_price == 100.0
    assert zone.width_atr == 0.25


def test_family_representative_and_time_invariants_are_enforced(family_state, timestamp) -> None:
    with pytest.raises(ContractValidationError, match="representative_member_id"):
        replace(family_state, representative_member_id="missing")
    with pytest.raises(ContractValidationError, match="exact geometry"):
        replace(family_state, representative=LineGeometry(timestamp, 110.0, 0.001))
    with pytest.raises(ContractValidationError, match="timestamps"):
        replace(family_state, last_confirmed_at=timestamp + timedelta(hours=1))
    with pytest.raises(ContractValidationError, match="confidence"):
        replace(family_state, confidence=1.1)
    assert isinstance(family_state.members, tuple)


def test_family_member_requires_causal_unique_canonical_anchor_pair(member, timestamp) -> None:
    with pytest.raises(ContractValidationError, match="at least two canonical anchors"):
        replace(member, anchors=(member.anchors[0],))
    with pytest.raises(ContractValidationError, match="unique"):
        replace(member, anchors=(member.anchors[0], member.anchors[0]))
    with pytest.raises(ContractValidationError, match="canonical anchors"):
        replace(member, anchors=(member.anchors[0], "not-an-anchor"))
    future_anchor = AnchorRef("anchor-3", timestamp, 102.0, "low", timestamp + timedelta(hours=1))
    with pytest.raises(ContractValidationError, match="last_seen_at"):
        replace(member, anchors=(member.anchors[0], future_anchor))


def test_transition_version_invariants_are_enforced(snapshot) -> None:
    transition = snapshot.transitions[0]
    with pytest.raises(ContractValidationError, match="BIRTH transition"):
        replace(transition, new_version=2)
    with pytest.raises(ContractValidationError, match="BIRTH transition"):
        replace(transition, previous_version=1)
    with pytest.raises(ContractValidationError, match="non-BIRTH"):
        replace(transition, transition_type=FamilyTransitionType.CONTINUE, previous_version=None)
    with pytest.raises(ContractValidationError, match="non-BIRTH"):
        replace(transition, transition_type=FamilyTransitionType.CONTINUE, previous_version=1, new_version=3)


def test_snapshot_bucket_metadata_and_timestamp_invariants(snapshot, family_state, timestamp) -> None:
    dormant = replace(family_state, lifecycle_state=FamilyLifecycleState.DORMANT)
    with pytest.raises(ContractValidationError, match="active snapshot bucket"):
        replace(snapshot, active_families=(dormant,))
    late_state = replace(family_state, updated_at=timestamp + timedelta(hours=1), last_confirmed_at=timestamp + timedelta(hours=1))
    with pytest.raises(ContractValidationError, match="cannot exceed snapshot"):
        replace(snapshot, active_families=(late_state,))
    bad_transition = replace(snapshot.transitions[0], resolved_config_hash="b" * 64)
    with pytest.raises(ContractValidationError, match="transition metadata"):
        replace(snapshot, transitions=(bad_transition,))
    with pytest.raises(ContractValidationError, match="SHA-256"):
        replace(snapshot, resolved_config_hash="ABC")
    with pytest.raises(ContractValidationError, match="transition IDs"):
        replace(snapshot, transitions=(snapshot.transitions[0], snapshot.transitions[0]))
    missing_family = replace(snapshot.transitions[0], family_id="missing-family")
    with pytest.raises(ContractValidationError, match="published family"):
        replace(snapshot, transitions=(missing_family,))
    continued = replace(snapshot.transitions[0], transition_type=FamilyTransitionType.CONTINUE, previous_version=1, new_version=2)
    with pytest.raises(ContractValidationError, match="new_version"):
        replace(snapshot, transitions=(continued,))
    expiry = replace(snapshot.transitions[0], family_id="expired-family", transition_type=FamilyTransitionType.EXPIRE, previous_version=1, new_version=2)
    assert replace(snapshot, transitions=(expiry,)).transitions == (expiry,)


def test_recursive_freezing_and_malformed_payloads(snapshot) -> None:
    metadata = {"nested": {"items": [1, 2]}}
    candidate = _candidate(snapshot.timestamp, snapshot.active_families[0].members[0].anchors, metadata=metadata)
    metadata["nested"]["items"].append(3)
    assert candidate.metadata["nested"]["items"] == (1, 2)
    assert isinstance(candidate.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        candidate.metadata["another"] = 1
    with pytest.raises(ContractValidationError, match="missing required"):
        LineDiagnostics.from_dict({})
    with pytest.raises(ContractValidationError, match="LineUncertainty"):
        LineUncertainty.from_dict([])
    with pytest.raises(ContractValidationError, match="ISO-8601"):
        LineGeometry.from_dict({"reference_time": "invalid", "reference_price": 1.0, "slope_per_second": 0.0})
