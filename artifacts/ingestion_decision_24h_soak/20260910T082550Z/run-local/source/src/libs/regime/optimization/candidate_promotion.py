from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_CANDIDATES = (
    "regime_only",
    "breadth_gate",
    "breadth_blend",
    "best_hmm_preset",
)

_SEVERE_FLIP_FLOP_RATE = 0.15
_SEVERE_AVG_DURATION = 5.0
_SEVERE_HMM_UNSTABLE_RATE = 0.15


def load_json_rows(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        payload = json.loads(path.read_text())
        if not isinstance(payload, list):
            raise ValueError(f"Expected list payload in {path}")
        rows.extend(payload)
    return rows


def build_candidate_promotion_report(
    breadth_rows: list[dict[str, Any]],
    hmm_rows: list[dict[str, Any]],
    *,
    candidate_names: tuple[str, ...] = DEFAULT_CANDIDATES,
) -> dict[str, Any]:
    hmm_by_key = {(row["asset"], row["timeframe"]): row for row in hmm_rows}
    slice_results: list[dict[str, Any]] = []

    for breadth_row in breadth_rows:
        key = (breadth_row["asset"], breadth_row["timeframe"])
        hmm_row = hmm_by_key.get(key)
        candidates = _build_slice_candidates(breadth_row, hmm_row, candidate_names=candidate_names)
        ranking = _rank_slice_candidates(candidates.values())
        slice_results.append(
            {
                "asset": breadth_row["asset"],
                "timeframe": breadth_row["timeframe"],
                "ranking": ranking,
                "candidates": candidates,
            }
        )

    panel_summary = _summarize_panel(slice_results, candidate_names=candidate_names)
    panel_ranking = _rank_panel_candidates(panel_summary.values())
    return {
        "candidate_names": list(candidate_names),
        "slice_results": slice_results,
        "panel_summary": panel_summary,
        "panel_ranking": panel_ranking,
    }


def _build_slice_candidates(
    breadth_row: dict[str, Any],
    hmm_row: dict[str, Any] | None,
    *,
    candidate_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    asset = breadth_row["asset"]
    timeframe = breadth_row["timeframe"]
    breadth_variants = breadth_row.get("breadth_variants", {})
    breadth_walk = breadth_variants.get("walk_forward", {})
    breadth_full = breadth_variants.get("full_sample", {})
    result: dict[str, dict[str, Any]] = {}

    for name in ("regime_only", "breadth_gate", "breadth_blend"):
        if name not in candidate_names:
            continue
        walk = breadth_walk.get(name)
        if not walk:
            continue
        full = breadth_full.get(name, {})
        result[name] = _candidate_entry(
            candidate=name,
            asset=asset,
            timeframe=timeframe,
            walk=walk,
            full=full,
            source_variant=name,
            hmm_health=(breadth_row.get("hmm_health") or {}).get("walk_forward", {}),
        )

    if "best_hmm_preset" in candidate_names and hmm_row and hmm_row.get("best_variant"):
        best_variant = hmm_row["best_variant"]
        best_result = (hmm_row.get("hmm_variants") or {}).get(best_variant)
        if best_result:
            result["best_hmm_preset"] = _candidate_entry(
                candidate="best_hmm_preset",
                asset=asset,
                timeframe=timeframe,
                walk={
                    "score": best_result.get("mean_fold_score"),
                    "benchmarks": best_result.get("walk_forward", {}),
                },
                full={
                    "score": None,
                    "benchmarks": best_result.get("full_sample", {}),
                },
                source_variant=best_variant,
                hmm_health=(best_result.get("hmm_health") or {}).get("walk_forward", {}),
            )
    return result


def _candidate_entry(
    *,
    candidate: str,
    asset: str,
    timeframe: str,
    walk: dict[str, Any],
    full: dict[str, Any],
    source_variant: str,
    hmm_health: dict[str, Any],
) -> dict[str, Any]:
    walk_bench = walk.get("benchmarks", {})
    full_bench = full.get("benchmarks", {})
    avg_duration = _float_or_none(walk_bench.get("avg_regime_duration"))
    flip_flop_rate = _float_or_none(walk_bench.get("flip_flop_rate"))
    unstable_fit_rate = _float_or_none(hmm_health.get("unstable_fit_rate"))
    severe_instability = (
        (avg_duration is not None and avg_duration < _SEVERE_AVG_DURATION)
        or (flip_flop_rate is not None and flip_flop_rate > _SEVERE_FLIP_FLOP_RATE)
        or (unstable_fit_rate is not None and unstable_fit_rate > _SEVERE_HMM_UNSTABLE_RATE)
    )
    return {
        "candidate": candidate,
        "source_variant": source_variant,
        "asset": asset,
        "timeframe": timeframe,
        "walk_forward_score": _float_or_none(walk.get("score")),
        "walk_forward_forward_ic": _float_or_none(walk_bench.get("forward_return_ic")),
        "walk_forward_sharpe_improvement": _float_or_none(walk_bench.get("sharpe_improvement")),
        "strict_pass": bool(walk_bench.get("passed_strict_baseline_gate", False)),
        "avg_regime_duration": avg_duration,
        "flip_flop_rate": flip_flop_rate,
        "hmm_unstable_fit_rate": unstable_fit_rate,
        "hmm_health_pass": bool(hmm_health.get("passed", False)),
        "severe_instability": severe_instability,
        "full_sample_score": _float_or_none(full.get("score")),
        "full_sample_forward_ic": _float_or_none(full_bench.get("forward_return_ic")),
    }


def _rank_slice_candidates(rows: Any) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (
            row["strict_pass"],
            row["walk_forward_forward_ic"] is not None and row["walk_forward_forward_ic"] >= 0.0,
            row["walk_forward_score"] is not None,
            row["walk_forward_score"] if row["walk_forward_score"] is not None else float("-inf"),
            row["walk_forward_forward_ic"] if row["walk_forward_forward_ic"] is not None else float("-inf"),
            -int(row["severe_instability"]),
        ),
        reverse=True,
    )
    return ranked


def _summarize_panel(
    slice_results: list[dict[str, Any]],
    *,
    candidate_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for candidate in candidate_names:
        rows = [
            slice_row["candidates"][candidate]
            for slice_row in slice_results
            if candidate in slice_row["candidates"]
        ]
        if not rows:
            continue
        metrics = {
            "candidate": candidate,
            "evaluated_slices": len(rows),
            "strict_pass_count": sum(1 for row in rows if row["strict_pass"]),
            "strict_pass_rate": sum(1 for row in rows if row["strict_pass"]) / len(rows),
            "median_walk_forward_score": _median_of(rows, "walk_forward_score"),
            "median_forward_return_ic": _median_of(rows, "walk_forward_forward_ic"),
            "median_sharpe_improvement": _median_of(rows, "walk_forward_sharpe_improvement"),
            "median_avg_regime_duration": _median_of(rows, "avg_regime_duration"),
            "median_flip_flop_rate": _median_of(rows, "flip_flop_rate"),
            "median_hmm_unstable_fit_rate": _median_of(rows, "hmm_unstable_fit_rate"),
            "severe_instability_count": sum(1 for row in rows if row["severe_instability"]),
            "severe_instability_rate": sum(1 for row in rows if row["severe_instability"]) / len(rows),
            "per_slice": rows,
        }
        summary[candidate] = metrics

    baseline = summary.get("regime_only")
    for candidate, row in summary.items():
        row["promotion_decision"] = _promotion_decision(row, baseline)
    return summary


def _rank_panel_candidates(rows: Any) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (
            row["strict_pass_rate"],
            row["median_forward_return_ic"] is not None and row["median_forward_return_ic"] >= 0.0,
            row["median_forward_return_ic"] if row["median_forward_return_ic"] is not None else float("-inf"),
            row["median_walk_forward_score"] if row["median_walk_forward_score"] is not None else float("-inf"),
            -row["severe_instability_rate"],
        ),
        reverse=True,
    )
    return ranked


def _promotion_decision(
    candidate_row: dict[str, Any],
    baseline_row: dict[str, Any] | None,
) -> str:
    if candidate_row["candidate"] == "regime_only":
        return "baseline"
    if baseline_row is None:
        return "reject"

    strict_improved = candidate_row["strict_pass_rate"] > baseline_row["strict_pass_rate"]
    ic_value = candidate_row["median_forward_return_ic"]
    baseline_ic = baseline_row["median_forward_return_ic"]
    ic_non_negative = ic_value is not None and ic_value >= 0.0
    ic_improved = (
        ic_value is not None
        and baseline_ic is not None
        and ic_value > baseline_ic
    )
    score_improved = (
        candidate_row["median_walk_forward_score"] is not None
        and baseline_row["median_walk_forward_score"] is not None
        and candidate_row["median_walk_forward_score"] > baseline_row["median_walk_forward_score"]
    )
    stability_not_worse = (
        candidate_row["severe_instability_rate"] <= baseline_row["severe_instability_rate"]
    )

    if strict_improved and (ic_non_negative or ic_improved) and stability_not_worse:
        return "promote"
    if score_improved and ic_improved:
        return "hold_for_overlay_only"
    return "reject"


def _median_of(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return float(median(values))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
