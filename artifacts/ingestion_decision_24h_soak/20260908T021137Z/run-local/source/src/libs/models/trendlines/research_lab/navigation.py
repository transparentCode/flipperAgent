"""Recorded-position navigation for research-lab sessions."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from libs.models.trendlines.research_viewer import (
    TrendlineViewerSpec,
    build_trendlines_viewer_payload,
)
from libs.models.trendlines.workflows.research import (
    TrendlineEvidenceSelection,
    build_research_evidence_bundle,
)

from .contracts import TrendlineResearchLabContractError, TrendlineResearchLabSelection


def default_selection_position(session: Any, timeframe: str) -> tuple[int, str]:
    """Choose latest valid geometry using the approved descriptive policy."""

    if timeframe not in session.prepared.spec.timeframes:
        raise TrendlineResearchLabContractError(
            f"timeframe {timeframe!r} is absent from prepared research"
        )
    rows = [
        row
        for row in session._diagnostics()["snapshot"]
        if row.timeframe == timeframe
    ]
    if not rows:
        raise TrendlineResearchLabContractError(
            f"no recorded snapshots for timeframe {timeframe}"
        )
    if session.controls.selection_policy == "latest_recorded":
        return rows[-1].position, "latest_recorded"
    complete = [
        row
        for row in rows
        if row.fit_valid
        and row.support_line_count > 0
        and row.resistance_line_count > 0
        and row.support_ray_count > 0
        and row.resistance_ray_count > 0
    ]
    if complete:
        return complete[-1].position, "latest_valid_point_with_both_line_and_ray_roles"
    any_geometry = [
        row
        for row in rows
        if row.fit_valid
        and (
            row.support_line_count
            or row.resistance_line_count
            or row.support_ray_count
            or row.resistance_ray_count
        )
    ]
    if any_geometry:
        return any_geometry[-1].position, "latest_valid_point_with_any_line_or_ray"
    return rows[-1].position, "final_recorded_point_no_valid_geometry"


def select_replay_position(
    session: Any,
    *,
    timeframe: str,
    position: int,
    viewer_lookback_bars: int | None = None,
) -> TrendlineResearchLabSelection:
    """Build selected evidence and payload without re-running replay."""

    if timeframe not in session.prepared.spec.timeframes:
        raise TrendlineResearchLabContractError(
            f"timeframe {timeframe!r} is absent from prepared research"
        )
    if isinstance(position, bool) or not isinstance(position, int):
        raise TrendlineResearchLabContractError("position must be an integer")
    recorded = session.replay.timeframes[timeframe].recorded_positions
    if position not in recorded:
        raise TrendlineResearchLabContractError(
            f"position {position} is not recorded for timeframe {timeframe}"
        )
    lookback = (
        session.controls.viewer_lookback_bars
        if viewer_lookback_bars is None
        else viewer_lookback_bars
    )
    viewer_spec = TrendlineViewerSpec(
        timeframe=timeframe,
        position=position,
        display_lookback_bars=lookback,
    )
    evidence_selection = TrendlineEvidenceSelection(
        timeframe=timeframe,
        position=position,
    )
    evidence_started = perf_counter()
    evidence = build_research_evidence_bundle(
        session.prepared,
        session.replay,
        selection=evidence_selection,
    )
    evidence_ms = (perf_counter() - evidence_started) * 1000.0
    payload_started = perf_counter()
    payload = build_trendlines_viewer_payload(
        session.prepared,
        session.replay,
        evidence,
        viewer_spec,
    )
    payload_ms = (perf_counter() - payload_started) * 1000.0
    coordinate = (timeframe, position)
    diagnostics = session._diagnostics()
    snapshot_rows = [row for row in diagnostics["snapshot"] if (row.timeframe, row.position) == coordinate]
    pivot_count_rows = [row for row in diagnostics["pivot_count"] if (row.timeframe, row.position) == coordinate]
    line_rows = tuple(row for row in evidence.line_rows if (row.timeframe, row.position) == coordinate)
    ray_rows = tuple(row for row in evidence.ray_rows if (row.timeframe, row.position) == coordinate)
    signal_rows = tuple(row for row in evidence.signal_rows if (row.timeframe, row.position) == coordinate)
    if len(snapshot_rows) != 1 or len(pivot_count_rows) != 1:
        raise TrendlineResearchLabContractError(
            "selected coordinate must have one snapshot and pivot-count row"
        )
    evidence_times = dict(session.timings.evidence_ms_by_timeframe)
    payload_times = dict(session.timings.viewer_payload_ms_by_timeframe)
    evidence_times[timeframe] = evidence_ms
    payload_times[timeframe] = payload_ms
    session._replace_timings(
        evidence_ms_by_timeframe=evidence_times,
        viewer_payload_ms_by_timeframe=payload_times,
    )
    return TrendlineResearchLabSelection(
        timeframe=timeframe,
        position=position,
        selection_reason="explicit_recorded_position",
        point=session.replay.output_at(timeframe, position),
        snapshot_row=snapshot_rows[0],
        pivot_count_row=pivot_count_rows[0],
        selected_pivots=tuple(evidence.selected_pivots),
        line_rows=line_rows,
        ray_rows=ray_rows,
        signal_rows=signal_rows,
        evidence_bundle=evidence,
        viewer_payload=payload,
    )


__all__ = ["default_selection_position", "select_replay_position"]
