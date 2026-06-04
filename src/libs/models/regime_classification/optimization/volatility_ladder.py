"""Volatility-aware downstream ladder for RegimeClassification descriptors.

This controlled post-descriptor test asks whether the promoted forward-vol
descriptor can improve simple strategy risk-adjusted outcomes without turning
the regime model into a directional signal.
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
    summarize_ladder_panel,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.walk_forward import WalkForwardSplitter


def run_volatility_ladder(
    price_df: pd.DataFrame,
    *,
    asset: str = "",
    timeframe: str = "1h",
    params: dict[str, Any] | None = None,
    frozen_overrides: dict[str, Any] | None = None,
    regime_df: pd.DataFrame | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select volatility-sizing policy on validation and audit on OOS."""
    cfg = settings or load_regime_optimization_settings()
    ladder_cfg = cfg.get("benchmark_ladder", {})
    vol_cfg = cfg.get("volatility_ladder", {})
    frame = _clean_price_frame(price_df)
    min_bars = int(vol_cfg.get("min_bars", 500))
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

    forecast_column = str(vol_cfg.get("forecast_column", "fwd_vol_ewma"))
    if forecast_column not in regime:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "status": "missing_forecast_column",
            "forecast_column": forecast_column,
        }

    split = WalkForwardSplitter(
        train_ratio=float(vol_cfg.get("train_ratio", ladder_cfg.get("train_ratio", 0.60))),
        val_ratio=float(vol_cfg.get("val_ratio", ladder_cfg.get("val_ratio", 0.20))),
        oos_ratio=1.0
        - float(vol_cfg.get("train_ratio", ladder_cfg.get("train_ratio", 0.60)))
        - float(vol_cfg.get("val_ratio", ladder_cfg.get("val_ratio", 0.20))),
        purge_bars=int(vol_cfg.get("purge_bars", ladder_cfg.get("purge_bars", 24))),
    ).split(len(frame))
    segments = {
        "train": (split.train_start, split.train_end),
        "validate": (split.val_start, split.val_end),
        "oos": (split.oos_start, split.oos_end),
        "full": (0, len(frame)),
    }

    base_positions = _build_base_positions(frame, ladder_cfg)
    null_regimes = _build_null_regimes(regime, vol_cfg)
    policies = _candidate_policies(vol_cfg)
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
        selected = _select_policy(
            policies,
            base,
            frame,
            regime,
            null_regimes,
            segments,
            baseline,
            forecast_column=forecast_column,
            timeframe=timeframe,
            settings=cfg,
        )
        overlay = _score_selected_policy(
            selected,
            base,
            frame,
            regime,
            null_regimes,
            segments,
            baseline,
            forecast_column=forecast_column,
            timeframe=timeframe,
            settings=cfg,
        )
        strategies[strategy_name] = {
            "baseline": baseline,
            "overlays": {"volatility_sized": overlay},
            "ranking": _rank_overlays({"volatility_sized": overlay}),
        }

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "ok",
        "bars": int(len(frame)),
        "date_from": _index_value(frame, 0),
        "date_to": _index_value(frame, -1),
        "forecast_column": forecast_column,
        "strategies": strategies,
        "panel_decision": _panel_decision(strategies),
    }


