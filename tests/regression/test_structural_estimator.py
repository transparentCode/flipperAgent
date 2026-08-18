"""Focused tests for the additive structural regression estimator."""

from __future__ import annotations

import dataclasses
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from libs.regression import api
from libs.regression.api import compute_structural_estimate
from libs.regression.config.resolver import ConfigResolver
from libs.regression.contracts import StructuralRegressionEstimate
from libs.regression.structural import STRUCTURAL_ESTIMATOR_ID

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "libs"
    / "regression"
    / "config"
    / "regression.yaml"
)


def _config(timeframe: str = "1h", window_size: int = 20):
    config = ConfigResolver.from_yaml(str(_CONFIG_PATH)).resolve("BTCUSDT", timeframe)
    return dataclasses.replace(config, window_size=window_size)


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


def _line(hours: np.ndarray, slope: float = 0.01, intercept: float = np.log(100.0)):
    return intercept + slope * hours


def test_exact_log_linear_recovery_and_market_times():
    config = _config(window_size=20)
    timestamps = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
    result = compute_structural_estimate(
        _frame(_line(np.arange(20.0)), timestamps=timestamps),
        "BTCUSDT",
        "1h",
        config,
    )

    assert result.slope_log_per_hour == pytest.approx(0.01)
    assert result.center_price == pytest.approx(np.exp(_line(np.array([19.0]))[0]))
    assert result.window_started_at == timestamps[0].to_pydatetime()
    assert result.timestamp == timestamps[-1].to_pydatetime()
    assert result.observed_through == (
        timestamps[-1] + pd.Timedelta(hours=1)
    ).to_pydatetime()


def test_fit_uses_the_exact_unweighted_all_pair_median():
    hours = np.array([0.0, 1.0, 3.0, 4.0, 7.0])
    log_prices = np.array([0.0, 0.4, 0.1, 0.9, 0.3])
    pair_slopes = [
        (log_prices[j] - log_prices[i]) / (hours[j] - hours[i])
        for i in range(len(hours))
        for j in range(i + 1, len(hours))
    ]
    expected_slope = float(np.median(pair_slopes))
    expected_intercept = float(np.median(log_prices - expected_slope * hours))

    result = compute_structural_estimate(
        _frame(log_prices, timestamps=pd.to_datetime(hours, unit="h", utc=True)),
        "BTCUSDT",
        "1h",
        _config(window_size=5),
    )

    assert len(pair_slopes) == 10
    assert result.slope_log_per_hour == pytest.approx(expected_slope)
    assert result.center_price == pytest.approx(
        np.exp(expected_intercept + expected_slope * hours[-1])
    )


def test_same_drift_has_same_slope_units_at_1h_and_4h():
    hours_1h = np.arange(20.0)
    hours_4h = np.arange(20.0) * 4.0
    result_1h = compute_structural_estimate(
        _frame(_line(hours_1h)), "BTCUSDT", "1h", _config("1h")
    )
    result_4h = compute_structural_estimate(
        _frame(
            _line(hours_4h),
            timestamps=pd.date_range(
                "2024-01-01", periods=20, freq="4h", tz="UTC"
            ),
        ),
        "BTCUSDT",
        "4h",
        _config("4h"),
    )

    assert result_1h.slope_log_per_hour == pytest.approx(0.01)
    assert result_4h.slope_log_per_hour == pytest.approx(0.01)
    assert result_1h.slope_log_per_hour == pytest.approx(
        result_4h.slope_log_per_hour
    )


def test_actual_elapsed_time_not_bar_ordinal():
    timestamps = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-01-01 00:00", tz="UTC"),
            pd.Timestamp("2024-01-01 01:00", tz="UTC"),
            pd.Timestamp("2024-01-01 03:00", tz="UTC"),
            pd.Timestamp("2024-01-01 04:00", tz="UTC"),
        ]
    )
    hours = np.array([0.0, 1.0, 3.0, 4.0])
    result = compute_structural_estimate(
        _frame(_line(hours, slope=0.2), timestamps=timestamps),
        "BTCUSDT",
        "1h",
        _config(window_size=4),
    )

    assert result.slope_log_per_hour == pytest.approx(0.2)


