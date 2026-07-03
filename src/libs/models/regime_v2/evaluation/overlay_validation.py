"""Rolling-window validation for RegimeV2 trend-overlay experiments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from libs.models.regime_v2.evaluation.candidate_export import TrendCandidateExportConfig, export_builtin_trend_candidates
from libs.models.regime_v2.evaluation.comparison import RegimeComparisonConfig, run_regime_comparison
from libs.models.regime_v2.evaluation.failure_diagnostics import (
    diagnose_selection_overlay_failures,
    summarize_failure_diagnostics,
)
from libs.models.regime_v2.evaluation.selection_overlay import RegimeV2TrendOverlayConfig, run_regime_v2_trend_selection_overlay


@dataclass(frozen=True)
class OverlayWindowValidationConfig:
    horizon_bars: int
    window_bars: int = 300
    step_bars: int = 150
    min_count: int = 10
    fee_bps_values: tuple[float, ...] = (0.0,)
    candidate_models: tuple[str, ...] = ("Momentum", "TrendFollowing", "PriceAction")
    min_abs_edge: float = 0.01
    top_k: int = 1
    aligned_boost: float = 0.35
    conflict_penalty: float = 0.70
    trend_score_floor: float = 0.24
    breakout_score_floor: float = 0.24
    mean_reversion_score_floor: float = 0.24


def run_overlay_window_validation(
    ohlcv: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: OverlayWindowValidationConfig,
) -> dict[str, Any]:
    """Run RegimeV2 gated-overlay validation over rolling windows."""
    df = ohlcv.sort_index().copy()
    windows = _windows(df, config.window_bars, config.step_bars)
    rows: list[dict[str, Any]] = []
    for window_id, window in enumerate(windows, start=1):
        comparison = run_regime_comparison(
            window,
            asset=asset,
            timeframe=timeframe,
            config=RegimeComparisonConfig(
                horizon_bars=config.horizon_bars,
                include_legacy_regime=False,
                include_regime_classification=False,
            ),
        )
        candidates = export_builtin_trend_candidates(
            window,
            asset=asset,
            timeframe=timeframe,
            config=TrendCandidateExportConfig(
                models=config.candidate_models,
                min_abs_edge=config.min_abs_edge,
                include_flat=False,
            ),
        )
        counts = candidates["model_name"].value_counts().sort_index().to_dict() if not candidates.empty else {}
        for fee in config.fee_bps_values:
            overlay = run_regime_v2_trend_selection_overlay(
                comparison.frame,
                candidates,
                config=RegimeV2TrendOverlayConfig(
                    min_count=config.min_count,
                    fee_bps=fee,
                    top_k=config.top_k,
                    aligned_boost=config.aligned_boost,
                    conflict_penalty=config.conflict_penalty,
                    trend_score_floor=config.trend_score_floor,
                    breakout_score_floor=config.breakout_score_floor,
                    mean_reversion_score_floor=config.mean_reversion_score_floor,
                ),
            )
            diagnostics = diagnose_selection_overlay_failures(overlay.selected_frame)
            rows.append(
                {
                    "asset": asset,
                    "timeframe": timeframe,
                    "window_id": window_id,
                    "start": str(window.index[0]),
                    "end": str(window.index[-1]),
                    "rows": int(len(window)),
                    "fee_bps": float(fee),
                    "candidate_rows": int(len(candidates)),
                    "candidate_counts": {str(k): int(v) for k, v in counts.items()},
                    "baseline_mean_edge": overlay.baseline.mean_edge,
                    "gated_mean_edge": overlay.gated.mean_edge,
                    "gated_lift": overlay.summary.get("gated_lift_vs_baseline"),
                    "baseline_count": overlay.baseline.count,
                    "gated_count": overlay.gated.count,
                    "gated_win_rate": overlay.gated.win_rate,
                    "gated_better": bool(overlay.summary.get("gated_better", False)),
                    "enough_samples": bool(overlay.gated.enough_samples),
                    "failure_diagnostics": diagnostics,
                }
            )
    return {"summary": _summary(rows, config), "metrics": rows}


def _windows(df: pd.DataFrame, window_bars: int, step_bars: int) -> list[pd.DataFrame]:
    if len(df) <= window_bars:
        return [df]
    out: list[pd.DataFrame] = []
    start = 0
    while start + window_bars <= len(df):
        out.append(df.iloc[start : start + window_bars])
        start += step_bars
    last = df.iloc[-window_bars:]
    if not out or not out[-1].index.equals(last.index):
        out.append(last)
    return out


def _summary(rows: list[dict[str, Any]], config: OverlayWindowValidationConfig) -> dict[str, Any]:
    valid = [row for row in rows if row["enough_samples"] and row["gated_lift"] is not None]
    positive = [row for row in valid if row["gated_lift"] > 0.0]
    fees = sorted({row["fee_bps"] for row in rows})
    fee_summary = {}
    for fee in fees:
        fee_valid = [row for row in valid if row["fee_bps"] == fee]
        fee_positive = [row for row in fee_valid if row["gated_lift"] > 0.0]
        fee_summary[str(fee)] = {
            "valid_window_count": len(fee_valid),
            "positive_gated_window_count": len(fee_positive),
            "positive_gated_rate": _round(len(fee_positive) / len(fee_valid)) if fee_valid else None,
            "mean_gated_lift": _mean([row["gated_lift"] for row in fee_valid]),
            "median_gated_lift": _median([row["gated_lift"] for row in fee_valid]),
            "median_gated_win_rate": _median([row["gated_win_rate"] for row in fee_valid]),
            "failure_diagnostics": summarize_failure_diagnostics(
                [row["failure_diagnostics"] for row in fee_valid if "failure_diagnostics" in row]
            ),
        }
    return {
        "window_count": len(rows),
        "valid_window_count": len(valid),
        "positive_gated_window_count": len(positive),
        "positive_gated_rate": _round(len(positive) / len(valid)) if valid else None,
        "mean_gated_lift": _mean([row["gated_lift"] for row in valid]),
        "median_gated_lift": _median([row["gated_lift"] for row in valid]),
        "median_gated_win_rate": _median([row["gated_win_rate"] for row in valid]),
        "fee_bps_values": fees,
        "fee_summary": fee_summary,
        "failure_diagnostics": summarize_failure_diagnostics(
            [row["failure_diagnostics"] for row in valid if "failure_diagnostics" in row]
        ),
        "horizon_bars": config.horizon_bars,
        "window_bars": config.window_bars,
        "step_bars": config.step_bars,
        "candidate_models": list(config.candidate_models),
        "trend_score_floor": config.trend_score_floor,
        "breakout_score_floor": config.breakout_score_floor,
        "mean_reversion_score_floor": config.mean_reversion_score_floor,
    }


def _mean(values: list[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return _round(sum(clean) / len(clean)) if clean else None


def _median(values: list[float | None]) -> float | None:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    return _round(clean[mid]) if len(clean) % 2 else _round((clean[mid - 1] + clean[mid]) / 2.0)


def _round(value: float | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 8)


__all__ = ["OverlayWindowValidationConfig", "run_overlay_window_validation"]
