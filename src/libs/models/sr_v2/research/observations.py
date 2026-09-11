"""Explicit candidate and matched-null research observations.

The runtime target is intentionally smaller than the research record.  This
record carries the matching dimensions and the full point-in-time lineage
interval needed by protected evaluation and block inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from ..contracts import require_utc
from ..domain.zones import ZoneLineage
from ..forecast.targets import TargetObservation

STRATA_FIELD_ATTRIBUTES = MappingProxyType(
    {
        "asset": "asset",
        "timeframe": "timeframe",
        "side": "side",
        "width": "width_stratum",
        "issuance_calendar_block": "issuance_calendar_block",
        "normalized_distance": "normalized_distance_stratum",
        "volatility": "volatility_stratum",
        "level_density": "level_density_stratum",
        "touch_opportunity": "touch_opportunity_stratum",
    }
)


def canonical_matching_strata(values: object) -> tuple[str, ...]:
    """Resolve a YAML-selected ordered subset of the strata ontology."""

    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise TypeError("matching_strata must be a sequence")
    if any(not isinstance(value, str) for value in values):
        raise TypeError("matching_strata must contain canonical field names")
    result = tuple(values)
    if not result:
        raise ValueError("matching_strata must not be empty")
    if any(item not in STRATA_FIELD_ATTRIBUTES for item in result):
        unknown = sorted(set(result) - set(STRATA_FIELD_ATTRIBUTES))
        raise ValueError(f"matching_strata contains unsupported fields: {', '.join(unknown)}")
    if len(result) != len(set(result)):
        raise ValueError("matching_strata must contain unique fields")
    return result


def canonical_issuance_calendar_block(
    issued_at: datetime,
    *,
    block: timedelta,
    epoch: datetime,
) -> str:
    """Return the deterministic UTC calendar block for one issuance."""

    require_utc(issued_at, field_name="issued_at")
    require_utc(epoch, field_name="bootstrap_epoch")
    if not isinstance(block, timedelta) or block <= timedelta(0):
        raise ValueError("bootstrap block must be positive")
    index = (issued_at - epoch) // block
    start = epoch + block * index
    end = start + block
    return f"{start.isoformat(timespec='microseconds')}/{end.isoformat(timespec='microseconds')}"


def validate_issuance_calendar_block(
    issued_at: datetime,
    supplied: str,
    *,
    block: timedelta,
    epoch: datetime,
) -> str:
    """Validate a supplied label against the canonical UTC block."""

    expected = canonical_issuance_calendar_block(issued_at, block=block, epoch=epoch)
    if supplied != expected:
        raise ValueError("issuance_calendar_block does not match issued_at")
    return expected


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchObservation:
    """One candidate/null observation with all preregistered matching strata."""

    observation_id: str
    asset: str
    timeframe: str
    side: str
    width_stratum: str
    issuance_calendar_block: str
    normalized_distance_stratum: str
    volatility_stratum: str
    level_density_stratum: str
    touch_opportunity_stratum: str
    formed_at: datetime
    issued_at: datetime
    observation_end_at: datetime
    source_file_path: str | None = None
    source_record_identity: str | None = None
    target: TargetObservation | None = None
    source_evidence_id: str = ""
    record_type: str = "candidate"
    source_observation_id: str | None = None
    null_generator: str | None = None
    null_seed: str | None = None
    zone: ZoneLineage | None = None
    target_provenance: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "asset",
            "timeframe",
            "side",
            "width_stratum",
            "issuance_calendar_block",
            "normalized_distance_stratum",
            "volatility_stratum",
            "level_density_stratum",
            "touch_opportunity_stratum",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.record_type not in {"candidate", "random_price_null", "shuffled_time_null"}:
            raise ValueError("unsupported research observation record_type")
        if not isinstance(self.source_evidence_id, str) or not self.source_evidence_id.strip():
            raise ValueError("source_evidence_id must be non-empty")
        if (self.source_file_path is None) != (self.source_record_identity is None):
            raise ValueError("source file and source record identity must be supplied together")
        if self.source_file_path is not None and not self.source_file_path.strip():
            raise ValueError("source_file_path must be non-empty")
        if self.source_record_identity is not None and not self.source_record_identity.strip():
            raise ValueError("source_record_identity must be non-empty")
        require_utc(self.formed_at, field_name="formed_at")
        require_utc(self.issued_at, field_name="issued_at")
        require_utc(self.observation_end_at, field_name="observation_end_at")
        if self.formed_at > self.issued_at:
            raise ValueError("formation must not follow issuance")
        if self.observation_end_at <= self.issued_at:
            raise ValueError("observation interval must be positive")
        if self.target is not None:
            if self.target.zone_id != self.observation_id:
                raise ValueError("target and research observation identities differ")
            if self.target.issued_at != self.issued_at:
                raise ValueError("target and research issuance differ")
            if self.target.observation_end_at != self.observation_end_at:
                raise ValueError("target and research observation interval differ")
        if self.zone is not None:
            if not isinstance(self.zone, ZoneLineage):
                raise TypeError("zone must be a ZoneLineage when supplied")
            if self.zone.zone_id != self.observation_id:
                raise ValueError("zone and research observation identities differ")
            if self.zone.asset != self.asset or self.zone.source_timeframe != self.timeframe:
                raise ValueError("zone and research observation market identity differs")
            if self.zone.side.value != self.side:
                raise ValueError("zone and research observation side differs")
            if self.zone.formed_at != self.formed_at:
                raise ValueError("zone and research formation times differ")
            if self.zone.available_at > self.issued_at:
                raise ValueError("zone must be available by research issuance")
        if self.target_provenance is not None:
            if len(self.target_provenance) != 64:
                raise ValueError("target_provenance must be a SHA-256 when supplied")
            try:
                int(self.target_provenance, 16)
            except ValueError as exc:
                raise ValueError("target_provenance must be hexadecimal") from exc
        if self.record_type != "candidate" and not self.source_observation_id:
            raise ValueError("matched nulls require source_observation_id")
        if self.null_generator is not None and self.null_generator not in {
            "random_price_v1",
            "shuffled_time_v1",
        }:
            raise ValueError("unsupported null generator provenance")
        if self.null_seed is not None and (
            not isinstance(self.null_seed, str) or not self.null_seed.strip()
        ):
            raise ValueError("null_seed must be non-empty when supplied")
        if self.null_generator == "random_price_v1" and self.record_type != "random_price_null":
            raise ValueError("random-price provenance requires random_price_null record type")
        if self.null_generator == "shuffled_time_v1" and self.record_type != "shuffled_time_null":
            raise ValueError("shuffled-time provenance requires shuffled_time_null record type")

    def strata_key_for(self, fields: object) -> tuple[str, ...]:
        """Return the key for the caller's configured field selection/order."""

        selected = canonical_matching_strata(fields)
        return tuple(str(getattr(self, STRATA_FIELD_ATTRIBUTES[field])) for field in selected)

    def require_target(self) -> TargetObservation:
        if self.target is None:
            raise ValueError("research observation is not labeled")
        return self.target



__all__ = [
    "STRATA_FIELD_ATTRIBUTES",
    "ResearchObservation",
    "canonical_issuance_calendar_block",
    "canonical_matching_strata",
    "validate_issuance_calendar_block",
]
