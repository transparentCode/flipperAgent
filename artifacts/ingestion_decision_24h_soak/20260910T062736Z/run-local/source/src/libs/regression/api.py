"""Public facade for the certified structural regression context package."""

from __future__ import annotations

import pandas as pd

from .channel import compute_structural_channel as _compute_structural_channel
from .config.schema import ResolvedPipelineConfig, StructuralChannelConfig
from .context_snapshot import compute_regression_context as _compute_regression_context
from .contracts.channel import StructuralChannelEstimate
from .contracts.context_snapshot import RegressionContextSnapshot
from .contracts.structural import StructuralRegressionEstimate
from .structural import compute_structural_estimate as _compute_structural_estimate


def compute_structural_estimate(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
) -> StructuralRegressionEstimate:
    """Compute the standalone causal structural log-price estimate."""
    return _compute_structural_estimate(df, asset, timeframe, config)


def compute_structural_channel(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
    channel_config: StructuralChannelConfig,
) -> StructuralChannelEstimate:
    """Compute residual-quantile channel geometry around the structural fit."""
    return _compute_structural_channel(df, asset, timeframe, config, channel_config)


def compute_regression_context(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
    channel_config: StructuralChannelConfig,
) -> RegressionContextSnapshot:
    """Compute descriptive channel geometry and one-step causal context."""
    return _compute_regression_context(df, asset, timeframe, config, channel_config)
