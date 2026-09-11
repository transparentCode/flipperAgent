"""Failure diagnostics for RegimeV2 offline selection-overlay experiments.

The matrix gate tells us *whether* the overlay helped.  This module explains
*why* losing windows lost, using the selected candidate replay frame produced by
``run_regime_v2_trend_selection_overlay``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FailureDiagnosticConfig:
    """Thresholds used to classify RegimeV2 overlay failures."""

    bad_edge_threshold: float = 0.0
    low_trend_score_threshold: float = 0.35
    high_chop_risk_threshold: float = 0.60
    high_uncertainty_threshold: float = 0.65
    high_false_breakout_risk_threshold: float = 0.60
    high_shock_risk_threshold: float = 0.60
    low_confidence_threshold: float = 0.35


def diagnose_selection_overlay_failures(
    selected_frame: pd.DataFrame,
    *,
    config: FailureDiagnosticConfig | None = None,
) -> dict[str, Any]:
    """Explain failure modes in an offline RegimeV2 selected-candidate frame.

    Returns a JSON-safe dictionary.  The function is defensive: if optional
    diagnostic columns are absent, it still returns counts from available edge
    and model-selection columns.
    """
    cfg = config or FailureDiagnosticConfig()
    if selected_frame.empty:
        return {
            "row_count": 0,
            "bad_row_count": 0,
            "bad_row_rate": None,
            "reason_counts": {},
            "reason_rates": {},
            "top_reasons": [],
            "summary": "no_selected_rows",
            "config": asdict(cfg),
        }

    frame = selected_frame.copy()
    baseline_edge = _numeric(frame.get("baseline_edge"), frame.index)
    overlay_edge = _numeric(frame.get("overlay_edge"), frame.index)
    gated_edge = _numeric(frame.get("gated_edge"), frame.index)
    evaluated_edge = gated_edge.where(gated_edge.notna(), overlay_edge)
    edge_delta = evaluated_edge - baseline_edge

    bad_mask = evaluated_edge.notna() & (evaluated_edge <= cfg.bad_edge_threshold)
    bad = frame.loc[bad_mask].copy()
    bad_count = int(len(bad))
    row_count = int(len(frame))

    if bad.empty:
        return {
            "row_count": row_count,
            "bad_row_count": 0,
            "bad_row_rate": 0.0,
            "mean_bad_edge": None,
            "mean_edge_delta": _round(edge_delta.mean()),
            "reason_counts": {},
            "reason_rates": {},
            "top_reasons": [],
            "summary": "no_material_failures",
            "config": asdict(cfg),
        }

    trend_playbook = _playbook_is(bad, {"trend"}, default_when_missing=True)
    breakout_playbook = _playbook_is(bad, {"breakout"}, default_when_missing=False)
    mean_reversion_playbook = _playbook_is(bad, {"mean_reversion"}, default_when_missing=False)
    reasons = {
        "trend_direction_wrong": trend_playbook & _trend_direction_wrong(bad, cfg),
        "low_trend_score": trend_playbook & (_numeric(bad.get("regime_v2_policy_trend_score"), bad.index) < cfg.low_trend_score_threshold),
        "low_breakout_score": breakout_playbook & (_numeric(bad.get("regime_v2_policy_breakout_score"), bad.index) < cfg.low_trend_score_threshold),
        "low_mean_reversion_score": mean_reversion_playbook & (_numeric(bad.get("regime_v2_policy_mean_reversion_score"), bad.index) < cfg.low_trend_score_threshold),
        "low_confidence": _numeric(bad.get("regime_v2_confidence"), bad.index) < cfg.low_confidence_threshold,
        "high_uncertainty": _numeric(bad.get("regime_v2_uncertainty"), bad.index) >= cfg.high_uncertainty_threshold,
        "chop_leakage": _numeric(bad.get("regime_v2_chop_risk"), bad.index) >= cfg.high_chop_risk_threshold,
        "false_breakout_risk": _numeric(bad.get("regime_v2_false_breakout_risk"), bad.index) >= cfg.high_false_breakout_risk_threshold,
        "shock_risk": _numeric(bad.get("regime_v2_shock_risk"), bad.index) >= cfg.high_shock_risk_threshold,
        "overlay_changed_pick": _changed_pick(bad),
        "conflict_penalty_selected": _bool_series(bad.get("_overlay_conflict_penalty"), bad.index),
        "aligned_pick_lost": _bool_series(bad.get("_overlay_aligned_boost"), bad.index),
        "missing_gated_pick": bad.get("gated_model", pd.Series(np.nan, index=bad.index)).isna(),
        "no_active_playbook": _playbook_is(bad, {"none"}, default_when_missing=False),
    }
    reason_counts = {name: int(mask.fillna(False).sum()) for name, mask in reasons.items()}
    reason_rates = {name: _round(count / bad_count) for name, count in reason_counts.items()}
    top_reasons = [
        {"reason": name, "count": count, "rate": reason_rates[name]}
        for name, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 0
    ]

    return {
        "row_count": row_count,
        "bad_row_count": bad_count,
        "bad_row_rate": _round(bad_count / row_count),
        "mean_bad_edge": _round(evaluated_edge.loc[bad_mask].mean()),
        "mean_edge_delta": _round(edge_delta.mean()),
        "reason_counts": reason_counts,
        "reason_rates": reason_rates,
        "top_reasons": top_reasons,
        "summary": _summary_label(top_reasons),
        "config": asdict(cfg),
    }


def summarize_failure_diagnostics(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-window failure diagnostics into one compact summary."""
    if not diagnostics:
        return {
            "diagnostic_count": 0,
            "bad_row_count": 0,
            "reason_counts": {},
            "reason_rates": {},
            "top_reasons": [],
        }

    reason_counts: dict[str, int] = {}
    bad_rows = 0
    total_rows = 0
    for diagnostic in diagnostics:
        bad_rows += int(diagnostic.get("bad_row_count") or 0)
        total_rows += int(diagnostic.get("row_count") or 0)
        for reason, count in dict(diagnostic.get("reason_counts", {})).items():
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + int(count or 0)

    reason_rates = {
        reason: _round(count / bad_rows) if bad_rows else None
        for reason, count in sorted(reason_counts.items())
    }
    top_reasons = [
        {"reason": reason, "count": count, "rate": reason_rates[reason]}
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 0
    ]
    return {
        "diagnostic_count": int(len(diagnostics)),
        "row_count": int(total_rows),
        "bad_row_count": int(bad_rows),
        "bad_row_rate": _round(bad_rows / total_rows) if total_rows else None,
        "reason_counts": reason_counts,
        "reason_rates": reason_rates,
        "top_reasons": top_reasons,
        "summary": _summary_label(top_reasons),
    }


