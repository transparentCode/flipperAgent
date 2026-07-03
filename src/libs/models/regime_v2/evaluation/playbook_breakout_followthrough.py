"""Directional breakout follow-through refinement for RegimeV2 Phase 7F.

Phase 7E proved that breakout confirmation can identify large movement, but not
necessarily favorable directional continuation. 7F keeps the same offline-only
posture and adds direction-aware confirmation scoring plus directional outcome
validation.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

_CONFIRMATION_STATE = "BREAKOUT_CONFIRMATION"
_ELIGIBLE_STATES = {"BREAKOUT_SETUP", "WAIT_COMPRESSION"}
_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)


def build_breakout_followthrough_frame(
    analysis_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    breakout_window: int = 20,
    hold_bars: int = 2,
    follow_bars: int = 3,
    min_followthrough_score: float = 0.35,
    max_false_breakout_risk: float = 0.65,
    max_shock_risk: float = 0.80,
) -> pd.DataFrame:
    """Return refined states using direction-aware follow-through evidence."""
    features = _followthrough_features(
        analysis_df,
        ohlcv,
        breakout_window=int(breakout_window),
        hold_bars=int(hold_bars),
        follow_bars=int(follow_bars),
    )
    joined = state_df.copy().join(features, how="left")
    rows = []
    for _, row in joined.iterrows():
        rows.append(
            _refined_row(
                row,
                min_followthrough_score=float(min_followthrough_score),
                max_false_breakout_risk=float(max_false_breakout_risk),
                max_shock_risk=float(max_shock_risk),
            )
        )
    return pd.DataFrame(rows, index=joined.index)


def build_breakout_followthrough_report(
    refined_state_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Summarize the 7F direction-aware refinement."""
    rows = int(len(refined_state_df))
    eligible = refined_state_df[refined_state_df["breakout_followthrough_eligible"] == True]
    active = refined_state_df[refined_state_df["breakout_followthrough_active"] == True]
    return {
        "phase": "phase_7f_breakout_followthrough_refinement",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "source": source,
            "row_count": rows,
            "eligible_count": int(len(eligible)),
            "eligible_rate": _rate(len(eligible), rows),
            "active_count": int(len(active)),
            "active_rate": _rate(len(active), rows),
            "avg_followthrough_score": _mean(refined_state_df.get("breakout_followthrough_score")),
            "avg_active_score": _mean(active.get("breakout_followthrough_score")) if len(active) else None,
            "base_state_distribution": _counts(refined_state_df.get("playbook_state_base")),
            "refined_state_distribution": _counts(refined_state_df.get("playbook_state")),
            "reason_distribution": _counts(refined_state_df.get("breakout_followthrough_reason")),
            "direction_distribution": _counts(active.get("breakout_followthrough_direction")) if len(active) else {},
        },
        "recent_active": _recent_active(refined_state_df),
    }


def build_breakout_followthrough_outcome_matrix(
    refined_state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
) -> dict[str, Any]:
    """Evaluate active follow-through rows using directional net returns."""
    cells = []
    for horizon in horizons:
        for fee in fees_bps:
            labeled = label_breakout_followthrough_outcomes(
                refined_state_df,
                ohlcv,
                horizon_bars=int(horizon),
                fee_bps=float(fee),
            )
            cells.append(_cell(labeled, horizon_bars=int(horizon), fee_bps=float(fee)))
    return {
        "phase": "phase_7f_breakout_followthrough_outcome_matrix",
        "summary": _matrix_summary(cells),
        "cells": cells,
    }


def label_breakout_followthrough_outcomes(
    refined_state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizon_bars: int,
    fee_bps: float,
) -> list[dict[str, Any]]:
    """Label active 7F confirmations with directional future returns."""
    price = _prepare_ohlcv(ohlcv)
    fee = float(fee_bps) / 10000.0
    records = []
    active = refined_state_df[refined_state_df["breakout_followthrough_active"] == True].copy()
    for ts, row in active.iterrows():
        if ts not in price.index:
            records.append(_unlabeled(ts, row, "timestamp_not_in_ohlcv", horizon_bars, fee_bps))
            continue
        loc = price.index.get_loc(ts)
        if isinstance(loc, slice) or isinstance(loc, np.ndarray):
            records.append(_unlabeled(ts, row, "non_unique_timestamp", horizon_bars, fee_bps))
            continue
        future_loc = int(loc) + int(horizon_bars)
        if future_loc >= len(price):
            records.append(_unlabeled(ts, row, "missing_future_bar", horizon_bars, fee_bps))
            continue
        close_now = float(price["close"].iloc[int(loc)])
        close_future = float(price["close"].iloc[future_loc])
        if close_now <= 0.0 or close_future <= 0.0:
            records.append(_unlabeled(ts, row, "invalid_close", horizon_bars, fee_bps))
            continue
        forward = float(np.log(close_future / close_now))
        side = _direction_side(row.get("breakout_followthrough_direction"))
        directional = side * forward - fee
        records.append(
            {
                **_base_outcome(ts, row, horizon_bars, fee_bps),
                "outcome_label": "labeled",
                "outcome_reason": "ok",
                "future_timestamp": str(price.index[future_loc]),
                "forward_log_return": forward,
                "side": side,
                "directional_net_return": directional,
                "directional_positive": directional > 0.0,
                "abs_forward_log_return": abs(forward),
            }
        )
    return records


