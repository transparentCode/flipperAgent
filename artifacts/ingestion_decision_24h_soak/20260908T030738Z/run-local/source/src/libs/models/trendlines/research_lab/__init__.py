"""Explicit package-local mature-trendlines research workbench APIs."""

from .comparison import (
    TrendlineLabSessionComparison,
    TrendlineReplayPositionComparison,
    compare_lab_sessions,
    compare_replay_positions,
)
from .contracts import (
    DEFAULT_SELECTION_POLICY,
    RESEARCH_LAB_SEMANTICS_VERSION,
    TrendlineResearchLabContractError,
    TrendlineResearchLabControls,
    TrendlineResearchLabSelection,
    TrendlineResearchLabTimings,
    TrendlineResearchStudyRegistry,
    binance_lab_controls,
    default_study_registry,
    injected_lab_controls,
    synthetic_lab_controls,
)
from .navigation import default_selection_position, select_replay_position
from .performance import elapsed_ms, timed_call
from .session import (
    TrendlineResearchLabSession,
    resolve_provider_call_count,
    run_research_lab,
)
from libs.models.trendlines.workflows.research import (
    TrendlineReplayWindow,
    TrendlineResearchReplaySpec,
)
from .tables import (
    lab_config_table,
    lab_controls_table,
    lab_export_table,
    lab_identity_table,
    lab_line_table,
    lab_performance_table,
    lab_pivot_count_table,
    lab_position_comparison_table,
    lab_ray_table,
    lab_replay_summary_table,
    lab_selected_pivot_table,
    lab_signal_history_table,
    lab_signal_table,
    lab_snapshot_timeline,
    lab_source_table,
    lab_study_registry_table,
)


__all__ = [
    "DEFAULT_SELECTION_POLICY",
    "RESEARCH_LAB_SEMANTICS_VERSION",
    "TrendlineLabSessionComparison",
    "TrendlineReplayPositionComparison",
    "TrendlineResearchLabContractError",
    "TrendlineResearchLabControls",
    "TrendlineResearchLabSelection",
    "TrendlineResearchLabSession",
    "TrendlineResearchLabTimings",
    "TrendlineResearchStudyRegistry",
    "TrendlineReplayWindow",
    "TrendlineResearchReplaySpec",
    "binance_lab_controls",
    "compare_lab_sessions",
    "compare_replay_positions",
    "default_selection_position",
    "default_study_registry",
    "elapsed_ms",
    "injected_lab_controls",
    "lab_config_table",
    "lab_controls_table",
    "lab_export_table",
    "lab_identity_table",
    "lab_line_table",
    "lab_performance_table",
    "lab_pivot_count_table",
    "lab_position_comparison_table",
    "lab_ray_table",
    "lab_replay_summary_table",
    "lab_selected_pivot_table",
    "lab_signal_history_table",
    "lab_signal_table",
    "lab_snapshot_timeline",
    "lab_source_table",
    "lab_study_registry_table",
    "run_research_lab",
    "resolve_provider_call_count",
    "select_replay_position",
    "synthetic_lab_controls",
    "timed_call",
]
