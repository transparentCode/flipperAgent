from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_MODELS
from libs.models.legacy_adapter import LegacyScoringAdapter
from libs.models.legacy_bootstrap import bootstrap_legacy_model_registries
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.scoring import compute_max_drawdown, compute_sharpe
from libs.optim_utils.scoring_feature_pipeline import build_scoring_feature_df
from libs.regime.config_loader import load_regime_config
from libs.regime.optimization.breadth_overlays import (
    build_breadth_variants,
    compute_breadth_features,
)
from libs.regime.optimization.models import OptimizationConfig
from libs.regime.optimization.walk_forward import WalkForwardValidator
from libs.regime.orchestrator import RegimeOrchestrator

DEFAULT_CANDIDATES = ("no_regime", "regime_only", "breadth_gate", "breadth_blend")
_DEFAULT = "default"
_ASSETS = "assets"
_TIMEFRAMES = "timeframes"


def load_ohlcv_frame(asset: str, timeframe: str, *, days: int) -> pd.DataFrame:
    end = pd.Timestamp.utcnow()
    start = end - pd.Timedelta(days=days)
    seconds_per_bar = {
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }.get(timeframe)
    if seconds_per_bar is None:
        raise ValueError(f"Unsupported timeframe for downstream benchmark: {timeframe}")

    limit = int(((end - start).total_seconds()) / seconds_per_bar) + 32
    df = fetch_historical_ohlcv(
        asset,
        timeframe,
        since=int(start.timestamp() * 1000),
        until=int(end.timestamp() * 1000),
        limit=limit,
    )
    if df.empty:
        return df

    frame = df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.set_index("timestamp").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = frame[col].astype(float)
    return frame[["open", "high", "low", "close", "volume"]]


def build_downstream_candidate_report(
    asset: str,
    timeframe: str,
    *,
    days: int,
    cost_bps: float = 10.0,
    candidate_names: tuple[str, ...] = DEFAULT_CANDIDATES,
) -> dict[str, Any]:
    frame = load_ohlcv_frame(asset, timeframe, days=days)
    if frame.empty:
        return {"asset": asset, "timeframe": timeframe, "error": "no_data"}

    wf = _walk_forward_for_timeframe(timeframe)
    fold_rows: list[dict[str, Any]] = []
    candidate_fold_metrics: dict[str, list[dict[str, Any]]] = {
        name: [] for name in candidate_names
    }

    for split, _, test_df in wf.iterate_splits(frame):
        window_df = frame.iloc[: split.test_end].copy()
        fold_eval = _evaluate_window(
            window_df,
            asset=asset,
            timeframe=timeframe,
            cost_bps=cost_bps,
            candidate_names=candidate_names,
        )
        test_index = test_df.index
        candidates: dict[str, dict[str, Any]] = {}
        for candidate_name in candidate_names:
            metrics = _slice_candidate_metrics(
                fold_eval["candidates"][candidate_name], test_index
            )
            candidates[candidate_name] = metrics
            candidate_fold_metrics[candidate_name].append(metrics)
        fold_rows.append(
            {
                "fold": split.fold_id,
                "train_start": int(split.train_start),
                "train_end": int(split.train_end),
                "test_start": test_index[0].isoformat(),
                "test_end": test_index[-1].isoformat(),
                "candidates": candidates,
            }
        )

    full_eval = _evaluate_window(
        frame,
        asset=asset,
        timeframe=timeframe,
        cost_bps=cost_bps,
        candidate_names=candidate_names,
    )

    candidate_summary: dict[str, Any] = {}
    for candidate_name in candidate_names:
        fold_metrics = candidate_fold_metrics[candidate_name]
        full_candidate = full_eval["candidates"][candidate_name]
        summary = {
            "walk_forward": _aggregate_candidate_metrics(fold_metrics),
            "full_sample": _export_candidate_metrics(full_candidate),
        }
        candidate_summary[candidate_name] = summary

    baseline_walk = candidate_summary["no_regime"]["walk_forward"]
    for candidate_name, summary in candidate_summary.items():
        walk = summary["walk_forward"]
        walk["decision"] = _candidate_decision(candidate_name, walk, baseline_walk)
        walk["sharpe_lift_vs_no_regime"] = walk["sharpe"] - baseline_walk["sharpe"]
        walk["cumulative_return_lift_vs_no_regime"] = (
            walk["cumulative_return"] - baseline_walk["cumulative_return"]
        )

    ranking = sorted(
        (
            {
                "candidate": name,
                "decision": candidate_summary[name]["walk_forward"]["decision"],
                "walk_forward_sharpe": candidate_summary[name]["walk_forward"][
                    "sharpe"
                ],
                "walk_forward_cumulative_return": candidate_summary[name][
                    "walk_forward"
                ]["cumulative_return"],
                "walk_forward_max_drawdown": candidate_summary[name]["walk_forward"][
                    "max_drawdown"
                ],
                "sharpe_lift_vs_no_regime": candidate_summary[name]["walk_forward"][
                    "sharpe_lift_vs_no_regime"
                ],
            }
            for name in candidate_names
        ),
        key=lambda row: (
            row["walk_forward_sharpe"],
            row["walk_forward_cumulative_return"],
            row["walk_forward_max_drawdown"],
        ),
        reverse=True,
    )

    return {
        "asset": asset,
        "timeframe": timeframe,
        "date_from": frame.index[0].isoformat(),
        "date_to": frame.index[-1].isoformat(),
        "bars": len(frame),
        "slice_usable": _is_usable_candidates(candidate_summary),
        "model_names": full_eval["model_names"],
        "candidate_names": list(candidate_names),
        "folds": fold_rows,
        "candidates": candidate_summary,
        "candidate_ranking": ranking,
    }


