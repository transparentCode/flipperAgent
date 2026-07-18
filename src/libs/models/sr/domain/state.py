"""SR aggregate state contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._validation import _hash, _string, _tuple_of
from .bars import ClosedBar, SRStateKey, _state_key
from .errors import ContractValidationError
from .zones import ZoneRecord, _validate_zone_ownership


SR_SCHEMA_VERSION = "1.0"


def _zone_sort_key(record: ZoneRecord) -> tuple[float, str, str]:
    """Canonical ordering: lower geometry bound desc, then side, then id."""
    geometry = record.definition.geometry
    lower = geometry.lower_bound
    side = record.definition.side.value
    # SUPPORT zones sort above RESISTANCE at the same lower bound.
    side_rank = "0" if side == "SUPPORT" else "1"
    return (-lower, side_rank, record.definition.zone_id)


def _validate_recent_bars(
    value: Any,
    *,
    state_key: SRStateKey,
    last_processed_bar: str | None,
) -> tuple[ClosedBar, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractValidationError(
            "recent_bars must be a list or tuple of ClosedBar"
        )
    bars = tuple(value)
    seen_bar_ids: set[str] = set()
    previous_timestamp: datetime | None = None
    for idx, bar in enumerate(bars):
        if type(bar) is not ClosedBar:
            raise ContractValidationError(
                f"recent_bars[{idx}] must be exactly ClosedBar"
            )
        if bar.state_key != state_key:
            raise ContractValidationError(
                f"recent_bars[{idx}].state_key must match aggregate state_key"
            )
        if bar.bar_id in seen_bar_ids:
            raise ContractValidationError(
                f"duplicate bar_id in recent_bars: {bar.bar_id}"
            )
        seen_bar_ids.add(bar.bar_id)
        if (
            previous_timestamp is not None
            and bar.closed_at <= previous_timestamp
        ):
            raise ContractValidationError(
                "recent_bars.closed_at values must be strictly increasing"
            )
        previous_timestamp = bar.closed_at
    if bars and last_processed_bar is None:
        raise ContractValidationError(
            "recent_bars require non-null last_processed_bar"
        )
    if bars and bars[-1].bar_id != last_processed_bar:
        raise ContractValidationError(
            "recent_bars final bar_id must match last_processed_bar"
        )
    return bars


@dataclass(frozen=True)
class SRState:
    schema_version: str
    state_key: SRStateKey
    config_hash: str
    last_processed_bar: str | None
    zones: tuple[ZoneRecord, ...]
    recent_bars: tuple[ClosedBar, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _string(self.schema_version, field_name="schema_version")
        )
        if self.schema_version != SR_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported SR schema version: {self.schema_version!r}"
            )
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(
            self, "config_hash", _hash(self.config_hash, field_name="config_hash")
        )
        object.__setattr__(
            self,
            "last_processed_bar",
            (
                None
                if self.last_processed_bar is None
                else _string(
                    self.last_processed_bar,
                    field_name="last_processed_bar",
                )
            ),
        )
        object.__setattr__(
            self, "zones", _tuple_of(self.zones, ZoneRecord, field_name="zones")
        )
        object.__setattr__(
            self,
            "recent_bars",
            _validate_recent_bars(
                self.recent_bars,
                state_key=self.state_key,
                last_processed_bar=self.last_processed_bar,
            ),
        )
        if self.last_processed_bar is None:
            if self.zones or self.recent_bars:
                raise ContractValidationError(
                    "null last_processed_bar requires empty zones and recent_bars"
                )
        elif not self.recent_bars:
            raise ContractValidationError(
                "non-null last_processed_bar requires non-empty recent_bars"
            )
        _validate_zone_ownership(self.state_key, self.config_hash, self.zones)
        object.__setattr__(self, "zones", tuple(sorted(self.zones, key=_zone_sort_key)))


__all__ = ["SR_SCHEMA_VERSION", "SRState"]
