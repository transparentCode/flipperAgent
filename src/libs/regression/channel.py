"""Residual-quantile channel geometry around the approved structural fit."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from .config.schema import ResolvedPipelineConfig, StructuralChannelConfig
from .contracts.channel import StructuralChannelEstimate
from .structural import compute_structural_estimate
from .temporal import normalize_timestamps

STRUCTURAL_CHANNEL_ID = "asymmetric_residual_quantiles_linear_v1"
_NESTING_EPSILON = np.finfo(np.float64).eps


def channel_config_fingerprint(config: StructuralChannelConfig) -> str:
    """Return the deterministic hash of the canonical channel policy."""
    canonical = json.dumps(
        {
            "inner_coverage": config.inner_coverage,
            "outer_coverage": config.outer_coverage,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _residuals(
    selected: pd.DataFrame,
    structural_slope: float,
    structural_center: float,
) -> np.ndarray:
    timestamps = normalize_timestamps(selected.index)
    close = selected["close"].to_numpy(dtype=np.float64, copy=False)
    if not np.all(np.isfinite(close)):
        raise ValueError("structural channel close values must be finite")
    if np.any(close <= 0.0):
        raise ValueError("structural channel close values must be positive")
    if not np.isfinite(structural_center) or structural_center <= 0.0:
        raise ValueError("structural channel center price must be finite")
    if not np.isfinite(structural_slope):
        raise ValueError("structural channel slope must be finite")

    elapsed_hours = (timestamps - timestamps[0]) / np.timedelta64(1, "h")
    elapsed_hours = np.asarray(elapsed_hours, dtype=np.float64)
    center_log = float(np.log(structural_center))
    fitted_log_prices = center_log + structural_slope * (
        elapsed_hours - elapsed_hours[-1]
    )
    residuals = np.log(close) - fitted_log_prices
    if not np.all(np.isfinite(residuals)):
        raise ValueError("structural channel residuals must be finite")
    return residuals


def _quantile_offsets(residuals: np.ndarray, coverage: float) -> tuple[float, float]:
    tail = (1.0 - coverage) / 2.0
    lower = float(np.quantile(residuals, tail, method="linear"))
    upper = float(np.quantile(residuals, 1.0 - tail, method="linear"))
    if not np.isfinite(lower) or not np.isfinite(upper):
        raise ValueError("structural channel quantile offsets must be finite")
    return lower, upper


def _validate_geometry(
    center_price: float,
    lower_inner: float,
    upper_inner: float,
    lower_outer: float,
    upper_outer: float,
) -> None:
    prices = np.asarray(
        [
            center_price,
            lower_inner,
            upper_inner,
            lower_outer,
            upper_outer,
        ],
        dtype=np.float64,
    )
    if not np.all(np.isfinite(prices)) or np.any(prices <= 0.0):
        raise ValueError("structural channel prices must be finite and positive")

    scale = max(1.0, float(np.max(np.abs(prices))))
    tolerance = _NESTING_EPSILON * scale
    if (
        lower_outer > lower_inner + tolerance
        or lower_inner > center_price + tolerance
        or center_price > upper_inner + tolerance
        or upper_inner > upper_outer + tolerance
    ):
        raise ValueError("structural channel prices must be nested")


def compute_structural_channel(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
    channel_config: StructuralChannelConfig,
) -> StructuralChannelEstimate:
    """Compute residual-quantile geometry around one structural estimate."""
    structural = compute_structural_estimate(df, asset, timeframe, config)
    selected = df.iloc[-int(config.window_size) :]
    residuals = _residuals(
        selected,
        structural.slope_log_per_hour,
        structural.center_price,
    )

    lower_inner_residual, upper_inner_residual = _quantile_offsets(
        residuals, channel_config.inner_coverage
    )
    lower_outer_residual, upper_outer_residual = _quantile_offsets(
        residuals, channel_config.outer_coverage
    )
    center_price = structural.center_price
    lower_inner_price = float(center_price * np.exp(lower_inner_residual))
    upper_inner_price = float(center_price * np.exp(upper_inner_residual))
    lower_outer_price = float(center_price * np.exp(lower_outer_residual))
    upper_outer_price = float(center_price * np.exp(upper_outer_residual))
    _validate_geometry(
        center_price,
        lower_inner_price,
        upper_inner_price,
        lower_outer_price,
        upper_outer_price,
    )

    return StructuralChannelEstimate(
        structural=structural,
        channel_id=STRUCTURAL_CHANNEL_ID,
        channel_config_hash=channel_config_fingerprint(channel_config),
        inner_coverage=channel_config.inner_coverage,
        outer_coverage=channel_config.outer_coverage,
        lower_inner_residual_log=lower_inner_residual,
        upper_inner_residual_log=upper_inner_residual,
        lower_outer_residual_log=lower_outer_residual,
        upper_outer_residual_log=upper_outer_residual,
        lower_inner_price=lower_inner_price,
        upper_inner_price=upper_inner_price,
        lower_outer_price=lower_outer_price,
        upper_outer_price=upper_outer_price,
        current_residual_log=float(residuals[-1]),
    )
