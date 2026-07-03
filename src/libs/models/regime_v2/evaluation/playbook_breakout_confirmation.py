"""Offline breakout-confirmation refinement for RegimeV2 Phase 7E.

This module refines Phase 7B states by promoting eligible breakout setup/wait
rows into BREAKOUT_CONFIRMATION when deterministic confirmation evidence is
present. It is diagnostic-only and does not change RegimePolicy or selection.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import numpy as np
import pandas as pd

_CONFIRMATION_STATE = "BREAKOUT_CONFIRMATION"
_ELIGIBLE_STATES = {"BREAKOUT_SETUP", "WAIT_COMPRESSION"}


def build_breakout_confirmation_frame(
    analysis_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    breakout_window: int = 20,
    hold_bars: int = 2,
    min_confirmation_score: float = 0.55,
    max_false_breakout_risk: float = 0.55,
    max_shock_risk: float = 0.80,
) -> pd.DataFrame:
    """Return a refined state dataframe with breakout confirmation columns."""
    features = _confirmation_features(
        analysis_df,
        ohlcv,
        breakout_window=int(breakout_window),
        hold_bars=int(hold_bars),
    )
    out = state_df.copy()
    joined = out.join(features, how="left")
    rows = []
    for _, row in joined.iterrows():
        rows.append(
            _refined_row(
                row,
                min_confirmation_score=float(min_confirmation_score),
                max_false_breakout_risk=float(max_false_breakout_risk),
                max_shock_risk=float(max_shock_risk),
            )
        )
    refined = pd.DataFrame(rows, index=joined.index)
    return refined


def build_breakout_confirmation_report(
    refined_state_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Summarize breakout-confirmation refinement output."""
    rows = int(len(refined_state_df))
    confirmed = refined_state_df[refined_state_df["breakout_confirmation_active"] == True]
    promoted = refined_state_df[refined_state_df["breakout_confirmation_promoted"] == True]
    eligible = refined_state_df[refined_state_df["breakout_confirmation_eligible"] == True]
    return {
        "phase": "phase_7e_breakout_confirmation_refinement",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "source": source,
            "row_count": rows,
            "eligible_count": int(len(eligible)),
            "eligible_rate": _rate(len(eligible), rows),
            "confirmation_count": int(len(confirmed)),
            "confirmation_rate": _rate(len(confirmed), rows),
            "promoted_count": int(len(promoted)),
            "promoted_rate": _rate(len(promoted), rows),
            "avg_confirmation_score": _mean(refined_state_df.get("breakout_confirmation_score")),
            "avg_confirmed_score": _mean(confirmed.get("breakout_confirmation_score")) if len(confirmed) else None,
            "base_state_distribution": _counts(refined_state_df.get("playbook_state_base")),
            "refined_state_distribution": _counts(refined_state_df.get("playbook_state")),
            "confirmation_reason_distribution": _counts(refined_state_df.get("breakout_confirmation_reason")),
            "confirmation_direction_distribution": _counts(confirmed.get("breakout_confirmation_direction")) if len(confirmed) else {},
        },
        "recent_confirmations": _recent_confirmations(refined_state_df),
    }


