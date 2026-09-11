"""TradingView derivative persistence kept outside the frozen legacy app."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from asyncpg import Pool
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def normalize_utc_timestamp(value: Any) -> datetime:
    """Normalize TradingView timestamps using the former legacy boundary."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    if isinstance(value, (int, float)):
        if value > 1e11:
            return datetime.fromtimestamp(value / 1000.0, tz=UTC)
        return datetime.fromtimestamp(value, tz=UTC)

    if isinstance(value, str):
        try:
            numeric_value = float(value)
            if numeric_value > 1e11:
                return datetime.fromtimestamp(numeric_value / 1000.0, tz=UTC)
            return datetime.fromtimestamp(numeric_value, tz=UTC)
        except ValueError:
            # Keep the former legacy parser's exact ISO/Z handling.
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)

    raise ValueError(f"Cannot parse timestamp from {value}")


class _TradingViewRecord(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    timestamp: datetime = Field(
        validation_alias=AliasChoices("timestamp", "E", "T", "t"),
    )
    symbol: str = Field(
        validation_alias=AliasChoices("symbol", "s", "sym"),
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def coerce_timestamp(cls, value: Any) -> datetime:
        return normalize_utc_timestamp(value)


class OIRecord(_TradingViewRecord):
    open_interest: float = Field(
        ge=0,
        validation_alias=AliasChoices("open_interest", "openInterest", "oi"),
    )


class FundingRateRecord(_TradingViewRecord):
    funding_rate: float = Field(
        validation_alias=AliasChoices("funding_rate", "fundingRate", "fr"),
    )


class TradingViewTimescaleWriter:
    """Persist only the derivative rows produced by the TradingView worker."""

    def __init__(self, pool: Pool) -> None:
        self.pool = pool

    async def insert_open_interest(self, records: Sequence[OIRecord]) -> None:
        if not records:
            return
        rows = [
            (record.timestamp, record.symbol, record.open_interest)
            for record in records
        ]
        async with self.pool.acquire() as connection:
            await connection.executemany(
                """
                INSERT INTO open_interest (timestamp, symbol, open_interest)
                VALUES ($1, $2, $3)
                ON CONFLICT (timestamp, symbol)
                DO UPDATE SET open_interest = EXCLUDED.open_interest
                """,
                rows,
            )

    async def insert_funding_rate(self, records: Sequence[FundingRateRecord]) -> None:
        if not records:
            return
        rows = [
            (record.timestamp, record.symbol, record.funding_rate) for record in records
        ]
        async with self.pool.acquire() as connection:
            await connection.executemany(
                """
                INSERT INTO funding_rate (timestamp, symbol, funding_rate)
                VALUES ($1, $2, $3)
                ON CONFLICT (timestamp, symbol)
                DO UPDATE SET funding_rate = EXCLUDED.funding_rate
                """,
                rows,
            )


__all__ = [
    "FundingRateRecord",
    "OIRecord",
    "TradingViewTimescaleWriter",
    "normalize_utc_timestamp",
]
