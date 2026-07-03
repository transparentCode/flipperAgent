"""Phase 7Y context-tag diagnostics for transition micro-state windows."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_micro_state import (
    MICRO_STATE_BREAKOUT_SETUP,
    MICRO_STATE_COMPRESSION_OBSERVE,
    build_transition_micro_state_frame,
)
from libs.models.regime_v2.evaluation.playbook_transition_micro_state_robust import build_transition_micro_state_robust_report
from libs.models.regime_v2.evaluation.playbook_transition_setup import build_setup_transition_candidate_frame

_FEATURE_COLUMNS = (
    "breakout_transition_score",
    "breakout_transition_continuation_score",
    "setup_transition_score_gap",
    "setup_transition_volatility",
)


def build_transition_micro_state_context_diag_report(
    micro_df: pd.DataFrame,
    robust_report: Mapping[str, Any],
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    min_state_active: int = 6,
    compression_share_threshold: float = 0.55,
    score_advantage_threshold: float = 0.03,
    high_quantile: float = 0.75,
    low_quantile: float = 0.25,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build policy-safe feature tags for 7W windows."""
    frame = micro_df.copy()
    active = frame[frame.get("breakout_transition_active", False) == True]
    baselines = _baselines(active, high_quantile, low_quantile)
    rows = []
    for window in robust_report.get("windows", []):
        start = int(window.get("start") or 0)
        end = int(window.get("end") or len(frame))
        rows.append(
            _window_row(
                asset,
                timeframe,
                window,
                frame.iloc[start:end],
                baselines,
                min_state_active=min_state_active,
                compression_share_threshold=compression_share_threshold,
                score_advantage_threshold=score_advantage_threshold,
            )
        )
    candidates = _candidate_tags(rows)
    return {
        "phase": "phase_7y_transition_micro_state_context_diag",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "window_count": len(rows),
            "mixed_window_count": sum(1 for row in rows if row.get("window_class") == "supported_mixed"),
            "passing_window_count": sum(1 for row in rows if row.get("window_class") == "supported_breakout"),
            "support_thin_count": sum(1 for row in rows if row.get("window_class") == "support_thin"),
            "top_candidate_tag": candidates[0] if candidates else None,
            "candidate_tag_count": len(candidates),
            "tag_distribution": _tag_counts(rows),
            "recommendation": _recommendation(candidates),
            "config": dict(config or {}),
        },
        "feature_baselines": baselines,
        "windows": rows,
        "candidate_tags": candidates,
    }


def build_transition_micro_state_context_diag_retest_report(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    window_size: int = 360,
    step_size: int = 180,
    min_state_active: int = 6,
    lookback_bars: int = 8,
    min_candidate_score: float = 0.62,
    min_context_score: float = 0.70,
    max_risk_score: float = 0.72,
    max_conflict_count: int = 1,
    min_wick_score: float = 0.35,
    min_attempt_score: float = 0.50,
) -> dict[str, Any]:
    """Rebuild micro-states and run context-tag diagnostics."""
    config = {
        "window_size": int(window_size),
        "step_size": int(step_size),
        "min_state_active": int(min_state_active),
        "lookback_bars": int(lookback_bars),
        "min_candidate_score": float(min_candidate_score),
    }
    candidates = build_setup_transition_candidate_frame(
        analysis_df,
        context_df,
        state_df,
        ohlcv,
        lookback_bars=int(lookback_bars),
        min_candidate_score=float(min_candidate_score),
        min_context_score=float(min_context_score),
        max_risk_score=float(max_risk_score),
        max_conflict_count=int(max_conflict_count),
        min_wick_score=float(min_wick_score),
        min_attempt_score=float(min_attempt_score),
    )
    micro = build_transition_micro_state_frame(candidates)
    robust = build_transition_micro_state_robust_report(
        micro,
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        window_size=int(window_size),
        step_size=int(step_size),
        min_state_active=int(min_state_active),
        config=config,
    )
    diag = build_transition_micro_state_context_diag_report(
        micro,
        robust,
        asset=asset,
        timeframe=timeframe,
        min_state_active=int(min_state_active),
        config=config,
    )
    return {"phase": "phase_7y_transition_micro_state_context_diag_retest", "summary": diag["summary"], "context_diag_report": diag}


