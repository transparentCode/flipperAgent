from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from libs.optim_utils.scoring import compute_max_drawdown, compute_sharpe
from libs.regime.optimization.downstream_backtest import (
    DEFAULT_CANDIDATES,
    _build_candidate_scales,
    _walk_forward_for_timeframe,
    load_ohlcv_frame,
)

DEFAULT_STRATEGIES = (
    "cash_flat",
    "buy_and_hold",
    "vol_targeted_buy_and_hold",
    "ema_20_50",
    "sma_50_200",
    "donchian_20_10",
    "rsi_14_30_70",
)


def build_simple_baseline_report(
    asset: str,
    timeframe: str,
    *,
    days: int,
    cost_bps: float = 10.0,
    candidate_names: tuple[str, ...] = DEFAULT_CANDIDATES,
    strategy_names: tuple[str, ...] = DEFAULT_STRATEGIES,
) -> dict[str, Any]:
    frame = load_ohlcv_frame(asset, timeframe, days=days)
    if frame.empty:
        return {"asset": asset, "timeframe": timeframe, "error": "no_data"}

    wf = _walk_forward_for_timeframe(timeframe)
    fold_rows: list[dict[str, Any]] = []
    fold_metrics: dict[str, dict[str, list[dict[str, Any]]]] = {
        strategy_name: {candidate_name: [] for candidate_name in candidate_names}
        for strategy_name in strategy_names
    }

    for split, _, test_df in wf.iterate_splits(frame):
        window_df = frame.iloc[: split.test_end].copy()
        fold_eval = _evaluate_strategy_window(
            window_df,
            asset=asset,
            timeframe=timeframe,
            cost_bps=cost_bps,
            candidate_names=candidate_names,
            strategy_names=strategy_names,
        )
        test_index = test_df.index
        fold_strategy_rows: dict[str, Any] = {}
        for strategy_name in strategy_names:
            candidate_rows: dict[str, Any] = {}
            for candidate_name in candidate_names:
                metrics = _slice_strategy_metrics(
                    fold_eval["strategies"][strategy_name]["candidates"][candidate_name],
                    test_index,
                )
                candidate_rows[candidate_name] = metrics
                fold_metrics[strategy_name][candidate_name].append(metrics)
            fold_strategy_rows[strategy_name] = {"candidates": candidate_rows}
        fold_rows.append(
            {
                "fold": split.fold_id,
                "train_start": int(split.train_start),
                "train_end": int(split.train_end),
                "test_start": test_index[0].isoformat(),
                "test_end": test_index[-1].isoformat(),
                "strategies": fold_strategy_rows,
            }
        )

    full_eval = _evaluate_strategy_window(
        frame,
        asset=asset,
        timeframe=timeframe,
        cost_bps=cost_bps,
        candidate_names=candidate_names,
        strategy_names=strategy_names,
    )

    strategy_summary: dict[str, Any] = {}
    for strategy_name in strategy_names:
        candidate_summary: dict[str, Any] = {}
        for candidate_name in candidate_names:
            walk = _aggregate_strategy_metrics(fold_metrics[strategy_name][candidate_name])
            full = _export_strategy_metrics(
                full_eval["strategies"][strategy_name]["candidates"][candidate_name]
            )
            candidate_summary[candidate_name] = {"walk_forward": walk, "full_sample": full}

        baseline_walk = candidate_summary["no_regime"]["walk_forward"]
        for candidate_name, summary in candidate_summary.items():
            walk = summary["walk_forward"]
            walk["decision"] = _candidate_decision(candidate_name, walk, baseline_walk)
            walk["sharpe_lift_vs_no_regime"] = walk["sharpe"] - baseline_walk["sharpe"]
            walk["cumulative_return_lift_vs_no_regime"] = (
                walk["cumulative_return"] - baseline_walk["cumulative_return"]
            )
            walk["calmar_lift_vs_no_regime"] = walk["calmar"] - baseline_walk["calmar"]

        ranking = sorted(
            (
                {
                    "candidate": candidate_name,
                    "decision": candidate_summary[candidate_name]["walk_forward"]["decision"],
                    "walk_forward_sharpe": candidate_summary[candidate_name]["walk_forward"]["sharpe"],
                    "walk_forward_cumulative_return": candidate_summary[candidate_name]["walk_forward"]["cumulative_return"],
                    "walk_forward_max_drawdown": candidate_summary[candidate_name]["walk_forward"]["max_drawdown"],
                    "walk_forward_calmar": candidate_summary[candidate_name]["walk_forward"]["calmar"],
                    "sharpe_lift_vs_no_regime": candidate_summary[candidate_name]["walk_forward"]["sharpe_lift_vs_no_regime"],
                }
                for candidate_name in candidate_names
            ),
            key=lambda row: (
                row["walk_forward_calmar"],
                row["walk_forward_sharpe"],
                row["walk_forward_cumulative_return"],
            ),
            reverse=True,
        )
        strategy_summary[strategy_name] = {"candidates": candidate_summary, "candidate_ranking": ranking}

    return {
        "asset": asset,
        "timeframe": timeframe,
        "date_from": frame.index[0].isoformat(),
        "date_to": frame.index[-1].isoformat(),
        "bars": int(len(frame)),
        "slice_usable": _is_slice_usable(strategy_summary),
        "candidate_names": list(candidate_names),
        "strategy_names": list(strategy_names),
        "folds": fold_rows,
        "strategies": strategy_summary,
    }


