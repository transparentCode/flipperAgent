from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from libs.models.trendlines.boundary import (
    BoundaryResult,
    QualityMetrics,
    Ray,
    TrendlineSnapshot,
    TrendlineSnapshotHistory,
)
from libs.models.trendlines.config import SnapshotHistoryPolicies, SnapshotHistoryPolicy
from libs.models.trendlines.contracts.identity import (
    PivotFinality,
    SourceIdentityKind,
    TrendlineCheckpoint,
    TrendlineExecutionMode,
    TrendlineSnapshotFinality,
    TrendlineSnapshotStage,
    TrendlineSnapshotIdentity,
    TrendlineSourceRef,
)


def _ray(level: float, *, is_support: bool) -> Ray:
    return Ray(
        start_time=pd.Timestamp("2026-01-01T00:00:00Z"),
        end_time=pd.Timestamp("2026-01-01T01:00:00Z"),
        start_price=level,
        end_price=level,
        slope=0.0,
        intercept=level,
        touch_count=3,
        is_support=is_support,
        score=0.8,
    )


def _boundary(
    hour: int,
    *,
    asset: str = "btcusdt",
    timeframe: str = "1h",
    interaction: str = "NONE",
    hull_width_atr: float = 2.0,
) -> BoundaryResult:
    timestamp = datetime(2026, 1, 1, hour, tzinfo=timezone.utc)
    source = TrendlineSourceRef(
        source_id=f"source-{asset}-{timeframe}-{hour}",
        source_start=timestamp.isoformat(),
        as_of=timestamp.isoformat(),
        row_count=1,
        columns=("close",),
        identity_kind=SourceIdentityKind.COMPUTED,
    )
    checkpoint = TrendlineCheckpoint(
        checkpoint_id=f"checkpoint-{asset}-{timeframe}-{hour}",
        source=source,
        config_id=f"config-{interaction}-{hull_width_atr}",
        execution_mode=TrendlineExecutionMode.RUNTIME,
        extractor_finality=PivotFinality.CONFIRMED_APPEND_ONLY,
    )
    identity = TrendlineSnapshotIdentity(
        snapshot_id=f"snapshot-{asset}-{timeframe}-{hour}",
        revision_id=f"revision-{asset}-{timeframe}-{hour}-{interaction}-{hull_width_atr}",
        checkpoint=checkpoint,
        stage=TrendlineSnapshotStage.BOUNDARY,
        finality=TrendlineSnapshotFinality.CONFIRMED_AS_OF,
        content_id=f"content-{interaction}-{hull_width_atr}",
        asset=asset,
        timeframe=timeframe,
    )
    return BoundaryResult(
        asset=asset,
        timeframe=timeframe,
        timestamp=timestamp,
        active_support_rays=[_ray(100.0, is_support=True)],
        active_resistance_rays=[_ray(110.0, is_support=False)],
        convex_hull_floor=100.0,
        convex_hull_ceiling=110.0,
        interaction=interaction,
        is_valid=True,
        quality_metrics=QualityMetrics(
            n_support_rays=1,
            n_resistance_rays=1,
            mean_score=0.8,
            mean_normalized_quality=0.75,
            mean_support_quality=0.7,
            mean_resistance_quality=0.8,
            mean_touch_count=3.0,
            mean_r_squared=0.9,
            hull_width_atr=hull_width_atr,
        ),
        snapshot_identity=identity,
    )


def _history(*, logical: int = 256, revisions: int = 8, context: int = 5) -> TrendlineSnapshotHistory:
    return TrendlineSnapshotHistory(
        SnapshotHistoryPolicies(
            SnapshotHistoryPolicy(logical, revisions, context),
            {},
        )
    )


def test_snapshot_serializes_boundary_payload():
    boundary = _boundary(1, asset="ethusdt")
    snapshot = TrendlineSnapshot.from_boundary(boundary, metadata={"source": "unit"})

    payload = snapshot.to_dict()

    assert snapshot.key == ("ETHUSDT", "1h")
    assert payload["asset"] == "ETHUSDT"
    assert payload["metadata"] == {"source": "unit"}
    assert payload["boundary"]["asset"] == "ethusdt"


def test_history_prunes_per_asset_timeframe_bucket():
    history = _history(logical=3)
    for hour in range(5):
        history.add(_boundary(hour))

    stored = history.history("BTCUSDT", "1h")

    assert history.count("BTCUSDT", "1h") == 3
    assert [item.timestamp.hour for item in stored] == [2, 3, 4]
    assert history.latest("BTCUSDT", "1h").timestamp.hour == 4


def test_history_keeps_asset_timeframes_isolated():
    history = _history(logical=5)
    history.add(_boundary(1, asset="BTCUSDT", timeframe="1h"))
    history.add(_boundary(2, asset="BTCUSDT", timeframe="4h"))
    history.add(_boundary(3, asset="ETHUSDT", timeframe="1h"))

    assert history.keys() == [("BTCUSDT", "1h"), ("BTCUSDT", "4h"), ("ETHUSDT", "1h")]
    assert history.count() == 3
    assert history.latest("BTCUSDT", "4h").timestamp.hour == 2


def test_temporal_history_returns_snapshots_before_current_timestamp():
    history = _history(logical=10)
    for hour in range(5):
        history.add(_boundary(hour, hull_width_atr=5.0 - hour))

    current = _boundary(5, interaction="STRUCTURAL_BREAKOUT", hull_width_atr=1.0)
    temporal = history.temporal_history(current, min_history=3)

    assert [item.timestamp.hour for item in temporal] == [2, 3, 4]
    assert [item.quality_metrics.hull_width_atr for item in temporal] == [3.0, 2.0, 1.0]


def test_history_before_filters_by_timestamp_even_with_later_snapshots():
    history = _history(logical=10)
    for hour in range(6):
        history.add(_boundary(hour))

    previous = history.history_before("BTCUSDT", "1h", _boundary(4).timestamp, limit=2)

    assert [item.timestamp.hour for item in previous] == [2, 3]


def test_temporal_history_excludes_current_if_already_added():
    history = _history(logical=10)
    for hour in range(4):
        history.add(_boundary(hour))
    current = _boundary(4)
    history.add(current)

    temporal = history.temporal_history(current, min_history=4)

    assert [item.timestamp.hour for item in temporal] == [0, 1, 2, 3]


def test_history_rejects_bad_policy_and_partial_keys():
    with pytest.raises(ValueError, match=">= 1"):
        SnapshotHistoryPolicy(0, 1, 1)

    history = _history(logical=2)
    with pytest.raises(ValueError, match="asset and timeframe"):
        history.count(asset="BTCUSDT")
    with pytest.raises(ValueError, match="asset and timeframe"):
        history.clear(timeframe="1h")
