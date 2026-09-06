"""Bounded experiment for suppressing already-invalid current line emissions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    EmittedLine,
    LegacyPathfindingResult,
    SidePathResult,
    analyze_legacy,
)
from research.trendlines_v4.post_anchor_validity_audit import (
    post_anchor_body_crossings,
)


@dataclass(frozen=True, slots=True)
class FilteredSideResult:
    """One unchanged G1 side result and its emission-only filter result."""

    baseline: SidePathResult
    post_anchor_crossings: tuple[tuple[int, float, float], ...]
    filtered_line: EmittedLine | None

    @property
    def suppressed(self) -> bool:
        return self.baseline.emitted_line is not None and self.filtered_line is None


@dataclass(frozen=True, slots=True)
class FilteredLegacyResult:
    """Complete G1 facts with only current emitted lines transformed."""

    baseline: LegacyPathfindingResult
    support: FilteredSideResult
    resistance: FilteredSideResult


def filter_side_result(
    bars: Sequence[Bar], side_result: SidePathResult
) -> FilteredSideResult:
    """Apply exactly the G3 hard-body rule to one unchanged side result."""

    line = side_result.emitted_line
    crossings = (
        () if line is None else post_anchor_body_crossings(bars, line, side_result.side)
    )
    return FilteredSideResult(
        baseline=side_result,
        post_anchor_crossings=crossings,
        filtered_line=None if crossings else line,
    )


def filter_legacy_result(
    bars: Sequence[Bar], baseline: LegacyPathfindingResult
) -> FilteredLegacyResult:
    """Preserve the complete baseline and transform only its two line fields."""

    return FilteredLegacyResult(
        baseline=baseline,
        support=filter_side_result(bars, baseline.support),
        resistance=filter_side_result(bars, baseline.resistance),
    )


def geometry_key(window_key: str, side: str, line: EmittedLine) -> tuple[object, ...]:
    """Return an exact, non-persistent identity for one observed line geometry."""

    return (
        window_key,
        side,
        line.start_index,
        line.end_index,
        line.start_price,
        line.end_price,
        line.slope,
        line.intercept,
    )


def _new_side_stats() -> dict[str, object]:
    return {
        "baseline": 0,
        "retained": 0,
        "suppressed": 0,
        "inspected": 0,
        "runs": [],
        "run": 0,
    }


def _close_run(stats: dict[str, object]) -> None:
    run = stats["run"]
    if run:
        stats["runs"].append(run)  # type: ignore[union-attr]
        stats["run"] = 0


def _side_payload(stats: dict[str, object], eligible: int) -> dict[str, object]:
    baseline = stats["baseline"]
    retained = stats["retained"]
    runs = stats["runs"]
    return {
        "eligible_prefix_count": eligible,
        "baseline_boundary_available_count": baseline,
        "filtered_boundary_available_count": retained,
        "suppressed_count": stats["suppressed"],
        "baseline_availability_fraction": baseline / eligible,
        "filtered_availability_fraction": retained / eligible,
        "suppression_run_count": len(runs),
        "maximum_suppression_run_length": max(runs, default=0),
        "suppression_run_lengths": list(runs),
    }


def _scan_window(
    window_key: str, bars: Sequence[Bar], pivot_window: int
) -> tuple[
    dict[str, object],
    set[tuple[object, ...]],
    set[tuple[object, ...]],
    set[tuple[object, ...]],
    tuple[dict[str, object], ...],
]:
    stats = {"support": _new_side_stats(), "resistance": _new_side_stats()}
    baseline_geometries: set[tuple[object, ...]] = set()
    retained_geometries: set[tuple[object, ...]] = set()
    suppressed_geometries: set[tuple[object, ...]] = set()
    total_crossings = 0
    retained_with_crossing = 0
    suppressed_without_crossing = 0
    final_cutoffs: tuple[dict[str, object], ...] = ()

    for prefix_length in range(1, len(bars) + 1):
        filtered = filter_legacy_result(
            bars[:prefix_length], analyze_legacy(bars[:prefix_length], pivot_window)
        )
        for side_result in (filtered.support, filtered.resistance):
            side = side_result.baseline.side
            baseline_line = side_result.baseline.emitted_line
            crossings = side_result.post_anchor_crossings
            total_crossings += len(crossings)
            if baseline_line is None:
                _close_run(stats[side])
                continue

            side_stats = stats[side]
            side_stats["baseline"] += 1  # type: ignore[operator]
            side_stats["inspected"] += max(
                0, prefix_length - baseline_line.end_index - 1
            )  # type: ignore[operator]
            geometry = geometry_key(window_key, side, baseline_line)
            baseline_geometries.add(geometry)
            if side_result.filtered_line is None:
                side_stats["suppressed"] += 1  # type: ignore[operator]
                side_stats["run"] += 1  # type: ignore[operator]
                suppressed_geometries.add(geometry)
                if not crossings:
                    suppressed_without_crossing += 1
            else:
                side_stats["retained"] += 1  # type: ignore[operator]
                _close_run(side_stats)
                retained_geometries.add(geometry)
                if crossings:
                    retained_with_crossing += 1

        if prefix_length == len(bars):
            final_cutoffs = tuple(
                {
                    "side": side_result.baseline.side,
                    "baseline_line_present": side_result.baseline.emitted_line
                    is not None,
                    "filtered_line_present": side_result.filtered_line is not None,
                    "post_anchor_crossings": len(side_result.post_anchor_crossings),
                }
                for side_result in (filtered.support, filtered.resistance)
            )

    for side_stats in stats.values():
        _close_run(side_stats)
    summary = {
        "prefixes_audited": len(bars),
        "sides": {
            side: _side_payload(side_stats, len(bars))
            for side, side_stats in stats.items()
        },
        "post_anchor_bars_inspected": sum(
            side_stats["inspected"] for side_stats in stats.values()
        ),
        "retained_line_with_crossing_count": retained_with_crossing,
        "suppressed_line_without_crossing_count": suppressed_without_crossing,
        "total_body_crossings": total_crossings,
    }
    return (
        summary,
        baseline_geometries,
        retained_geometries,
        suppressed_geometries,
        final_cutoffs,
    )


def audit_window(bars: Sequence[Bar], pivot_window: int = 3) -> dict[str, object]:
    """Measure the emission filter over every causal prefix of one window."""

    if pivot_window < 1:
        raise ValueError("pivot_window must be >= 1")
    return _scan_window("window", bars, pivot_window)[0]


def audit_corpus(
    windows: Sequence[tuple[str, Sequence[Bar]]], pivot_window: int = 3
) -> dict[str, object]:
    """Measure the fixed emission filter across an ordered corpus."""

    if pivot_window < 1:
        raise ValueError("pivot_window must be >= 1")
    summaries: dict[str, object] = {}
    baseline_geometries: set[tuple[object, ...]] = set()
    retained_geometries: set[tuple[object, ...]] = set()
    suppressed_geometries: set[tuple[object, ...]] = set()
    final_cutoffs: list[dict[str, object]] = []
    total: dict[str, int] = {
        "prefixes_audited": 0,
        "baseline_support_lines": 0,
        "baseline_resistance_lines": 0,
        "retained_support_lines": 0,
        "retained_resistance_lines": 0,
        "suppressed_support_lines": 0,
        "suppressed_resistance_lines": 0,
        "post_anchor_bars_inspected": 0,
        "total_body_crossings": 0,
        "retained_line_with_crossing_count": 0,
        "suppressed_line_without_crossing_count": 0,
    }
    for window_key, bars in windows:
        summary, baseline, retained, suppressed, final = _scan_window(
            window_key, bars, pivot_window
        )
        summaries[window_key] = summary
        baseline_geometries |= baseline
        retained_geometries |= retained
        suppressed_geometries |= suppressed
        final_cutoffs.extend({"window": window_key, **item} for item in final)
        total["prefixes_audited"] += summary["prefixes_audited"]  # type: ignore[operator]
        for side in ("support", "resistance"):
            side_payload = summary["sides"][side]  # type: ignore[index]
            total[f"baseline_{side}_lines"] += side_payload[
                "baseline_boundary_available_count"
            ]  # type: ignore[operator]
            total[f"retained_{side}_lines"] += side_payload[
                "filtered_boundary_available_count"
            ]  # type: ignore[operator]
            total[f"suppressed_{side}_lines"] += side_payload["suppressed_count"]  # type: ignore[operator]
        for field in (
            "post_anchor_bars_inspected",
            "total_body_crossings",
            "retained_line_with_crossing_count",
            "suppressed_line_without_crossing_count",
        ):
            total[field] += summary[field]  # type: ignore[operator]

    baseline_count = (
        total["baseline_support_lines"] + total["baseline_resistance_lines"]
    )
    retained_count = (
        total["retained_support_lines"] + total["retained_resistance_lines"]
    )
    suppressed_count = (
        total["suppressed_support_lines"] + total["suppressed_resistance_lines"]
    )
    return {
        **total,
        "windows_audited": len(summaries),
        "total_baseline_lines": baseline_count,
        "total_retained_lines": retained_count,
        "total_suppressed_lines": suppressed_count,
        "suppression_fraction": suppressed_count / baseline_count,
        "unique_geometry_impact": {
            "baseline_geometries": len(baseline_geometries),
            "retained_geometries": len(retained_geometries),
            "suppressed_geometries": len(suppressed_geometries),
            "both_retained_and_suppressed_geometries": len(
                retained_geometries & suppressed_geometries
            ),
        },
        "window_summaries": summaries,
        "final_cutoffs": final_cutoffs,
    }


__all__ = [
    "FilteredLegacyResult",
    "FilteredSideResult",
    "audit_corpus",
    "audit_window",
    "filter_legacy_result",
    "filter_side_result",
    "geometry_key",
]
