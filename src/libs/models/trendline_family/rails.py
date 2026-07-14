"""Deterministic causal grouping and continuation matching for exact rails."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from statistics import median
from typing import Iterable

from .config import ResolvedTrendlineFamilyConfig
from .contracts import (
    ContractValidationError,
    FamilyMember,
    FamilyRole,
    LineCandidate,
    TrendlineFamilyState,
    deterministic_id,
    require_utc,
)
from .matching import NormalizationAtr


@dataclass(frozen=True)
class RailCandidateGroup:
    """One complete-linkage-safe group of current exact candidate rails."""

    group_id: str
    asset: str
    timeframe: str
    role: FamilyRole
    observed_at: datetime
    candidates: tuple[LineCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id:
            raise ContractValidationError("rail group_id must be a non-empty string")
        if not isinstance(self.asset, str) or not self.asset:
            raise ContractValidationError("rail group asset must be a non-empty string")
        if not isinstance(self.timeframe, str) or not self.timeframe:
            raise ContractValidationError("rail group timeframe must be a non-empty string")
        if self.role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
            raise ContractValidationError("rail group requires SUPPORT or RESISTANCE")
        object.__setattr__(
            self,
            "observed_at",
            require_utc(self.observed_at, field_name="rail group observed_at"),
        )
        candidates = tuple(self.candidates)
        if not candidates or any(not isinstance(candidate, LineCandidate) for candidate in candidates):
            raise ContractValidationError("rail group requires canonical candidates")
        if tuple(sorted(candidates, key=lambda item: item.candidate_id)) != candidates:
            raise ContractValidationError("rail group candidates must have deterministic ID ordering")
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ContractValidationError("rail group candidate IDs must be unique")
        if any(
            candidate.asset != self.asset
            or candidate.timeframe != self.timeframe
            or candidate.role is not self.role
            or candidate.observed_at != self.observed_at
            for candidate in candidates
        ):
            raise ContractValidationError("rail group candidates must share request identity and role")
        expected_id = deterministic_id(
            "rail-candidate-group",
            {
                "asset": self.asset,
                "timeframe": self.timeframe,
                "role": self.role.value,
                "observed_at": self.observed_at,
                "candidate_ids": tuple(candidate.candidate_id for candidate in candidates),
            },
        )
        if self.group_id != expected_id:
            raise ContractValidationError("rail group_id must be content-addressed")
        object.__setattr__(self, "candidates", candidates)

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.candidate_id for candidate in self.candidates)


@dataclass(frozen=True)
class RailMemberMatch:
    """One deterministic same-role continuation between a member and candidate."""

    member_id: str
    candidate_id: str
    score: float
    projected_distance_atr: float
    slope_delta_atr_per_hour: float
    anchor_similarity: float

    def __post_init__(self) -> None:
        for name in ("member_id", "candidate_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ContractValidationError(f"rail {name} must be a non-empty string")
        for name in (
            "score",
            "projected_distance_atr",
            "slope_delta_atr_per_hour",
            "anchor_similarity",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ContractValidationError(f"rail {name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        if self.score > 1.0 or self.anchor_similarity > 1.0:
            raise ContractValidationError("rail score and anchor similarity must be at most one")


@dataclass(frozen=True)
class RailGroupingResult:
    groups: tuple[RailCandidateGroup, ...]
    rejected_pair_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        groups = tuple(self.groups)
        if any(not isinstance(group, RailCandidateGroup) for group in groups):
            raise ContractValidationError("rail grouping result must contain canonical groups")
        if len({group.group_id for group in groups}) != len(groups):
            raise ContractValidationError("rail grouping result group IDs must be unique")
        if tuple(sorted(groups, key=lambda item: item.group_id)) != groups:
            raise ContractValidationError("rail grouping result must have deterministic group ordering")
        object.__setattr__(self, "groups", groups)
        reasons = tuple(self.rejected_pair_reason_codes)
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise ContractValidationError("rail grouping reason codes must be non-empty strings")
        object.__setattr__(self, "rejected_pair_reason_codes", tuple(sorted(reasons)))


def group_rail_candidates(
    candidates: Iterable[LineCandidate],
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
) -> RailGroupingResult:
    """Build deterministic complete-linkage rail groups from confirmed candidates.

    Candidates are ordered by projected price then ID.  A candidate joins the
    first compatible group only when it is compatible with *every* existing
    rail, which prevents transitive A/B/C chain over-merging.
    """

    observed_at = require_utc(timestamp, field_name="rail grouping timestamp")
    ordered = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    if len({candidate.candidate_id for candidate in ordered}) != len(ordered):
        raise ContractValidationError("rail grouping candidates must have unique IDs")
    buckets: dict[FamilyRole, list[LineCandidate]] = {
        FamilyRole.SUPPORT: [],
        FamilyRole.RESISTANCE: [],
    }
    for candidate in ordered:
        if (
            candidate.asset != config.asset
            or candidate.timeframe != config.timeframe
            or candidate.observed_at != observed_at
            or candidate.role not in buckets
        ):
            raise ContractValidationError("rail grouping candidate identity does not match request")
        buckets[candidate.role].append(candidate)

    groups: list[RailCandidateGroup] = []
    rejected: list[str] = []
    for role in (FamilyRole.SUPPORT, FamilyRole.RESISTANCE):
        pending_groups: list[list[LineCandidate]] = []
        ordered_role = sorted(
            buckets[role],
            key=lambda item: (item.geometry.value_at(observed_at), item.candidate_id),
        )
        for candidate in ordered_role:
            rejection_reasons_by_index = {
                index: _candidate_group_rejection_reasons(
                    candidate,
                    members,
                    timestamp=observed_at,
                    atr=atr,
                    config=config,
                )
                for index, members in enumerate(pending_groups)
            }
            compatible_indexes = [
                index
                for index, reasons in rejection_reasons_by_index.items()
                if not reasons
            ]
            if not compatible_indexes:
                if pending_groups:
                    rejected.extend(
                        reason
                        for reasons in rejection_reasons_by_index.values()
                        for reason in reasons
                    )
                    rejected.append("complete_linkage_rejected")
                pending_groups.append([candidate])
                continue
            selected_index = min(
                compatible_indexes,
                key=lambda index: _group_tie_key(
                    pending_groups[index], timestamp=observed_at
                ),
            )
            for index, members in enumerate(pending_groups):
                if index == selected_index:
                    continue
                reasons = rejection_reasons_by_index[index]
                if reasons:
                    rejected.extend(reasons)
                    rejected.append("complete_linkage_rejected")
            pending_groups[selected_index].append(candidate)
        for members in pending_groups:
            canonical = tuple(sorted(members, key=lambda item: item.candidate_id))
            groups.append(
                RailCandidateGroup(
                    group_id=deterministic_id(
                        "rail-candidate-group",
                        {
                            "asset": config.asset,
                            "timeframe": config.timeframe,
                            "role": role.value,
                            "observed_at": observed_at,
                            "candidate_ids": tuple(candidate.candidate_id for candidate in canonical),
                        },
                    ),
                    asset=config.asset,
                    timeframe=config.timeframe,
                    role=role,
                    observed_at=observed_at,
                    candidates=canonical,
                )
            )
    return RailGroupingResult(
        groups=tuple(sorted(groups, key=lambda item: item.group_id)),
        rejected_pair_reason_codes=tuple(rejected),
    )


def match_group_members(
    family: TrendlineFamilyState,
    group: RailCandidateGroup,
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
) -> tuple[RailMemberMatch, ...]:
    """Return deterministic one-to-one continuation matches within one family/group."""

    if family.current_role is not group.role:
        return ()
    observed_at = require_utc(timestamp, field_name="rail member matching timestamp")
    scores: list[RailMemberMatch] = []
    for member in family.members:
        if member.role is not group.role:
            continue
        for candidate in group.candidates:
            match = score_member_candidate(
                member,
                candidate,
                timestamp=observed_at,
                atr=atr,
                config=config,
            )
            if match is not None:
                scores.append(match)
    used_members: set[str] = set()
    used_candidates: set[str] = set()
    selected: list[RailMemberMatch] = []
    for match in sorted(
        scores,
        key=lambda item: (-item.score, item.member_id, item.candidate_id),
    ):
        if match.member_id in used_members or match.candidate_id in used_candidates:
            continue
        used_members.add(match.member_id)
        used_candidates.add(match.candidate_id)
        selected.append(match)
    return tuple(sorted(selected, key=lambda item: item.member_id))


def subset_rail_candidate_group(
    group: RailCandidateGroup,
    candidates: Iterable[LineCandidate],
) -> RailCandidateGroup:
    """Rebuild a content-addressed residual group after deterministic filtering."""

    selected = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    if not selected:
        raise ContractValidationError("rail group residual requires at least one candidate")
    allowed = set(group.candidate_ids)
    if any(candidate.candidate_id not in allowed for candidate in selected):
        raise ContractValidationError("rail group residual candidates must originate from the group")
    return RailCandidateGroup(
        group_id=deterministic_id(
            "rail-candidate-group",
            {
                "asset": group.asset,
                "timeframe": group.timeframe,
                "role": group.role.value,
                "observed_at": group.observed_at,
                "candidate_ids": tuple(candidate.candidate_id for candidate in selected),
            },
        ),
        asset=group.asset,
        timeframe=group.timeframe,
        role=group.role,
        observed_at=group.observed_at,
        candidates=selected,
    )


def select_representative_member(
    members: Iterable[FamilyMember],
    *,
    timestamp: datetime,
    atr: float | None,
    previous_representative_member_id: str | None,
) -> FamilyMember:
    """Choose a prior exact rail when valid, otherwise a deterministic medoid."""

    observed_at = require_utc(timestamp, field_name="representative selection timestamp")
    ordered = tuple(sorted(members, key=lambda item: item.member_id))
    if not ordered:
        raise ContractValidationError("representative selection requires at least one member")
    if previous_representative_member_id is not None:
        previous = next(
            (member for member in ordered if member.member_id == previous_representative_member_id),
            None,
        )
        if previous is not None:
            return previous
    normalizer = atr if atr is not None and math.isfinite(atr) and atr > 0.0 else 1.0
    def medoid_key(member: FamilyMember) -> tuple[float, float, str]:
        price = member.geometry.value_at(observed_at)
        distance = sum(
            abs(price - other.geometry.value_at(observed_at)) / normalizer
            + abs(member.geometry.slope_per_second - other.geometry.slope_per_second)
            * 3600.0
            / normalizer
            for other in ordered
        )
        return (distance, -member.diagnostics.normalized_quality, member.member_id)

    return min(ordered, key=medoid_key)


def _candidate_fits_group(
    candidate: LineCandidate,
    members: Iterable[LineCandidate],
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
) -> bool:
    return not _candidate_group_rejection_reasons(
        candidate,
        members,
        timestamp=timestamp,
        atr=atr,
        config=config,
    )


def _candidate_group_rejection_reasons(
    candidate: LineCandidate,
    members: Iterable[LineCandidate],
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
) -> tuple[str, ...]:
    values = tuple(members)
    if not values:
        return ("empty_group",)
    pair_reasons = tuple(
        sorted(
            {
                reason
                for member in values
                if (
                    reason := _pair_rejection_reason(
                        candidate,
                        member,
                        timestamp=timestamp,
                        atr=atr,
                        config=config,
                    )
                )
                is not None
            }
        )
    )
    if pair_reasons:
        return pair_reasons
    ordered_prices = tuple(
        sorted(
            item.geometry.value_at(timestamp) for item in values + (candidate,)
        )
    )
    adjacent_gaps = tuple(
        (ordered_prices[index + 1] - ordered_prices[index]) / atr.value
        for index in range(len(ordered_prices) - 1)
    )
    if any(gap > config.rails.max_adjacent_gap_atr for gap in adjacent_gaps):
        return ("adjacent_gap_exceeds_maximum",)
    if (
        _corridor_width_atr(values + (candidate,), timestamp=timestamp, atr=atr)
        > config.rails.max_corridor_width_atr
    ):
        return ("corridor_width_exceeds_maximum",)
    return ()


def _pair_rejection_reason(
    left: LineCandidate,
    right: LineCandidate,
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
) -> str | None:
    if left.role is not right.role:
        return "role_mismatch"
    slope_delta = (
        abs(left.geometry.slope_per_second - right.geometry.slope_per_second)
        * 3600.0
        / atr.value
    )
    if slope_delta > config.rails.max_group_slope_delta_atr_per_hour:
        return "slope_delta_exceeds_maximum"
    if _crosses_within_confirmed_span(left, right, timestamp=timestamp):
        return "crossing_rails"
    distance = abs(
        left.geometry.value_at(timestamp) - right.geometry.value_at(timestamp)
    ) / atr.value
    if distance < config.rails.minimum_spacing_atr:
        return "spacing_below_minimum"
    return None


def _crosses_within_confirmed_span(
    left: LineCandidate,
    right: LineCandidate,
    *,
    timestamp: datetime,
) -> bool:
    """Reject rails whose exact geometries cross inside their known causal span."""

    slope_delta = left.geometry.slope_per_second - right.geometry.slope_per_second
    if abs(slope_delta) <= 1e-18:
        return False
    reference_delta_seconds = (
        left.geometry.reference_time - right.geometry.reference_time
    ).total_seconds()
    numerator = (
        right.geometry.reference_price
        - left.geometry.reference_price
        + right.geometry.slope_per_second * reference_delta_seconds
    )
    crossing = left.geometry.reference_time + timedelta(
        seconds=numerator / slope_delta
    )
    common_geometry_start = max(
        min(anchor.timestamp for anchor in left.anchors),
        min(anchor.timestamp for anchor in right.anchors),
    )
    return common_geometry_start <= crossing <= timestamp


def score_member_candidate(
    member: FamilyMember,
    candidate: LineCandidate,
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
    config: ResolvedTrendlineFamilyConfig,
) -> RailMemberMatch | None:
    if member.role is not candidate.role:
        return None
    projected_distance = abs(
        member.geometry.value_at(timestamp) - candidate.geometry.value_at(timestamp)
    ) / atr.value
    slope_delta = (
        abs(member.geometry.slope_per_second - candidate.geometry.slope_per_second)
        * 3600.0
        / atr.value
    )
    if (
        projected_distance > config.matching.max_distance_atr
        or slope_delta > config.matching.max_slope_delta_atr_per_hour
    ):
        return None
    member_anchor_ids = {anchor.anchor_id for anchor in member.anchors}
    candidate_anchor_ids = {anchor.anchor_id for anchor in candidate.anchors}
    union = member_anchor_ids | candidate_anchor_ids
    anchor_similarity = (
        len(member_anchor_ids & candidate_anchor_ids) / len(union) if union else 0.0
    )
    level_similarity = _threshold_similarity(
        projected_distance, config.matching.max_distance_atr
    )
    slope_similarity = _threshold_similarity(
        slope_delta, config.matching.max_slope_delta_atr_per_hour
    )
    score = (
        config.matching.level_weight * level_similarity
        + config.matching.slope_weight * slope_similarity
        + config.matching.anchor_weight * anchor_similarity
        + config.matching.role_weight
    )
    if score < config.matching.minimum_match_score:
        return None
    return RailMemberMatch(
        member_id=member.member_id,
        candidate_id=candidate.candidate_id,
        score=score,
        projected_distance_atr=projected_distance,
        slope_delta_atr_per_hour=slope_delta,
        anchor_similarity=anchor_similarity,
    )


def _corridor_width_atr(
    candidates: tuple[LineCandidate, ...],
    *,
    timestamp: datetime,
    atr: NormalizationAtr,
) -> float:
    prices = tuple(candidate.geometry.value_at(timestamp) for candidate in candidates)
    return (max(prices) - min(prices)) / atr.value


def _group_tie_key(
    members: Iterable[LineCandidate],
    *,
    timestamp: datetime,
) -> tuple[float, tuple[str, ...]]:
    values = tuple(members)
    return (
        median(candidate.geometry.value_at(timestamp) for candidate in values),
        tuple(sorted(candidate.candidate_id for candidate in values)),
    )


def _threshold_similarity(value: float, threshold: float) -> float:
    if threshold == 0.0:
        return 1.0 if value == 0.0 else 0.0
    return max(0.0, 1.0 - value / threshold)
