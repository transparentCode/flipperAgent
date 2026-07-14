"""Compact Phase-D features derived only from persisted typed observations."""

from __future__ import annotations

import math
from typing import Any

from .contracts import (
    ContractValidationError,
    FamilyCorridor,
    FamilyInteractionEvent,
    FamilyInteractionObservation,
    TrendlineFamilyState,
    TrendlineFamilySnapshot,
)
from .events import compatibility_label


def build_interaction_features(
    snapshot: TrendlineFamilySnapshot,
    *,
    nearest_support_family_id: str | None,
    nearest_resistance_family_id: str | None,
    current_price: float | None = None,
) -> dict[str, Any]:
    """Expose nearest active role features without recomputing interaction semantics."""

    observations: dict[str, FamilyInteractionObservation] = {}
    for observation in snapshot.observations:
        if observation.family_id in observations:
            raise ContractValidationError("interaction features require exactly one observation per family")
        observations[observation.family_id] = observation
    events: dict[str, FamilyInteractionEvent] = {}
    for event in getattr(snapshot, "interaction_events", ()):
        if event.family_id in events:
            raise ContractValidationError("interaction features require at most one event per family")
        events[event.family_id] = event
    corridors: dict[str, FamilyCorridor] = {}
    for corridor in getattr(snapshot, "corridors", ()):
        if corridor.family_id in corridors:
            raise ContractValidationError("interaction features require at most one corridor per family")
        corridors[corridor.family_id] = corridor
    families: dict[str, TrendlineFamilyState] = {
        family.family_id: family
        for family in snapshot.active_families + snapshot.dormant_families
    }
    support = observations.get(nearest_support_family_id) if nearest_support_family_id else None
    resistance = observations.get(nearest_resistance_family_id) if nearest_resistance_family_id else None
    _validate_external_current_price(current_price, observations.values())
    all_corridors = tuple(corridors.values())
    return {
        "trendline_family_event_count": len(getattr(snapshot, "interaction_events", ())),
        "trendline_family_event_transition_count": len(
            getattr(snapshot, "interaction_event_transitions", ())
        ),
        **_role_features("support", support, events.get(nearest_support_family_id) if nearest_support_family_id else None),
        **_role_features("resistance", resistance, events.get(nearest_resistance_family_id) if nearest_resistance_family_id else None),
        "trendline_family_corridor_count": len(all_corridors),
        "trendline_family_singleton_count": sum(corridor.rail_count == 1 for corridor in all_corridors),
        "trendline_family_multi_rail_count": sum(corridor.rail_count > 1 for corridor in all_corridors),
        "trendline_family_total_rail_count": sum(corridor.rail_count for corridor in all_corridors),
        **_corridor_features(
            "support",
            families.get(nearest_support_family_id) if nearest_support_family_id else None,
            corridors.get(nearest_support_family_id) if nearest_support_family_id else None,
            observation=support,
            normalization_atr=snapshot.diagnostics.get("normalization_atr"),
        ),
        **_corridor_features(
            "resistance",
            families.get(nearest_resistance_family_id) if nearest_resistance_family_id else None,
            corridors.get(nearest_resistance_family_id) if nearest_resistance_family_id else None,
            observation=resistance,
            normalization_atr=snapshot.diagnostics.get("normalization_atr"),
        ),
    }


