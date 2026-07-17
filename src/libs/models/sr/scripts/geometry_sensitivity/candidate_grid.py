"""Canonical V1.8 candidate construction and effective SR configurations."""

from __future__ import annotations

from libs.models.sr.config.models import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
)
from libs.models.sr.domain.contracts import ContractValidationError

from .config import (
    APPROVED_PIVOT_SPANS,
    APPROVED_ZONE_HALF_WIDTHS,
    BASELINE_PIVOT_SPAN,
    BASELINE_ZONE_HALF_WIDTH,
    GeometrySensitivityConfig,
)
from .contracts import GeometryCandidate, TrialOverride


def build_candidate_grid(
    config: GeometrySensitivityConfig | None = None,
) -> tuple[GeometryCandidate, ...]:
    """Build exactly the predeclared Cartesian product in canonical order."""
    pivots = APPROVED_PIVOT_SPANS if config is None else config.pivot_span_bars
    widths = APPROVED_ZONE_HALF_WIDTHS if config is None else config.zone_half_width_atr
    if tuple(pivots) != APPROVED_PIVOT_SPANS or tuple(widths) != APPROVED_ZONE_HALF_WIDTHS:
        raise ContractValidationError("V1.8 candidate axes are immutable")
    candidates = tuple(
        GeometryCandidate(
            pivot_span_bars=pivot,
            zone_half_width_atr=width,
            baseline=(pivot, width) == (BASELINE_PIVOT_SPAN, BASELINE_ZONE_HALF_WIDTH),
            grid_position=(pivot_index, width_index),
        )
        for pivot_index, pivot in enumerate(APPROVED_PIVOT_SPANS)
        for width_index, width in enumerate(APPROVED_ZONE_HALF_WIDTHS)
    )
    if len(candidates) != 9 or len({item.candidate_id for item in candidates}) != 9:
        raise ContractValidationError("candidate grid is not unique")
    return candidates


def validate_candidate_grid(candidates: tuple[GeometryCandidate, ...]) -> None:
    expected = build_candidate_grid()
    if type(candidates) is not tuple or candidates != expected:
        raise ContractValidationError("candidate grid differs from the approved canonical matrix")


def baseline_candidate(candidates: tuple[GeometryCandidate, ...] | None = None) -> GeometryCandidate:
    values = build_candidate_grid() if candidates is None else candidates
    matches = tuple(item for item in values if item.baseline)
    if len(matches) != 1:
        raise ContractValidationError("candidate grid must have exactly one baseline")
    return matches[0]


def orthogonal_neighbors(
    candidate: GeometryCandidate,
    candidates: tuple[GeometryCandidate, ...] | None = None,
) -> tuple[GeometryCandidate, ...]:
    values = build_candidate_grid() if candidates is None else candidates
    return tuple(
        other for other in values
        if other.candidate_id != candidate.candidate_id
        and (
            abs(other.grid_position[0] - candidate.grid_position[0]) == 1
            and other.grid_position[1] == candidate.grid_position[1]
            or abs(other.grid_position[1] - candidate.grid_position[1]) == 1
            and other.grid_position[0] == candidate.grid_position[0]
        )
    )


def trial_overrides(candidate: GeometryCandidate) -> tuple[TrialOverride, ...]:
    return (
        TrialOverride("detection.pivot_span_bars", BASELINE_PIVOT_SPAN, candidate.pivot_span_bars),
        TrialOverride("detection.zone_half_width_atr", BASELINE_ZONE_HALF_WIDTH, candidate.zone_half_width_atr),
    )


def build_effective_config(
    base: ResolvedSRConfig,
    candidate: GeometryCandidate,
) -> ResolvedSRConfig:
    """Create a typed effective config without inventing production provenance."""
    if type(base) is not ResolvedSRConfig:
        raise ContractValidationError("base SR config must be exactly ResolvedSRConfig")
    if base.detection.pivot_span_bars == candidate.pivot_span_bars and base.detection.zone_half_width_atr == candidate.zone_half_width_atr:
        detection = base.detection
    else:
        detection = DetectionConfig(
            pivot_span_bars=candidate.pivot_span_bars,
            zone_half_width_atr=candidate.zone_half_width_atr,
        )
    return ResolvedSRConfig.create(
        version=base.version,
        asset=base.asset,
        timeframe=base.timeframe,
        detection=detection,
        association=AssociationConfig(base.association.merge_distance_atr),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=base.lifecycle.touch_tolerance_atr,
            break_buffer_atr=base.lifecycle.break_buffer_atr,
            break_confirm_closes=base.lifecycle.break_confirm_closes,
            max_age_bars=base.lifecycle.max_age_bars,
        ),
        runtime=RuntimeConfig(max_active_zones=base.runtime.max_active_zones),
        field_provenance=dict(base.field_provenance),
    )


__all__ = [
    "baseline_candidate", "build_candidate_grid", "build_effective_config", "orthogonal_neighbors",
    "trial_overrides", "validate_candidate_grid",
]
