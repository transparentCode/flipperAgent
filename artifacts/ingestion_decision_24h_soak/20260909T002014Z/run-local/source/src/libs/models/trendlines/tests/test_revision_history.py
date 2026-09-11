from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendlines.boundary import (
    BoundaryResult,
    SnapshotHistoryContractError,
    SnapshotIdentityConflictError,
    SnapshotRevisionCapacityError,
    SnapshotRetentionError,
    TrendlineSnapshotHistory,
)
from libs.models.trendlines.config import (
    AssetConfig,
    AssetTimeframeConfig,
    SnapshotHistoryConfigError,
    SnapshotHistoryOverride,
    SnapshotHistoryPolicies,
    SnapshotHistoryPolicy,
    TrendlinesConfig,
    load_trendlines_config,
    resolve_snapshot_history_policy,
)
from libs.models.trendlines.contracts.identity import (
    PivotFinality,
    SourceIdentityKind,
    TrendlineCheckpoint,
    TrendlineExecutionMode,
    TrendlineSnapshotFinality,
    TrendlineSnapshotIdentity,
    TrendlineSnapshotStage,
    TrendlineSourceRef,
)


BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _boundary(
    hour: int,
    *,
    revision: str = "r1",
    snapshot_id: str | None = None,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    marker: str = "base",
) -> BoundaryResult:
    timestamp = BASE_TIME + timedelta(hours=hour)
    snapshot_id = snapshot_id or f"snapshot-{asset}-{timeframe}-{hour}"
    source = TrendlineSourceRef(
        source_id=f"source-{snapshot_id}-{revision}",
        source_start=BASE_TIME.isoformat(),
        as_of=timestamp.isoformat(),
        row_count=hour + 1,
        columns=("close",),
        identity_kind=SourceIdentityKind.COMPUTED,
    )
    checkpoint = TrendlineCheckpoint(
        checkpoint_id=f"checkpoint-{snapshot_id}-{revision}",
        source=source,
        config_id=f"config-{revision}",
        execution_mode=TrendlineExecutionMode.RUNTIME,
        extractor_finality=PivotFinality.CONFIRMED_APPEND_ONLY,
    )
    identity = TrendlineSnapshotIdentity(
        snapshot_id=snapshot_id,
        revision_id=f"revision-{snapshot_id}-{revision}",
        checkpoint=checkpoint,
        stage=TrendlineSnapshotStage.BOUNDARY,
        finality=TrendlineSnapshotFinality.CONFIRMED_AS_OF,
        content_id=f"content-{marker}",
        asset=asset,
        timeframe=timeframe,
    )
    return BoundaryResult(
        asset=asset,
        timeframe=timeframe,
        timestamp=timestamp,
        is_valid=True,
        metadata={"marker": marker},
        snapshot_identity=identity,
    )


def _history(
    *,
    logical: int = 256,
    revisions: int = 8,
    context: int = 5,
    overrides: dict[tuple[str, str], SnapshotHistoryPolicy] | None = None,
) -> TrendlineSnapshotHistory:
    policies = SnapshotHistoryPolicies(
        SnapshotHistoryPolicy(logical, revisions, context),
        overrides or {},
    )
    return TrendlineSnapshotHistory(policies)


def test_canonical_yaml_history_policy_loads():
    config = load_trendlines_config()
    assert config.history == SnapshotHistoryPolicy(256, 8, 5)


def test_asset_timeframe_override_precedence_works():
    config = TrendlinesConfig(
        history=SnapshotHistoryPolicy(256, 8, 5),
        assets={
            "BTCUSDT": AssetConfig(
                timeframes={
                    "1h": AssetTimeframeConfig(
                        history=SnapshotHistoryOverride(
                            max_logical_snapshots_per_key=512,
                            max_revisions_per_snapshot=12,
                            context_limit=8,
                        )
                    )
                }
            )
        },
    )
    assert resolve_snapshot_history_policy(config, "btcusdt", "1h") == SnapshotHistoryPolicy(512, 12, 8)
    assert resolve_snapshot_history_policy(config, "ETHUSDT", "1h") == SnapshotHistoryPolicy(256, 8, 5)


