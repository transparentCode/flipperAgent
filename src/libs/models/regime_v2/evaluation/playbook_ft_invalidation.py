"""Offline invalidation/cooldown filter for Phase 7J follow-through retests.

Phase 7I showed that the Phase 7F follow-through candidate still leaks failed
windows with direction-specific losses, weak long-horizon continuation, and high
reversal pressure. This module stays offline-only and applies a deterministic
post-confirmation invalidation layer before rerunning the Phase 7H walk-forward
checks.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_wf import build_ft_walkforward_report

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)
_EXECUTABLE_STATE = "BREAKOUT_CONFIRMATION"
_WAIT_STATES = {"WAIT_COMPRESSION"}
_SETUP_STATES = {"BREAKOUT_SETUP"}


def apply_ft_invalidation_filter(
    refined_state_df: pd.DataFrame,
    *,
    min_hold_score: float = 0.50,
    min_follow_score: float = 0.50,
    min_direction_return_score: float = 0.40,
    max_reversal_penalty: float = 0.35,
    cooldown_bars: int = 3,
    cooldown_by_direction: bool = True,
    blocked_directions: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Deactivate 7F rows that fail deterministic invalidation/cooldown checks.

    The filter consumes only columns already emitted by Phase 7F, so it is safe
    to run as an offline retest layer without changing the live playbook state
    machine. Active rows can be removed for three reasons:

    - direct invalidation: weak hold/follow/directional-return or high reversal;
    - direction block: optional explicit direction blacklist for diagnostics;
    - cooldown: suppress clustered confirmations after an invalidated row.
    """
    frame = refined_state_df.copy()
    if frame.empty:
        return _ensure_columns(frame)

    blocked = {str(value).lower() for value in (blocked_directions or []) if str(value).strip()}
    cooldowns: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        item = dict(row)
        original_active = bool(item.get("breakout_followthrough_active", False))
        direction = str(item.get("breakout_followthrough_direction") or "none").lower()
        cooldown_key = direction if cooldown_by_direction else "__all__"
        cooldown_active = int(cooldowns.get(cooldown_key, 0)) > 0 or int(cooldowns.get("__all__", 0)) > 0
        tags = _invalidation_tags(
            item,
            direction=direction,
            blocked=blocked,
            min_hold_score=float(min_hold_score),
            min_follow_score=float(min_follow_score),
            min_direction_return_score=float(min_direction_return_score),
            max_reversal_penalty=float(max_reversal_penalty),
        )

        invalidated = bool(original_active and tags)
        cooldown_suppressed = bool(original_active and not invalidated and cooldown_active)
        active = bool(original_active and not invalidated and not cooldown_suppressed)
        reason = "active" if active else str(item.get("breakout_followthrough_reason") or "inactive")
        if invalidated:
            reason = "+".join(tags)
        elif cooldown_suppressed:
            reason = "cooldown_suppressed"

        item["breakout_followthrough_pre_invalidation_active"] = original_active
        item["breakout_followthrough_active"] = active
        item["breakout_followthrough_post_invalidation_active"] = active
        item["breakout_followthrough_invalidated"] = invalidated
        item["breakout_followthrough_cooldown_suppressed"] = cooldown_suppressed
        item["breakout_followthrough_invalidation_reason"] = reason
        item["breakout_followthrough_invalidation_tags"] = tags
        item["breakout_followthrough_cooldown_key"] = cooldown_key if (invalidated or cooldown_suppressed) else None
        if not active and original_active:
            _restore_base_state(item)
        rows.append(item)

        cooldowns = {key: max(0, value - 1) for key, value in cooldowns.items() if value - 1 > 0}
        if invalidated and int(cooldown_bars) > 0:
            cooldowns[cooldown_key] = max(int(cooldowns.get(cooldown_key, 0)), int(cooldown_bars))
    return pd.DataFrame(rows, index=frame.index)


