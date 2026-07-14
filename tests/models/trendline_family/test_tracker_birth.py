from __future__ import annotations

from libs.models.trendline_family.contracts import FamilyLifecycleState, FamilyTransitionType
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def test_eligible_candidate_births_exact_single_member_family() -> None:
    config = tracker_config()
    observed = timestamp()
    observation = candidate(config, observed, candidate_id="birth", quality=0.80)
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(observation),)),
        config=config,
    ).update(tracker_ohlcv(observed))

    family = output.snapshot.active_families[0]
    transition = output.snapshot.transitions[0]
    assert family.lifecycle_state is FamilyLifecycleState.ACTIVE
    assert family.version == 1
    assert family.representative == observation.geometry
    assert family.members[0].candidate_id == observation.candidate_id
    assert family.members[0].anchors == observation.anchors
    assert transition.transition_type is FamilyTransitionType.BIRTH
    assert transition.previous_version is None
    assert transition.new_version == 1
    assert output.snapshot.diagnostics["birth_count"] == 1


def test_birth_threshold_rejects_candidate_and_exposes_audit_diagnostic() -> None:
    config = tracker_config(candidate={"birth_quality_threshold": 0.85})
    observed = timestamp()
    rejected = candidate(config, observed, candidate_id="below-threshold", quality=0.80)
    output = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(rejected),)),
        config=config,
    ).update(tracker_ohlcv(observed))

    assert not output.snapshot.active_families
    assert output.snapshot.diagnostics["rejected_birth_count"] == 1
    assert output.snapshot.diagnostics["rejected_birth_candidate_ids"] == ("below-threshold",)


def test_birth_quality_threshold_has_a_controlled_parameter_effect() -> None:
    observed = timestamp()
    low_threshold = tracker_config(candidate={"birth_quality_threshold": 0.70})
    high_threshold = tracker_config(candidate={"birth_quality_threshold": 0.90})
    low_candidate = candidate(low_threshold, observed, candidate_id="same-quality", quality=0.80)
    high_candidate = candidate(high_threshold, observed, candidate_id="same-quality", quality=0.80)

    admitted = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(low_candidate),)),
        config=low_threshold,
    ).update(tracker_ohlcv(observed))
    rejected = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(high_candidate),)),
        config=high_threshold,
    ).update(tracker_ohlcv(observed))

    assert len(admitted.snapshot.active_families) == 1
    assert not rejected.snapshot.active_families
