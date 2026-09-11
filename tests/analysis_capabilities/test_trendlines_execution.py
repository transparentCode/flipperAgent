from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.execution.trendlines import (
    TrendlinesExecutionRequest,
    execute_trendlines,
)
from libs.models.trendlines import TrendlineBar, analyze_trendlines


def _history(size: int = 305) -> tuple[TrendlineBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        TrendlineBar(
            closed_at=start + timedelta(hours=index),
            open=100.0 + index * 0.05,
            high=101.0 + index * 0.05,
            low=99.0 + index * 0.05,
            close=100.5 + index * 0.05,
        )
        for index in range(size)
    )


def test_trendlines_direct_adapter_and_dispatcher_are_exactly_equal() -> None:
    history = _history()
    request = TrendlinesExecutionRequest(history)
    direct = analyze_trendlines(history)

    assert execute_trendlines(request) == direct
    assert execute_analysis_capability("model.trendlines", request) == direct
    assert request.history is history


def test_trendlines_adapter_does_not_duplicate_the_300_bar_cap() -> None:
    history = _history(305)
    request = TrendlinesExecutionRequest(history)

    assert execute_trendlines(request) == analyze_trendlines(history[-300:])


def test_trendlines_request_is_frozen_and_native_validation_propagates() -> None:
    request = TrendlinesExecutionRequest(_history(3))
    with pytest.raises(FrozenInstanceError):
        request.history = ()

    invalid = (request.history[1], request.history[0])
    invalid_request = TrendlinesExecutionRequest(invalid)
    with pytest.raises(Exception) as direct_error:
        analyze_trendlines(invalid)
    with pytest.raises(type(direct_error.value)) as adapter_error:
        execute_trendlines(invalid_request)
    assert str(adapter_error.value) == str(direct_error.value)


def test_trendlines_request_rejects_non_tuple_or_non_bar_history() -> None:
    with pytest.raises(TypeError):
        TrendlinesExecutionRequest([])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        TrendlinesExecutionRequest((object(),))  # type: ignore[arg-type]
