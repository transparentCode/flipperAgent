"""Phase 7R pruning discovery for setup-origin transition candidates.

7P found a useful but unstable setup-transition family. 7R does not promote it;
it sweeps simple, explainable pruning rules over 7P candidates and retests the
resulting active set with the same offline outcome pipeline.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_wf import build_ft_walkforward_report
from libs.models.regime_v2.evaluation.playbook_transition_setup import build_setup_transition_candidate_frame
from libs.models.regime_v2.evaluation.playbook_transition_state import build_breakout_transition_outcome_matrix

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)


def apply_setup_transition_prune(
    candidate_df: pd.DataFrame,
    *,
    min_score_gap: float = 0.0,
    max_continuation_score: float | None = None,
    max_volatility_quantile: float = 1.0,
    allowed_market_phases: Sequence[str] | None = None,
    allowed_directions: Sequence[str] = ("up", "down"),
) -> pd.DataFrame:
    """Apply one diagnostic prune configuration to a 7P candidate dataframe."""
    frame = candidate_df.copy()
    if frame.empty:
        return _ensure_prune_columns(frame)
    allowed_phase_set = {str(value) for value in allowed_market_phases} if allowed_market_phases else None
    allowed_direction_set = {str(value) for value in allowed_directions}
    active_mask = frame.get("breakout_transition_active", False).astype(bool)
    volatility_cutoff = _volatility_cutoff(frame, active_mask, max_volatility_quantile)
    reasons: list[str] = []
    tags: list[str] = []
    post_active: list[bool] = []
    for _, row in frame.iterrows():
        row_active = bool(row.get("breakout_transition_active", False))
        row_reasons: list[str] = []
        if not row_active:
            row_reasons.append("inactive")
        direction = str(row.get("breakout_transition_direction") or "none")
        phase = str(row.get("ft_context_gate_market_phase") or "")
        score_gap = abs(_float(row.get("setup_transition_up_score")) - _float(row.get("setup_transition_down_score")))
        continuation = _float(row.get("breakout_transition_continuation_score"))
        volatility = _float(row.get("setup_transition_volatility"))
        if row_active and direction not in allowed_direction_set:
            row_reasons.append("direction_pruned")
        if row_active and allowed_phase_set is not None and phase not in allowed_phase_set:
            row_reasons.append("phase_pruned")
        if row_active and score_gap < float(min_score_gap):
            row_reasons.append("ambiguous_score_gap")
        if row_active and max_continuation_score is not None and continuation > float(max_continuation_score):
            row_reasons.append("continuation_too_high")
        if row_active and volatility_cutoff is not None and volatility > volatility_cutoff:
            row_reasons.append("volatility_tail_pruned")
        keep = row_active and not row_reasons
        post_active.append(bool(keep))
        if not row_reasons:
            row_reasons.append("kept")
        reasons.append(row_reasons[0])
        tags.append(";".join(row_reasons))
    frame["setup_transition_pre_prune_active"] = active_mask.astype(bool)
    frame["setup_transition_post_prune_active"] = post_active
    frame["setup_transition_pruned"] = frame["setup_transition_pre_prune_active"] & ~frame["setup_transition_post_prune_active"]
    frame["setup_transition_prune_reason"] = reasons
    frame["setup_transition_prune_tags"] = tags
    frame["setup_transition_score_gap"] = (
        pd.to_numeric(frame.get("setup_transition_up_score"), errors="coerce").fillna(0.0)
        - pd.to_numeric(frame.get("setup_transition_down_score"), errors="coerce").fillna(0.0)
    ).abs()
    frame["setup_transition_volatility_cutoff"] = volatility_cutoff
    frame["breakout_transition_active"] = frame["setup_transition_post_prune_active"].astype(bool)
    frame["breakout_followthrough_active"] = frame["setup_transition_post_prune_active"].astype(bool)
    return frame


def build_setup_transition_prune_report(
    pruned_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize one 7R prune result."""
    frame = _ensure_prune_columns(pruned_df.copy())
    pre = int(frame["setup_transition_pre_prune_active"].sum())
    post = int(frame["setup_transition_post_prune_active"].sum())
    pruned = int(frame["setup_transition_pruned"].sum())
    active = frame[frame["setup_transition_post_prune_active"] == True]
    return {
        "phase": "phase_7r_setup_transition_prune_report",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "pre_active_count": pre,
            "post_active_count": post,
            "pruned_count": pruned,
            "pruned_rate": _rate(pruned, pre),
            "state_distribution": _counts(active.get("breakout_transition_state")) if len(active) else {},
            "direction_distribution": _counts(active.get("breakout_transition_direction")) if len(active) else {},
            "phase_distribution": _counts(active.get("ft_context_gate_market_phase")) if len(active) else {},
            "prune_reason_distribution": _counts(frame.get("setup_transition_prune_reason")),
            "config": dict(config or {}),
        },
        "recent_active": _rows(active.tail(12)),
    }