def render_breakout_followthrough_markdown(report: Mapping[str, Any]) -> str:
    """Render the 7F refinement report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7F Breakout Follow-Through Refinement",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Rows: {summary.get('row_count', 0)}",
        f"- Eligible rows: {summary.get('eligible_count', 0)} ({summary.get('eligible_rate')})",
        f"- Active rows: {summary.get('active_count', 0)} ({summary.get('active_rate')})",
        f"- Avg follow-through score: {summary.get('avg_followthrough_score')}",
        f"- Avg active score: {summary.get('avg_active_score')}",
        "",
        "## Distributions",
        "",
    ]
    for key in ("base_state_distribution", "refined_state_distribution", "reason_distribution", "direction_distribution"):
        lines.append(f"### {key}")
        values = dict(summary.get(key, {}))
        if not values:
            lines.append("- none")
        else:
            for name, count in values.items():
                lines.append(f"- {name}: {count}")
        lines.append("")
    lines.append("## Recent active rows")
    lines.append("")
    for row in report.get("recent_active", []):
        lines.append(
            "- {timestamp}: direction={direction}, score={score}, base={base}, reason={reason}".format(
                timestamp=row.get("timestamp"),
                direction=row.get("direction"),
                score=row.get("score"),
                base=row.get("base_state"),
                reason=row.get("reason"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_breakout_followthrough_outcome_markdown(matrix: Mapping[str, Any]) -> str:
    """Render directional 7F outcome matrix."""
    summary = dict(matrix.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7F Breakout Follow-Through Outcomes",
        "",
        "## Summary",
        "",
        f"- Cells: {summary.get('cell_count', 0)}",
        f"- Best cell: {summary.get('best_cell')}",
        f"- Worst cell: {summary.get('worst_cell')}",
        f"- Passing cells: {summary.get('passing_cell_count')}",
        "",
        "## Cells",
        "",
        "| Horizon | Fee | Count | Avg directional | Positive rate | Avg raw forward |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in matrix.get("cells", []):
        lines.append(
            "| {h} | {f} | {n} | {avg} | {pos} | {raw} |".format(
                h=cell.get("horizon_bars"),
                f=cell.get("fee_bps"),
                n=cell.get("labeled_count"),
                avg=cell.get("avg_directional_net_return"),
                pos=cell.get("directional_positive_rate"),
                raw=cell.get("avg_forward_log_return"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _followthrough_features(
    analysis_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    breakout_window: int,
    hold_bars: int,
    follow_bars: int,
) -> pd.DataFrame:
    price = _prepare_ohlcv(ohlcv)
    close = price["close"].astype(float)
    high = price["high"].astype(float)
    low = price["low"].astype(float)
    volume = price["volume"].astype(float)
    min_periods = max(1, min(5, int(breakout_window)))
    prior_high = high.shift(1).rolling(breakout_window, min_periods=min_periods).max()
    prior_low = low.shift(1).rolling(breakout_window, min_periods=min_periods).min()
    rolling_range = (prior_high - prior_low).replace(0.0, np.nan)

    up_break = ((close - prior_high) / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    down_break = ((prior_low - close) / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    direction = np.where(up_break > down_break, "up", np.where(down_break > up_break, "down", "none"))

    lr = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    up_follow = (lr > 0.0).astype(float).rolling(follow_bars, min_periods=1).mean()
    down_follow = (lr < 0.0).astype(float).rolling(follow_bars, min_periods=1).mean()
    signed_return_sum = lr.rolling(follow_bars, min_periods=1).sum()
    direction_return = pd.Series(np.where(direction == "up", signed_return_sum, np.where(direction == "down", -signed_return_sum, 0.0)), index=price.index)
    direction_return_score = (direction_return / 0.01).clip(0.0, 1.0)
    follow_score = pd.Series(np.where(direction == "up", up_follow, np.where(direction == "down", down_follow, 0.0)), index=price.index).astype(float)

    up_hold = (close > prior_high).astype(float).rolling(hold_bars, min_periods=1).mean()
    down_hold = (close < prior_low).astype(float).rolling(hold_bars, min_periods=1).mean()
    hold_score = pd.Series(np.where(direction == "up", up_hold, np.where(direction == "down", down_hold, 0.0)), index=price.index).astype(float)

    reversal_score = pd.Series(np.where(direction == "up", (lr < 0.0).astype(float), np.where(direction == "down", (lr > 0.0).astype(float), 1.0)), index=price.index)
    reversal_penalty = reversal_score.rolling(follow_bars, min_periods=1).mean().clip(0.0, 1.0)
    volume_score = _volume_score(volume, breakout_window)
    displacement = _analysis_series(analysis_df, "displacement_breakout_score", price.index, default=0.0)
    retest = _analysis_series(analysis_df, "policy_retest_breakout_score", price.index, default=None)
    if retest is None:
        retest = _analysis_series(analysis_df, "post_breakout_retest_score", price.index, default=0.0)
    false_risk = _analysis_series(analysis_df, "false_breakout_risk", price.index, default=1.0)
    shock_risk = _analysis_series(analysis_df, "shock_risk", price.index, default=1.0)

    raw = (
        0.26 * displacement
        + 0.22 * follow_score
        + 0.18 * direction_return_score
        + 0.16 * hold_score
        + 0.10 * retest
        + 0.08 * volume_score
    )
    penalty = (0.55 * false_risk + 0.25 * shock_risk + 0.35 * reversal_penalty).clip(0.0, 0.85)
    score = (raw * (1.0 - penalty)).clip(0.0, 1.0)
    return pd.DataFrame(
        {
            "breakout_followthrough_score": score.astype(float),
            "breakout_followthrough_direction": direction,
            "breakout_followthrough_follow_score": follow_score.astype(float),
            "breakout_followthrough_direction_return_score": direction_return_score.astype(float),
            "breakout_followthrough_hold_score": hold_score.astype(float),
            "breakout_followthrough_reversal_penalty": reversal_penalty.astype(float),
            "breakout_followthrough_volume_score": volume_score.astype(float),
            "breakout_followthrough_false_risk": false_risk.astype(float),
            "breakout_followthrough_shock_risk": shock_risk.astype(float),
        },
        index=price.index,
    )


def _refined_row(
    row: Mapping[str, Any],
    *,
    min_followthrough_score: float,
    max_false_breakout_risk: float,
    max_shock_risk: float,
) -> dict[str, Any]:
    base = str(row.get("playbook_state") or "")
    eligible = base in _ELIGIBLE_STATES
    score = _float(row.get("breakout_followthrough_score"))
    direction = str(row.get("breakout_followthrough_direction") or "none")
    false_risk = _float(row.get("breakout_followthrough_false_risk"), 1.0)
    shock_risk = _float(row.get("breakout_followthrough_shock_risk"), 1.0)
    active = (
        eligible
        and direction in {"up", "down"}
        and score >= min_followthrough_score
        and false_risk <= max_false_breakout_risk
        and shock_risk <= max_shock_risk
    )
    reason = _reason(
        eligible=eligible,
        direction=direction,
        score=score,
        false_risk=false_risk,
        shock_risk=shock_risk,
        min_followthrough_score=min_followthrough_score,
        max_false_breakout_risk=max_false_breakout_risk,
        max_shock_risk=max_shock_risk,
    )
    out = dict(row)
    out["playbook_state_base"] = base
    out["playbook_state"] = _CONFIRMATION_STATE if active else base
    out["playbook_state_group"] = "executable" if active else row.get("playbook_state_group")
    out["playbook_state_reason"] = "breakout_followthrough_confirmed" if active else row.get("playbook_state_reason")
    out["playbook_state_is_executable"] = bool(active or row.get("playbook_state_is_executable", False))
    out["playbook_state_is_wait"] = False if active else bool(row.get("playbook_state_is_wait", False))
    out["playbook_state_dominant_playbook"] = "breakout" if active else row.get("playbook_state_dominant_playbook")
    out["breakout_followthrough_eligible"] = bool(eligible)
    out["breakout_followthrough_active"] = bool(active)
    out["breakout_followthrough_reason"] = reason
    return out


def _cell(records: list[dict[str, Any]], *, horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    labeled = [row for row in records if row.get("outcome_label") == "labeled"]
    unlabeled = [row for row in records if row.get("outcome_label") != "labeled"]
    return {
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "total_records": len(records),
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "unlabeled_reasons": dict(sorted(Counter(str(row.get("outcome_reason")) for row in unlabeled).items())),
        "avg_directional_net_return": _mean(row.get("directional_net_return") for row in labeled),
        "directional_positive_rate": _rate(sum(1 for row in labeled if bool(row.get("directional_positive"))), len(labeled)),
        "avg_forward_log_return": _mean(row.get("forward_log_return") for row in labeled),
        "avg_abs_forward_log_return": _mean(row.get("abs_forward_log_return") for row in labeled),
        "direction_distribution": dict(Counter(str(row.get("breakout_followthrough_direction")) for row in labeled).most_common()),
    }


def _matrix_summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cell_count": len(cells),
        "best_cell": _rank_cell(cells, reverse=True),
        "worst_cell": _rank_cell(cells, reverse=False),
        "passing_cell_count": sum(1 for cell in cells if (cell.get("avg_directional_net_return") is not None and float(cell.get("avg_directional_net_return")) > 0.0 and float(cell.get("directional_positive_rate") or 0.0) >= 0.50)),
    }


def _rank_cell(cells: list[dict[str, Any]], *, reverse: bool) -> dict[str, Any] | None:
    rows = [
        {
            "horizon_bars": cell.get("horizon_bars"),
            "fee_bps": cell.get("fee_bps"),
            "count": cell.get("labeled_count"),
            "avg_directional_net_return": cell.get("avg_directional_net_return"),
            "directional_positive_rate": cell.get("directional_positive_rate"),
        }
        for cell in cells
        if cell.get("avg_directional_net_return") is not None
    ]
    if not rows:
        return None
    return sorted(rows, key=lambda row: float(row.get("avg_directional_net_return") or 0.0), reverse=reverse)[0]


def _base_outcome(ts: Any, row: Mapping[str, Any], horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    return {
        "timestamp": str(ts),
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "breakout_followthrough_direction": row.get("breakout_followthrough_direction"),
        "breakout_followthrough_score": row.get("breakout_followthrough_score"),
        "playbook_state_base": row.get("playbook_state_base"),
        "playbook_state": row.get("playbook_state"),
    }


def _unlabeled(ts: Any, row: Mapping[str, Any], reason: str, horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    return {**_base_outcome(ts, row, horizon_bars, fee_bps), "outcome_label": "unlabeled", "outcome_reason": reason}


def _reason(*, eligible: bool, direction: str, score: float, false_risk: float, shock_risk: float, min_followthrough_score: float, max_false_breakout_risk: float, max_shock_risk: float) -> str:
    if not eligible:
        return "not_eligible_state"
    if direction not in {"up", "down"}:
        return "missing_break_direction"
    if score < min_followthrough_score:
        return "score_below_threshold"
    if false_risk > max_false_breakout_risk:
        return "false_breakout_risk_high"
    if shock_risk > max_shock_risk:
        return "shock_risk_high"
    return "confirmed"


def _prepare_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    if "timestamp" in frame.columns:
        frame = frame.set_index("timestamp")
    frame = frame.sort_index()
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _analysis_series(analysis_df: pd.DataFrame, column: str, index: pd.Index, *, default: float | None) -> pd.Series | None:
    if column not in analysis_df.columns:
        if default is None:
            return None
        return pd.Series(float(default), index=index)
    return pd.to_numeric(analysis_df[column], errors="coerce").reindex(index).fillna(float(default or 0.0))


def _volume_score(volume: pd.Series, window: int) -> pd.Series:
    min_periods = max(1, min(5, int(window)))
    baseline = volume.rolling(window, min_periods=min_periods).median().replace(0.0, np.nan)
    ratio = (volume / baseline).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    return ((ratio - 1.0) / 1.5).clip(0.0, 1.0)


def _direction_side(direction: Any) -> int:
    if str(direction) == "up":
        return 1
    if str(direction) == "down":
        return -1
    return 0


def _recent_active(frame: pd.DataFrame, *, limit: int = 12) -> list[dict[str, Any]]:
    rows = []
    active = frame[frame["breakout_followthrough_active"] == True].tail(limit)
    for idx, row in active.iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "direction": row.get("breakout_followthrough_direction"),
                "score": row.get("breakout_followthrough_score"),
                "base_state": row.get("playbook_state_base"),
                "reason": row.get("breakout_followthrough_reason"),
            }
        )
    return rows


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in series.fillna("missing").tolist()).most_common())


def _mean(values) -> float | None:
    nums = []
    for value in values:
        try:
            if value is not None:
                nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(nums) / len(nums) if nums else None


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "build_breakout_followthrough_frame",
    "build_breakout_followthrough_outcome_matrix",
    "build_breakout_followthrough_report",
    "label_breakout_followthrough_outcomes",
    "render_breakout_followthrough_markdown",
    "render_breakout_followthrough_outcome_markdown",
]
