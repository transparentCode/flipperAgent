"""Focused tests for additive structural residual-quantile geometry."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from libs.regression import api
from libs.regression.api import compute_structural_channel, compute_structural_estimate
from libs.regression.channel import (
    STRUCTURAL_CHANNEL_ID,
    channel_config_fingerprint,
)
from libs.regression.config.resolver import ConfigResolver
from libs.regression.config.schema import (
    OrchestratorConfig,
    StructuralChannelConfig,
)
from libs.regression.contracts import StructuralChannelEstimate
from libs.regression.temporal import normalize_timestamps

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "libs"
    / "regression"
    / "config"
    / "regression.yaml"
)


def _resolver() -> ConfigResolver:
    return ConfigResolver.from_yaml(str(_CONFIG_PATH))


def _config(timeframe: str = "1h", window_size: int = 20):
    config = _resolver().resolve("BTCUSDT", timeframe)
    return dataclasses.replace(config, window_size=window_size)


def _policy(
    inner_coverage: float = 0.68, outer_coverage: float = 0.95
) -> StructuralChannelConfig:
    return StructuralChannelConfig(inner_coverage, outer_coverage)


def _frame(
    log_prices: np.ndarray,
    *,
    timestamps: pd.DatetimeIndex | None = None,
    volume: np.ndarray | None = None,
) -> pd.DataFrame:
    if timestamps is None:
        timestamps = pd.date_range(
            "2024-01-01", periods=len(log_prices), freq="1h", tz="UTC"
        )
    if volume is None:
        volume = np.full(len(log_prices), 100.0)
    return pd.DataFrame(
        {"close": np.exp(log_prices), "volume": volume}, index=timestamps
    )


def _noisy_frame(size: int = 20) -> pd.DataFrame:
    hours = np.arange(size, dtype=np.float64)
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
    return _frame(np.log(100.0) + 0.01 * hours + residuals)


def _compute(frame: pd.DataFrame, policy: StructuralChannelConfig | None = None):
    return compute_structural_channel(
        frame,
        "BTCUSDT",
        "1h",
        _config(window_size=20),
        policy or _policy(),
    )


def test_yaml_exposes_structural_channel_policy_without_optimization_metadata():
    resolver = _resolver()
    policy = resolver.structural_channel_config

    assert policy == _policy()
    assert policy.inner_coverage == pytest.approx(0.68)
    assert policy.outer_coverage == pytest.approx(0.95)
    assert "inner_coverage" not in json.dumps(resolver.orchestrator_config.optimization)
    assert "outer_coverage" not in json.dumps(resolver.orchestrator_config.optimization)


def test_canonical_structural_channel_mapping_requires_exact_keys():
    mapping = {"inner_coverage": 0.68, "outer_coverage": 0.95}
    resolver = ConfigResolver.from_dict({"structural_channel": mapping})

    assert resolver.structural_channel_config == _policy()
    assert channel_config_fingerprint(resolver.structural_channel_config) == (
        "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2"
    )


@pytest.mark.parametrize(
    ("mapping", "missing_key"),
    [
        ({"outer_coverage": 0.95}, "inner_coverage"),
        ({"inner_coverage": 0.68}, "outer_coverage"),
    ],
)
def test_structural_channel_mapping_rejects_missing_keys(mapping, missing_key):
    with pytest.raises(ValueError, match=missing_key):
        ConfigResolver.from_dict({"structural_channel": mapping})


@pytest.mark.parametrize("unexpected_key", ["unexpected", "outer_covergae"])
def test_structural_channel_mapping_rejects_unexpected_keys(unexpected_key):
    mapping = {
        "inner_coverage": 0.68,
        "outer_coverage": 0.95,
        unexpected_key: 123,
    }

    with pytest.raises(ValueError, match=unexpected_key):
        ConfigResolver.from_dict({"structural_channel": mapping})


def test_canonical_source_config_hashes_remain_unchanged():
    resolver = _resolver()

    assert resolver.resolve("BTCUSDT", "1h").config_hash == "30d530f70382"
    assert resolver.resolve("BTCUSDT", "4h").config_hash == "218fd7f91880"


def test_missing_structural_channel_policy_fails_clearly():
    resolver = ConfigResolver(OrchestratorConfig())
    with pytest.raises(ValueError, match="not configured"):
        _ = resolver.structural_channel_config


@pytest.mark.parametrize(
    "inner,outer",
    [
        (True, 0.95),
        (0.68, False),
        (np.nan, 0.95),
        (0.68, np.inf),
        (0.0, 0.95),
        (0.68, 1.0),
        (0.95, 0.68),
        (0.68, 0.68),
    ],
)
def test_invalid_structural_channel_coverages_are_rejected(inner, outer):
    with pytest.raises((TypeError, ValueError)):
        StructuralChannelConfig(inner, outer)


def test_structural_channel_config_is_frozen_and_exact():
    assert dataclasses.is_dataclass(StructuralChannelConfig)
    assert StructuralChannelConfig.__dataclass_params__.frozen is True
    assert [field.name for field in dataclasses.fields(StructuralChannelConfig)] == [
        "inner_coverage",
        "outer_coverage",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        _policy().inner_coverage = 0.5


def test_structural_channel_contract_is_frozen_and_exact():
    assert dataclasses.is_dataclass(StructuralChannelEstimate)
    assert StructuralChannelEstimate.__dataclass_params__.frozen is True
    assert [field.name for field in dataclasses.fields(StructuralChannelEstimate)] == [
        "structural",
        "channel_id",
        "channel_config_hash",
        "inner_coverage",
        "outer_coverage",
        "lower_inner_residual_log",
        "upper_inner_residual_log",
        "lower_outer_residual_log",
        "upper_outer_residual_log",
        "lower_inner_price",
        "upper_inner_price",
        "lower_outer_price",
        "upper_outer_price",
        "current_residual_log",
    ]


def test_channel_reuses_exact_r2a_structural_estimate():
    frame = _noisy_frame()
    config = _config(window_size=20)
    channel = compute_structural_channel(frame, "BTCUSDT", "1h", config, _policy())

    assert channel.structural == compute_structural_estimate(
        frame, "BTCUSDT", "1h", config
    )
    assert channel.channel_id == STRUCTURAL_CHANNEL_ID
    assert channel.structural.source_config_hash == "30d530f70382"


def test_offsets_match_independent_linear_quantiles():
    frame = _noisy_frame()
    config = _config(window_size=20)
    policy = _policy()
    structural = compute_structural_estimate(frame, "BTCUSDT", "1h", config)
    selected = frame.iloc[-config.window_size :]
    timestamps = normalize_timestamps(selected.index)
    elapsed_hours = (timestamps - timestamps[0]) / np.timedelta64(1, "h")
    elapsed_hours = np.asarray(elapsed_hours, dtype=np.float64)
    fitted = np.log(structural.center_price) + structural.slope_log_per_hour * (
        elapsed_hours - elapsed_hours[-1]
    )
    residuals = np.log(selected["close"].to_numpy()) - fitted

    channel = compute_structural_channel(frame, "BTCUSDT", "1h", config, policy)
    inner_tail = (1.0 - policy.inner_coverage) / 2.0
    outer_tail = (1.0 - policy.outer_coverage) / 2.0
    expected = (
        np.quantile(residuals, inner_tail, method="linear"),
        np.quantile(residuals, 1.0 - inner_tail, method="linear"),
        np.quantile(residuals, outer_tail, method="linear"),
        np.quantile(residuals, 1.0 - outer_tail, method="linear"),
    )

    assert channel.lower_inner_residual_log == expected[0]
    assert channel.upper_inner_residual_log == expected[1]
    assert channel.lower_outer_residual_log == expected[2]
    assert channel.upper_outer_residual_log == expected[3]
    assert channel.current_residual_log == residuals[-1]


def test_channel_geometry_is_asymmetric_and_nested():
    channel = _compute(_noisy_frame())

    assert not np.isclose(
        abs(channel.lower_inner_residual_log),
        abs(channel.upper_inner_residual_log),
    )
    assert (
        channel.lower_outer_price
        <= channel.lower_inner_price
        <= channel.structural.center_price
        <= channel.upper_inner_price
        <= channel.upper_outer_price
    )


def test_constant_price_collapses_channel_to_center():
    frame = _frame(np.full(20, np.log(137.0)))
    channel = _compute(frame)

    assert channel.structural.slope_log_per_hour == 0.0
    assert channel.current_residual_log == 0.0
    assert channel.lower_inner_residual_log == 0.0
    assert channel.upper_inner_residual_log == 0.0
    assert channel.lower_outer_residual_log == 0.0
    assert channel.upper_outer_residual_log == 0.0
    assert channel.lower_inner_price == channel.structural.center_price
    assert channel.upper_inner_price == channel.structural.center_price
    assert channel.lower_outer_price == channel.structural.center_price
    assert channel.upper_outer_price == channel.structural.center_price


def test_price_scaling_preserves_log_geometry_and_scales_prices():
    frame = _noisy_frame()
    scaled = frame.copy()
    scaled["close"] *= 17.0
    first = _compute(frame)
    second = _compute(scaled)

    assert second.structural.slope_log_per_hour == first.structural.slope_log_per_hour
    assert second.structural.residual_mad_log == pytest.approx(
        first.structural.residual_mad_log
    )
    assert second.structural.fit_quality == pytest.approx(first.structural.fit_quality)
    assert second.current_residual_log == pytest.approx(first.current_residual_log)
    assert second.lower_inner_residual_log == pytest.approx(
        first.lower_inner_residual_log
    )
    assert second.upper_inner_residual_log == pytest.approx(
        first.upper_inner_residual_log
    )
    assert second.lower_outer_residual_log == pytest.approx(
        first.lower_outer_residual_log
    )
    assert second.upper_outer_residual_log == pytest.approx(
        first.upper_outer_residual_log
    )
    assert second.channel_config_hash == first.channel_config_hash
    assert second.structural.center_price == pytest.approx(
        17.0 * first.structural.center_price
    )
    for first_price, second_price in (
        (first.lower_inner_price, second.lower_inner_price),
        (first.upper_inner_price, second.upper_inner_price),
        (first.lower_outer_price, second.lower_outer_price),
        (first.upper_outer_price, second.upper_outer_price),
    ):
        assert second_price == pytest.approx(17.0 * first_price)


def test_volume_does_not_change_structural_channel():
    frame = _noisy_frame()
    changed_volume = frame.copy()
    changed_volume["volume"] = np.arange(len(frame), dtype=float) ** 2 + 1.0

    assert _compute(changed_volume) == _compute(frame)


@pytest.mark.parametrize(
    "inner,outer",
    [(0.50, 0.95), (0.68, 0.90)],
)
def test_policy_change_only_changes_channel_geometry_and_hash(inner, outer):
    frame = _noisy_frame()
    baseline = _compute(frame, _policy())
    changed = _compute(frame, _policy(inner, outer))

    assert changed.structural == baseline.structural
    assert changed.channel_config_hash != baseline.channel_config_hash
    assert (
        changed.lower_inner_residual_log != baseline.lower_inner_residual_log
        or changed.upper_inner_residual_log != baseline.upper_inner_residual_log
        or changed.lower_outer_residual_log != baseline.lower_outer_residual_log
        or changed.upper_outer_residual_log != baseline.upper_outer_residual_log
    )


def test_channel_fingerprint_is_canonical_and_policy_only():
    policy = _policy()
    canonical = json.dumps(
        {"outer_coverage": 0.95, "inner_coverage": 0.68},
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    assert channel_config_fingerprint(policy) == expected
    assert len(expected) == 64

    resolver = _resolver()
    reordered = {
        "optimization": resolver.orchestrator_config.optimization,
        "structural_channel": {
            "outer_coverage": 0.95,
            "inner_coverage": 0.68,
        },
        "assets": {},
        "timeframes": {},
        "global": {},
        "unrelated": {"ignored": "value"},
    }
    reordered_resolver = ConfigResolver.from_dict(reordered)
    assert (
        channel_config_fingerprint(reordered_resolver.structural_channel_config)
        == expected
    )


def test_prefix_prices_and_malformed_prefix_time_cannot_change_channel():
    hours = np.arange(23, dtype=np.float64)
    frame = _frame(np.log(100.0) + 0.01 * hours)
    baseline = _compute(frame)

    mutated = frame.copy()
    mutated.iloc[0, mutated.columns.get_loc("close")] = 1.0e300
    prefix_index = list(mutated.index)
    prefix_index[0] = pd.NaT
    mutated.index = pd.DatetimeIndex(prefix_index)

    assert _compute(mutated) == baseline


@pytest.mark.parametrize(
    "index_factory",
    [
        lambda index: pd.Index(range(len(index))),
        lambda index: pd.DatetimeIndex([index[0], index[0], *index[2:]]),
        lambda index: pd.DatetimeIndex([index[0], index[2], index[1], *index[3:]]),
        lambda index: pd.DatetimeIndex([index[0], pd.NaT, *index[2:]]),
    ],
    ids=["non_datetime", "duplicate", "non_monotonic", "nat"],
)
def test_selected_temporal_defects_fail_closed(index_factory):
    frame = _frame(np.log(100.0) + 0.01 * np.arange(20, dtype=float))
    frame.index = index_factory(frame.index)

    with pytest.raises((TypeError, ValueError)):
        _compute(frame)


@pytest.mark.parametrize("close_value", [0.0, -1.0, np.nan, np.inf])
def test_selected_close_defects_fail_closed(close_value):
    frame = _frame(np.log(100.0) + 0.01 * np.arange(20, dtype=float))
    frame.iloc[-1, frame.columns.get_loc("close")] = close_value

    with pytest.raises(ValueError):
        _compute(frame)


def test_aware_non_utc_and_naive_indexes_have_same_epoch_semantics():
    frame = _noisy_frame()
    utc_index = frame.index
    non_utc = frame.copy()
    non_utc.index = utc_index.tz_convert("Asia/Kolkata")
    naive = frame.copy()
    naive.index = utc_index.tz_localize(None)

    expected = _compute(frame)
    assert _compute(non_utc) == expected
    assert _compute(naive) == expected


def test_public_api_and_contract_exports_are_available():
    assert api.compute_structural_channel is compute_structural_channel
    assert StructuralChannelEstimate is not None


def test_channel_module_has_no_forbidden_runtime_dependencies():
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "libs"
        / "regression"
        / "channel.py"
    )
    text = source.read_text()
    for forbidden in (
        "band_multiplier",
        "atr",
        "direction",
        "confidence",
        "signal",
        "regime",
        "cascade",
        "mtf",
        "optimizer",
    ):
        assert forbidden not in text.lower()
