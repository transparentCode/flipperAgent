from __future__ import annotations

from libs.models.trendline_family.contracts import FamilyLifecycleState, FamilyTransitionType
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import SequenceProvider, abstention, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def test_dormant_family_reactivates_only_above_reactivation_score() -> None:
    config = tracker_config(lifecycle={"reactivation_min_score": 0.80})
    times = tuple(timestamp(offset) for offset in range(6))
    first = candidate(config, times[0], candidate_id="first", quality=0.80)
    low_score = candidate(config, times[4], candidate_id="low-score", reference_price=100.7, anchor_prefix="other")
    strong = candidate(config, times[5], candidate_id="strong", reference_price=100.0, anchor_prefix="support")
    repository = InMemoryTrendlineFamilyRepository()
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider(
            (valid_result(first), abstention(), abstention(), abstention(), valid_result(low_score), valid_result(strong))
        ),
        config=config,
    )
    initial = tracker.update(tracker_ohlcv(times[0]))
    tracker.update(tracker_ohlcv(times[1]))
    tracker.update(tracker_ohlcv(times[2]))
    dormant = tracker.update(tracker_ohlcv(times[3]))
    still_dormant = tracker.update(tracker_ohlcv(times[4]))
    reactivated = tracker.update(tracker_ohlcv(times[5]))

    family_id = initial.snapshot.active_families[0].family_id
    member_id = initial.snapshot.active_families[0].members[0].member_id
    assert dormant.snapshot.dormant_families[0].lifecycle_state is FamilyLifecycleState.DORMANT
    assert still_dormant.snapshot.dormant_families[0].family_id == family_id
    assert still_dormant.snapshot.diagnostics["matched_count"] == 0
    family = next(family for family in reactivated.snapshot.active_families if family.family_id == family_id)
    assert family.family_id == family_id
    assert family.members[0].member_id == member_id
    assert family.lifecycle_state is FamilyLifecycleState.ACTIVE
    assert family.bars_since_match == 0
    assert family.bars_since_touch == 0
    assert family.uncertainty.projection_horizon_bars == 0
    transition = next(transition for transition in reactivated.snapshot.transitions if transition.family_id == family_id)
    assert transition.transition_type is FamilyTransitionType.REACTIVATE
