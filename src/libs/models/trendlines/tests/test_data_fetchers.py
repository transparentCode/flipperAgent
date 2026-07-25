from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendlines.data import (
    TrendlineArtifactRef,
    TrendlineDataRequest,
    artifact_path,
    build_dataset_manifest,
    load_dataset,
    read_dataset_manifest,
    read_temporal_split_manifest,
    resolve_trendline_auto_split_spec,
    write_dataset_manifest,
    write_temporal_split_manifest,
)
from libs.models.trendlines.data.temporal import build_temporal_split_manifest


def _demo_frames() -> dict[str, pd.DataFrame]:
    return {
        "1h": pd.DataFrame(
            {
                "open": [1.0, 2.0, 3.0],
                "high": [2.0, 3.0, 4.0],
                "low": [0.5, 1.5, 2.5],
                "close": [1.5, 2.5, 3.5],
            }
        ),
        "4h": pd.DataFrame(
            {
                "open": [10.0, 12.0],
                "high": [11.0, 13.0],
                "low": [9.0, 11.0],
                "close": [10.5, 12.5],
                "volume": [100.0, 120.0],
            }
        ),
    }


def test_build_dataset_manifest_uses_request_order_and_union_of_columns():
    request = TrendlineDataRequest(asset="BTCUSDT", timeframes=("1h", "4h"))
    manifest = build_dataset_manifest(request, _demo_frames(), metadata={"source_kind": "fixture"})

    assert manifest.bar_counts == {"1h": 3, "4h": 2}
    assert manifest.columns == ("open", "high", "low", "close", "volume")
    assert manifest.metadata["source_kind"] == "fixture"


def test_load_dataset_uses_injected_loader_and_returns_manifest():
    request = TrendlineDataRequest(asset="BTCUSDT", timeframes=("1h", "4h"))
    seen = []

    def loader(incoming: TrendlineDataRequest) -> dict[str, pd.DataFrame]:
        seen.append(incoming)
        return _demo_frames()

    frames, manifest = load_dataset(request, loader, start_ts="2025-01-01T00:00:00Z", end_ts="2025-01-02T00:00:00Z")

    assert seen == [request]
    assert tuple(frames) == request.timeframes
    assert manifest.start_ts == "2025-01-01T00:00:00Z"
    assert manifest.end_ts == "2025-01-02T00:00:00Z"


def test_load_dataset_rejects_missing_timeframes_from_loader():
    request = TrendlineDataRequest(asset="BTCUSDT", timeframes=("1h", "4h"))

    def loader(_: TrendlineDataRequest) -> dict[str, pd.DataFrame]:
        return {"1h": _demo_frames()["1h"]}

    with pytest.raises(ValueError, match="missing requested timeframes"):
        load_dataset(request, loader)


def test_dataset_and_temporal_manifests_round_trip_through_artifact_helpers(tmp_path: Path):
    dataset_artifact = TrendlineArtifactRef(
        artifact_root=str(tmp_path),
        relative_path="datasets/request_manifest.json",
    )
    temporal_artifact = TrendlineArtifactRef(
        artifact_root=str(tmp_path),
        relative_path="datasets/temporal_manifest.json",
    )
    request = TrendlineDataRequest(asset="BTCUSDT", timeframes=("1h", "4h"))
    dataset_manifest = build_dataset_manifest(request, _demo_frames(), artifact=dataset_artifact)
    temporal_manifest = build_temporal_split_manifest(500, resolve_trendline_auto_split_spec("1h"))

    dataset_path = write_dataset_manifest(dataset_manifest)
    temporal_path = write_temporal_split_manifest(temporal_manifest, temporal_artifact)

    assert dataset_path == artifact_path(dataset_artifact)
    assert temporal_path == artifact_path(temporal_artifact)
    assert read_dataset_manifest(dataset_artifact) == dataset_manifest
    assert read_temporal_split_manifest(temporal_artifact) == temporal_manifest