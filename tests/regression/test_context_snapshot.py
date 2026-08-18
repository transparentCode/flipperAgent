"""Focused tests for the additive regression context snapshot."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from libs.regression import api
from libs.regression.api import (
    compute_regression_context,
    compute_structural_channel,
)
from libs.regression.channel import channel_config_fingerprint
from libs.regression.config.resolver import ConfigResolver
from libs.regression.context_snapshot import (
    REGRESSION_CONTEXT_ID,
    _classify_region,
    _outer_breaches,
    _outer_channel_position,
)
from libs.regression.contracts import RegressionContextSnapshot, ResidualRegion

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "libs"
    / "regression"
    / "config"
    / "regression.yaml"
)
_CHANNEL_HASH = "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2"


def _resolver() -> ConfigResolver:
    return ConfigResolver.from_yaml(str(_CONFIG_PATH))


def _config(timeframe: str = "1h", window_size: int = 20):
    return dataclasses.replace(
        _resolver().resolve("BTCUSDT", timeframe), window_size=window_size
    )


def _policy():
    return _resolver().structural_channel_config


def _frame_from_residuals(
    residuals: np.ndarray,
    *,
    timeframe: str = "1h",
    volume: np.ndarray | None = None,
) -> pd.DataFrame:
    steps = {"1h": 1.0, "4h": 4.0}
    hours = np.arange(len(residuals), dtype=np.float64) * steps[timeframe]
    index = pd.date_range(
        "2024-01-01",
        periods=len(residuals),
        freq=timeframe,
        tz="UTC",
    )
    if volume is None:
        volume = np.full(len(residuals), 100.0)
    log_prices = np.log(100.0) + 0.01 * hours + residuals
    return pd.DataFrame({"close": np.exp(log_prices), "volume": volume}, index=index)


def _noisy_frame(timeframe: str = "1h") -> pd.DataFrame:
    residuals = np.array(
        [
            -0.20,
            -0.10,
            -0.08,
            -0.06,
            -0.05,
            -0.04,
            -0.03,
            -0.02,
            -0.01,
            0.00,
            0.01,
            0.02,
            0.03,
            0.04,
            0.05,
            0.07,
            0.09,
            0.12,
            0.15,
            0.35,
        ],
        dtype=np.float64,
    )
    return _frame_from_residuals(residuals, timeframe=timeframe)


def _constant_price_frame(size: int = 20) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=size, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"close": np.full(size, 137.0), "volume": np.full(size, 100.0)},
        index=index,
    )


def _transition_frame(side: str, current_residual: float = 0.0) -> pd.DataFrame:
    residuals = np.zeros(21, dtype=np.float64)
    residuals[-2] = 0.8 if side == "upper" else -0.8
    residuals[-1] = current_residual
    return _frame_from_residuals(residuals)


def _context(frame: pd.DataFrame, timeframe: str = "1h"):
    return compute_regression_context(
        frame,
        "BTCUSDT",
        timeframe,
        _config(timeframe, window_size=20),
        _policy(),
    )


def test_residual_region_has_exact_public_values():
    assert [region.value for region in ResidualRegion] == [
        "BELOW_OUTER",
        "LOWER_OUTER_BAND",
        "INNER_CHANNEL",
        "UPPER_OUTER_BAND",
        "ABOVE_OUTER",
    ]


def test_context_contract_is_frozen_and_exact():
    assert dataclasses.is_dataclass(RegressionContextSnapshot)
    assert RegressionContextSnapshot.__dataclass_params__.frozen is True
    assert [field.name for field in dataclasses.fields(RegressionContextSnapshot)] == [
        "channel",
        "context_id",
        "region",
        "outer_channel_position",
        "inner_width_log",
        "outer_width_log",
        "inner_width_fraction",
        "outer_width_fraction",
        "upper_outer_breach",
        "lower_outer_breach",
        "previous_region",
        "reentered_from_upper_outer",
        "reentered_from_lower_outer",
    ]


def test_context_id_and_public_api_are_available():
    assert REGRESSION_CONTEXT_ID == "structural_channel_location_one_step_v1"
    assert api.compute_regression_context is compute_regression_context


def test_context_nests_the_exact_current_channel():
    frame = _noisy_frame()
    config = _config(window_size=20)
    context = compute_regression_context(frame, "BTCUSDT", "1h", config, _policy())

    assert context.channel == compute_structural_channel(
        frame, "BTCUSDT", "1h", config, _policy()
    )
    assert context.context_id == REGRESSION_CONTEXT_ID


def test_context_requires_only_the_approved_channel_policy():
    resolver = _resolver()
    assert [
        field.name for field in dataclasses.fields(resolver.orchestrator_config)
    ] == [
        "mtf_timeframes",
        "tf_weights",
        "global_config",
        "timeframes",
        "asset_classes",
        "assets",
        "optimization",
        "structural_channel",
    ]
    assert resolver.structural_channel_config.inner_coverage == 0.68
    assert resolver.structural_channel_config.outer_coverage == 0.95


def test_region_boundaries_use_exact_inclusive_semantics():
    channel = compute_structural_channel(
        _noisy_frame(), "BTCUSDT", "1h", _config(), _policy()
    )
    cases = [
        (channel.lower_outer_residual_log, ResidualRegion.LOWER_OUTER_BAND),
        (channel.lower_inner_residual_log, ResidualRegion.INNER_CHANNEL),
        (channel.upper_inner_residual_log, ResidualRegion.INNER_CHANNEL),
        (channel.upper_outer_residual_log, ResidualRegion.UPPER_OUTER_BAND),
    ]

    for residual, expected in cases:
        adjusted = dataclasses.replace(channel, current_residual_log=residual)
        assert _classify_region(adjusted) is expected
        upper_breach, lower_breach = _outer_breaches(adjusted)
        assert not upper_breach
        assert not lower_breach


def test_outer_position_is_signed_unclipped_and_outer_normalized():
    channel = compute_structural_channel(
        _noisy_frame(), "BTCUSDT", "1h", _config(), _policy()
    )
    center = dataclasses.replace(channel, current_residual_log=0.0)
    lower = dataclasses.replace(
        channel, current_residual_log=channel.lower_outer_residual_log
    )
    upper = dataclasses.replace(
        channel, current_residual_log=channel.upper_outer_residual_log
    )
    below = dataclasses.replace(
        channel,
        current_residual_log=channel.lower_outer_residual_log * 1.25,
    )
    above = dataclasses.replace(
        channel,
        current_residual_log=channel.upper_outer_residual_log * 1.25,
    )

    assert _outer_channel_position(center) == 0.0
    assert _outer_channel_position(lower) == pytest.approx(-1.0)
    assert _outer_channel_position(upper) == pytest.approx(1.0)
    assert _outer_channel_position(below) < -1.0
    assert _outer_channel_position(above) > 1.0
    assert _classify_region(below) is ResidualRegion.BELOW_OUTER
    assert _classify_region(above) is ResidualRegion.ABOVE_OUTER


def test_width_geometry_and_strict_breach_flags_match_channel_values():
    context = _context(_noisy_frame())
    channel = context.channel
    expected_inner_log = (
        channel.upper_inner_residual_log - channel.lower_inner_residual_log
    )
    expected_outer_log = (
        channel.upper_outer_residual_log - channel.lower_outer_residual_log
    )
    expected_inner_fraction = (
        channel.upper_inner_price - channel.lower_inner_price
    ) / channel.structural.center_price
    expected_outer_fraction = (
        channel.upper_outer_price - channel.lower_outer_price
    ) / channel.structural.center_price

    assert context.inner_width_log == expected_inner_log
    assert context.outer_width_log == expected_outer_log
    assert context.inner_width_fraction == expected_inner_fraction
    assert context.outer_width_fraction == expected_outer_fraction
    assert context.inner_width_log >= 0.0
    assert context.outer_width_log >= 0.0
    assert context.inner_width_fraction >= 0.0
    assert context.outer_width_fraction >= 0.0
    assert context.upper_outer_breach == (
        channel.current_residual_log > channel.upper_outer_residual_log
    )
    assert context.lower_outer_breach == (
        channel.current_residual_log < channel.lower_outer_residual_log
    )

    upper_breach = dataclasses.replace(
        context.channel,
        current_residual_log=context.channel.upper_outer_residual_log * 1.25,
    )
    lower_breach = dataclasses.replace(
        context.channel,
        current_residual_log=context.channel.lower_outer_residual_log * 1.25,
    )
    assert _outer_breaches(upper_breach) == (True, False)
    assert _outer_breaches(lower_breach) == (False, True)


def test_constant_channel_is_inner_zero_geometry_without_breach():
    context = _context(_constant_price_frame())

    assert context.region is ResidualRegion.INNER_CHANNEL
    assert context.outer_channel_position == 0.0
    assert context.inner_width_log == 0.0
    assert context.outer_width_log == 0.0
    assert context.inner_width_fraction == 0.0
    assert context.outer_width_fraction == 0.0
    assert not context.upper_outer_breach
    assert not context.lower_outer_breach


def test_previous_state_is_unavailable_without_one_extra_bar():
    context = _context(_frame_from_residuals(np.zeros(20)))

    assert context.previous_region is None
    assert context.reentered_from_upper_outer is None
    assert context.reentered_from_lower_outer is None


def test_previous_state_is_independent_and_causal():
    frame = _transition_frame("upper")
    context = _context(frame)
    previous = compute_structural_channel(
        frame.iloc[:-1], "BTCUSDT", "1h", _config(), _policy()
    )

    assert context.previous_region is _classify_region(previous)
    assert context.previous_region is ResidualRegion.ABOVE_OUTER
    assert context.reentered_from_upper_outer is True
    assert context.reentered_from_lower_outer is False


def test_lower_outer_reentry_is_reported_once():
    context = _context(_transition_frame("lower"))

    assert context.previous_region is ResidualRegion.BELOW_OUTER
    assert context.reentered_from_upper_outer is False
    assert context.reentered_from_lower_outer is True


@pytest.mark.parametrize("side", ["upper", "lower"])
def test_staying_in_the_same_outer_region_is_not_reentry(side):
    residual = 1.2 if side == "upper" else -1.2
    context = _context(_transition_frame(side, residual))

    assert context.region in {
        ResidualRegion.ABOVE_OUTER,
        ResidualRegion.BELOW_OUTER,
    }
    assert context.reentered_from_upper_outer is False
    assert context.reentered_from_lower_outer is False


def test_only_current_bar_can_change_current_state_not_previous_state():
    first = _transition_frame("upper", 0.0)
    second = first.copy()
    second.iloc[-1, second.columns.get_loc("close")] *= 1.5

    first_context = _context(first)
    second_context = _context(second)

    assert first_context.previous_region is second_context.previous_region
    assert first.iloc[:-1].equals(second.iloc[:-1])


def test_context_makes_at_most_one_causal_previous_channel_call(monkeypatch):
    import libs.regression.context_snapshot as context_module

    frame = _transition_frame("upper")
    original = context_module.compute_structural_channel
    calls = []

    def recording_channel(*args, **kwargs):
        calls.append(args[0].copy())
        return original(*args, **kwargs)

    monkeypatch.setattr(context_module, "compute_structural_channel", recording_channel)
    _context(frame)

    assert len(calls) == 2
    assert calls[0].equals(frame)
    assert calls[1].equals(frame.iloc[:-1])


def test_rows_older_than_window_plus_one_are_ignored_even_if_malformed():
    residuals = np.zeros(23, dtype=np.float64)
    residuals[-2] = 0.8
    frame = _frame_from_residuals(residuals)
    baseline = _context(frame)

    changed = frame.copy()
    changed.iloc[0, changed.columns.get_loc("close")] = 1.0e300
    index = list(changed.index)
    index[0] = pd.NaT
    changed.index = pd.DatetimeIndex(index)

    assert _context(changed) == baseline


def test_mixed_type_older_prefix_is_ignored_without_parsing_owned_labels():
    residuals = np.zeros(23, dtype=np.float64)
    residuals[-2] = 0.8
    frame = _frame_from_residuals(residuals)
    baseline = _context(frame)

    changed = frame.copy()
    index = list(changed.index)
    index[0] = "BAD_IGNORED_PREFIX"
    changed.index = pd.Index(index)

    assert _context(changed) == baseline


def test_mixed_type_timestamp_inside_owned_horizon_fails_closed():
    frame = _frame_from_residuals(np.zeros(23, dtype=np.float64))
    index = list(frame.index)
    index[2] = "BAD_OWNED_TIMESTAMP"
    frame.index = pd.Index(index)

    with pytest.raises(TypeError, match="must be a DatetimeIndex"):
        _context(frame)


@pytest.mark.parametrize(
    "owned_index",
    [
        lambda frame: pd.Index([value.isoformat() for value in frame.index]),
        lambda frame: pd.Index(range(len(frame))),
    ],
    ids=["timestamp_like_strings", "integers"],
)
def test_generic_owned_index_is_not_parsed_or_accepted(owned_index):
    frame = _frame_from_residuals(np.zeros(21, dtype=np.float64))
    frame.index = owned_index(frame)

    with pytest.raises(TypeError, match="must be a DatetimeIndex"):
        _context(frame)


def test_current_selected_window_defect_fails_closed():
    frame = _frame_from_residuals(np.zeros(21))
    frame.iloc[-1, frame.columns.get_loc("close")] = np.nan

    with pytest.raises(ValueError, match="close values"):
        _context(frame)


def test_previous_selected_window_defect_fails_closed():
    frame = _frame_from_residuals(np.zeros(21))
    index = list(frame.index)
    index[0] = pd.NaT
    frame.index = pd.DatetimeIndex(index)

    with pytest.raises(ValueError, match="index must not contain NaT"):
        _context(frame)


def test_price_scaling_preserves_context_semantics_and_scales_prices():
    frame = _transition_frame("upper")
    scaled = frame.copy()
    scaled["close"] *= 17.0
    first = _context(frame)
    second = _context(scaled)

    assert second.region is first.region
    assert second.outer_channel_position == pytest.approx(first.outer_channel_position)
    assert second.inner_width_log == pytest.approx(first.inner_width_log)
    assert second.outer_width_log == pytest.approx(first.outer_width_log)
    assert second.inner_width_fraction == pytest.approx(first.inner_width_fraction)
    assert second.outer_width_fraction == pytest.approx(first.outer_width_fraction)
    assert second.upper_outer_breach is first.upper_outer_breach
    assert second.lower_outer_breach is first.lower_outer_breach
    assert second.previous_region is first.previous_region
    assert second.reentered_from_upper_outer is first.reentered_from_upper_outer
    assert second.reentered_from_lower_outer is first.reentered_from_lower_outer
    assert second.channel.channel_config_hash == first.channel.channel_config_hash
    assert second.channel.structural.source_config_hash == (
        first.channel.structural.source_config_hash
    )
    assert second.channel.structural.center_price == pytest.approx(
        17.0 * first.channel.structural.center_price
    )
    for first_price, second_price in (
        (first.channel.lower_inner_price, second.channel.lower_inner_price),
        (first.channel.upper_inner_price, second.channel.upper_inner_price),
        (first.channel.lower_outer_price, second.channel.lower_outer_price),
        (first.channel.upper_outer_price, second.channel.upper_outer_price),
    ):
        assert second_price == pytest.approx(17.0 * first_price)


def test_volume_changes_do_not_change_context():
    frame = _transition_frame("upper")
    changed_volume = frame.copy()
    changed_volume["volume"] = np.arange(len(frame), dtype=float) ** 2 + 1.0

    assert _context(changed_volume) == _context(frame)


def test_aware_non_utc_and_naive_timestamps_preserve_context():
    frame = _transition_frame("upper")
    non_utc = frame.copy()
    non_utc.index = frame.index.tz_convert("Asia/Kolkata")
    naive = frame.copy()
    naive.index = frame.index.tz_localize(None)

    expected = _context(frame)
    assert _context(non_utc) == expected
    assert _context(naive) == expected


@pytest.mark.parametrize(
    ("timeframe", "source_hash"),
    [("1h", "30d530f70382"), ("4h", "218fd7f91880")],
)
def test_canonical_source_and_channel_hashes_remain_unchanged(timeframe, source_hash):
    context = _context(_noisy_frame(timeframe), timeframe)

    assert context.channel.channel_config_hash == _CHANNEL_HASH
    assert context.channel.structural.source_config_hash == source_hash
    assert channel_config_fingerprint(_policy()) == _CHANNEL_HASH


def test_context_implementation_has_no_forbidden_runtime_surface():
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "libs"
        / "regression"
        / "context_snapshot.py"
    ).read_text()
    for forbidden in (
        "band_multiplier",
        "atr",
        "regime",
        "cascade",
        "mtf",
        "optimizer",
        "signal",
        "direction",
        "confidence",
        "touch",
        "outside_run",
    ):
        assert forbidden not in source.lower()