def run_rolling_volatility_ladder(
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
    """Run repeated chronological volatility-ladder folds."""
    cfg = settings or load_regime_optimization_settings()
    rolling_cfg = cfg.get("rolling_volatility_ladder", {})
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
        fold_report = run_volatility_ladder(
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


def summarize_volatility_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multiple volatility-ladder reports."""
    return summarize_ladder_panel(rows)


def _select_policy(
    policies: list[dict[str, Any]],
    base: np.ndarray,
    frame: pd.DataFrame,
    regime: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    segments: dict[str, tuple[int, int]],
    baseline: dict[str, dict[str, float]],
    *,
    forecast_column: str,
    timeframe: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    vol_cfg = settings.get("volatility_ladder", {})
    ladder_cfg = settings.get("benchmark_ladder", {})
    val_start, val_end = segments["validate"]
    train_start, train_end = segments["train"]
    best: dict[str, Any] | None = None
    for policy in policies:
        scale = _policy_scale(
            regime[forecast_column],
            train_slice=slice(train_start, train_end),
            policy=policy,
        )
        positions = base * scale
        metrics = _score_positions(
            positions[val_start:val_end],
            frame.iloc[val_start:val_end],
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        null_metrics = _score_hardest_null(
            base,
            null_regimes,
            policy,
            slice(train_start, train_end),
            slice(val_start, val_end),
            frame.iloc[val_start:val_end],
            forecast_column=forecast_column,
            timeframe=timeframe,
            settings=settings,
        )
        lifts = _metric_lifts(metrics, baseline["validate"], null_metrics)
        score = _validation_score(metrics, baseline["validate"], lifts, vol_cfg)
        candidate = {
            "policy": policy,
            "validation_score": score,
            "validation_metrics": metrics,
            "validation_lifts": lifts,
        }
        if best is None or score > float(best["validation_score"]):
            best = candidate
    return best or {
        "policy": policies[0],
        "validation_score": 0.0,
        "validation_metrics": {},
        "validation_lifts": {},
    }


def _score_selected_policy(
    selected: dict[str, Any],
    base: np.ndarray,
    frame: pd.DataFrame,
    regime: pd.DataFrame,
    null_regimes: dict[str, pd.DataFrame],
    segments: dict[str, tuple[int, int]],
    baseline: dict[str, dict[str, float]],
    *,
    forecast_column: str,
    timeframe: str,
    settings: dict[str, Any],
) -> dict[str, Any]:
    ladder_cfg = settings.get("benchmark_ladder", {})
    vol_cfg = settings.get("volatility_ladder", {})
    train_start, train_end = segments["train"]
    policy = selected["policy"]
    scale = _policy_scale(
        regime[forecast_column],
        train_slice=slice(train_start, train_end),
        policy=policy,
    )
    positions = base * scale
    metrics = {
        name: _score_positions(
            positions[start:end],
            frame.iloc[start:end],
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        for name, (start, end) in segments.items()
    }
    null_control_metrics = {
        mode: {
            name: _score_positions(
                base[start:end]
                * _policy_scale(
                    null_regime[forecast_column],
                    train_slice=slice(train_start, train_end),
                    policy=policy,
                )[start:end],
                frame.iloc[start:end],
                timeframe=timeframe,
                cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
            )
            for name, (start, end) in segments.items()
        }
        for mode, null_regime in null_regimes.items()
        if forecast_column in null_regime
    }
    hardest_mode = _hardest_null_mode(null_control_metrics, segment="oos")
    shuffled_metrics = null_control_metrics[hardest_mode]
    lifts = _metric_lifts(metrics["oos"], baseline["oos"], shuffled_metrics["oos"])
    return {
        "metrics": metrics,
        "shuffled_control": shuffled_metrics,
        "null_controls": null_control_metrics,
        "null_control_mode": hardest_mode,
        "oos_lifts": lifts,
        "decision": _volatility_decision(metrics["oos"], baseline["oos"], lifts, vol_cfg),
        "selection": selected,
    }


def _candidate_policies(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    policies: list[dict[str, Any]] = []
    kinds = cfg.get(
        "policy_kinds",
        ["inverse_vol", "high_vol_throttle", "vol_rank_scaled"],
    )
    if "inverse_vol" in kinds:
        for target_mult in cfg.get("target_vol_multipliers", [0.75, 1.0, 1.25]):
            for min_scale in cfg.get("min_position_scales", [0.25, 0.50]):
                policies.append(
                    {
                        "policy_kind": "inverse_vol",
                        "target_vol_multiplier": float(target_mult),
                        "min_position_scale": float(min_scale),
                    }
                )
    if "high_vol_throttle" in kinds:
        for quantile in cfg.get("high_vol_quantiles", [0.60, 0.75, 0.90]):
            for high_scale in cfg.get("high_vol_scales", [0.25, 0.50]):
                policies.append(
                    {
                        "policy_kind": "high_vol_throttle",
                        "high_vol_quantile": float(quantile),
                        "high_vol_scale": float(high_scale),
                    }
                )
    if "vol_rank_scaled" in kinds:
        for power in cfg.get("rank_powers", [1.0, 2.0]):
            for min_scale in cfg.get("min_position_scales", [0.25, 0.50]):
                policies.append(
                    {
                        "policy_kind": "vol_rank_scaled",
                        "rank_power": float(power),
                        "min_position_scale": float(min_scale),
                    }
                )
    return policies or [{"policy_kind": "identity"}]


def _policy_scale(
    forecast: pd.Series,
    *,
    train_slice: slice,
    policy: dict[str, Any],
) -> np.ndarray:
    values = pd.to_numeric(forecast, errors="coerce").replace([np.inf, -np.inf], np.nan)
    values = values.ffill().bfill().fillna(0.0)
    train = values.iloc[train_slice]
    if len(train) == 0 or train.nunique() <= 1:
        return np.ones(len(values), dtype=float)

    kind = policy.get("policy_kind", "identity")
    if kind == "inverse_vol":
        target = float(train.median()) * float(policy.get("target_vol_multiplier", 1.0))
        min_scale = float(policy.get("min_position_scale", 0.25))
        scale = target / values.clip(lower=max(float(train.quantile(0.05)), 1e-12))
        return scale.clip(lower=min_scale, upper=1.0).to_numpy(dtype=float)

    if kind == "high_vol_throttle":
        threshold = float(train.quantile(float(policy.get("high_vol_quantile", 0.75))))
        high_scale = float(policy.get("high_vol_scale", 0.50))
        scale = np.where(values.to_numpy(dtype=float) > threshold, high_scale, 1.0)
        return np.asarray(scale, dtype=float)

    if kind == "vol_rank_scaled":
        min_scale = float(policy.get("min_position_scale", 0.25))
        power = float(policy.get("rank_power", 1.0))
        lo = float(train.quantile(0.05))
        hi = float(train.quantile(0.95))
        denom = max(hi - lo, 1e-12)
        rank = ((values - lo) / denom).clip(0.0, 1.0).to_numpy(dtype=float)
        return np.clip(1.0 - (rank**power) * (1.0 - min_scale), min_scale, 1.0)

    return np.ones(len(values), dtype=float)


def _score_hardest_null(
    base: np.ndarray,
    null_regimes: dict[str, pd.DataFrame],
    policy: dict[str, Any],
    train_slice: slice,
    segment: slice,
    frame_segment: pd.DataFrame,
    *,
    forecast_column: str,
    timeframe: str,
    settings: dict[str, Any],
) -> dict[str, float]:
    ladder_cfg = settings.get("benchmark_ladder", {})
    metrics = []
    for mode, null_regime in null_regimes.items():
        if forecast_column not in null_regime:
            continue
        scale = _policy_scale(
            null_regime[forecast_column],
            train_slice=train_slice,
            policy=policy,
        )
        scored = _score_positions(
            base[segment] * scale[segment],
            frame_segment,
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
        metrics.append((mode, scored))
    if not metrics:
        return _score_positions(
            base[segment],
            frame_segment,
            timeframe=timeframe,
            cost_bps=float(ladder_cfg.get("cost_bps", 10.0)),
        )
    return max(metrics, key=lambda item: item[1]["sharpe"])[1]


def _validation_score(
    metrics: dict[str, float],
    baseline: dict[str, float],
    lifts: dict[str, float],
    cfg: dict[str, Any],
) -> float:
    dd_improvement = abs(baseline["max_drawdown"]) - abs(metrics["max_drawdown"])
    return (
        lifts["sharpe_vs_baseline"]
        + 0.25 * lifts["calmar_vs_baseline"]
        + 0.50 * lifts["sharpe_vs_shuffled"]
        + float(cfg.get("drawdown_improvement_weight", 1.0)) * dd_improvement
        - float(cfg.get("turnover_penalty", 0.05))
        * max(0.0, metrics["turnover"] - baseline["turnover"])
    )


def _volatility_decision(
    metrics: dict[str, float],
    baseline: dict[str, float],
    lifts: dict[str, float],
    cfg: dict[str, Any],
) -> str:
    dd_improvement = abs(baseline["max_drawdown"]) - abs(metrics["max_drawdown"])
    if (
        lifts["sharpe_vs_baseline"] >= float(cfg.get("min_sharpe_lift", 0.05))
        and lifts["calmar_vs_baseline"] >= float(cfg.get("min_calmar_lift", 0.0))
        and lifts["sharpe_vs_shuffled"] >= 0.0
        and dd_improvement >= float(cfg.get("min_drawdown_improvement", 0.0))
        and metrics["avg_position"] >= float(cfg.get("min_avg_position", 0.05))
    ):
        return "promote_to_downstream_research"
    return "reject"


def _summarize_rolling_folds(
    folds: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    rolling_cfg = cfg.get("rolling_volatility_ladder", {})
    usable = [fold for fold in folds if fold.get("status") == "ok"]
    best_rows = [_best_row(fold) for fold in usable]
    best_rows = [row for row in best_rows if row]
    promoted = [row for row in best_rows if row["decision"] == "promote_to_downstream_research"]
    pass_rate = len(promoted) / len(best_rows) if best_rows else 0.0
    median_sharpe_lift = _median(row["sharpe_vs_baseline"] for row in best_rows)
    median_null_lift = _median(row["sharpe_vs_shuffled"] for row in best_rows)
    median_dd_improvement = _median(row["drawdown_improvement"] for row in best_rows)
    decision = (
        "promote_to_downstream_research"
        if len(promoted) >= int(rolling_cfg.get("min_promoted_folds", 2))
        and pass_rate >= float(rolling_cfg.get("min_pass_rate", 0.60))
        and median_sharpe_lift >= float(rolling_cfg.get("min_median_sharpe_lift", 0.05))
        and median_null_lift >= float(rolling_cfg.get("min_median_null_sharpe_lift", 0.0))
        and median_dd_improvement
        >= float(rolling_cfg.get("min_median_drawdown_improvement", 0.0))
        else "reject"
    )
    return {
        "total_folds": len(folds),
        "usable_folds": len(usable),
        "best_rows": best_rows,
        "promoted_folds": len(promoted),
        "rejected_folds": len(best_rows) - len(promoted),
        "pass_rate": float(pass_rate),
        "median_sharpe_lift": float(median_sharpe_lift),
        "median_null_sharpe_lift": float(median_null_lift),
        "median_drawdown_improvement": float(median_dd_improvement),
        "decision": decision,
    }


def _best_row(fold: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for strategy_name, strategy in fold.get("strategies", {}).items():
        overlay = strategy.get("overlays", {}).get("volatility_sized", {})
        metrics = overlay.get("metrics", {}).get("oos", {})
        baseline = strategy.get("baseline", {}).get("oos", {})
        lifts = overlay.get("oos_lifts", {})
        rows.append(
            {
                "strategy": strategy_name,
                "decision": overlay.get("decision", "reject"),
                "policy_kind": overlay.get("selection", {})
                .get("policy", {})
                .get("policy_kind", ""),
                "oos_sharpe": float(metrics.get("sharpe", 0.0)),
                "oos_total_return": float(metrics.get("total_return", 0.0)),
                "sharpe_vs_baseline": float(lifts.get("sharpe_vs_baseline", 0.0)),
                "sharpe_vs_shuffled": float(lifts.get("sharpe_vs_shuffled", 0.0)),
                "drawdown_improvement": abs(float(baseline.get("max_drawdown", 0.0)))
                - abs(float(metrics.get("max_drawdown", 0.0))),
            }
        )
    if not rows:
        return {}
    return sorted(
        rows,
        key=lambda row: (
            row["decision"] == "promote_to_downstream_research",
            row["sharpe_vs_baseline"],
            row["drawdown_improvement"],
        ),
        reverse=True,
    )[0]


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
