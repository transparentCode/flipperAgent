"""Simple-model selection ladder for RegimeClassification probabilities.

This downstream gate asks a narrower question than the alpha ladder: after the
probability model is calibrated on train data, can it improve simple MA-style
models selected on validation and audited on untouched OOS data?
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.benchmark_ladder import (
    _build_base_positions,
    _clean_price_frame,
    _index_value,
    _metric_lifts,
    _score_positions,
    build_regime_feature_frame,
)
from libs.models.regime_classification.optimization.probability_ladder import (
    _build_null_regimes,
    _candidate_probability_configs,
    _combine_fold_target_metadata,
    _filter_candidate_configs_for_available_targets,
    _fit_probability_ensemble,
    _predict_probability_ensemble,
    _probability_scale,
    _probability_score,
    _score_probability_config,
    _target_cache,
    _target_for_candidate,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.walk_forward import WalkForwardSplitter


def run_model_selection_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare simple validation-selected models with probability-aware models."""
    cfg = settings or load_regime_optimization_settings()
    ladder_cfg = cfg.get("benchmark_ladder", {})
    model_cfg = cfg.get("model_selection_ladder", {})
    prob_cfg = cfg.get("probability_ladder", {})
    frame = _clean_price_frame(price_df)
    min_bars = int(model_cfg.get("min_bars", prob_cfg.get("min_bars", 500)))
    if len(frame) < min_bars:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "insufficient_data",
            "bars": int(len(frame)),
            "min_bars": min_bars,
        }

    regime = (
        regime_df.copy()
        if regime_df is not None
        else build_regime_feature_frame(
            frame,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
        )
    )
    regime = regime.reindex(frame.index)

    candidate_configs = _candidate_probability_configs(prob_cfg, regime.columns)
    if not candidate_configs:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "missing_feature_columns",
        }
    candidate_configs, target_metadata = _filter_candidate_configs_for_available_targets(
        frame,
        candidate_configs,
    )
    if not candidate_configs:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "missing_derivatives_data",
            "bars": int(len(frame)),
            "target_metadata": target_metadata,
        }

    split = WalkForwardSplitter(
        train_ratio=float(prob_cfg.get("train_ratio", ladder_cfg.get("train_ratio", 0.60))),
        val_ratio=float(prob_cfg.get("val_ratio", ladder_cfg.get("val_ratio", 0.20))),
        oos_ratio=1.0
        - float(prob_cfg.get("train_ratio", ladder_cfg.get("train_ratio", 0.60)))
        - float(prob_cfg.get("val_ratio", ladder_cfg.get("val_ratio", 0.20))),
        purge_bars=int(prob_cfg.get("purge_bars", ladder_cfg.get("purge_bars", 24))),
    ).split(len(frame))
    segments = {
        "train": (split.train_start, split.train_end),
        "validate": (split.val_start, split.val_end),
        "oos": (split.oos_start, split.oos_end),
        "full": (0, len(frame)),
    }

    targets = _target_cache(frame, candidate_configs, prob_cfg)
    null_regimes = _build_null_regimes(regime, prob_cfg)
    selected_probability = _select_probability_for_model_selection(
        regime,
        null_regimes,
        targets,
        segments=segments,
        probability_cfg=prob_cfg,
        model_cfg=model_cfg,
        candidate_configs=candidate_configs,
    )
    probability_report = _score_probability_config(
        selected_probability,
        regime,
        null_regimes,
        targets,
        segments=segments,
        cfg=prob_cfg,
    )
    base_positions = _filtered_base_positions(frame, ladder_cfg, model_cfg)
    raw_selection = _select_best_raw_model(
        base_positions,
        frame,
        segments,
        timeframe=timeframe,
        cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        cfg=model_cfg,
    )
    probability_selection = _select_best_probability_model(
        base_positions,
        frame,
        regime,
        selected_probability,
        segments,
        timeframe=timeframe,
        cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        cfg=model_cfg,
    )
    null_selection = _score_null_probability_model(
        probability_selection,
        base_positions,
        frame,
        null_regimes,
        targets,
        selected_probability,
        segments,
        timeframe=timeframe,
        cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
    )
    lifts = _metric_lifts(
        probability_selection["metrics"]["oos"],
        raw_selection["metrics"]["oos"],
        null_selection["metrics"]["oos"],
    )
    _add_risk_lifts(
        lifts,
        probability_selection["metrics"]["oos"],
        raw_selection["metrics"]["oos"],
        null_selection["metrics"]["oos"],
    )
    decision = _model_selection_decision(
        probability_selection["metrics"]["oos"],
        raw_selection["metrics"]["oos"],
        lifts,
        cfg=model_cfg,
    )
    risk_decision = _risk_overlay_decision(
        probability_selection["metrics"]["oos"],
        lifts,
        cfg=model_cfg,
    )

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "date_from": _index_value(frame, 0),
        "date_to": _index_value(frame, -1),
        "target_metadata": {
            **target_metadata,
            "selected_target_kind": selected_probability["config"].get("target_kind"),
            "selected_target_horizon": selected_probability["config"].get(
                "target_horizon"
            ),
        },
        "probability": probability_report,
        "raw_selection": raw_selection,
        "probability_selection": probability_selection,
        "null_selection": null_selection,
        "oos_lifts": lifts,
        "panel_decision": decision,
        "risk_overlay_decision": risk_decision,
    }


