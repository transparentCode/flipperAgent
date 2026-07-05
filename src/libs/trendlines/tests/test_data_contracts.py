import pytest

from app.trendlines.data import TrendlineArtifactRef, TrendlineDataRequest, TrendlineDatasetManifest


def test_trendline_data_request_round_trip_normalizes_fields():
    request = TrendlineDataRequest(
        asset=" BTCUSDT ",
        timeframes=("1h", "4h", "1h"),
        lookback_days=30,
        price_fields=("open", "high", "close", "close"),
        metadata={"kind": "research"},
    )

    restored = TrendlineDataRequest.from_dict(request.to_dict())

    assert request.asset == "BTCUSDT"
    assert request.timeframes == ("1h", "4h")
    assert request.price_fields == ("open", "high", "close")
    assert restored == request
    assert restored.request_hash == request.request_hash


def test_trendline_artifact_ref_round_trip():
    artifact = TrendlineArtifactRef(
        artifact_root="app/trendlines/results",
        relative_path="datasets/btcusdt_1h.parquet",
        label="btc-1h-source",
        content_type="application/x-parquet",
        metadata={"compression": "zstd"},
    )

    restored = TrendlineArtifactRef.from_dict(artifact.to_dict())

    assert restored == artifact


def test_trendline_dataset_manifest_round_trip_is_deterministic():
    request = TrendlineDataRequest(
        asset="BTCUSDT",
        timeframes=("1h", "4h"),
        source="parquet",
        start_date="2025-01-01",
        end_date="2025-03-01",
    )
    artifact = TrendlineArtifactRef(
        artifact_root="app/trendlines/results",
        relative_path="datasets/btcusdt_bundle.json",
    )
    manifest = TrendlineDatasetManifest(
        request=request,
        bar_counts={"4h": 80, "1h": 240},
        columns=("open", "high", "low", "close", "volume"),
        artifact=artifact,
        start_ts="2025-01-01T00:00:00Z",
        end_ts="2025-03-01T00:00:00Z",
        metadata={"exchange": "binance"},
    )

    restored = TrendlineDatasetManifest.from_dict(manifest.to_dict())

    assert manifest.bar_counts == {"1h": 240, "4h": 80}
    assert restored == manifest
    assert restored.manifest_hash == manifest.manifest_hash


def test_trendline_dataset_manifest_rejects_mismatched_timeframes():
    request = TrendlineDataRequest(asset="BTCUSDT", timeframes=("1h", "4h"))

    with pytest.raises(ValueError, match="Missing bar count"):
        TrendlineDatasetManifest(request=request, bar_counts={"1h": 240})