def build_simple_panel_summary(
    rows: list[dict[str, Any]],
    *,
    candidate_names: tuple[str, ...] = DEFAULT_CANDIDATES,
    strategy_names: tuple[str, ...] = DEFAULT_STRATEGIES,
) -> dict[str, Any]:
    usable_rows = [row for row in rows if "strategies" in row and row.get("slice_usable")]
    summary: dict[str, Any] = {}

    for strategy_name in strategy_names:
        strategy_summary: dict[str, Any] = {}
        baseline_entries = [
            row["strategies"][strategy_name]["candidates"]["no_regime"]["walk_forward"]
            for row in usable_rows
            if strategy_name in row["strategies"]
        ]
        for candidate_name in candidate_names:
            entries = [
                row["strategies"][strategy_name]["candidates"][candidate_name]["walk_forward"]
                for row in usable_rows
                if strategy_name in row["strategies"] and candidate_name in row["strategies"][strategy_name]["candidates"]
            ]
            if not entries:
                continue
            strategy_summary[candidate_name] = {
                "strategy": strategy_name,
                "candidate": candidate_name,
                "evaluated_slices": len(entries),
                "total_requested_slices": len(rows),
                "median_sharpe": _median_metric(entries, "sharpe"),
                "median_cumulative_return": _median_metric(entries, "cumulative_return"),
                "median_max_drawdown": _median_metric(entries, "max_drawdown"),
                "median_calmar": _median_metric(entries, "calmar"),
                "median_turnover": _median_metric(entries, "turnover"),
                "positive_sharpe_lift_slices": sum(
                    1
                    for entry, baseline in zip(entries, baseline_entries, strict=False)
                    if entry["sharpe"] > baseline["sharpe"]
                ),
                "positive_calmar_lift_slices": sum(
                    1
                    for entry, baseline in zip(entries, baseline_entries, strict=False)
                    if entry["calmar"] > baseline["calmar"]
                ),
                "per_slice": [
                    {
                        "asset": row["asset"],
                        "timeframe": row["timeframe"],
                        "decision": row["strategies"][strategy_name]["candidates"][candidate_name]["walk_forward"]["decision"],
                        "sharpe": row["strategies"][strategy_name]["candidates"][candidate_name]["walk_forward"]["sharpe"],
                        "cumulative_return": row["strategies"][strategy_name]["candidates"][candidate_name]["walk_forward"]["cumulative_return"],
                        "max_drawdown": row["strategies"][strategy_name]["candidates"][candidate_name]["walk_forward"]["max_drawdown"],
                        "calmar": row["strategies"][strategy_name]["candidates"][candidate_name]["walk_forward"]["calmar"],
                    }
                    for row in usable_rows
                    if strategy_name in row["strategies"] and candidate_name in row["strategies"][strategy_name]["candidates"]
                ],
            }
        baseline = strategy_summary.get("no_regime")
        for candidate_name, entry in strategy_summary.items():
            entry["panel_decision"] = _panel_decision(candidate_name, entry, baseline)
        summary[strategy_name] = strategy_summary

    overall_ranking = sorted(
        (
            {
                "strategy": strategy_name,
                **candidate_summary,
            }
            for strategy_name, strategy_entries in summary.items()
            for candidate_summary in strategy_entries.values()
        ),
        key=lambda row: (
            row["median_calmar"],
            row["median_sharpe"],
            row["median_cumulative_return"],
        ),
        reverse=True,
    )

    return {
        "usable_slices": len(usable_rows),
        "total_requested_slices": len(rows),
        "strategy_summary": summary,
        "overall_ranking": overall_ranking,
    }


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2))


