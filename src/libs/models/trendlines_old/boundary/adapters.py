"""Adapters from narrow trendlines fit results to richer boundary contracts."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.trendlines.boundary.contracts import BoundaryResult, QualityMetrics, Ray
from app.trendlines.config import BoundaryAdapterConfig, TrendlinePipelineConfig
from app.trendlines.contracts import Trendline, TrendlineFitResult


def _validate_trendline_boundary_frame(df: pd.DataFrame) -> None:
    required_columns = {"open", "high", "low", "close"}
    missing = sorted(required_columns.difference(df.columns))
    if missing:
        raise ValueError(
            f"Trendlines boundary adapter requires columns {sorted(required_columns)}; missing {missing}"
        )
    if df.empty:
        raise ValueError("Trendlines boundary adapter requires a non-empty dataframe")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Trendlines boundary adapter requires a DatetimeIndex")


def _mean_true_range(df: pd.DataFrame, window: int = 14) -> np.ndarray:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    previous_close = np.concatenate(([close[0]], close[:-1]))
    true_range = np.maximum.reduce(
        [
            high - low,
            np.abs(high - previous_close),
            np.abs(low - previous_close),
        ]
    )
    return pd.Series(true_range, index=df.index).rolling(window, min_periods=1).mean().to_numpy(dtype=float)


def _detect_boundary_interaction(
    price: float,
    support_rays: list[Ray],
    resistance_rays: list[Ray],
    hull_floor: float,
    hull_ceiling: float,
    atr_values: np.ndarray,
    interaction_tolerance_atr: float,
) -> str:
    mean_atr = float(np.nanmean(atr_values))
    tolerance = interaction_tolerance_atr * max(mean_atr, 1e-9)
    current_bar = float(len(atr_values) - 1)

    if not np.isnan(hull_floor) and price < hull_floor - tolerance:
        return "STRUCTURAL_BREAKDOWN"
    if not np.isnan(hull_ceiling) and price > hull_ceiling + tolerance:
        return "STRUCTURAL_BREAKOUT"

    if support_rays:
        best_support = max(support_rays, key=lambda ray: ray.score)
        if abs(price - best_support.value_at(current_bar)) < tolerance:
            return "GEOMETRIC_BOUNCE_SUPPORT"

    if resistance_rays:
        best_resistance = max(resistance_rays, key=lambda ray: ray.score)
        if abs(price - best_resistance.value_at(current_bar)) < tolerance:
            return "GEOMETRIC_BOUNCE_RESISTANCE"

    return "NONE"


def trendline_to_boundary_ray(
    line: Trendline,
    *,
    index: pd.DatetimeIndex,
    extractor_name: str | None = None,
    kernel_prefix: str = "trendlines",
) -> Ray:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("trendline_to_boundary_ray requires a DatetimeIndex")
    if not (0 <= line.start_index < len(index)) or not (0 <= line.end_index < len(index)):
        raise ValueError("Trendline indices must fall within the provided index")

    method = (line.method or "line").strip() or "line"
    metadata = dict(line.metadata)
    metadata.setdefault("source", "trendlines")
    metadata["trendline_method"] = method
    if extractor_name:
        metadata["extractor"] = extractor_name

    return Ray(
        start_time=pd.Timestamp(index[line.start_index]),
        end_time=pd.Timestamp(index[line.end_index]),
        start_price=float(line.start_value),
        end_price=float(line.end_value),
        slope=float(line.slope),
        intercept=float(line.intercept),
        touch_count=int(line.touch_count),
        is_support=bool(line.is_support),
        kernel=f"{kernel_prefix}:{method}",
        score=float(line.score),
        r_squared=float(metadata.get("r_squared", 0.0)),
        metadata=metadata,
    )


def build_boundary_result_from_trendline_result(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    trendline_result: TrendlineFitResult,
    trendline_config: TrendlinePipelineConfig | None = None,
    interaction_tolerance_atr: float | None = None,
    atr_window: int | None = None,
) -> BoundaryResult:
    _validate_trendline_boundary_frame(df)

    boundary_params = trendline_config.boundary_params if trendline_config is not None else {}
    
    if trendline_config is not None and getattr(trendline_config, "trendlines_config", None):
        cfg = trendline_config.trendlines_config.boundary
    else:
        cfg = BoundaryAdapterConfig()

    resolved_interaction_tolerance_atr = float(
        interaction_tolerance_atr
        if interaction_tolerance_atr is not None
        else boundary_params.get("interaction_tolerance_atr", cfg.interaction_tolerance_atr)
    )
    resolved_atr_window = int(
        atr_window if atr_window is not None else boundary_params.get("atr_window", cfg.atr_window)
    )
    if resolved_interaction_tolerance_atr < 0:
        raise ValueError("interaction_tolerance_atr must be >= 0")
    if resolved_atr_window < 1:
        raise ValueError("atr_window must be >= 1")

    pipeline_metadata = trendline_result.metadata.get("pipeline", {})
    extractor_name = pipeline_metadata.get("extractor") if isinstance(pipeline_metadata, dict) else None

    support_rays = [
        trendline_to_boundary_ray(line, index=df.index, extractor_name=extractor_name)
        for line in trendline_result.support_lines
    ]
    resistance_rays = [
        trendline_to_boundary_ray(line, index=df.index, extractor_name=extractor_name)
        for line in trendline_result.resistance_lines
    ]

    current_bar = float(len(df) - 1)
    hull_floor = float(max(ray.value_at(current_bar) for ray in support_rays)) if support_rays else np.nan
    hull_ceiling = float(min(ray.value_at(current_bar) for ray in resistance_rays)) if resistance_rays else np.nan
    atr_values = _mean_true_range(df, window=resolved_atr_window)
    interaction = _detect_boundary_interaction(
        float(df["close"].iloc[-1]),
        support_rays,
        resistance_rays,
        hull_floor,
        hull_ceiling,
        atr_values,
        resolved_interaction_tolerance_atr,
    )
    quality_metrics = QualityMetrics.from_result(
        support_rays,
        resistance_rays,
        hull_floor,
        hull_ceiling,
        float(np.nanmean(atr_values)),
    )

    trendlines_metadata = dict(trendline_result.metadata)
    trendlines_metadata["adapter"] = {
        "atr_window": resolved_atr_window,
        "interaction_tolerance_atr": resolved_interaction_tolerance_atr,
    }
    if trendline_config is not None:
        trendlines_metadata["config"] = trendline_config.to_dict()

    return BoundaryResult(
        asset=asset,
        timeframe=timeframe,
        timestamp=df.index[-1].to_pydatetime(),
        active_support_rays=support_rays,
        active_resistance_rays=resistance_rays,
        convex_hull_floor=hull_floor,
        convex_hull_ceiling=hull_ceiling,
        interaction=interaction,
        is_valid=bool(trendline_result.is_valid),
        quality_metrics=quality_metrics,
        metadata={
            "source": "trendlines",
            "trendlines": trendlines_metadata,
        },
    )


__all__ = [
    "build_boundary_result_from_trendline_result",
    "trendline_to_boundary_ray",
]