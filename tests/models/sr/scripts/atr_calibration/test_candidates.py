from __future__ import annotations

from libs.models.sr.scripts.atr_calibration.candidates import compute_atr_series


def test_atr_prefix_invariance_for_all_candidates(calibration_config, source_capsules):
    development, _ = source_capsules
    for period in calibration_config.candidate_periods:
        full = compute_atr_series(development, period)
        prefix = compute_atr_series(development.bars[:-10], period)
        assert full[: len(prefix)] == prefix


def test_all_candidates_share_common_identity_and_reference_atr(development_replays):
    first = development_replays[0]
    first_ids = tuple(bar.bar_id for bar in first.model_bars)
    first_ohlc = tuple((bar.open, bar.high, bar.low, bar.close) for bar in first.model_bars)
    for replay in development_replays:
        assert replay.common_start_index == 28
        assert tuple(bar.bar_id for bar in replay.model_bars) == first_ids
        assert tuple((bar.open, bar.high, bar.low, bar.close) for bar in replay.model_bars) == first_ohlc
        assert replay.reference_atr == first.reference_atr


def test_candidate_replays_have_one_continuous_snapshot_sequence(development_replays):
    for replay in development_replays:
        assert len(replay.snapshots) == len(replay.model_bars)
        assert [snapshot.as_of for snapshot in replay.snapshots] == sorted(snapshot.as_of for snapshot in replay.snapshots)
