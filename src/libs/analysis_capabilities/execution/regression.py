"""Thin execution adapter for the canonical regression context API."""

from dataclasses import dataclass

import pandas as pd

from libs.regression.api import compute_regression_context
from libs.regression.config.schema import (
    ResolvedPipelineConfig,
    StructuralChannelConfig,
)
from libs.regression.contracts import RegressionContextSnapshot


@dataclass(frozen=True, slots=True)
class RegressionExecutionRequest:
    """Native request borrowing, not deep-freezing, its DataFrame contents."""

    frame: pd.DataFrame
    asset: str
    timeframe: str
    config: ResolvedPipelineConfig
    channel_config: StructuralChannelConfig


def execute_regression(
    request: RegressionExecutionRequest,
) -> RegressionContextSnapshot:
    """Run the native regression context function without frame translation."""

    if not isinstance(request, RegressionExecutionRequest):
        raise TypeError("request must be RegressionExecutionRequest")
    return compute_regression_context(
        request.frame,
        request.asset,
        request.timeframe,
        request.config,
        request.channel_config,
    )


__all__ = ("RegressionExecutionRequest", "execute_regression")
