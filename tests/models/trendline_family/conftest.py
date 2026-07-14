from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendline_family.contracts import (
    AnchorRef,
    FamilyLifecycleState,
    FamilyMember,
    FamilyRole,
    FamilyTransition,
    FamilyTransitionType,
    LineDiagnostics,
    LineGeometry,
    LineUncertainty,
    TrendlineFamilySnapshot,
    TrendlineFamilyState,
)


@pytest.fixture
def timestamp() -> datetime:
    return datetime(2024, 1, 1, 4, tzinfo=timezone.utc)


@pytest.fixture
def anchors(timestamp: datetime) -> tuple[AnchorRef, AnchorRef]:
    return (
        AnchorRef("anchor-1", timestamp - timedelta(hours=4), 100.0, "low", timestamp - timedelta(hours=2)),
        AnchorRef("anchor-2", timestamp - timedelta(hours=1), 101.0, "low", timestamp),
    )


@pytest.fixture
def member(timestamp: datetime, anchors: tuple[AnchorRef, AnchorRef]) -> FamilyMember:
    return FamilyMember(
        member_id="member-1",
        candidate_id="candidate-1",
        geometry=LineGeometry(timestamp - timedelta(hours=4), 100.0, 0.001),
        role=FamilyRole.SUPPORT,
        diagnostics=LineDiagnostics(0.7, 0.7, 3, 3, 0.5, r_squared=0.8),
        anchors=anchors,
        first_seen_at=timestamp,
        last_seen_at=timestamp,
    )


@pytest.fixture
def family_state(timestamp: datetime, member: FamilyMember) -> TrendlineFamilyState:
    return TrendlineFamilyState(
        family_id="family-1",
        asset="BTCUSDT",
        timeframe="4h",
        created_at=timestamp,
        updated_at=timestamp,
        last_confirmed_at=timestamp,
        age_bars=1,
        representative=member.geometry,
        representative_member_id=member.member_id,
        members=(member,),
        current_role=FamilyRole.SUPPORT,
        lifecycle_state=FamilyLifecycleState.ACTIVE,
        confidence=0.7,
        structural_importance=0.6,
        current_relevance=0.5,
        touch_count=3,
        effective_touch_count=3,
        breach_count=0,
        bars_since_touch=0,
        bars_since_match=0,
        uncertainty=LineUncertainty(),
    )


@pytest.fixture
def snapshot(timestamp: datetime, family_state: TrendlineFamilyState) -> TrendlineFamilySnapshot:
    transition = FamilyTransition(
        transition_id="transition-1",
        family_id=family_state.family_id,
        timestamp=timestamp,
        transition_type=FamilyTransitionType.BIRTH,
        previous_version=None,
        new_version=1,
        matched_candidate_ids=("candidate-1",),
        association_score=0.8,
        reason_codes=("quality_passed",),
        metrics={"quality": 0.7},
        model_version="trendline_family_v1",
        config_version="1",
        resolved_config_hash="a" * 64,
    )
    return TrendlineFamilySnapshot(
        snapshot_id="snapshot-1",
        asset="BTCUSDT",
        timeframe="4h",
        timestamp=timestamp,
        previous_snapshot_id=None,
        model_version="trendline_family_v1",
        config_version="1",
        resolved_config_hash="a" * 64,
        active_families=(family_state,),
        dormant_families=(),
        transitions=(transition,),
        diagnostics={"candidate_count": 1},
    )
