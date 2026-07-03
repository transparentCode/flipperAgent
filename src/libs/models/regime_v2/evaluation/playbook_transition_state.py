"""Phase 7O separate breakout transition-state prototype.

7L/7N showed that rewriting the direction of ``BREAKOUT_CONFIRMATION`` is too
fragile. 7O keeps breakout follow-through intact and emits a separate offline
transition-state layer with its own validation path.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import build_breakout_followthrough_frame
from libs.models.regime_v2.evaluation.playbook_ft_context_gate import apply_ft_context_gate
from libs.models.regime_v2.evaluation.playbook_ft_wf import build_ft_walkforward_report

STATE_NO_TRANSITION = "NO_BREAKOUT_TRANSITION"
STATE_BREAKOUT_EXHAUSTION_TRANSITION = "BREAKOUT_EXHAUSTION_TRANSITION"
STATE_FAILED_BREAKOUT_REVERSAL_SETUP = "FAILED_BREAKOUT_REVERSAL_SETUP"
_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)


def build_breakout_transition_state_frame(
    refined_state_df: pd.DataFrame,
    *,
    min_transition_score: float = 0.58,
    min_reversal_penalty: float = 0.60,
    max_continuation_score: float = 0.78,
    min_context_score: float = 0.70,
    transition_directions: Sequence[str] = ("up", "down"),
) -> pd.DataFrame:
    """Return a separate transition-state frame from 7F refined states.

    This does not mutate ``playbook_state`` or ``breakout_followthrough_*``. It
    adds a parallel ``breakout_transition_*`` namespace used only by offline
    diagnostics and outcome validation.
    """
    frame = refined_state_df.copy()
    if frame.empty:
        return _ensure_columns(frame)
    directions = {str(value).lower() for value in transition_directions}
    rows = []
    for _, row in frame.iterrows():
        item = dict(row)
        scores = _scores(item)
        active, state, reason = _resolve_transition_state(
            item,
            scores=scores,
            directions=directions,
            min_transition_score=float(min_transition_score),
            min_reversal_penalty=float(min_reversal_penalty),
            max_continuation_score=float(max_continuation_score),
            min_context_score=float(min_context_score),
        )
        original_direction = str(item.get("breakout_followthrough_direction") or "none").lower()
        item["breakout_transition_state"] = state
        item["breakout_transition_active"] = bool(active)
        item["breakout_transition_direction"] = _opposite_direction(original_direction) if active else "none"
        item["breakout_transition_original_direction"] = original_direction
        item["breakout_transition_reason"] = reason
        item["breakout_transition_score"] = scores["transition_score"]
        item["breakout_transition_continuation_score"] = scores["continuation_score"]
        item["breakout_transition_exhaustion_score"] = scores["exhaustion_score"]
        item["breakout_transition_failure_score"] = scores["failure_score"]
        item["breakout_transition_edge"] = scores["transition_score"] - scores["continuation_score"]
        rows.append(item)
    return pd.DataFrame(rows, index=frame.index)


def build_breakout_transition_state_report(
    transition_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize the separate 7O transition-state layer."""
    frame = _ensure_columns(transition_df.copy())
    active = frame[frame["breakout_transition_active"] == True]
    return {
        "phase": "phase_7o_breakout_transition_state",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "threshold": threshold,
            "row_count": int(len(frame)),
            "active_count": int(len(active)),
            "active_rate": _rate(len(active), len(frame)),
            "avg_transition_score": _mean(frame.get("breakout_transition_score")),
            "avg_active_transition_score": _mean(active.get("breakout_transition_score")) if len(active) else None,
            "state_distribution": _counts(frame.get("breakout_transition_state")),
            "reason_distribution": _counts(frame.get("breakout_transition_reason")),
            "transition_direction_distribution": _counts(active.get("breakout_transition_direction")) if len(active) else {},
            "original_direction_distribution": _counts(active.get("breakout_transition_original_direction")) if len(active) else {},
            "config": dict(config or {}),
        },
        "recent_active": _rows(active.tail(12)),
    }


