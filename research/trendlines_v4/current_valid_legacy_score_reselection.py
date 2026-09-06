"""Measure current-valid re-selection from unchanged legacy DP endpoints."""

from __future__ import annotations

from collections import namedtuple
from collections.abc import Sequence
from statistics import median

from research.trendlines_v4.legacy_pathfinding_reference import (
    Bar,
    SidePathResult,
    _build_line,
    analyze_legacy,
)
from research.trendlines_v4.post_anchor_filter_impact import geometry_key
from research.trendlines_v4.post_anchor_validity_audit import post_anchor_body_crossings

# fmt: off
PathPoint = tuple[int, float]
_INV = ("g1_pivot_inventory_mismatch", "g1_valid_edge_inventory_mismatch", "g1_dp_score_inventory_mismatch", "g1_predecessor_inventory_mismatch", "g5_selected_endpoint_absent_from_g1_inventory", "g5_selected_line_with_adverse_post_anchor_body_crossing", "g5_retained_geometry_altered_from_endpoint_path")
EndpointPathAudit = namedtuple("EndpointPathAudit", "endpoint_index dp_score path line post_anchor_crossings")
EndpointPathAudit.current_valid = property(lambda item: not item.post_anchor_crossings)
CurrentValidSideResult = namedtuple("CurrentValidSideResult", "baseline endpoint_paths g4_line selected_endpoint_index selected_dp_score selected_line")
CurrentValidSideResult.recovered_by_g5 = property(lambda item: item.g4_line is None and item.selected_line is not None)
CurrentValidSideResult.differs_from_g1 = property(lambda item: item.selected_line != item.baseline.emitted_line)

def _reconstruct_path(endpoint, prices, predecessors, positions):
    path, seen, cursor = [], set(), endpoint
    while cursor != -1:
        if cursor in seen or cursor not in prices or cursor not in predecessors:
            raise ValueError("invalid legacy predecessor state")
        seen.add(cursor)
        path.append((cursor, prices[cursor]))
        previous = predecessors[cursor]
        if previous != -1 and positions[previous] >= positions[cursor]:
            raise ValueError("legacy predecessor is not strictly earlier")
        cursor = previous
    path.reverse()
    if not path or path[-1][0] != endpoint:
        raise ValueError("reconstructed endpoint path has the wrong endpoint")
    return tuple(path)

def reselect_side_result(bars: Sequence[Bar], side_result: SidePathResult) -> CurrentValidSideResult:
    """Use only stored positive-score endpoint paths and original score order."""
    prices = dict(side_result.pivots)
    if len(prices) != len(side_result.pivots):
        raise ValueError("legacy pivot inventory contains a duplicate index")
    positions = {index: n for n, (index, _) in enumerate(side_result.pivots)}
    scores = dict(side_result.dp_scores)
    if len(scores) != len(side_result.dp_scores) or set(scores) != set(prices):
        raise ValueError("legacy score inventory does not match pivots")
    predecessors = dict(side_result.dp_predecessors)
    if len(predecessors) != len(side_result.dp_predecessors) or set(predecessors) != set(scores):
        raise ValueError("legacy predecessor inventory does not match scores")
    endpoints = []
    for endpoint, score in side_result.dp_scores:
        if score <= 0:
            continue
        path = _reconstruct_path(endpoint, prices, predecessors, positions)
        line = _build_line(path, len(bars) - 1)
        if line is None:
            raise ValueError("positive legacy endpoint has no emitted line")
        endpoints.append(
            EndpointPathAudit(
                endpoint,
                score,
                path,
                line,
                post_anchor_body_crossings(bars, line, side_result.side),
            )
        )
    if (
        _build_line(side_result.winning_path, len(bars) - 1)
        != side_result.emitted_line
    ):
        raise ValueError("G1 emitted line differs from its stored winning path")
    crossings = (
        ()
        if side_result.emitted_line is None
        else post_anchor_body_crossings(
            bars, side_result.emitted_line, side_result.side
        )
    )
    selected = max(
        (endpoint for endpoint in endpoints if endpoint.current_valid),
        key=lambda endpoint: endpoint.dp_score,
        default=None,
    )
    return CurrentValidSideResult(
        side_result,
        tuple(endpoints),
        None if crossings else side_result.emitted_line,
        None if selected is None else selected.endpoint_index,
        None if selected is None else selected.dp_score,
        None if selected is None else selected.line,
    )