def build_panel_summary(
    rows: list[dict[str, Any]],
    *,
    candidate_names: tuple[str, ...] = DEFAULT_CANDIDATES,
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    usable_rows = [row for row in rows if "candidates" in row and _is_usable_row(row)]
    baseline_entries = [
        row["candidates"]["no_regime"]["walk_forward"] for row in usable_rows
    ]

    for candidate_name in candidate_names:
        entries = [
            row["candidates"][candidate_name]["walk_forward"]
            for row in usable_rows
            if candidate_name in row["candidates"]
        ]
        if not entries:
            continue
        summary[candidate_name] = {
            "candidate": candidate_name,
            "evaluated_slices": len(entries),
            "total_requested_slices": len(rows),
            "median_sharpe": _median_metric(entries, "sharpe"),
            "median_cumulative_return": _median_metric(entries, "cumulative_return"),
            "median_max_drawdown": _median_metric(entries, "max_drawdown"),
            "median_turnover": _median_metric(entries, "turnover"),
            "positive_sharpe_lift_slices": sum(
                1
                for entry, baseline in zip(entries, baseline_entries, strict=False)
                if entry["sharpe"] > baseline["sharpe"]
            ),
            "per_slice": [
                {
                    "asset": row["asset"],
                    "timeframe": row["timeframe"],
                    "decision": row["candidates"][candidate_name]["walk_forward"][
                        "decision"
                    ],
                    "sharpe": row["candidates"][candidate_name]["walk_forward"][
                        "sharpe"
                    ],
                    "cumulative_return": row["candidates"][candidate_name][
                        "walk_forward"
                    ]["cumulative_return"],
                    "max_drawdown": row["candidates"][candidate_name]["walk_forward"][
                        "max_drawdown"
                    ],
                    "best_model_counts": row["candidates"][candidate_name][
                        "walk_forward"
                    ]["model_selection_counts"],
                }
                for row in usable_rows
                if candidate_name in row["candidates"]
            ],
        }

    baseline = summary.get("no_regime")
    for candidate_name, row in summary.items():
        row["panel_decision"] = _panel_decision(candidate_name, row, baseline)

    panel_ranking = sorted(
        summary.values(),
        key=lambda row: (
            row["median_sharpe"],
            row["median_cumulative_return"],
            row["median_max_drawdown"],
        ),
        reverse=True,
    )
    return {
        "usable_slices": len(usable_rows),
        "total_requested_slices": len(rows),
        "candidate_summary": summary,
        "panel_ranking": panel_ranking,
    }


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2))


