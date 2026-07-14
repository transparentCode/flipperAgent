from __future__ import annotations

from libs.models.trendline_family.contracts import FamilyLifecycleState, FamilyTransitionType
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def _capped_output():
    config = tracker_config(lifecycle={"max_active_families_per_role": 1})
    observed = timestamp()
    first = candidate(config, observed, candidate_id="candidate-a", quality=0.80, anchor_prefix="a")
    second = candidate(config, observed, candidate_id="candidate-b", quality=0.80, anchor_prefix="b")
    return TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(second, first),)),
        config=config,
    ).update(tracker_ohlcv(observed))


def test_active_family_cap_is_deterministic_and_rejections_are_auditable() -> None:
    first = _capped_output()
    second = _capped_output()

    assert len(first.snapshot.active_families) == 1
    assert first.snapshot.active_families[0].lifecycle_state is FamilyLifecycleState.ACTIVE
    assert first.snapshot.diagnostics["birth_count"] == 1
    assert first.snapshot.diagnostics["rejected_birth_count"] == 1
    assert first.snapshot.diagnostics["family_churn_count"] == 1
    assert first.snapshot.diagnostics["family_churn_rate"] == 1.0
    assert 0.0 <= first.snapshot.diagnostics["family_churn_rate"] <= 1.0
    assert first.snapshot.to_dict() == second.snapshot.to_dict()


def test_existing_family_demoted_by_cap_emits_only_final_dormant_transition() -> None:
    config = tracker_config(lifecycle={"max_active_families_per_role": 2})
    first_time = timestamp()
    second_time = timestamp(1)
    initial_one = candidate(config, first_time, candidate_id="one", quality=0.90, anchor_prefix="one")
    initial_two = candidate(config, first_time, candidate_id="two", quality=0.70, anchor_prefix="two")
    replacement = candidate(
        config,
        second_time,
        candidate_id="replacement",
        reference_price=110.0,
        quality=0.95,
        anchor_prefix="replacement",
    )
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(initial_one, initial_two), valid_result(replacement))),
        config=config,
    )
    tracker.update(tracker_ohlcv(first_time))
    output = tracker.update(tracker_ohlcv(second_time))

    transitions = output.snapshot.transitions
    assert len({transition.family_id for transition in transitions}) == len(transitions)
    assert sum(transition.transition_type is FamilyTransitionType.DORMANT for transition in transitions) == 1
    assert output.snapshot.dormant_families[0].uncertainty.projection_horizon_bars == 1
    assert output.snapshot.dormant_families[0].bars_since_touch == 0