def _runs(values):
    result, run = [], 0
    for value in values:
        if value:
            run += 1
        elif run:
            result.append(run)
            run = 0
    if run:
        result.append(run)
    return result

def _distribution(values):
    if not values:
        return {"count": 0, "minimum": None, "median": None, "maximum": None}
    ordered = sorted(values)
    return dict(
        zip(
            ("count", "minimum", "median", "maximum"),
            (len(ordered), ordered[0], median(ordered), ordered[-1]),
        )
    )

def _recovery_summary(items):
    return dict(zip(["count", "score_gap", "endpoint_index_delta", "final_anchor_pair_changed_count"], (len(items), _distribution([item["score_gap"] for item in items]), _distribution([item["endpoint_index_delta"] for item in items]), sum(item["final_anchor_pair_changed"] for item in items))))

def _side_summary(state, eligible):
    runs = _runs(state[4])
    keys = ["eligible_prefix_count", "g1_boundary_available_count", "g4_boundary_available_count", "g5_boundary_available_count", "g4_suppressed_count", "g5_recovered_count", "g5_no_boundary_count", "g5_availability_fraction", "g5_no_boundary_run_count", "g5_no_boundary_run_lengths", "g5_maximum_no_boundary_run_length", "g1_no_boundary_run_lengths", "g5_validity_no_boundary_run_lengths"]
    values = (eligible, state[0], state[1], state[2], state[0] - state[1], state[2] - state[1], eligible - state[2], state[2] / eligible, len(runs), runs, max(runs, default=0), _runs(state[3]), _runs(state[5]))
    return dict(zip(keys, values))

def _scan_window(window, bars, pivot_window):
    states = {side: [0, 0, 0, [], [], []] for side in ("support", "resistance")}
    g1_geometries, g5_geometries = set(), set()
    recoveries, final_cutoffs, invariants = [], [], dict.fromkeys(_INV, 0)
    for prefix_length in range(1, len(bars) + 1):
        prefix = bars[:prefix_length]
        result = analyze_legacy(prefix, pivot_window)
        for original in (result.support, result.resistance):
            selected = reselect_side_result(prefix, original)
            for field, left, right in zip(
                _INV[:4],
                (original.pivots, original.valid_edges, original.dp_scores, original.dp_predecessors),
                (selected.baseline.pivots, selected.baseline.valid_edges, selected.baseline.dp_scores, selected.baseline.dp_predecessors),
            ):
                invariants[field] += left != right
            valid = [item for item in selected.endpoint_paths if item.current_valid]
            expected = max(valid, key=lambda item: item.dp_score, default=None)
            wanted = (None, None, None) if expected is None else (expected.endpoint_index, expected.dp_score, expected.line)
            if (
                selected.selected_endpoint_index,
                selected.selected_dp_score,
                selected.selected_line,
            ) != wanted:
                raise ValueError("G5 selection does not use the first maximum legacy score")
            side = original.side
            state = states[original.side]
            scores = dict(original.dp_scores)
            index = selected.selected_endpoint_index
            if selected.selected_line is not None and (
                index is None or index not in scores
            ):
                invariants[_INV[4]] += 1
            if selected.selected_line is not None and post_anchor_body_crossings(
                prefix, selected.selected_line, side
            ):
                invariants[_INV[5]] += 1
            endpoint = next((item for item in selected.endpoint_paths if item.endpoint_index == index), None)
            endpoint_line = None if endpoint is None else _build_line(endpoint.path, len(prefix) - 1)
            if selected.selected_line is not None and endpoint_line != selected.selected_line:
                invariants[_INV[6]] += 1
            baseline_line = original.emitted_line
            state[0] += baseline_line is not None
            state[1] += selected.g4_line is not None
            state[2] += selected.selected_line is not None
            state[3].append(baseline_line is None)
            state[4].append(selected.selected_line is None)
            state[5].append(
                baseline_line is not None and selected.selected_line is None
            )
            if baseline_line is not None:
                g1_geometries.add(geometry_key(window, side, baseline_line))
            if selected.selected_line is not None:
                g5_geometries.add(
                    geometry_key(window, side, selected.selected_line)
                )
            if selected.recovered_by_g5:
                if (
                    index is None
                    or selected.selected_dp_score is None
                    or len(original.winning_path) < 2
                ):
                    raise ValueError("recovery lacks endpoint or score provenance")
                selected_path = next(
                    item.path
                    for item in selected.endpoint_paths
                    if item.endpoint_index == index
                )
                original_endpoint = original.winning_path[-1][0]
                recoveries.append(
                    {
                        "score_gap": scores[original_endpoint]
                        - selected.selected_dp_score,
                        "endpoint_index_delta": index - original_endpoint,
                        "final_anchor_pair_changed": original.winning_path[-2:]
                        != selected_path[-2:],
                    }
                )
            if prefix_length == len(bars):
                final_cutoffs.append(
                    {
                        "window": window,
                        "side": side,
                        "g1_line_present": baseline_line is not None,
                        "g4_line_present": selected.g4_line is not None,
                        "g5_line_present": selected.selected_line is not None,
                        "g5_selected_endpoint_index": index,
                        "g5_selected_dp_score": selected.selected_dp_score,
                        "g5_differs_from_g1": selected.differs_from_g1,
                    }
                )
    return (
        {
            "prefixes_audited": len(bars),
            "sides": {
                side: _side_summary(state, len(bars))
                for side, state in states.items()
            },
            "recovery_characteristics": _recovery_summary(recoveries),
            "final_cutoffs": final_cutoffs,
        },
        g1_geometries,
        g5_geometries,
        recoveries,
        invariants,
    )