def _evaluate_strategy_window(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    cost_bps: float,
    candidate_names: tuple[str, ...],
    strategy_names: tuple[str, ...],
) -> dict[str, Any]:
    candidate_scales = _build_candidate_scales(
        frame,
        asset=asset,
        timeframe=timeframe,
        candidate_names=candidate_names,
    )
    strategy_positions = _build_strategy_positions(frame, timeframe=timeframe, strategy_names=strategy_names)
    close = frame["close"]
    strategies: dict[str, Any] = {}
    for strategy_name, base_positions in strategy_positions.items():
        candidates: dict[str, Any] = {}
        for candidate_name in candidate_names:
            positions = base_positions * candidate_scales[candidate_name]
            candidates[candidate_name] = _evaluate_position_series(
                positions,
                close=close,
                timeframe=timeframe,
                cost_bps=cost_bps,
            )
        strategies[strategy_name] = {"candidates": candidates}
    return {"strategies": strategies}


def _build_strategy_positions(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    strategy_names: tuple[str, ...],
) -> dict[str, pd.Series]:
    close = frame["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    positions: dict[str, pd.Series] = {}

    for strategy_name in strategy_names:
        if strategy_name == "cash_flat":
            positions[strategy_name] = pd.Series(0.0, index=frame.index, dtype=float)
        elif strategy_name == "buy_and_hold":
            positions[strategy_name] = pd.Series(1.0, index=frame.index, dtype=float)
        elif strategy_name == "vol_targeted_buy_and_hold":
            bars_per_year = _bars_per_year(timeframe)
            realized_vol = returns.rolling(20, min_periods=10).std() * math.sqrt(bars_per_year)
            size = (1.0 / realized_vol.replace(0.0, np.nan)).clip(lower=0.0, upper=1.5).fillna(0.0)
            positions[strategy_name] = size.astype(float)
        elif strategy_name == "ema_20_50":
            fast = close.ewm(span=20, adjust=False).mean()
            slow = close.ewm(span=50, adjust=False).mean()
            positions[strategy_name] = (fast > slow).astype(float)
        elif strategy_name == "sma_50_200":
            fast = close.rolling(50, min_periods=50).mean()
            slow = close.rolling(200, min_periods=200).mean()
            positions[strategy_name] = (fast > slow).astype(float).fillna(0.0)
        elif strategy_name == "donchian_20_10":
            positions[strategy_name] = _donchian_breakout_positions(close, entry=20, exit_=10)
        elif strategy_name == "rsi_14_30_70":
            positions[strategy_name] = _rsi_mean_reversion_positions(close, period=14, lower=30.0, upper=70.0)
        else:
            raise ValueError(f"Unsupported simple strategy: {strategy_name}")

    return positions


def _evaluate_position_series(
    positions: pd.Series,
    *,
    close: pd.Series,
    timeframe: str,
    cost_bps: float,
) -> dict[str, Any]:
    metrics = _backtest_positions(
        positions.to_numpy(dtype=float),
        close.to_numpy(dtype=float),
        timeframe=timeframe,
        cost_bps=cost_bps,
    )
    metrics["position_series"] = positions.astype(float)
    metrics["close_series"] = close.astype(float)
    metrics["timeframe"] = timeframe
    metrics["cost_bps"] = cost_bps
    return metrics


def _slice_strategy_metrics(candidate: dict[str, Any], index: pd.Index) -> dict[str, Any]:
    positions = candidate["position_series"].reindex(index).fillna(0.0)
    close = candidate["close_series"].reindex(index).astype(float)
    metrics = _backtest_positions(
        positions.to_numpy(dtype=float),
        close.to_numpy(dtype=float),
        timeframe=candidate["timeframe"],
        cost_bps=candidate["cost_bps"],
    )
    return {
        "sharpe": metrics["sharpe"],
        "cumulative_return": metrics["cumulative_return"],
        "max_drawdown": metrics["max_drawdown"],
        "calmar": metrics["calmar"],
        "turnover": metrics["turnover"],
        "trade_count": metrics["trade_count"],
        "active_ratio": metrics["active_ratio"],
    }


def _aggregate_strategy_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sharpe": _median_metric(rows, "sharpe"),
        "cumulative_return": _median_metric(rows, "cumulative_return"),
        "max_drawdown": _median_metric(rows, "max_drawdown"),
        "calmar": _median_metric(rows, "calmar"),
        "turnover": _median_metric(rows, "turnover"),
        "trade_count": _median_metric(rows, "trade_count"),
        "active_ratio": _median_metric(rows, "active_ratio"),
    }


def _export_strategy_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "sharpe": candidate["sharpe"],
        "cumulative_return": candidate["cumulative_return"],
        "max_drawdown": candidate["max_drawdown"],
        "calmar": candidate["calmar"],
        "turnover": candidate["turnover"],
        "trade_count": candidate["trade_count"],
        "active_ratio": candidate["active_ratio"],
    }


