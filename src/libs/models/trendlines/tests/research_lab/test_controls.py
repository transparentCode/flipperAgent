from __future__ import annotations

from datetime import datetime, timezone

import pytest

from libs.models.trendlines.research_lab import (
    TrendlineResearchLabControls,
    TrendlineResearchLabContractError,
    TrendlineReplayWindow,
    injected_lab_controls,
    resolve_provider_call_count,
    synthetic_lab_controls,
)


def _controls():
    return synthetic_lab_controls(
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
        seed=7,
        start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        bar_counts={"1h": 32},
        replay_windows={"1h": TrendlineReplayWindow(19, 20, 31, 1)},
        start_inline_viewers=False,
    )


def test_controls_reject_model_parameter_dictionaries() -> None:
    with pytest.raises(TypeError):
        synthetic_lab_controls(  # type: ignore[call-arg]
            asset="BTCUSDT",
            timeframes=("1h",),
            primary_timeframe="1h",
            seed=7,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bar_counts={"1h": 32},
            replay_windows={"1h": TrendlineReplayWindow(19, 20, 31, 1)},
            extractor_params={"window_left": 99},
        )


def test_synthetic_controls_are_deterministic() -> None:
    left = _controls()
    right = _controls()
    assert left.to_dict() == right.to_dict()
    assert resolve_provider_call_count(None, left.data_mode) == 0
    injected = injected_lab_controls(
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
        replay_windows={"1h": TrendlineReplayWindow(19, 20, 31, 1)},
        start_inline_viewers=False,
    )
    assert resolve_provider_call_count({}, injected.data_mode) == 0


def test_controls_require_ordered_unique_timeframes_and_matching_windows() -> None:
    controls = _controls()
    with pytest.raises(TrendlineResearchLabContractError, match="ordered and unique"):
        TrendlineResearchLabControls(
            purpose=controls.purpose,
            data_mode=controls.data_mode,
            asset=controls.asset,
            timeframes=("1h", "1h"),
            primary_timeframe="1h",
            data_spec=controls.data_spec,
            replay_spec=controls.replay_spec,
            include_signals=controls.include_signals,
            provider_calls_authorized=False,
            viewer_lookback_bars=16,
            start_inline_viewers=False,
            permanent_export=False,
        )


def test_controls_reject_provider_authorization_for_non_binance() -> None:
    controls = _controls()
    with pytest.raises(TrendlineResearchLabContractError, match="provider authorization"):
        TrendlineResearchLabControls(
            purpose=controls.purpose,
            data_mode=controls.data_mode,
            asset=controls.asset,
            timeframes=controls.timeframes,
            primary_timeframe=controls.primary_timeframe,
            data_spec=controls.data_spec,
            replay_spec=controls.replay_spec,
            include_signals=controls.include_signals,
            provider_calls_authorized=True,
            viewer_lookback_bars=16,
            start_inline_viewers=False,
            permanent_export=False,
        )
