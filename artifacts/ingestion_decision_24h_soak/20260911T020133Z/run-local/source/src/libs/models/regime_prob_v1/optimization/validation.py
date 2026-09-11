"""Rolling validation and hard gates for RegimeProbV1 optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

_HMM_SCORING_ELIGIBLE_COLUMN = "hmm_scoring_eligible"
_HMM_STATE_ERROR_COLUMN = "hmm_state_error"


@dataclass(frozen=True)
class RegimeProbOptimizationGates:
    """Hard rejection gates for a candidate RegimeProbV1 parameter set."""

    min_support_count: int = 20
    min_support_rate: float = 0.02
    min_positive_window_rate: float = 0.35
    min_mean_edge_return: float = 0.0
    max_decision_flip_rate: float = 0.45
    max_threshold_churn: float = 0.45
    min_oos_score_ratio: float = 0.50


@dataclass(frozen=True)
class RegimeProbObjectiveWeights:
    """Weights for the conservative scalar objective."""

    mean_edge_return: float = 1.0
    positive_window_rate: float = 0.25
    support: float = 0.05
    brier_penalty: float = 0.35
    ece_penalty: float = 0.20
    flip_penalty: float = 0.15
    churn_penalty: float = 0.15
    low_support_penalty: float = 1.00


@dataclass(frozen=True)
class RegimeProbRollingValidationConfig:
    """Rolling-window scorer configuration."""

    window_bars: int = 240
    step_bars: int = 120
    min_window_bars: int = 120
    calibration_bins: int = 10
    gates: RegimeProbOptimizationGates = field(default_factory=RegimeProbOptimizationGates)
    weights: RegimeProbObjectiveWeights = field(default_factory=RegimeProbObjectiveWeights)


@dataclass(frozen=True)
class RegimeProbWindowMetric:
    """Metrics for one rolling validation window."""

    start: int
    end: int
    support_count: int
    support_rate: float
    mean_edge_return: float
    positive_rate: float
    decision_flip_rate: float
    threshold_churn: float
    brier_score: float
    expected_calibration_error: float
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "support_count": self.support_count,
            "support_rate": self.support_rate,
            "mean_edge_return": self.mean_edge_return,
            "positive_rate": self.positive_rate,
            "decision_flip_rate": self.decision_flip_rate,
            "threshold_churn": self.threshold_churn,
            "brier_score": self.brier_score,
            "expected_calibration_error": self.expected_calibration_error,
            "score": self.score,
        }


@dataclass(frozen=True)
class RegimeProbValidationResult:
    """Aggregate rolling validation result."""

    score: float
    rejected: bool
    rejection_reasons: tuple[str, ...]
    windows: tuple[RegimeProbWindowMetric, ...]
    aggregate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "rejected": self.rejected,
            "rejection_reasons": list(self.rejection_reasons),
            "windows": [window.to_dict() for window in self.windows],
            "aggregate": dict(self.aggregate),
        }


def evaluate_regime_prob_frame(
    frame: pd.DataFrame,
    *,
    config: RegimeProbRollingValidationConfig | None = None,
) -> RegimeProbValidationResult:
    """Score a RegimeProbV1 decision frame using rolling downstream metrics."""
    cfg = config or RegimeProbRollingValidationConfig()
    required = {"selected_probability", "selected_label", "selected_edge_return", "decision_active"}
    missing = required.difference(frame.columns)
    if missing:
        raise KeyError(f"RegimeProb decision frame missing required columns: {sorted(missing)}")

    working = frame.replace([np.inf, -np.inf], np.nan).copy()
    hmm_support_overrides: dict[str, Any] | None = None
    if _HMM_SCORING_ELIGIBLE_COLUMN in working.columns:
        eligible = _bool(working.get(_HMM_SCORING_ELIGIBLE_COLUMN), working.index)
        eligible_count = int(eligible.sum())
        eligible_rate = float(eligible.mean()) if len(eligible) else 0.0
        hmm_support_overrides = {
            "hmm_oos_filtered_support_count": eligible_count,
            "hmm_oos_filtered_support_rate": round(eligible_rate, 8),
        }
    if _HMM_STATE_ERROR_COLUMN in working.columns:
        errors = [
            str(value)
            for value in working[_HMM_STATE_ERROR_COLUMN].dropna().astype(str).unique().tolist()
            if str(value)
        ]
        if errors:
            return _empty_result(errors[0], aggregate_overrides=hmm_support_overrides)
    if _HMM_SCORING_ELIGIBLE_COLUMN in working.columns:
        if (
            eligible_count < int(cfg.gates.min_support_count)
            or eligible_rate < float(cfg.gates.min_support_rate)
        ):
            return _empty_result(
                "hmm_oos_filtered_support_below_minimum",
                aggregate_overrides=hmm_support_overrides,
            )
        working = working.loc[eligible].copy()
    valid_probs = pd.to_numeric(working["selected_probability"], errors="coerce").notna()
    valid_labels = pd.to_numeric(working["selected_label"], errors="coerce").notna()
    working = working.loc[valid_probs | valid_labels | working["decision_active"].fillna(False).astype(bool)]
    if working.empty:
        return _empty_result("no_valid_probability_rows", aggregate_overrides=hmm_support_overrides)

    windows = tuple(
        _score_window(working.iloc[start:end], start=start, end=end, cfg=cfg)
        for start, end in _rolling_windows(len(working), cfg)
    )
    if not windows:
        return _empty_result("no_valid_windows", aggregate_overrides=hmm_support_overrides)

    aggregate = _aggregate_windows(windows)
    if hmm_support_overrides is not None:
        aggregate.update(hmm_support_overrides)
    reasons = _rejection_reasons(aggregate, cfg.gates)
    return RegimeProbValidationResult(
        score=float(aggregate["score"]),
        rejected=bool(reasons),
        rejection_reasons=tuple(reasons),
        windows=windows,
        aggregate=aggregate,
    )


def compare_oos_gate(
    validation: RegimeProbValidationResult,
    oos: RegimeProbValidationResult,
    *,
    gates: RegimeProbOptimizationGates | None = None,
) -> tuple[bool, str | None]:
    """Return whether OOS degradation breaches the hard gate."""
    cfg = gates or RegimeProbOptimizationGates()
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
    cfg: RegimeProbRollingValidationConfig,
) -> RegimeProbWindowMetric:
    decision_active = _bool(window.get("decision_active"), window.index)
    valid_probs = pd.to_numeric(window.get("selected_probability"), errors="coerce").notna()
    valid_labels = pd.to_numeric(window.get("selected_label"), errors="coerce").notna()
    valid = valid_probs & valid_labels
    active = decision_active & valid

    support_count = int(active.sum())
    support_rate = float(active.mean()) if len(active) else 0.0
    edge_returns = pd.to_numeric(window.get("selected_edge_return"), errors="coerce")
    mean_edge_return = float(edge_returns.loc[active].mean()) if support_count else 0.0
    positive_rate = float(pd.to_numeric(window.get("selected_label"), errors="coerce").loc[active].mean()) if support_count else 0.0

    decision_key = window.get("decision_key")
    if decision_key is None:
        decision_key = pd.Series(np.where(decision_active, "active", "flat"), index=window.index, dtype=object)
    else:
        decision_key = decision_key.fillna("flat").astype(str)

    decision_flip_rate = _change_rate(decision_key)
    threshold_churn = _change_rate(decision_active.astype(bool))
    brier = _brier_score(
        pd.to_numeric(window.get("selected_label"), errors="coerce").loc[valid],
        pd.to_numeric(window.get("selected_probability"), errors="coerce").loc[valid],
    )
    ece = _expected_calibration_error(
        pd.to_numeric(window.get("selected_label"), errors="coerce").loc[valid],
        pd.to_numeric(window.get("selected_probability"), errors="coerce").loc[valid],
        n_bins=cfg.calibration_bins,
    )
    score = _window_score(
        mean_edge_return=mean_edge_return,
        positive_rate=positive_rate,
        support_rate=support_rate,
        brier=brier,
        ece=ece,
        decision_flip_rate=decision_flip_rate,
        threshold_churn=threshold_churn,
        cfg=cfg,
    )

    return RegimeProbWindowMetric(
        start=start,
        end=end,
        support_count=support_count,
        support_rate=round(support_rate, 6),
        mean_edge_return=round(mean_edge_return, 8),
        positive_rate=round(positive_rate, 6),
        decision_flip_rate=round(decision_flip_rate, 6),
        threshold_churn=round(threshold_churn, 6),
        brier_score=round(brier, 8),
        expected_calibration_error=round(ece, 8),
        score=round(score, 8),
    )


def _rolling_windows(n_rows: int, cfg: RegimeProbRollingValidationConfig) -> list[tuple[int, int]]:
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


def _window_score(
    *,
    mean_edge_return: float,
    positive_rate: float,
    support_rate: float,
    brier: float,
    ece: float,
    decision_flip_rate: float,
    threshold_churn: float,
    cfg: RegimeProbRollingValidationConfig,
) -> float:
    weights = cfg.weights
    gates = cfg.gates
    low_support_gap = max(0.0, gates.min_support_rate - support_rate)
    return (
        weights.mean_edge_return * mean_edge_return
        + weights.positive_window_rate * positive_rate
        + weights.support * support_rate
        - weights.brier_penalty * brier
        - weights.ece_penalty * ece
        - weights.flip_penalty * decision_flip_rate
        - weights.churn_penalty * threshold_churn
        - weights.low_support_penalty * low_support_gap
    )


def _aggregate_windows(windows: tuple[RegimeProbWindowMetric, ...]) -> dict[str, Any]:
    return {
        "score": round(float(np.mean([window.score for window in windows])), 8),
        "window_count": len(windows),
        "positive_window_rate": round(float(np.mean([window.mean_edge_return > 0.0 for window in windows])), 8),
        "mean_support_count": round(float(np.mean([window.support_count for window in windows])), 8),
        "mean_support_rate": round(float(np.mean([window.support_rate for window in windows])), 8),
        "mean_edge_return": round(float(np.mean([window.mean_edge_return for window in windows])), 8),
        "mean_positive_rate": round(float(np.mean([window.positive_rate for window in windows])), 8),
        "mean_brier_score": round(float(np.mean([window.brier_score for window in windows])), 8),
        "mean_expected_calibration_error": round(float(np.mean([window.expected_calibration_error for window in windows])), 8),
        "mean_decision_flip_rate": round(float(np.mean([window.decision_flip_rate for window in windows])), 8),
        "mean_threshold_churn": round(float(np.mean([window.threshold_churn for window in windows])), 8),
    }


def _rejection_reasons(
    aggregate: dict[str, Any],
    gates: RegimeProbOptimizationGates,
) -> list[str]:
    reasons: list[str] = []
    if aggregate["mean_support_count"] < gates.min_support_count:
        reasons.append("support_count_below_minimum")
    if aggregate["mean_support_rate"] < gates.min_support_rate:
        reasons.append("support_rate_below_minimum")
    if aggregate["positive_window_rate"] < gates.min_positive_window_rate:
        reasons.append("positive_window_rate_below_minimum")
    if aggregate["mean_edge_return"] < gates.min_mean_edge_return:
        reasons.append("mean_edge_return_below_minimum")
    if aggregate["mean_decision_flip_rate"] > gates.max_decision_flip_rate:
        reasons.append("decision_flip_rate_too_high")
    if aggregate["mean_threshold_churn"] > gates.max_threshold_churn:
        reasons.append("threshold_churn_too_high")
    return reasons


def _change_rate(values: pd.Series) -> float:
    if len(values) <= 1:
        return 0.0
    return float((values != values.shift(1)).iloc[1:].mean())


def _bool(values: pd.Series | None, index: pd.Index) -> pd.Series:
    if values is None:
        return pd.Series(False, index=index, dtype=bool)
    return values.reindex(index).fillna(False).astype(bool)


def _brier_score(labels: pd.Series, probs: pd.Series) -> float:
    if len(labels) == 0:
        return 1.0
    return float(np.mean((probs.to_numpy(dtype=float) - labels.to_numpy(dtype=float)) ** 2))


def _expected_calibration_error(labels: pd.Series, probs: pd.Series, *, n_bins: int) -> float:
    if len(labels) == 0:
        return 1.0
    edges = np.linspace(0.0, 1.0, max(int(n_bins), 1) + 1)
    total = len(labels)
    error = 0.0
    labels_np = labels.to_numpy(dtype=float)
    probs_np = probs.to_numpy(dtype=float)
    for left, right in zip(edges[:-1], edges[1:]):
        if right == 1.0:
            mask = (probs_np >= left) & (probs_np <= right)
        else:
            mask = (probs_np >= left) & (probs_np < right)
        if not np.any(mask):
            continue
        acc = float(np.mean(labels_np[mask]))
        conf = float(np.mean(probs_np[mask]))
        error += abs(acc - conf) * (mask.sum() / total)
    return float(error)


def _empty_result(
    reason: str,
    *,
    aggregate_overrides: dict[str, Any] | None = None,
) -> RegimeProbValidationResult:
    aggregate = {
        "score": -1_000_000.0,
        "window_count": 0,
        "positive_window_rate": 0.0,
        "mean_support_count": 0.0,
        "mean_support_rate": 0.0,
        "mean_edge_return": 0.0,
        "mean_positive_rate": 0.0,
        "mean_brier_score": 1.0,
        "mean_expected_calibration_error": 1.0,
        "mean_decision_flip_rate": 0.0,
        "mean_threshold_churn": 0.0,
    }
    if aggregate_overrides:
        aggregate.update(aggregate_overrides)
    return RegimeProbValidationResult(
        score=-1_000_000.0,
        rejected=True,
        rejection_reasons=(reason,),
        windows=(),
        aggregate=aggregate,
    )


__all__ = [
    "RegimeProbObjectiveWeights",
    "RegimeProbOptimizationGates",
    "RegimeProbRollingValidationConfig",
    "RegimeProbValidationResult",
    "RegimeProbWindowMetric",
    "compare_oos_gate",
    "evaluate_regime_prob_frame",
]
