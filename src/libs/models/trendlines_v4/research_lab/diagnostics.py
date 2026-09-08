"""Factual tables and descriptive comparisons for the research notebook."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from libs.models.trendlines_v4.core_v2 import (
    HISTORY_CAPACITY_BARS,
    TrendlineBar,
    TrendlineSnapshotV2,
    _pivots,
)
from libs.models.trendlines_v4.engine.types import TrendlineGeometry
from research.trendlines_v4 import pivot_consensus_candidate_tape as f1a
from research.trendlines_v4 import pivot_consensus_selector_challenge as f1b

from .data import (
    _bounded_bars,
    _timestamp_text,
    analyze_frame,
    frame_to_trendline_bars,
    normalize_native_frame,
)


def snapshot_summary_rows(
    snapshots: Mapping[str, TrendlineSnapshotV2] | TrendlineSnapshotV2,
    *,
    timeframe: str | None = None,
    asset: str | None = None,
) -> tuple[dict[str, Any], ...]:
    if isinstance(snapshots, TrendlineSnapshotV2):
        if timeframe is None:
            raise ValueError("timeframe is required for one snapshot")
        items = ((timeframe, snapshots),)
    elif isinstance(snapshots, Mapping):
        items = tuple(snapshots.items())
    else:
        raise TypeError("snapshots must be a snapshot or mapping")

    rows = []
    for item_timeframe, snapshot in items:
        row: dict[str, Any] = {
            "timeframe": item_timeframe,
            "market_as_of": _timestamp_text(snapshot.market_as_of),
            "history_bar_count": snapshot.history_bar_count,
            "pivot_window": snapshot.pivot_window,
        }
        if asset is not None:
            row["asset"] = asset
        for side_name in ("support", "resistance"):
            side = getattr(snapshot, side_name)
            row[f"{side_name}_structural_available"] = side.structural is not None
            row[f"{side_name}_current_valid_available"] = side.current_valid is not None
            row[f"{side_name}_secondary_available"] = side.secondary is not None
        rows.append(row)
    return tuple(rows)


def _line_rows(
    bars: tuple[TrendlineBar, ...],
    snapshot: TrendlineSnapshotV2,
    timeframe: str,
) -> tuple[dict[str, Any], ...]:
    close = bars[-1].close
    rows: list[dict[str, Any]] = []
    for side_name in ("support", "resistance"):
        side = getattr(snapshot, side_name)
        entries: list[tuple[str, TrendlineGeometry]] = []
        if side.same_geometry and side.structural is not None:
            entries.append(("structural + current_valid", side.structural))
        else:
            if side.structural is not None:
                entries.append(("structural", side.structural))
            if side.current_valid is not None:
                entries.append(("current_valid", side.current_valid))
        if side.secondary is not None and side.secondary not in {
            line for _, line in entries
        }:
            entries.append(("secondary", side.secondary))
        for role, line in entries:
            rows.append(
                {
                    "timeframe": timeframe,
                    "side": side_name,
                    "role": role,
                    "start_anchor_at": _timestamp_text(line.start_anchor_at),
                    "start_price": line.start_anchor_price,
                    "end_anchor_at": _timestamp_text(line.end_anchor_at),
                    "end_price": line.end_anchor_price,
                    "slope_per_bar": line.slope_per_bar,
                    "projected_price_at_market_as_of": line.projected_price_at_market_as_of,
                    "projected_distance_bps": (
                        (line.projected_price_at_market_as_of / close - 1.0) * 10_000
                    ),
                    "post_anchor_body_cross_count": line.post_anchor_body_cross_count,
                    "projection_positive": line.projection_positive,
                    "same_geometry": side.same_geometry,
                }
            )
    return tuple(rows)


def geometry_rows(
    frame: pd.DataFrame,
    snapshot: TrendlineSnapshotV2,
    *,
    timeframe: str = "",
) -> tuple[dict[str, Any], ...]:
    return _line_rows(_bounded_bars(frame, snapshot), snapshot, timeframe)


def pivot_rows(
    frame: pd.DataFrame,
    *,
    timeframe: str = "",
) -> tuple[dict[str, Any], ...]:
    bars = frame_to_trendline_bars(frame)[-HISTORY_CAPACITY_BARS:]
    rows: list[dict[str, Any]] = []
    for side in ("support", "resistance"):
        for position, price in _pivots(bars, side):
            rows.append(
                {
                    "timeframe": timeframe,
                    "side": side,
                    "position": position,
                    "pivot_at": _timestamp_text(bars[position].closed_at),
                    "pivot_price": price,
                    "age_bars": len(bars) - 1 - position,
                }
            )
    return tuple(rows)


def _selected_pivot_consensus_candidates(
    frame: pd.DataFrame,
    snapshot: TrendlineSnapshotV2 | None = None,
) -> tuple[tuple[str, str, str, f1a.PivotConsensusCandidate | None], ...]:
    """Select the frozen F1B roles from the current causal model history."""

    bars = (
        _bounded_bars(frame, snapshot)
        if snapshot is not None
        else frame_to_trendline_bars(frame)[-HISTORY_CAPACITY_BARS:]
    )
    tape = f1a.build_candidate_tape(bars)
    selected: list[tuple[str, str, str, f1a.PivotConsensusCandidate | None]] = []
    for side in ("support", "resistance"):
        candidates = tape.candidates_for_side(side)
        if candidates:
            selected.extend(
                (
                    (
                        side,
                        "structural",
                        "span_first",
                        f1b.select_span_first(candidates),
                    ),
                    (
                        side,
                        "local",
                        "consensus_first",
                        f1b.select_consensus_first(candidates),
                    ),
                )
            )
        else:
            selected.extend(
                (
                    (side, "structural", "span_first", None),
                    (side, "local", "consensus_first", None),
                )
            )
    return tuple(selected)


def pivot_consensus_rows(
    frame: pd.DataFrame,
    snapshot: TrendlineSnapshotV2 | None = None,
    *,
    timeframe: str = "",
) -> tuple[dict[str, Any], ...]:
    """Return descriptive rows for the frozen span/local pivot-consensus roles."""

    market_as_of = (
        _timestamp_text(snapshot.market_as_of)
        if snapshot is not None
        else _timestamp_text(frame_to_trendline_bars(frame)[-1].closed_at)
    )
    rows: list[dict[str, Any]] = []
    for side, role, selector, candidate in _selected_pivot_consensus_candidates(
        frame, snapshot
    ):
        row: dict[str, Any] = {
            "timeframe": timeframe,
            "market_as_of": market_as_of,
            "family": "pivot_consensus",
            "side": side,
            "role": role,
            "selector": selector,
        }
        if candidate is None:
            row.update(
                {
                    "candidate_id": None,
                    "geometry_id": None,
                    "anchor_mode": None,
                    "start_anchor_at": None,
                    "start_anchor_price": None,
                    "end_anchor_at": None,
                    "end_anchor_price": None,
                    "anchor_span_bars": None,
                    "projected_price_at_market_as_of": None,
                    "non_anchor_evidence_count": 0,
                    "body_intersection_count": None,
                    "full_range_intersection_count": None,
                    "interaction_bar_count": None,
                    "body_intersection_rate": None,
                    "full_range_intersection_rate": None,
                    "observable_from_at": None,
                    "observable_from_index": None,
                }
            )
        else:
            interaction_bars = candidate.interaction_bar_count
            row.update(
                {
                    "candidate_id": candidate.candidate_id,
                    "geometry_id": candidate.geometry_id,
                    "anchor_mode": candidate.anchor_mode,
                    "start_anchor_at": _timestamp_text(candidate.start_pivot.at),
                    "start_anchor_price": candidate.start_price,
                    "end_anchor_at": _timestamp_text(candidate.end_pivot.at),
                    "end_anchor_price": candidate.end_price,
                    "anchor_span_bars": candidate.anchor_span_bars,
                    "projected_price_at_market_as_of": candidate.projected_price_at_market_as_of,
                    "non_anchor_evidence_count": len(candidate.non_anchor_evidence),
                    "body_intersection_count": candidate.body_intersection_count,
                    "full_range_intersection_count": candidate.full_range_intersection_count,
                    "interaction_bar_count": interaction_bars,
                    "body_intersection_rate": candidate.body_intersection_count
                    / interaction_bars,
                    "full_range_intersection_rate": candidate.full_range_intersection_count
                    / interaction_bars,
                    "observable_from_at": _timestamp_text(candidate.observable_from_at),
                    "observable_from_index": candidate.observable_from_index,
                }
            )
        rows.append(row)
    return tuple(rows)


def role_transition_rows(
    frame: pd.DataFrame,
    *,
    timeframe: str = "",
    end_positions: Sequence[int] | None = None,
    start_offset: int = 120,
    step_size: int = 6,
    steps: int = 30,
) -> tuple[dict[str, Any], ...]:
    normalized = normalize_native_frame(frame)
    positions = end_positions
    if positions is None:
        total = len(normalized)
        first = min(start_offset, total)
        positions = tuple(
            dict.fromkeys(
                min(first + index * step_size, total) for index in range(steps)
            )
        )
    previous: dict[tuple[str, str], tuple[Any, ...]] = {}
    rows: list[dict[str, Any]] = []
    for end_position in positions:
        prefix = normalized.iloc[:end_position].copy()
        snapshot = analyze_frame(prefix)
        current = {
            (row["side"], row["role"]): row
            for row in geometry_rows(prefix, snapshot, timeframe=timeframe)
        }
        for key, row in current.items():
            identity = (
                row["start_anchor_at"],
                row["end_anchor_at"],
                row["projected_price_at_market_as_of"],
            )
            rows.append(
                {
                    "cutoff": _timestamp_text(snapshot.market_as_of),
                    "market_as_of": _timestamp_text(snapshot.market_as_of),
                    "timeframe": timeframe,
                    "side": key[0],
                    "role": key[1],
                    "geometry_changed": previous.get(key) not in (None, identity),
                    "start_anchor_at": row["start_anchor_at"],
                    "end_anchor_at": row["end_anchor_at"],
                    "projected_price_at_market_as_of": row[
                        "projected_price_at_market_as_of"
                    ],
                    "post_anchor_body_cross_count": row["post_anchor_body_cross_count"],
                }
            )
            previous[key] = identity
    return tuple(rows)


def compare_asset_frames(
    asset_frames: Mapping[str, pd.DataFrame | Mapping[str, pd.DataFrame]],
    *,
    timeframe: str = "4h",
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for asset, value in asset_frames.items():
        frame = value[timeframe] if isinstance(value, Mapping) else value
        snapshot = analyze_frame(frame)
        rows.extend(snapshot_summary_rows(snapshot, timeframe=timeframe, asset=asset))
        for row in geometry_rows(frame, snapshot, timeframe=timeframe):
            rows.append({"asset": asset, **row})
    return tuple(rows)


__all__ = [
    "compare_asset_frames",
    "geometry_rows",
    "pivot_consensus_rows",
    "pivot_rows",
    "role_transition_rows",
    "snapshot_summary_rows",
]