def _evaluate_window(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    cost_bps: float,
    candidate_names: tuple[str, ...],
) -> dict[str, Any]:
    feature_df = build_scoring_feature_df(frame.reset_index(), asset, timeframe)
    feature_df.index = frame.index

    breadth_features = compute_breadth_features(frame)
    for col in breadth_features.columns:
        feature_df[col] = breadth_features[col]

    candidate_scales = _build_candidate_scales(
        frame, asset=asset, timeframe=timeframe, candidate_names=candidate_names
    )
    models = _load_scoring_models(asset, timeframe)
    edge_df = _evaluate_models(feature_df, models)
    candidates: dict[str, dict[str, Any]] = {}
    close = frame["close"]
    for candidate_name in candidate_names:
        scaled_edges = edge_df.mul(candidate_scales[candidate_name], axis=0)
        candidates[candidate_name] = _evaluate_scaled_edges(
            scaled_edges,
            close=close,
            timeframe=timeframe,
            cost_bps=cost_bps,
        )
    return {"model_names": list(edge_df.columns), "candidates": candidates}


def _build_candidate_scales(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    candidate_names: tuple[str, ...],
) -> dict[str, pd.Series]:
    params = _load_regime_params(asset, timeframe)
    orchestrator = RegimeOrchestrator.create(asset=asset, timeframe=timeframe, **params)
    regime_features = orchestrator.analyze_series(frame)
    breadth_features = compute_breadth_features(frame)
    breadth_frames = build_breadth_variants(
        regime_features,
        breadth_features,
        position_scale_cfg=orchestrator.aggregator.config.position_scale,
        cp_position_decay=orchestrator.aggregator.config.cp_position_decay,
        vol_squeeze_pct=orchestrator.aggregator.config.vol_squeeze_pct,
        variants=tuple(name for name in candidate_names if name != "no_regime"),
    )
    scales: dict[str, pd.Series] = {}
    for name in candidate_names:
        if name == "no_regime":
            scales[name] = pd.Series(1.0, index=frame.index)
            continue
        variant_df = breadth_frames[name]
        scales[name] = (
            variant_df["position_scale"]
            .reindex(frame.index)
            .fillna(0.0)
            .clip(lower=0.0, upper=1.5)
            .astype(float)
        )
    return scales


def _load_scoring_models(asset: str, timeframe: str) -> list[ScoringModel]:
    bootstrap_legacy_model_registries()
    manager = ConfigManager()
    manager.register_file(CONFIG_FILE_MODELS)
    models: list[ScoringModel] = []

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for model_name, model_cfg in _resolve_asset_timeframe_node(
            manager, "models", asset, timeframe
        ).items():
            loaded = _load_model_entry(model_name, model_cfg)
            if loaded is not None:
                models.append(loaded)
        for model_name, model_cfg in _resolve_asset_timeframe_node(
            manager, "scoring_models", asset, timeframe
        ).items():
            loaded = _load_scoring_entry(model_name, model_cfg)
            if loaded is not None:
                models.append(loaded)

    deduped: dict[str, ScoringModel] = {}
    for model in models:
        deduped.setdefault(model.meta.name, model)
    return list(deduped.values())


def _resolve_asset_timeframe_node(
    config_manager: ConfigManager,
    root_key: str,
    asset: str,
    timeframe: str,
) -> dict[str, Any]:
    config = config_manager.get(root_key, {})
    assets_config = config.get(_ASSETS, {})
    asset_node = assets_config.get(asset, {})
    default_asset_node = assets_config.get(_DEFAULT, {})
    tf_node = asset_node.get(_TIMEFRAMES, {}).get(timeframe, {})
    asset_default_tf = asset_node.get(_TIMEFRAMES, {}).get(_DEFAULT, {})
    default_tf_node = default_asset_node.get(_TIMEFRAMES, {}).get(timeframe, {})
    default_default_tf = default_asset_node.get(_TIMEFRAMES, {}).get(_DEFAULT, {})
    merged: dict[str, Any] = {}
    for node in (default_default_tf, default_tf_node, asset_default_tf, tf_node):
        if isinstance(node, dict):
            merged.update(node)
    return merged


def _load_model_entry(model_name: str, model_cfg: Any) -> ScoringModel | None:
    if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
        return None
    try:
        model_cls = ModelRegistry.get(model_name)
    except KeyError:
        return None
    params = model_cfg.get("params", {}) or {}
    migration_mode = str(model_cfg.get("migration_mode", "legacy"))
    if migration_mode == "native_scoring":
        return None
    instance = model_cls(params)
    if migration_mode == "scoring" and isinstance(instance, ScoringModel):
        return instance
    return LegacyScoringAdapter(instance)


