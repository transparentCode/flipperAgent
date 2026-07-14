"""Derived Phase-G family corridors built only from persisted exact member rails."""

from __future__ import annotations

from datetime import datetime
import math
from statistics import median, pstdev
from typing import Iterable

from .config import ResolvedTrendlineFamilyConfig
from .contracts import (
    FamilyCorridor,
    FamilyRailProjection,
    TrendlineFamilyState,
    deterministic_id,
    require_utc,
)


def build_family_corridors(
    families: Iterable[TrendlineFamilyState],
    *,
    timestamp: datetime,
    normalization_atr: float,
    config: ResolvedTrendlineFamilyConfig,
) -> tuple[FamilyCorridor, ...]:
    """Return one deterministic exact-rail corridor for every published family."""

    observed_at = require_utc(timestamp, field_name="corridor timestamp")
    if not math.isfinite(normalization_atr) or normalization_atr <= 0.0:
        raise ValueError("corridor normalization_atr must be finite and positive")
    corridors = tuple(
        _build_family_corridor(
            family,
            timestamp=observed_at,
            normalization_atr=normalization_atr,
            config=config,
        )
        for family in sorted(families, key=lambda item: item.family_id)
    )
    return tuple(sorted(corridors, key=lambda item: (item.family_id, item.corridor_id)))


def _build_family_corridor(
    family: TrendlineFamilyState,
    *,
    timestamp: datetime,
    normalization_atr: float,
    config: ResolvedTrendlineFamilyConfig,
) -> FamilyCorridor:
    representative_price = family.representative.value_at(timestamp)
    ordered = tuple(
        sorted(
            (
                (member.geometry.value_at(timestamp), member.member_id)
                for member in family.members
            ),
            key=lambda item: item,
        )
    )
    projections = tuple(
        FamilyRailProjection(
            member_id=member_id,
            order_index=index,
            projected_price=price,
            offset_from_representative_atr=(price - representative_price)
            / normalization_atr,
        )
        for index, (price, member_id) in enumerate(ordered)
    )
    prices = tuple(price for price, _ in ordered)
    gaps = tuple(
        (prices[index + 1] - prices[index]) / normalization_atr
        for index in range(len(prices) - 1)
    )
    if gaps:
        max_gap = max(gaps)
        median_gap = median(gaps)
        coefficient_of_variation = pstdev(gaps) / median_gap if median_gap > 0.0 else math.inf
        spacing_stability = 1.0 / (1.0 + coefficient_of_variation)
    else:
        max_gap = None
        median_gap = None
        spacing_stability = None
    lower_price = prices[0]
    upper_price = prices[-1]
    width_absolute = upper_price - lower_price
    identity_payload = {
        "family_id": family.family_id,
        "asset": family.asset,
        "timeframe": family.timeframe,
        "timestamp": timestamp,
        "role": family.current_role.value,
        "ordered_member_ids": tuple(member_id for _, member_id in ordered),
        "representative_member_id": family.representative_member_id,
        "representative_slope_per_second": family.representative.slope_per_second,
        "lower_price": lower_price,
        "upper_price": upper_price,
        "center_price": representative_price,
        "width_absolute": width_absolute,
        "width_atr": width_absolute / normalization_atr,
        "rail_count": len(projections),
        "max_adjacent_gap_atr": max_gap,
        "median_adjacent_gap_atr": median_gap,
        "spacing_stability": spacing_stability,
        "rails": tuple(projection.to_dict() for projection in projections),
        "center_policy": "representative_exact_rail_v1",
        "model_version": config.model_version,
        "config_version": config.config_version,
        "resolved_config_hash": config.resolved_config_hash,
    }
    return FamilyCorridor(
        corridor_id=deterministic_id("family-corridor", identity_payload),
        family_id=family.family_id,
        asset=family.asset,
        timeframe=family.timeframe,
        timestamp=timestamp,
        role=family.current_role,
        ordered_member_ids=tuple(member_id for _, member_id in ordered),
        representative_member_id=family.representative_member_id,
        representative_slope_per_second=family.representative.slope_per_second,
        lower_price=lower_price,
        upper_price=upper_price,
        center_price=representative_price,
        width_absolute=width_absolute,
        width_atr=width_absolute / normalization_atr,
        rail_count=len(projections),
        max_adjacent_gap_atr=max_gap,
        median_adjacent_gap_atr=median_gap,
        spacing_stability=spacing_stability,
        rails=projections,
        center_policy="representative_exact_rail_v1",
        model_version=config.model_version,
        config_version=config.config_version,
        resolved_config_hash=config.resolved_config_hash,
    )
