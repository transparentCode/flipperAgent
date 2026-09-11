"""Trend-family downstream evaluator for RegimeV2.

This evaluator answers a narrower Phase-4 question than the generic ablation
module:

    Does RegimeV2 trend permission improve existing directional model
    candidates such as MomentumV2, TrendFollowing, PriceActionV2, or
    RegimePullbackV2?

Input is a RegimeV2 comparison frame plus a candidate frame/list.  The candidate
shape is intentionally compatible with ``SelectionCandidate`` but also accepts
plain research dataframes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

_DEFAULT_TREND_MODELS = (
    "Momentum",
    "MomentumV2",
    "TrendFollowing",
    "TrendFollowingModel",
    "PriceAction",
    "PriceActionV2",
    "RegimePullbackV2",
)


@dataclass(frozen=True)
class TrendFamilyAblationConfig:
    """Configuration for trend-family candidate ablation."""

    model_names: tuple[str, ...] = _DEFAULT_TREND_MODELS
    min_count: int = 20
    fee_bps: float = 0.0
    trend_score_floor: float = 0.24
    top_quantile: float = 0.90
    require_direction_agreement: bool = True


@dataclass(frozen=True)
class TrendFamilyMetric:
    """Metrics for one trend-family filter/model pair."""

    model_name: str
    filter_name: str
    count: int
    baseline_count: int
    candidate_rate: float
    mean_edge: float | None
    baseline_mean_edge: float | None
    lift_vs_baseline: float | None
    median_edge: float | None
    win_rate: float | None
    enough_samples: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "filter_name": self.filter_name,
            "count": self.count,
            "baseline_count": self.baseline_count,
            "candidate_rate": self.candidate_rate,
            "mean_edge": self.mean_edge,
            "baseline_mean_edge": self.baseline_mean_edge,
            "lift_vs_baseline": self.lift_vs_baseline,
            "median_edge": self.median_edge,
            "win_rate": self.win_rate,
            "enough_samples": self.enough_samples,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TrendFamilyAblationResult:
    """Trend-family ablation result."""

    metrics: list[TrendFamilyMetric]
    summary: dict[str, Any]
    joined_frame: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": dict(self.summary),
            "metrics": [metric.to_dict() for metric in self.metrics],
            "rows": int(len(self.joined_frame)),
            "columns": list(self.joined_frame.columns),
        }


def run_trend_family_ablation(
    comparison_frame: pd.DataFrame,
    candidates: pd.DataFrame | Sequence[Any],
    *,
    config: TrendFamilyAblationConfig | None = None,
) -> TrendFamilyAblationResult:
    """Evaluate RegimeV2 trend filters on directional model candidates."""
    cfg = config or TrendFamilyAblationConfig()
    candidate_frame = _normalize_candidates(candidates)
    joined = _join_candidates_to_comparison(comparison_frame, candidate_frame, cfg)
    joined = _prepare_edges(joined, cfg)

    metrics: list[TrendFamilyMetric] = []
    for model_name in ["__all__", *sorted(joined["model_name"].dropna().astype(str).unique())]:
        model_slice = joined if model_name == "__all__" else joined[joined["model_name"].astype(str) == model_name]
        if model_slice.empty:
            continue
        metrics.extend(_model_metrics(model_slice, model_name=model_name, cfg=cfg))

    summary = _summarize(metrics, cfg)
    return TrendFamilyAblationResult(metrics=metrics, summary=summary, joined_frame=joined)


def _model_metrics(frame: pd.DataFrame, *, model_name: str, cfg: TrendFamilyAblationConfig) -> list[TrendFamilyMetric]:
    base_mask = frame["direction"].fillna(0).astype(float) != 0.0
    regime_side = _regime_trend_side(frame)
    direction_side = frame["direction"].fillna(0).astype(float).clip(-1.0, 1.0)
    agreement = regime_side == direction_side
    if not cfg.require_direction_agreement:
        agreement = pd.Series(True, index=frame.index)

    trend_allowed = frame.get("regime_v2_policy_allow_trend_following", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    trend_score = pd.to_numeric(frame.get("regime_v2_policy_trend_score", 0.0), errors="coerce").fillna(0.0)
    score_threshold = _score_threshold(trend_score, cfg)

    filters = {
        "baseline_candidates": base_mask,
        "regime_trend_allowed_agree": base_mask & trend_allowed & agreement,
        "regime_trend_score_floor_agree": base_mask & (trend_score >= cfg.trend_score_floor) & agreement,
        "regime_trend_score_top_agree": base_mask & (trend_score >= score_threshold) & agreement,
    }
    return [
        _metric(frame, model_name=model_name, filter_name=name, mask=mask, baseline_mask=base_mask, cfg=cfg)
        for name, mask in filters.items()
    ]


def _metric(
    frame: pd.DataFrame,
    *,
    model_name: str,
    filter_name: str,
    mask: pd.Series,
    baseline_mask: pd.Series,
    cfg: TrendFamilyAblationConfig,
) -> TrendFamilyMetric:
    baseline = frame.loc[baseline_mask, "_candidate_edge"].replace([np.inf, -np.inf], np.nan).dropna()
    selected = frame.loc[mask, "_candidate_edge"].replace([np.inf, -np.inf], np.nan).dropna()
    baseline_mean = _round_or_none(baseline.mean()) if not baseline.empty else None
    mean_edge = _round_or_none(selected.mean()) if not selected.empty else None
    lift = _round_or_none(mean_edge - baseline_mean) if mean_edge is not None and baseline_mean is not None else None
    return TrendFamilyMetric(
        model_name=model_name,
        filter_name=filter_name,
        count=int(len(selected)),
        baseline_count=int(len(baseline)),
        candidate_rate=round(float(mask.mean()), 6) if len(mask) else 0.0,
        mean_edge=mean_edge,
        baseline_mean_edge=baseline_mean,
        lift_vs_baseline=lift,
        median_edge=_round_or_none(selected.median()) if not selected.empty else None,
        win_rate=_round_or_none((selected > 0.0).mean()) if not selected.empty else None,
        enough_samples=int(len(selected)) >= cfg.min_count,
        metadata={"fee_bps": cfg.fee_bps},
    )


def _normalize_candidates(candidates: pd.DataFrame | Sequence[Any]) -> pd.DataFrame:
    if isinstance(candidates, pd.DataFrame):
        frame = candidates.copy()
    else:
        rows = []
        for item in candidates:
            if hasattr(item, "model_dump"):
                rows.append(item.model_dump())
            elif hasattr(item, "dict"):
                rows.append(item.dict())
            elif hasattr(item, "to_dict"):
                rows.append(item.to_dict())
            else:
                rows.append(dict(item))
        frame = pd.DataFrame(rows)

    required = {"model_name", "direction"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Trend-family candidates missing required columns: {missing}")
    if "edge_score" not in frame.columns:
        frame["edge_score"] = 1.0
    if "conviction" not in frame.columns:
        frame["conviction"] = 1.0
    return frame


def _join_candidates_to_comparison(
    comparison_frame: pd.DataFrame,
    candidates: pd.DataFrame,
    cfg: TrendFamilyAblationConfig,
) -> pd.DataFrame:
    comparison = comparison_frame.copy()
    comparison["_join_key"] = _index_join_key(comparison.index).to_numpy()
    cand = candidates.copy()
    cand["_join_key"] = _candidate_join_key(cand, comparison_frame.index).to_numpy()
    joined = cand.merge(comparison, on="_join_key", how="left", suffixes=("", "_regime"))
    if cfg.model_names:
        joined = joined[joined["model_name"].astype(str).isin(set(cfg.model_names))]
    return joined.reset_index(drop=True)


def _prepare_edges(frame: pd.DataFrame, cfg: TrendFamilyAblationConfig) -> pd.DataFrame:
    out = frame.copy()
    fwd = pd.to_numeric(out.get("fwd_return"), errors="coerce")
    direction = pd.to_numeric(out.get("direction"), errors="coerce").fillna(0.0).clip(-1.0, 1.0)
    conviction = pd.to_numeric(out.get("conviction"), errors="coerce").fillna(1.0).clip(lower=0.0)
    edge_score = pd.to_numeric(out.get("edge_score"), errors="coerce").fillna(1.0).abs()
    fee = float(cfg.fee_bps) / 10_000.0
    out["_candidate_edge"] = direction * fwd * conviction * edge_score - fee
    return out


def _score_threshold(score: pd.Series, cfg: TrendFamilyAblationConfig) -> float:
    positive = score[score > 0.0]
    if positive.empty:
        return float("inf")
    return max(float(cfg.trend_score_floor), float(positive.quantile(cfg.top_quantile)))


def _regime_trend_side(frame: pd.DataFrame) -> pd.Series:
    direction = frame.get("regime_v2_trend_direction", pd.Series("neutral", index=frame.index)).astype(str)
    return direction.map({"bull": 1.0, "bear": -1.0}).fillna(0.0)


def _index_join_key(index: pd.Index) -> pd.Series:
    if isinstance(index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(index, utc=True).astype("int64"), index=index).reset_index(drop=True)
    return pd.Series(index).reset_index(drop=True)


def _candidate_join_key(candidates: pd.DataFrame, comparison_index: pd.Index) -> pd.Series:
    if "timestamp" not in candidates.columns:
        return _index_join_key(candidates.index)
    ts = candidates["timestamp"]
    if isinstance(comparison_index, pd.DatetimeIndex):
        if pd.api.types.is_numeric_dtype(ts):
            numeric = pd.to_numeric(ts, errors="coerce")
            unit = "ms" if numeric.dropna().median() > 10_000_000_000 else "s"
            return pd.to_datetime(numeric, unit=unit, utc=True).astype("int64")
        return pd.to_datetime(ts, utc=True).astype("int64")
    return ts.reset_index(drop=True)


def _summarize(metrics: list[TrendFamilyMetric], cfg: TrendFamilyAblationConfig) -> dict[str, Any]:
    ranked = sorted(
        [m for m in metrics if m.enough_samples and m.lift_vs_baseline is not None and m.filter_name != "baseline_candidates"],
        key=lambda m: m.lift_vs_baseline or -999.0,
        reverse=True,
    )
    return {
        "metric_count": len(metrics),
        "min_count": cfg.min_count,
        "trend_score_floor": cfg.trend_score_floor,
        "top_quantile": cfg.top_quantile,
        "fee_bps": cfg.fee_bps,
        "best_filter": ranked[0].to_dict() if ranked else None,
        "positive_lift_count": int(sum((m.lift_vs_baseline or 0.0) > 0.0 for m in ranked)),
    }


def _round_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 8)


__all__ = [
    "TrendFamilyAblationConfig",
    "TrendFamilyAblationResult",
    "TrendFamilyMetric",
    "run_trend_family_ablation",
]