def build_ft_invalidation_report(
    filtered_state_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize the Phase 7J invalidation layer."""
    frame = _ensure_columns(filtered_state_df.copy())
    rows = int(len(frame))
    before = frame[frame["breakout_followthrough_pre_invalidation_active"] == True]
    after = frame[frame["breakout_followthrough_active"] == True]
    invalidated = frame[frame["breakout_followthrough_invalidated"] == True]
    cooldown = frame[frame["breakout_followthrough_cooldown_suppressed"] == True]
    removed = frame[(frame["breakout_followthrough_pre_invalidation_active"] == True) & (frame["breakout_followthrough_active"] != True)]
    return {
        "phase": "phase_7j_ft_invalidation_filter",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "threshold": threshold,
            "row_count": rows,
            "active_before": int(len(before)),
            "active_after": int(len(after)),
            "removed_count": int(len(removed)),
            "invalidated_count": int(len(invalidated)),
            "cooldown_suppressed_count": int(len(cooldown)),
            "active_reduction_rate": _rate(len(removed), len(before)),
            "reason_distribution": _counts(frame.get("breakout_followthrough_invalidation_reason")),
            "direction_distribution_before": _counts(before.get("breakout_followthrough_direction")) if len(before) else {},
            "direction_distribution_after": _counts(after.get("breakout_followthrough_direction")) if len(after) else {},
            "config": dict(config or {}),
        },
        "recent_removed": _recent_removed(removed),
    }


def build_ft_invalidation_retest_report(
    refined_state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    split_count: int = 4,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    min_split_support: int = 2,
    min_passing_rate: float = 0.60,
    min_avg_return: float = 0.0,
    max_worst_loss: float = 0.0010,
    min_hold_score: float = 0.50,
    min_follow_score: float = 0.50,
    min_direction_return_score: float = 0.40,
    max_reversal_penalty: float = 0.35,
    cooldown_bars: int = 3,
    cooldown_by_direction: bool = True,
    blocked_directions: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Apply Phase 7J filtering and rerun Phase 7H walk-forward validation."""
    config = {
        "min_hold_score": float(min_hold_score),
        "min_follow_score": float(min_follow_score),
        "min_direction_return_score": float(min_direction_return_score),
        "max_reversal_penalty": float(max_reversal_penalty),
        "cooldown_bars": int(cooldown_bars),
        "cooldown_by_direction": bool(cooldown_by_direction),
        "blocked_directions": [str(value) for value in (blocked_directions or [])],
    }
    filtered = apply_ft_invalidation_filter(refined_state_df, **config)
    invalidation = build_ft_invalidation_report(
        filtered,
        asset=asset,
        timeframe=timeframe,
        threshold=threshold,
        config=config,
    )
    walkforward = build_ft_walkforward_report(
        filtered,
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
        "phase": "phase_7j_ft_invalidation_retest",
        "summary": _variant_summary(invalidation, walkforward),
        "invalidation_report": invalidation,
        "walkforward_report": walkforward,
    }


def build_ft_invalidation_matrix_report(retest_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize Phase 7J invalidation retests across thresholds/configs."""
    variants = [_variant_row(report) for report in retest_reports]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            int(row.get("active_after") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7j_ft_invalidation_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "thresholds": sorted({float(row.get("threshold") or 0.0) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_ready_after_invalidation" if ready else "hold_off_invalidation_unstable",
        },
        "variants": variants,
    }


def render_ft_invalidation_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for Phase 7J invalidation reports."""
    if report.get("phase") == "phase_7j_ft_invalidation_matrix":
        return _render_matrix(report)
    if report.get("phase") == "phase_7j_ft_invalidation_retest":
        return _render_retest(report)
    return _render_filter(report)


def _invalidation_tags(
    row: Mapping[str, Any],
    *,
    direction: str,
    blocked: set[str],
    min_hold_score: float,
    min_follow_score: float,
    min_direction_return_score: float,
    max_reversal_penalty: float,
) -> list[str]:
    tags: list[str] = []
    if direction in blocked:
        tags.append(f"blocked_direction:{direction}")
    if _float(row.get("breakout_followthrough_hold_score"), 1.0) < min_hold_score:
        tags.append("weak_boundary_hold")
    if _float(row.get("breakout_followthrough_follow_score"), 1.0) < min_follow_score:
        tags.append("weak_followthrough")
    if _float(row.get("breakout_followthrough_direction_return_score"), 1.0) < min_direction_return_score:
        tags.append("weak_directional_return_score")
    if _float(row.get("breakout_followthrough_reversal_penalty"), 0.0) > max_reversal_penalty:
        tags.append("high_reversal_pressure")
    return tags


def _restore_base_state(item: dict[str, Any]) -> None:
    base = str(item.get("playbook_state_base") or item.get("playbook_state") or "")
    item["playbook_state"] = base
    item["playbook_state_is_executable"] = False
    item["playbook_state_is_wait"] = base in _WAIT_STATES
    if base in _WAIT_STATES:
        item["playbook_state_group"] = "wait"
    elif base in _SETUP_STATES:
        item["playbook_state_group"] = "setup"
    elif item.get("playbook_state_group") == "executable" and base != _EXECUTABLE_STATE:
        item["playbook_state_group"] = "inactive"
    item["playbook_state_reason"] = "breakout_followthrough_invalidated"


def _ensure_columns(frame: pd.DataFrame) -> pd.DataFrame:
    defaults: dict[str, Any] = {
        "breakout_followthrough_pre_invalidation_active": False,
        "breakout_followthrough_post_invalidation_active": False,
        "breakout_followthrough_invalidated": False,
        "breakout_followthrough_cooldown_suppressed": False,
        "breakout_followthrough_invalidation_reason": "inactive",
        "breakout_followthrough_direction": "none",
        "breakout_followthrough_active": False,
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    return frame


def _variant_summary(invalidation: Mapping[str, Any], walkforward: Mapping[str, Any]) -> dict[str, Any]:
    inv = dict(invalidation.get("summary", {}))
    wf = dict(walkforward.get("summary", {}))
    return {
        "asset": inv.get("asset"),
        "timeframe": inv.get("timeframe"),
        "threshold": inv.get("threshold"),
        "active_before": inv.get("active_before"),
        "active_after": inv.get("active_after"),
        "removed_count": inv.get("removed_count"),
        "invalidated_count": inv.get("invalidated_count"),
        "cooldown_suppressed_count": inv.get("cooldown_suppressed_count"),
        "passed_split_count": wf.get("passed_split_count"),
        "split_count": wf.get("split_count"),
        "ready": wf.get("ready"),
        "recommendation": wf.get("recommendation"),
        "avg_split_directional_return": wf.get("avg_split_directional_return"),
        "worst_split_directional_return": wf.get("worst_split_directional_return"),
    }


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    inv = dict(dict(report.get("invalidation_report", {})).get("summary", {}))
    wf = dict(dict(report.get("walkforward_report", {})).get("summary", {}))
    return {
        **summary,
        "reason_distribution": inv.get("reason_distribution", {}),
        "direction_distribution_after": inv.get("direction_distribution_after", {}),
        "failure_reasons": _aggregate_failure_reasons(dict(report.get("walkforward_report", {})).get("splits", [])),
        "splits": list(dict(report.get("walkforward_report", {})).get("splits", [])),
        "config": inv.get("config", {}),
        "support_failure_count": wf.get("support_failure_count"),
        "negative_failure_count": wf.get("negative_failure_count"),
    }


def _aggregate_failure_reasons(splits: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for split in splits:
        counter.update(str(reason) for reason in split.get("failure_reasons", []))
    return dict(counter.most_common())


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "threshold": row.get("threshold"),
        "active_before": row.get("active_before"),
        "active_after": row.get("active_after"),
        "removed_count": row.get("removed_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
    }


def _recent_removed(frame: pd.DataFrame, *, limit: int = 12) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.tail(limit).iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "direction": row.get("breakout_followthrough_direction"),
                "score": row.get("breakout_followthrough_score"),
                "base_state": row.get("playbook_state_base"),
                "reason": row.get("breakout_followthrough_invalidation_reason"),
            }
        )
    return rows


def _render_filter(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7J Follow-Through Invalidation Filter",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Threshold: {summary.get('threshold')}",
        f"- Active before/after: {summary.get('active_before')}/{summary.get('active_after')}",
        f"- Removed: {summary.get('removed_count')}",
        f"- Invalidated: {summary.get('invalidated_count')}",
        f"- Cooldown suppressed: {summary.get('cooldown_suppressed_count')}",
        "",
        "## Reason distribution",
        "",
    ]
    for reason, count in dict(summary.get("reason_distribution", {})).items():
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "## Recent removed", ""])
    for row in report.get("recent_removed", []):
        lines.append(
            "- {timestamp}: direction={direction}, score={score}, reason={reason}".format(
                timestamp=row.get("timestamp"),
                direction=row.get("direction"),
                score=row.get("score"),
                reason=row.get("reason"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_retest(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7J Follow-Through Invalidation Retest",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Threshold: {summary.get('threshold')}",
        f"- Active before/after: {summary.get('active_before')}/{summary.get('active_after')}",
        f"- Removed: {summary.get('removed_count')}",
        f"- Splits passed: {summary.get('passed_split_count')}/{summary.get('split_count')}",
        f"- Ready: {summary.get('ready')}",
        f"- Recommendation: {summary.get('recommendation')}",
        "",
    ]
    return "\n".join(lines)


def _render_matrix(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7J Follow-Through Invalidation Matrix",
        "",
        "## Summary",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Ready variants: {summary.get('ready_variant_count', 0)}",
        f"- Thresholds: {summary.get('thresholds', [])}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        f"- Best ready variant: {summary.get('best_ready_variant')}",
        "",
        "## Variants",
        "",
        "| Threshold | Active before | Active after | Removed | Passed | Avg split dir | Worst split dir | Ready |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {thr} | {before} | {after} | {removed} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
                thr=row.get("threshold"),
                before=row.get("active_before"),
                after=row.get("active_after"),
                removed=row.get("removed_count"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
                ready=row.get("ready"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in series.fillna("missing").tolist()).most_common())


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
    "apply_ft_invalidation_filter",
    "build_ft_invalidation_matrix_report",
    "build_ft_invalidation_report",
    "build_ft_invalidation_retest_report",
    "render_ft_invalidation_markdown",
]