def build_setup_transition_prune_retest_report(
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
    lookback_bars: int = 8,
    min_candidate_score: float = 0.62,
    min_context_score: float = 0.70,
    max_risk_score: float = 0.72,
    max_conflict_count: int = 1,
    min_wick_score: float = 0.35,
    min_attempt_score: float = 0.50,
    min_score_gap: float = 0.0,
    max_continuation_score: float | None = None,
    max_volatility_quantile: float = 1.0,
    allowed_market_phases: Sequence[str] | None = None,
    allowed_directions: Sequence[str] = ("up", "down"),
) -> dict[str, Any]:
    """Build candidates, prune, then run transition outcome validation."""
    base_config = {
        "lookback_bars": int(lookback_bars),
        "min_candidate_score": float(min_candidate_score),
        "min_context_score": float(min_context_score),
        "max_risk_score": float(max_risk_score),
        "max_conflict_count": int(max_conflict_count),
        "min_wick_score": float(min_wick_score),
        "min_attempt_score": float(min_attempt_score),
    }
    prune_config = {
        "min_score_gap": float(min_score_gap),
        "max_continuation_score": max_continuation_score,
        "max_volatility_quantile": float(max_volatility_quantile),
        "allowed_market_phases": list(allowed_market_phases) if allowed_market_phases else None,
        "allowed_directions": list(allowed_directions),
    }
    candidates = build_setup_transition_candidate_frame(
        analysis_df,
        context_df,
        state_df,
        ohlcv,
        **base_config,
    )
    pruned = apply_setup_transition_prune(candidates, **prune_config)
    report = build_setup_transition_prune_report(
        pruned,
        asset=asset,
        timeframe=timeframe,
        config={**base_config, **prune_config},
    )
    outcome_matrix = build_breakout_transition_outcome_matrix(
        pruned,
        ohlcv,
        horizons=tuple(int(h) for h in horizons),
        fees_bps=tuple(float(f) for f in fees_bps),
    )
    walkforward = build_ft_walkforward_report(
        pruned,
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
        "phase": "phase_7r_setup_transition_prune_retest",
        "summary": _summary(report, walkforward, outcome_matrix),
        "prune_report": report,
        "outcome_matrix": outcome_matrix,
        "walkforward_report": walkforward,
    }


