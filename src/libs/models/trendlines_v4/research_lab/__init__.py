"""Notebook-friendly facade for the Trendlines V4 research lab."""

from .data import (
    analyze_frame,
    analyze_frames,
    fetch_native_window,
    fetch_native_window_async,
    frame_to_trendline_bars,
    normalize_native_frame,
    snapshot_json,
    snapshot_payload,
    snapshot_to_payload,
)
from .diagnostics import (
    compare_asset_frames,
    geometry_rows,
    pivot_consensus_rows,
    pivot_rows,
    role_transition_rows,
    snapshot_summary_rows,
)
from .replay import (
    build_causal_replay_payload,
    build_causal_scrolling_html,
    render_causal_replay_viewer,
    render_causal_scrolling_replay,
)
from .tvlc import (
    TVLC_CDN_URL,
    TVLC_VERSION,
    build_pivot_consensus_html,
    build_pivot_consensus_payload,
    build_tvlc_html,
    build_tvlc_html_from_payload,
    build_tvlc_payload,
    render_pivot_consensus_chart,
    render_tvlc_chart,
)

__all__ = [
    "TVLC_CDN_URL",
    "TVLC_VERSION",
    "analyze_frame",
    "analyze_frames",
    "build_causal_replay_payload",
    "build_causal_scrolling_html",
    "build_pivot_consensus_html",
    "build_pivot_consensus_payload",
    "build_tvlc_html",
    "build_tvlc_html_from_payload",
    "build_tvlc_payload",
    "compare_asset_frames",
    "fetch_native_window",
    "fetch_native_window_async",
    "frame_to_trendline_bars",
    "geometry_rows",
    "normalize_native_frame",
    "pivot_consensus_rows",
    "pivot_rows",
    "render_causal_replay_viewer",
    "render_causal_scrolling_replay",
    "render_pivot_consensus_chart",
    "render_tvlc_chart",
    "role_transition_rows",
    "snapshot_json",
    "snapshot_payload",
    "snapshot_summary_rows",
    "snapshot_to_payload",
]