def test_price_scale_invariance_and_volume_invariance():
    config = _config(window_size=20)
    hours = np.arange(20.0)
    base = _frame(_line(hours), volume=np.arange(20.0) + 1.0)
    volume_only = base.copy()
    volume_only["volume"] = np.arange(20.0)[::-1] + 1000.0
    scaled = base.copy()
    scaled["close"] *= 17.0
    scaled["volume"] = volume_only["volume"]

    first = compute_structural_estimate(base, "BTCUSDT", "1h", config)
    volume_result = compute_structural_estimate(
        volume_only, "BTCUSDT", "1h", config
    )
    second = compute_structural_estimate(scaled, "BTCUSDT", "1h", config)

    assert volume_result == first
    assert second.slope_log_per_hour == pytest.approx(first.slope_log_per_hour)
    assert second.residual_mad_log == pytest.approx(first.residual_mad_log)
    assert second.fit_quality == pytest.approx(first.fit_quality)
    assert second.center_price == pytest.approx(first.center_price * 17.0)


def test_outlier_does_not_reverse_robust_slope():
    hours = np.arange(20.0)
    log_prices = _line(hours, slope=0.01)
    log_prices[9] = np.log(100_000.0)

    result = compute_structural_estimate(
        _frame(log_prices), "BTCUSDT", "1h", _config(window_size=20)
    )

    assert result.slope_log_per_hour > 0.0


def test_repeated_computation_is_deterministic():
    frame = _frame(_line(np.arange(20.0)))
    config = _config(window_size=20)

    first = compute_structural_estimate(frame, "BTCUSDT", "1h", config)
    second = compute_structural_estimate(frame, "BTCUSDT", "1h", config)

    assert first == second


def test_constant_price_truth_and_quality_bounds():
    result = compute_structural_estimate(
        _frame(np.full(20, np.log(250.0))),
        "BTCUSDT",
        "1h",
        _config(window_size=20),
    )

    assert result.slope_log_per_hour == 0.0
    assert result.center_price == pytest.approx(250.0)
    assert result.residual_mad_log == 0.0
    assert result.fit_quality == 1.0
    assert 0.0 <= result.fit_quality <= 1.0


def test_only_last_window_rows_affect_estimate():
    config = _config(window_size=10)
    timestamps = pd.date_range("2024-01-01", periods=15, freq="1h", tz="UTC")
    tail = _line(np.arange(10.0), slope=0.02, intercept=np.log(200.0))
    first_frame = _frame(
        np.concatenate([_line(np.arange(5.0), intercept=np.log(2.0)), tail]),
        timestamps=timestamps,
    )
    second_frame = _frame(
        np.concatenate([_line(np.arange(5.0), slope=-0.4, intercept=np.log(5000.0)), tail]),
        timestamps=timestamps,
    )

    first = compute_structural_estimate(first_frame, "BTCUSDT", "1h", config)
    second = compute_structural_estimate(second_frame, "BTCUSDT", "1h", config)

    assert first == second


@pytest.mark.parametrize("prefix_defect", ["duplicate", "nat", "non_monotonic"])
def test_ignored_prefix_temporal_defects_do_not_affect_estimate(prefix_defect):
    config = _config(window_size=20)
    timestamps = pd.date_range("2024-01-01", periods=25, freq="1h", tz="UTC")
    frame = _frame(_line(np.arange(25.0)), timestamps=timestamps)
    baseline = compute_structural_estimate(frame, "BTCUSDT", "1h", config)

    mutated_index = list(timestamps)
    if prefix_defect == "duplicate":
        mutated_index[0] = timestamps[1]
    elif prefix_defect == "nat":
        mutated_index[0] = pd.NaT
    else:
        mutated_index[0] = timestamps[4]
    changed_prefix = frame.copy()
    changed_prefix.index = pd.DatetimeIndex(mutated_index)

    assert compute_structural_estimate(
        changed_prefix, "BTCUSDT", "1h", config
    ) == baseline