def build_breakout_transition_outcome_matrix(
    transition_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
) -> dict[str, Any]:
    """Evaluate active transition states with their own transition direction."""
    cells = []
    for horizon in horizons:
        for fee in fees_bps:
            records = label_breakout_transition_outcomes(
                transition_df,
                ohlcv,
                horizon_bars=int(horizon),
                fee_bps=float(fee),
            )
            cells.append(_cell(records, horizon_bars=int(horizon), fee_bps=float(fee)))
    return {
        "phase": "phase_7o_breakout_transition_outcome_matrix",
        "summary": _matrix_summary(cells),
        "cells": cells,
    }


def label_breakout_transition_outcomes(
    transition_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizon_bars: int,
    fee_bps: float,
) -> list[dict[str, Any]]:
    """Label active 7O transition states with directional net returns."""
    price = _prepare_ohlcv(ohlcv)
    fee = float(fee_bps) / 10000.0
    records = []
    frame = _ensure_columns(transition_df.copy())
    active = frame[frame["breakout_transition_active"] == True]
    for ts, row in active.iterrows():
        if ts not in price.index:
            records.append(_unlabeled(ts, row, horizon_bars, fee_bps, "timestamp_not_in_ohlcv"))
            continue
        loc = price.index.get_loc(ts)
        if isinstance(loc, slice) or isinstance(loc, np.ndarray):
            records.append(_unlabeled(ts, row, horizon_bars, fee_bps, "non_unique_timestamp"))
            continue
        future_loc = int(loc) + int(horizon_bars)
        if future_loc >= len(price):
            records.append(_unlabeled(ts, row, horizon_bars, fee_bps, "missing_future_bar"))
            continue
        close_now = float(price["close"].iloc[int(loc)])
        close_future = float(price["close"].iloc[future_loc])
        if close_now <= 0.0 or close_future <= 0.0:
            records.append(_unlabeled(ts, row, horizon_bars, fee_bps, "invalid_close"))
            continue
        forward = float(np.log(close_future / close_now))
        side = _direction_side(row.get("breakout_transition_direction"))
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


def build_breakout_transition_state_retest_report(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    split_count: int = 4,
    breakout_window: int = 20,
    hold_bars: int = 2,
    follow_bars: int = 3,
    max_false_breakout_risk: float = 0.65,
    max_shock_risk: float = 0.80,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    min_split_support: int = 2,
    min_passing_rate: float = 0.60,
    min_avg_return: float = 0.0,
    max_worst_loss: float = 0.0010,
    gate_min_context_score: float = 0.70,
    gate_max_risk_score: float = 0.72,
    gate_max_conflict_count: int = 1,
    min_transition_score: float = 0.58,
    min_reversal_penalty: float = 0.60,
    max_continuation_score: float = 0.78,
    min_transition_context_score: float = 0.70,
) -> dict[str, Any]:
    """Run 7K -> 7F -> 7O separate transition-state retest."""
    gated = apply_ft_context_gate(
        analysis_df,
        context_df,
        state_df,
        min_context_score=float(gate_min_context_score),
        max_risk_score=float(gate_max_risk_score),
        max_conflict_count=int(gate_max_conflict_count),
    )
    refined = build_breakout_followthrough_frame(
        analysis_df,
        gated,
        ohlcv,
        breakout_window=int(breakout_window),
        hold_bars=int(hold_bars),
        follow_bars=int(follow_bars),
        min_followthrough_score=float(threshold or 0.0),
        max_false_breakout_risk=float(max_false_breakout_risk),
        max_shock_risk=float(max_shock_risk),
    )
    config = {
        "gate_min_context_score": float(gate_min_context_score),
        "gate_max_risk_score": float(gate_max_risk_score),
        "gate_max_conflict_count": int(gate_max_conflict_count),
        "min_transition_score": float(min_transition_score),
        "min_reversal_penalty": float(min_reversal_penalty),
        "max_continuation_score": float(max_continuation_score),
        "min_transition_context_score": float(min_transition_context_score),
    }
    transition = build_breakout_transition_state_frame(
        refined,
        min_transition_score=float(min_transition_score),
        min_reversal_penalty=float(min_reversal_penalty),
        max_continuation_score=float(max_continuation_score),
        min_context_score=float(min_transition_context_score),
    )
    state_report = build_breakout_transition_state_report(
        transition,
        asset=asset,
        timeframe=timeframe,
        threshold=threshold,
        config=config,
    )
    outcome_matrix = build_breakout_transition_outcome_matrix(
        transition,
        ohlcv,
        horizons=tuple(int(h) for h in horizons),
        fees_bps=tuple(float(f) for f in fees_bps),
    )
    wf_frame = _as_followthrough_validation_frame(transition)
    walkforward = build_ft_walkforward_report(
        wf_frame,
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        threshold=threshold,
        split_count=int(split_count),
        horizons=tuple(int(h) for h in horizons),
        fees_bps=tuple(float(f) for f in fees_bps),
        min_split_support=int(min_split_support),
        min_passing_rate=float(min_passing_rate),
        min_avg_return=float(min_avg_return),
        max_worst_loss=float(max_worst_loss),
    )
    return {
        "phase": "phase_7o_breakout_transition_state_retest",
        "summary": _variant_summary(state_report, walkforward, outcome_matrix),
        "transition_state_report": state_report,
        "outcome_matrix": outcome_matrix,
        "walkforward_report": walkforward,
    }