def _load_scoring_entry(model_name: str, model_cfg: Any) -> ScoringModel | None:
    if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
        return None
    try:
        model_cls = ModelRegistry.get(model_name)
    except KeyError:
        return None
    instance = model_cls(model_cfg.get("params", {}) or {})
    if not isinstance(instance, ScoringModel):
        raise TypeError(
            f"configured scoring model {model_name} must extend ScoringModel"
        )
    return instance


def _evaluate_models(
    feature_df: pd.DataFrame, models: list[ScoringModel]
) -> pd.DataFrame:
    edges: dict[str, pd.Series] = {}
    for model in models:
        try:
            series = model.batch_evaluate(feature_df).fillna(0.0).astype(float)
        except Exception as exc:  # noqa: BLE001
            warnings.warn(
                (
                    "Skipping downstream model "
                    f"{getattr(model.meta, 'name', type(model).__name__)} "
                    f"after batch evaluation failure: {exc}"
                ),
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        if not np.isfinite(series.values).all():
            series = series.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        edges[model.meta.name] = series
    if not edges:
        raise ValueError("No downstream models produced batch-evaluable outputs")
    return pd.DataFrame(edges, index=feature_df.index).fillna(0.0)


def _evaluate_scaled_edges(
    edge_df: pd.DataFrame,
    *,
    close: pd.Series,
    timeframe: str,
    cost_bps: float,
) -> dict[str, Any]:
    selected_edges, selected_models = _select_top_edges(edge_df)
    metrics = _backtest_edge_series(
        selected_edges,
        close.values.astype(float),
        timeframe=timeframe,
        cost_bps=cost_bps,
    )
    metrics["model_selection_counts"] = {
        str(name): int(count)
        for name, count in selected_models.value_counts().items()
        if name is not None
    }
    metrics["selected_edge_series"] = selected_edges
    metrics["selected_model_series"] = selected_models
    metrics["close_series"] = close
    metrics["timeframe"] = timeframe
    metrics["cost_bps"] = cost_bps
    return metrics


def _select_top_edges(edge_df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    abs_edges = edge_df.abs()
    top_model = abs_edges.idxmax(axis=1).astype(object)
    top_edge = pd.Series(0.0, index=edge_df.index, dtype=float)
    non_zero = abs_edges.max(axis=1) > 0.0
    if non_zero.any():
        row_idx = np.flatnonzero(non_zero.to_numpy(dtype=bool))
        col_idx = edge_df.columns.get_indexer(top_model.loc[non_zero])
        values = edge_df.to_numpy(dtype=float)[row_idx, col_idx]
        top_edge.loc[non_zero] = values
    top_model.loc[~non_zero] = None
    return top_edge, top_model


def _backtest_edge_series(
    edge_series: pd.Series,
    close_prices: np.ndarray,
    *,
    timeframe: str,
    cost_bps: float,
) -> dict[str, Any]:
    positions = np.clip(edge_series.to_numpy(dtype=float), -1.0, 1.0)
    bar_returns = np.diff(close_prices) / np.maximum(close_prices[:-1], 1e-12)
    pos = positions[:-1]
    strategy_returns = pos * bar_returns
    pos_changes = np.diff(np.concatenate([[0.0], pos]))
    strategy_returns -= np.abs(pos_changes) * (cost_bps / 10_000.0)

    cumulative = (
        float(np.prod(1.0 + strategy_returns) - 1.0) if len(strategy_returns) else 0.0
    )
    active_ratio = float(np.mean(np.abs(pos) > 1e-9)) if len(pos) else 0.0
    turnover = float(np.sum(np.abs(pos_changes)))
    trade_count = int(np.sum(np.abs(pos_changes) > 1e-9))
    return {
        "sharpe": compute_sharpe(strategy_returns, timeframe),
        "cumulative_return": cumulative,
        "max_drawdown": compute_max_drawdown(strategy_returns),
        "turnover": turnover,
        "trade_count": trade_count,
        "active_ratio": active_ratio,
    }


def _slice_candidate_metrics(
    candidate: dict[str, Any], index: pd.Index
) -> dict[str, Any]:
    edges = candidate["selected_edge_series"].reindex(index).fillna(0.0)
    models = candidate["selected_model_series"].reindex(index)
    close = candidate["close_series"].reindex(index).astype(float)
    metrics = _backtest_edge_series(
        edges,
        close.to_numpy(dtype=float),
        timeframe=candidate["timeframe"],
        cost_bps=candidate["cost_bps"],
    )
    return {
        "sharpe": metrics["sharpe"],
        "cumulative_return": metrics["cumulative_return"],
        "max_drawdown": metrics["max_drawdown"],
        "turnover": metrics["turnover"],
        "trade_count": metrics["trade_count"],
        "active_ratio": metrics["active_ratio"],
        "model_selection_counts": {
            str(name): int(count)
            for name, count in models.value_counts().items()
            if name is not None
        },
    }


def _aggregate_candidate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aggregated = {
        "sharpe": _median_metric(rows, "sharpe"),
        "cumulative_return": _median_metric(rows, "cumulative_return"),
        "max_drawdown": _median_metric(rows, "max_drawdown"),
        "turnover": _median_metric(rows, "turnover"),
        "trade_count": _median_metric(rows, "trade_count"),
        "active_ratio": _median_metric(rows, "active_ratio"),
    }
    model_counts: dict[str, int] = {}
    for row in rows:
        for model_name, count in row["model_selection_counts"].items():
            model_counts[model_name] = model_counts.get(model_name, 0) + count
    aggregated["model_selection_counts"] = model_counts
    return aggregated


def _export_candidate_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "sharpe": candidate["sharpe"],
        "cumulative_return": candidate["cumulative_return"],
        "max_drawdown": candidate["max_drawdown"],
        "turnover": candidate["turnover"],
        "trade_count": candidate["trade_count"],
        "active_ratio": candidate["active_ratio"],
        "model_selection_counts": candidate["model_selection_counts"],
    }


def _candidate_decision(
    candidate_name: str, row: dict[str, Any], baseline: dict[str, Any]
) -> str:
    if candidate_name == "no_regime":
        return "baseline"
    better_sharpe = row["sharpe"] > baseline["sharpe"]
    better_return = row["cumulative_return"] > baseline["cumulative_return"]
    better_dd = row["max_drawdown"] >= baseline["max_drawdown"]
    if better_sharpe and better_return and better_dd:
        return "promote_to_integration_design"
    if better_sharpe or better_return:
        return "keep_research_only"
    return "reject"


def _panel_decision(
    candidate_name: str, row: dict[str, Any], baseline: dict[str, Any] | None
) -> str:
    if candidate_name == "no_regime":
        return "baseline"
    if baseline is None:
        return "reject"
    improved_slices = row["positive_sharpe_lift_slices"]
    if (
        improved_slices >= math.ceil(row["evaluated_slices"] * 0.6)
        and row["median_sharpe"] > baseline["median_sharpe"]
    ):
        return "promote_to_integration_design"
    if (
        row["median_sharpe"] > baseline["median_sharpe"]
        or row["median_cumulative_return"] > baseline["median_cumulative_return"]
    ):
        return "keep_research_only"
    return "reject"


def _is_usable_candidates(candidate_summary: dict[str, Any]) -> bool:
    baseline = candidate_summary.get("no_regime", {})
    walk = baseline.get("walk_forward", {})
    full = baseline.get("full_sample", {})
    return bool(
        walk.get("trade_count", 0) > 0
        or walk.get("turnover", 0.0) > 0.0
        or full.get("trade_count", 0) > 0
        or full.get("turnover", 0.0) > 0.0
    )


def _is_usable_row(row: dict[str, Any]) -> bool:
    if "slice_usable" in row:
        return bool(row["slice_usable"])
    return _is_usable_candidates(row.get("candidates", {}))


def _median_metric(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows]
    return float(median(values)) if values else 0.0


def _walk_forward_for_timeframe(timeframe: str) -> WalkForwardValidator:
    config = OptimizationConfig()
    wf = WalkForwardValidator(
        train_bars=config.walk_forward.train_bars,
        test_bars=config.walk_forward.test_bars,
        step_bars=config.walk_forward.step_bars,
        purge_bars=config.walk_forward.purge_bars_for_timeframe(timeframe),
        min_train_bars=config.walk_forward.min_train_bars,
    )
    return wf


def _load_regime_params(asset: str, timeframe: str) -> dict[str, Any]:
    raw_cfg = load_regime_config()
    params = dict(raw_cfg.get("assets", {}).get(asset, {}).get(timeframe, {}))
    if params:
        return params
    return dict(raw_cfg.get("defaults", {}))
