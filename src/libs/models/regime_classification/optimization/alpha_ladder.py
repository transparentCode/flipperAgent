"""Optuna-backed alpha ladder for RegimeClassification descriptors.

This is the second offline gate after descriptor-quality optimization. It asks
whether a train/validation-selected regime overlay improves simple baselines on
untouched OOS data after costs and against shuffled-regime controls.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import optuna
import pandas as pd

from libs.models.regime_classification.optimization.benchmark_ladder import (
    _build_base_positions,
    _clean_price_frame,
    _metric_lifts,
    _panel_decision,
    _posterior_confidence,
    _rank_overlays,
    _score_positions,
    _series,
    build_regime_feature_frame,
    compute_information_metrics,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.walk_forward import WalkForwardSplitter


_POLICY_KINDS = (
    "risk_filtered",
    "trend_scaled",
    "confidence_scaled",
    "combined",
    "soft_scaled",
)


def run_alpha_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Optimize regime-overlay policy on validation, then audit on OOS."""
    cfg = settings or load_regime_optimization_settings()
    ladder_cfg = cfg.get("benchmark_ladder", {})
    alpha_cfg = cfg.get("alpha_ladder", {})
    frame = _clean_price_frame(price_df)
    min_bars = int(alpha_cfg.get("min_bars", ladder_cfg.get("min_bars", 500)))
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

    split = WalkForwardSplitter(
        train_ratio=float(ladder_cfg.get("train_ratio", 0.60)),
        val_ratio=float(ladder_cfg.get("val_ratio", 0.20)),
        oos_ratio=1.0
        - float(ladder_cfg.get("train_ratio", 0.60))
        - float(ladder_cfg.get("val_ratio", 0.20)),
        purge_bars=int(ladder_cfg.get("purge_bars", 24)),
    ).split(len(frame))
    segments = {
        "train": (split.train_start, split.train_end),
        "validate": (split.val_start, split.val_end),
        "oos": (split.oos_start, split.oos_end),
        "full": (0, len(frame)),
    }

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
        best_policy = optimize_overlay_policy(
            base,
            frame,
            regime,
            strategy_name=strategy_name,
            timeframe=timeframe,
            baseline=baseline,
            settings=cfg,
        )
        overlay_rows = _score_selected_policy(
            best_policy,
            base,
            frame,
            regime,
            segments,
            baseline,
            timeframe=timeframe,
            settings=cfg,
        )
        strategies[strategy_name] = {
            "baseline": baseline,
            "overlays": overlay_rows,
            "ranking": _rank_overlays(overlay_rows),
        }

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "date_from": _index_value(frame, 0),
        "date_to": _index_value(frame, -1),
        "information_metrics": compute_information_metrics(regime, frame),
        "strategies": strategies,
        "panel_decision": _panel_decision(strategies),
    }


