from __future__ import annotations

import pytest

from libs.models.trendline_family.repository import InMemoryTrendlineFamilyRepository, serialize_snapshot
from libs.models.trendline_family.tracker import TrendlineFamilyTracker, TrendlineFamilyUpdateError

from .tracker_support import SequenceProvider, candidate, timestamp, tracker_config, tracker_ohlcv, valid_result


def _seed_repository():
    config = tracker_config()
    observed = timestamp()
    repository = InMemoryTrendlineFamilyRepository()
    TrendlineFamilyTracker(
        repository=repository,
        provider=SequenceProvider((valid_result(candidate(config, observed, candidate_id="first")),)),
        config=config,
    ).update(tracker_ohlcv(observed))
    head = repository.latest_snapshot(config.asset, config.timeframe)
    assert head is not None
    return config, repository, head


def _assert_config_lineage_rejection(config_b, expected_field: str) -> None:
    config_a, repository, head = _seed_repository()
    observed = timestamp(1)
    provider = SequenceProvider((valid_result(candidate(config_b, observed, candidate_id="second")),))
    before = serialize_snapshot(head)

    with pytest.raises(TrendlineFamilyUpdateError, match=expected_field):
        TrendlineFamilyTracker(
            repository=repository,
            provider=provider,
            config=config_b,
        ).update(tracker_ohlcv(observed))

    after = repository.latest_snapshot(config_a.asset, config_a.timeframe)
    assert after is not None
    assert provider.calls == []
    assert serialize_snapshot(after) == before


def test_resolved_config_hash_mismatch_fails_before_provider_and_preserves_head() -> None:
    _assert_config_lineage_rejection(
        tracker_config(matching={"normalization_atr_window": 1}),
        "resolved_config_hash",
    )


def test_model_version_mismatch_fails_before_provider_and_preserves_head() -> None:
    _assert_config_lineage_rejection(
        tracker_config(model={"model_version": "trendline_family_v2"}),
        "model_version",
    )


def test_config_version_mismatch_fails_before_provider_and_preserves_head() -> None:
    _assert_config_lineage_rejection(tracker_config(config_version=2), "config_version")


class _ForeignHeadRepository:
    def __init__(self, head) -> None:
        self.head = head
        self.requests: list[tuple[str, str]] = []
        self.saved = []

    def latest_snapshot(self, asset: str, timeframe: str):
        self.requests.append((asset, timeframe))
        return self.head

    def save_snapshot(self, snapshot) -> None:
        self.saved.append(snapshot)


def test_repository_asset_timeframe_mismatch_fails_before_provider_and_preserves_head() -> None:
    _, _, head = _seed_repository()
    config = tracker_config(asset="ETHUSDT", timeframe="4h")
    repository = _ForeignHeadRepository(head)
    provider = SequenceProvider((valid_result(candidate(config, timestamp(1))),))
    before = serialize_snapshot(head)

    with pytest.raises(TrendlineFamilyUpdateError, match="asset"):
        TrendlineFamilyTracker(
            repository=repository,
            provider=provider,
            config=config,
        ).update(tracker_ohlcv(timestamp(1)))

    assert repository.requests == [("ETHUSDT", "4h")]
    assert provider.calls == []
    assert repository.saved == []
    assert serialize_snapshot(repository.head) == before


def test_same_config_head_continues_normally() -> None:
    config, repository, head = _seed_repository()
    observed = timestamp(1)
    provider = SequenceProvider((valid_result(candidate(config, observed, candidate_id="second")),))

    output = TrendlineFamilyTracker(
        repository=repository,
        provider=provider,
        config=config,
    ).update(tracker_ohlcv(observed))

    assert provider.calls
    assert output.snapshot.previous_snapshot_id == head.snapshot_id
    assert output.snapshot.diagnostics["matched_count"] == 1
