"""Phase 7P setup-origin transition candidates.

7O created a separate transition-state layer, but it still depended on active
7F confirmations. 7P expands the search one step earlier: gated compression and
breakout-setup rows can emit a separate transition candidate when price-action
features show failed expansion, wick rejection, or reclaim pressure.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_context_gate import apply_ft_context_gate
from libs.models.regime_v2.evaluation.playbook_ft_wf import build_ft_walkforward_report
from libs.models.regime_v2.evaluation.playbook_transition_state import (
    STATE_BREAKOUT_EXHAUSTION_TRANSITION,
    STATE_FAILED_BREAKOUT_REVERSAL_SETUP,
    STATE_NO_TRANSITION,
    build_breakout_transition_outcome_matrix,
)

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)


def build_setup_transition_candidate_frame(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    lookback_bars: int = 12,
    min_candidate_score: float = 0.62,
    min_context_score: float = 0.70,
    max_risk_score: float = 0.72,
    max_conflict_count: int = 1,
    min_wick_score: float = 0.35,
    min_attempt_score: float = 0.50,
) -> pd.DataFrame:
    """Build setup-origin transition candidates in the 7O transition namespace."""
    gated = apply_ft_context_gate(
        analysis_df,
        context_df,
        state_df,
        min_context_score=float(min_context_score),
        max_risk_score=float(max_risk_score),
        max_conflict_count=int(max_conflict_count),
    )
    prices = _price_features(ohlcv, lookback_bars=int(lookback_bars))
    frame = gated.join(prices, how="left")
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        item = dict(row)
        scores = _setup_scores(item)
        active, direction, state, reason = _resolve_candidate(
            item,
            scores=scores,
            min_candidate_score=float(min_candidate_score),
            min_wick_score=float(min_wick_score),
            min_attempt_score=float(min_attempt_score),
        )
        item["breakout_transition_state"] = state
        item["breakout_transition_active"] = bool(active)
        item["breakout_transition_direction"] = direction if active else "none"
        item["breakout_transition_original_direction"] = _attempt_direction(item)
        item["breakout_transition_reason"] = reason
        item["breakout_transition_score"] = scores["candidate_score"]
        item["breakout_transition_continuation_score"] = scores["continuation_score"]
        item["breakout_transition_exhaustion_score"] = scores["exhaustion_score"]
        item["breakout_transition_failure_score"] = scores["failure_score"]
        item["breakout_transition_edge"] = scores["candidate_score"] - scores["continuation_score"]
        item["setup_transition_up_score"] = scores["up_score"]
        item["setup_transition_down_score"] = scores["down_score"]
        rows.append(item)
    out = pd.DataFrame(rows, index=frame.index)
    return _as_validation_frame(out)


def build_setup_transition_candidate_report(
    candidate_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize 7P setup-origin transition candidates."""
    frame = candidate_df.copy()
    active = frame[frame["breakout_transition_active"] == True]
    return {
        "phase": "phase_7p_setup_transition_candidates",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "row_count": int(len(frame)),
            "active_count": int(len(active)),
            "active_rate": _rate(len(active), len(frame)),
            "avg_candidate_score": _mean(frame.get("breakout_transition_score")),
            "avg_active_candidate_score": _mean(active.get("breakout_transition_score")) if len(active) else None,
            "state_distribution": _counts(frame.get("breakout_transition_state")),
            "reason_distribution": _counts(frame.get("breakout_transition_reason")),
            "direction_distribution": _counts(active.get("breakout_transition_direction")) if len(active) else {},
            "market_phase_distribution": _counts(active.get("ft_context_gate_market_phase")) if len(active) else {},
            "config": dict(config or {}),
        },
        "recent_active": _rows(active.tail(12)),
    }