def run_rolling_model_selection_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
    fold_bars: int | None = None,
    step_bars: int | None = None,
) -> dict[str, Any]:
    """Run repeated chronological model-selection folds."""
    cfg = settings or load_regime_optimization_settings()
    rolling_cfg = cfg.get("rolling_model_selection_ladder", {})
    frame = _clean_price_frame(price_df)
    fold_size = int(fold_bars or rolling_cfg.get("fold_bars", 2160))
    step_size = int(step_bars or rolling_cfg.get("step_bars", 720))
    min_folds = int(rolling_cfg.get("min_folds", 2))
    if len(frame) < fold_size:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "insufficient_data",
            "bars": int(len(frame)),
            "fold_bars": fold_size,
        }

    regime = (
        regime_df.copy()
        if regime_df is not None
        else build_regime_feature_frame(
            frame,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
        )
    )
    regime = regime.reindex(frame.index)

    folds: list[dict[str, Any]] = []
    for fold_idx, start in enumerate(range(0, len(frame) - fold_size + 1, step_size)):
        fold_frame = frame.iloc[start : start + fold_size]
        fold_report = run_model_selection_ladder(
            fold_frame,
            asset=asset,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
            regime_df=regime.loc[fold_frame.index],
            settings=cfg,
        )
        fold_report["fold_index"] = fold_idx
        fold_report["fold_start"] = _index_value(fold_frame, 0)
        fold_report["fold_end"] = _index_value(fold_frame, -1)
        folds.append(fold_report)

    if folds and all(fold.get("status") == "missing_derivatives_data" for fold in folds):
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "missing_derivatives_data",
            "bars": int(len(frame)),
            "fold_bars": fold_size,
            "step_bars": step_size,
            "folds": folds,
            "target_metadata": _combine_fold_target_metadata(folds),
        }

    if len(folds) < min_folds:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "insufficient_folds",
            "bars": int(len(frame)),
            "folds": len(folds),
            "min_folds": min_folds,
        }

    summary = summarize_rolling_model_selection_ladder(folds, settings=cfg)
    risk_summary = summarize_rolling_risk_overlay(folds, settings=cfg)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "fold_bars": fold_size,
        "step_bars": step_size,
        "folds": folds,
        "summary": summary,
        "risk_summary": risk_summary,
        "panel_decision": summary["decision"],
        "risk_overlay_decision": risk_summary["decision"],
    }


