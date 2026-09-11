"""Current structural-channel geometry and one-step causal context."""

from __future__ import annotations

from datetime import datetime
from math import isfinite

import numpy as np
import pandas as pd

from .channel import compute_structural_channel
from .config.schema import ResolvedPipelineConfig, StructuralChannelConfig
from .contracts.channel import StructuralChannelEstimate
from .contracts.context_snapshot import (
    RegressionContextSnapshot,
    ResidualRegion,
)

REGRESSION_CONTEXT_ID = "structural_channel_location_one_step_v1"
_FLOAT64_TOLERANCE = np.finfo(np.float64).eps


def _bound_owned_horizon(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Keep only the current and one causal prior structural window."""
    owned = df.iloc[-(window + 1) :]
    if isinstance(owned.index, pd.DatetimeIndex):
        return owned

    labels = list(owned.index)
    datetime_scalar_types = (datetime, np.datetime64, pd.Timestamp)
    if labels and all(isinstance(label, datetime_scalar_types) for label in labels):
        recovered = owned.copy()
        recovered.index = pd.DatetimeIndex(labels)
        return recovered
    return owned


def _classify_region(channel: StructuralChannelEstimate) -> ResidualRegion:
    residual = float(channel.current_residual_log)
    lower_outer = float(channel.lower_outer_residual_log)
    lower_inner = float(channel.lower_inner_residual_log)
    upper_inner = float(channel.upper_inner_residual_log)
    upper_outer = float(channel.upper_outer_residual_log)
    values = (residual, lower_outer, lower_inner, upper_inner, upper_outer)
    if not all(isfinite(value) for value in values):
        raise ValueError("regression context residual geometry must be finite")
    if not lower_outer <= lower_inner <= upper_inner <= upper_outer:
        raise ValueError("regression context residual geometry must be ordered")

    if residual < lower_outer:
        return ResidualRegion.BELOW_OUTER
    if residual < lower_inner:
        return ResidualRegion.LOWER_OUTER_BAND
    if residual <= upper_inner:
        return ResidualRegion.INNER_CHANNEL
    if residual <= upper_outer:
        return ResidualRegion.UPPER_OUTER_BAND
    return ResidualRegion.ABOVE_OUTER


def _outer_channel_position(channel: StructuralChannelEstimate) -> float:
    residual = float(channel.current_residual_log)
    lower_outer = float(channel.lower_outer_residual_log)
    upper_outer = float(channel.upper_outer_residual_log)
    if not all(isfinite(value) for value in (residual, lower_outer, upper_outer)):
        raise ValueError("regression context position geometry must be finite")
    if residual == 0.0:
        return 0.0

    denominator = upper_outer if residual > 0.0 else abs(lower_outer)
    if not isfinite(denominator):
        raise ValueError("regression context position denominator must be finite")
    if abs(denominator) <= _FLOAT64_TOLERANCE:
        if abs(residual) <= _FLOAT64_TOLERANCE:
            return 0.0
        raise ValueError("regression context position denominator is degenerate")
    if denominator < 0.0:
        raise ValueError("regression context position denominator must be positive")

    position = residual / denominator
    if not isfinite(position):
        raise ValueError("regression context position must be finite")
    return float(position)


def _width_geometry(
    channel: StructuralChannelEstimate,
) -> tuple[float, float, float, float]:
    inner_width_log = float(
        channel.upper_inner_residual_log - channel.lower_inner_residual_log
    )
    outer_width_log = float(
        channel.upper_outer_residual_log - channel.lower_outer_residual_log
    )
    center_price = float(channel.structural.center_price)
    inner_width_fraction = float(
        (channel.upper_inner_price - channel.lower_inner_price) / center_price
    )
    outer_width_fraction = float(
        (channel.upper_outer_price - channel.lower_outer_price) / center_price
    )
    widths = (
        inner_width_log,
        outer_width_log,
        inner_width_fraction,
        outer_width_fraction,
    )
    if not all(isfinite(value) and value >= 0.0 for value in widths):
        raise ValueError("regression context widths must be finite and non-negative")
    return widths


def _outer_breaches(
    channel: StructuralChannelEstimate,
) -> tuple[bool, bool]:
    residual = float(channel.current_residual_log)
    upper = residual > float(channel.upper_outer_residual_log)
    lower = residual < float(channel.lower_outer_residual_log)
    if upper and lower:
        raise ValueError("regression context outer breaches cannot both be true")
    return upper, lower


def compute_regression_context(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
    channel_config: StructuralChannelConfig,
) -> RegressionContextSnapshot:
    """Compute current channel geometry and one causal prior transition."""
    owned = _bound_owned_horizon(df, int(config.window_size))
    current = compute_structural_channel(
        owned, asset, timeframe, config, channel_config
    )
    region = _classify_region(current)
    position = _outer_channel_position(current)
    widths = _width_geometry(current)
    upper_breach, lower_breach = _outer_breaches(current)

    previous_region: ResidualRegion | None = None
    reentered_from_upper_outer: bool | None = None
    reentered_from_lower_outer: bool | None = None
    if len(owned) >= int(config.window_size) + 1:
        previous = compute_structural_channel(
            owned.iloc[:-1], asset, timeframe, config, channel_config
        )
        previous_region = _classify_region(previous)
        reentered_from_upper_outer = (
            previous_region is ResidualRegion.ABOVE_OUTER
            and region is not ResidualRegion.ABOVE_OUTER
        )
        reentered_from_lower_outer = (
            previous_region is ResidualRegion.BELOW_OUTER
            and region is not ResidualRegion.BELOW_OUTER
        )

    return RegressionContextSnapshot(
        channel=current,
        context_id=REGRESSION_CONTEXT_ID,
        region=region,
        outer_channel_position=position,
        inner_width_log=widths[0],
        outer_width_log=widths[1],
        inner_width_fraction=widths[2],
        outer_width_fraction=widths[3],
        upper_outer_breach=upper_breach,
        lower_outer_breach=lower_breach,
        previous_region=previous_region,
        reentered_from_upper_outer=reentered_from_upper_outer,
        reentered_from_lower_outer=reentered_from_lower_outer,
    )
