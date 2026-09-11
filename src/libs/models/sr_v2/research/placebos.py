"""Deterministic matched-null generation with explicit provenance."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType

from ..contracts import ZoneSide
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash, make_zone_id
from ..domain.zones import ZoneLineage, ZoneRecord
from .observations import ResearchObservation, canonical_matching_strata

FEASIBLE_RANDOM_PRICE_ID = "feasible_random_price@3"


@dataclass(frozen=True, slots=True, kw_only=True)
class FeasibleRandomPriceNull:
    """One deterministic, causally feasible random-price null receipt."""

    source_observation_id: str
    zone: ZoneLineage | None
    complete: bool
    reason: str | None
    opportunity_bar_ids: tuple[str, ...]
    excluded_active_zone_ids: tuple[str, ...]
    provenance: Mapping[str, object]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_observation_id, str)
            or not self.source_observation_id.strip()
        ):
            raise ValueError("source_observation_id must be non-empty")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be bool")
        if self.complete and self.zone is None:
            raise ValueError("complete feasible null must contain a zone")
        if not self.complete and self.zone is not None:
            raise ValueError("incomplete feasible null must not contain a zone")
        if self.complete and self.reason is not None:
            raise ValueError("complete feasible null must not have a reason")
        if not self.complete and (
            not isinstance(self.reason, str) or not self.reason.strip()
        ):
            raise ValueError("incomplete feasible null must explain its reason")
        object.__setattr__(self, "opportunity_bar_ids", tuple(self.opportunity_bar_ids))
        object.__setattr__(
            self, "excluded_active_zone_ids", tuple(self.excluded_active_zone_ids)
        )
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


def build_feasible_random_price_null(
    zone: ZoneLineage,
    *,
    kernel_bars: Sequence[SRBar],
    active_zones: Sequence[ZoneLineage | ZoneRecord],
    seed: str,
) -> FeasibleRandomPriceNull:
    """Select one feasible support/resistance opportunity from a causal window.

    Opportunities are unique lows for support and unique highs for resistance.
    The exact source window and excluded active-zone identities are retained in
    provenance; no candidate ATR or future/retry search participates.
    """

    if not isinstance(zone, ZoneLineage):
        raise TypeError("zone must be ZoneLineage")
    _require_seed(seed)
    values = tuple(kernel_bars)
    if not values or any(not isinstance(bar, SRBar) for bar in values):
        raise ValueError("feasible null requires a non-empty SRBar kernel window")
    if any(bar.timeframe != zone.source_timeframe for bar in values):
        raise ValueError("feasible null kernel window timeframe mismatch")
    # The compiler supplies the exact catalog window.  Validate its local
    # continuity here so a caller cannot turn a gap into an opportunity set.
    from ..features.time import grid_for

    grid_for(zone.source_timeframe).validate_contiguous(
        tuple(bar.bar_open_at for bar in values),
        tuple(bar.bar_close_at for bar in values),
    )
    if any(bar.bar_close_at > zone.available_at for bar in values):
        raise ValueError("feasible null kernel window contains future bars")
    if values[-1].bar_close_at != zone.available_at:
        raise ValueError("feasible null kernel window must end at zone availability")
    normalized_active: list[ZoneLineage] = []
    for item in active_zones:
        if isinstance(item, ZoneLineage):
            normalized_active.append(item)
        elif isinstance(item, ZoneRecord):
            normalized_active.append(item.lineage)
        else:
            raise TypeError(
                "active_zones must contain ZoneLineage or ZoneRecord values"
            )
    same_side = tuple(
        item
        for item in normalized_active
        if (
            item.side is zone.side
            and item.venue == zone.venue
            and item.instrument_id == zone.instrument_id
            and item.asset == zone.asset
            and item.source_timeframe == zone.source_timeframe
        )
    )
    excluded_ids = tuple(sorted(item.zone_id for item in same_side))
    left_width = zone.center - zone.lower
    right_width = zone.upper - zone.center
    total_width = left_width + right_width
    if (
        not left_width.is_finite()
        or not right_width.is_finite()
        or left_width < 0
        or right_width < 0
        or not total_width.is_finite()
        or total_width <= 0
    ):
        raise ValueError(
            "feasible null requires finite non-negative stored offsets and "
            "a positive total zone width"
        )
    opportunities: dict[Decimal, tuple[str, ...]] = defaultdict(tuple)
    for bar in values:
        center = bar.low if zone.side is ZoneSide.SUPPORT else bar.high
        if center <= 0 or not center.is_finite():
            continue
        opportunities[center] = opportunities[center] + (bar.identity,)
    ordered = tuple(sorted(opportunities))
    opportunity_ids = tuple(
        bar_id for center in ordered for bar_id in opportunities[center]
    )
    feasible: list[tuple[Decimal, tuple[str, ...]]] = []
    for center in ordered:
        lower = center - left_width
        upper = center + right_width
        if lower <= 0 or lower > center or center > upper:
            continue
        overlaps = any(
            lower <= item.upper and upper >= item.lower for item in same_side
        )
        if not overlaps:
            feasible.append((center, opportunities[center]))
    provenance_base = {
        "algorithm_id": FEASIBLE_RANDOM_PRICE_ID,
        "seed": seed,
        "source_observation_id": zone.zone_id,
        "side": zone.side.value,
        "source_timeframe": zone.source_timeframe,
        "source_window_bar_ids": tuple(bar.identity for bar in values),
        "opportunity_bar_ids": opportunity_ids,
        "feasible_opportunity_bar_ids": tuple(
            bar_id for _, bar_ids in feasible for bar_id in bar_ids
        ),
        "excluded_active_zone_ids": excluded_ids,
        "source_geometry": {
            "center": zone.center,
            "lower": zone.lower,
            "upper": zone.upper,
        },
        "left_width": left_width,
        "right_width": right_width,
        "placement_rule": "preserve_stored_offsets@1",
        "linkage": zone.zone_id,
    }
    if not feasible:
        return FeasibleRandomPriceNull(
            source_observation_id=zone.zone_id,
            zone=None,
            complete=False,
            reason="no feasible same-side opportunity remains after overlap exclusion",
            opportunity_bar_ids=opportunity_ids,
            excluded_active_zone_ids=excluded_ids,
            provenance={**provenance_base, "selected_center": None},
        )
    digest = hashlib.sha256(f"{seed}:{zone.zone_id}".encode()).digest()
    selected_center, selected_bar_ids = feasible[
        int.from_bytes(digest[:8], "big") % len(feasible)
    ]
    lower = selected_center - left_width
    upper = selected_center + right_width
    candidate_key = (
        f"{FEASIBLE_RANDOM_PRICE_ID}:{zone.zone_id}:"
        f"{selected_center}:{selected_bar_ids[0]}"
    )
    evidence_id = f"{FEASIBLE_RANDOM_PRICE_ID}:{canonical_hash(provenance_base | {'selected_center': selected_center})}"
    null_id = make_zone_id(
        venue=zone.venue,
        instrument_id=zone.instrument_id,
        asset=zone.asset,
        source_timeframe=zone.source_timeframe,
        kernel_id=zone.kernel_id,
        kernel_version=zone.kernel_version,
        source_candidate_key=candidate_key,
        available_at=zone.available_at,
        center=selected_center,
        lower=lower,
        upper=upper,
        predecessor_id=zone.predecessor_id,
        identity_schema_version=zone.identity_schema_version,
    )
    null_zone = replace(
        zone,
        zone_id=null_id,
        center=selected_center,
        lower=lower,
        upper=upper,
        source_candidate_key=candidate_key,
        source_evidence_id=evidence_id,
    )
    return FeasibleRandomPriceNull(
        source_observation_id=zone.zone_id,
        zone=null_zone,
        complete=True,
        reason=None,
        opportunity_bar_ids=opportunity_ids,
        excluded_active_zone_ids=excluded_ids,
        provenance={
            **provenance_base,
            "selected_center": selected_center,
            "selected_bar_ids": selected_bar_ids,
            "output_geometry": {
                "center": selected_center,
                "lower": lower,
                "upper": upper,
            },
        },
    )


def _require_seed(seed: str) -> None:
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be non-empty")


def _require_max_abs_shift(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("max_abs_shift_atr must be a finite positive Decimal")
    return value


def matched_random_price_placebos(
    zones: Iterable[ZoneLineage],
    *,
    seed: str,
    max_abs_shift_atr: Decimal,
) -> tuple[ZoneLineage, ...]:
    """Shift zone geometry deterministically while preserving source timing."""

    _require_seed(seed)
    max_shift = _require_max_abs_shift(max_abs_shift_atr)
    result: list[ZoneLineage] = []
    seen: set[str] = set()
    for zone in zones:
        digest = hashlib.sha256(f"{seed}:{zone.zone_id}".encode()).digest()
        scale = Decimal(int.from_bytes(digest[:8], "big")) / Decimal(2**64)
        shift = (scale - Decimal("0.5")) * zone.creation_atr * max_shift * Decimal(2)
        center = zone.center + shift
        lower = zone.lower + shift
        upper = zone.upper + shift
        placebo_id = make_zone_id(
            venue=zone.venue,
            instrument_id=zone.instrument_id,
            asset=zone.asset,
            source_timeframe=zone.source_timeframe,
            kernel_id=zone.kernel_id,
            kernel_version=zone.kernel_version,
            source_candidate_key=zone.source_candidate_key or zone.source_evidence_id,
            available_at=zone.available_at,
            center=center,
            lower=lower,
            upper=upper,
            predecessor_id=zone.predecessor_id,
            identity_schema_version=zone.identity_schema_version,
        )
        if placebo_id in seen:
            raise ValueError("random-price null identity collision")
        seen.add(placebo_id)
        result.append(
            replace(
                zone,
                zone_id=placebo_id,
                center=center,
                lower=lower,
                upper=upper,
                source_evidence_id=f"random_price:{seed}:{zone.source_evidence_id}",
            )
        )
    return tuple(result)


def _rotate_derangement[T](values: list[T], *, seed_material: str) -> list[T]:
    if len(values) < 2:
        raise ValueError("shuffled-time null requires a derangeable group")
    digest = hashlib.sha256(seed_material.encode()).digest()
    offset = 1 + int.from_bytes(digest[:8], "big") % (len(values) - 1)
    return values[offset:] + values[:offset]


def build_random_price_nulls(
    observations: Iterable[ResearchObservation],
    *,
    seed: str,
    max_abs_shift_atr: Decimal,
    matching_strata: object,
) -> tuple[ResearchObservation, ...]:
    """Build one random-price null per observation, preserving all strata."""

    _require_seed(seed)
    max_shift = _require_max_abs_shift(max_abs_shift_atr)
    values = tuple(observations)
    result_values: list[ResearchObservation] = []
    for item in values:
        placebo_zone = None
        observation_id = canonical_hash(
            {"kind": "random_price_null", "seed": seed, "source": item.observation_id}
        )
        if item.zone is not None:
            placebo_zone = matched_random_price_placebos(
                (item.zone,),
                seed=seed,
                max_abs_shift_atr=max_shift,
            )[0]
            observation_id = placebo_zone.zone_id
        result_values.append(
            replace(
                item,
                observation_id=observation_id,
                source_evidence_id=f"random_price:{seed}:{item.source_evidence_id}",
                record_type="random_price_null",
                source_observation_id=item.observation_id,
                null_generator="random_price_v1",
                null_seed=seed,
                zone=placebo_zone,
                target=None,
                target_provenance=None,
            )
        )
    result = tuple(result_values)
    _assert_matched_counts(values, result, matching_strata=matching_strata)
    _assert_unique_ids(result)
    return result


def build_shuffled_time_nulls(
    observations: Iterable[ResearchObservation],
    *,
    seed: str,
    matching_strata: object,
) -> tuple[ResearchObservation, ...]:
    """Derange issuance times inside every configured strata group."""

    _require_seed(seed)
    selected_strata = canonical_matching_strata(matching_strata)
    if not {"asset", "timeframe"}.issubset(selected_strata):
        raise ValueError(
            "shuffled-time null matching_strata must include asset and timeframe"
        )
    values = tuple(observations)
    groups: dict[tuple[str, ...], list[ResearchObservation]] = defaultdict(list)
    for item in values:
        groups[item.strata_key_for(selected_strata)].append(item)
    replacements: dict[str, ResearchObservation] = {}
    for strata, group in sorted(groups.items()):
        ordered = sorted(group, key=lambda item: item.observation_id)
        if len(ordered) < 2:
            raise ValueError(f"shuffled-time null group is not derangeable: {strata}")
        shuffled = _rotate_derangement(
            ordered,
            seed_material=f"{seed}:{'|'.join(strata)}",
        )
        for target, source in zip(ordered, shuffled):
            horizon = target.observation_end_at - target.issued_at
            shifted_zone = None
            observation_id = canonical_hash(
                {
                    "kind": "shuffled_time_null",
                    "seed": seed,
                    "source": target.observation_id,
                    "source_time": source.issued_at,
                    "source_formed": source.formed_at,
                }
            )
            if target.zone is not None:
                availability_lag = target.zone.available_at - target.zone.formed_at
                shifted_available = source.formed_at + availability_lag
                if shifted_available > source.issued_at:
                    raise ValueError(
                        "shuffled-time null zone is unavailable at shifted issuance"
                    )
                source_candidate_key = (
                    f"shuffled:{target.zone.source_candidate_key or target.zone.source_evidence_id}:"
                    f"{source.observation_id}"
                )
                shifted_zone_id = make_zone_id(
                    venue=target.zone.venue,
                    instrument_id=target.zone.instrument_id,
                    asset=target.zone.asset,
                    source_timeframe=target.zone.source_timeframe,
                    kernel_id=target.zone.kernel_id,
                    kernel_version=target.zone.kernel_version,
                    source_candidate_key=source_candidate_key,
                    available_at=shifted_available,
                    center=target.zone.center,
                    lower=target.zone.lower,
                    upper=target.zone.upper,
                    predecessor_id=target.zone.predecessor_id,
                    identity_schema_version=target.zone.identity_schema_version,
                )
                shifted_zone = replace(
                    target.zone,
                    zone_id=shifted_zone_id,
                    formed_at=source.formed_at,
                    available_at=shifted_available,
                    source_candidate_key=source_candidate_key,
                )
                observation_id = shifted_zone.zone_id
            replacements[target.observation_id] = replace(
                target,
                observation_id=observation_id,
                formed_at=source.formed_at,
                issued_at=source.issued_at,
                observation_end_at=source.issued_at + horizon,
                issuance_calendar_block=source.issuance_calendar_block,
                source_file_path=source.source_file_path,
                source_record_identity=source.source_record_identity,
                source_evidence_id=f"shuffled_time:{seed}:{target.source_evidence_id}:{source.observation_id}",
                record_type="shuffled_time_null",
                source_observation_id=target.observation_id,
                null_generator="shuffled_time_v1",
                null_seed=seed,
                zone=shifted_zone,
                target_provenance=None,
                target=None,
            )
    result = tuple(replacements[item.observation_id] for item in values)
    _assert_matched_counts(values, result, matching_strata=selected_strata)
    _assert_unique_ids(result)
    return result


def _assert_matched_counts(
    source: Iterable[ResearchObservation],
    nulls: Iterable[ResearchObservation],
    *,
    matching_strata: object,
) -> None:
    selected_strata = canonical_matching_strata(matching_strata)
    source_values = tuple(source)
    null_values = tuple(nulls)
    if len(source_values) != len(null_values):
        raise ValueError("matched null count differs from candidate count")
    if Counter(
        item.strata_key_for(selected_strata) for item in source_values
    ) != Counter(item.strata_key_for(selected_strata) for item in null_values):
        raise ValueError("matched null strata counts differ from candidates")


def _assert_unique_ids(values: Iterable[ResearchObservation]) -> None:
    items = tuple(values)
    if len({item.observation_id for item in items}) != len(items):
        raise ValueError("matched null observation identity collision")


__all__ = [
    "FEASIBLE_RANDOM_PRICE_ID",
    "FeasibleRandomPriceNull",
    "build_feasible_random_price_null",
    "build_random_price_nulls",
    "build_shuffled_time_nulls",
    "matched_random_price_placebos",
]