def test_missing_history_policy_fails_history_construction():
    with pytest.raises(SnapshotHistoryConfigError):
        TrendlineSnapshotHistory.from_config(TrendlinesConfig())


def test_invalid_policy_capacities_are_rejected():
    with pytest.raises(SnapshotHistoryConfigError, match=">= 1"):
        SnapshotHistoryPolicy(0, 8, 5)
    with pytest.raises(SnapshotHistoryConfigError, match="unknown history fields"):
        SnapshotHistoryPolicy.from_mapping({"max_logical_snapshots_per_key": 1, "max_revisions_per_snapshot": 1, "context_limit": 1, "extra": 1})


def test_strict_insertion_requires_boundary_identity():
    history = _history()
    boundary = BoundaryResult(asset="BTCUSDT", timeframe="1h", timestamp=BASE_TIME)
    with pytest.raises(SnapshotHistoryContractError, match="snapshot_identity"):
        history.add(boundary)


def test_first_revision_defaults_known_at_to_as_of():
    history = _history()
    snapshot = history.add(_boundary(1))
    assert snapshot.known_at == BASE_TIME + timedelta(hours=1)


def test_new_correction_requires_explicit_known_at():
    history = _history()
    first = _boundary(1, snapshot_id="logical-1", revision="r1")
    history.add(first)
    with pytest.raises(SnapshotHistoryContractError, match="required"):
        history.add(_boundary(1, snapshot_id="logical-1", revision="r2"))


def test_naive_known_at_is_rejected():
    history = _history()
    with pytest.raises(SnapshotHistoryContractError, match="timezone-aware"):
        history.add(_boundary(1), known_at=datetime(2026, 1, 1, 1))


def test_known_at_before_as_of_is_rejected():
    history = _history()
    with pytest.raises(SnapshotHistoryContractError, match=">= snapshot as_of"):
        history.add(_boundary(2), known_at=BASE_TIME + timedelta(hours=1))


def test_out_of_order_event_insertion_remains_event_time_ordered():
    history = _history()
    history.add(_boundary(2))
    history.add(_boundary(1))
    history.add(_boundary(3))
    assert [item.timestamp.hour for item in history.history("BTCUSDT", "1h")] == [1, 2, 3]


def test_exact_duplicate_insertion_is_idempotent():
    history = _history()
    boundary = _boundary(1)
    first = history.add(boundary)
    second = history.add(boundary)
    assert first is second
    assert history.logical_count() == 1
    assert history.revision_count() == 1


def test_duplicate_revision_with_conflicting_known_at_is_rejected():
    history = _history()
    boundary = _boundary(1)
    history.add(boundary, known_at=BASE_TIME + timedelta(hours=2))
    with pytest.raises(SnapshotIdentityConflictError, match="known_at"):
        history.add(boundary, known_at=BASE_TIME + timedelta(hours=3))


def test_new_revision_of_same_snapshot_is_retained():
    history = _history()
    history.add(_boundary(1, snapshot_id="logical-1", revision="r1"))
    history.add(
        _boundary(1, snapshot_id="logical-1", revision="r2", marker="corrected"),
        known_at=BASE_TIME + timedelta(hours=2),
    )
    assert history.logical_count() == 1
    assert history.revision_count() == 2
    assert len(history.revision_history("BTCUSDT", "1h", "logical-1")) == 2


def test_different_revisions_at_identical_known_at_are_rejected():
    history = _history()
    known_at = BASE_TIME + timedelta(hours=2)
    history.add(_boundary(1, snapshot_id="logical-1", revision="r1"), known_at=known_at)
    with pytest.raises(SnapshotIdentityConflictError, match="share known_at"):
        history.add(
            _boundary(1, snapshot_id="logical-1", revision="r2"),
            known_at=known_at,
        )


