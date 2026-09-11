from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.execution.regression import (
    RegressionExecutionRequest,
    execute_regression,
)
from libs.regression.api import compute_regression_context
from libs.regression.config.resolver import ConfigResolver

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "libs"
    / "regression"
    / "config"
    / "regression.yaml"
)


def _request() -> RegressionExecutionRequest:
    resolver = ConfigResolver.from_yaml(str(_CONFIG_PATH))
    config = replace(resolver.resolve("BTCUSDT", "1h"), window_size=20)
    index = pd.date_range("2026-01-01", periods=21, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "close": np.linspace(100.0, 120.0, len(index)),
            "volume": np.full(len(index), 100.0),
        },
        index=index,
    )
    return RegressionExecutionRequest(
        frame=frame,
        asset="BTCUSDT",
        timeframe="1h",
        config=config,
        channel_config=resolver.structural_channel_config,
    )


def test_regression_direct_adapter_and_dispatcher_are_exactly_equal() -> None:
    request = _request()
    direct = compute_regression_context(
        request.frame,
        request.asset,
        request.timeframe,
        request.config,
        request.channel_config,
    )

    assert execute_regression(request) == direct
    assert execute_analysis_capability("model.regression", request) == direct


def test_regression_adapter_does_not_mutate_the_input_dataframe() -> None:
    request = _request()
    before = request.frame.copy(deep=True)

    execute_regression(request)

    assert request.frame.equals(before)
    assert request.frame.index.equals(before.index)
    assert tuple(request.frame.columns) == tuple(before.columns)


def test_regression_request_is_frozen_and_duplicate_index_error_propagates() -> None:
    request = _request()
    with pytest.raises(FrozenInstanceError):
        request.asset = "ETHUSDT"

    duplicate_frame = request.frame.copy()
    duplicate_index = list(duplicate_frame.index)
    duplicate_index[-1] = duplicate_index[-2]
    duplicate_frame.index = pd.DatetimeIndex(duplicate_index)
    invalid = RegressionExecutionRequest(
        frame=duplicate_frame,
        asset=request.asset,
        timeframe=request.timeframe,
        config=request.config,
        channel_config=request.channel_config,
    )

    with pytest.raises(Exception) as direct_error:
        compute_regression_context(
            invalid.frame,
            invalid.asset,
            invalid.timeframe,
            invalid.config,
            invalid.channel_config,
        )
    with pytest.raises(type(direct_error.value)) as adapter_error:
        execute_regression(invalid)
    assert str(adapter_error.value) == str(direct_error.value)
