from __future__ import annotations

from libs.common.runtime_scale import RuntimeScaleInputs, StreamCaps, estimate_runtime_scale


def test_estimate_runtime_scale_computes_worker_and_stream_counts() -> None:
    report = estimate_runtime_scale(
        RuntimeScaleInputs(
            asset_count=200,
            runtime_timeframes_per_asset=3.0,
            signal_pairs_per_asset=2.0,
            strategy_pairs_per_asset=1.5,
            stream_caps=StreamCaps(
                ohlcv_maxlen=1000,
                feature_stream_maxlen=1000,
                price_update_stream_maxlen=200,
                signal_stream_maxlen=1000,
                order_stream_maxlen=1000,
                fill_stream_maxlen=1000,
                failure_stream_maxlen=1000,
                lifecycle_maxlen=1000,
                control_maxlen=1000,
                events_maxlen=1000,
                runtime_status_maxlen=1000,
            ),
        )
    )

    assert report.ingestion_runtime_count == 200
    assert report.signal_worker_count == 400
    assert report.strategy_worker_count == 300
    assert report.ohlcv_stream_count == 600
    assert report.replay_entry_upper_bounds["ohlcv"] == 600_000
    assert report.replay_entry_upper_bounds["signals"] == 300_000
    assert report.total_worker_count == 1_300


def test_estimate_runtime_scale_rounds_fractional_pairs_up() -> None:
    report = estimate_runtime_scale(
        RuntimeScaleInputs(
            asset_count=3,
            runtime_timeframes_per_asset=1.34,
            signal_pairs_per_asset=0.34,
            strategy_pairs_per_asset=0.67,
            stream_caps=StreamCaps(
                ohlcv_maxlen=10,
                feature_stream_maxlen=10,
                price_update_stream_maxlen=10,
                signal_stream_maxlen=10,
                order_stream_maxlen=10,
                fill_stream_maxlen=10,
                failure_stream_maxlen=10,
                lifecycle_maxlen=10,
                control_maxlen=10,
                events_maxlen=10,
                runtime_status_maxlen=10,
            ),
        )
    )

    assert report.ohlcv_stream_count == 5
    assert report.signal_worker_count == 2
    assert report.strategy_worker_count == 3