def test_insufficient_history_fails_closed():
    with pytest.raises(ValueError, match="requires 20 rows"):
        compute_structural_estimate(
            _frame(_line(np.arange(19.0))), "BTCUSDT", "1h", _config(window_size=20)
        )


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf, 0.0, -1.0])
def test_invalid_close_fails_closed(invalid):
    prices = np.exp(_line(np.arange(20.0)))
    prices[5] = invalid
    frame = _frame(np.log(np.where(prices > 0, prices, 1.0)))
    frame.iloc[5, frame.columns.get_loc("close")] = invalid

    with pytest.raises(ValueError, match="close values"):
        compute_structural_estimate(frame, "BTCUSDT", "1h", _config(window_size=20))


def test_config_identity_mismatch_fails_closed():
    frame = _frame(_line(np.arange(20.0)))

    with pytest.raises(ValueError, match="asset mismatch"):
        compute_structural_estimate(
            frame, "ETHUSDT", "1h", _config(window_size=20)
        )
    with pytest.raises(ValueError, match="timeframe mismatch"):
        compute_structural_estimate(
            frame, "BTCUSDT", "4h", _config("1h", window_size=20)
        )


@pytest.mark.parametrize(
    ("index_factory", "expected_exception"),
    [
        (lambda index: pd.Index(range(len(index))), TypeError),
        (
            lambda index: pd.DatetimeIndex([index[0], index[0], *index[2:]]),
            ValueError,
        ),
        (
            lambda index: pd.DatetimeIndex([index[0], index[2], index[1], *index[3:]]),
            ValueError,
        ),
        (
            lambda index: pd.DatetimeIndex([index[0], pd.NaT, *index[2:]]),
            ValueError,
        ),
    ],
    ids=["non_datetime", "duplicate", "non_monotonic", "nat"],
)
def test_r1b_temporal_validation_is_reused(index_factory, expected_exception):
    frame = _frame(_line(np.arange(20.0)))
    frame.index = index_factory(frame.index)

    with pytest.raises(expected_exception):
        compute_structural_estimate(
            frame, "BTCUSDT", "1h", _config(window_size=20)
        )


def test_non_utc_and_naive_indexes_normalize_to_aware_utc():
    log_prices = _line(np.arange(20.0))
    aware = _frame(
        log_prices,
        timestamps=pd.date_range(
            "2024-01-01", periods=20, freq="1h", tz="Asia/Kolkata"
        ),
    )
    naive = _frame(
        log_prices,
        timestamps=pd.date_range("2024-01-01", periods=20, freq="1h"),
    )

    aware_result = compute_structural_estimate(
        aware, "BTCUSDT", "1h", _config(window_size=20)
    )
    naive_result = compute_structural_estimate(
        naive, "BTCUSDT", "1h", _config(window_size=20)
    )

    assert aware_result.timestamp.tzinfo is not None
    assert aware_result.timestamp.utcoffset() == dt.timedelta(0)
    assert naive_result.timestamp.tzinfo is not None
    assert naive_result.timestamp.utcoffset() == dt.timedelta(0)


def test_public_api_import_and_contract_shape():
    assert api.compute_structural_estimate is compute_structural_estimate
    assert dataclasses.is_dataclass(StructuralRegressionEstimate)
    assert StructuralRegressionEstimate.__dataclass_params__.frozen is True
    assert [field.name for field in dataclasses.fields(StructuralRegressionEstimate)] == [
        "asset",
        "timeframe",
        "window_started_at",
        "timestamp",
        "observed_through",
        "source_config_hash",
        "estimator_id",
        "window_size",
        "slope_log_per_hour",
        "center_price",
        "residual_mad_log",
        "fit_quality",
    ]
    assert STRUCTURAL_ESTIMATOR_ID == "theil_sen_log_price_all_pairs_v1"
