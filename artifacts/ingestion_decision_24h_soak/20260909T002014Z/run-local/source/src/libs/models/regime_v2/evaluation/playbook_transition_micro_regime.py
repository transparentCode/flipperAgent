"""Phase 7T transition micro-regime diagnostics.

This module reads a transition matrix, such as Phase 7R output, and tags each
split with diagnostic micro-regime labels. The labels are not trading rules and
are not timestamp/split-index overrides; they explain failure pockets using
support, phase mode, direction balance, volatility-prune mode, and validation
failure reasons.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence


def build_transition_micro_regime_report(
    matrix_payload: Mapping[str, Any],
    *,
    min_split_active: int = 3,
    direction_skew_threshold: float = 0.75,
    max_worst_loss: float = 0.0010,
) -> dict[str, Any]:
    """Build split-level micro-regime diagnostics from a transition matrix."""
    matrix = dict(matrix_payload.get("matrix_report", matrix_payload))
    variants = [dict(row) for row in matrix.get("variants", [])]
    tagged_splits = []
    for variant_index, variant in enumerate(variants):
        for split in variant.get("splits", []):
            tagged_splits.append(
                _tag_split(
                    variant_index,
                    variant,
                    split,
                    min_split_active=int(min_split_active),
                    direction_skew_threshold=float(direction_skew_threshold),
                    max_worst_loss=float(max_worst_loss),
                )
            )
    tag_rows = _tag_rows(tagged_splits)
    tag_rows.sort(key=lambda row: (_float(row.get("avg_directional_net_return"), 999.0), -int(row.get("split_count") or 0)))
    return {
        "phase": "phase_7t_transition_micro_regime_diagnostics",
        "summary": {
            "variant_count": len(variants),
            "tagged_split_count": len(tagged_splits),
            "assets": sorted({str(row.get("asset")) for row in variants}),
            "tag_distribution": _tag_distribution(tagged_splits),
            "worst_tag": tag_rows[0] if tag_rows else None,
            "asset_summary": _asset_summary(tagged_splits),
            "recommendation": _recommendation(tag_rows),
            "criteria": {
                "min_split_active": int(min_split_active),
                "direction_skew_threshold": float(direction_skew_threshold),
                "max_worst_loss": float(max_worst_loss),
            },
        },
        "tagged_splits": tagged_splits,
        "micro_regimes": tag_rows,
    }


def render_transition_micro_regime_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for Phase 7T diagnostics."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7T Transition Micro-Regime Diagnostics",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Tagged splits: {summary.get('tagged_split_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Worst tag: {summary.get('worst_tag')}",
        "",
        "## Asset summary",
        "",
        "| Asset | Tagged splits | Failed splits | Worst avg | Worst split loss | Top tags |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for asset, row in dict(summary.get("asset_summary", {})).items():
        lines.append(
            "| {asset} | {tagged_split_count} | {failed_split_count} | {worst_avg_directional_return} | {worst_split_loss} | {top_tags} |".format(
                asset=asset,
                tagged_split_count=row.get("tagged_split_count"),
                failed_split_count=row.get("failed_split_count"),
                worst_avg_directional_return=row.get("worst_avg_directional_return"),
                worst_split_loss=row.get("worst_split_loss"),
                top_tags=row.get("top_tags"),
            )
        )
    lines.extend([
        "",
        "## Micro-regime tags",
        "",
        "| Tag | Splits | Failed | Avg return | Worst loss | Assets |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for row in report.get("micro_regimes", [])[:30]:
        lines.append(
            "| {tag} | {split_count} | {failed_count} | {avg_directional_net_return} | {worst_directional_net_return} | {assets} |".format(
                tag=row.get("tag"),
                split_count=row.get("split_count"),
                failed_count=row.get("failed_count"),
                avg_directional_net_return=row.get("avg_directional_net_return"),
                worst_directional_net_return=row.get("worst_directional_net_return"),
                assets=",".join(row.get("assets", [])),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _tag_split(
    variant_index: int,
    variant: Mapping[str, Any],
    split: Mapping[str, Any],
    *,
    min_split_active: int,
    direction_skew_threshold: float,
    max_worst_loss: float,
) -> dict[str, Any]:
    config = dict(variant.get("config", {}))
    active_count = int(split.get("active_count") or 0)
    direction_distribution = dict(split.get("direction_distribution", {}))
    tags = []
    phase_mode = config.get("allowed_market_phases")
    if phase_mode:
        tags.append("phase_" + "_".join(str(x) for x in phase_mode))
    else:
        tags.append("phase_all")
    if _float(config.get("max_volatility_quantile"), 1.0) < 1.0:
        tags.append("volatility_tail_pruned")
    if config.get("max_continuation_score") is not None:
        tags.append("continuation_pruned")
    if active_count < min_split_active:
        tags.append("support_thin")
    if _is_direction_skewed(direction_distribution, direction_skew_threshold):
        tags.append("direction_skew")
    for reason in split.get("failure_reasons", []):
        tags.append("reason_" + str(reason))
    if _float(split.get("worst_directional_net_return")) < -abs(max_worst_loss):
        tags.append("worst_loss_tail")
    return {
        "variant_index": variant_index,
        "asset": variant.get("asset"),
        "timeframe": variant.get("timeframe"),
        "split_index": split.get("split_index"),
        "split_passed": bool(split.get("split_passed")),
        "active_count": active_count,
        "avg_directional_net_return": split.get("avg_directional_net_return"),
        "worst_directional_net_return": split.get("worst_directional_net_return"),
        "direction_distribution": direction_distribution,
        "tags": sorted(set(tags)),
    }


def _tag_rows(tagged_splits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for split in tagged_splits:
        for tag in split.get("tags", []):
            buckets[str(tag)].append(split)
    rows = []
    for tag, splits in buckets.items():
        avgs = [_float(row.get("avg_directional_net_return")) for row in splits if row.get("avg_directional_net_return") is not None]
        worst_values = [_float(row.get("worst_directional_net_return")) for row in splits if row.get("worst_directional_net_return") is not None]
        rows.append(
            {
                "tag": tag,
                "split_count": len(splits),
                "failed_count": sum(1 for row in splits if not row.get("split_passed")),
                "avg_directional_net_return": sum(avgs) / len(avgs) if avgs else None,
                "worst_directional_net_return": min(worst_values) if worst_values else None,
                "assets": sorted({str(row.get("asset")) for row in splits}),
            }
        )
    return rows


def _asset_summary(tagged_splits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    for asset in sorted({str(row.get("asset")) for row in tagged_splits}):
        rows = [row for row in tagged_splits if str(row.get("asset")) == asset]
        avgs = [_float(row.get("avg_directional_net_return")) for row in rows if row.get("avg_directional_net_return") is not None]
        worst_values = [_float(row.get("worst_directional_net_return")) for row in rows if row.get("worst_directional_net_return") is not None]
        tag_counter = Counter(tag for row in rows for tag in row.get("tags", []))
        out[asset] = {
            "tagged_split_count": len(rows),
            "failed_split_count": sum(1 for row in rows if not row.get("split_passed")),
            "worst_avg_directional_return": min(avgs) if avgs else None,
            "worst_split_loss": min(worst_values) if worst_values else None,
            "top_tags": dict(tag_counter.most_common(5)),
        }
    return out


def _tag_distribution(tagged_splits: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(tag for row in tagged_splits for tag in row.get("tags", [])).most_common())


def _recommendation(tag_rows: Sequence[Mapping[str, Any]]) -> str:
    if not tag_rows:
        return "no_micro_regime_tags"
    worst = tag_rows[0]
    if _float(worst.get("avg_directional_net_return")) < 0.0 and int(worst.get("failed_count") or 0) > 0:
        return "test_micro_regime_exclusion_next"
    return "micro_regimes_explain_little"


def _is_direction_skewed(distribution: Mapping[str, Any], threshold: float) -> bool:
    counts = [int(value) for value in distribution.values()]
    total = sum(counts)
    return total > 0 and max(counts) / float(total) >= threshold


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_transition_micro_regime_report", "render_transition_micro_regime_markdown"]