def _trend_direction_wrong(frame: pd.DataFrame, cfg: FailureDiagnosticConfig) -> pd.Series:
    regime_side = _numeric(frame.get("_regime_side"), frame.index)
    trend_score = _numeric(frame.get("regime_v2_policy_trend_score"), frame.index)
    evaluated_direction = _numeric(frame.get("gated_direction"), frame.index).where(
        _numeric(frame.get("gated_direction"), frame.index).notna(),
        _numeric(frame.get("overlay_direction"), frame.index),
    )
    evaluated_edge = _numeric(frame.get("gated_edge"), frame.index).where(
        _numeric(frame.get("gated_edge"), frame.index).notna(),
        _numeric(frame.get("overlay_edge"), frame.index),
    )
    return (
        (regime_side != 0.0)
        & (evaluated_direction == regime_side)
        & (trend_score >= cfg.low_trend_score_threshold)
        & (evaluated_edge <= cfg.bad_edge_threshold)
    )


def _changed_pick(frame: pd.DataFrame) -> pd.Series:
    baseline = frame.get("baseline_model", pd.Series(np.nan, index=frame.index)).astype(str)
    overlay = frame.get("overlay_model", pd.Series(np.nan, index=frame.index)).astype(str)
    return baseline != overlay


def _playbook_is(frame: pd.DataFrame, names: set[str], *, default_when_missing: bool) -> pd.Series:
    if "_overlay_playbook" not in frame.columns:
        return pd.Series(default_when_missing, index=frame.index, dtype=bool)
    playbook = frame["_overlay_playbook"].fillna("none").astype(str)
    return playbook.isin(names)


def _numeric(series: Any, index: pd.Index) -> pd.Series:
    if series is None:
        return pd.Series(np.nan, index=index, dtype=float)
    if not isinstance(series, pd.Series):
        series = pd.Series(series, index=index)
    return pd.to_numeric(series, errors="coerce")


def _bool_series(series: Any, index: pd.Index) -> pd.Series:
    if series is None:
        return pd.Series(False, index=index)
    if not isinstance(series, pd.Series):
        series = pd.Series(series, index=index)
    return series.fillna(False).astype(bool)


def _summary_label(top_reasons: list[dict[str, Any]]) -> str:
    if not top_reasons:
        return "no_material_failures"
    return str(top_reasons[0]["reason"])


def _round(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 8)


__all__ = [
    "FailureDiagnosticConfig",
    "diagnose_selection_overlay_failures",
    "summarize_failure_diagnostics",
]
