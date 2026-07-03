"""Phase 7Q diagnostics for setup-origin transition candidates."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


def build_setup_transition_diag_report(
    matrix_report: Mapping[str, Any],
    *,
    min_active_support: int = 30,
    min_passed_splits: int = 4,
) -> dict[str, Any]:
    """Diagnose 7P setup-transition variants and failure pockets."""
    matrix = dict(matrix_report.get("matrix_report", matrix_report))
    variants = [dict(row) for row in matrix.get("variants", [])]
    ranked = sorted(
        variants,
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            -abs(float(row.get("worst_split_directional_return") or 0.0)),
            int(row.get("active_count") or 0),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else {}
    by_asset = _asset_summary(variants)
    failure = _failure_profile(best)
    recommendation = _recommendation(best, failure, min_active_support=min_active_support, min_passed_splits=min_passed_splits)
    return {
        "phase": "phase_7q_setup_transition_diagnostics",
        "summary": {
            "variant_count": len(variants),
            "best_variant": _compact(best),
            "asset_summary": by_asset,
            "best_failure_profile": failure,
            "recommendation": recommendation,
        },
        "top_variants": [_compact(row) for row in ranked[:10]],
    }


def render_setup_transition_diag_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for 7Q diagnostics."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7Q Setup Transition Diagnostics",
        "",
        "## Summary",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        "",
        "## Asset summary",
        "",
        "| Asset | Variants | Max active | Best passed | Best avg | Best worst |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for asset, row in dict(summary.get("asset_summary", {})).items():
        lines.append(
            "| {asset} | {variants} | {active} | {passed} | {avg} | {worst} |".format(
                asset=asset,
                variants=row.get("variant_count"),
                active=row.get("max_active_count"),
                passed=row.get("best_passed_split_count"),
                avg=row.get("best_avg_split_directional_return"),
                worst=row.get("best_worst_split_directional_return"),
            )
        )
    lines.extend(["", "## Best variant failure profile", ""])
    failure = dict(summary.get("best_failure_profile", {}))
    lines.append(f"- Failed split count: {failure.get('failed_split_count')}")
    lines.append(f"- Failure reasons: {failure.get('failure_reason_distribution')}")
    lines.append(f"- Worst failed split: {failure.get('worst_failed_split')}")
    lines.append(f"- Direction distribution in failed splits: {failure.get('failed_direction_distribution')}")
    lines.extend(["", "## Top variants", "", "| Asset | Lookback | Min score | Active | Passed | Avg | Worst |", "|---|---:|---:|---:|---:|---:|---:|"])
    for row in report.get("top_variants", []):
        cfg = dict(row.get("config", {}))
        lines.append(
            "| {asset} | {lookback} | {score} | {active} | {passed}/{splits} | {avg} | {worst} |".format(
                asset=row.get("asset"),
                lookback=cfg.get("lookback_bars"),
                score=cfg.get("min_candidate_score"),
                active=row.get("active_count"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _asset_summary(variants: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    assets = sorted({str(row.get("asset")) for row in variants})
    out: dict[str, Any] = {}
    for asset in assets:
        rows = [row for row in variants if str(row.get("asset")) == asset]
        out[asset] = {
            "variant_count": len(rows),
            "max_active_count": max((int(row.get("active_count") or 0) for row in rows), default=0),
            "best_passed_split_count": max((int(row.get("passed_split_count") or 0) for row in rows), default=0),
            "best_avg_split_directional_return": max((float(row.get("avg_split_directional_return") or -999.0) for row in rows), default=None),
            "best_worst_split_directional_return": max((float(row.get("worst_split_directional_return") or -999.0) for row in rows), default=None),
        }
    return out


def _failure_profile(variant: Mapping[str, Any]) -> dict[str, Any]:
    splits = [dict(row) for row in variant.get("splits", [])]
    failed = [row for row in splits if not row.get("split_passed")]
    reasons: Counter[str] = Counter()
    directions: Counter[str] = Counter()
    for split in failed:
        reasons.update(str(reason) for reason in split.get("failure_reasons", []))
        directions.update({str(k): int(v) for k, v in dict(split.get("direction_distribution", {})).items()})
    worst = None
    if failed:
        worst = sorted(failed, key=lambda row: float(row.get("worst_directional_net_return") or 0.0))[0]
    return {
        "failed_split_count": len(failed),
        "failure_reason_distribution": dict(reasons.most_common()),
        "failed_direction_distribution": dict(directions.most_common()),
        "worst_failed_split": _split_compact(worst),
    }


def _recommendation(
    best: Mapping[str, Any],
    failure: Mapping[str, Any],
    *,
    min_active_support: int,
    min_passed_splits: int,
) -> str:
    active = int(best.get("active_count") or 0)
    passed = int(best.get("passed_split_count") or 0)
    reasons = dict(failure.get("failure_reason_distribution", {}))
    if active < min_active_support:
        return "increase_support_before_pruning"
    if passed >= min_passed_splits:
        return "candidate_ready_for_robustness"
    if reasons.get("worst_cell_too_negative"):
        return "diagnose_worst_cell_prune_before_promotion"
    if reasons.get("low_passing_rate"):
        return "diagnose_direction_or_horizon_filter"
    return "hold_off_collect_more_transition_evidence"


def _compact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "active_count": row.get("active_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
        "ready": row.get("ready"),
        "direction_distribution": row.get("direction_distribution"),
        "state_distribution": row.get("state_distribution"),
        "config": row.get("config", {}),
    }


def _split_compact(split: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not split:
        return None
    return {
        "split_index": split.get("split_index"),
        "active_count": split.get("active_count"),
        "direction_distribution": split.get("direction_distribution"),
        "failure_reasons": split.get("failure_reasons"),
        "passing_cell_rate": split.get("passing_cell_rate"),
        "avg_directional_net_return": split.get("avg_directional_net_return"),
        "worst_directional_net_return": split.get("worst_directional_net_return"),
        "start_timestamp": split.get("start_timestamp"),
        "end_timestamp": split.get("end_timestamp"),
    }


__all__ = ["build_setup_transition_diag_report", "render_setup_transition_diag_markdown"]