def audit_corpus(windows: Sequence[tuple[str, Sequence[Bar]]], pivot_window: int = 3) -> dict[str, object]:
    """Freeze aggregate G1/G4/G5 impact over an ordered corpus."""
    if pivot_window < 1: raise ValueError("pivot_window must be >= 1")
    totals = dict.fromkeys(["g1_support", "g1_resistance", "g4_support", "g4_resistance", "g5_support", "g5_resistance"], 0)
    summaries, final_cutoffs, recoveries = {}, [], []
    g1_geometries, g5_geometries, invariants = set(), set(), dict.fromkeys(_INV, 0)
    fields = {"g1": "g1_boundary_available_count", "g4": "g4_boundary_available_count", "g5": "g5_boundary_available_count"}
    for window, bars in windows:
        summary, g1, g5, window_recoveries, measured = _scan_window(window, bars, pivot_window)
        summaries[window] = {key: value for key, value in summary.items() if key != "final_cutoffs"}
        final_cutoffs.extend(summary["final_cutoffs"]); recoveries.extend(window_recoveries); g1_geometries |= g1; g5_geometries |= g5
        for field in _INV: invariants[field] += measured[field]
        for side in ("support", "resistance"):
            for prefix, field in fields.items(): totals[f"{prefix}_{side}"] += summary["sides"][side][field]
    bar_count = sum(len(bars) for _, bars in windows); opportunities = bar_count * 2
    g1 = totals["g1_support"] + totals["g1_resistance"]; g4 = totals["g4_support"] + totals["g4_resistance"]; g5 = totals["g5_support"] + totals["g5_resistance"]
    return dict(zip(["windows_audited", "prefixes_audited", "total_side_cutoff_opportunities", "g1_support_lines", "g1_resistance_lines", "g1_emitted_decisions", "g4_retained_decisions", "g5_emitted_decisions", "g4_suppressed_decisions", "g5_recovered_decisions", "g5_remaining_no_boundary_decisions", "g5_availability_fraction", "g5_support_availability_fraction", "g5_resistance_availability_fraction", "recovery_characteristics", "unique_geometry_impact", "invariants", "window_summaries", "final_cutoffs"], (len(windows), bar_count, opportunities, totals["g1_support"], totals["g1_resistance"], g1, g4, g5, g1 - g4, len(recoveries), opportunities - g5, g5 / opportunities, totals["g5_support"] / bar_count, totals["g5_resistance"] / bar_count, _recovery_summary(recoveries), {"g1_exposed_geometries": len(g1_geometries), "g5_exposed_geometries": len(g5_geometries), "g5_geometries_already_exposed_by_g1": len(g5_geometries & g1_geometries), "g5_geometries_never_globally_exposed_by_g1": len(g5_geometries - g1_geometries)}, invariants, summaries, final_cutoffs)))
# fmt: on

__all__ = [
    "CurrentValidSideResult",
    "EndpointPathAudit",
    "audit_corpus",
    "reselect_side_result",
]
