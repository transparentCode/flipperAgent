"""Rolling validation and hard gates for RegimeV2 optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_v2.evaluation.downstream import DownstreamAblationConfig, run_downstream_ablation


@dataclass(frozen=True)
class RegimeV2OptimizationGates:
    """Hard rejection gates for a candidate RegimeV2 parameter set."""

    min_support_count: int = 20
    min_support_rate: float = 0.02
    max_flip_rate: float = 0.35
    max_policy_turnover: float = 0.45
    min_oos_score_ratio: float = 0.50


@dataclass(frozen=True)
class RegimeV2ObjectiveWeights:
    """Weights for the conservative scalar objective."""

    lift: float = 1.0
    positive_window_rate: float = 0.25
    support: float = 0.05
    tail_penalty: float = 0.50
    flip_penalty: float = 0.20
    turnover_penalty: float = 0.20
    low_support_penalty: float = 1.00


@dataclass(frozen=True)
class RegimeV2RollingValidationConfig:
    """Rolling-window scorer configuration."""

    window_bars: int = 240
    step_bars: int = 120
    min_window_bars: int = 120
    downstream: DownstreamAblationConfig = field(
        default_factory=lambda: DownstreamAblationConfig(min_count=20)
    )
    gates: RegimeV2OptimizationGates = field(default_factory=RegimeV2OptimizationGates)
    weights: RegimeV2ObjectiveWeights = field(default_factory=RegimeV2ObjectiveWeights)


@dataclass(frozen=True)
class RegimeV2WindowMetric:
    """Metrics for one rolling validation window."""

    start: int
    end: int
    support_count: int
    support_rate: float
    downstream_lift: float
    positive_lift: bool
    flip_rate: float
    policy_turnover: float
    label_entropy: float
    tail_penalty: float
    score: float
    best_metric_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "support_count": self.support_count,
            "support_rate": self.support_rate,
            "downstream_lift": self.downstream_lift,
            "positive_lift": self.positive_lift,
            "flip_rate": self.flip_rate,
            "policy_turnover": self.policy_turnover,
            "label_entropy": self.label_entropy,
            "tail_penalty": self.tail_penalty,
            "score": self.score,
            "best_metric_name": self.best_metric_name,
        }


@dataclass(frozen=True)
class RegimeV2ValidationResult:
    """Aggregate rolling validation result."""

    score: float
    rejected: bool
    rejection_reasons: tuple[str, ...]
    windows: tuple[RegimeV2WindowMetric, ...]
    aggregate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "rejected": self.rejected,
            "rejection_reasons": list(self.rejection_reasons),
            "windows": [window.to_dict() for window in self.windows],
            "aggregate": dict(self.aggregate),
        }


def evaluate_regime_v2_frame(
    frame: pd.DataFrame,
    *,
    config: RegimeV2RollingValidationConfig | None = None,
) -> RegimeV2ValidationResult:
    """Score a RegimeV2 comparison frame using rolling downstream metrics."""
    cfg = config or RegimeV2RollingValidationConfig()
    working = frame.replace([np.inf, -np.inf], np.nan).copy()
    if "fwd_return" in working.columns:
        working = working.loc[pd.to_numeric(working["fwd_return"], errors="coerce").notna()]
    if working.empty:
        return _empty_result("no_valid_forward_returns")

    windows = tuple(
        _score_window(working.iloc[start:end], start=start, end=end, cfg=cfg)
        for start, end in _rolling_windows(len(working), cfg)
    )
    if not windows:
        return _empty_result("no_valid_windows")

    aggregate = _aggregate_windows(windows)
    reasons = _rejection_reasons(aggregate, cfg.gates)
    return RegimeV2ValidationResult(
        score=float(aggregate["score"]),
        rejected=bool(reasons),
        rejection_reasons=tuple(reasons),
        windows=windows,
        aggregate=aggregate,
    )


def compare_oos_gate(
    validation: RegimeV2ValidationResult,
    oos: RegimeV2ValidationResult,
    *,
    gates: RegimeV2OptimizationGates | None = None,
) -> tuple[bool, str | None]:
    """Return whether OOS degradation breaches the hard gate."""
    cfg = gates or RegimeV2OptimizationGates()
    if validation.score <= 0.0:
        return False, None
    min_score = validation.score * cfg.min_oos_score_ratio
    if oos.score < min_score:
        return True, "oos_degradation"
    return False, None


def _score_window(
    window: pd.DataFrame,
    *,
    start: int,
    end: int,
    cfg: RegimeV2RollingValidationConfig,
) -> RegimeV2WindowMetric:
    active = _active_policy_mask(window)
    support_count = int(active.sum())
    support_rate = round(float(active.mean()), 6) if len(active) else 0.0

    downstream = run_downstream_ablation(window, config=cfg.downstream)
    best = downstream.summary.get("best_by_lift") or {}
    lift = float(best.get("lift_vs_baseline") or 0.0)

    flip_rate = _change_rate(window.get("regime_v2_summary_label"))
    policy_turnover = _change_rate(active)
    entropy = _label_entropy(window.get("regime_v2_summary_label"))
    tail_penalty = _tail_penalty(window, active)
    score = _window_score(
        lift=lift,
        support_rate=support_rate,
        flip_rate=flip_rate,
        policy_turnover=policy_turnover,
        tail_penalty=tail_penalty,
        cfg=cfg,
    )

    return RegimeV2WindowMetric(
        start=start,
        end=end,
        support_count=support_count,
        support_rate=support_rate,
        downstream_lift=round(lift, 8),
        positive_lift=lift > 0.0,
        flip_rate=round(flip_rate, 6),
        policy_turnover=round(policy_turnover, 6),
        label_entropy=round(entropy, 6),
        tail_penalty=round(tail_penalty, 8),
        score=round(score, 8),
        best_metric_name=best.get("name"),
    )


def _rolling_windows(
    n_rows: int,
    cfg: RegimeV2RollingValidationConfig,
) -> list[tuple[int, int]]:
    if n_rows < cfg.min_window_bars:
        return []
    window_bars = max(int(cfg.window_bars), int(cfg.min_window_bars))
    step_bars = max(int(cfg.step_bars), 1)
    if n_rows <= window_bars:
        return [(0, n_rows)]

    windows: list[tuple[int, int]] = []
    start = 0
    while start + window_bars <= n_rows:
        windows.append((start, start + window_bars))
        start += step_bars
    if windows[-1][1] < n_rows:
        windows.append((n_rows - window_bars, n_rows))
    return windows


def _active_policy_mask(frame: pd.DataFrame) -> pd.Series:
    columns = [
        "regime_v2_policy_allow_trend_following",
        "regime_v2_policy_allow_breakout",
        "regime_v2_policy_allow_mean_reversion",
        "regime_v2_policy_allow_scalping",
        "regime_v2_policy_allow_countertrend",
    ]
    present = [col for col in columns if col in frame.columns]
    if not present:
        return pd.Series(False, index=frame.index)
    allowed = frame[present].fillna(False).astype(bool).any(axis=1)
    if "regime_v2_policy_max_position_scale" in frame.columns:
        scale = pd.to_numeric(frame["regime_v2_policy_max_position_scale"], errors="coerce").fillna(0.0)
        allowed = allowed & (scale > 0.0)
    return allowed.astype(bool)


def _window_score(
    *,
    lift: float,
    support_rate: float,
    flip_rate: float,
    policy_turnover: float,
    tail_penalty: float,
    cfg: RegimeV2RollingValidationConfig,
) -> float:
    weights = cfg.weights
    gates = cfg.gates
    low_support_gap = max(0.0, gates.min_support_rate - support_rate)
    return (
        weights.lift * lift
        + weights.positive_window_rate * float(lift > 0.0)
        + weights.support * support_rate
        - weights.tail_penalty * tail_penalty
        - weights.flip_penalty * flip_rate
        - weights.turnover_penalty * policy_turnover
        - weights.low_support_penalty * low_support_gap
    )


def _aggregate_windows(windows: tuple[RegimeV2WindowMetric, ...]) -> dict[str, Any]:
    support_counts = [window.support_count for window in windows]
    support_rates = [window.support_rate for window in windows]
    lifts = [window.downstream_lift for window in windows]
    flip_rates = [window.flip_rate for window in windows]
    turnovers = [window.policy_turnover for window in windows]
    scores = [window.score for window in windows]
    positive_rate = float(np.mean([window.positive_lift for window in windows]))
    mean_score = float(np.mean(scores))
    return {
        "window_count": len(windows),
        "score": round(mean_score, 8),
        "mean_downstream_lift": round(float(np.mean(lifts)), 8),
        "positive_window_rate": round(positive_rate, 6),
        "mean_support_count": round(float(np.mean(support_counts)), 4),
        "min_support_count": int(min(support_counts)),
        "mean_support_rate": round(float(np.mean(support_rates)), 6),
        "mean_flip_rate": round(float(np.mean(flip_rates)), 6),
        "mean_policy_turnover": round(float(np.mean(turnovers)), 6),
        "mean_tail_penalty": round(float(np.mean([window.tail_penalty for window in windows])), 8),
    }


def _rejection_reasons(
    aggregate: dict[str, Any],
    gates: RegimeV2OptimizationGates,
) -> list[str]:
    reasons: list[str] = []
    if int(aggregate["min_support_count"]) < gates.min_support_count:
        reasons.append("support_count_below_minimum")
    if float(aggregate["mean_support_rate"]) < gates.min_support_rate:
        reasons.append("support_rate_below_minimum")
    if float(aggregate["mean_flip_rate"]) > gates.max_flip_rate:
        reasons.append("flip_rate_above_maximum")
    if float(aggregate["mean_policy_turnover"]) > gates.max_policy_turnover:
        reasons.append("policy_turnover_above_maximum")
    return reasons


def _change_rate(series: pd.Series | None) -> float:
    if series is None:
        return 0.0
    clean = series.dropna()
    if len(clean) <= 1:
        return 0.0
    return float(clean.ne(clean.shift()).iloc[1:].mean())


def _label_entropy(series: pd.Series | None) -> float:
    if series is None:
        return 0.0
    values = series.dropna().astype(str)
    if values.empty:
        return 0.0
    probs = values.value_counts(normalize=True).to_numpy(dtype=float)
    if len(probs) <= 1:
        return 0.0
    entropy = -float(np.sum(probs * np.log(probs)))
    return entropy / float(np.log(len(probs)))


def _tail_penalty(frame: pd.DataFrame, active: pd.Series) -> float:
    if "fwd_return" not in frame.columns:
        return 0.0
    selected = pd.to_numeric(frame.loc[active, "fwd_return"], errors="coerce").dropna()
    if selected.empty:
        return 0.0
    q10 = float(selected.quantile(0.10))
    return abs(min(q10, 0.0))


def _empty_result(reason: str) -> RegimeV2ValidationResult:
    return RegimeV2ValidationResult(
        score=-1_000_000.0,
        rejected=True,
        rejection_reasons=(reason,),
        windows=(),
        aggregate={
            "window_count": 0,
            "score": -1_000_000.0,
            "mean_downstream_lift": 0.0,
            "positive_window_rate": 0.0,
            "mean_support_count": 0.0,
            "min_support_count": 0,
            "mean_support_rate": 0.0,
            "mean_flip_rate": 0.0,
            "mean_policy_turnover": 0.0,
            "mean_tail_penalty": 0.0,
        },
    )


__all__ = [
    "RegimeV2ObjectiveWeights",
    "RegimeV2OptimizationGates",
    "RegimeV2RollingValidationConfig",
    "RegimeV2ValidationResult",
    "RegimeV2WindowMetric",
    "compare_oos_gate",
    "evaluate_regime_v2_frame",
]
