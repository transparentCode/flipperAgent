"""Diagnostics for RegimeClassification alpha-ladder artifacts."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np

from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)

_POLICY_NUMERIC_KEYS = (
    "max_vol_percentile",
    "max_changepoint_prob",
    "max_crisis_prob",
    "min_trend_strength",
    "min_confidence",
    "trend_power",
    "min_position_scale",
)


def diagnose_alpha_payload(
    payload: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Diagnose policy stability and shuffled controls in an alpha artifact."""
    cfg = settings or load_regime_optimization_settings()
    reports = [
        diagnose_alpha_report(report, settings=cfg)
        for report in payload.get("reports", [])
    ]
    return {
        "artifact_panel_summary": payload.get("panel_summary", {}),
        "reports": reports,
        "summary": _summarize_diagnostics(reports),
    }


def diagnose_alpha_report(
    report: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Diagnose one alpha-ladder report, rolling or single-split."""
    cfg = settings or load_regime_optimization_settings()
    all_rows = list(_iter_policy_rows(report))
    best_rows = _best_rows_by_fold(all_rows)
    return {
        "asset": report.get("asset", ""),
        "timeframe": report.get("timeframe", ""),
        "status": report.get("status", ""),
        "is_rolling": bool(report.get("folds")),
        "folds": len({row["fold_index"] for row in all_rows}),
        "all_policy_rows": len(all_rows),
        "best_policy_rows": len(best_rows),
        "policy_stability": _policy_stability(best_rows),
        "gate_failures": _gate_failure_summary(best_rows, cfg),
        "shuffled_control": _shuffled_summary(all_rows, best_rows),
        "validation_oos_decay": _validation_oos_decay(all_rows, best_rows),
    }


def _iter_policy_rows(report: dict[str, Any]):
    folds = report.get("folds") or [report]
    for fold_idx, fold in enumerate(folds):
        actual_fold_idx = int(fold.get("fold_index", fold_idx))
        for strategy_name, strategy in fold.get("strategies", {}).items():
            overlay = strategy.get("overlays", {}).get("optimized_policy", {})
            selection = overlay.get("selection", {})
            policy = selection.get("policy", {})
            oos = overlay.get("metrics", {}).get("oos", {})
            shuffled = overlay.get("shuffled_control", {}).get("oos", {})
            lifts = overlay.get("oos_lifts", {})
            yield {
                "fold_index": actual_fold_idx,
                "fold_start": fold.get("fold_start") or fold.get("date_from"),
                "fold_end": fold.get("fold_end") or fold.get("date_to"),
                "strategy": strategy_name,
                "decision": overlay.get("decision", "reject"),
                "policy": policy,
                "policy_kind": policy.get("policy_kind", ""),
                "validation_score": float(selection.get("validation_score", 0.0)),
                "oos_sharpe": float(oos.get("sharpe", 0.0)),
                "oos_calmar": float(oos.get("calmar", 0.0)),
                "oos_total_return": float(oos.get("total_return", 0.0)),
                "oos_avg_position": float(oos.get("avg_position", 0.0)),
                "oos_turnover": float(oos.get("turnover", 0.0)),
                "shuffled_oos_sharpe": float(shuffled.get("sharpe", 0.0)),
                "shuffled_oos_calmar": float(shuffled.get("calmar", 0.0)),
                "shuffled_oos_return": float(shuffled.get("total_return", 0.0)),
                "sharpe_vs_baseline": float(lifts.get("sharpe_vs_baseline", 0.0)),
                "calmar_vs_baseline": float(lifts.get("calmar_vs_baseline", 0.0)),
                "total_return_vs_baseline": float(
                    lifts.get("total_return_vs_baseline", 0.0)
                ),
                "sharpe_vs_shuffled": float(lifts.get("sharpe_vs_shuffled", 0.0)),
                "calmar_vs_shuffled": float(lifts.get("calmar_vs_shuffled", 0.0)),
            }


def _best_rows_by_fold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best = []
    for fold_index in sorted({row["fold_index"] for row in rows}):
        fold_rows = [row for row in rows if row["fold_index"] == fold_index]
        if not fold_rows:
            continue
        best.append(
            sorted(
                fold_rows,
                key=lambda row: (
                    row["decision"] == "promote_to_downstream_research",
                    row["oos_sharpe"],
                    row["oos_total_return"],
                ),
                reverse=True,
            )[0]
        )
    return best


def _policy_stability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    policy_kinds = [row["policy_kind"] for row in rows]
    strategies = [row["strategy"] for row in rows]
    return {
        "best_policy_kind_counts": dict(Counter(policy_kinds)),
        "best_strategy_counts": dict(Counter(strategies)),
        "policy_kind_churn_rate": _churn_rate(policy_kinds),
        "strategy_churn_rate": _churn_rate(strategies),
        "numeric_policy_summary": _numeric_policy_summary(rows),
    }


def _gate_failure_summary(
    rows: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    per_fold = []
    for row in rows:
        failures = _gate_failures(row, cfg)
        counts.update(failures)
        per_fold.append(
            {
                "fold_index": row["fold_index"],
                "strategy": row["strategy"],
                "decision": row["decision"],
                "failures": failures,
            }
        )
    return {"failure_counts": dict(counts), "per_fold": per_fold}


def _gate_failures(row: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    ladder_cfg = cfg.get("benchmark_ladder", {})
    failures = []
    checks = {
        "sharpe_lift_low": row["sharpe_vs_baseline"]
        < float(ladder_cfg.get("min_sharpe_lift", 0.10)),
        "calmar_lift_low": row["calmar_vs_baseline"]
        < float(ladder_cfg.get("min_calmar_lift", 0.05)),
        "return_lift_low": row["total_return_vs_baseline"]
        < float(ladder_cfg.get("min_total_return_lift", 0.0)),
        "loses_to_shuffled_sharpe": row["sharpe_vs_shuffled"] < 0,
        "oos_sharpe_low": row["oos_sharpe"]
        < float(ladder_cfg.get("min_oos_sharpe", 0.0)),
        "oos_return_low": row["oos_total_return"]
        < float(ladder_cfg.get("min_oos_total_return", 0.0)),
        "avg_position_low": row["oos_avg_position"]
        < float(ladder_cfg.get("min_avg_position", 0.05)),
    }
    for name, failed in checks.items():
        if failed:
            failures.append(name)
    return failures


def _shuffled_summary(
    all_rows: list[dict[str, Any]],
    best_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "all_rows": _shuffled_group_summary(all_rows),
        "best_rows": _shuffled_group_summary(best_rows),
    }


def _shuffled_group_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {}
    real_beats = [row["sharpe_vs_shuffled"] >= 0 for row in rows]
    shuffled_positive = [row["shuffled_oos_sharpe"] > 0 for row in rows]
    return {
        "rows": len(rows),
        "real_beats_shuffled_rate": float(np.mean(real_beats)),
        "shuffled_positive_sharpe_rate": float(np.mean(shuffled_positive)),
        "median_real_oos_sharpe": _median(row["oos_sharpe"] for row in rows),
        "median_shuffled_oos_sharpe": _median(
            row["shuffled_oos_sharpe"] for row in rows
        ),
        "median_sharpe_vs_shuffled": _median(
            row["sharpe_vs_shuffled"] for row in rows
        ),
        "median_calmar_vs_shuffled": _median(
            row["calmar_vs_shuffled"] for row in rows
        ),
    }


def _validation_oos_decay(
    all_rows: list[dict[str, Any]],
    best_rows: list[dict[str, Any]],
) -> dict[str, float]:
    return {
        "all_rows_validation_oos_corr": _corr(
            [row["validation_score"] for row in all_rows],
            [row["oos_sharpe"] for row in all_rows],
        ),
        "best_rows_validation_oos_corr": _corr(
            [row["validation_score"] for row in best_rows],
            [row["oos_sharpe"] for row in best_rows],
        ),
        "median_validation_score_best_rows": _median(
            row["validation_score"] for row in best_rows
        ),
        "median_oos_sharpe_best_rows": _median(row["oos_sharpe"] for row in best_rows),
        "median_oos_return_best_rows": _median(
            row["oos_total_return"] for row in best_rows
        ),
    }


def _numeric_policy_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    summary = {}
    for key in _POLICY_NUMERIC_KEYS:
        values = [float(row["policy"].get(key, 0.0)) for row in rows]
        if not values:
            continue
        arr = np.asarray(values, dtype=float)
        summary[key] = {
            "median": float(np.median(arr)),
            "iqr": float(np.percentile(arr, 75) - np.percentile(arr, 25)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
        }
    return summary


def _summarize_diagnostics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "reports": len(reports),
        "rolling_reports": sum(1 for report in reports if report.get("is_rolling")),
        "rejected_reports": sum(
            1
            for report in reports
            if report.get("status") == "ok"
            and report.get("gate_failures", {}).get("failure_counts")
        ),
    }


def _churn_rate(values: list[str]) -> float:
    if len(values) < 2:
        return 0.0
    changes = sum(1 for left, right in zip(values, values[1:]) if left != right)
    return float(changes / (len(values) - 1))


def _median(values) -> float:
    arr = np.asarray(list(values), dtype=float)
    if len(arr) == 0:
        return 0.0
    return float(np.median(arr))


def _corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3 or len(ys) < 3:
        return 0.0
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    value = float(np.corrcoef(x, y)[0, 1])
    return value if np.isfinite(value) else 0.0
