"""Probabilistic benchmark ladder for RegimeClassification descriptors.

This ladder preserves the model's continuous/probabilistic nature: it derives
asset/timeframe-specific high-vol event calibration on train data, selects a
probability config on validation, then audits probability quality and smooth
risk scaling on untouched OOS data against time-preserving null controls.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.benchmark_ladder import (
    _build_base_positions,
    _clean_price_frame,
    _metric_lifts,
    _panel_decision,
    _rank_overlays,
    _score_positions,
    build_regime_feature_frame,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.walk_forward import WalkForwardSplitter


_DERIVATIVE_TARGET_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "oi_expansion": ("open_interest",),
    "funding_divergence": ("funding_rate",),
    "oi_vol_composite": ("open_interest",),
}


def run_probability_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calibrate descriptor probabilities and audit probabilistic sizing."""
    cfg = settings or load_regime_optimization_settings()
    ladder_cfg = cfg.get("benchmark_ladder", {})
    prob_cfg = cfg.get("probability_ladder", {})
    frame = _clean_price_frame(price_df)
    min_bars = int(prob_cfg.get("min_bars", 500))
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
            "requested_feature_sets": _configured_feature_sets(prob_cfg),
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
    selected = _select_probability_config(
        regime,
        null_regimes,
        targets,
        segments=segments,
        cfg=prob_cfg,
        candidate_configs=candidate_configs,
    )
    probability_report = _score_probability_config(
        selected,
        regime,
        null_regimes,
        targets,
        segments=segments,
        cfg=prob_cfg,
    )

    base_positions = _build_base_positions(frame, ladder_cfg)
    strategies: dict[str, Any] = {}
    for strategy_name, base in base_positions.items():
        baseline = {
            seg_name: _score_positions(
                base[start:end],
                frame.iloc[start:end],
                timeframe=timeframe,
                cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
            )
            for seg_name, (start, end) in segments.items()
        }
        overlay = _score_probability_sizing(
            selected,
            base,
            frame,
            regime,
            null_regimes,
            segments,
            baseline,
            targets,
            timeframe=timeframe,
            settings=cfg,
        )
        strategies[strategy_name] = {
            "baseline": baseline,
            "overlays": {"probability_sized": overlay},
            "ranking": _rank_overlays({"probability_sized": overlay}),
        }

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "date_from": _index_value(frame, 0),
        "date_to": _index_value(frame, -1),
        "candidate_feature_sets": _unique_feature_sets_from_configs(candidate_configs),
        "target_metadata": {
            **target_metadata,
            "selected_target_kind": selected["config"].get("target_kind"),
            "selected_target_horizon": selected["config"].get("target_horizon"),
        },
        "probability": probability_report,
        "strategies": strategies,
        "panel_decision": probability_report["decision"],
        "sizing_panel_decision": _panel_decision(strategies),
    }


