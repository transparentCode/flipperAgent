"""Research-only source, split, null, metric, and evidence helpers."""

from .artifacts import ResearchArtifact, write_research_artifact
from .consumption import (
    claim_consumption,
    finalize_consumption,
    verify_consumption_claim,
)
from .labels import label_candidates, target_provenance_fingerprint
from .metrics import compare_against_nulls, evaluate_observations
from .observations import (
    STRATA_FIELD_ATTRIBUTES,
    ResearchObservation,
    canonical_issuance_calendar_block,
    canonical_matching_strata,
    validate_issuance_calendar_block,
)
from .placebos import (
    FEASIBLE_RANDOM_PRICE_ID,
    FeasibleRandomPriceNull,
    build_feasible_random_price_null,
    build_random_price_nulls,
    build_shuffled_time_nulls,
    matched_random_price_placebos,
)
from .source import (
    ProtectedManifest,
    ProtectedManifestFile,
    SourceBarRecord,
    SourceManifest,
    load_protected_manifest,
    load_source_jsonl,
)
from .splits import ChronologicalSplits, purge_lineage_intervals, validate_splits
from .studies import (
    ProtectedEvaluationEvidence,
    StudyResult,
    TrialConfig,
    build_protected_evaluation,
    evaluate_conclusion_gates,
    load_trial_config,
    run_phase1_study,
    run_protected_phase1_evaluation,
)

__all__ = [
    "FEASIBLE_RANDOM_PRICE_ID",
    "STRATA_FIELD_ATTRIBUTES",
    "ChronologicalSplits",
    "FeasibleRandomPriceNull",
    "ProtectedEvaluationEvidence",
    "ProtectedManifest",
    "ProtectedManifestFile",
    "ResearchArtifact",
    "ResearchObservation",
    "SourceBarRecord",
    "SourceManifest",
    "StudyResult",
    "TrialConfig",
    "build_feasible_random_price_null",
    "build_protected_evaluation",
    "build_random_price_nulls",
    "build_shuffled_time_nulls",
    "canonical_issuance_calendar_block",
    "canonical_matching_strata",
    "claim_consumption",
    "compare_against_nulls",
    "evaluate_conclusion_gates",
    "evaluate_observations",
    "finalize_consumption",
    "label_candidates",
    "load_protected_manifest",
    "load_source_jsonl",
    "load_trial_config",
    "matched_random_price_placebos",
    "purge_lineage_intervals",
    "run_phase1_study",
    "run_protected_phase1_evaluation",
    "target_provenance_fingerprint",
    "validate_issuance_calendar_block",
    "validate_splits",
    "verify_consumption_claim",
    "write_research_artifact",
]
