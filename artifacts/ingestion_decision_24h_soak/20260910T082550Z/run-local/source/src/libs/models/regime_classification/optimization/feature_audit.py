"""Feature ablation audit for RegimeClassification probability descriptors."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.benchmark_ladder import (
    build_regime_feature_frame,
)
from libs.models.regime_classification.optimization.probability_ladder import (
    run_probability_ladder,
    run_rolling_probability_ladder,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)


def run_feature_ablation_audit(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
    rolling: bool = False,
    fold_bars: int | None = None,
    step_bars: int | None = None,
) -> dict[str, Any]:
    """Run one-feature ablations without promoting the model downstream."""
    cfg = settings or load_regime_optimization_settings()
    regime = (
        regime_df.copy()
        if regime_df is not None
        else build_regime_feature_frame(
            price_df,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
        )
    )
    features = _configured_features(cfg, regime.columns)
    rows: list[dict[str, Any]] = []
    for feature in features:
        feature_cfg = deepcopy(cfg)
        feature_cfg.setdefault("probability_ladder", {})["feature_sets"] = [[feature]]
        if rolling:
            report = run_rolling_probability_ladder(
                price_df,
                asset=asset,
                timeframe=timeframe,
                params=params,
                frozen_overrides=frozen_overrides,
                regime_df=regime[[feature]],
                settings=feature_cfg,
                fold_bars=fold_bars,
                step_bars=step_bars,
            )
            metrics = _rolling_feature_metrics(report)
        else:
            report = run_probability_ladder(
                price_df,
                asset=asset,
                timeframe=timeframe,
                params=params,
                frozen_overrides=frozen_overrides,
                regime_df=regime[[feature]],
                settings=feature_cfg,
            )
            metrics = _single_feature_metrics(report)
        rows.append(
            {
                "feature": feature,
                "status": report.get("status", "unknown"),
                "action": _feature_action(metrics, cfg, report.get("status", "unknown")),
                "metrics": metrics,
                "target_metadata": report.get("target_metadata")
                or _fold_target_metadata(report),
            }
        )

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok" if rows else "missing_feature_columns",
        "audit_kind": "rolling_feature_ablation" if rolling else "feature_ablation",
        "features": rows,
        "summary": _summarize_feature_actions(rows),
        "thresholds": _feature_thresholds(cfg),
    }


def _configured_features(cfg: dict[str, Any], available_columns: pd.Index) -> list[str]:
    prob_cfg = cfg.get("probability_ladder", {})
    raw_sets = prob_cfg.get("feature_sets") or prob_cfg.get("feature_columns")
    if raw_sets is None:
        raw_sets = [[str(prob_cfg.get("forecast_column", "fwd_vol_ewma"))]]
    if isinstance(raw_sets, str):
        raw_sets = [[raw_sets]]
    available = {str(column) for column in available_columns}
    features: list[str] = []
    for raw in raw_sets:
        values = [raw] if isinstance(raw, str) else raw
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            feature = str(value)
            if feature in available and feature not in features:
                features.append(feature)
    return features


def _single_feature_metrics(report: dict[str, Any]) -> dict[str, float]:
    if report.get("status") != "ok":
        return _empty_feature_metrics()
    probability = report.get("probability", {})
    prob_lifts = probability.get("oos_lifts", {})
    best_overlay = _best_overlay_row(report)
    decision = probability.get("decision", "reject")
    return {
        "probability_information_lift": float(prob_lifts.get("auc_vs_null", 0.0)),
        "risk_overlay_lift": float(best_overlay.get("sharpe_vs_baseline", 0.0)),
        "null_control_lift": float(best_overlay.get("sharpe_vs_shuffled", 0.0)),
        "fold_stability": 1.0 if decision == "promote_probability_research" else 0.0,
        "oos_auc": float(probability.get("metrics", {}).get("oos", {}).get("auc", 0.5)),
    }


def _rolling_feature_metrics(report: dict[str, Any]) -> dict[str, float]:
    if report.get("status") != "ok":
        return _empty_feature_metrics()
    summary = report.get("summary", {})
    return {
        "probability_information_lift": float(
            summary.get("median_auc_lift_vs_null", 0.0)
        ),
        "risk_overlay_lift": float(summary.get("median_sharpe_lift", 0.0)),
        "null_control_lift": float(summary.get("median_null_sharpe_lift", 0.0)),
        "fold_stability": float(summary.get("probability_pass_rate", 0.0)),
        "oos_auc": float(summary.get("median_oos_auc", 0.5)),
    }


def _empty_feature_metrics() -> dict[str, float]:
    return {
        "probability_information_lift": 0.0,
        "risk_overlay_lift": 0.0,
        "null_control_lift": 0.0,
        "fold_stability": 0.0,
        "oos_auc": 0.5,
    }


def _best_overlay_row(report: dict[str, Any]) -> dict[str, float]:
    rows: list[dict[str, float]] = []
    for strategy in report.get("strategies", {}).values():
        overlay = strategy.get("overlays", {}).get("probability_sized", {})
        lifts = overlay.get("oos_lifts", {})
        rows.append(
            {
                "sharpe_vs_baseline": float(lifts.get("sharpe_vs_baseline", 0.0)),
                "sharpe_vs_shuffled": float(lifts.get("sharpe_vs_shuffled", 0.0)),
            }
        )
    if not rows:
        return {}
    return max(
        rows,
        key=lambda row: (
            row["sharpe_vs_baseline"],
            row["sharpe_vs_shuffled"],
        ),
    )


def _feature_action(
    metrics: dict[str, float],
    cfg: dict[str, Any],
    status: str,
) -> str:
    if status == "missing_derivatives_data":
        return "conditional_by_asset_tf"
    if status != "ok":
        return "drop"
    thresholds = _feature_thresholds(cfg)
    if (
        metrics["probability_information_lift"] >= thresholds["min_probability_lift"]
        and metrics["null_control_lift"] >= thresholds["min_null_control_lift"]
        and metrics["fold_stability"] >= thresholds["min_fold_stability"]
    ):
        return "keep"
    if (
        metrics["probability_information_lift"] < thresholds["drop_probability_lift"]
        and metrics["fold_stability"] < thresholds["drop_fold_stability"]
    ):
        return "drop"
    return "conditional_by_asset_tf"


def _feature_thresholds(cfg: dict[str, Any]) -> dict[str, float]:
    audit_cfg = cfg.get("feature_ablation", {})
    return {
        "min_probability_lift": float(audit_cfg.get("min_probability_lift", 0.0)),
        "min_null_control_lift": float(audit_cfg.get("min_null_control_lift", 0.0)),
        "min_fold_stability": float(audit_cfg.get("min_fold_stability", 0.50)),
        "drop_probability_lift": float(audit_cfg.get("drop_probability_lift", -0.02)),
        "drop_fold_stability": float(audit_cfg.get("drop_fold_stability", 0.25)),
    }


def _summarize_feature_actions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {"keep": 0, "drop": 0, "conditional_by_asset_tf": 0}
    for row in rows:
        action = str(row.get("action", "drop"))
        counts[action] = counts.get(action, 0) + 1
    return {
        "total_features": len(rows),
        "action_counts": counts,
        "keep": [row["feature"] for row in rows if row.get("action") == "keep"],
        "drop": [row["feature"] for row in rows if row.get("action") == "drop"],
        "conditional_by_asset_tf": [
            row["feature"]
            for row in rows
            if row.get("action") == "conditional_by_asset_tf"
        ],
    }


def _fold_target_metadata(report: dict[str, Any]) -> dict[str, Any] | None:
    folds = report.get("folds", [])
    metadata = [fold.get("target_metadata") for fold in folds if fold.get("target_metadata")]
    if not metadata:
        return None
    requested = sorted(
        {
            kind
            for row in metadata
            for kind in row.get("requested_target_kinds", [])
        }
    )
    available = sorted(
        {
            kind
            for row in metadata
            for kind in row.get("available_target_kinds", [])
        }
    )
    missing: dict[str, list[str]] = {}
    for row in metadata:
        for kind, columns in row.get("missing_target_requirements", {}).items():
            missing.setdefault(kind, [])
            for column in columns:
                if column not in missing[kind]:
                    missing[kind].append(column)
    return {
        "requested_target_kinds": requested,
        "available_target_kinds": available,
        "missing_target_requirements": missing,
        "derivative_columns_present": any(
            bool(row.get("derivative_columns_present")) for row in metadata
        ),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    return value
