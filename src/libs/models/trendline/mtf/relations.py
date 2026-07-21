"""Deterministic MTF pair relations and finite intersections."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Mapping

from ..domain.geometry import LineGeometry
from ..domain.identity import deterministic_id
from .contracts import (
    MTFNormalizationContext,
    MTFPolicyAudit,
    MTFRelation,
    MTFRelationType,
    ProjectedMTFFamily,
    _FLOAT_TOLERANCE,
    _close,
)

def _corridor_overlap(left: ProjectedMTFFamily, right: ProjectedMTFFamily) -> float:
    lower = max(left.projected_corridor_lower_price, right.projected_corridor_lower_price)
    upper = min(left.projected_corridor_upper_price, right.projected_corridor_upper_price)
    overlap = max(upper - lower, 0.0)
    widths = (
        left.projected_corridor_upper_price - left.projected_corridor_lower_price,
        right.projected_corridor_upper_price - right.projected_corridor_lower_price,
    )
    if widths[0] == 0.0 and widths[1] == 0.0:
        return 1.0 if _close(left.projected_representative_price, right.projected_representative_price) else 0.0
    nonzero = [width for width in widths if width > 0.0]
    if overlap == 0.0:
        return 0.0
    return min(overlap / min(nonzero), 1.0)


def _level_separation(left: ProjectedMTFFamily, right: ProjectedMTFFamily, atr: float) -> float:
    return abs(left.projected_representative_price - right.projected_representative_price) / atr


def _corridor_separation(left: ProjectedMTFFamily, right: ProjectedMTFFamily, atr: float) -> float:
    return max(
        left.projected_corridor_lower_price - right.projected_corridor_upper_price,
        right.projected_corridor_lower_price - left.projected_corridor_upper_price,
        0.0,
    ) / atr


def _is_nested(left: ProjectedMTFFamily, right: ProjectedMTFFamily) -> bool:
    left_inside_right = left.projected_corridor_lower_price >= right.projected_corridor_lower_price and left.projected_corridor_upper_price <= right.projected_corridor_upper_price
    right_inside_left = right.projected_corridor_lower_price >= left.projected_corridor_lower_price and right.projected_corridor_upper_price <= left.projected_corridor_upper_price
    return (left_inside_right or right_inside_left) and not (
        _close(left.projected_corridor_lower_price, right.projected_corridor_lower_price)
        and _close(left.projected_corridor_upper_price, right.projected_corridor_upper_price)
    )


def _finite_intersection(
    left: LineGeometry,
    right: LineGeometry,
    *,
    decision_timestamp: datetime,
    horizon_seconds: float,
) -> tuple[datetime, float, float] | None:
    denominator = left.slope_per_second - right.slope_per_second
    if abs(denominator) <= 1e-15:
        return None
    left_reference = left.reference_time.timestamp()
    right_reference = right.reference_time.timestamp()
    seconds = (
        right.reference_price - left.reference_price
        + left.slope_per_second * left_reference
        - right.slope_per_second * right_reference
    ) / denominator
    if not math.isfinite(seconds):
        return None
    timestamp = datetime.fromtimestamp(seconds, tz=timezone.utc)
    delta = (timestamp - decision_timestamp).total_seconds()
    price = left.value_at(timestamp)
    if not math.isfinite(price) or delta < 0.0 or delta > horizon_seconds:
        return None
    return timestamp, delta, price


def _build_relations(
    *,
    families: tuple[ProjectedMTFFamily, ...],
    geometries: Mapping[str, LineGeometry],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    policy: MTFPolicyAudit,
) -> tuple[MTFRelation, ...]:
    relations: list[MTFRelation] = []
    horizon = policy.intersection_horizon_bars * normalization_context.timeframe_duration_seconds
    for index, first in enumerate(families):
        for second in families[index + 1 :]:
            if first.source_timeframe == second.source_timeframe:
                continue
            left, right = sorted((first, second), key=lambda item: item.projected_family_id)
            level = _level_separation(left, right, normalization_context.atr)
            overlap = _corridor_overlap(left, right)
            separation = _corridor_separation(left, right, normalization_context.atr)
            slope = None if left.normalized_slope_atr_per_hour is None or right.normalized_slope_atr_per_hour is None else abs(left.normalized_slope_atr_per_hour - right.normalized_slope_atr_per_hour)
            intersection = _finite_intersection(
                geometries[left.projected_family_id], geometries[right.projected_family_id], decision_timestamp=decision_timestamp, horizon_seconds=horizon
            )
            stale = not left.contributes_to_confluence or not right.contributes_to_confluence
            compatible_slope = slope is not None and slope <= policy.max_slope_delta_atr_per_hour
            nearby = level <= policy.max_level_distance_atr
            corridor_nearby = overlap > 0.0 or separation <= policy.max_corridor_separation_atr
            conflict = left.source_family_role is not right.source_family_role and nearby and corridor_nearby
            if stale:
                relation_type, codes, severity = MTFRelationType.DISJOINT, ("stale_or_normalization_excluded",), None
            elif conflict:
                severity = min(1.0, (1.0 - min(level / max(policy.max_level_distance_atr, _FLOAT_TOLERANCE), 1.0)) * (0.5 + 0.5 * overlap))
                relation_type, codes = MTFRelationType.CONFLICT, ("opposite_role_nearby",)
            elif left.source_family_role is right.source_family_role and compatible_slope and nearby and _is_nested(left, right):
                relation_type, codes, severity = MTFRelationType.NESTED, ("same_role_nested_corridor",), None
            elif left.source_family_role is right.source_family_role and compatible_slope and nearby and corridor_nearby:
                relation_type = MTFRelationType.CONFLUENCE if overlap > 0.0 else MTFRelationType.AGREEMENT
                codes, severity = (("same_role_corridor_overlap",) if overlap > 0.0 else ("same_role_level_agreement",)), None
            elif left.source_family_role is right.source_family_role and slope is not None and slope > policy.max_slope_delta_atr_per_hour:
                relation_type, codes, severity = MTFRelationType.DIVERGENCE, ("same_role_slope_divergence",), None
            elif intersection is not None:
                relation_type, codes, severity = MTFRelationType.INTERSECTION, ("forward_exact_representative_intersection",), None
            else:
                relation_type, codes, severity = MTFRelationType.DISJOINT, ("no_compatible_relation",), None
            payload = {
                "relation_type": relation_type.value,
                "left_projected_family_id": left.projected_family_id,
                "right_projected_family_id": right.projected_family_id,
                "left_source_timeframe": left.source_timeframe,
                "right_source_timeframe": right.source_timeframe,
                "left_role": left.source_family_role.value,
                "right_role": right.source_family_role.value,
                "level_separation_atr": level,
                "corridor_overlap_ratio": overlap,
                "slope_disagreement_atr_per_hour": slope,
                "conflict_severity": severity,
                "intersection_timestamp": None if intersection is None else intersection[0],
                "intersection_seconds_from_decision": None if intersection is None else intersection[1],
                "intersection_price": None if intersection is None else intersection[2],
                "intersection_horizon_eligible": intersection is not None,
                "reason_codes": codes,
            }
            relations.append(MTFRelation(relation_id=deterministic_id("mtf-relation", payload), **payload))
    return tuple(sorted(relations, key=lambda item: item.relation_id))
