from __future__ import annotations

from libs.common.asset_manifest import (
    AssetManifest,
    iter_live_manifest_timeframes,
    live_manifest_pairs,
    manifest_runtime_timeframes,
)


def test_manifest_runtime_timeframes_prefers_explicit_manifest_timeframes() -> None:
    manifest = AssetManifest(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h", "4h"],
        timeframes=["1m", "1h", "4h"],
        updated_at=1.0,
    )

    assert manifest_runtime_timeframes(manifest) == ["1m", "1h", "4h"]


def test_manifest_runtime_timeframes_falls_back_to_base_and_publish_timeframes() -> None:
    manifest = AssetManifest(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h", "1h", "4h"],
        timeframes=[],
        updated_at=1.0,
    )

    assert manifest_runtime_timeframes(manifest) == ["1m", "1h", "4h"]


def test_live_manifest_helpers_skip_non_live_assets() -> None:
    live_manifest = AssetManifest(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h"],
        timeframes=["1m", "1h"],
        desired_state="LIVE",
        updated_at=1.0,
    )
    paused_manifest = AssetManifest(
        symbol="ETHUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h"],
        timeframes=["1m", "1h"],
        desired_state="PAUSED",
        updated_at=1.0,
    )

    assert live_manifest_pairs([live_manifest, paused_manifest]) == [
        ("BTCUSDT", "1m"),
        ("BTCUSDT", "1h"),
    ]
    assert iter_live_manifest_timeframes([live_manifest, paused_manifest]) == [
        (live_manifest, "1m"),
        (live_manifest, "1h"),
    ]
