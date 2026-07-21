"""Deterministic Phase-C structural and relevance ranking for active families."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from ..domain.enums import FamilyRole
from ..domain.families import TrendlineFamilyState


@dataclass(frozen=True)
class FamilyRank:
    family_id: str
    role: FamilyRole
    structural_importance: float
    current_relevance: float
    projected_distance: float


def structural_importance(family: TrendlineFamilyState) -> float:
    """Phase-C structural score: current representative structural confidence only."""

    return family.confidence


def current_relevance(
    family: TrendlineFamilyState,
    *,
    timestamp,
    current_price: float,
    atr: float | None,
) -> tuple[float, float]:
    distance = abs(family.representative.value_at(timestamp) - current_price)
    if atr is None or not math.isfinite(atr) or atr <= 0.0:
        return 0.0, distance
    return 1.0 / (1.0 + distance / atr), distance


def rank_families(
    families: Iterable[TrendlineFamilyState],
    *,
    timestamp,
    current_price: float,
    atr: float | None,
) -> tuple[FamilyRank, ...]:
    ranks = []
    for family in families:
        relevance, distance = current_relevance(
            family,
            timestamp=timestamp,
            current_price=current_price,
            atr=atr,
        )
        ranks.append(
            FamilyRank(
                family_id=family.family_id,
                role=family.current_role,
                structural_importance=structural_importance(family),
                current_relevance=relevance,
                projected_distance=distance,
            )
        )
    return tuple(sorted(ranks, key=lambda item: (-item.structural_importance, -item.current_relevance, item.family_id)))


def ranked_role_ids(ranks: Iterable[FamilyRank], role: FamilyRole) -> tuple[str, ...]:
    return tuple(rank.family_id for rank in ranks if rank.role is role)


def nearest_role_id(ranks: Iterable[FamilyRank], role: FamilyRole) -> str | None:
    eligible = [rank for rank in ranks if rank.role is role]
    if not eligible:
        return None
    return min(eligible, key=lambda item: (item.projected_distance, item.family_id)).family_id