def build_setup_transition_retest_report(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    split_count: int = 4,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    min_split_support: int = 2,
    min_passing_rate: float = 0.60,
    min_avg_return: float = 0.0,
    max_worst_loss: float = 0.0010,
    lookback_bars: int = 12,
    min_candidate_score: float = 0.62,
    min_context_score: float = 0.70,
    max_risk_score: float = 0.72,
    max_conflict_count: int = 1,
    min_wick_score: float = 0.35,
    min_attempt_score: float = 0.50,
) -> dict[str, Any]:
    """Run 7P setup transition candidates through outcome + WF validation."""
    config = {
        "lookback_bars": int(lookback_bars),
        "min_candidate_score": float(min_candidate_score),
        "min_context_score": float(min_context_score),
        "max_risk_score": float(max_risk_score),
        "max_conflict_count": int(max_conflict_count),
        "min_wick_score": float(min_wick_score),
        "min_attempt_score": float(min_attempt_score),
    }
    candidates = build_setup_transition_candidate_frame(
        analysis_df,
        context_df,
        state_df,
        ohlcv,
        **config,
    )
    report = build_setup_transition_candidate_report(candidates, asset=asset, timeframe=timeframe, config=config)
    outcome_matrix = build_breakout_transition_outcome_matrix(
        candidates,
        ohlcv,
        horizons=tuple(int(h) for h in horizons),
        fees_bps=tuple(float(f) for f in fees_bps),
    )
    walkforward = build_ft_walkforward_report(
        candidates,
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        threshold=float(min_candidate_score),
        split_count=int(split_count),
        horizons=tuple(int(h) for h in horizons),
        fees_bps=tuple(float(f) for f in fees_bps),
        min_split_support=int(min_split_support),
        min_passing_rate=float(min_passing_rate),
        min_avg_return=float(min_avg_return),
        max_worst_loss=float(max_worst_loss),
    )
    return {
        "phase": "phase_7p_setup_transition_retest",
        "summary": _summary(report, walkforward, outcome_matrix),
        "candidate_report": report,
        "outcome_matrix": outcome_matrix,
        "walkforward_report": walkforward,
    }