def summarize_model_selection_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multiple model-selection reports."""
    usable = [row for row in rows if row.get("status") == "ok"]
    decisions: dict[str, int] = {}
    risk_decisions: dict[str, int] = {}
    promoted = 0
    risk_promoted = 0
    for row in usable:
        decision = row.get("panel_decision", "reject")
        decisions[decision] = decisions.get(decision, 0) + 1
        if decision == "promote_model_selection_research":
            promoted += 1
        risk_decision = row.get("risk_overlay_decision", "reject")
        risk_decisions[risk_decision] = risk_decisions.get(risk_decision, 0) + 1
        if risk_decision == "promote_risk_overlay_research":
            risk_promoted += 1
    return {
        "usable_slices": len(usable),
        "total_slices": len(rows),
        "decision_counts": decisions,
        "promoted_slices": promoted,
        "rejected_slices": len(usable) - promoted,
        "risk_decision_counts": risk_decisions,
        "risk_promoted_slices": risk_promoted,
        "risk_rejected_slices": len(usable) - risk_promoted,
    }


def summarize_rolling_model_selection_ladder(
    folds: list[dict[str, Any]],
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate rolling model-selection folds into one decision."""
    cfg = settings or load_regime_optimization_settings()
    rolling_cfg = cfg.get("rolling_model_selection_ladder", {})
    usable = [fold for fold in folds if fold.get("status") == "ok"]
    promoted = [
        fold
        for fold in usable
        if fold.get("panel_decision") == "promote_model_selection_research"
    ]
    pass_rate = len(promoted) / len(usable) if usable else 0.0
    lifts = [fold["oos_lifts"] for fold in usable]
    prob_rows = [fold["probability"] for fold in usable]
    median_sharpe_lift = _median(row["sharpe_vs_baseline"] for row in lifts)
    median_null_lift = _median(row["sharpe_vs_shuffled"] for row in lifts)
    median_return_lift = _median(row["total_return_vs_baseline"] for row in lifts)
    median_auc_lift = _median(row["oos_lifts"]["auc_vs_null"] for row in prob_rows)
    decision = (
        "promote_model_selection_research"
        if len(promoted) >= int(rolling_cfg.get("min_promoted_folds", 2))
        and pass_rate >= float(rolling_cfg.get("min_pass_rate", 0.60))
        and median_sharpe_lift >= float(rolling_cfg.get("min_median_sharpe_lift", 0.0))
        and median_null_lift >= float(rolling_cfg.get("min_median_null_sharpe_lift", 0.0))
        and median_auc_lift >= float(rolling_cfg.get("min_median_auc_lift", 0.0))
        else "reject"
    )
    return {
        "total_folds": len(folds),
        "usable_folds": len(usable),
        "promoted_folds": len(promoted),
        "rejected_folds": len(usable) - len(promoted),
        "pass_rate": float(pass_rate),
        "median_sharpe_lift": float(median_sharpe_lift),
        "median_null_sharpe_lift": float(median_null_lift),
        "median_return_lift": float(median_return_lift),
        "median_auc_lift_vs_null": float(median_auc_lift),
        "best_rows": [_fold_row(fold) for fold in usable],
        "decision": decision,
    }


