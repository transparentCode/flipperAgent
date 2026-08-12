"""Immutable market identity contracts for ingestion."""

from __future__ import annotations

from dataclasses import dataclass


def _require_non_empty_string(value: object, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class Instrument:
    """Provider-independent identity and market metadata for one instrument."""

    instrument_id: str
    venue: str
    market_type: str
    base_asset: str
    quote_asset: str
    settlement_asset: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "venue",
            "market_type",
            "base_asset",
            "quote_asset",
        ):
            _require_non_empty_string(getattr(self, field_name), field_name=field_name)
        if self.settlement_asset is not None:
            _require_non_empty_string(
                self.settlement_asset,
                field_name="settlement_asset",
            )


@dataclass(frozen=True, slots=True)
class MarketLane:
    """The canonical venue, instrument, and timeframe identity for a market lane."""

    venue: str
    instrument_id: str
    timeframe: str

    def __post_init__(self) -> None:
        for field_name in ("venue", "instrument_id", "timeframe"):
            _require_non_empty_string(getattr(self, field_name), field_name=field_name)


__all__ = ["Instrument", "MarketLane"]