def run_rolling_probability_ladder(
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
    """Run repeated chronological probabilistic calibration folds."""
    cfg = settings or load_regime_optimization_settings()
    rolling_cfg = cfg.get("rolling_probability_ladder", {})
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
        end = start + fold_size
        fold_frame = frame.iloc[start:end]
        fold_report = run_probability_ladder(
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

    summary = _summarize_rolling_folds(folds, cfg)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "fold_bars": fold_size,
        "step_bars": step_size,
        "folds": folds,
        "summary": summary,
        "panel_decision": summary["decision"],
    }


def summarize_probability_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multiple probability-ladder reports."""
    usable = [row for row in rows if row.get("status") == "ok"]
    decisions: dict[str, int] = {}
    promoted = 0
    rejected = 0
    for row in usable:
        decision = row.get("panel_decision", "reject")
        decisions[decision] = decisions.get(decision, 0) + 1
        if decision == "promote_probability_research":
            promoted += 1
        else:
            rejected += 1
    return {
        "usable_slices": len(usable),
        "total_slices": len(rows),
        "decision_counts": decisions,
        "promoted_slices": promoted,
        "rejected_slices": rejected,
    }


def _select_probability_config(
    regime: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    targets: dict[tuple[str, int], pd.Series],
    *,
    segments: dict[str, tuple[int, int]],
    cfg: dict[str, Any],
    candidate_configs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    train = slice(*segments["train"])
    validate = slice(*segments["validate"])
    best: dict[str, Any] | None = None
    for candidate in candidate_configs or _candidate_probability_configs(
        cfg,
        regime.columns,
    ):
        target = _target_for_candidate(targets, candidate)
        fitted = _fit_probability_ensemble(
            regime,
            target,
            train_slice=train,
            cfg=candidate,
        )
        probs = _predict_probability_ensemble(regime, fitted)
        event = _event_series(target, fitted["event_threshold"])
        metrics = _probability_metrics(probs[validate], event.iloc[validate])
        null_metrics = _hardest_null_probability_metrics(
            null_regimes,
            target,
            train_slice=train,
            segment=validate,
            cfg=candidate,
        )
        score = _probability_score(metrics, null_metrics, cfg)
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


def _score_probability_config(
    selected: dict[str, Any],
    regime: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    targets: dict[tuple[str, int], pd.Series],
    *,
    segments: dict[str, tuple[int, int]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    target = _target_for_candidate(targets, selected["config"])
    fitted = selected["fitted_config"]
    event = _event_series(target, fitted["event_threshold"])
    probs = _predict_probability_ensemble(regime, fitted)
    real = {
        name: _probability_metrics(probs[start:end], event.iloc[start:end])
        for name, (start, end) in segments.items()
    }
    nulls: dict[str, dict[str, dict[str, float]]] = {}
    for mode, null_regime in null_regimes.items():
        null_fit = _fit_probability_ensemble(
            null_regime,
            target,
            train_slice=slice(*segments["train"]),
            cfg=selected["config"],
        )
        null_probs = _predict_probability_ensemble(null_regime, null_fit)
        nulls[mode] = {
            name: _probability_metrics(null_probs[start:end], event.iloc[start:end])
            for name, (start, end) in segments.items()
        }
    hardest_mode = _hardest_null_probability_mode(nulls, "oos")
    hardest_oos = nulls.get(hardest_mode, {}).get("oos", _empty_prob_metrics())
    oos = real["oos"]
    lifts = {
        "auc_vs_null": oos["auc"] - hardest_oos["auc"],
        "brier_vs_null": hardest_oos["brier"] - oos["brier"],
        "bucket_spread_vs_null": (
            oos["top_bottom_event_spread"]
            - hardest_oos["top_bottom_event_spread"]
        ),
    }
    return {
        "selection": selected,
        "metrics": real,
        "null_controls": nulls,
        "null_control_mode": hardest_mode,
        "oos_lifts": lifts,
        "decision": _probability_decision(oos, lifts, cfg),
    }


def _score_probability_sizing(
    selected: dict[str, Any],
    base: np.ndarray,
    frame: pd.DataFrame,
    regime: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    segments: dict[str, tuple[int, int]],
    baseline: dict[str, dict[str, float]],
    targets: dict[tuple[str, int], pd.Series],
    *,
    timeframe: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    ladder_cfg = settings.get("benchmark_ladder", {})
    prob_cfg = settings.get("probability_ladder", {})
    fitted = selected["fitted_config"]
    probs = _predict_probability_ensemble(regime, fitted)
    positions = base * _probability_scale(probs, selected["config"])
    metrics = {
        name: _score_positions(
            positions[start:end],
            frame.iloc[start:end],
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        for name, (start, end) in segments.items()
    }
    null_metrics: dict[str, dict[str, dict[str, float]]] = {}
    for mode, null_regime in null_regimes.items():
        null_fit = _fit_probability_ensemble(
            null_regime,
            _target_for_candidate(targets, selected["config"]),
            train_slice=slice(*segments["train"]),
            cfg=selected["config"],
        )
        null_probs = _predict_probability_ensemble(null_regime, null_fit)
        null_positions = base * _probability_scale(null_probs, selected["config"])
        null_metrics[mode] = {
            name: _score_positions(
                null_positions[start:end],
                frame.iloc[start:end],
                timeframe=timeframe,
                cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
            )
            for name, (start, end) in segments.items()
        }
    hardest_mode = _hardest_null_mode(null_metrics, "oos")
    shuffled = null_metrics[hardest_mode]
    lifts = _metric_lifts(metrics["oos"], baseline["oos"], shuffled["oos"])
    return {
        "metrics": metrics,
        "shuffled_control": shuffled,
        "null_controls": null_metrics,
        "null_control_mode": hardest_mode,
        "oos_lifts": lifts,
        "decision": _sizing_decision(metrics["oos"], baseline["oos"], lifts, prob_cfg),
        "selection": selected,
    }


def _fit_probability_ensemble(
    regime: pd.DataFrame,
    target: pd.Series,
    *,
    train_slice: slice,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Fit train-only quantile-bin calibrators for a descriptor feature set."""
    train_target = pd.to_numeric(target.iloc[train_slice], errors="coerce")
    threshold = float(train_target.quantile(float(cfg.get("event_quantile", 0.75))))
    event = _event_series(target, threshold)
    train_event = event.iloc[train_slice]
    base_rate = float(train_event.dropna().mean()) if train_event.notna().any() else 0.5
    feature_columns = [
        str(col)
        for col in cfg.get("feature_columns", [])
        if str(col) in regime.columns
    ]
    feature_models: dict[str, dict[str, Any]] = {}
    raw_weights: dict[str, float] = {}
    for feature in feature_columns:
        fitted = _fit_probability_model(
            regime[feature],
            target,
            train_slice=train_slice,
            cfg={key: value for key, value in cfg.items() if key != "feature_columns"},
        )
        train_probs = _predict_probability(regime[feature], fitted)
        train_metrics = _probability_metrics(
            train_probs[train_slice],
            train_event,
        )
        weight = max(float(train_metrics["auc"]) - 0.5, 0.0)
        feature_models[feature] = {
            "event_threshold": threshold,
            "base_rate": float(fitted.get("base_rate", base_rate)),
            "bin_edges": fitted.get("bin_edges", []),
            "bin_probs": fitted.get("bin_probs", []),
            "train_metrics": train_metrics,
        }
        raw_weights[feature] = weight

    if feature_models and sum(raw_weights.values()) <= 0.0:
        raw_weights = {feature: 1.0 for feature in feature_models}
    weight_sum = float(sum(raw_weights.values()))
    feature_weights = (
        {feature: raw_weights[feature] / weight_sum for feature in feature_models}
        if weight_sum > 0.0
        else {}
    )
    first_model = next(iter(feature_models.values()), {})
    return {
        **cfg,
        "event_threshold": threshold,
        "base_rate": base_rate,
        "feature_columns": list(feature_models),
        "feature_models": feature_models,
        "feature_weights": feature_weights,
        # Keep the previous single-feature contract readable for older callers.
        "bin_edges": first_model.get("bin_edges", []),
        "bin_probs": first_model.get("bin_probs", []),
    }


def _fit_probability_model(
    forecast: pd.Series,
    target: pd.Series,
    *,
    train_slice: slice,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    train_target = pd.to_numeric(target.iloc[train_slice], errors="coerce")
    threshold = float(train_target.quantile(float(cfg.get("event_quantile", 0.75))))
    event = _event_series(target, threshold)
    train_forecast = _clean_series(forecast).iloc[train_slice]
    train_event = event.iloc[train_slice]
    joined = pd.concat([train_forecast, train_event], axis=1).dropna()
    base_rate = float(train_event.dropna().mean()) if train_event.notna().any() else 0.5
    n_bins = int(cfg.get("n_bins", 5))
    smoothing = float(cfg.get("smoothing", 2.0))
    if len(joined) < max(20, n_bins * 5) or joined.iloc[:, 0].nunique() <= 1:
        return {
            **cfg,
            "event_threshold": threshold,
            "base_rate": base_rate,
            "bin_edges": [],
            "bin_probs": [],
        }
    quantiles = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.unique(np.quantile(joined.iloc[:, 0].to_numpy(dtype=float), quantiles))
    if len(edges) < 3:
        return {
            **cfg,
            "event_threshold": threshold,
            "base_rate": base_rate,
            "bin_edges": [],
            "bin_probs": [],
        }
    bin_ids = np.searchsorted(edges[1:-1], joined.iloc[:, 0], side="right")
    probs = []
    for idx in range(len(edges) - 1):
        mask = bin_ids == idx
        positives = float(joined.iloc[:, 1][mask].sum())
        count = float(mask.sum())
        probs.append((positives + smoothing * base_rate) / (count + smoothing))
    return {
        **cfg,
        "event_threshold": threshold,
        "base_rate": base_rate,
        "bin_edges": [float(x) for x in edges],
        "bin_probs": [float(np.clip(x, 0.0, 1.0)) for x in probs],
    }


def _predict_probability(forecast: pd.Series, fitted: dict[str, Any]) -> np.ndarray:
    values = _clean_series(forecast).to_numpy(dtype=float)
    edges = fitted.get("bin_edges", [])
    probs = fitted.get("bin_probs", [])
    if not edges or not probs:
        return np.full(len(values), float(fitted.get("base_rate", 0.5)), dtype=float)
    ids = np.searchsorted(np.asarray(edges[1:-1], dtype=float), values, side="right")
    mapped = np.asarray(probs, dtype=float)[np.clip(ids, 0, len(probs) - 1)]
    return np.clip(mapped, 0.0, 1.0)


def _predict_probability_ensemble(
    regime: pd.DataFrame,
    fitted: dict[str, Any],
) -> np.ndarray:
    feature_models = fitted.get("feature_models", {})
    if not feature_models:
        return np.full(len(regime), float(fitted.get("base_rate", 0.5)), dtype=float)
    feature_probs: list[np.ndarray] = []
    weights: list[float] = []
    fitted_weights = fitted.get("feature_weights", {})
    for feature, feature_model in feature_models.items():
        if feature not in regime:
            continue
        feature_probs.append(_predict_probability(regime[feature], feature_model))
        weights.append(float(fitted_weights.get(feature, 0.0)))
    if not feature_probs:
        return np.full(len(regime), float(fitted.get("base_rate", 0.5)), dtype=float)
    weight_arr = np.asarray(weights, dtype=float)
    if not np.isfinite(weight_arr).all() or float(weight_arr.sum()) <= 0.0:
        weight_arr = np.ones(len(feature_probs), dtype=float)
    stacked = np.vstack(feature_probs)
    return np.clip(np.average(stacked, axis=0, weights=weight_arr), 0.0, 1.0)


def _probability_scale(probs: np.ndarray, cfg: dict[str, Any]) -> np.ndarray:
    risk_budget = float(cfg.get("risk_budget", 0.50))
    min_scale = float(cfg.get("min_position_scale", 0.25))
    return np.clip(1.0 - risk_budget * probs, min_scale, 1.0)


def _probability_metrics(probs: np.ndarray, event: pd.Series) -> dict[str, float]:
    joined = pd.DataFrame({"p": probs, "y": event.to_numpy(dtype=float)}).dropna()
    if joined.empty:
        return _empty_prob_metrics()
    p = np.clip(joined["p"].to_numpy(dtype=float), 0.0, 1.0)
    y = joined["y"].to_numpy(dtype=float)
    bucket = _bucket_event_metrics(p, y)
    return {
        "brier": float(np.mean((p - y) ** 2)),
        "auc": _auc(p, y),
        "event_rate": float(np.mean(y)),
        "mean_probability": float(np.mean(p)),
        "rows": int(len(joined)),
        **bucket,
    }


def _probability_score(
    metrics: dict[str, float],
    null_metrics: dict[str, float],
    cfg: dict[str, Any],
) -> float:
    return (
        metrics["auc"]
        + float(cfg.get("brier_weight", 2.0)) * (1.0 - metrics["brier"])
        + float(cfg.get("null_lift_weight", 1.0))
        * (metrics["auc"] - null_metrics["auc"])
        + float(cfg.get("null_brier_weight", 1.0))
        * (null_metrics["brier"] - metrics["brier"])
        + float(cfg.get("bucket_spread_weight", 0.5))
        * metrics["top_bottom_event_spread"]
        + float(cfg.get("null_bucket_spread_weight", 0.5))
        * (
            metrics["top_bottom_event_spread"]
            - null_metrics["top_bottom_event_spread"]
        )
    )


def _hardest_null_probability_metrics(
    null_regimes: dict[str, pd.DataFrame],
    target: pd.Series,
    *,
    train_slice: slice,
    segment: slice,
    cfg: dict[str, Any],
) -> dict[str, float]:
    metrics = []
    for null_regime in null_regimes.values():
        fitted = _fit_probability_ensemble(
            null_regime,
            target,
            train_slice=train_slice,
            cfg=cfg,
        )
        event = _event_series(target, fitted["event_threshold"])
        probs = _predict_probability_ensemble(null_regime, fitted)
        metrics.append(_probability_metrics(probs[segment], event.iloc[segment]))
    if not metrics:
        return _empty_prob_metrics()
    return max(metrics, key=lambda item: (item["auc"], -item["brier"]))


def _probability_decision(
    metrics: dict[str, float],
    lifts: dict[str, float],
    cfg: dict[str, Any],
) -> str:
    if (
        metrics["auc"] >= float(cfg.get("min_oos_auc", 0.55))
        and lifts["auc_vs_null"] >= float(cfg.get("min_auc_lift_vs_null", 0.0))
        and lifts["brier_vs_null"] >= float(cfg.get("min_brier_lift_vs_null", 0.0))
        and lifts["bucket_spread_vs_null"]
        >= float(cfg.get("min_bucket_spread_lift_vs_null", 0.0))
    ):
        return "promote_probability_research"
    return "reject"


def _sizing_decision(
    metrics: dict[str, float],
    baseline: dict[str, float],
    lifts: dict[str, float],
    cfg: dict[str, Any],
) -> str:
    dd_improvement = abs(baseline["max_drawdown"]) - abs(metrics["max_drawdown"])
    if (
        lifts["sharpe_vs_baseline"] >= float(cfg.get("min_sharpe_lift", 0.05))
        and lifts["sharpe_vs_shuffled"] >= float(cfg.get("min_null_sharpe_lift", 0.0))
        and dd_improvement >= float(cfg.get("min_drawdown_improvement", 0.0))
        and metrics["avg_position"] >= float(cfg.get("min_avg_position", 0.05))
    ):
        return "promote_to_downstream_research"
    return "reject"


def _candidate_probability_configs(
    cfg: dict[str, Any],
    available_columns: pd.Index | list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    available = {str(col) for col in available_columns} if available_columns is not None else None
    for target_kind in _configured_target_kinds(cfg):
        for target_horizon in _configured_target_horizons(cfg):
            for event_quantile in cfg.get("event_quantiles", [0.70, 0.75, 0.80]):
                for n_bins in cfg.get("n_bins_grid", [4, 5, 8]):
                    for risk_budget in cfg.get("risk_budgets", [0.25, 0.50, 0.75]):
                        for min_scale in cfg.get("min_position_scales", [0.25, 0.50]):
                            for feature_set in _configured_feature_sets(cfg):
                                feature_columns = [
                                    feature
                                    for feature in feature_set
                                    if available is None or feature in available
                                ]
                                if not feature_columns:
                                    continue
                                rows.append(
                                    {
                                        "target_kind": target_kind,
                                        "target_horizon": int(target_horizon),
                                        "event_quantile": float(event_quantile),
                                        "n_bins": int(n_bins),
                                        "risk_budget": float(risk_budget),
                                        "min_position_scale": float(min_scale),
                                        "smoothing": float(cfg.get("smoothing", 2.0)),
                                        "feature_columns": feature_columns,
                                    }
                                )
    return rows


def _configured_target_kinds(cfg: dict[str, Any]) -> list[str]:
    raw = cfg.get("target_kinds")
    if raw is None:
        raw = [cfg.get("target_kind", "fwd_vol")]
    if isinstance(raw, str):
        raw = [raw]
    _valid_kinds = {
        "fwd_vol", "vol_expansion", "oi_expansion",
        "funding_divergence", "oi_vol_composite",
    }
    kinds: list[str] = []
    for value in raw:
        kind = str(value)
        if kind in _valid_kinds and kind not in kinds:
            kinds.append(kind)
    return kinds or ["fwd_vol"]


def _configured_target_horizons(cfg: dict[str, Any]) -> list[int]:
    raw = cfg.get("target_horizons")
    if raw is None:
        raw = [cfg.get("target_horizon", 5)]
    if isinstance(raw, (int, float, str)):
        raw = [raw]
    horizons: list[int] = []
    for value in raw:
        horizon = max(int(value), 1)
        if horizon not in horizons:
            horizons.append(horizon)
    return horizons


def _configured_feature_sets(cfg: dict[str, Any]) -> list[list[str]]:
    raw_sets = cfg.get("feature_sets")
    if raw_sets is None:
        raw_sets = cfg.get("feature_columns")
    if raw_sets is None:
        raw_sets = [[str(cfg.get("forecast_column", "fwd_vol_ewma"))]]
    if isinstance(raw_sets, str):
        raw_sets = [[raw_sets]]

    feature_sets: list[list[str]] = []
    for raw in raw_sets:
        if isinstance(raw, str):
            columns = [raw]
        elif isinstance(raw, (list, tuple)):
            columns = [str(col) for col in raw if str(col)]
        else:
            continue
        columns = list(dict.fromkeys(columns))
        if columns and columns not in feature_sets:
            feature_sets.append(columns)
    return feature_sets


def _target_requirements(kind: str) -> tuple[str, ...]:
    return _DERIVATIVE_TARGET_REQUIREMENTS.get(str(kind), ())


def _filter_candidate_configs_for_available_targets(
    frame: pd.DataFrame,
    candidate_configs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop unavailable derivative targets and report exactly what can run."""
    available_columns = {str(col) for col in frame.columns}
    requested_kinds = list(
        dict.fromkeys(str(cfg.get("target_kind", "fwd_vol")) for cfg in candidate_configs)
    )
    missing_by_kind: dict[str, list[str]] = {}
    available_kinds: list[str] = []
    filtered: list[dict[str, Any]] = []
    derivative_columns_present = any(
        column in available_columns
        for required in _DERIVATIVE_TARGET_REQUIREMENTS.values()
        for column in required
    )

    for target_kind in requested_kinds:
        required = _target_requirements(target_kind)
        missing = [column for column in required if column not in available_columns]
        if missing:
            missing_by_kind[target_kind] = missing
        else:
            available_kinds.append(target_kind)

    for cfg in candidate_configs:
        target_kind = str(cfg.get("target_kind", "fwd_vol"))
        if target_kind in missing_by_kind:
            continue
        filtered.append(cfg)

    return filtered, {
        "available_columns": sorted(available_columns),
        "requested_target_kinds": requested_kinds,
        "available_target_kinds": available_kinds,
        "missing_target_requirements": missing_by_kind,
        "derivative_columns_present": derivative_columns_present,
    }


def _unique_feature_sets_from_configs(configs: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for cfg in configs:
        columns = [str(col) for col in cfg.get("feature_columns", [])]
        if columns and columns not in rows:
            rows.append(columns)
    return rows


def _summarize_rolling_folds(
    folds: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    rolling_cfg = cfg.get("rolling_probability_ladder", {})
    usable = [fold for fold in folds if fold.get("status") == "ok"]
    prob_rows = [fold["probability"] for fold in usable]
    best_rows = [_best_row(fold) for fold in usable]
    best_rows = [row for row in best_rows if row]
    prob_promoted = [
        row for row in prob_rows if row.get("decision") == "promote_probability_research"
    ]
    sizing_promoted = [
        row for row in best_rows if row["decision"] == "promote_to_downstream_research"
    ]
    prob_pass_rate = len(prob_promoted) / len(prob_rows) if prob_rows else 0.0
    sizing_pass_rate = len(sizing_promoted) / len(best_rows) if best_rows else 0.0
    median_auc = _median(row["metrics"]["oos"]["auc"] for row in prob_rows)
    median_auc_lift = _median(row["oos_lifts"]["auc_vs_null"] for row in prob_rows)
    median_brier_lift = _median(row["oos_lifts"]["brier_vs_null"] for row in prob_rows)
    median_bucket_spread = _median(
        row["metrics"]["oos"]["top_bottom_event_spread"] for row in prob_rows
    )
    median_bucket_lift = _median(
        row["oos_lifts"]["bucket_spread_vs_null"] for row in prob_rows
    )
    median_sharpe_lift = _median(row["sharpe_vs_baseline"] for row in best_rows)
    median_null_lift = _median(row["sharpe_vs_shuffled"] for row in best_rows)
    decision = (
        "promote_probability_research"
        if len(prob_promoted) >= int(rolling_cfg.get("min_promoted_folds", 2))
        and prob_pass_rate >= float(rolling_cfg.get("min_probability_pass_rate", 0.60))
        and median_auc >= float(rolling_cfg.get("min_median_auc", 0.55))
        and median_auc_lift >= float(rolling_cfg.get("min_median_auc_lift", 0.0))
        and median_brier_lift >= float(rolling_cfg.get("min_median_brier_lift", 0.0))
        and median_bucket_lift
        >= float(rolling_cfg.get("min_median_bucket_spread_lift", 0.0))
        else "reject"
    )
    return {
        "total_folds": len(folds),
        "usable_folds": len(usable),
        "probability_promoted_folds": len(prob_promoted),
        "probability_rejected_folds": len(prob_rows) - len(prob_promoted),
        "probability_pass_rate": float(prob_pass_rate),
        "sizing_promoted_folds": len(sizing_promoted),
        "sizing_rejected_folds": len(best_rows) - len(sizing_promoted),
        "sizing_pass_rate": float(sizing_pass_rate),
        "median_oos_auc": float(median_auc),
        "median_auc_lift_vs_null": float(median_auc_lift),
        "median_brier_lift_vs_null": float(median_brier_lift),
        "median_bucket_spread": float(median_bucket_spread),
        "median_bucket_spread_lift_vs_null": float(median_bucket_lift),
        "median_sharpe_lift": float(median_sharpe_lift),
        "median_null_sharpe_lift": float(median_null_lift),
        "best_rows": best_rows,
        "decision": decision,
    }


def _best_row(fold: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for strategy_name, strategy in fold.get("strategies", {}).items():
        overlay = strategy.get("overlays", {}).get("probability_sized", {})
        metrics = overlay.get("metrics", {}).get("oos", {})
        lifts = overlay.get("oos_lifts", {})
        rows.append(
            {
                "strategy": strategy_name,
                "decision": overlay.get("decision", "reject"),
                "oos_sharpe": float(metrics.get("sharpe", 0.0)),
                "oos_total_return": float(metrics.get("total_return", 0.0)),
                "sharpe_vs_baseline": float(lifts.get("sharpe_vs_baseline", 0.0)),
                "sharpe_vs_shuffled": float(lifts.get("sharpe_vs_shuffled", 0.0)),
            }
        )
    if not rows:
        return {}
    return sorted(
        rows,
        key=lambda row: (
            row["decision"] == "promote_to_downstream_research",
            row["sharpe_vs_baseline"],
            row["sharpe_vs_shuffled"],
        ),
        reverse=True,
    )[0]


def _combine_fold_target_metadata(folds: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = [fold.get("target_metadata") for fold in folds if fold.get("target_metadata")]
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


def _forward_vol_target(frame: pd.DataFrame, horizon: int) -> pd.Series:
    returns = frame["close"].astype(float).pct_change()
    return returns.rolling(horizon).std().shift(-horizon)


def _target_cache(
    frame: pd.DataFrame,
    candidate_configs: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[tuple[str, int], pd.Series]:
    targets: dict[tuple[str, int], pd.Series] = {}
    for candidate in candidate_configs:
        kind = str(candidate.get("target_kind", "fwd_vol"))
        horizon = max(int(candidate.get("target_horizon", 5)), 1)
        key = (kind, horizon)
        if key not in targets:
            targets[key] = _target_series(frame, kind, horizon, cfg)
    return targets


def _target_for_candidate(
    targets: dict[tuple[str, int], pd.Series],
    candidate: dict[str, Any],
) -> pd.Series:
    kind = str(candidate.get("target_kind", "fwd_vol"))
    horizon = max(int(candidate.get("target_horizon", 5)), 1)
    key = (kind, horizon)
    if key in targets:
        return targets[key]
    return next(iter(targets.values()))


def _target_series(
    frame: pd.DataFrame,
    kind: str,
    horizon: int,
    cfg: dict[str, Any],
) -> pd.Series:
    fwd_vol = _forward_vol_target(frame, horizon)
    if kind == "vol_expansion":
        lookback = max(int(cfg.get("target_vol_lookback", 20)), horizon)
        returns = frame["close"].astype(float).pct_change()
        current_vol = returns.rolling(lookback).std()
        return (fwd_vol / current_vol.replace(0.0, np.nan)).replace(
            [np.inf, -np.inf],
            np.nan,
        )
    if kind == "oi_expansion":
        _require_target_columns(frame, kind)
        oi = frame["open_interest"].astype(float)
        return oi.pct_change(horizon).shift(-horizon).replace([np.inf, -np.inf], np.nan)
    if kind == "funding_divergence":
        _require_target_columns(frame, kind)
        fr = frame["funding_rate"].astype(float)
        return fr.rolling(horizon).std().shift(-horizon)
    if kind == "oi_vol_composite":
        _require_target_columns(frame, kind)
        lookback = max(int(cfg.get("target_vol_lookback", 20)), horizon)
        returns = frame["close"].astype(float).pct_change()
        current_vol = returns.rolling(lookback).std()
        vol_ratio = (fwd_vol / current_vol.replace(0.0, np.nan)).replace(
            [np.inf, -np.inf], np.nan
        )
        oi_change = frame["open_interest"].astype(float).pct_change(horizon).shift(-horizon)
        vol_mean = vol_ratio.rolling(lookback, min_periods=lookback).mean()
        vol_std = vol_ratio.rolling(lookback, min_periods=lookback).std()
        oi_mean = oi_change.rolling(lookback, min_periods=lookback).mean()
        oi_std = oi_change.rolling(lookback, min_periods=lookback).std()
        vol_z = (vol_ratio - vol_mean) / vol_std.replace(0.0, np.nan)
        oi_z = (oi_change - oi_mean) / oi_std.replace(0.0, np.nan)
        return (vol_z + oi_z).replace([np.inf, -np.inf], np.nan)
    return fwd_vol


def _require_target_columns(frame: pd.DataFrame, kind: str) -> None:
    missing = [column for column in _target_requirements(kind) if column not in frame.columns]
    if missing:
        raise ValueError(
            f"target_kind={kind!r} requires missing derivative columns: {missing}"
        )


def _event_series(target: pd.Series, threshold: float) -> pd.Series:
    event = (pd.to_numeric(target, errors="coerce") > threshold).astype(float)
    event[target.isna()] = np.nan
    return event


def _clean_series(values: pd.Series) -> pd.Series:
    return (
        pd.to_numeric(values, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .ffill()
        .bfill()
        .fillna(0.0)
    )


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


def _bucket_event_metrics(probs: np.ndarray, event: np.ndarray) -> dict[str, float]:
    if len(probs) < 10:
        return _empty_bucket_metrics()
    low_cut = float(np.quantile(probs, 0.20))
    high_cut = float(np.quantile(probs, 0.80))
    low = probs <= low_cut
    high = probs >= high_cut
    if not low.any() or not high.any():
        return _empty_bucket_metrics()
    low_rate = float(np.mean(event[low]))
    high_rate = float(np.mean(event[high]))
    return {
        "bottom_bucket_event_rate": low_rate,
        "top_bucket_event_rate": high_rate,
        "top_bottom_event_spread": float(high_rate - low_rate),
        "bottom_bucket_rows": int(np.sum(low)),
        "top_bucket_rows": int(np.sum(high)),
    }


def _empty_bucket_metrics() -> dict[str, float]:
    return {
        "bottom_bucket_event_rate": 0.0,
        "top_bucket_event_rate": 0.0,
        "top_bottom_event_spread": 0.0,
        "bottom_bucket_rows": 0,
        "top_bucket_rows": 0,
    }


def _empty_prob_metrics() -> dict[str, float]:
    return {
        "brier": 1.0,
        "auc": 0.5,
        "event_rate": 0.0,
        "mean_probability": 0.0,
        "rows": 0,
        **_empty_bucket_metrics(),
    }


def _build_null_regimes(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    modes = cfg.get("null_controls", ["circular_shift", "block_shuffle"])
    if isinstance(modes, str):
        modes = [modes]
    nulls = {
        mode: _null_regime(regime_df, cfg, mode)
        for mode in modes
        if mode in {"row_shuffle", "circular_shift", "block_shuffle"}
    }
    if not nulls:
        nulls["circular_shift"] = _null_regime(regime_df, cfg, "circular_shift")
    return nulls


def _null_regime(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
    mode: str,
) -> pd.DataFrame:
    if mode == "row_shuffle":
        return _row_shuffle_regime(regime_df, cfg)
    if mode == "block_shuffle":
        return _block_shuffle_regime(regime_df, cfg)
    return _circular_shift_regime(regime_df, cfg)


def _row_shuffle_regime(regime_df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    shuffled = regime_df.sample(
        frac=1.0,
        random_state=int(cfg.get("shuffle_seed", 42)),
    ).reset_index(drop=True)
    shuffled.index = regime_df.index
    return shuffled


def _circular_shift_regime(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    if len(regime_df) == 0:
        return regime_df.copy()
    shift = int(cfg.get("null_shift_bars", max(1, len(regime_df) // 3)))
    shift = shift % len(regime_df)
    if shift == 0:
        shift = max(1, len(regime_df) // 3)
    values = np.roll(regime_df.to_numpy(), shift=shift, axis=0)
    return pd.DataFrame(values, index=regime_df.index, columns=regime_df.columns)


def _block_shuffle_regime(
    regime_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    block_bars = max(int(cfg.get("null_block_bars", 96)), 1)
    rng = np.random.default_rng(int(cfg.get("shuffle_seed", 42)))
    blocks = [
        regime_df.iloc[start : start + block_bars]
        for start in range(0, len(regime_df), block_bars)
    ]
    if len(blocks) <= 1:
        return _circular_shift_regime(regime_df, cfg)
    order = rng.permutation(len(blocks))
    shuffled = pd.concat([blocks[idx] for idx in order], axis=0).reset_index(drop=True)
    shuffled.index = regime_df.index
    return shuffled


def _hardest_null_probability_mode(
    nulls: dict[str, dict[str, dict[str, float]]],
    segment: str,
) -> str:
    if not nulls:
        return ""
    return max(nulls, key=lambda mode: nulls[mode].get(segment, {}).get("auc", 0.5))


def _hardest_null_mode(
    null_metrics: dict[str, dict[str, dict[str, float]]],
    segment: str,
) -> str:
    if not null_metrics:
        return ""
    return max(
        null_metrics,
        key=lambda mode: float(null_metrics[mode].get(segment, {}).get("sharpe", 0.0)),
    )


def _median(values) -> float:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.median(arr)) if len(arr) else 0.0


def _index_value(frame: pd.DataFrame, idx: int) -> str:
    value = frame.index[idx]
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
