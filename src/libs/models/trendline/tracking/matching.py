"""Causal ATR-normalized, deterministic one-to-one family matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import TYPE_CHECKING, Iterable

import pandas as pd

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..domain.candidates import LineCandidate
from ..domain.families import TrendlineFamilyState
from ..domain.validation import ContractValidationError, require_utc

if TYPE_CHECKING:
    from .rails import RailCandidateGroup


NORMALIZATION_ATR_METHOD = "simple_true_range_mean_v1"


@dataclass(frozen=True)
class NormalizationAtr:
    value: float
    method: str
    sample_count: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or self.value <= 0.0:
            raise ContractValidationError("normalization ATR must be finite and positive")
        if not isinstance(self.method, str) or not self.method:
            raise ContractValidationError("normalization ATR method must be non-empty")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 1:
            raise ContractValidationError("normalization ATR sample_count must be a positive integer")


@dataclass(frozen=True)
class FamilyCandidateMatch:
    family_id: str
    candidate_id: str
    score: float
    projected_distance_atr: float
    slope_delta_atr_per_hour: float
    anchor_similarity: float

    def __post_init__(self) -> None:
        for name in ("family_id", "candidate_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"{name} must be a non-empty string")
        for name in ("score", "projected_distance_atr", "slope_delta_atr_per_hour", "anchor_similarity"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ContractValidationError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        if self.score > 1.0 or self.anchor_similarity > 1.0:
            raise ContractValidationError("match score and anchor similarity must be at most one")


@dataclass(frozen=True)
class FamilyRailGroupMatch:
    """One deterministic association between a previous family and rail group."""

    family_id: str
    group_id: str
    representative_candidate_id: str
    score: float
    projected_distance_atr: float
    slope_delta_atr_per_hour: float
    anchor_similarity: float
    member_continuation_count: int = 0
    representative_gate_passed: bool = False

    def __post_init__(self) -> None:
        for name in ("family_id", "group_id", "representative_candidate_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"{name} must be a non-empty string")
        for name in (
            "score",
            "projected_distance_atr",
            "slope_delta_atr_per_hour",
            "anchor_similarity",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ContractValidationError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        if self.score > 1.0 or self.anchor_similarity > 1.0:
            raise ContractValidationError("group match score and anchor similarity must be at most one")
        if (
            isinstance(self.member_continuation_count, bool)
            or not isinstance(self.member_continuation_count, int)
            or self.member_continuation_count < 0
        ):
            raise ContractValidationError("member_continuation_count must be a non-negative integer")
        if not isinstance(self.representative_gate_passed, bool):
            raise ContractValidationError("representative_gate_passed must be boolean")


def calculate_normalization_atr(ohlcv: pd.DataFrame, *, window: int) -> NormalizationAtr:
    """Compute a causal simple-mean true range from confirmed normalized bars."""

    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ContractValidationError("normalization ATR window must be an integer >= 1")
    if not isinstance(ohlcv, pd.DataFrame) or len(ohlcv) < 2:
        raise ContractValidationError("at least two confirmed bars are required for normalization ATR")
    required = {"high", "low", "close"}
    if required.difference(ohlcv.columns):
        raise ContractValidationError("normalization ATR requires high, low, and close columns")
    high = ohlcv["high"].astype(float).to_list()
    low = ohlcv["low"].astype(float).to_list()
    close = ohlcv["close"].astype(float).to_list()
    true_ranges = [high[0] - low[0]]
    for index in range(1, len(ohlcv)):
        true_ranges.append(
            max(
                high[index] - low[index],
                abs(high[index] - close[index - 1]),
                abs(low[index] - close[index - 1]),
            )
        )
    samples = true_ranges[-window:]
    value = sum(samples) / len(samples)
    return NormalizationAtr(value=value, method=NORMALIZATION_ATR_METHOD, sample_count=len(samples))


def score_family_candidate(
    family: TrendlineFamilyState,
    candidate: LineCandidate,
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
    reactivation: bool,
) -> FamilyCandidateMatch | None:
    """Score one causal association, returning ``None`` for any hard rejection."""

    observed_at = require_utc(timestamp, field_name="matching timestamp")
    if family.asset != config.asset or family.timeframe != config.timeframe:
        return None
    if candidate.asset != config.asset or candidate.timeframe != config.timeframe:
        return None
    if candidate.observed_at != observed_at or family.updated_at > observed_at:
        return None
    if candidate.metadata.get("model_version") != config.model_version:
        return None
    if candidate.metadata.get("config_version") != config.config_version:
        return None
    if candidate.metadata.get("resolved_config_hash") != config.resolved_config_hash:
        return None
    if family.current_role is not candidate.role:
        return None

    candidate_price = candidate.geometry.value_at(observed_at)
    family_price = family.representative.value_at(observed_at)
    projected_distance = abs(candidate_price - family_price) / atr.value
    slope_delta = abs(candidate.geometry.slope_per_second - family.representative.slope_per_second) * 3600.0 / atr.value
    matching = config.matching
    if projected_distance > matching.max_distance_atr or slope_delta > matching.max_slope_delta_atr_per_hour:
        return None

    representative_member = next(
        member
        for member in family.members
        if member.member_id == family.representative_member_id
    )
    family_anchor_ids = {anchor.anchor_id for anchor in representative_member.anchors}
    candidate_anchor_ids = {anchor.anchor_id for anchor in candidate.anchors}
    union = family_anchor_ids | candidate_anchor_ids
    anchor_similarity = len(family_anchor_ids & candidate_anchor_ids) / len(union) if union else 0.0
    level_similarity = _threshold_similarity(projected_distance, matching.max_distance_atr)
    slope_similarity = _threshold_similarity(slope_delta, matching.max_slope_delta_atr_per_hour)
    score = (
        matching.level_weight * level_similarity
        + matching.slope_weight * slope_similarity
        + matching.anchor_weight * anchor_similarity
        + matching.role_weight
    )
    required_score = max(
        matching.minimum_match_score,
        config.lifecycle.reactivation_min_score if reactivation else 0.0,
    )
    if score < required_score:
        return None
    return FamilyCandidateMatch(
        family_id=family.family_id,
        candidate_id=candidate.candidate_id,
        score=score,
        projected_distance_atr=projected_distance,
        slope_delta_atr_per_hour=slope_delta,
        anchor_similarity=anchor_similarity,
    )


def greedy_match_candidates(
    candidates: Iterable[LineCandidate],
    families: Iterable[TrendlineFamilyState],
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
    dormant_family_ids: set[str],
) -> tuple[FamilyCandidateMatch, ...]:
    """Return deterministic greedy one-to-one candidate/family assignments."""

    all_scores: list[FamilyCandidateMatch] = []
    for family in families:
        for candidate in candidates:
            match = score_family_candidate(
                family,
                candidate,
                timestamp=timestamp,
                atr=atr,
                config=config,
                reactivation=family.family_id in dormant_family_ids,
            )
            if match is not None:
                all_scores.append(match)
    assigned_families: set[str] = set()
    assigned_candidates: set[str] = set()
    selected: list[FamilyCandidateMatch] = []
    for match in sorted(all_scores, key=lambda item: (-item.score, item.family_id, item.candidate_id)):
        if match.family_id in assigned_families or match.candidate_id in assigned_candidates:
            continue
        assigned_families.add(match.family_id)
        assigned_candidates.add(match.candidate_id)
        selected.append(match)
    return tuple(selected)


def greedy_match_rail_groups(
    groups: Iterable["RailCandidateGroup"],
    families: Iterable[TrendlineFamilyState],
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
    dormant_family_ids: set[str],
) -> tuple[FamilyRailGroupMatch, ...]:
    """Associate one group to one family using canonical member continuations.

    The family representative remains supplementary evidence only.  A valid
    continuation of any exact prior member keeps a family eligible even when
    that member is outside the representative-level distance gate.
    """

    # ``rails`` imports ``NormalizationAtr`` from this module, so keeping this
    # import local avoids a module-import cycle while retaining one canonical
    # member-scoring implementation.
    from .rails import match_group_members

    scores: list[FamilyRailGroupMatch] = []
    for family in families:
        for group in groups:
            if family.current_role is not group.role:
                continue
            representative_matches = tuple(
                score_family_candidate(
                    family,
                    candidate,
                    timestamp=timestamp,
                    atr=atr,
                    config=config,
                    reactivation=family.family_id in dormant_family_ids,
                )
                for candidate in group.candidates
            )
            representative_matches = tuple(
                match for match in representative_matches if match is not None
            )
            member_matches = match_group_members(
                family,
                group,
                timestamp=timestamp,
                atr=atr,
                config=config,
            )
            required_score = max(
                config.matching.minimum_match_score,
                config.lifecycle.reactivation_min_score
                if family.family_id in dormant_family_ids
                else 0.0,
            )
            eligible_member_matches = tuple(
                match for match in member_matches if match.score >= required_score
            )
            if not eligible_member_matches and not representative_matches:
                continue
            evidence = tuple(
                (
                    match.score,
                    match.candidate_id,
                    match.projected_distance_atr,
                    match.slope_delta_atr_per_hour,
                    match.anchor_similarity,
                )
                for match in eligible_member_matches
            ) + tuple(
                (
                    match.score,
                    match.candidate_id,
                    match.projected_distance_atr,
                    match.slope_delta_atr_per_hour,
                    match.anchor_similarity,
                )
                for match in representative_matches
            )
            best = min(
                evidence,
                key=lambda item: (
                    -item[0],
                    -item[4],
                    item[2],
                    item[3],
                    item[1],
                ),
            )
            scores.append(
                FamilyRailGroupMatch(
                    family_id=family.family_id,
                    group_id=group.group_id,
                    representative_candidate_id=best[1],
                    score=best[0],
                    projected_distance_atr=best[2],
                    slope_delta_atr_per_hour=best[3],
                    anchor_similarity=best[4],
                    member_continuation_count=len(eligible_member_matches),
                    representative_gate_passed=bool(representative_matches),
                )
            )
    used_families: set[str] = set()
    used_groups: set[str] = set()
    selected: list[FamilyRailGroupMatch] = []
    for match in sorted(
        scores,
        key=lambda item: (
            -item.score,
            -item.member_continuation_count,
            item.projected_distance_atr,
            item.slope_delta_atr_per_hour,
            item.family_id,
            item.group_id,
            item.representative_candidate_id,
        ),
    ):
        if match.family_id in used_families or match.group_id in used_groups:
            continue
        used_families.add(match.family_id)
        used_groups.add(match.group_id)
        selected.append(match)
    return tuple(sorted(selected, key=lambda item: (item.family_id, item.group_id)))


def _threshold_similarity(value: float, threshold: float) -> float:
    if threshold == 0.0:
        return 1.0 if value == 0.0 else 0.0
    return max(0.0, 1.0 - value / threshold)
