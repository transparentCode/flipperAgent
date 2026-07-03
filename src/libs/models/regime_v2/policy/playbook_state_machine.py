"""Offline deterministic playbook state machine for RegimeV2 Phase 7B.

The state machine consumes Phase 7A playbook context rows and turns them into a
small, explicit set of staged states. It is diagnostic-only and does not change
current RegimePolicy permissions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import pandas as pd

STATE_NO_TRADE_RISK = "NO_TRADE_RISK"
STATE_WAIT_COMPRESSION = "WAIT_COMPRESSION"
STATE_BREAKOUT_SETUP = "BREAKOUT_SETUP"
STATE_BREAKOUT_CONFIRMATION = "BREAKOUT_CONFIRMATION"
STATE_TREND_CONTINUATION = "TREND_CONTINUATION"
STATE_RANGE_REVERSION = "RANGE_REVERSION"
STATE_SCALP_ONLY = "SCALP_ONLY"
STATE_OBSERVE_ONLY = "OBSERVE_ONLY"

_EXECUTABLE_STATES = {
    STATE_BREAKOUT_CONFIRMATION,
    STATE_TREND_CONTINUATION,
    STATE_RANGE_REVERSION,
    STATE_SCALP_ONLY,
}
_WAIT_STATES = {STATE_WAIT_COMPRESSION, STATE_BREAKOUT_SETUP, STATE_OBSERVE_ONLY}
_RISK_STATES = {STATE_NO_TRADE_RISK}


def context_row_to_state(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map one Phase 7A context row to a deterministic staged state."""
    phase = _text(row.get("playbook_context_market_phase"))
    risk_state = _text(row.get("playbook_context_risk_state"))
    playbook = _text(row.get("playbook_context_dominant_playbook"))
    horizon = _text(row.get("playbook_context_horizon_bias"))
    next_step = _text(row.get("playbook_context_next_step"))
    tags = _tags(row.get("playbook_context_conflict_tags"))
    risk_score = _float(row.get("playbook_context_risk_score"))
    conflict_count = int(_float(row.get("playbook_context_conflict_count")))
    active = bool(row.get("playbook_context_is_active", False))

    state, reason = _resolve_state(
        phase=phase,
        risk_state=risk_state,
        playbook=playbook,
        horizon=horizon,
        next_step=next_step,
        tags=tags,
        active=active,
    )
    return {
        "playbook_state": state,
        "state_reason": reason,
        "state_group": _state_group(state),
        "is_executable_state": state in _EXECUTABLE_STATES,
        "is_wait_state": state in _WAIT_STATES,
        "is_risk_state": state in _RISK_STATES,
        "risk_score": round(risk_score, 4),
        "conflict_count": conflict_count,
        "conflict_tags": tuple(tags),
        "dominant_playbook": playbook,
        "market_phase": phase,
        "horizon_bias": horizon,
        "recommended_next_step": next_step,
    }


def build_playbook_state_frame(context_df: pd.DataFrame) -> pd.DataFrame:
    """Build state-machine columns for a Phase 7A context dataframe."""
    rows = []
    for _, row in context_df.iterrows():
        state = context_row_to_state(row)
        rows.append(_flatten_state(state))
    return pd.DataFrame(rows, index=context_df.index)


