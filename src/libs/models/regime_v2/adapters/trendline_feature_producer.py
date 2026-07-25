"""Trendline market-structure adapter for RegimeV2.

The trendlines package owns pivot extraction, line fitting, and boundary/ray
classification.  RegimeV2 should consume only a compact, normalized feature
snapshot so playbook logic does not depend on trendline internals.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_v2.features.utils import true_range
from libs.models.trendlines import fit_and_signal, fit_trendlines_to_boundary
from libs.models.trendlines.boundary import TrendlineSnapshotHistory
from libs.models.trendlines.signals.utils import count_persistent_rays, series_acceleration

_REQUIRED_OHLCV = ("open", "high", "low", "close")
_INTERACTION_DIRECTION = {
    "GEOMETRIC_BOUNCE_SUPPORT": 1.0,
    "GEOMETRIC_BOUNCE_RESISTANCE": -1.0,
    "STRUCTURAL_BREAKOUT": 1.0,
    "STRUCTURAL_BREAKDOWN": -1.0,
}


@dataclass(frozen=True)
class TrendlineFeatureConfig:
    """Runtime knobs for the RegimeV2 trendline adapter."""

    extractor: str = "fractal"
    fitter: str = "ensemble"
    min_bars: int = 30
    atr_window: int = 14
    pathfinding_line_fit_mode: str = "endpoint"
    include_native_signals: bool = False
    history_limit: int = 5
    record_snapshot: bool = False


class TrendlineFeatureProducer:
    """Produce flat trendline context features for live/shadow pipelines."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config: TrendlineFeatureConfig | None = None,
        snapshot_history: TrendlineSnapshotHistory | None = None,
    ) -> None:
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.config = config or TrendlineFeatureConfig()
        self.snapshot_history = snapshot_history

    def analyze(
        self,
        price_history: Sequence[Mapping[str, Any]],
        latest_features: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        df = pd.DataFrame(list(price_history))
        if latest_features and not df.empty:
            last_idx = df.index[-1]
            for key, value in latest_features.items():
                if key in {"spread_bps", "bid_ask_imbalance", "depth_ratio"}:
                    df.loc[last_idx, key] = value
        return compute_trendline_context_features(
            df,
            asset=self.asset,
            timeframe=self.timeframe,
            config=self.config,
            snapshot_history=self.snapshot_history,
        )


def compute_trendline_context_features(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: TrendlineFeatureConfig | None = None,
    snapshot_history: TrendlineSnapshotHistory | None = None,
) -> dict[str, Any]:
    """Return a compact latest-bar trendline feature snapshot.

    The function is fail-soft by design.  Missing/insufficient data returns a
    neutral invalid snapshot instead of raising inside a live feature pipeline.
    """

    cfg = config or TrendlineFeatureConfig()
    base = _neutral_features(asset=asset, timeframe=timeframe)

    missing = [column for column in _REQUIRED_OHLCV if column not in df.columns]
    if missing:
        return {**base, "trendline_error": f"missing_columns:{','.join(missing)}"}
    if len(df) < cfg.min_bars:
        return {**base, "trendline_error": f"insufficient_bars:{len(df)}<{cfg.min_bars}"}

    prepared = _prepare_ohlcv_index(df, timeframe)
    try:
        fitter_kwargs = _build_fitter_kwargs(cfg)
        signal_history = _signal_history(
            snapshot_history,
            asset=asset,
            timeframe=timeframe,
            timestamp=prepared.index[-1].to_pydatetime(),
            limit=cfg.history_limit,
        )
        output = (
            fit_and_signal(
                prepared,
                asset=asset,
                timeframe=timeframe,
                extractor=cfg.extractor,
                fitter=cfg.fitter,
                fitter_kwargs=fitter_kwargs,
                history=signal_history,
                context={
                    "ohlcv": prepared,
                    "atr": _latest_atr(prepared, cfg.atr_window),
                    "volume_is_trustworthy": "volume" in prepared.columns,
                },
            )
            if cfg.include_native_signals
            else fit_trendlines_to_boundary(
                prepared,
                asset=asset,
                timeframe=timeframe,
                extractor=cfg.extractor,
                fitter=cfg.fitter,
                fitter_kwargs=fitter_kwargs,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive live-pipeline guard
        return {**base, "trendline_error": f"{exc.__class__.__name__}:{exc}"}

    boundary = output.boundary_result
    if boundary is None or not boundary.is_valid:
        return {**base, "trendline_error": "invalid_boundary"}
    if snapshot_history is not None and cfg.record_snapshot:
        snapshot_history.add(boundary, metadata={"source": "regime_v2_trendline_adapter"})

    close = float(prepared["close"].iloc[-1])
    atr = _latest_atr(prepared, cfg.atr_window)
    current_bar = float(len(prepared) - 1)
    support = boundary.best_support
    resistance = boundary.best_resistance
    qm = boundary.quality_metrics
    context = boundary.boundary_context

    support_level = float(context.get("support_level", support.value_at(current_bar) if support else np.nan))
    resistance_level = float(context.get("resistance_level", resistance.value_at(current_bar) if resistance else np.nan))
    hull_width_atr = float(context.get("hull_width_atr", float(qm.hull_width_atr) if qm is not None else np.nan))
    interaction = str(boundary.interaction or "NONE")

    features: dict[str, Any] = {
        **base,
        "trendline_valid": 1.0,
        "trendline_error": None,
        "trendline_interaction": interaction,
        "trendline_interaction_direction": float(_INTERACTION_DIRECTION.get(interaction, 0.0)),
        "trendline_is_breakout": 1.0 if interaction == "STRUCTURAL_BREAKOUT" else 0.0,
        "trendline_is_breakdown": 1.0 if interaction == "STRUCTURAL_BREAKDOWN" else 0.0,
        "trendline_is_support_bounce": 1.0 if interaction == "GEOMETRIC_BOUNCE_SUPPORT" else 0.0,
        "trendline_is_resistance_bounce": 1.0 if interaction == "GEOMETRIC_BOUNCE_RESISTANCE" else 0.0,
        "trendline_structure_state": boundary.structure_state,
        "trendline_has_support": 1.0 if boundary.has_support else 0.0,
        "trendline_has_resistance": 1.0 if boundary.has_resistance else 0.0,
        "trendline_has_both_sides": 1.0 if boundary.has_both_sides else 0.0,
        "trendline_has_closed_channel": 1.0 if boundary.has_closed_channel else 0.0,
        "trendline_is_one_sided_structure": 1.0 if boundary.is_one_sided_structure else 0.0,
        "trendline_market_position_state": str(context.get("market_position_state", boundary.market_position_state)),
        "trendline_inside_channel": 1.0 if context.get("inside_channel", False) else 0.0,
        "trendline_above_channel": 1.0 if context.get("above_channel", False) else 0.0,
        "trendline_below_channel": 1.0 if context.get("below_channel", False) else 0.0,
        "trendline_near_support": 1.0 if context.get("near_support", False) else 0.0,
        "trendline_near_resistance": 1.0 if context.get("near_resistance", False) else 0.0,
        "trendline_mid_channel_noise": 1.0 if context.get("mid_channel_noise", False) else 0.0,
        "trendline_upper_channel_pressure": 1.0 if context.get("upper_channel_pressure", False) else 0.0,
        "trendline_lower_channel_pressure": 1.0 if context.get("lower_channel_pressure", False) else 0.0,
        "trendline_support_level": support_level,
        "trendline_resistance_level": resistance_level,
        "trendline_latest_atr": float(context.get("latest_atr", atr)),
        "trendline_mean_atr": float(context.get("mean_atr", atr)),
        "trendline_interaction_tolerance_price": float(context.get("interaction_tolerance_price", np.nan)),
        "trendline_support_distance_atr": float(context.get("support_distance_atr", _distance_atr(close, support_level, atr, support=True))),
        "trendline_resistance_distance_atr": float(context.get("resistance_distance_atr", _distance_atr(close, resistance_level, atr, support=False))),
        "trendline_hull_width_atr": hull_width_atr,
        "trendline_channel_compression": _compression_from_width(hull_width_atr),
        "trendline_channel_compression_score": float(context.get("channel_compression_score", _compression_from_width(hull_width_atr))),
        "trendline_hull_position": float(context.get("hull_position", _hull_position(close, boundary.convex_hull_floor, boundary.convex_hull_ceiling))),
        "trendline_support_score": float(support.score) if support else 0.0,
        "trendline_resistance_score": float(resistance.score) if resistance else 0.0,
        "trendline_support_quality_score": float(context.get("best_support_quality", boundary.best_support_quality)),
        "trendline_resistance_quality_score": float(context.get("best_resistance_quality", boundary.best_resistance_quality)),
        "trendline_mean_normalized_quality": float(context.get("mean_normalized_quality", boundary.mean_normalized_quality)),
        "trendline_mean_support_quality": float(context.get("mean_support_quality", qm.mean_support_quality if qm is not None else 0.0)),
        "trendline_mean_resistance_quality": float(context.get("mean_resistance_quality", qm.mean_resistance_quality if qm is not None else 0.0)),
        "trendline_support_touch_count": float(support.touch_count) if support else 0.0,
        "trendline_resistance_touch_count": float(resistance.touch_count) if resistance else 0.0,
        "trendline_support_slope_atr": _slope_atr(support, atr),
        "trendline_resistance_slope_atr": _slope_atr(resistance, atr),
        "trendline_support_ray_count": float(len(boundary.active_support_rays)),
        "trendline_resistance_ray_count": float(len(boundary.active_resistance_rays)),
        "trendline_mean_score": float(qm.mean_score) if qm is not None else 0.0,
        "trendline_mean_touch_count": float(qm.mean_touch_count) if qm is not None else 0.0,
        "trendline_mean_r_squared": float(qm.mean_r_squared) if qm is not None else 0.0,
        "trendline_history_count": float(len(signal_history)),
        "trendline_snapshot_recorded": 1.0 if snapshot_history is not None and cfg.record_snapshot else 0.0,
        **_temporal_context_features(boundary, signal_history),
        "trendline_composite_direction": float(output.composite_direction),
        "trendline_composite_confidence": float(output.composite_confidence),
    }
    features.update(_trendline_annotation_features(features))
    return features


def _neutral_features(*, asset: str, timeframe: str) -> dict[str, Any]:
    return {
        "trendline_asset": asset.upper(),
        "trendline_timeframe": timeframe,
        "trendline_valid": 0.0,
        "trendline_error": None,
        "trendline_interaction": "NONE",
        "trendline_interaction_direction": 0.0,
        "trendline_is_breakout": 0.0,
        "trendline_is_breakdown": 0.0,
        "trendline_is_support_bounce": 0.0,
        "trendline_is_resistance_bounce": 0.0,
        "trendline_structure_state": "empty",
        "trendline_has_support": 0.0,
        "trendline_has_resistance": 0.0,
        "trendline_has_both_sides": 0.0,
        "trendline_has_closed_channel": 0.0,
        "trendline_is_one_sided_structure": 0.0,
        "trendline_market_position_state": "unknown",
        "trendline_inside_channel": 0.0,
        "trendline_above_channel": 0.0,
        "trendline_below_channel": 0.0,
        "trendline_near_support": 0.0,
        "trendline_near_resistance": 0.0,
        "trendline_mid_channel_noise": 0.0,
        "trendline_upper_channel_pressure": 0.0,
        "trendline_lower_channel_pressure": 0.0,
        "trendline_support_level": np.nan,
        "trendline_resistance_level": np.nan,
        "trendline_latest_atr": np.nan,
        "trendline_mean_atr": np.nan,
        "trendline_interaction_tolerance_price": np.nan,
        "trendline_support_distance_atr": np.nan,
        "trendline_resistance_distance_atr": np.nan,
        "trendline_hull_width_atr": np.nan,
        "trendline_channel_compression": 0.0,
        "trendline_channel_compression_score": 0.0,
        "trendline_hull_position": 0.5,
        "trendline_support_score": 0.0,
        "trendline_resistance_score": 0.0,
        "trendline_support_quality_score": 0.0,
        "trendline_resistance_quality_score": 0.0,
        "trendline_mean_normalized_quality": 0.0,
        "trendline_mean_support_quality": 0.0,
        "trendline_mean_resistance_quality": 0.0,
        "trendline_support_touch_count": 0.0,
        "trendline_resistance_touch_count": 0.0,
        "trendline_support_slope_atr": 0.0,
        "trendline_resistance_slope_atr": 0.0,
        "trendline_support_ray_count": 0.0,
        "trendline_resistance_ray_count": 0.0,
        "trendline_mean_score": 0.0,
        "trendline_mean_touch_count": 0.0,
        "trendline_mean_r_squared": 0.0,
        "trendline_history_count": 0.0,
        "trendline_snapshot_recorded": 0.0,
        **_neutral_temporal_features(),
        **_neutral_annotation_features(),
        "trendline_composite_direction": 0.0,
        "trendline_composite_confidence": 0.0,
    }


def _neutral_annotation_features() -> dict[str, Any]:
    return {
        "trendline_risk_context": "invalid_or_missing",
        "trendline_confidence_annotation": "neutral",
        "trendline_annotation_reason": "no_valid_trendline_context",
        "trendline_no_trade_warning": 0.0,
        "trendline_mid_channel_noise_warning": 0.0,
        "trendline_low_quality_warning": 0.0,
        "trendline_reversal_context": 0.0,
        "trendline_breakout_context": 0.0,
        "trendline_breakdown_context": 0.0,
        "trendline_pressure_watch": 0.0,
        "trendline_continuation_watch": 0.0,
        "trendline_breakout_watch_high_quality": 0.0,
        "trendline_breakout_watch_positive_persistence": 0.0,
        "trendline_breakout_watch_hull_expansion": 0.0,
        "trendline_breakout_watch_clean_context": 0.0,
        "trendline_breakout_watch_confirmed_interaction": 0.0,
        "trendline_breakout_watch_strict_score": 0.0,
        "trendline_breakout_watch_strict_context": "none",
    }


def _trendline_annotation_features(features: Mapping[str, Any]) -> dict[str, Any]:
    annotations = _neutral_annotation_features()
    if float(features.get("trendline_valid", 0.0) or 0.0) <= 0.0:
        return annotations

    state = str(features.get("trendline_market_position_state") or "unknown")
    interaction = str(features.get("trendline_interaction") or "NONE")
    quality = _as_float(features.get("trendline_mean_normalized_quality"), 0.0)
    low_quality = quality > 0.0 and quality < 0.4

    annotations.update(
        {
            "trendline_risk_context": "valid_structure",
            "trendline_confidence_annotation": "neutral",
            "trendline_annotation_reason": "valid_trendline_context",
            "trendline_low_quality_warning": 1.0 if low_quality else 0.0,
        }
    )

    if low_quality:
        annotations.update(
            {
                "trendline_risk_context": "low_quality_structure",
                "trendline_confidence_annotation": "caution",
                "trendline_annotation_reason": "normalized_quality_below_0_4",
                "trendline_no_trade_warning": 1.0,
            }
        )
        return annotations

    if state == "mid_channel_noise":
        annotations.update(
            {
                "trendline_risk_context": "mid_channel_noise",
                "trendline_confidence_annotation": "caution",
                "trendline_annotation_reason": "price_in_mid_channel_noise_zone",
                "trendline_no_trade_warning": 1.0,
                "trendline_mid_channel_noise_warning": 1.0,
            }
        )
    elif state == "near_support":
        annotations.update(
            {
                "trendline_risk_context": "near_support_reversal_context",
                "trendline_confidence_annotation": "reversal_watch",
                "trendline_annotation_reason": "price_near_structural_support",
                "trendline_reversal_context": 1.0,
            }
        )
    elif state == "near_resistance":
        annotations.update(
            {
                "trendline_risk_context": "near_resistance_reversal_context",
                "trendline_confidence_annotation": "reversal_watch",
                "trendline_annotation_reason": "price_near_structural_resistance",
                "trendline_reversal_context": 1.0,
            }
        )
    elif state == "upper_channel_pressure":
        annotations.update(
            {
                "trendline_risk_context": "upper_channel_pressure_watch",
                "trendline_confidence_annotation": "breakout_watch",
                "trendline_annotation_reason": "price_pressing_upper_channel_without_full_breakout",
                "trendline_pressure_watch": 1.0,
            }
        )
    elif state == "lower_channel_pressure":
        annotations.update(
            {
                "trendline_risk_context": "lower_channel_pressure_watch",
                "trendline_confidence_annotation": "breakdown_watch",
                "trendline_annotation_reason": "price_pressing_lower_channel_without_full_breakdown",
                "trendline_pressure_watch": 1.0,
            }
        )
    elif state == "above_channel":
        annotations.update(
            {
                "trendline_risk_context": "above_channel_breakout_context",
                "trendline_confidence_annotation": "continuation_watch",
                "trendline_annotation_reason": "price_above_structural_channel",
                "trendline_breakout_context": 1.0,
                "trendline_continuation_watch": 1.0,
            }
        )
    elif state == "below_channel":
        annotations.update(
            {
                "trendline_risk_context": "below_channel_breakdown_context",
                "trendline_confidence_annotation": "continuation_watch",
                "trendline_annotation_reason": "price_below_structural_channel",
                "trendline_breakdown_context": 1.0,
                "trendline_continuation_watch": 1.0,
            }
        )
    elif state == "inside_channel":
        annotations.update(
            {
                "trendline_risk_context": "inside_channel_context",
                "trendline_confidence_annotation": "neutral",
                "trendline_annotation_reason": "price_inside_structural_channel",
            }
        )

    if interaction == "STRUCTURAL_BREAKOUT":
        annotations["trendline_breakout_context"] = 1.0
    elif interaction == "STRUCTURAL_BREAKDOWN":
        annotations["trendline_breakdown_context"] = 1.0
    elif interaction in {"GEOMETRIC_BOUNCE_SUPPORT", "GEOMETRIC_BOUNCE_RESISTANCE"}:
        annotations["trendline_reversal_context"] = 1.0

    annotations.update(_strict_breakout_watch_annotations(features, annotations))
    return annotations


def _strict_breakout_watch_annotations(features: Mapping[str, Any], annotations: Mapping[str, Any]) -> dict[str, Any]:
    breakout_watch = str(annotations.get("trendline_confidence_annotation") or "") == "breakout_watch"
    if not breakout_watch:
        return {}
    quality = _as_float(features.get("trendline_mean_normalized_quality"), 0.0)
    resistance_quality = _as_float(features.get("trendline_resistance_quality_score"), 0.0)
    persistence_bias = _as_float(features.get("trendline_ray_persistence_bias"), 0.0)
    expansion_rate = _as_float(features.get("trendline_hull_expansion_rate"), 0.0)
    interaction = str(features.get("trendline_interaction") or "NONE")
    high_quality = quality >= 0.85 and resistance_quality >= 0.85
    positive_persistence = persistence_bias > 0.0
    hull_expansion = expansion_rate > 0.0
    clean_context = (
        _as_float(features.get("trendline_mid_channel_noise"), 0.0) <= 0.0
        and _as_float(features.get("trendline_no_trade_warning"), 0.0) <= 0.0
        and _as_float(features.get("trendline_low_quality_warning"), 0.0) <= 0.0
    )
    confirmed_interaction = interaction == "STRUCTURAL_BREAKOUT"
    strict_score = float(sum([high_quality, positive_persistence, hull_expansion, clean_context, confirmed_interaction]))
    strict_context = "breakout_watch_broad"
    if strict_score >= 4.0:
        strict_context = "breakout_watch_strict"
    elif strict_score >= 3.0:
        strict_context = "breakout_watch_candidate"
    return {
        "trendline_breakout_watch_high_quality": 1.0 if high_quality else 0.0,
        "trendline_breakout_watch_positive_persistence": 1.0 if positive_persistence else 0.0,
        "trendline_breakout_watch_hull_expansion": 1.0 if hull_expansion else 0.0,
        "trendline_breakout_watch_clean_context": 1.0 if clean_context else 0.0,
        "trendline_breakout_watch_confirmed_interaction": 1.0 if confirmed_interaction else 0.0,
        "trendline_breakout_watch_strict_score": strict_score,
        "trendline_breakout_watch_strict_context": strict_context,
    }


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if np.isfinite(parsed) else default


def _neutral_temporal_features() -> dict[str, Any]:
    return {
        "trendline_prev_interaction": "NONE",
        "trendline_interaction_transition": "NONE->NONE",
        "trendline_interaction_changed": 0.0,
        "trendline_prev_market_position_state": "unknown",
        "trendline_market_position_transition": "unknown->unknown",
        "trendline_hull_width_delta": 0.0,
        "trendline_hull_width_delta_pct": 0.0,
        "trendline_hull_convergence_rate": 0.0,
        "trendline_hull_expansion_rate": 0.0,
        "trendline_support_quality_delta": 0.0,
        "trendline_resistance_quality_delta": 0.0,
        "trendline_mean_quality_delta": 0.0,
        "trendline_support_persistence": 0.0,
        "trendline_resistance_persistence": 0.0,
        "trendline_ray_persistence_bias": 0.0,
        "trendline_support_slope_delta": 0.0,
        "trendline_resistance_slope_delta": 0.0,
        "trendline_support_slope_acceleration": 0.0,
        "trendline_resistance_slope_acceleration": 0.0,
        "trendline_slope_acceleration": 0.0,
    }


def _temporal_context_features(boundary: Any, history: Sequence[Any]) -> dict[str, Any]:
    features = _neutral_temporal_features()
    if not history:
        return features

    previous = history[-1]
    current_interaction = str(boundary.interaction or "NONE")
    previous_interaction = str(previous.interaction or "NONE")
    current_position = str(boundary.market_position_state)
    previous_position = str(previous.market_position_state)

    current_width = _boundary_hull_width(boundary)
    previous_width = _boundary_hull_width(previous)
    width_delta = _safe_delta(current_width, previous_width)
    width_delta_pct = width_delta / max(abs(previous_width), 1e-12) if np.isfinite(previous_width) else 0.0

    widths = [_boundary_hull_width(item) for item in [*history, boundary]]
    valid_widths = [width for width in widths if np.isfinite(width) and width > 0.0]
    mean_width_diff = 0.0
    if len(valid_widths) >= 2:
        diffs = [valid_widths[i + 1] - valid_widths[i] for i in range(len(valid_widths) - 1)]
        mean_width_diff = float(sum(diffs) / len(diffs))
    base_width = valid_widths[0] if valid_widths else 0.0
    convergence_rate = max(0.0, -mean_width_diff / max(base_width, 1e-12)) if base_width > 0 else 0.0
    expansion_rate = max(0.0, mean_width_diff / max(base_width, 1e-12)) if base_width > 0 else 0.0

    support_persistence = _ray_persistence_ratio(
        boundary.active_support_rays,
        history,
        is_support=True,
    )
    resistance_persistence = _ray_persistence_ratio(
        boundary.active_resistance_rays,
        history,
        is_support=False,
    )

    current_support_slope = _best_slope(boundary, support=True)
    previous_support_slope = _best_slope(previous, support=True)
    current_resistance_slope = _best_slope(boundary, support=False)
    previous_resistance_slope = _best_slope(previous, support=False)
    support_slopes = [_best_slope(item, support=True) for item in [*history, boundary]]
    resistance_slopes = [_best_slope(item, support=False) for item in [*history, boundary]]
    support_slopes = [value for value in support_slopes if np.isfinite(value)]
    resistance_slopes = [value for value in resistance_slopes if np.isfinite(value)]
    support_accel = series_acceleration(support_slopes) if len(support_slopes) >= 2 else 0.0
    resistance_accel = series_acceleration(resistance_slopes) if len(resistance_slopes) >= 2 else 0.0

    features.update(
        {
            "trendline_prev_interaction": previous_interaction,
            "trendline_interaction_transition": f"{previous_interaction}->{current_interaction}",
            "trendline_interaction_changed": 1.0 if previous_interaction != current_interaction else 0.0,
            "trendline_prev_market_position_state": previous_position,
            "trendline_market_position_transition": f"{previous_position}->{current_position}",
            "trendline_hull_width_delta": width_delta,
            "trendline_hull_width_delta_pct": float(width_delta_pct) if np.isfinite(width_delta_pct) else 0.0,
            "trendline_hull_convergence_rate": float(convergence_rate),
            "trendline_hull_expansion_rate": float(expansion_rate),
            "trendline_support_quality_delta": _safe_delta(boundary.best_support_quality, previous.best_support_quality),
            "trendline_resistance_quality_delta": _safe_delta(boundary.best_resistance_quality, previous.best_resistance_quality),
            "trendline_mean_quality_delta": _safe_delta(boundary.mean_normalized_quality, previous.mean_normalized_quality),
            "trendline_support_persistence": support_persistence,
            "trendline_resistance_persistence": resistance_persistence,
            "trendline_ray_persistence_bias": support_persistence - resistance_persistence,
            "trendline_support_slope_delta": _safe_delta(current_support_slope, previous_support_slope),
            "trendline_resistance_slope_delta": _safe_delta(current_resistance_slope, previous_resistance_slope),
            "trendline_support_slope_acceleration": float(support_accel),
            "trendline_resistance_slope_acceleration": float(resistance_accel),
            "trendline_slope_acceleration": float(support_accel + resistance_accel),
        }
    )
    return features


def _boundary_hull_width(boundary: Any) -> float:
    qm = getattr(boundary, "quality_metrics", None)
    if qm is None:
        return np.nan
    return float(getattr(qm, "hull_width_atr", np.nan))


def _safe_delta(current: float, previous: float) -> float:
    if not np.isfinite(current) or not np.isfinite(previous):
        return 0.0
    return float(current - previous)


def _ray_persistence_ratio(current_rays: list[Any], history: Sequence[Any], *, is_support: bool) -> float:
    if not current_rays or not history:
        return 0.0
    persistent = count_persistent_rays(
        current_rays,
        list(history),
        is_support=is_support,
        slope_match_tol=0.05,
    )
    return float(persistent / max(len(current_rays), 1))


def _best_slope(boundary: Any, *, support: bool) -> float:
    ray = boundary.best_support if support else boundary.best_resistance
    if ray is None:
        return np.nan
    return float(ray.slope)


def _signal_history(
    snapshot_history: TrendlineSnapshotHistory | None,
    *,
    asset: str,
    timeframe: str,
    timestamp: Any,
    limit: int,
) -> list[Any]:
    if snapshot_history is None:
        return []
    return snapshot_history.history_before(asset, timeframe, timestamp, limit=max(int(limit), 1))


def _build_fitter_kwargs(config: TrendlineFeatureConfig) -> dict[str, Any]:
    if config.fitter == "pathfinding":
        return {"line_fit_mode": config.pathfinding_line_fit_mode}
    if config.fitter == "ensemble":
        return {"pathfinding_line_fit_mode": config.pathfinding_line_fit_mode}
    return {}


def _prepare_ohlcv_index(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        return out.sort_index()
    if "timestamp" in out.columns:
        out.index = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        out = out[~out.index.isna()]
        if not out.empty:
            return out.sort_index()
    out.index = pd.date_range("1970-01-01", periods=len(out), freq=_timeframe_to_freq(timeframe))
    return out


def _timeframe_to_freq(timeframe: str) -> str:
    tf = timeframe.strip().lower()
    if tf.endswith("m") and tf[:-1].isdigit():
        return f"{int(tf[:-1])}min"
    if tf.endswith("h") and tf[:-1].isdigit():
        return f"{int(tf[:-1])}h"
    if tf.endswith("d") and tf[:-1].isdigit():
        return f"{int(tf[:-1])}D"
    return "1h"


def _latest_atr(df: pd.DataFrame, window: int) -> float:
    atr = true_range(df).rolling(max(int(window), 1), min_periods=1).mean()
    return float(max(atr.iloc[-1], 1e-12))


def _distance_atr(close: float, level: float, atr: float, *, support: bool) -> float:
    if not np.isfinite(level):
        return np.nan
    distance = close - level if support else level - close
    return float(distance / max(atr, 1e-12))


def _slope_atr(ray: Any, atr: float) -> float:
    if ray is None:
        return 0.0
    return float(ray.slope / max(atr, 1e-12))


def _compression_from_width(hull_width_atr: float) -> float:
    if not np.isfinite(hull_width_atr) or hull_width_atr <= 0:
        return 0.0
    return float(max(0.0, min(1.0, 1.0 - hull_width_atr / 3.0)))


def _hull_position(close: float, floor: float, ceiling: float) -> float:
    if not np.isfinite(floor) or not np.isfinite(ceiling) or ceiling <= floor:
        return 0.5
    return float(max(0.0, min(1.0, (close - floor) / (ceiling - floor))))


__all__ = [
    "TrendlineFeatureConfig",
    "TrendlineFeatureProducer",
    "compute_trendline_context_features",
]
