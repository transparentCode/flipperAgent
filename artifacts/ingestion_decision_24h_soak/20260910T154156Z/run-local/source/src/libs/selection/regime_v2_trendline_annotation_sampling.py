"""Sampling-plan helper for RegimeV2 trendline annotation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Mapping, Sequence

_DEFAULT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "LTCUSDT",
)
_DEFAULT_TIMEFRAMES = ("1h", "2h", "4h")


@dataclass(frozen=True)
class AnnotationSamplingConfig:
    symbols: tuple[str, ...] = _DEFAULT_SYMBOLS
    timeframes: tuple[str, ...] = _DEFAULT_TIMEFRAMES
    max_records_per_pair: int = 200
    limit: int = 1200
    warmup_bars: int = 120
    horizon_bars: int = 12
    batch_size: int = 8
    target_rows: int = 100
    min_hit_rate: float = 0.005
    output_root: str = "research/tl15"


def build_annotation_sampling_plan(
    target_report: Mapping[str, Any],
    *,
    config: AnnotationSamplingConfig | None = None,
    target_field: str = "trendline_confidence_annotation",
    target_value: Any = "breakout_watch",
) -> dict[str, Any]:
    cfg = config or AnnotationSamplingConfig()
    summary = dict(target_report.get("summary", {}))
    target = _find_target(list(target_report.get("targets", [])), target_field, target_value)
    labeled_count = int(summary.get("labeled_count") or summary.get("records_after_filter") or 0)
    current_count = int(target.get("count", 0)) if target else 0
    observed_hit_rate = current_count / labeled_count if labeled_count else 0.0
    planning_hit_rate = max(observed_hit_rate, cfg.min_hit_rate)
    deficit = max(0, cfg.target_rows - current_count)
    estimated_shadow_rows_needed = int(ceil(deficit / planning_hit_rate)) if deficit else 0
    pair_runs_needed = int(ceil(estimated_shadow_rows_needed / max(cfg.max_records_per_pair, 1))) if deficit else 0
    candidates = _candidate_pair_runs(cfg, dict(target.get("asset_timeframe", {})) if target else {})
    selected = candidates[:pair_runs_needed]
    batches = _batch_runs(selected, cfg.batch_size)
    return {
        "phase": "phase_tl_h15_annotation_sampling_plan",
        "target": {
            "field": target_field,
            "value": target_value,
            "current_count": current_count,
            "target_rows": cfg.target_rows,
            "deficit": deficit,
            "labeled_count": labeled_count,
            "observed_hit_rate": observed_hit_rate,
            "planning_hit_rate": planning_hit_rate,
            "estimated_shadow_rows_needed": estimated_shadow_rows_needed,
            "pair_runs_needed": pair_runs_needed,
        },
        "config": {
            "symbols": list(cfg.symbols),
            "timeframes": list(cfg.timeframes),
            "max_records_per_pair": cfg.max_records_per_pair,
            "limit": cfg.limit,
            "warmup_bars": cfg.warmup_bars,
            "horizon_bars": cfg.horizon_bars,
            "batch_size": cfg.batch_size,
            "output_root": cfg.output_root,
        },
        "candidate_pair_runs": candidates,
        "selected_pair_runs": selected,
        "batches": batches,
        "commands": [_collector_command(batch, cfg, idx + 1) for idx, batch in enumerate(batches)],
        "recommendation": _recommendation(deficit, observed_hit_rate, planning_hit_rate, pair_runs_needed),
    }


def render_annotation_sampling_plan_markdown(plan: Mapping[str, Any]) -> str:
    target = dict(plan.get("target", {}))
    lines = [
        "# RegimeV2 Trendline Annotation Sampling Plan",
        "",
        "## Target",
        "",
        f"- Field: {target.get('field')}",
        f"- Value: {target.get('value')}",
        f"- Current count: {target.get('current_count')}",
        f"- Target rows: {target.get('target_rows')}",
        f"- Deficit: {target.get('deficit')}",
        f"- Observed hit rate: {target.get('observed_hit_rate')}",
        f"- Estimated shadow rows needed: {target.get('estimated_shadow_rows_needed')}",
        f"- Pair-runs needed: {target.get('pair_runs_needed')}",
        "",
        "## Selected Pair Runs",
        "",
        "| Pair | Existing target rows | Rank |",
        "|---|---:|---:|",
    ]
    selected = list(plan.get("selected_pair_runs", []))
    if selected:
        for row in selected:
            lines.append(f"| {row.get('pair')} | {row.get('existing_target_rows')} | {row.get('rank')} |")
    else:
        lines.append("| none | 0 | 0 |")
    lines.extend(["", "## Commands", ""])
    for idx, command in enumerate(plan.get("commands", []), start=1):
        lines.extend([f"### Batch {idx}", "", "```bash", str(command), "```", ""])
    lines.extend(["## Recommendation", "", str(plan.get("recommendation", "")), ""])
    return "\n".join(lines)


def _find_target(targets: list[Any], field: str, value: Any) -> dict[str, Any] | None:
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        if str(target.get("field")) == str(field) and str(target.get("value")) == str(value):
            return dict(target)
    return None


def _candidate_pair_runs(config: AnnotationSamplingConfig, existing_counts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rank = 1
    for timeframe in config.timeframes:
        for symbol in config.symbols:
            asset = symbol.upper()
            key = f"{asset}|{timeframe}"
            rows.append(
                {
                    "pair": f"{asset}:{timeframe}",
                    "asset": asset,
                    "timeframe": timeframe,
                    "existing_target_rows": int(existing_counts.get(key, 0) or 0),
                    "rank": rank,
                }
            )
            rank += 1
    return sorted(rows, key=lambda row: (-int(row["existing_target_rows"]), int(row["rank"])))


def _batch_runs(rows: Sequence[Mapping[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    size = max(int(batch_size), 1)
    return [[dict(row) for row in rows[i : i + size]] for i in range(0, len(rows), size)]


def _collector_command(batch: Sequence[Mapping[str, Any]], config: AnnotationSamplingConfig, batch_idx: int) -> str:
    pair_args = " ".join(f"--pair {row['pair']}" for row in batch)
    prefix = f"{config.output_root.rstrip('/')}/batch_{batch_idx:02d}"
    return (
        "PYTHONPATH=src .venv/bin/python -m libs.models.regime_v2.scripts.collect_shadow_binance "
        f"{pair_args} "
        f"--limit {config.limit} "
        f"--warmup-bars {config.warmup_bars} "
        f"--horizon-bars {config.horizon_bars} "
        f"--max-records-per-pair {config.max_records_per_pair} "
        "--include-trendline-context "
        "--trendline-min-bars 80 "
        "--trendline-history-limit 5 "
        f"--log-path {prefix}_records.jsonl "
        "--reset-log "
        f"--output-json {prefix}_collect.json "
        f"--report-json {prefix}_shadow_report.json "
        f"--report-md {prefix}_shadow_report.md"
    )


def _recommendation(deficit: int, observed_hit_rate: float, planning_hit_rate: float, pair_runs_needed: int) -> str:
    if deficit <= 0:
        return "Target sample count is already satisfied; rerun outcome diagnostics before any experiment design."
    if observed_hit_rate <= 0:
        return "No target rows observed yet; run broad sampling and revisit the target definition if it stays empty."
    return (
        f"Collect about {deficit} more target rows. At observed hit rate {observed_hit_rate:.4f} "
        f"using planning hit rate {planning_hit_rate:.4f}, schedule about {pair_runs_needed} pair/timeframe runs. "
        "Keep this evidence-only until sample, positive-rate, and average-lift thresholds are all met."
    )


__all__ = [
    "AnnotationSamplingConfig",
    "build_annotation_sampling_plan",
    "render_annotation_sampling_plan_markdown",
]