def build_setup_transition_prune_matrix_report(retest_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize 7R pruning sweeps."""
    variants = [_variant_row(report) for report in retest_reports]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            float(row.get("worst_split_directional_return") or -999.0),
            int(row.get("post_active_count") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7r_setup_transition_prune_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "assets": sorted({str(row.get("asset")) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_ready_pruned_setup_transition" if ready else "hold_off_pruned_setup_transition_unstable",
        },
        "variants": variants,
    }


def render_setup_transition_prune_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for a 7R prune matrix or retest report."""
    if report.get("phase") == "phase_7r_setup_transition_prune_matrix":
        return _render_matrix(report)
    summary = dict(report.get("summary", {}))
    return "\n".join(
        [
            "# RegimeV2 Phase 7R Setup Transition Prune Retest",
            "",
            f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
            f"- Active before/after: {summary.get('pre_active_count')} -> {summary.get('post_active_count')}",
            f"- Splits passed: {summary.get('passed_split_count')}/{summary.get('split_count')}",
            f"- Ready: {summary.get('ready')}",
            "",
        ]
    )


def _summary(report: Mapping[str, Any], walkforward: Mapping[str, Any], outcome_matrix: Mapping[str, Any]) -> dict[str, Any]:
    rs = dict(report.get("summary", {}))
    ws = dict(walkforward.get("summary", {}))
    ms = dict(outcome_matrix.get("summary", {}))
    return {
        "asset": rs.get("asset"),
        "timeframe": rs.get("timeframe"),
        "pre_active_count": rs.get("pre_active_count"),
        "post_active_count": rs.get("post_active_count"),
        "pruned_count": rs.get("pruned_count"),
        "pruned_rate": rs.get("pruned_rate"),
        "state_distribution": rs.get("state_distribution"),
        "direction_distribution": rs.get("direction_distribution"),
        "phase_distribution": rs.get("phase_distribution"),
        "prune_reason_distribution": rs.get("prune_reason_distribution"),
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
    prune_summary = dict(dict(report.get("prune_report", {})).get("summary", {}))
    return {
        **summary,
        "recent_active": list(dict(report.get("prune_report", {})).get("recent_active", [])),
        "config": prune_summary.get("config", {}),
        "splits": list(dict(report.get("walkforward_report", {})).get("splits", [])),
    }


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "pre_active_count": row.get("pre_active_count"),
        "post_active_count": row.get("post_active_count"),
        "pruned_count": row.get("pruned_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
        "direction_distribution": row.get("direction_distribution"),
        "config": row.get("config", {}),
    }


def _render_matrix(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7R Setup Transition Prune Matrix",
        "",
        f"- Variants: {s.get('variant_count', 0)}",
        f"- Ready variants: {s.get('ready_variant_count', 0)}",
        f"- Recommendation: {s.get('recommendation')}",
        f"- Best variant: {s.get('best_variant')}",
        "",
        "| Asset | Pre | Post | Pruned | Passed | Avg split dir | Worst split dir | Ready |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", [])[:30]:
        lines.append(
            "| {asset} | {pre} | {post} | {pruned} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
                asset=row.get("asset"),
                pre=row.get("pre_active_count"),
                post=row.get("post_active_count"),
                pruned=row.get("pruned_count"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
                ready=row.get("ready"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _volatility_cutoff(frame: pd.DataFrame, active_mask: pd.Series, quantile: float) -> float | None:
    q = float(quantile)
    if q >= 1.0 or "setup_transition_volatility" not in frame.columns:
        return None
    active_values = pd.to_numeric(frame.loc[active_mask, "setup_transition_volatility"], errors="coerce").dropna()
    if active_values.empty:
        return None
    return float(active_values.quantile(max(0.0, min(1.0, q))))


def _ensure_prune_columns(frame: pd.DataFrame) -> pd.DataFrame:
    defaults: dict[str, Any] = {
        "setup_transition_pre_prune_active": False,
        "setup_transition_post_prune_active": False,
        "setup_transition_pruned": False,
        "setup_transition_prune_reason": "missing",
        "setup_transition_prune_tags": "missing",
        "setup_transition_score_gap": 0.0,
        "setup_transition_volatility_cutoff": None,
    }
    for col, default in defaults.items():
        if col not in frame.columns:
            frame[col] = default
    return frame


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "state": row.get("breakout_transition_state"),
                "direction": row.get("breakout_transition_direction"),
                "score": row.get("breakout_transition_score"),
                "score_gap": row.get("setup_transition_score_gap"),
                "continuation_score": row.get("breakout_transition_continuation_score"),
                "volatility": row.get("setup_transition_volatility"),
                "phase": row.get("ft_context_gate_market_phase"),
                "reason": row.get("breakout_transition_reason"),
            }
        )
    return rows


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
    "apply_setup_transition_prune",
    "build_setup_transition_prune_matrix_report",
    "build_setup_transition_prune_report",
    "build_setup_transition_prune_retest_report",
    "render_setup_transition_prune_markdown",
]
