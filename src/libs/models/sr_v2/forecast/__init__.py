"""Research-only causal event targets.

Forecast issuance and calibration modules are intentionally not part of the
active SR v2 tree. The target function remains here for the research label
contract and is never imported by structural runtime code.
"""

from .targets import (
    REFERENCE_VOLATILITY_ID,
    SCIENTIFIC_TARGET_SCHEMA,
    TARGET_SCHEMA,
    ResolvedTargetSpec,
    ScientificReaction,
    ScientificTargetResult,
    TargetObservation,
    TargetReferenceVolatility,
    TwoStageTargetView,
    compute_target_reference_volatility,
    label_forecast,
    label_scientific_target,
    label_scientific_target_indexed,
    resolve_target_spec,
    scientific_target_fingerprint,
    target_fingerprint,
)

__all__ = [
    "REFERENCE_VOLATILITY_ID",
    "SCIENTIFIC_TARGET_SCHEMA",
    "TARGET_SCHEMA",
    "ResolvedTargetSpec",
    "ScientificReaction",
    "ScientificTargetResult",
    "TargetObservation",
    "TargetReferenceVolatility",
    "TwoStageTargetView",
    "compute_target_reference_volatility",
    "label_forecast",
    "label_scientific_target",
    "label_scientific_target_indexed",
    "resolve_target_spec",
    "scientific_target_fingerprint",
    "target_fingerprint",
]
