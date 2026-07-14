from __future__ import annotations

from libs.models.trendline_family.contracts import FamilyRole
from libs.models.trendline_family.matching import (
    calculate_normalization_atr,
    greedy_match_candidates,
    score_family_candidate,
)
from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository
from libs.models.trendline_family.tracker import TrendlineFamilyTracker

from .tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def _born_family():
    config = tracker_config()
    observed = timestamp()
    initial = candidate(config, observed, candidate_id="first")
    repository = InMemoryTrendlineFamilyRepository()
    TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider((valid_result(initial),)),
        config=config,
    ).update(tracker_ohlcv(observed))
    snapshot = repository.latest_snapshot(config.asset, config.timeframe)
    assert snapshot is not None
    return config, snapshot.active_families[0], observed


def test_role_mismatch_never_matches() -> None:
    config, family, observed = _born_family()
    later = observed + (timestamp(1) - timestamp())
    candidate_observation = candidate(
        config,
        later,
        candidate_id="resistance",
        role=FamilyRole.RESISTANCE,
    )
    atr = calculate_normalization_atr(tracker_ohlcv(later), window=3)

    assert score_family_candidate(
        family,
        candidate_observation,
        timestamp=later,
        atr=atr,
        config=config,
        reactivation=False,
    ) is None


def test_anchor_overlap_improves_match_score() -> None:
    config, family, observed = _born_family()
    later = observed + (timestamp(1) - timestamp())
    overlapping = candidate(config, later, candidate_id="overlap", anchor_prefix="support")
    distinct = candidate(config, later, candidate_id="distinct", anchor_prefix="other")
    atr = calculate_normalization_atr(tracker_ohlcv(later), window=3)

    overlap_score = score_family_candidate(
        family,
        overlapping,
        timestamp=later,
        atr=atr,
        config=config,
        reactivation=False,
    )
    distinct_score = score_family_candidate(
        family,
        distinct,
        timestamp=later,
        atr=atr,
        config=config,
        reactivation=False,
    )

    assert overlap_score is not None
    assert distinct_score is not None
    assert overlap_score.anchor_similarity == 1.0
    assert distinct_score.anchor_similarity == 0.0
    assert overlap_score.score > distinct_score.score


def test_greedy_matching_has_stable_family_and_candidate_tie_breakers() -> None:
    config = tracker_config(matching={"minimum_match_score": 0.0})
    first_time = timestamp()
    first = candidate(config, first_time, candidate_id="first", anchor_prefix="shared")
    second = candidate(config, first_time, candidate_id="second", anchor_prefix="shared")
    repository = InMemoryTrendlineFamilyRepository()
    TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider((valid_result(first, second),)),
        config=config,
    ).update(tracker_ohlcv(first_time))
    snapshot = repository.latest_snapshot(config.asset, config.timeframe)
    assert snapshot is not None
    later = timestamp(1)
    candidates = (
        candidate(config, later, candidate_id="candidate-b", anchor_prefix="shared"),
        candidate(config, later, candidate_id="candidate-a", anchor_prefix="shared"),
    )
    matches = greedy_match_candidates(
        candidates,
        snapshot.active_families,
        timestamp=later,
        atr=calculate_normalization_atr(tracker_ohlcv(later), window=3),
        config=config,
        dormant_family_ids=set(),
    )

    assert tuple((match.family_id, match.candidate_id) for match in matches) == tuple(
        sorted((match.family_id, match.candidate_id) for match in matches)
    )


def test_normalization_atr_window_changes_matching_normalizer() -> None:
    observed = timestamp()
    frame = tracker_ohlcv(observed)
    frame.loc[frame.index[-1], "high"] = 110.0
    frame.loc[frame.index[-1], "low"] = 90.0

    short = calculate_normalization_atr(frame, window=1)
    long = calculate_normalization_atr(frame, window=3)

    assert short.method == "simple_true_range_mean_v1"
    assert short.value != long.value
    assert short.sample_count == 1
    assert long.sample_count == 3


def test_matching_atr_window_changes_tracker_association_outcome() -> None:
    first_time = timestamp()
    second_time = timestamp(1)
    short_config = tracker_config(
        matching={"normalization_atr_window": 1},
        lifecycle={"max_active_families_per_role": 3},
    )
    long_config = tracker_config(
        matching={"normalization_atr_window": 3},
        lifecycle={"max_active_families_per_role": 3},
    )
    frame = tracker_ohlcv(second_time)
    frame.loc[frame.index[-1], ["high", "low"]] = (110.0, 90.0)
    short_tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(candidate(short_config, first_time, candidate_id="first")),
                valid_result(candidate(short_config, second_time, candidate_id="second", reference_price=110.0)),
            )
        ),
        config=short_config,
    )
    long_tracker = TrendlineFamilyTracker(
        repository=InMemoryTrendlineFamilyRepository(),
        provider=SequenceProvider(
            (
                valid_result(candidate(long_config, first_time, candidate_id="first")),
                valid_result(candidate(long_config, second_time, candidate_id="second", reference_price=110.0)),
            )
        ),
        config=long_config,
    )

    short_tracker.update(tracker_ohlcv(first_time))
    long_tracker.update(tracker_ohlcv(first_time))
    short_update = short_tracker.update(frame)
    long_update = long_tracker.update(frame)

    assert short_update.snapshot.diagnostics["matched_count"] == 1
    assert short_update.snapshot.diagnostics["birth_count"] == 0
    assert long_update.snapshot.diagnostics["matched_count"] == 0
    assert long_update.snapshot.diagnostics["birth_count"] == 1
