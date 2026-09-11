"""Offline evaluation helpers for RegimeV2."""

from libs.models.regime_v2.evaluation.candidate_export import (
    TrendCandidateExportConfig,
    TrendlineCandidateExportConfig,
    build_standard_feature_frame,
    export_builtin_trend_candidates,
    export_trendline_candidates,
)
from libs.models.regime_v2.evaluation.comparison import (
    RegimeComparisonConfig,
    RegimeComparisonResult,
    run_regime_comparison,
)
from libs.models.regime_v2.evaluation.downstream import (
    AblationMetric,
    DownstreamAblationConfig,
    DownstreamAblationResult,
    run_downstream_ablation,
)
from libs.models.regime_v2.evaluation.failure_diagnostics import (
    FailureDiagnosticConfig,
    diagnose_selection_overlay_failures,
    summarize_failure_diagnostics,
)
from libs.models.regime_v2.evaluation.overlay_validation import (
    OverlayWindowValidationConfig,
    run_overlay_window_validation,
)
from libs.models.regime_v2.evaluation.phase4_matrix import (
    HOLD_FOR_MORE_EVIDENCE,
    PROMOTE_TO_SHADOW_CANDIDATE,
    Phase4DecisionConfig,
    Phase4OverlayMatrixConfig,
    render_phase4_overlay_matrix_markdown,
    run_phase4_overlay_matrix,
    run_phase4_overlay_matrix_async,
    run_phase4_overlay_matrix_from_frames,
)
from libs.models.regime_v2.evaluation.selection_overlay import (
    RegimeV2TrendOverlayConfig,
    SelectionOverlayMetric,
    SelectionOverlayResult,
    run_regime_v2_trend_selection_overlay,
)
from libs.models.regime_v2.evaluation.trend_family import (
    TrendFamilyAblationConfig,
    TrendFamilyAblationResult,
    TrendFamilyMetric,
    run_trend_family_ablation,
)

__all__ = [
    "AblationMetric",
    "DownstreamAblationConfig",
    "DownstreamAblationResult",
    "FailureDiagnosticConfig",
    "RegimeComparisonConfig",
    "RegimeComparisonResult",
    "HOLD_FOR_MORE_EVIDENCE",
    "OverlayWindowValidationConfig",
    "PROMOTE_TO_SHADOW_CANDIDATE",
    "Phase4DecisionConfig",
    "Phase4OverlayMatrixConfig",
    "RegimeV2TrendOverlayConfig",
    "SelectionOverlayMetric",
    "SelectionOverlayResult",
    "TrendCandidateExportConfig",
    "TrendlineCandidateExportConfig",
    "TrendFamilyAblationConfig",
    "TrendFamilyAblationResult",
    "TrendFamilyMetric",
    "build_standard_feature_frame",
    "diagnose_selection_overlay_failures",
    "export_builtin_trend_candidates",
    "export_trendline_candidates",
    "run_downstream_ablation",
    "run_regime_comparison",
    "render_phase4_overlay_matrix_markdown",
    "run_overlay_window_validation",
    "run_phase4_overlay_matrix",
    "run_phase4_overlay_matrix_async",
    "run_phase4_overlay_matrix_from_frames",
    "run_regime_v2_trend_selection_overlay",
    "run_trend_family_ablation",
    "summarize_failure_diagnostics",
]