def _backtest_positions(
    positions: np.ndarray,
    close_prices: np.ndarray,
    *,
    timeframe: str,
    cost_bps: float,
) -> dict[str, Any]:
    clipped = np.clip(positions, -1.5, 1.5)
    bar_returns = np.diff(close_prices) / np.maximum(close_prices[:-1], 1e-12)
    pos = clipped[:-1]
    strategy_returns = pos * bar_returns
    pos_changes = np.diff(np.concatenate([[0.0], pos]))
    strategy_returns -= np.abs(pos_changes) * (cost_bps / 10_000.0)

    cumulative = float(np.prod(1.0 + strategy_returns) - 1.0) if len(strategy_returns) else 0.0
    max_drawdown = compute_max_drawdown(strategy_returns)
    calmar = 0.0
    if max_drawdown < 0.0:
        calmar = cumulative / abs(max_drawdown)
    elif cumulative > 0.0:
        calmar = float("inf")

    active_ratio = float(np.mean(np.abs(pos) > 1e-9)) if len(pos) else 0.0
    turnover = float(np.sum(np.abs(pos_changes)))
    trade_count = int(np.sum(np.abs(pos_changes) > 1e-9))
    return {
        "sharpe": compute_sharpe(strategy_returns, timeframe),
        "cumulative_return": cumulative,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "turnover": turnover,
        "trade_count": trade_count,
        "active_ratio": active_ratio,
    }


def _donchian_breakout_positions(close: pd.Series, *, entry: int, exit_: int) -> pd.Series:
    entry_high = close.rolling(entry, min_periods=entry).max().shift(1)
    exit_low = close.rolling(exit_, min_periods=exit_).min().shift(1)
    state = np.zeros(len(close), dtype=float)
    active = 0.0
    for idx, price in enumerate(close.to_numpy(dtype=float)):
        if np.isfinite(entry_high.iloc[idx]) and price > float(entry_high.iloc[idx]):
            active = 1.0
        elif np.isfinite(exit_low.iloc[idx]) and price < float(exit_low.iloc[idx]):
            active = 0.0
        state[idx] = active
    return pd.Series(state, index=close.index, dtype=float)


def _rsi_mean_reversion_positions(
    close: pd.Series,
    *,
    period: int,
    lower: float,
    upper: float,
) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    state = np.zeros(len(close), dtype=float)
    active = 0.0
    for idx, value in enumerate(rsi.fillna(50.0).to_numpy(dtype=float)):
        if value < lower:
            active = 1.0
        elif value > upper:
            active = 0.0
        state[idx] = active
    return pd.Series(state, index=close.index, dtype=float)


def _candidate_decision(candidate_name: str, row: dict[str, Any], baseline: dict[str, Any]) -> str:
    if candidate_name == "no_regime":
        return "baseline"
    better_sharpe = row["sharpe"] > baseline["sharpe"]
    better_return = row["cumulative_return"] > baseline["cumulative_return"]
    better_dd = row["max_drawdown"] >= baseline["max_drawdown"]
    better_calmar = row["calmar"] > baseline["calmar"]
    if better_sharpe and (better_return or better_calmar) and better_dd:
        return "promote_to_integration_design"
    if better_sharpe or better_calmar or better_return:
        return "keep_research_only"
    return "reject"


def _panel_decision(candidate_name: str, row: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    if candidate_name == "no_regime":
        return "baseline"
    if baseline is None:
        return "reject"
    threshold = math.ceil(row["evaluated_slices"] * 0.6)
    if (
        row["positive_calmar_lift_slices"] >= threshold
        and row["median_calmar"] > baseline["median_calmar"]
        and row["median_max_drawdown"] >= baseline["median_max_drawdown"]
    ):
        return "promote_to_integration_design"
    if row["median_calmar"] > baseline["median_calmar"] or row["median_sharpe"] > baseline["median_sharpe"]:
        return "keep_research_only"
    return "reject"


def _is_slice_usable(strategy_summary: dict[str, Any]) -> bool:
    for strategy_name, strategy_row in strategy_summary.items():
        if strategy_name == "cash_flat":
            continue
        baseline = strategy_row["candidates"]["no_regime"]["full_sample"]
        if baseline["trade_count"] > 0 or baseline["turnover"] > 0.0:
            return True
    return False


def _median_metric(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows]
    return float(median(values)) if values else 0.0


def _bars_per_year(timeframe: str) -> float:
    return {
        "30m": 24.0 * 365.0 * 2.0,
        "1h": 24.0 * 365.0,
        "4h": 6.0 * 365.0,
        "1d": 365.0,
    }.get(timeframe, 24.0 * 365.0)