def summarize_rolling_risk_overlay(
    folds: list[dict[str, Any]],
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate rolling folds for risk-overlay usability."""
    cfg = settings or load_regime_optimization_settings()
    rolling_cfg = cfg.get("rolling_model_selection_ladder", {})
    usable = [fold for fold in folds if fold.get("status") == "ok"]
    promoted = [
        fold
        for fold in usable
        if fold.get("risk_overlay_decision") == "promote_risk_overlay_research"
    ]
    pass_rate = len(promoted) / len(usable) if usable else 0.0
    lifts = [fold["oos_lifts"] for fold in usable]
    median_dd_lift = _median(
        row["max_drawdown_improvement_vs_baseline"] for row in lifts
    )
    median_null_dd_lift = _median(
        row["max_drawdown_improvement_vs_shuffled"] for row in lifts
    )
    median_return_lift = _median(row["total_return_vs_baseline"] for row in lifts)
    median_null_return_lift = _median(row["total_return_vs_shuffled"] for row in lifts)
    decision = (
        "promote_risk_overlay_research"
        if len(promoted) >= int(rolling_cfg.get("min_risk_promoted_folds", 2))
        and pass_rate >= float(rolling_cfg.get("min_risk_pass_rate", 0.60))
        and median_dd_lift
        >= float(rolling_cfg.get("min_median_risk_drawdown_improvement", 0.0))
        and median_null_dd_lift
        >= float(rolling_cfg.get("min_median_risk_null_drawdown_improvement", 0.0))
        and median_return_lift
        >= float(rolling_cfg.get("min_median_risk_total_return_lift", 0.0))
        and median_null_return_lift
        >= float(rolling_cfg.get("min_median_risk_null_total_return_lift", 0.0))
        else "reject"
    )
    return {
        "total_folds": len(folds),
        "usable_folds": len(usable),
        "promoted_folds": len(promoted),
        "rejected_folds": len(usable) - len(promoted),
        "pass_rate": float(pass_rate),
        "median_drawdown_improvement": float(median_dd_lift),
        "median_null_drawdown_improvement": float(median_null_dd_lift),
        "median_return_lift": float(median_return_lift),
        "median_null_return_lift": float(median_null_return_lift),
        "decision": decision,
    }


def _select_probability_for_model_selection(
    regime: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    targets: dict[tuple[str, int], pd.Series],
    *,
    segments: dict[str, tuple[int, int]],
    probability_cfg: dict[str, Any],
    model_cfg: dict[str, Any],
    candidate_configs: list[dict[str, Any]],
) -> dict[str, Any]:
    train = slice(*segments["train"])
    validate = slice(*segments["validate"])
    best: dict[str, Any] | None = None
    for candidate in candidate_configs:
        target = _target_for_candidate(targets, candidate)
        fitted = _fit_probability_ensemble(
            regime,
            target,
            train_slice=train,
            cfg=candidate,
        )
        probs = _predict_probability_ensemble(regime, fitted)
        event = (target > fitted["event_threshold"]).astype(float)
        event[target.isna()] = np.nan
        metrics = _probability_metrics_for_selection(probs[validate], event.iloc[validate])
        null_metrics = _hardest_null_probability_metrics(
            null_regimes,
            targets,
            candidate,
            train_slice=train,
            segment=validate,
        )
        score = _probability_score(metrics, null_metrics, probability_cfg)
        score += float(model_cfg.get("probability_validation_weight", 0.25)) * (
            metrics["top_bottom_event_spread"]
        )
        row = {
            "config": candidate,
            "fitted_config": fitted,
            "validation_score": score,
            "validation_metrics": metrics,
            "validation_null_metrics": null_metrics,
        }
        if best is None or score > float(best["validation_score"]):
            best = row
    return best or {}


def _filtered_base_positions(
    frame: pd.DataFrame,
    ladder_cfg: dict[str, Any],
    model_cfg: dict[str, Any],
) -> dict[str, np.ndarray]:
    base = _build_base_positions(frame, ladder_cfg)
    allowed = model_cfg.get("base_models", ["sma_cross", "ema_cross", "buy_and_hold"])
    if isinstance(allowed, str):
        allowed = [allowed]
    return {name: base[name] for name in allowed if name in base}


def _select_best_raw_model(
    base_positions: dict[str, np.ndarray],
    frame: pd.DataFrame,
    segments: dict[str, tuple[int, int]],
    *,
    timeframe: str,
    cost_bps: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        _score_model_row(
            name,
            positions,
            frame,
            segments,
            timeframe=timeframe,
            cost_bps=cost_bps,
            cfg=cfg,
        )
        for name, positions in base_positions.items()
    ]
    return _best_by_validation(rows)


def _select_best_probability_model(
    base_positions: dict[str, np.ndarray],
    frame: pd.DataFrame,
    regime: pd.DataFrame,
    selected_probability: dict[str, Any],
    segments: dict[str, tuple[int, int]],
    *,
    timeframe: str,
    cost_bps: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    probs = _predict_probability_ensemble(regime, selected_probability["fitted_config"])
    train_probs = probs[slice(*segments["train"])]
    rows = []
    for name, positions in base_positions.items():
        for policy in _configured_probability_policies(cfg):
            scale = _probability_policy_scale(
                probs,
                selected_probability["config"],
                selected_probability["fitted_config"],
                policy,
                train_probs=train_probs,
            )
            row = _score_model_row(
                f"{name}:{policy}",
                positions * scale,
                frame,
                segments,
                timeframe=timeframe,
                cost_bps=cost_bps,
                cfg=cfg,
                base_model=name,
            )
            row["probability_policy"] = policy
            row["probability_config"] = selected_probability["config"]
            rows.append(row)
    row = _best_by_validation(rows)
    row["probability_config"] = selected_probability["config"]
    return row


def _score_null_probability_model(
    probability_selection: dict[str, Any],
    base_positions: dict[str, np.ndarray],
    frame: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    targets: dict[tuple[str, int], pd.Series],
    selected_probability: dict[str, Any],
    segments: dict[str, tuple[int, int]],
    *,
    timeframe: str,
    cost_bps: float,
) -> dict[str, Any]:
    rows = []
    model = str(probability_selection["model"])
    policy = str(probability_selection.get("probability_policy", "throttle_high_vol"))
    base = base_positions[model]
    for mode, null_regime in null_regimes.items():
        null_fit = _fit_probability_ensemble(
            null_regime,
            _target_for_candidate(targets, selected_probability["config"]),
            train_slice=slice(*segments["train"]),
            cfg=selected_probability["config"],
        )
        null_probs = _predict_probability_ensemble(null_regime, null_fit)
        positions = base * _probability_policy_scale(
            null_probs,
            selected_probability["config"],
            null_fit,
            policy,
            train_probs=null_probs[slice(*segments["train"])],
        )
        row = _score_model_row(
            f"{model}:{policy}:{mode}",
            positions,
            frame,
            segments,
            timeframe=timeframe,
            cost_bps=cost_bps,
            cfg={},
            base_model=model,
        )
        row["null_mode"] = mode
        row["probability_policy"] = policy
        rows.append(row)
    return _best_by_validation(rows) if rows else probability_selection


def _score_model_row(
    name: str,
    positions: np.ndarray,
    frame: pd.DataFrame,
    segments: dict[str, tuple[int, int]],
    *,
    timeframe: str,
    cost_bps: float,
    cfg: dict[str, Any],
    base_model: str | None = None,
) -> dict[str, Any]:
    metrics = {
        segment: _score_positions(
            positions[start:end],
            frame.iloc[start:end],
            timeframe=timeframe,
            cost_bps=cost_bps,
        )
        for segment, (start, end) in segments.items()
    }
    return {
        "model": base_model or name,
        "variant": name,
        "metrics": metrics,
        "validation_score": _model_score(metrics["validate"], cfg),
    }


def _model_score(metrics: dict[str, float], cfg: dict[str, Any]) -> float:
    return (
        metrics["sharpe"]
        + float(cfg.get("calmar_weight", 0.25)) * metrics["calmar"]
        + float(cfg.get("return_weight", 1.0)) * metrics["total_return"]
        - float(cfg.get("turnover_penalty", 0.0)) * metrics["turnover"]
    )


def _configured_probability_policies(cfg: dict[str, Any]) -> list[str]:
    raw = cfg.get(
        "probability_policies",
        [
            "throttle_high_vol",
            "rank_throttle",
            "prefer_high_vol",
            "rank_prefer_high_vol",
            "confidence_scaled",
        ],
    )
    if isinstance(raw, str):
        raw = [raw]
    allowed = {
        "throttle_high_vol",
        "rank_throttle",
        "prefer_high_vol",
        "rank_prefer_high_vol",
        "confidence_scaled",
    }
    policies: list[str] = []
    for item in raw:
        policy = str(item)
        if policy in allowed and policy not in policies:
            policies.append(policy)
    return policies or ["throttle_high_vol"]


def _probability_policy_scale(
    probs: np.ndarray,
    cfg: dict[str, Any],
    fitted: dict[str, Any],
    policy: str,
    *,
    train_probs: np.ndarray,
) -> np.ndarray:
    p = np.clip(np.asarray(probs, dtype=float), 0.0, 1.0)
    min_scale = float(cfg.get("min_position_scale", 0.25))
    if policy == "throttle_high_vol":
        return _probability_scale(p, cfg)
    if policy == "rank_throttle":
        return np.clip(1.0 - float(cfg.get("risk_budget", 0.50)) * _probability_rank(p, train_probs), min_scale, 1.0)
    if policy == "prefer_high_vol":
        return np.clip(min_scale + (1.0 - min_scale) * p, min_scale, 1.0)
    if policy == "rank_prefer_high_vol":
        return np.clip(
            min_scale + (1.0 - min_scale) * _probability_rank(p, train_probs),
            min_scale,
            1.0,
        )
    if policy == "confidence_scaled":
        base_rate = float(fitted.get("base_rate", np.nanmean(train_probs)))
        denom = max(base_rate, 1.0 - base_rate, 1e-9)
        confidence = np.clip(np.abs(p - base_rate) / denom, 0.0, 1.0)
        return np.clip(min_scale + (1.0 - min_scale) * confidence, min_scale, 1.0)
    return _probability_scale(p, cfg)


def _probability_rank(probs: np.ndarray, train_probs: np.ndarray) -> np.ndarray:
    train = np.asarray(train_probs, dtype=float)
    train = np.sort(train[np.isfinite(train)])
    if len(train) == 0:
        return np.full(len(probs), 0.5, dtype=float)
    ranks = np.searchsorted(train, np.asarray(probs, dtype=float), side="right")
    return np.clip(ranks / len(train), 0.0, 1.0)


def _best_by_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return sorted(
        rows,
        key=lambda row: (
            row["validation_score"],
            row["metrics"]["validate"]["sharpe"],
            row["metrics"]["validate"]["total_return"],
        ),
        reverse=True,
    )[0]


def _model_selection_decision(
    probability_metrics: dict[str, float],
    raw_metrics: dict[str, float],
    lifts: dict[str, float],
    *,
    cfg: dict[str, Any],
) -> str:
    dd_improvement = abs(raw_metrics["max_drawdown"]) - abs(
        probability_metrics["max_drawdown"]
    )
    if (
        lifts["sharpe_vs_baseline"] >= float(cfg.get("min_sharpe_lift", 0.0))
        and lifts["sharpe_vs_shuffled"] >= float(cfg.get("min_null_sharpe_lift", 0.0))
        and lifts["total_return_vs_baseline"]
        >= float(cfg.get("min_total_return_lift", -1.0))
        and dd_improvement >= float(cfg.get("min_drawdown_improvement", -1.0))
        and probability_metrics["avg_position"]
        >= float(cfg.get("min_avg_position", 0.05))
    ):
        return "promote_model_selection_research"
    return "reject"


def _add_risk_lifts(
    lifts: dict[str, float],
    probability_metrics: dict[str, float],
    raw_metrics: dict[str, float],
    null_metrics: dict[str, float],
) -> None:
    lifts["max_drawdown_improvement_vs_baseline"] = abs(
        raw_metrics["max_drawdown"]
    ) - abs(probability_metrics["max_drawdown"])
    lifts["max_drawdown_improvement_vs_shuffled"] = abs(
        null_metrics["max_drawdown"]
    ) - abs(probability_metrics["max_drawdown"])
    lifts["total_return_vs_shuffled"] = (
        probability_metrics["total_return"] - null_metrics["total_return"]
    )


def _risk_overlay_decision(
    probability_metrics: dict[str, float],
    lifts: dict[str, float],
    *,
    cfg: dict[str, Any],
) -> str:
    if (
        lifts["max_drawdown_improvement_vs_baseline"]
        >= float(cfg.get("min_risk_drawdown_improvement", 0.0))
        and lifts["max_drawdown_improvement_vs_shuffled"]
        >= float(cfg.get("min_risk_null_drawdown_improvement", 0.0))
        and lifts["total_return_vs_baseline"]
        >= float(cfg.get("min_risk_total_return_lift", 0.0))
        and lifts["total_return_vs_shuffled"]
        >= float(cfg.get("min_risk_null_total_return_lift", 0.0))
        and probability_metrics["avg_position"]
        >= float(cfg.get("min_avg_position", 0.05))
    ):
        return "promote_risk_overlay_research"
    return "reject"


def _hardest_null_probability_metrics(
    null_regimes: dict[str, pd.DataFrame],
    targets: dict[tuple[str, int], pd.Series],
    candidate: dict[str, Any],
    *,
    train_slice: slice,
    segment: slice,
) -> dict[str, float]:
    metrics = []
    for null_regime in null_regimes.values():
        target = _target_for_candidate(targets, candidate)
        fitted = _fit_probability_ensemble(
            null_regime,
            target,
            train_slice=train_slice,
            cfg=candidate,
        )
        event = (target > fitted["event_threshold"]).astype(float)
        event[target.isna()] = np.nan
        probs = _predict_probability_ensemble(null_regime, fitted)
        metrics.append(_probability_metrics_for_selection(probs[segment], event.iloc[segment]))
    if not metrics:
        return _empty_prob_metrics()
    return max(metrics, key=lambda item: (item["auc"], -item["brier"]))


def _probability_metrics_for_selection(
    probs: np.ndarray,
    event: pd.Series,
) -> dict[str, float]:
    joined = pd.DataFrame({"p": probs, "y": event.to_numpy(dtype=float)}).dropna()
    if joined.empty:
        return _empty_prob_metrics()
    p = np.clip(joined["p"].to_numpy(dtype=float), 0.0, 1.0)
    y = joined["y"].to_numpy(dtype=float)
    low = p <= float(np.quantile(p, 0.20))
    high = p >= float(np.quantile(p, 0.80))
    low_rate = float(np.mean(y[low])) if low.any() else 0.0
    high_rate = float(np.mean(y[high])) if high.any() else 0.0
    return {
        "brier": float(np.mean((p - y) ** 2)),
        "auc": _auc(p, y),
        "event_rate": float(np.mean(y)),
        "mean_probability": float(np.mean(p)),
        "rows": int(len(joined)),
        "top_bottom_event_spread": float(high_rate - low_rate),
    }


def _auc(probs: np.ndarray, event: np.ndarray) -> float:
    y = np.asarray(event, dtype=float)
    p = np.asarray(probs, dtype=float)
    pos = y == 1.0
    neg = y == 0.0
    n_pos = int(np.sum(pos))
    n_neg = int(np.sum(neg))
    if n_pos == 0 or n_neg == 0:
        return 0.5
    ranks = pd.Series(p).rank(method="average").to_numpy(dtype=float)
    pos_rank_sum = float(np.sum(ranks[pos]))
    return float((pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _empty_prob_metrics() -> dict[str, float]:
    return {
        "brier": 1.0,
        "auc": 0.5,
        "event_rate": 0.0,
        "mean_probability": 0.0,
        "rows": 0,
        "top_bottom_event_spread": 0.0,
    }


def _fold_row(fold: dict[str, Any]) -> dict[str, Any]:
    prob = fold.get("probability_selection", {})
    raw = fold.get("raw_selection", {})
    lifts = fold.get("oos_lifts", {})
    return {
        "decision": fold.get("panel_decision", "reject"),
        "raw_model": raw.get("model", ""),
        "probability_model": prob.get("model", ""),
        "probability_policy": prob.get("probability_policy", ""),
        "oos_sharpe": float(prob.get("metrics", {}).get("oos", {}).get("sharpe", 0.0)),
        "oos_total_return": float(
            prob.get("metrics", {}).get("oos", {}).get("total_return", 0.0)
        ),
        "sharpe_vs_baseline": float(lifts.get("sharpe_vs_baseline", 0.0)),
        "sharpe_vs_shuffled": float(lifts.get("sharpe_vs_shuffled", 0.0)),
    }


def _median(values) -> float:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.median(arr)) if len(arr) else 0.0
