from __future__ import annotations

from libs.models.trendline_family.contracts import FamilyTransitionType
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import abstention, SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def test_small_drift_preserves_family_and_member_identity() -> None:
    config = tracker_config()
    first_time = timestamp()
    second_time = timestamp(1)
    first = candidate(config, first_time, candidate_id="first", reference_price=100.0, quality=0.70)
    second = candidate(config, second_time, candidate_id="second", reference_price=100.2, quality=0.90)
    repository = InMemoryTrendlineFamilyRepository()
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider((valid_result(first), valid_result(second))),
        config=config,
    )
    initial = tracker.update(tracker_ohlcv(first_time))
    continued = tracker.update(tracker_ohlcv(second_time))

    old_family = initial.snapshot.active_families[0]
    family = continued.snapshot.active_families[0]
    assert family.family_id == old_family.family_id
    assert family.members[0].member_id == old_family.members[0].member_id
    assert family.members[0].first_seen_at == old_family.members[0].first_seen_at
    assert family.members[0].last_seen_at == second_time
    assert family.members[0].candidate_id == "second"
    assert family.representative == second.geometry
    assert family.age_bars == 2
    assert family.version == 2
    assert family.bars_since_match == 0
    assert continued.snapshot.transitions[0].transition_type is FamilyTransitionType.STRENGTHEN


def test_large_level_or_slope_drift_births_new_family() -> None:
    config = tracker_config(lifecycle={"max_active_families_per_role": 3})
    first_time = timestamp()
    second_time = timestamp(1)
    first = candidate(config, first_time, candidate_id="first")
    far = candidate(config, second_time, candidate_id="far", reference_price=110.0)
    steep = candidate(config, second_time, candidate_id="steep", slope_per_hour=1.0)
    repository = InMemoryTrendlineFamilyRepository()
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider((valid_result(first), valid_result(far, steep))),
        config=config,
    )
    initial = tracker.update(tracker_ohlcv(first_time))
    changed = tracker.update(tracker_ohlcv(second_time))

    assert initial.snapshot.active_families[0].family_id not in {
        family.family_id for family in changed.snapshot.active_families if family.bars_since_match == 0
    }
    assert changed.snapshot.diagnostics["birth_count"] == 2
    assert changed.snapshot.diagnostics["matched_count"] == 0


def test_matched_continuation_resets_projection_horizon_without_creating_touch_evidence() -> None:
    config = tracker_config()
    first_time = timestamp()
    second_time = timestamp(1)
    third_time = timestamp(2)
    first = candidate(config, first_time, candidate_id="first")
    continued = candidate(config, third_time, candidate_id="continued")
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(first), abstention(), valid_result(continued))),
        config=config,
    )

    tracker.update(tracker_ohlcv(first_time))
    unmatched = tracker.update(tracker_ohlcv(second_time))
    matched = tracker.update(tracker_ohlcv(third_time))

    assert unmatched.snapshot.active_families[0].uncertainty.projection_horizon_bars == 1
    family = matched.snapshot.active_families[0]
    assert family.uncertainty.projection_horizon_bars == 0
    assert family.bars_since_touch == 0