def test_get_exact_at_selects_revision_known_at_query_time():
    history = _history()
    history.add(_boundary(1, snapshot_id="logical-1", revision="r1"))
    history.add(
        _boundary(1, snapshot_id="logical-1", revision="r2", marker="corrected"),
        known_at=BASE_TIME + timedelta(hours=3),
    )
    as_of = BASE_TIME + timedelta(hours=1)
    assert history.get_exact_at("BTCUSDT", "1h", as_of, known_at=BASE_TIME + timedelta(hours=2)).metadata["marker"] == "base"
    assert history.get_exact_at("BTCUSDT", "1h", as_of, known_at=BASE_TIME + timedelta(hours=4)).metadata["marker"] == "corrected"


def test_get_state_at_falls_back_to_earlier_event_snapshot_when_necessary():
    history = _history()
    history.add(_boundary(1, marker="earlier"))
    history.add(
        _boundary(2, marker="late-event"),
        known_at=BASE_TIME + timedelta(hours=4),
    )
    state = history.get_state_at(
        "BTCUSDT", "1h", BASE_TIME + timedelta(hours=2), known_at=BASE_TIME + timedelta(hours=3)
    )
    assert state is not None
    assert state.metadata["marker"] == "earlier"


def test_future_event_snapshots_are_excluded_from_historical_queries():
    history = _history()
    history.add(_boundary(1, marker="current"))
    history.add(_boundary(2, marker="future"))
    state = history.get_state_at("BTCUSDT", "1h", BASE_TIME + timedelta(hours=1))
    assert state is not None
    assert state.metadata["marker"] == "current"


def test_history_before_is_ordered_and_knowledge_time_causal():
    history = _history()
    history.add(_boundary(1, marker="one"))
    history.add(_boundary(2, marker="two"), known_at=BASE_TIME + timedelta(hours=4))
    values = history.history_before(
        "BTCUSDT", "1h", BASE_TIME + timedelta(hours=3), known_at=BASE_TIME + timedelta(hours=3)
    )
    assert [item.metadata["marker"] for item in values] == ["one"]


def test_latest_uses_newest_event_and_latest_retained_revision():
    history = _history()
    history.add(_boundary(1, marker="one"))
    history.add(_boundary(2, marker="two"))
    history.add(
        _boundary(2, marker="two-corrected", revision="r2"),
        known_at=BASE_TIME + timedelta(hours=3),
    )
    assert history.latest("BTCUSDT", "1h").metadata["marker"] == "two-corrected"


def test_logical_capacity_prunes_complete_oldest_snapshot_groups():
    history = _history(logical=2)
    history.add(_boundary(1, snapshot_id="one", revision="r1"))
    history.add(
        _boundary(1, snapshot_id="one", revision="r2"),
        known_at=BASE_TIME + timedelta(hours=2),
    )
    history.add(_boundary(2, snapshot_id="two"))
    history.add(_boundary(3, snapshot_id="three"))
    assert history.history("BTCUSDT", "1h")[0].timestamp.hour == 2
    assert history.revision_history("BTCUSDT", "1h", "one") == []
    assert history.revision_count() == 2


def test_revision_capacity_fails_closed_without_pruning_earlier_revisions():
    history = _history(revisions=1)
    history.add(_boundary(1, snapshot_id="one", revision="r1"))
    with pytest.raises(SnapshotRevisionCapacityError):
        history.add(
            _boundary(1, snapshot_id="one", revision="r2"),
            known_at=BASE_TIME + timedelta(hours=2),
        )
    assert history.revision_count() == 1
    assert history.revision_history("BTCUSDT", "1h", "one")[0].snapshot_identity.revision_id.endswith("-r1")


def test_different_asset_timeframe_policies_remain_isolated():
    history = _history(
        logical=2,
        overrides={("BTCUSDT", "1h"): SnapshotHistoryPolicy(1, 1, 2)},
    )
    history.add(_boundary(1, asset="BTCUSDT", timeframe="1h"))
    history.add(_boundary(2, asset="BTCUSDT", timeframe="1h"))
    history.add(_boundary(1, asset="ETHUSDT", timeframe="1h"))
    history.add(_boundary(2, asset="ETHUSDT", timeframe="1h"))
    assert history.logical_count("BTCUSDT", "1h") == 1
    assert history.logical_count("ETHUSDT", "1h") == 2
    with pytest.raises(SnapshotRetentionError):
        history.add(_boundary(0, asset="BTCUSDT", timeframe="1h"))
