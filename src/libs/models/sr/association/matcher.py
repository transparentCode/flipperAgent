"""Pure deterministic candidate-to-zone association."""

from __future__ import annotations

import math

from libs.models.sr.config.models import AssociationConfig
from libs.models.sr.domain.contracts import (
    CandidateLevel,
    ContractValidationError,
    ZoneRecord,
)


def _finite(value: float, *, field_name: str) -> float:
    if not math.isfinite(value):
        raise ContractValidationError(f"{field_name} must be finite")
    return value


def _validate_geometry(record: ZoneRecord, *, field_name: str) -> None:
    geometry = record.definition.geometry
    _finite(geometry.center, field_name=f"{field_name}.center")
    _finite(geometry.half_width, field_name=f"{field_name}.half_width")
    _finite(geometry.lower_bound, field_name=f"{field_name}.lower_bound")
    _finite(geometry.upper_bound, field_name=f"{field_name}.upper_bound")


def match_candidate(
    candidate: CandidateLevel,
    zones: tuple[ZoneRecord, ...],
    config: AssociationConfig,
) -> ZoneRecord | None:
    """Return nearest eligible same-side zone within ATR merge threshold."""
    if type(candidate) is not CandidateLevel:
        raise ContractValidationError("candidate must be exactly CandidateLevel")
    if type(zones) is not tuple:
        raise ContractValidationError("zones must be exactly a tuple")
    if type(config) is not AssociationConfig:
        raise ContractValidationError(
            "config must be exactly AssociationConfig"
        )
    _finite(
        candidate.geometry.half_width,
        field_name="candidate.half_width",
    )
    _finite(candidate.geometry.center, field_name="candidate.center")
    _finite(candidate.geometry.lower_bound, field_name="candidate.lower_bound")
    _finite(candidate.geometry.upper_bound, field_name="candidate.upper_bound")
    threshold = _finite(
        config.merge_distance_atr * candidate.atr_at_creation,
        field_name="merge threshold",
    )

    matches: list[tuple[float, str, ZoneRecord]] = []
    for idx, record in enumerate(zones):
        if type(record) is not ZoneRecord:
            raise ContractValidationError(
                f"zones[{idx}] must be exactly ZoneRecord"
            )
        _validate_geometry(record, field_name=f"zones[{idx}].geometry")
        if record.definition.state_key != candidate.state_key:
            raise ContractValidationError(
                f"zones[{idx}].definition.state_key must match candidate"
            )
        if record.definition.side is not candidate.side:
            continue
        distance = _finite(
            abs(
                candidate.geometry.center
                - record.definition.geometry.center
            ),
            field_name="candidate-zone distance",
        )
        if distance <= threshold:
            matches.append((distance, record.definition.zone_id, record))
    if not matches:
        return None
    return min(matches, key=lambda item: (item[0], item[1]))[2]


__all__ = ["match_candidate"]
