"""Adapters from narrow trendlines fit results to richer boundary contracts."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.trendlines.boundary.contracts import BoundaryResult, QualityMetrics, Ray
from app.trendlines.config import BoundaryAdapterConfig, TrendlinePipelineConfig
from app.trendlines.contracts import Trendline, TrendlineFitResult


_CHANNEL_COMPRESSION_WIDTH_ATR = 3.0
_MID_CHANNEL_LOWER = 0.35
_MID_CHANNEL_UPPER = 0.65
_PRESSURE_LOWER = 0.25
_PRESSURE_UPPER = 0.75


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


def _distance_atr(price: float, level: float, atr: float, *, support: bool) -> float:
    if not np.isfinite(level):
        return np.nan
    distance = price - level if support else level - price
    return float(distance / max(atr, 1e-9))


def _hull_position(price: float, hull_floor: float, hull_ceiling: float) -> float:
    if not np.isfinite(hull_floor) or not np.isfinite(hull_ceiling) or hull_ceiling <= hull_floor:
        return np.nan
    return float(max(0.0, min(1.0, (price - hull_floor) / (hull_ceiling - hull_floor))))


def _build_boundary_context(
    *,
    price: float,
    support_rays: list[Ray],
    resistance_rays: list[Ray],
    hull_floor: float,
    hull_ceiling: float,
    atr_values: np.ndarray,
    interaction_tolerance_atr: float,
    hull_width_atr: float,
) -> dict[str, object]:
    latest_atr = float(max(atr_values[-1], 1e-9))
    mean_atr = float(max(np.nanmean(atr_values), 1e-9))
    tolerance_price = float(interaction_tolerance_atr * latest_atr)
    current_bar = float(len(atr_values) - 1)

    best_support = max(support_rays, key=lambda ray: ray.score) if support_rays else None
    best_resistance = max(resistance_rays, key=lambda ray: ray.score) if resistance_rays else None
    support_level = best_support.value_at(current_bar) if best_support else np.nan
    resistance_level = best_resistance.value_at(current_bar) if best_resistance else np.nan
    support_distance_atr = _distance_atr(price, support_level, latest_atr, support=True)
    resistance_distance_atr = _distance_atr(price, resistance_level, latest_atr, support=False)
    hull_pos = _hull_position(price, hull_floor, hull_ceiling)

    has_closed_channel = bool(
        support_rays
        and resistance_rays
        and np.isfinite(hull_floor)
        and np.isfinite(hull_ceiling)
    )
    above_channel = bool(np.isfinite(hull_ceiling) and price > hull_ceiling + tolerance_price)
    below_channel = bool(np.isfinite(hull_floor) and price < hull_floor - tolerance_price)
    inside_channel = bool(has_closed_channel and not above_channel and not below_channel)
    near_support = bool(np.isfinite(support_distance_atr) and abs(support_distance_atr) <= interaction_tolerance_atr)
    near_resistance = bool(np.isfinite(resistance_distance_atr) and abs(resistance_distance_atr) <= interaction_tolerance_atr)
    mid_channel_noise = bool(inside_channel and np.isfinite(hull_pos) and _MID_CHANNEL_LOWER <= hull_pos <= _MID_CHANNEL_UPPER)
    channel_compression = bool(
        np.isfinite(hull_width_atr)
        and hull_width_atr > 0.0
        and hull_width_atr <= _CHANNEL_COMPRESSION_WIDTH_ATR
    )
    upper_channel_pressure = bool(inside_channel and np.isfinite(hull_pos) and hull_pos >= _PRESSURE_UPPER)
    lower_channel_pressure = bool(inside_channel and np.isfinite(hull_pos) and hull_pos <= _PRESSURE_LOWER)

    if above_channel:
        state = "above_channel"
    elif below_channel:
        state = "below_channel"
    elif near_support:
        state = "near_support"
    elif near_resistance:
        state = "near_resistance"
    elif upper_channel_pressure:
        state = "upper_channel_pressure"
    elif lower_channel_pressure:
        state = "lower_channel_pressure"
    elif mid_channel_noise:
        state = "mid_channel_noise"
    elif inside_channel:
        state = "inside_channel"
    elif support_rays and not resistance_rays:
        state = "support_only_context"
    elif resistance_rays and not support_rays:
        state = "resistance_only_context"
    else:
        state = "unknown"

    compression_score = 0.0
    if np.isfinite(hull_width_atr) and hull_width_atr > 0:
        compression_score = float(max(0.0, min(1.0, 1.0 - hull_width_atr / _CHANNEL_COMPRESSION_WIDTH_ATR)))

    return {
        "current_price": float(price),
        "latest_atr": latest_atr,
        "mean_atr": mean_atr,
        "interaction_tolerance_atr": float(interaction_tolerance_atr),
        "interaction_tolerance_price": tolerance_price,
        "support_level": float(support_level) if np.isfinite(support_level) else np.nan,
        "resistance_level": float(resistance_level) if np.isfinite(resistance_level) else np.nan,
        "support_distance_atr": support_distance_atr,
        "resistance_distance_atr": resistance_distance_atr,
        "hull_width_atr": float(hull_width_atr) if np.isfinite(hull_width_atr) else np.nan,
        "hull_position": hull_pos,
        "market_position_state": state,
        "inside_channel": inside_channel,
        "above_channel": above_channel,
        "below_channel": below_channel,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "mid_channel_noise": mid_channel_noise,
        "channel_compression": channel_compression,
        "channel_compression_score": compression_score,
        "upper_channel_pressure": upper_channel_pressure,
        "lower_channel_pressure": lower_channel_pressure,
    }


def _clip01(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def _line_coverage_score(line: Trendline, index_len: int) -> float:
    raw = line.metadata.get("coverage")
    if raw is not None:
        return _clip01(float(raw))
    return _clip01((line.end_index - line.start_index) / max(index_len - 1, 1))


def _residual_quality_score(line: Trendline) -> float:
    metadata = line.metadata
    r_squared = float(metadata.get("r_squared", 0.0))
    inlier_ratio = float(metadata.get("inlier_ratio", 0.0))
    if r_squared > 0.0 or inlier_ratio > 0.0:
        return _clip01(max(r_squared, inlier_ratio))
    return _clip01(float(line.score))


def _line_quality_summary(line: Trendline, index_len: int) -> dict[str, float | str]:
    touch_score = _clip01(line.touch_count / 4.0)
    coverage_score = _line_coverage_score(line, index_len)
    residual_score = _residual_quality_score(line)
    recency_score = _clip01(line.end_index / max(index_len - 1, 1))
    cut_fraction = float(line.metadata.get("cut_fraction", 0.0))
    no_cut_score = _clip01(1.0 - cut_fraction)
    raw_score = _clip01(float(line.score))

    normalized = (
        0.30 * coverage_score
        + 0.25 * touch_score
        + 0.20 * residual_score
        + 0.15 * no_cut_score
        + 0.10 * recency_score
    )
    normalized = _clip01(normalized)
    components: dict[str, float | str] = {
        "method": line.method or "unknown",
        "raw_score": raw_score,
        "coverage_score": coverage_score,
        "touch_score": touch_score,
        "residual_quality_score": residual_score,
        "no_cut_score": no_cut_score,
        "recency_score": recency_score,
        "normalized_quality_score": normalized,
    }
    return components


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
    quality_components = _line_quality_summary(line, len(index))
    metadata.setdefault("source", "trendlines")
    metadata["trendline_method"] = method
    metadata["quality_components"] = quality_components
    metadata["normalized_quality_score"] = float(quality_components["normalized_quality_score"])
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
    boundary_context = _build_boundary_context(
        price=float(df["close"].iloc[-1]),
        support_rays=support_rays,
        resistance_rays=resistance_rays,
        hull_floor=hull_floor,
        hull_ceiling=hull_ceiling,
        atr_values=atr_values,
        interaction_tolerance_atr=resolved_interaction_tolerance_atr,
        hull_width_atr=quality_metrics.hull_width_atr if quality_metrics is not None else np.nan,
    )
    boundary_context["mean_normalized_quality"] = quality_metrics.mean_normalized_quality
    boundary_context["mean_support_quality"] = quality_metrics.mean_support_quality
    boundary_context["mean_resistance_quality"] = quality_metrics.mean_resistance_quality
    boundary_context["best_support_quality"] = (
        max((ray.normalized_quality_score for ray in support_rays), default=0.0)
    )
    boundary_context["best_resistance_quality"] = (
        max((ray.normalized_quality_score for ray in resistance_rays), default=0.0)
    )

    trendlines_metadata = dict(trendline_result.metadata)
    trendlines_metadata.setdefault("structure", trendline_result.structure_summary())
    trendlines_metadata["adapter"] = {
        "atr_window": resolved_atr_window,
        "interaction_tolerance_atr": resolved_interaction_tolerance_atr,
    }
    boundary_structure = {
        "n_support_rays": len(support_rays),
        "n_resistance_rays": len(resistance_rays),
        "has_support": bool(support_rays),
        "has_resistance": bool(resistance_rays),
        "has_both_sides": bool(support_rays and resistance_rays),
        "has_closed_channel": bool(
            support_rays
            and resistance_rays
            and np.isfinite(hull_floor)
            and np.isfinite(hull_ceiling)
        ),
        "is_one_sided_structure": bool(support_rays) != bool(resistance_rays),
        "structure_state": (
            "closed_channel"
            if support_rays and resistance_rays and np.isfinite(hull_floor) and np.isfinite(hull_ceiling)
            else "support_only"
            if support_rays and not resistance_rays
            else "resistance_only"
            if resistance_rays and not support_rays
            else "two_sided_unbounded"
            if support_rays and resistance_rays
            else "empty"
        ),
    }
    quality_summary = {
        "mean_normalized_quality": quality_metrics.mean_normalized_quality,
        "mean_support_quality": quality_metrics.mean_support_quality,
        "mean_resistance_quality": quality_metrics.mean_resistance_quality,
        "best_support_quality": boundary_context["best_support_quality"],
        "best_resistance_quality": boundary_context["best_resistance_quality"],
    }
    trendlines_metadata["normalized_quality"] = quality_summary
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
            "structure": boundary_structure,
            "context": boundary_context,
            "normalized_quality": quality_summary,
            "trendlines": trendlines_metadata,
        },
    )


__all__ = [
    "build_boundary_result_from_trendline_result",
    "trendline_to_boundary_ray",
]