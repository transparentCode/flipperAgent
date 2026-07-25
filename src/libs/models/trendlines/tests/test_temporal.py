import pandas as pd

from app.trendlines.data import (
    TRENDLINE_AUTO_SPLIT_POLICY,
    TemporalSplitManifest,
    TemporalSplitSpec,
    WalkForwardValidator,
    build_temporal_split_manifest,
    resolve_trendline_auto_split_spec,
)


def test_resolve_trendline_auto_split_spec_matches_current_hourly_heuristic():
    spec = resolve_trendline_auto_split_spec("1h")

    assert spec.policy_name == TRENDLINE_AUTO_SPLIT_POLICY
    assert spec.train_bars == 24 * 30
    assert spec.test_bars == 24 * 7
    assert spec.step_bars == 24 * 7
    assert spec.purge_bars == 0
    assert spec.min_train_bars == 24 * 30


def test_temporal_split_manifest_is_deterministic_and_uses_walk_forward_shape():
    spec = resolve_trendline_auto_split_spec("4h", purge_bars=6)

    manifest_a = build_temporal_split_manifest(700, spec)
    manifest_b = build_temporal_split_manifest(700, spec)

    assert isinstance(manifest_a, TemporalSplitManifest)
    assert manifest_a.to_dict() == manifest_b.to_dict()
    assert manifest_a.folds[0].test_start == manifest_a.folds[0].train_end + 6


def test_temporal_split_manifest_round_trip_restores_spec_and_folds():
    spec = TemporalSplitSpec(
        split_kind="walk_forward",
        train_bars=120,
        test_bars=30,
        step_bars=30,
        purge_bars=5,
        min_train_bars=120,
        timeframe="1h",
        asset_class="crypto",
        policy_name="manual",
    )
    manifest = build_temporal_split_manifest(400, spec)

    restored = TemporalSplitManifest.from_dict(manifest.to_dict())

    assert restored == manifest
    assert restored.spec.spec_hash == spec.spec_hash


def test_walk_forward_validator_iterates_expected_frame_sizes():
    validator = WalkForwardValidator(train_bars=4, test_bars=2, step_bars=2, purge_bars=1, min_train_bars=4)
    frame = pd.DataFrame({"close": range(12)})

    splits = list(validator.iterate_splits(frame))

    assert len(splits) == 3
    first_split, train_df, test_df = splits[0]
    assert first_split.train_size == 4
    assert first_split.test_size == 2
    assert len(train_df) == 4
    assert len(test_df) == 2