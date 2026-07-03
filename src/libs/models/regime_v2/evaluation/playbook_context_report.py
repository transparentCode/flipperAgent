"""Offline report helpers for Phase 7A playbook context diagnostics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import pandas as pd


def build_playbook_context_report(
    context_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Summarize context columns produced by build_playbook_context_frame."""
    rows = int(len(context_df))
    tags = _tag_counts(context_df.get("playbook_context_conflict_tags"))
    active_count = _true_count(context_df.get("playbook_context_is_active"))
    confirmed_count = _true_count(context_df.get("playbook_context_is_confirmed"))
    return {
        "phase": "phase_7a_playbook_context_report",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "source": source,
            "row_count": rows,
            "active_context_count": active_count,
            "active_context_rate": _rate(active_count, rows),
            "confirmed_context_count": confirmed_count,
            "confirmed_context_rate": _rate(confirmed_count, rows),
            "avg_risk_score": _mean(context_df.get("playbook_context_risk_score")),
            "avg_conflict_count": _mean(context_df.get("playbook_context_conflict_count")),
            "dominant_playbook": _counts(context_df.get("playbook_context_dominant_playbook")),
            "market_phase": _counts(context_df.get("playbook_context_market_phase")),
            "risk_state": _counts(context_df.get("playbook_context_risk_state")),
            "horizon_bias": _counts(context_df.get("playbook_context_horizon_bias")),
            "context_alignment": _counts(context_df.get("playbook_context_alignment")),
            "recommended_next_step": _counts(context_df.get("playbook_context_next_step")),
            "top_conflict_tags": dict(tags.most_common(12)),
        },
        "recent_context": _recent_rows(context_df),
    }


def render_playbook_context_report_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for a Phase 7A context report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7A Playbook Context Report",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Rows: {summary.get('row_count', 0)}",
        f"- Active context rate: {summary.get('active_context_rate')}",
        f"- Confirmed context rate: {summary.get('confirmed_context_rate')}",
        f"- Average risk score: {summary.get('avg_risk_score')}",
        f"- Average conflict count: {summary.get('avg_conflict_count')}",
        "",
        "## Distributions",
        "",
    ]
    for key in (
        "dominant_playbook",
        "market_phase",
        "risk_state",
        "horizon_bias",
        "context_alignment",
        "recommended_next_step",
        "top_conflict_tags",
    ):
        lines.append(f"### {key}")
        values = dict(summary.get(key, {}))
        if not values:
            lines.append("- none")
        else:
            for name, count in values.items():
                lines.append(f"- {name}: {count}")
        lines.append("")
    lines.append("## Recent context")
    lines.append("")
    for row in report.get("recent_context", []):
        lines.append(
            "- {timestamp}: phase={phase}, playbook={playbook}, risk={risk}, horizon={horizon}, next={next_step}".format(
                timestamp=row.get("timestamp"),
                phase=row.get("market_phase"),
                playbook=row.get("dominant_playbook"),
                risk=row.get("risk_state"),
                horizon=row.get("horizon_bias"),
                next_step=row.get("recommended_next_step"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    values = [str(value) for value in series.fillna("missing").tolist()]
    return dict(Counter(values).most_common())


def _tag_counts(series: pd.Series | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    if series is None:
        return counter
    for value in series.fillna("").tolist():
        for tag in str(value).split(";"):
            tag = tag.strip()
            if tag:
                counter[tag] += 1
    return counter


def _recent_rows(context_df: pd.DataFrame, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = []
    for idx, row in context_df.tail(limit).iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "market_phase": row.get("playbook_context_market_phase"),
                "dominant_playbook": row.get("playbook_context_dominant_playbook"),
                "risk_state": row.get("playbook_context_risk_state"),
                "horizon_bias": row.get("playbook_context_horizon_bias"),
                "recommended_next_step": row.get("playbook_context_next_step"),
                "conflict_tags": row.get("playbook_context_conflict_tags"),
            }
        )
    return rows


def _true_count(series: pd.Series | None) -> int:
    if series is None:
        return 0
    return int(sum(bool(value) for value in series.fillna(False).tolist()))


def _mean(series: pd.Series | None) -> float | None:
    if series is None or len(series) == 0:
        return None
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    return float(numeric.mean())


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = ["build_playbook_context_report", "render_playbook_context_report_markdown"]