def build_transition_micro_state_context_diag_matrix_report(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Combine 7Y reports across assets."""
    variants = [_variant_row(report) for report in reports]
    tags = _global_tags(reports)
    return {
        "phase": "phase_7y_transition_micro_state_context_diag_matrix",
        "summary": {
            "variant_count": len(variants),
            "assets": sorted({str(row.get("asset")) for row in variants}),
            "mixed_window_count": sum(int(row.get("mixed_window_count") or 0) for row in variants),
            "candidate_tag_count": len(tags),
            "top_global_candidate_tag": tags[0] if tags else None,
            "recommendation": "test_context_tag_next" if tags else "no_context_tag_found",
        },
        "variants": variants,
        "global_candidate_tags": tags,
    }


def render_transition_micro_state_context_diag_markdown(report: Mapping[str, Any]) -> str:
    """Render Phase 7Y Markdown."""
    if report.get("phase") == "phase_7y_transition_micro_state_context_diag_matrix":
        return _render_matrix(report)
    s = dict(report.get("summary", {}))
    return "\n".join(["# RegimeV2 Phase 7Y Context Tag Diagnostics", "", f"- Asset/timeframe: {s.get('asset')}|{s.get('timeframe')}", f"- Mixed windows: {s.get('mixed_window_count')}", f"- Candidate tags: {s.get('candidate_tag_count')}", f"- Top tag: {s.get('top_candidate_tag')}", f"- Recommendation: {s.get('recommendation')}", ""])


def _window_row(asset: str | None, timeframe: str | None, window: Mapping[str, Any], frame: pd.DataFrame, baselines: Mapping[str, Any], *, min_state_active: int, compression_share_threshold: float, score_advantage_threshold: float) -> dict[str, Any]:
    breakout = frame[frame.get("breakout_transition_micro_state", "") == MICRO_STATE_BREAKOUT_SETUP]
    compression = frame[frame.get("breakout_transition_micro_state", "") == MICRO_STATE_COMPRESSION_OBSERVE]
    b_count = int(len(breakout))
    c_count = int(len(compression))
    total = b_count + c_count
    support_ok = bool(window.get("support_ok"))
    better = bool(window.get("breakout_better"))
    window_class = "support_thin" if not support_ok else ("supported_breakout" if better else "supported_mixed")
    tags = []
    share = c_count / float(total) if total else 0.0
    if share >= float(compression_share_threshold):
        tags.append("compression_count_dominant")
    if b_count < int(min_state_active):
        tags.append("breakout_support_low")
    tags.extend(_state_tags("breakout", breakout, baselines, want_low=True, want_high=False))
    tags.extend(_state_tags("compression", compression, baselines, want_low=False, want_high=True))
    b_score = _mean(breakout, "breakout_transition_score")
    c_score = _mean(compression, "breakout_transition_score")
    if b_score is not None and c_score is not None and c_score - b_score >= float(score_advantage_threshold):
        tags.append("compression_score_advantage")
    return {
        "asset": asset,
        "timeframe": timeframe,
        "window_id": window.get("window_id"),
        "window_class": window_class,
        "support_ok": support_ok,
        "breakout_better": better,
        "breakout_active": b_count,
        "compression_active": c_count,
        "compression_share": share,
        "breakout_score_mean": b_score,
        "compression_score_mean": c_score,
        "tags": sorted(set(tags)),
    }


def _state_tags(prefix: str, frame: pd.DataFrame, baselines: Mapping[str, Any], *, want_low: bool, want_high: bool) -> list[str]:
    tags = []
    for col in _FEATURE_COLUMNS:
        value = _mean(frame, col)
        limits = dict(baselines.get(col, {}))
        if value is None:
            continue
        if want_low and limits.get("low") is not None and value <= float(limits["low"]):
            tags.append(f"{prefix}_{col}_low")
        if want_high and limits.get("high") is not None and value >= float(limits["high"]):
            tags.append(f"{prefix}_{col}_high")
    return tags


def _baselines(frame: pd.DataFrame, high_q: float, low_q: float) -> dict[str, dict[str, float | None]]:
    out = {}
    for col in _FEATURE_COLUMNS:
        values = pd.to_numeric(frame[col], errors="coerce").dropna() if col in frame.columns else pd.Series(dtype=float)
        out[col] = {"low": float(values.quantile(float(low_q))) if not values.empty else None, "high": float(values.quantile(float(high_q))) if not values.empty else None}
    return out


def _candidate_tags(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    mixed = [row for row in rows if row.get("window_class") == "supported_mixed"]
    passing = [row for row in rows if row.get("window_class") == "supported_breakout"]
    out = []
    for tag in sorted({tag for row in rows for tag in row.get("tags", [])}):
        mixed_hits = sum(1 for row in mixed if tag in row.get("tags", []))
        passing_hits = sum(1 for row in passing if tag in row.get("tags", []))
        if mixed_hits <= 0:
            continue
        total = mixed_hits + passing_hits
        out.append({"tag": tag, "mixed_hits": mixed_hits, "passing_hits": passing_hits, "precision": mixed_hits / float(total) if total else 0.0, "recall": mixed_hits / float(len(mixed)) if mixed else 0.0, "assets": sorted({str(row.get("asset")) for row in mixed if tag in row.get("tags", [])})})
    out.sort(key=lambda row: (float(row["precision"]), float(row["recall"]), int(row["mixed_hits"])), reverse=True)
    return out


def _global_tags(reports: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = defaultdict(lambda: {"mixed_hits": 0, "passing_hits": 0, "assets": set()})
    for report in reports:
        for row in dict(report.get("context_diag_report", {})).get("candidate_tags", []):
            item = bucket[str(row.get("tag"))]
            item["mixed_hits"] += int(row.get("mixed_hits") or 0)
            item["passing_hits"] += int(row.get("passing_hits") or 0)
            item["assets"].update(str(asset) for asset in row.get("assets", []))
    out = []
    for tag, item in bucket.items():
        total = item["mixed_hits"] + item["passing_hits"]
        out.append({"tag": tag, "mixed_hits": item["mixed_hits"], "passing_hits": item["passing_hits"], "precision": item["mixed_hits"] / float(total) if total else 0.0, "assets": sorted(item["assets"])})
    out.sort(key=lambda row: (float(row["precision"]), int(row["mixed_hits"])), reverse=True)
    return out


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    s = dict(report.get("summary", {}))
    return {"asset": s.get("asset"), "timeframe": s.get("timeframe"), "mixed_window_count": s.get("mixed_window_count"), "passing_window_count": s.get("passing_window_count"), "support_thin_count": s.get("support_thin_count"), "top_candidate_tag": s.get("top_candidate_tag"), "candidate_tag_count": s.get("candidate_tag_count"), "recommendation": s.get("recommendation")}


def _recommendation(tags: Sequence[Mapping[str, Any]]) -> str:
    if not tags:
        return "no_context_tag_found"
    top = tags[0]
    if float(top.get("precision") or 0.0) >= 0.75 and float(top.get("recall") or 0.0) >= 0.5:
        return "test_context_tag_next"
    return "context_tags_weak_collect_more_evidence"


def _tag_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(tag for row in rows for tag in row.get("tags", [])).most_common())


def _mean(frame: pd.DataFrame, col: str) -> float | None:
    if frame.empty or col not in frame.columns:
        return None
    values = pd.to_numeric(frame[col], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _render_matrix(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = ["# RegimeV2 Phase 7Y Context Tag Matrix", "", f"- Assets: {s.get('assets')}", f"- Mixed windows: {s.get('mixed_window_count')}", f"- Candidate tags: {s.get('candidate_tag_count')}", f"- Top tag: {s.get('top_global_candidate_tag')}", f"- Recommendation: {s.get('recommendation')}", "", "| Asset | Mixed | Passing | Thin | Top tag | Recommendation |", "|---|---:|---:|---:|---|---|"]
    for row in report.get("variants", []):
        lines.append(f"| {row.get('asset')} | {row.get('mixed_window_count')} | {row.get('passing_window_count')} | {row.get('support_thin_count')} | {row.get('top_candidate_tag')} | {row.get('recommendation')} |")
    lines.extend(["", "## Global candidate tags", "", "| Tag | Mixed hits | Passing hits | Precision | Assets |", "|---|---:|---:|---:|---|"])
    for row in report.get("global_candidate_tags", [])[:20]:
        lines.append(f"| {row.get('tag')} | {row.get('mixed_hits')} | {row.get('passing_hits')} | {row.get('precision')} | {','.join(row.get('assets', []))} |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["build_transition_micro_state_context_diag_matrix_report", "build_transition_micro_state_context_diag_report", "build_transition_micro_state_context_diag_retest_report", "render_transition_micro_state_context_diag_markdown"]