def build_playbook_state_report(
    state_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Summarize state-machine output."""
    rows = int(len(state_df))
    executable = _true_count(state_df.get("playbook_state_is_executable"))
    wait = _true_count(state_df.get("playbook_state_is_wait"))
    risk = _true_count(state_df.get("playbook_state_is_risk"))
    return {
        "phase": "phase_7b_playbook_state_machine_report",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "source": source,
            "row_count": rows,
            "executable_count": executable,
            "executable_rate": _rate(executable, rows),
            "wait_count": wait,
            "wait_rate": _rate(wait, rows),
            "risk_count": risk,
            "risk_rate": _rate(risk, rows),
            "state_distribution": _counts(state_df.get("playbook_state")),
            "state_group_distribution": _counts(state_df.get("playbook_state_group")),
            "reason_distribution": _counts(state_df.get("playbook_state_reason")),
            "dominant_playbook_distribution": _counts(state_df.get("playbook_state_dominant_playbook")),
            "horizon_bias_distribution": _counts(state_df.get("playbook_state_horizon_bias")),
            "avg_risk_score": _mean(state_df.get("playbook_state_risk_score")),
            "avg_conflict_count": _mean(state_df.get("playbook_state_conflict_count")),
        },
        "recent_states": _recent_rows(state_df),
    }


def render_playbook_state_report_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for a Phase 7B state-machine report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7B Playbook State Machine Report",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Rows: {summary.get('row_count', 0)}",
        f"- Executable rate: {summary.get('executable_rate')}",
        f"- Wait rate: {summary.get('wait_rate')}",
        f"- Risk/no-trade rate: {summary.get('risk_rate')}",
        f"- Average risk score: {summary.get('avg_risk_score')}",
        f"- Average conflict count: {summary.get('avg_conflict_count')}",
        "",
        "## Distributions",
        "",
    ]
    for key in (
        "state_distribution",
        "state_group_distribution",
        "reason_distribution",
        "dominant_playbook_distribution",
        "horizon_bias_distribution",
    ):
        lines.append(f"### {key}")
        values = dict(summary.get(key, {}))
        if not values:
            lines.append("- none")
        else:
            for name, count in values.items():
                lines.append(f"- {name}: {count}")
        lines.append("")
    lines.append("## Recent states")
    lines.append("")
    for row in report.get("recent_states", []):
        lines.append(
            "- {timestamp}: state={state}, reason={reason}, playbook={playbook}, horizon={horizon}".format(
                timestamp=row.get("timestamp"),
                state=row.get("state"),
                reason=row.get("reason"),
                playbook=row.get("dominant_playbook"),
                horizon=row.get("horizon_bias"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _resolve_state(
    *,
    phase: str,
    risk_state: str,
    playbook: str,
    horizon: str,
    next_step: str,
    tags: tuple[str, ...],
    active: bool,
) -> tuple[str, str]:
    if risk_state == "blocked" or phase in {"shock_no_trade", "uncertain_no_trade", "liquidity_no_trade"}:
        return STATE_NO_TRADE_RISK, "risk_blocked"
    if phase == "compressed_wait" or horizon == "wait_for_expansion" or next_step == "watch_for_breakout_expansion":
        return STATE_WAIT_COMPRESSION, "compression_wait"
    if phase == "breakout_setup":
        return STATE_BREAKOUT_SETUP, "pre_breakout_setup"
    if phase in {"displacement_breakout", "retest_breakout"}:
        if "breakout_false_break_risk" in tags or "breakout_shock_conflict" in tags:
            return STATE_BREAKOUT_SETUP, "breakout_needs_confirmation"
        return STATE_BREAKOUT_CONFIRMATION, "breakout_confirmed"
    if phase in {"bull_trend", "bear_trend"} or (playbook == "trend" and horizon in {"long", "mid_to_long"}):
        if "trend_chop_conflict" in tags:
            return STATE_OBSERVE_ONLY, "trend_chop_conflict"
        return STATE_TREND_CONTINUATION, "trend_context"
    if playbook == "mean_reversion" or phase in {"range_reversion", "range_chop"}:
        if "mean_reversion_break_risk" in tags:
            return STATE_OBSERVE_ONLY, "mean_reversion_break_risk"
        return STATE_RANGE_REVERSION, "range_reversion_context"
    if playbook == "scalping" and active and risk_state in {"ok", "watch"}:
        return STATE_SCALP_ONLY, "scalp_only_context"
    return STATE_OBSERVE_ONLY, "no_executable_context"


def _flatten_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "playbook_state": state["playbook_state"],
        "playbook_state_reason": state["state_reason"],
        "playbook_state_group": state["state_group"],
        "playbook_state_is_executable": bool(state["is_executable_state"]),
        "playbook_state_is_wait": bool(state["is_wait_state"]),
        "playbook_state_is_risk": bool(state["is_risk_state"]),
        "playbook_state_risk_score": float(state["risk_score"]),
        "playbook_state_conflict_count": int(state["conflict_count"]),
        "playbook_state_conflict_tags": ";".join(state["conflict_tags"]),
        "playbook_state_dominant_playbook": state["dominant_playbook"],
        "playbook_state_market_phase": state["market_phase"],
        "playbook_state_horizon_bias": state["horizon_bias"],
        "playbook_state_next_step": state["recommended_next_step"],
    }


def _state_group(state: str) -> str:
    if state in _RISK_STATES:
        return "risk"
    if state in _WAIT_STATES:
        return "wait"
    if state in _EXECUTABLE_STATES:
        return "executable"
    return "unknown"


def _tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value if str(item))
    return tuple(tag for tag in str(value).split(";") if tag)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return default if text.lower() == "nan" else text


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in series.fillna("missing").tolist()).most_common())


def _true_count(series: pd.Series | None) -> int:
    if series is None:
        return 0
    return int(sum(bool(value) for value in series.fillna(False).tolist()))


def _mean(series: pd.Series | None) -> float | None:
    if series is None or len(series) == 0:
        return None
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else None


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


def _recent_rows(state_df: pd.DataFrame, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = []
    for idx, row in state_df.tail(limit).iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "state": row.get("playbook_state"),
                "reason": row.get("playbook_state_reason"),
                "dominant_playbook": row.get("playbook_state_dominant_playbook"),
                "horizon_bias": row.get("playbook_state_horizon_bias"),
                "conflict_tags": row.get("playbook_state_conflict_tags"),
            }
        )
    return rows


__all__ = [
    "STATE_NO_TRADE_RISK",
    "STATE_WAIT_COMPRESSION",
    "STATE_BREAKOUT_SETUP",
    "STATE_BREAKOUT_CONFIRMATION",
    "STATE_TREND_CONTINUATION",
    "STATE_RANGE_REVERSION",
    "STATE_SCALP_ONLY",
    "STATE_OBSERVE_ONLY",
    "build_playbook_state_frame",
    "build_playbook_state_report",
    "context_row_to_state",
    "render_playbook_state_report_markdown",
]
