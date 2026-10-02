"""Immutable market identity contracts for ingestion."""

from __future__ import annotations

from dataclasses import dataclass

from .validation import require_non_empty_string


@dataclass(frozen=True, slots=True)
class MarketLane:
    """The canonical venue, instrument, and timeframe identity for a market lane."""

    venue: str
    instrument_id: str
    timeframe: str

    def __post_init__(self) -> None:
        for field_name in ("venue", "instrument_id", "timeframe"):
            require_non_empty_string(getattr(self, field_name), field_name=field_name)


__all__ = ["MarketLane"]