def optimize_overlay_policy(
    base_positions: np.ndarray,
    frame: pd.DataFrame,
    regime_df: pd.DataFrame,
    *,
    strategy_name: str,
    timeframe: str,
    baseline: dict[str, dict[str, float]],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Find the best validation overlay policy for one baseline strategy."""
    cfg = settings or load_regime_optimization_settings()
    alpha_cfg = cfg.get("alpha_ladder", {})
    ladder_cfg = cfg.get("benchmark_ladder", {})
    split = WalkForwardSplitter(
        train_ratio=float(ladder_cfg.get("train_ratio", 0.60)),
        val_ratio=float(ladder_cfg.get("val_ratio", 0.20)),
        oos_ratio=1.0
        - float(ladder_cfg.get("train_ratio", 0.60))
        - float(ladder_cfg.get("val_ratio", 0.20)),
        purge_bars=int(ladder_cfg.get("purge_bars", 24)),
    ).split(len(frame))
    val_slice = slice(split.val_start, split.val_end)
    shuffled = _shuffle_regime(regime_df, alpha_cfg)

    def objective(trial: optuna.Trial) -> float:
        policy = _suggest_policy(trial, alpha_cfg)
        positions = _apply_policy(base_positions, regime_df, policy)
        shuffled_positions = _apply_policy(base_positions, shuffled, policy)
        metrics = _score_positions(
            positions[val_slice],
            frame.iloc[val_slice],
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        shuffled_metrics = _score_positions(
            shuffled_positions[val_slice],
            frame.iloc[val_slice],
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        lifts = _metric_lifts(metrics, baseline["validate"], shuffled_metrics)
        turnover_penalty = float(alpha_cfg.get("turnover_penalty", 0.05))
        dd_penalty = _drawdown_penalty(metrics, baseline["validate"])
        return (
            lifts["sharpe_vs_baseline"]
            + 0.25 * lifts["calmar_vs_baseline"]
            + 2.0 * lifts["total_return_vs_baseline"]
            + 0.50 * lifts["sharpe_vs_shuffled"]
            - turnover_penalty * max(0.0, metrics["turnover"] - baseline["validate"]["turnover"])
            - dd_penalty
        )

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        study_name=f"RegimeAlpha_{strategy_name}",
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=int(alpha_cfg.get("seed", 42))),
    )
    study.optimize(objective, n_trials=int(alpha_cfg.get("n_trials", 80)))
    best_policy = _coerce_policy(study.best_params, alpha_cfg)
    return {
        "policy": best_policy,
        "validation_score": float(study.best_value),
        "n_trials": len(study.trials),
    }


def _score_selected_policy(
    selected: dict[str, Any],
    base: np.ndarray,
    frame: pd.DataFrame,
    regime_df: pd.DataFrame,
    segments: dict[str, tuple[int, int]],
    baseline: dict[str, dict[str, float]],
    *,
    timeframe: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    ladder_cfg = settings.get("benchmark_ladder", {})
    alpha_cfg = settings.get("alpha_ladder", {})
    policy = selected["policy"]
    positions = _apply_policy(base, regime_df, policy)
    shuffled_positions = _apply_policy(base, _shuffle_regime(regime_df, alpha_cfg), policy)

    metrics = {
        seg_name: _score_positions(
            positions[start:end],
            frame.iloc[start:end],
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        for seg_name, (start, end) in segments.items()
    }
    shuffled_metrics = {
        seg_name: _score_positions(
            shuffled_positions[start:end],
            frame.iloc[start:end],
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        for seg_name, (start, end) in segments.items()
    }
    return {
        "optimized_policy": {
            "metrics": metrics,
            "shuffled_control": shuffled_metrics,
            "oos_lifts": _metric_lifts(metrics["oos"], baseline["oos"], shuffled_metrics["oos"]),
            "decision": _overlay_decision(
                metrics["oos"],
                baseline["oos"],
                shuffled_metrics["oos"],
                ladder_cfg,
            ),
            "selection": selected,
        }
    }


def _suggest_policy(trial: optuna.Trial, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_kind": trial.suggest_categorical("policy_kind", list(_POLICY_KINDS)),
        "max_vol_percentile": trial.suggest_float(
            "max_vol_percentile",
            float(cfg.get("max_vol_percentile_low", 55.0)),
            float(cfg.get("max_vol_percentile_high", 100.0)),
        ),
        "max_changepoint_prob": trial.suggest_float(
            "max_changepoint_prob",
            float(cfg.get("max_changepoint_prob_low", 0.05)),
            float(cfg.get("max_changepoint_prob_high", 0.95)),
        ),
        "max_crisis_prob": trial.suggest_float(
            "max_crisis_prob",
            float(cfg.get("max_crisis_prob_low", 0.0)),
            float(cfg.get("max_crisis_prob_high", 0.95)),
        ),
        "min_trend_strength": trial.suggest_float(
            "min_trend_strength",
            float(cfg.get("min_trend_strength_low", 0.0)),
            float(cfg.get("min_trend_strength_high", 0.80)),
        ),
        "min_confidence": trial.suggest_float(
            "min_confidence",
            float(cfg.get("min_confidence_low", 0.0)),
            float(cfg.get("min_confidence_high", 0.95)),
        ),
        "trend_power": trial.suggest_float(
            "trend_power",
            float(cfg.get("trend_power_low", 0.50)),
            float(cfg.get("trend_power_high", 3.0)),
        ),
        "min_position_scale": trial.suggest_float(
            "min_position_scale",
            float(cfg.get("min_position_scale_low", 0.0)),
            float(cfg.get("min_position_scale_high", 0.50)),
        ),
    }


def _coerce_policy(params: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    policy = dict(params)
    policy.setdefault("policy_kind", "risk_filtered")
    for key, default in {
        "max_vol_percentile": 85.0,
        "max_changepoint_prob": 0.65,
        "max_crisis_prob": 0.50,
        "min_trend_strength": 0.35,
        "min_confidence": 0.0,
        "trend_power": 1.0,
        "min_position_scale": 0.0,
    }.items():
        policy[key] = float(policy.get(key, cfg.get(key, default)))
    return policy


def _apply_policy(
    base_positions: np.ndarray,
    regime_df: pd.DataFrame,
    policy: dict[str, Any],
) -> np.ndarray:
    trend = _series(regime_df, "trend_strength", 0.0).clip(0.0, 1.0)
    confidence = _posterior_confidence(regime_df).clip(0.0, 1.0)
    vol_ok = _series(regime_df, "vol_percentile", 50.0) <= policy["max_vol_percentile"]
    cp_ok = _series(regime_df, "changepoint_prob", 0.0) <= policy["max_changepoint_prob"]
    crisis_ok = _series(regime_df, "hmm_crisis_prob", 0.0) <= policy["max_crisis_prob"]
    conf_ok = confidence >= policy["min_confidence"]
    risk_gate = (vol_ok & cp_ok & crisis_ok & conf_ok).astype(float)
    trend_gate = (trend >= policy["min_trend_strength"]).astype(float)

    trend_scale = np.power(trend.to_numpy(), policy["trend_power"])
    min_scale = policy["min_position_scale"]
    conf_scale = confidence.to_numpy()
    risk = risk_gate.to_numpy()
    kind = policy["policy_kind"]

    if kind == "risk_filtered":
        scale = risk
    elif kind == "trend_scaled":
        scale = risk * (min_scale + (1.0 - min_scale) * trend_scale)
    elif kind == "confidence_scaled":
        scale = risk * (min_scale + (1.0 - min_scale) * conf_scale)
    elif kind == "combined":
        scale = risk * trend_gate.to_numpy() * conf_scale * trend_scale
    else:
        soft = 0.5 * (conf_scale + trend_scale)
        scale = risk * (min_scale + (1.0 - min_scale) * soft)
    return np.nan_to_num(base_positions.astype(float) * scale, nan=0.0)


def _overlay_decision(
    overlay: dict[str, float],
    baseline: dict[str, float],
    shuffled: dict[str, float],
    cfg: dict[str, Any],
) -> str:
    lifts = _metric_lifts(overlay, baseline, shuffled)
    if (
        lifts["sharpe_vs_baseline"] >= float(cfg.get("min_sharpe_lift", 0.10))
        and lifts["calmar_vs_baseline"] >= float(cfg.get("min_calmar_lift", 0.05))
        and lifts["total_return_vs_baseline"]
        >= float(cfg.get("min_total_return_lift", 0.0))
        and lifts["sharpe_vs_shuffled"] >= 0
        and overlay["sharpe"] >= float(cfg.get("min_oos_sharpe", 0.0))
        and overlay["total_return"] >= float(cfg.get("min_oos_total_return", 0.0))
        and overlay["avg_position"] >= float(cfg.get("min_avg_position", 0.05))
    ):
        return "promote_to_downstream_research"
    return "reject"


def _drawdown_penalty(
    metrics: dict[str, float],
    baseline: dict[str, float],
) -> float:
    if metrics["max_drawdown"] < baseline["max_drawdown"]:
        return abs(metrics["max_drawdown"] - baseline["max_drawdown"])
    return 0.0


def _shuffle_regime(regime_df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    shuffled = regime_df.sample(frac=1.0, random_state=int(cfg.get("shuffle_seed", 42)))
    shuffled = shuffled.reset_index(drop=True)
    shuffled.index = regime_df.index
    return shuffled


def _index_value(frame: pd.DataFrame, idx: int) -> str:
    value = frame.index[idx]
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