def build_breakout_transition_state_matrix_report(retest_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize 7O transition-state retests."""
    variants = [_variant_row(report) for report in retest_reports]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            int(row.get("active_count") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7o_breakout_transition_state_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "thresholds": sorted({float(row.get("threshold") or 0.0) for row in variants}),
            "assets": sorted({str(row.get("asset")) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_ready_transition_state" if ready else "hold_off_transition_state_unstable",
        },
        "variants": variants,
    }


def render_breakout_transition_state_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for 7O reports."""
    if report.get("phase") == "phase_7o_breakout_transition_state_matrix":
        return _render_matrix(report)
    return _render_retest(report)


def _scores(row: Mapping[str, Any]) -> dict[str, float]:
    follow = _float(row.get("breakout_followthrough_follow_score"))
    hold = _float(row.get("breakout_followthrough_hold_score"))
    ret = _float(row.get("breakout_followthrough_direction_return_score"))
    reversal = _float(row.get("breakout_followthrough_reversal_penalty"))
    false_risk = _float(row.get("breakout_followthrough_false_risk"))
    shock = _float(row.get("breakout_followthrough_shock_risk"))
    context = _float(row.get("ft_context_gate_score"))
    phase = str(row.get("ft_context_gate_market_phase") or "")
    horizon = str(row.get("ft_context_gate_horizon_bias") or "")
    phase_bonus = 1.0 if phase in {"compressed_wait", "breakout_setup"} else 0.35
    horizon_bonus = 1.0 if horizon == "wait_for_expansion" else 0.70 if horizon in {"mid", "short_to_mid"} else 0.35
    continuation = 0.30 * follow + 0.26 * hold + 0.26 * ret + 0.12 * (1.0 - reversal) + 0.06 * context
    exhaustion = 0.34 * reversal + 0.20 * (1.0 - ret) + 0.16 * (1.0 - hold) + 0.10 * phase_bonus + 0.08 * horizon_bonus + 0.06 * context + 0.06 * (1.0 - shock)
    failure = 0.30 * reversal + 0.20 * (1.0 - hold) + 0.16 * (1.0 - follow) + 0.14 * (1.0 - ret) + 0.08 * false_risk + 0.06 * phase_bonus + 0.06 * context
    transition = max(exhaustion, failure)
    return {
        "continuation_score": round(_clip(continuation), 6),
        "exhaustion_score": round(_clip(exhaustion), 6),
        "failure_score": round(_clip(failure), 6),
        "transition_score": round(_clip(transition), 6),
    }


def _resolve_transition_state(
    row: Mapping[str, Any],
    *,
    scores: Mapping[str, float],
    directions: set[str],
    min_transition_score: float,
    min_reversal_penalty: float,
    max_continuation_score: float,
    min_context_score: float,
) -> tuple[bool, str, str]:
    if not bool(row.get("breakout_followthrough_active", False)):
        return False, STATE_NO_TRANSITION, "inactive"
    direction = str(row.get("breakout_followthrough_direction") or "none").lower()
    if direction not in directions:
        return False, STATE_NO_TRANSITION, "direction_not_targeted"
    if _float(row.get("ft_context_gate_score")) < min_context_score:
        return False, STATE_NO_TRANSITION, "context_score_low"
    if _float(row.get("breakout_followthrough_reversal_penalty")) < min_reversal_penalty:
        return False, STATE_NO_TRANSITION, "reversal_penalty_low"
    if float(scores.get("continuation_score") or 0.0) > max_continuation_score:
        return False, STATE_NO_TRANSITION, "continuation_too_strong"
    if float(scores.get("transition_score") or 0.0) < min_transition_score:
        return False, STATE_NO_TRANSITION, "transition_score_low"
    if float(scores.get("failure_score") or 0.0) >= float(scores.get("exhaustion_score") or 0.0):
        return True, STATE_FAILED_BREAKOUT_REVERSAL_SETUP, "failed_breakout_reversal_setup"
    return True, STATE_BREAKOUT_EXHAUSTION_TRANSITION, "breakout_exhaustion_transition"


def _as_followthrough_validation_frame(transition_df: pd.DataFrame) -> pd.DataFrame:
    frame = transition_df.copy()
    frame["breakout_followthrough_active"] = frame["breakout_transition_active"].astype(bool)
    frame["breakout_followthrough_direction"] = frame["breakout_transition_direction"]
    frame["breakout_followthrough_score"] = frame["breakout_transition_score"]
    frame["playbook_state_base"] = frame["breakout_transition_state"]
    frame["playbook_state"] = frame["breakout_transition_state"]
    return frame


def _variant_summary(state_report: Mapping[str, Any], walkforward: Mapping[str, Any], outcome_matrix: Mapping[str, Any]) -> dict[str, Any]:
    ss = dict(state_report.get("summary", {}))
    ws = dict(walkforward.get("summary", {}))
    ms = dict(outcome_matrix.get("summary", {}))
    return {
        "asset": ss.get("asset"),
        "timeframe": ss.get("timeframe"),
        "threshold": ss.get("threshold"),
        "active_count": ss.get("active_count"),
        "state_distribution": ss.get("state_distribution"),
        "passed_split_count": ws.get("passed_split_count"),
        "split_count": ws.get("split_count"),
        "ready": ws.get("ready"),
        "recommendation": ws.get("recommendation"),
        "avg_split_directional_return": ws.get("avg_split_directional_return"),
        "worst_split_directional_return": ws.get("worst_split_directional_return"),
        "passing_cell_count": ms.get("passing_cell_count"),
    }


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    state_summary = dict(dict(report.get("transition_state_report", {})).get("summary", {}))
    return {
        **summary,
        "recent_active": list(dict(report.get("transition_state_report", {})).get("recent_active", [])),
        "reason_distribution": state_summary.get("reason_distribution", {}),
        "transition_direction_distribution": state_summary.get("transition_direction_distribution", {}),
        "splits": list(dict(report.get("walkforward_report", {})).get("splits", [])),
        "config": state_summary.get("config", {}),
    }


def _cell(records: list[dict[str, Any]], *, horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    labeled = [row for row in records if row.get("outcome_label") == "labeled"]
    unlabeled = [row for row in records if row.get("outcome_label") != "labeled"]
    return {
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "total_records": len(records),
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "unlabeled_reasons": dict(Counter(str(row.get("outcome_reason")) for row in unlabeled).most_common()),
        "avg_directional_net_return": _mean(row.get("directional_net_return") for row in labeled),
        "directional_positive_rate": _rate(sum(1 for row in labeled if bool(row.get("directional_positive"))), len(labeled)),
        "avg_forward_log_return": _mean(row.get("forward_log_return") for row in labeled),
        "direction_distribution": dict(Counter(str(row.get("breakout_transition_direction")) for row in labeled).most_common()),
        "state_distribution": dict(Counter(str(row.get("breakout_transition_state")) for row in labeled).most_common()),
    }


def _matrix_summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cell_count": len(cells),
        "passing_cell_count": sum(1 for cell in cells if cell.get("avg_directional_net_return") is not None and float(cell.get("avg_directional_net_return") or 0.0) > 0.0 and float(cell.get("directional_positive_rate") or 0.0) >= 0.50),
        "best_cell": _rank_cell(cells, reverse=True),
        "worst_cell": _rank_cell(cells, reverse=False),
    }


def _rank_cell(cells: list[dict[str, Any]], *, reverse: bool) -> dict[str, Any] | None:
    valid = [cell for cell in cells if cell.get("avg_directional_net_return") is not None]
    if not valid:
        return None
    cell = sorted(valid, key=lambda item: float(item.get("avg_directional_net_return") or 0.0), reverse=reverse)[0]
    return {
        "horizon_bars": cell.get("horizon_bars"),
        "fee_bps": cell.get("fee_bps"),
        "count": cell.get("labeled_count"),
        "avg_directional_net_return": cell.get("avg_directional_net_return"),
        "directional_positive_rate": cell.get("directional_positive_rate"),
    }


def _base_outcome(ts: Any, row: Mapping[str, Any], horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    return {
        "timestamp": str(ts),
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "breakout_transition_state": row.get("breakout_transition_state"),
        "breakout_transition_direction": row.get("breakout_transition_direction"),
        "breakout_transition_original_direction": row.get("breakout_transition_original_direction"),
        "breakout_transition_score": row.get("breakout_transition_score"),
    }


def _unlabeled(ts: Any, row: Mapping[str, Any], horizon_bars: int, fee_bps: float, reason: str) -> dict[str, Any]:
    return {**_base_outcome(ts, row, horizon_bars, fee_bps), "outcome_label": "unlabeled", "outcome_reason": reason}


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "state": row.get("breakout_transition_state"),
                "direction": row.get("breakout_transition_direction"),
                "original_direction": row.get("breakout_transition_original_direction"),
                "score": row.get("breakout_transition_score"),
                "continuation_score": row.get("breakout_transition_continuation_score"),
                "exhaustion_score": row.get("breakout_transition_exhaustion_score"),
                "failure_score": row.get("breakout_transition_failure_score"),
                "reason": row.get("breakout_transition_reason"),
            }
        )
    return rows


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "threshold": row.get("threshold"),
        "active_count": row.get("active_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
    }


