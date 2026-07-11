"""Optimization scaffolding for RegimeProbV1."""

from libs.models.regime_prob_v1.optimization.batch_optimize import (
    expand_manifest_runs,
    load_manifest,
    run_manifest,
)
from libs.models.regime_prob_v1.optimization.objective import (
    MODEL_NAME,
    REJECTED_TRIAL_SCORE,
    STUDY_DEFAULTS,
    build_decision_frame,
    evaluate_oos,
    format_deploy_params,
    make_objective,
    post_process_params,
)
from libs.models.regime_prob_v1.optimization.optimize import run_study
from libs.models.regime_prob_v1.optimization.params import (
    ProfileName,
    REGIME_PROB_OPTIMIZATION_PROFILES,
    RegimeProbParamSpec,
    extract_profile_defaults,
    get_optimization_param_schema,
)
from libs.models.regime_prob_v1.optimization.reports import (
    build_promotion_gate,
    render_markdown_report,
    summarize_oos_delta,
)
from libs.models.regime_prob_v1.optimization.threshold_sweep import (
    DEFAULT_THRESHOLD_PARAMS,
    run_threshold_sweep,
)
from libs.models.regime_prob_v1.optimization.validation import (
    RegimeProbObjectiveWeights,
    RegimeProbOptimizationGates,
    RegimeProbRollingValidationConfig,
    RegimeProbValidationResult,
    RegimeProbWindowMetric,
    compare_oos_gate,
    evaluate_regime_prob_frame,
)

__all__ = [
    "DEFAULT_THRESHOLD_PARAMS",
    "MODEL_NAME",
    "ProfileName",
    "REJECTED_TRIAL_SCORE",
    "REGIME_PROB_OPTIMIZATION_PROFILES",
    "STUDY_DEFAULTS",
    "RegimeProbObjectiveWeights",
    "RegimeProbOptimizationGates",
    "RegimeProbParamSpec",
    "RegimeProbRollingValidationConfig",
    "RegimeProbValidationResult",
    "RegimeProbWindowMetric",
    "build_decision_frame",
    "build_promotion_gate",
    "compare_oos_gate",
    "evaluate_oos",
    "evaluate_regime_prob_frame",
    "expand_manifest_runs",
    "extract_profile_defaults",
    "format_deploy_params",
    "get_optimization_param_schema",
    "load_manifest",
    "make_objective",
    "post_process_params",
    "render_markdown_report",
    "run_manifest",
    "run_study",
    "run_threshold_sweep",
    "summarize_oos_delta",
]
