"""Shared continuous-UTC timeframe grid semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..config.schema import TIMEFRAME_DURATIONS
from ..contracts import require_utc


@dataclass(frozen=True, slots=True)
class ContinuousUTCGrid:
    timeframe: str

    def __post_init__(self) -> None:
        if self.timeframe not in TIMEFRAME_DURATIONS:
            raise ValueError(f"unsupported timeframe: {self.timeframe}")

    @property
    def duration(self) -> timedelta:
        return TIMEFRAME_DURATIONS[self.timeframe]

    def is_aligned(self, instant: datetime) -> bool:
        require_utc(instant, field_name="grid instant")
        epoch_us = (
            instant.toordinal() - datetime(1970, 1, 1, tzinfo=UTC).toordinal()
        ) * 86_400_000_000 + instant.hour * 3_600_000_000 + instant.minute * 60_000_000 + instant.second * 1_000_000 + instant.microsecond
        duration_us = int(self.duration.total_seconds() * 1_000_000)
        return epoch_us % duration_us == 0

    def expected_closed_cutoff(self, market_as_of: datetime) -> datetime:
        """Latest closed bucket at a closed publication cutoff."""

        require_utc(market_as_of, field_name="market_as_of")
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        elapsed = market_as_of - epoch
        duration_us = int(self.duration.total_seconds() * 1_000_000)
        elapsed_us = elapsed.days * 86_400_000_000 + elapsed.seconds * 1_000_000 + elapsed.microseconds
        return epoch + timedelta(microseconds=(elapsed_us // duration_us) * duration_us)

    def validate_bar(self, opened: datetime, closed: datetime) -> None:
        require_utc(opened, field_name="bar_open_at")
        require_utc(closed, field_name="bar_close_at")
        if closed - opened != self.duration:
            raise ValueError(f"{self.timeframe} bar duration is invalid")
        if not self.is_aligned(opened) or not self.is_aligned(closed):
            raise ValueError(f"{self.timeframe} bar is not UTC-grid aligned")

    def validate_contiguous(self, opens: tuple[datetime, ...], closes: tuple[datetime, ...]) -> None:
        if len(opens) != len(closes):
            raise ValueError("bar opens/closes length mismatch")
        previous_close: datetime | None = None
        for opened, closed in zip(opens, closes):
            self.validate_bar(opened, closed)
            if previous_close is not None and opened != previous_close:
                raise ValueError(f"gapped {self.timeframe} history")
            previous_close = closed


def grid_for(timeframe: str) -> ContinuousUTCGrid:
    return ContinuousUTCGrid(timeframe)


__all__ = ["ContinuousUTCGrid", "grid_for"]
