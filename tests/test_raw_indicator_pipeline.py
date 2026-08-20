from __future__ import annotations

from unittest.mock import patch

from libs.common.config import ConfigManager
from libs.features.raw_indicator_pipeline import (
    RawIndicatorPipeline,
    _flatten_microstructure_outputs,
)


def _history(length: int) -> list[tuple[float, ...]]:
    base_ts = 1_700_000_000
    rows = []
    for index in range(length):
        close = 100.0 + index * 0.1
        rows.append(
            (
                close,
                close + 1,
                close - 1,
                close,
                1000.0,
                base_ts + index * 3600,
                550.0 + (index % 20),
            )
        )
    return rows


def test_raw_indicator_pipeline_live_tick_and_snapshot_match_expected_outputs() -> None:
    history = _history(260)
    tick = (126.0, 127.0, 125.0, 126.0, 1000.0, 1_700_000_000 + 261 * 3600, 560.0)

    ConfigManager.reset_singleton()
    raw = RawIndicatorPipeline("BTCUSDT", "1h")
    raw.prime(history)

    tick_result = raw.process_tick(tick)
    snapshot = raw.snapshot_features(history)

    assert raw.get_unprimed_indicator_keys() == []
    assert tick_result["RSI"] == 100.0
    assert tick_result["MACD"] == (
        0.7000000000000028,
        0.7000000000000026,
        2.220446049250313e-16,
    )
    assert snapshot["RSI"] == 100.0
    assert snapshot["MACD"] == (
        0.7000000000000028,
        0.7000000000000026,
        2.220446049250313e-16,
    )


def test_raw_indicator_pipeline_uses_default_indicator_config_for_unknown_asset() -> (
    None
):
    history = _history(260)

    ConfigManager.reset_singleton()
    raw = RawIndicatorPipeline("ANYASSET", "1h")
    raw.prime(history)
    snapshot = raw.snapshot_features(history)

    assert "RSI" in snapshot
    assert "MACD" in snapshot


def test_raw_indicator_pipeline_short_history_warns_not_errors() -> None:
    history = _history(5)

    ConfigManager.reset_singleton()
    with patch("libs.features.raw_indicator_pipeline.logger") as mock_logger:
        raw = RawIndicatorPipeline("BTCUSDT", "1h")
        raw.prime(history)

    assert raw.get_unprimed_indicator_keys()
    assert mock_logger.warning.called
    mock_logger.error.assert_not_called()


def test_microstructure_outputs_are_flattened() -> None:
    results = {}

    class KyleLambda: ...

    _flatten_microstructure_outputs(
        results,
        KyleLambda(),
        {"KyleLambda": 1.2, "VPIN": 0.4},
    )

    assert results["KyleLambda"] == 1.2
    assert results["VPIN"] == 0.4
