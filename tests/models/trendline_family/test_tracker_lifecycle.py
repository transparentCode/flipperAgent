from __future__ import annotations

from dataclasses import replace

import pytest

from libs.models.trendline_family.contracts import ContractValidationError, FamilyLifecycleState, FamilyTransitionType
from libs.models.trendline_family.provider import CandidateGenerationStatus
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker, TrendlineFamilyUpdateError

from .tracker_support import SequenceProvider, abstention, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def test_unmatched_lifecycle_obeys_exact_grace_decay_dormant_and_expiry_boundaries() -> None:
    config = tracker_config()
    times = tuple(timestamp(offset) for offset in range(6))
    provider = SequenceProvider((valid_result(candidate(config, times[0])),) + tuple(abstention() for _ in times[1:]))
    tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=provider,
        config=config,
    )
    outputs = [tracker.update(tracker_ohlcv(current)) for current in times]

    grace = outputs[1].snapshot.active_families[0]
    decayed = outputs[2].snapshot.active_families[0]
    dormant = outputs[3].snapshot.dormant_families[0]
    dormant_decayed = outputs[4].snapshot.dormant_families[0]
    assert grace.bars_since_match == 1
    assert grace.confidence == pytest.approx(0.80)
    assert grace.uncertainty.projection_horizon_bars == 1
    assert grace.bars_since_touch == 0
    assert outputs[1].snapshot.transitions[0].transition_type is FamilyTransitionType.WEAKEN
    assert decayed.bars_since_match == 2
    assert decayed.confidence == pytest.approx(0.70)
    assert decayed.uncertainty.projection_horizon_bars == 2
    assert decayed.bars_since_touch == 0
    assert dormant.bars_since_match == 3
    assert dormant.lifecycle_state is FamilyLifecycleState.DORMANT
    assert dormant.confidence == pytest.approx(0.60)
    assert dormant.uncertainty.projection_horizon_bars == 3
    assert dormant.bars_since_touch == 0
    assert outputs[3].snapshot.transitions[0].transition_type is FamilyTransitionType.DORMANT
    assert dormant_decayed.bars_since_match == 4
    assert dormant_decayed.confidence == pytest.approx(0.50)
    assert dormant_decayed.uncertainty.projection_horizon_bars == 4
    assert dormant_decayed.bars_since_touch == 0
    assert outputs[4].snapshot.transitions[0].transition_type is FamilyTransitionType.WEAKEN
    assert not outputs[5].snapshot.active_families
    assert not outputs[5].snapshot.dormant_families
    assert outputs[5].snapshot.transitions[0].transition_type is FamilyTransitionType.EXPIRE
    assert outputs[5].snapshot.transitions[0].new_version == 6


def test_normal_abstention_advances_lifecycle_but_provider_config_error_preserves_head() -> None:
    config = tracker_config()
    first_time = timestamp()
    second_time = timestamp(1)
    third_time = timestamp(2)
    repository = InMemoryTrendlineFamilyRepository()
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider(
            (
                valid_result(candidate(config, first_time)),
                abstention(CandidateGenerationStatus.NO_VALID_FITTED_PATHS),
                abstention(CandidateGenerationStatus.PROVIDER_CONFIG_ERROR),
            )
        ),
        config=config,
    )
    initial = tracker.update(tracker_ohlcv(first_time))
    abstained = tracker.update(tracker_ohlcv(second_time))
    before_error = repository.latest_snapshot(config.asset, config.timeframe)

    assert abstained.snapshot.active_families[0].bars_since_match == 1
    assert initial.snapshot.snapshot_id == before_error.previous_snapshot_id
    with pytest.raises(TrendlineFamilyUpdateError, match="failed closed"):
        tracker.update(tracker_ohlcv(third_time))

    assert repository.latest_snapshot(config.asset, config.timeframe) == before_error


def test_mismatched_candidate_config_identity_fails_closed_before_birth() -> None:
    config = tracker_config()
    mismatched = tracker_config(matching={"normalization_atr_window": 1})
    observed = timestamp()
    repository = InMemoryTrendlineFamilyRepository()
    tracker = TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider((valid_result(candidate(mismatched, observed)),)),
        config=config,
    )

    with pytest.raises(TrendlineFamilyUpdateError, match="config identity"):
        tracker.update(tracker_ohlcv(observed))

    assert repository.latest_snapshot(config.asset, config.timeframe) is None


@pytest.mark.parametrize(
    "lifecycle",
    (
        {"active_grace_bars": 3, "dormant_after_bars": 3, "expire_after_bars": 5},
        {"active_grace_bars": 1, "dormant_after_bars": 3, "expire_after_bars": 3},
    ),
)
def test_lifecycle_horizons_must_be_strictly_ordered(lifecycle: dict[str, int]) -> None:
    with pytest.raises(ContractValidationError, match="strictly ordered"):
        tracker_config(lifecycle=lifecycle)


class _SeededRepository:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.saved = []

    def latest_snapshot(self, asset: str, timeframe: str):
        assert (asset, timeframe) == (self.snapshot.asset, self.snapshot.timeframe)
        return self.snapshot

    def save_snapshot(self, snapshot) -> None:
        self.snapshot = snapshot
        self.saved.append(snapshot)


def test_dormant_family_at_expiry_is_not_eligible_for_reactivation() -> None:
    config = tracker_config()
    times = tuple(timestamp(offset) for offset in range(6))
    source = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider((valid_result(candidate(config, times[0])),) + tuple(abstention() for _ in times[1:5])),
        config=config,
    )
    outputs = [source.update(tracker_ohlcv(current)) for current in times[:5]]
    prior = outputs[-1].snapshot
    expired_dormant = replace(
        prior.dormant_families[0],
        bars_since_match=config.lifecycle.expire_after_bars,
    )
    seeded_snapshot = replace(prior)
    object.__setattr__(seeded_snapshot, "dormant_families", (expired_dormant,))
    seeded = _SeededRepository(seeded_snapshot)
    tracker = TrendlineFamilyTracker(
        repository=seeded,
        provider=SequenceProvider((valid_result(candidate(config, times[5], candidate_id="replacement")),)),
        config=config,
    )

    output = tracker.update(tracker_ohlcv(times[5]))

    assert expired_dormant.family_id not in {
        family.family_id for family in output.snapshot.active_families + output.snapshot.dormant_families
    }
    assert any(
        transition.family_id == expired_dormant.family_id
        and transition.transition_type is FamilyTransitionType.EXPIRE
        for transition in output.snapshot.transitions
    )
    assert all(transition.transition_type is not FamilyTransitionType.REACTIVATE for transition in output.snapshot.transitions)
