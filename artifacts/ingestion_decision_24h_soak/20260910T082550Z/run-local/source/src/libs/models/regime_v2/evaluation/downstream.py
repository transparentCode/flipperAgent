"""Downstream ablation evaluator for RegimeV2.

This module evaluates whether RegimeV2 evidence/policy columns improve simple
forward-return objectives.  It is intentionally strategy-agnostic: the goal is
not to declare a production strategy, but to identify which regime filters are
worth connecting to real model families next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

Objective = Literal["directional_return", "absolute_return"]


@dataclass(frozen=True)
class DownstreamAblationConfig:
    """Config for RegimeV2 downstream ablations."""

    top_quantile: float = 0.90
    score_floor: float = 0.24
    fee_bps: float = 0.0
    min_count: int = 20


@dataclass(frozen=True)
class AblationMetric:
    """Metrics for one ablation mask/objective."""

    name: str
    objective: Objective
    count: int
    candidate_rate: float
    mean_edge: float | None
    median_edge: float | None
    win_rate: float | None
    q25_edge: float | None
    q75_edge: float | None
    lift_vs_baseline: float | None
    baseline_mean_edge: float | None
    enough_samples: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "objective": self.objective,
            "count": self.count,
            "candidate_rate": self.candidate_rate,
            "mean_edge": self.mean_edge,
            "median_edge": self.median_edge,
            "win_rate": self.win_rate,
            "q25_edge": self.q25_edge,
            "q75_edge": self.q75_edge,
            "lift_vs_baseline": self.lift_vs_baseline,
            "baseline_mean_edge": self.baseline_mean_edge,
            "enough_samples": self.enough_samples,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class DownstreamAblationResult:
    """Result for a set of downstream ablations."""

    metrics: list[AblationMetric]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": dict(self.summary),
            "metrics": [metric.to_dict() for metric in self.metrics],
        }


def run_downstream_ablation(
    frame: pd.DataFrame,
    *,
    config: DownstreamAblationConfig | None = None,
) -> DownstreamAblationResult:
    """Evaluate built-in RegimeV2 downstream ablations.

    Expected input is usually ``RegimeComparisonResult.frame`` from
    ``run_regime_comparison``.  Required columns are ``fwd_return`` and/or
    ``fwd_abs_return`` plus RegimeV2 policy/evidence columns.
    """
    cfg = config or DownstreamAblationConfig()
    working = _prepare_frame(frame, cfg)
    metrics: list[AblationMetric] = []

    metrics.append(_evaluate_mask(working, name="baseline_all_abs_move", mask=_all_mask(working), objective="absolute_return", cfg=cfg))

    if "regime_v2_policy_allow_trend_following" in working.columns:
        metrics.append(
            _evaluate_mask(
                working,
                name="regime_v2_trend_allowed_directional",
                mask=_bool_col(working, "regime_v2_policy_allow_trend_following"),
                objective="directional_return",
                cfg=cfg,
                side=_trend_side(working),
            )
        )

    if "regime_v2_policy_trend_score" in working.columns:
        metrics.append(
            _evaluate_mask(
                working,
                name="regime_v2_trend_score_top_directional",
                mask=_score_top_mask(working, "regime_v2_policy_trend_score", cfg),
                objective="directional_return",
                cfg=cfg,
                side=_trend_side(working),
            )
        )

    if "regime_v2_policy_allow_breakout" in working.columns:
        metrics.append(
            _evaluate_mask(
                working,
                name="regime_v2_breakout_allowed_abs_move",
                mask=_bool_col(working, "regime_v2_policy_allow_breakout"),
                objective="absolute_return",
                cfg=cfg,
            )
        )

    for column, name in (
        ("regime_v2_policy_breakout_setup_score", "regime_v2_breakout_setup_watchlist_abs_move"),
        ("regime_v2_policy_displacement_breakout_score", "regime_v2_displacement_breakout_abs_move"),
        ("regime_v2_policy_retest_breakout_score", "regime_v2_retest_breakout_abs_move"),
        ("regime_v2_policy_mean_reversion_score", "regime_v2_mean_reversion_score_top_abs_move"),
        ("regime_v2_policy_scalping_score", "regime_v2_scalping_score_top_abs_move"),
        ("regime_v2_policy_countertrend_score", "regime_v2_countertrend_score_top_abs_move"),
    ):
        if column in working.columns:
            metrics.append(
                _evaluate_mask(
                    working,
                    name=name,
                    mask=_score_top_mask(working, column, cfg),
                    objective="absolute_return",
                    cfg=cfg,
                    metadata={"score_column": column},
                )
            )

    summary = _summarize_metrics(metrics, cfg)
    return DownstreamAblationResult(metrics=metrics, summary=summary)


def _prepare_frame(frame: pd.DataFrame, cfg: DownstreamAblationConfig) -> pd.DataFrame:
    out = frame.copy()
    if "fwd_abs_return" not in out.columns and "fwd_return" in out.columns:
        out["fwd_abs_return"] = pd.to_numeric(out["fwd_return"], errors="coerce").abs()
    if "fwd_return" not in out.columns and "close" in out.columns:
        # Comparison frames should already include forward returns.  This branch
        # is intentionally conservative and leaves no synthetic horizon guess.
        out["fwd_return"] = np.nan
    fee = float(cfg.fee_bps) / 10_000.0
    if "fwd_return" in out.columns:
        out["_net_fwd_return"] = pd.to_numeric(out["fwd_return"], errors="coerce") - fee
    if "fwd_abs_return" in out.columns:
        out["_net_fwd_abs_return"] = pd.to_numeric(out["fwd_abs_return"], errors="coerce") - fee
    return out


def _evaluate_mask(
    frame: pd.DataFrame,
    *,
    name: str,
    mask: pd.Series,
    objective: Objective,
    cfg: DownstreamAblationConfig,
    side: pd.Series | None = None,
    metadata: dict[str, Any] | None = None,
) -> AblationMetric:
    baseline_universe = pd.Series(True, index=frame.index)
    if objective == "directional_return":
        side_series = side if side is not None else pd.Series(0.0, index=frame.index)
        base_edge = _directional_edge(frame, side_series)
        baseline_universe = side_series.reindex(frame.index).fillna(0.0).astype(float) != 0.0
    else:
        base_edge = pd.to_numeric(frame.get("_net_fwd_abs_return"), errors="coerce")

    valid_base = base_edge.loc[baseline_universe].replace([np.inf, -np.inf], np.nan).dropna()
    baseline_mean = _round_or_none(valid_base.mean()) if not valid_base.empty else None

    clean_mask = mask.reindex(frame.index).fillna(False).astype(bool)
    selected = base_edge.loc[clean_mask].replace([np.inf, -np.inf], np.nan).dropna()
    count = int(len(selected))
    mean_edge = _round_or_none(selected.mean()) if count else None
    median_edge = _round_or_none(selected.median()) if count else None
    q25 = _round_or_none(selected.quantile(0.25)) if count else None
    q75 = _round_or_none(selected.quantile(0.75)) if count else None
    win_rate = _round_or_none((selected > 0.0).mean()) if count else None
    lift = _round_or_none(mean_edge - baseline_mean) if mean_edge is not None and baseline_mean is not None else None

    return AblationMetric(
        name=name,
        objective=objective,
        count=count,
        candidate_rate=round(float(clean_mask.mean()), 6) if len(clean_mask) else 0.0,
        mean_edge=mean_edge,
        median_edge=median_edge,
        win_rate=win_rate,
        q25_edge=q25,
        q75_edge=q75,
        lift_vs_baseline=lift,
        baseline_mean_edge=baseline_mean,
        enough_samples=count >= cfg.min_count,
        metadata={**(metadata or {}), "baseline_universe_count": int(len(valid_base))},
    )


def _summarize_metrics(metrics: list[AblationMetric], cfg: DownstreamAblationConfig) -> dict[str, Any]:
    ranked = sorted(
        [metric for metric in metrics if metric.enough_samples and metric.lift_vs_baseline is not None],
        key=lambda metric: metric.lift_vs_baseline or -999.0,
        reverse=True,
    )
    return {
        "metric_count": len(metrics),
        "min_count": cfg.min_count,
        "top_quantile": cfg.top_quantile,
        "score_floor": cfg.score_floor,
        "fee_bps": cfg.fee_bps,
        "best_by_lift": ranked[0].to_dict() if ranked else None,
        "positive_lift_count": int(sum((metric.lift_vs_baseline or 0.0) > 0.0 for metric in metrics if metric.enough_samples)),
    }


def _all_mask(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=frame.index)


def _bool_col(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna(False).astype(bool)


def _score_top_mask(frame: pd.DataFrame, column: str, cfg: DownstreamAblationConfig) -> pd.Series:
    score = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    positive = score[score > 0.0]
    if positive.empty:
        return pd.Series(False, index=frame.index)
    threshold = max(float(cfg.score_floor), float(positive.quantile(cfg.top_quantile)))
    return score >= threshold


def _trend_side(frame: pd.DataFrame) -> pd.Series:
    direction = frame.get("regime_v2_trend_direction", pd.Series("neutral", index=frame.index)).astype(str)
    return direction.map({"bull": 1.0, "bear": -1.0}).fillna(0.0)


def _directional_edge(frame: pd.DataFrame, side: pd.Series) -> pd.Series:
    fwd = pd.to_numeric(frame.get("_net_fwd_return"), errors="coerce")
    return side.reindex(frame.index).fillna(0.0).astype(float) * fwd


def _round_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 8)


__all__ = [
    "AblationMetric",
    "DownstreamAblationConfig",
    "DownstreamAblationResult",
    "run_downstream_ablation",
]