def _render_retest(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    return "\n".join(
        [
            "# RegimeV2 Phase 7O Breakout Transition-State Retest",
            "",
            f"- Asset/timeframe: {s.get('asset')}|{s.get('timeframe')}",
            f"- Threshold: {s.get('threshold')}",
            f"- Active transition states: {s.get('active_count')}",
            f"- Splits passed: {s.get('passed_split_count')}/{s.get('split_count')}",
            f"- Ready: {s.get('ready')}",
            "",
        ]
    )


def _render_matrix(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7O Breakout Transition-State Matrix",
        "",
        f"- Variants: {s.get('variant_count', 0)}",
        f"- Ready variants: {s.get('ready_variant_count', 0)}",
        f"- Recommendation: {s.get('recommendation')}",
        f"- Best variant: {s.get('best_variant')}",
        "",
        "| Asset | Threshold | Active | Passed | Avg split dir | Worst split dir | Ready |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {asset} | {thr} | {active} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
                asset=row.get("asset"),
                thr=row.get("threshold"),
                active=row.get("active_count"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
                ready=row.get("ready"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _ensure_columns(frame: pd.DataFrame) -> pd.DataFrame:
    defaults: dict[str, Any] = {
        "breakout_transition_state": STATE_NO_TRANSITION,
        "breakout_transition_active": False,
        "breakout_transition_direction": "none",
        "breakout_transition_original_direction": "none",
        "breakout_transition_reason": "inactive",
        "breakout_transition_score": 0.0,
        "breakout_transition_continuation_score": 0.0,
        "breakout_transition_exhaustion_score": 0.0,
        "breakout_transition_failure_score": 0.0,
        "breakout_transition_edge": 0.0,
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    return frame


def _prepare_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    if "timestamp" in frame.columns:
        frame = frame.set_index("timestamp")
    frame = frame.sort_index()
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _opposite_direction(direction: str) -> str:
    if direction == "up":
        return "down"
    if direction == "down":
        return "up"
    return "none"


def _direction_side(direction: Any) -> int:
    if str(direction) == "up":
        return 1
    if str(direction) == "down":
        return -1
    return 0


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


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "STATE_BREAKOUT_EXHAUSTION_TRANSITION",
    "STATE_FAILED_BREAKOUT_REVERSAL_SETUP",
    "STATE_NO_TRANSITION",
    "build_breakout_transition_outcome_matrix",
    "build_breakout_transition_state_frame",
    "build_breakout_transition_state_matrix_report",
    "build_breakout_transition_state_report",
    "build_breakout_transition_state_retest_report",
    "label_breakout_transition_outcomes",
    "render_breakout_transition_state_markdown",
]