def render_breakout_confirmation_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for the Phase 7E refinement report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7E Breakout Confirmation Refinement",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Rows: {summary.get('row_count', 0)}",
        f"- Eligible rows: {summary.get('eligible_count', 0)} ({summary.get('eligible_rate')})",
        f"- Confirmed rows: {summary.get('confirmation_count', 0)} ({summary.get('confirmation_rate')})",
        f"- Promoted rows: {summary.get('promoted_count', 0)} ({summary.get('promoted_rate')})",
        f"- Avg confirmation score: {summary.get('avg_confirmation_score')}",
        f"- Avg confirmed score: {summary.get('avg_confirmed_score')}",
        "",
        "## Distributions",
        "",
    ]
    for key in (
        "base_state_distribution",
        "refined_state_distribution",
        "confirmation_reason_distribution",
        "confirmation_direction_distribution",
    ):
        lines.append(f"### {key}")
        values = dict(summary.get(key, {}))
        if not values:
            lines.append("- none")
        else:
            for name, count in values.items():
                lines.append(f"- {name}: {count}")
        lines.append("")
    lines.append("## Recent confirmations")
    lines.append("")
    for row in report.get("recent_confirmations", []):
        lines.append(
            "- {timestamp}: direction={direction}, score={score}, base={base}, refined={state}, reason={reason}".format(
                timestamp=row.get("timestamp"),
                direction=row.get("direction"),
                score=row.get("score"),
                base=row.get("base_state"),
                state=row.get("refined_state"),
                reason=row.get("reason"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _confirmation_features(analysis_df: pd.DataFrame, ohlcv: pd.DataFrame, *, breakout_window: int, hold_bars: int) -> pd.DataFrame:
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

    up_hold = _hold_score(close > prior_high, hold_bars)
    down_hold = _hold_score(close < prior_low, hold_bars)
    hold = np.where(direction == "up", up_hold, np.where(direction == "down", down_hold, 0.0))
    follow_through = _follow_through_score(close, direction)
    volume_expansion = _volume_expansion_score(volume, breakout_window)
    range_expansion = _analysis_series(analysis_df, "range_expansion_z", price.index, default=0.0)
    range_score = (range_expansion / 2.0).clip(0.0, 1.0)
    displacement = _analysis_series(analysis_df, "displacement_breakout_score", price.index, default=0.0)
    retest = _analysis_series(analysis_df, "policy_retest_breakout_score", price.index, default=None)
    if retest is None:
        retest = _analysis_series(analysis_df, "post_breakout_retest_score", price.index, default=0.0)
    false_risk = _analysis_series(analysis_df, "false_breakout_risk", price.index, default=1.0)
    shock_risk = _analysis_series(analysis_df, "shock_risk", price.index, default=1.0)

    raw = (
        0.30 * displacement
        + 0.18 * pd.Series(hold, index=price.index)
        + 0.18 * pd.Series(follow_through, index=price.index)
        + 0.14 * volume_expansion
        + 0.12 * range_score
        + 0.08 * retest
    )
    penalty = (0.45 * false_risk + 0.25 * shock_risk).clip(0.0, 0.70)
    score = (raw * (1.0 - penalty)).clip(0.0, 1.0)
    return pd.DataFrame(
        {
            "breakout_confirmation_score": score.astype(float),
            "breakout_confirmation_direction": direction,
            "breakout_confirmation_hold_score": pd.Series(hold, index=price.index).astype(float),
            "breakout_confirmation_follow_score": pd.Series(follow_through, index=price.index).astype(float),
            "breakout_confirmation_volume_score": volume_expansion.astype(float),
            "breakout_confirmation_range_score": range_score.astype(float),
            "breakout_confirmation_false_risk": false_risk.astype(float),
            "breakout_confirmation_shock_risk": shock_risk.astype(float),
        },
        index=price.index,
    )


def _refined_row(row: Mapping[str, Any], *, min_confirmation_score: float, max_false_breakout_risk: float, max_shock_risk: float) -> dict[str, Any]:
    base = str(row.get("playbook_state") or "")
    eligible = base in _ELIGIBLE_STATES
    score = _float(row.get("breakout_confirmation_score"))
    false_risk = _float(row.get("breakout_confirmation_false_risk"), 1.0)
    shock_risk = _float(row.get("breakout_confirmation_shock_risk"), 1.0)
    direction = str(row.get("breakout_confirmation_direction") or "none")
    active = (
        eligible
        and score >= min_confirmation_score
        and false_risk <= max_false_breakout_risk
        and shock_risk <= max_shock_risk
        and direction in {"up", "down"}
    )
    reason = _reason(
        eligible=eligible,
        score=score,
        false_risk=false_risk,
        shock_risk=shock_risk,
        direction=direction,
        min_confirmation_score=min_confirmation_score,
        max_false_breakout_risk=max_false_breakout_risk,
        max_shock_risk=max_shock_risk,
    )
    out = dict(row)
    out["playbook_state_base"] = base
    out["playbook_state"] = _CONFIRMATION_STATE if active else base
    out["playbook_state_group"] = "executable" if active else row.get("playbook_state_group")
    out["playbook_state_reason"] = "breakout_confirmed" if active else row.get("playbook_state_reason")
    out["playbook_state_is_executable"] = bool(active or row.get("playbook_state_is_executable", False))
    out["playbook_state_is_wait"] = False if active else bool(row.get("playbook_state_is_wait", False))
    out["playbook_state_dominant_playbook"] = "breakout" if active else row.get("playbook_state_dominant_playbook")
    out["breakout_confirmation_eligible"] = bool(eligible)
    out["breakout_confirmation_active"] = bool(active)
    out["breakout_confirmation_promoted"] = bool(active and base != _CONFIRMATION_STATE)
    out["breakout_confirmation_reason"] = reason
    return out


def _reason(*, eligible: bool, score: float, false_risk: float, shock_risk: float, direction: str, min_confirmation_score: float, max_false_breakout_risk: float, max_shock_risk: float) -> str:
    if not eligible:
        return "not_eligible_state"
    if direction not in {"up", "down"}:
        return "missing_break_direction"
    if score < min_confirmation_score:
        return "score_below_threshold"
    if false_risk > max_false_breakout_risk:
        return "false_breakout_risk_high"
    if shock_risk > max_shock_risk:
        return "shock_risk_high"
    return "confirmed"


def _analysis_series(analysis_df: pd.DataFrame, column: str, index: pd.Index, *, default: float | None) -> pd.Series | None:
    if column not in analysis_df.columns:
        if default is None:
            return None
        return pd.Series(float(default), index=index)
    return pd.to_numeric(analysis_df[column], errors="coerce").reindex(index).fillna(float(default or 0.0))


def _prepare_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    if "timestamp" in frame.columns:
        frame = frame.set_index("timestamp")
    frame = frame.sort_index()
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _hold_score(condition: pd.Series, hold_bars: int) -> pd.Series:
    bars = max(1, int(hold_bars))
    return condition.astype(float).rolling(bars, min_periods=1).mean().clip(0.0, 1.0)


def _follow_through_score(close: pd.Series, direction: np.ndarray) -> np.ndarray:
    lr = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    up = (lr > 0.0).astype(float).rolling(2, min_periods=1).mean()
    down = (lr < 0.0).astype(float).rolling(2, min_periods=1).mean()
    return np.where(direction == "up", up, np.where(direction == "down", down, 0.0))


def _volume_expansion_score(volume: pd.Series, window: int) -> pd.Series:
    min_periods = max(1, min(5, int(window)))
    baseline = volume.rolling(window, min_periods=min_periods).median().replace(0.0, np.nan)
    ratio = (volume / baseline).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    return ((ratio - 1.0) / 1.5).clip(0.0, 1.0)


def _recent_confirmations(frame: pd.DataFrame, *, limit: int = 12) -> list[dict[str, Any]]:
    rows = []
    confirmed = frame[frame["breakout_confirmation_active"] == True].tail(limit)
    for idx, row in confirmed.iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "direction": row.get("breakout_confirmation_direction"),
                "score": row.get("breakout_confirmation_score"),
                "base_state": row.get("playbook_state_base"),
                "refined_state": row.get("playbook_state"),
                "reason": row.get("breakout_confirmation_reason"),
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
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else None


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
    "build_breakout_confirmation_frame",
    "build_breakout_confirmation_report",
    "render_breakout_confirmation_markdown",
]