def build_setup_transition_matrix_report(retest_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize 7P setup-transition sweeps."""
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
        "phase": "phase_7p_setup_transition_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "assets": sorted({str(row.get("asset")) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_ready_setup_transition" if ready else "hold_off_setup_transition_unstable",
        },
        "variants": variants,
    }


def render_setup_transition_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for 7P reports."""
    if report.get("phase") == "phase_7p_setup_transition_matrix":
        return _render_matrix(report)
    summary = dict(report.get("summary", {}))
    return "\n".join(
        [
            "# RegimeV2 Phase 7P Setup Transition Retest",
            "",
            f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
            f"- Active candidates: {summary.get('active_count')}",
            f"- Splits passed: {summary.get('passed_split_count')}/{summary.get('split_count')}",
            f"- Ready: {summary.get('ready')}",
            "",
        ]
    )


def _price_features(ohlcv: pd.DataFrame, *, lookback_bars: int) -> pd.DataFrame:
    frame = ohlcv.copy().sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    rng = (frame["high"] - frame["low"]).replace(0.0, np.nan)
    upper_wick = (frame["high"] - frame[["open", "close"]].max(axis=1)) / rng
    lower_wick = (frame[["open", "close"]].min(axis=1) - frame["low"]) / rng
    prev_high = frame["high"].rolling(lookback_bars, min_periods=max(2, lookback_bars // 2)).max().shift(1)
    prev_low = frame["low"].rolling(lookback_bars, min_periods=max(2, lookback_bars // 2)).min().shift(1)
    band = (prev_high - prev_low).replace(0.0, np.nan)
    range_pos = (frame["close"] - prev_low) / band
    log_ret = np.log(frame["close"] / frame["close"].shift(lookback_bars)).replace([np.inf, -np.inf], np.nan)
    vol = np.log(frame["high"] / frame["low"]).rolling(lookback_bars, min_periods=max(2, lookback_bars // 2)).mean().replace(0.0, np.nan)
    mom_z = (log_ret / vol).replace([np.inf, -np.inf], np.nan)
    out = pd.DataFrame(index=frame.index)
    out["setup_transition_upper_wick"] = upper_wick.clip(0.0, 1.0).fillna(0.0)
    out["setup_transition_lower_wick"] = lower_wick.clip(0.0, 1.0).fillna(0.0)
    out["setup_transition_up_attempt"] = (frame["high"] >= prev_high).astype(float).fillna(0.0)
    out["setup_transition_down_attempt"] = (frame["low"] <= prev_low).astype(float).fillna(0.0)
    out["setup_transition_range_pos"] = range_pos.clip(0.0, 1.0).fillna(0.5)
    out["setup_transition_momentum_z"] = mom_z.clip(-3.0, 3.0).fillna(0.0)
    out["setup_transition_volatility"] = vol.fillna(0.0)
    return out


def _setup_scores(row: Mapping[str, Any]) -> dict[str, float]:
    upper = _float(row.get("setup_transition_upper_wick"))
    lower = _float(row.get("setup_transition_lower_wick"))
    up_attempt = _float(row.get("setup_transition_up_attempt"))
    down_attempt = _float(row.get("setup_transition_down_attempt"))
    range_pos = _float(row.get("setup_transition_range_pos"), 0.5)
    mom = _float(row.get("setup_transition_momentum_z"))
    context = _float(row.get("ft_context_gate_score"))
    phase = str(row.get("ft_context_gate_market_phase") or "")
    phase_bonus = 1.0 if phase in {"compressed_wait", "breakout_setup"} else 0.45
    up_score = 0.30 * lower + 0.22 * down_attempt + 0.18 * _clip(-mom / 2.0) + 0.14 * (1.0 - range_pos) + 0.10 * context + 0.06 * phase_bonus
    down_score = 0.30 * upper + 0.22 * up_attempt + 0.18 * _clip(mom / 2.0) + 0.14 * range_pos + 0.10 * context + 0.06 * phase_bonus
    candidate = max(up_score, down_score)
    continuation = 0.35 * max(up_attempt, down_attempt) + 0.25 * abs(_clip(mom / 2.0) - _clip(-mom / 2.0)) + 0.20 * (1.0 - max(upper, lower)) + 0.20 * context
    return {
        "up_score": round(_clip(up_score), 6),
        "down_score": round(_clip(down_score), 6),
        "candidate_score": round(_clip(candidate), 6),
        "continuation_score": round(_clip(continuation), 6),
        "exhaustion_score": round(_clip(candidate), 6),
        "failure_score": round(_clip(0.60 * candidate + 0.40 * max(up_attempt, down_attempt)), 6),
    }


def _resolve_candidate(
    row: Mapping[str, Any],
    *,
    scores: Mapping[str, float],
    min_candidate_score: float,
    min_wick_score: float,
    min_attempt_score: float,
) -> tuple[bool, str, str, str]:
    if not bool(row.get("ft_context_gate_active", False)):
        return False, "none", STATE_NO_TRANSITION, "context_gate_inactive"
    state = str(row.get("playbook_state") or "")
    if state not in {"WAIT_COMPRESSION", "BREAKOUT_SETUP", "OBSERVE_ONLY"}:
        return False, "none", STATE_NO_TRANSITION, "not_setup_state"
    up_score = float(scores.get("up_score") or 0.0)
    down_score = float(scores.get("down_score") or 0.0)
    if max(up_score, down_score) < min_candidate_score:
        return False, "none", STATE_NO_TRANSITION, "candidate_score_low"
    if up_score >= down_score:
        if _float(row.get("setup_transition_lower_wick")) < min_wick_score and _float(row.get("setup_transition_down_attempt")) < min_attempt_score:
            return False, "none", STATE_NO_TRANSITION, "weak_up_reversal_evidence"
        subtype = STATE_FAILED_BREAKOUT_REVERSAL_SETUP if _float(row.get("setup_transition_down_attempt")) >= min_attempt_score else STATE_BREAKOUT_EXHAUSTION_TRANSITION
        return True, "up", subtype, "setup_failed_downside_reversal"
    if _float(row.get("setup_transition_upper_wick")) < min_wick_score and _float(row.get("setup_transition_up_attempt")) < min_attempt_score:
        return False, "none", STATE_NO_TRANSITION, "weak_down_reversal_evidence"
    subtype = STATE_FAILED_BREAKOUT_REVERSAL_SETUP if _float(row.get("setup_transition_up_attempt")) >= min_attempt_score else STATE_BREAKOUT_EXHAUSTION_TRANSITION
    return True, "down", subtype, "setup_failed_upside_reversal"


def _attempt_direction(row: Mapping[str, Any]) -> str:
    if _float(row.get("setup_transition_up_attempt")) > _float(row.get("setup_transition_down_attempt")):
        return "up"
    if _float(row.get("setup_transition_down_attempt")) > _float(row.get("setup_transition_up_attempt")):
        return "down"
    return "none"


def _as_validation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["breakout_followthrough_active"] = out["breakout_transition_active"].astype(bool)
    out["breakout_followthrough_direction"] = out["breakout_transition_direction"]
    out["breakout_followthrough_score"] = out["breakout_transition_score"]
    out["playbook_state_base"] = out["breakout_transition_state"]
    out["playbook_state"] = out["breakout_transition_state"]
    return out


def _summary(report: Mapping[str, Any], walkforward: Mapping[str, Any], outcome_matrix: Mapping[str, Any]) -> dict[str, Any]:
    rs = dict(report.get("summary", {}))
    ws = dict(walkforward.get("summary", {}))
    ms = dict(outcome_matrix.get("summary", {}))
    return {
        "asset": rs.get("asset"),
        "timeframe": rs.get("timeframe"),
        "active_count": rs.get("active_count"),
        "state_distribution": rs.get("state_distribution"),
        "direction_distribution": rs.get("direction_distribution"),
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
    candidate_summary = dict(dict(report.get("candidate_report", {})).get("summary", {}))
    return {
        **summary,
        "recent_active": list(dict(report.get("candidate_report", {})).get("recent_active", [])),
        "reason_distribution": candidate_summary.get("reason_distribution", {}),
        "market_phase_distribution": candidate_summary.get("market_phase_distribution", {}),
        "config": candidate_summary.get("config", {}),
        "splits": list(dict(report.get("walkforward_report", {})).get("splits", [])),
    }


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "active_count": row.get("active_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
    }


def _render_matrix(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7P Setup Transition Matrix",
        "",
        f"- Variants: {s.get('variant_count', 0)}",
        f"- Ready variants: {s.get('ready_variant_count', 0)}",
        f"- Recommendation: {s.get('recommendation')}",
        f"- Best variant: {s.get('best_variant')}",
        "",
        "| Asset | Active | Passed | Avg split dir | Worst split dir | Ready |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {asset} | {active} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
                asset=row.get("asset"),
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


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "state": row.get("breakout_transition_state"),
                "direction": row.get("breakout_transition_direction"),
                "attempt_direction": row.get("breakout_transition_original_direction"),
                "score": row.get("breakout_transition_score"),
                "up_score": row.get("setup_transition_up_score"),
                "down_score": row.get("setup_transition_down_score"),
                "reason": row.get("breakout_transition_reason"),
            }
        )
    return rows


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in series.fillna("missing").tolist()).most_common())


def _mean(series: pd.Series | None) -> float | None:
    if series is None or len(series) == 0:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else None


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
    "build_setup_transition_candidate_frame",
    "build_setup_transition_candidate_report",
    "build_setup_transition_matrix_report",
    "build_setup_transition_retest_report",
    "render_setup_transition_markdown",
]