def _corridor_features(
    prefix: str,
    family: TrendlineFamilyState | None,
    corridor: FamilyCorridor | None,
    *,
    observation: FamilyInteractionObservation | None,
    normalization_atr: Any,
) -> dict[str, Any]:
    keys = (
        "rail_count",
        "ordered_member_ids",
        "representative_member_id",
        "corridor_lower_price",
        "corridor_upper_price",
        "corridor_width_atr",
        "max_adjacent_gap_atr",
        "median_adjacent_gap_atr",
        "spacing_stability",
        "nearest_rail_member_id",
        "nearest_rail_distance_atr",
        "current_corridor_position",
    )
    if family is None or corridor is None:
        return {f"{prefix}_{key}": None for key in keys}
    values: dict[str, Any] = {
        f"{prefix}_rail_count": corridor.rail_count,
        f"{prefix}_ordered_member_ids": corridor.ordered_member_ids,
        f"{prefix}_representative_member_id": corridor.representative_member_id,
        f"{prefix}_corridor_lower_price": corridor.lower_price,
        f"{prefix}_corridor_upper_price": corridor.upper_price,
        f"{prefix}_corridor_width_atr": corridor.width_atr,
        f"{prefix}_max_adjacent_gap_atr": corridor.max_adjacent_gap_atr,
        f"{prefix}_median_adjacent_gap_atr": corridor.median_adjacent_gap_atr,
        f"{prefix}_spacing_stability": corridor.spacing_stability,
        f"{prefix}_nearest_rail_member_id": None,
        f"{prefix}_nearest_rail_distance_atr": None,
        f"{prefix}_current_corridor_position": None,
    }
    if observation is None or observation.close_price is None:
        return values
    if not isinstance(normalization_atr, (int, float)) or isinstance(normalization_atr, bool) or normalization_atr <= 0.0:
        return values
    nearest = min(
        corridor.rails,
        key=lambda rail: (abs(observation.close_price - rail.projected_price), rail.member_id),
    )
    values[f"{prefix}_nearest_rail_member_id"] = nearest.member_id
    values[f"{prefix}_nearest_rail_distance_atr"] = (
        abs(observation.close_price - nearest.projected_price) / float(normalization_atr)
    )
    if corridor.width_absolute > 0.0:
        # Unclamped: values below 0 or above 1 explicitly mean price is outside.
        values[f"{prefix}_current_corridor_position"] = (
            (observation.close_price - corridor.lower_price) / corridor.width_absolute
        )
    return values


def _validate_external_current_price(
    current_price: float | None,
    observations: Any,
) -> None:
    """Keep the legacy argument as an assertion, never a semantic input."""

    if current_price is None:
        return
    if (
        isinstance(current_price, bool)
        or not isinstance(current_price, (int, float))
        or not math.isfinite(float(current_price))
    ):
        raise ContractValidationError("current_price assertion must be a finite numeric value")
    for observation in observations:
        if observation.close_price is None:
            continue
        if not math.isclose(
            float(current_price),
            observation.close_price,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ContractValidationError(
                "current_price assertion must match persisted observation close_price"
            )


def _role_features(
    prefix: str,
    observation: FamilyInteractionObservation | None,
    event: FamilyInteractionEvent | None,
) -> dict[str, Any]:
    if observation is None:
        features = {
            f"distance_to_{prefix}_line_atr": None,
            f"distance_to_{prefix}_zone_atr": None,
            f"{prefix}_interaction_state": None,
            f"{prefix}_wick_penetration_atr": None,
            f"{prefix}_body_penetration_atr": None,
            f"{prefix}_close_penetration_atr": None,
        }
    else:
        features = {
            f"distance_to_{prefix}_line_atr": observation.distance_to_line_atr,
            f"distance_to_{prefix}_zone_atr": observation.distance_to_zone_atr,
            f"{prefix}_interaction_state": observation.state.value,
            f"{prefix}_wick_penetration_atr": observation.wick_penetration_atr,
            f"{prefix}_body_penetration_atr": observation.body_penetration_atr,
            f"{prefix}_close_penetration_atr": observation.close_penetration_atr,
        }
    features.update(_event_features(prefix, event))
    return features


def _event_features(prefix: str, event: FamilyInteractionEvent | None) -> dict[str, Any]:
    keys = (
        "event_id",
        "event_state",
        "event_age_bars",
        "event_bars_in_state",
        "pressure_bars",
        "close_beyond_streak",
        "retest_age_bars",
        "max_wick_penetration_atr",
        "max_body_penetration_atr",
        "max_close_penetration_atr",
        "pending_role_reversal",
        "event_compatibility_label",
    )
    if event is None:
        return {f"{prefix}_{key}": None for key in keys}
    return {
        f"{prefix}_event_id": event.event_id,
        f"{prefix}_event_state": event.state.value,
        f"{prefix}_event_age_bars": event.age_bars,
        f"{prefix}_event_bars_in_state": event.bars_in_state,
        f"{prefix}_pressure_bars": event.pressure_bars,
        f"{prefix}_close_beyond_streak": event.close_beyond_streak,
        f"{prefix}_retest_age_bars": event.retest_age_bars,
        f"{prefix}_max_wick_penetration_atr": event.max_wick_penetration_atr,
        f"{prefix}_max_body_penetration_atr": event.max_body_penetration_atr,
        f"{prefix}_max_close_penetration_atr": event.max_close_penetration_atr,
        f"{prefix}_pending_role_reversal": event.pending_role_reversal,
        f"{prefix}_event_compatibility_label": (
            None if compatibility_label(event) is None else compatibility_label(event).value
        ),
    }
