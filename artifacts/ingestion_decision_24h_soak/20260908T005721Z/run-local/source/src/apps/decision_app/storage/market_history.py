"""Read-only decision-owned access to canonical ``ingestion.candles``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from apps.decision_app.domain.market_state import (
    MarketSeriesKey,
    TimeframeGrid,
    validate_canonical_bar_geometry,
)
from apps.decision_app.transport.ingestion import validate_canonical_provenance
from libs.contracts.decision import CausalBarView, require_utc


class CanonicalHistoryError(ValueError):
    """Raised when canonical DB history cannot be trusted."""


_FIELDS = (
    "venue, instrument_id, timeframe, open_time, close_time, open, high, low, "
    "close, volume, taker_buy_base, source_type, source_provider, source_timeframe"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalMarketRecord:
    """One exact canonical bar plus the provenance needed for D9B equality."""

    series_key: MarketSeriesKey
    bar: CausalBarView
    source_type: str
    source_provider: str | None
    source_timeframe: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.series_key, MarketSeriesKey):
            raise TypeError("series_key must be MarketSeriesKey")
        if not isinstance(self.bar, CausalBarView) or not self.bar.closed:
            raise ValueError("canonical record requires a closed bar")
        if self.bar.timeframe != self.series_key.timeframe:
            raise ValueError("record bar timeframe must match series")
        try:
            validate_canonical_provenance(
                self.source_type,
                self.source_provider,
                self.source_timeframe,
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalHistoryError(str(exc)) from exc


class CanonicalMarketHistoryRepository:
    """Minimal asyncpg reader; it never writes or imports ingestion storage code."""

    def __init__(
        self, pool: Any, *, timeframe_grid: TimeframeGrid | None = None
    ) -> None:
        if pool is None or not hasattr(pool, "acquire"):
            raise TypeError("pool must provide asyncpg acquire()")
        if timeframe_grid is not None and not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be TimeframeGrid or None")
        self._pool = pool
        self._timeframe_grid = timeframe_grid

    async def fetch_latest_cutoff(self, key: MarketSeriesKey) -> datetime | None:
        self._validate_key(key)
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT close_time, source_type, source_provider, source_timeframe
                  FROM ingestion.candles
                 WHERE venue = $1 AND instrument_id = $2 AND timeframe = $3
                 ORDER BY close_time DESC, open_time DESC
                 LIMIT 1
                """,
                key.venue,
                key.instrument_id,
                key.timeframe,
            )
        if row is None:
            return None
        try:
            validate_canonical_provenance(
                _row_value(row, "source_type"),
                _row_value(row, "source_provider"),
                _row_value(row, "source_timeframe"),
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalHistoryError(f"DB row provenance is invalid: {exc}") from exc
        cutoff = _row_value(row, "close_time")
        require_utc(cutoff, field_name="canonical close_time")
        return cutoff

    async def fetch_bars(
        self,
        key: MarketSeriesKey,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        through: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[CausalBarView, ...]:
        self._validate_key(key)
        bounds = [start, end, through]
        for index, value in enumerate(bounds):
            if value is not None:
                require_utc(value, field_name=("start", "end", "through")[index])
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        clauses = ["venue = $1", "instrument_id = $2", "timeframe = $3"]
        args: list[Any] = [key.venue, key.instrument_id, key.timeframe]
        if start is not None:
            args.append(start)
            clauses.append(f"open_time >= ${len(args)}")
        if end is not None:
            args.append(end)
            clauses.append(f"open_time < ${len(args)}")
        if through is not None:
            args.append(through)
            clauses.append(f"close_time <= ${len(args)}")
        limit_sql = ""
        if limit is not None:
            args.append(limit)
            limit_sql = f" LIMIT ${len(args)}"
        ordering = (
            "ORDER BY open_time DESC, close_time DESC"
            if limit is not None
            else "ORDER BY open_time ASC, close_time ASC"
        )
        query = (
            f"SELECT {_FIELDS} FROM ingestion.candles WHERE "
            + " AND ".join(clauses)
            + f" {ordering}"
            + limit_sql
        )
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(query, *args)
        bars = tuple(self._row_to_bar(row, key) for row in rows)
        return tuple(reversed(bars)) if limit is not None else bars

    async def fetch_record_at(
        self,
        key: MarketSeriesKey,
        bar_open_at: datetime,
    ) -> CanonicalMarketRecord | None:
        """Read one exact canonical identity for duplicate/DB-ahead checks."""

        self._validate_key(key)
        require_utc(bar_open_at, field_name="bar_open_at")
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                f"""SELECT {_FIELDS} FROM ingestion.candles
                    WHERE venue = $1 AND instrument_id = $2
                      AND timeframe = $3 AND open_time = $4
                    LIMIT 1""",
                key.venue,
                key.instrument_id,
                key.timeframe,
                bar_open_at,
            )
        return None if row is None else self._row_to_record(row, key)

    def _row_to_bar(self, row: Any, key: MarketSeriesKey) -> CausalBarView:
        return self._row_to_record(row, key).bar

    def _row_to_record(
        self,
        row: Any,
        key: MarketSeriesKey,
    ) -> CanonicalMarketRecord:
        venue = _text(_row_value(row, "venue"), "venue")
        instrument_id = _text(_row_value(row, "instrument_id"), "instrument_id")
        timeframe = _text(_row_value(row, "timeframe"), "timeframe")
        if (venue, instrument_id, timeframe) != (
            key.venue,
            key.instrument_id,
            key.timeframe,
        ):
            raise CanonicalHistoryError(
                "DB row identity does not match requested series"
            )
        try:
            validate_canonical_provenance(
                _row_value(row, "source_type"),
                _row_value(row, "source_provider"),
                _row_value(row, "source_timeframe"),
            )
        except (TypeError, ValueError) as exc:
            raise CanonicalHistoryError(f"DB row provenance is invalid: {exc}") from exc
        opened_at = _utc(_row_value(row, "open_time"), "open_time")
        closed_at = _utc(_row_value(row, "close_time"), "close_time")
        bar = CausalBarView(
            timeframe=timeframe,
            bar_open_at=opened_at,
            bar_close_at=closed_at,
            market_as_of=closed_at,
            open=_decimal(_row_value(row, "open"), "open"),
            high=_decimal(_row_value(row, "high"), "high"),
            low=_decimal(_row_value(row, "low"), "low"),
            close=_decimal(_row_value(row, "close"), "close"),
            volume=_decimal(_row_value(row, "volume"), "volume"),
            taker_buy_base=(
                None
                if _row_value(row, "taker_buy_base") is None
                else _decimal(_row_value(row, "taker_buy_base"), "taker_buy_base")
            ),
            closed=True,
        )
        if self._timeframe_grid is not None:
            validate_canonical_bar_geometry(key, bar, self._timeframe_grid)
        source_type, source_provider, source_timeframe = validate_canonical_provenance(
            _row_value(row, "source_type"),
            _row_value(row, "source_provider"),
            _row_value(row, "source_timeframe"),
        )
        return CanonicalMarketRecord(
            series_key=key,
            bar=bar,
            source_type=source_type,
            source_provider=source_provider,
            source_timeframe=source_timeframe,
        )

    @staticmethod
    def _validate_key(key: MarketSeriesKey) -> None:
        if not isinstance(key, MarketSeriesKey):
            raise TypeError("key must be MarketSeriesKey")


class InMemoryCanonicalMarketHistoryRepository:
    """Small deterministic history seam for offline startup tests."""

    def __init__(
        self,
        bars_by_series: Mapping[MarketSeriesKey, Sequence[CausalBarView]] = (),
        *,
        timeframe_grid: TimeframeGrid | None = None,
        records_by_series: Mapping[MarketSeriesKey, Sequence[CanonicalMarketRecord]]
        | None = None,
    ) -> None:
        if isinstance(bars_by_series, Mapping):
            entries = bars_by_series.items()
        else:
            entries = ()
        self._grid = timeframe_grid
        self._bars: dict[MarketSeriesKey, tuple[CausalBarView, ...]] = {}
        self._records: dict[MarketSeriesKey, tuple[CanonicalMarketRecord, ...]] = {}
        for key, values in entries:
            if not isinstance(key, MarketSeriesKey):
                raise TypeError("history keys must be MarketSeriesKey")
            normalized = tuple(values)
            for bar in normalized:
                if not isinstance(bar, CausalBarView):
                    raise TypeError("history values must be CausalBarView")
                if not bar.closed:
                    raise ValueError("canonical history accepts closed bars only")
                if bar.timeframe != key.timeframe:
                    raise ValueError("history bar timeframe must match key")
                if self._grid is not None:
                    validate_canonical_bar_geometry(key, bar, self._grid)
            if any(
                current.bar_open_at <= previous.bar_open_at
                or current.bar_open_at < previous.bar_close_at
                for previous, current in pairwise(normalized)
            ):
                raise ValueError("history must be ordered and non-overlapping")
            self._bars[key] = normalized
            supplied_records = (
                None if records_by_series is None else records_by_series.get(key)
            )
            if supplied_records is None:
                self._records[key] = tuple(
                    CanonicalMarketRecord(
                        series_key=key,
                        bar=bar,
                        source_type="provider",
                        source_provider="test",
                        source_timeframe=None,
                    )
                    for bar in normalized
                )
            else:
                records = tuple(supplied_records)
                if tuple(record.bar for record in records) != normalized:
                    raise ValueError("records must match bars exactly")
                if any(record.series_key != key for record in records):
                    raise ValueError("record series must match history key")
                self._records[key] = records

    async def fetch_latest_cutoff(self, key: MarketSeriesKey) -> datetime | None:
        self._validate_key(key)
        values = self._bars.get(key, ())
        return values[-1].market_as_of if values else None

    async def fetch_bars(
        self,
        key: MarketSeriesKey,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        through: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[CausalBarView, ...]:
        self._validate_key(key)
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise ValueError("limit must be a positive integer")
        values = self._bars.get(key, ())
        if start is not None:
            require_utc(start, field_name="start")
        if end is not None:
            require_utc(end, field_name="end")
        if through is not None:
            require_utc(through, field_name="through")
        filtered = tuple(
            bar
            for bar in values
            if (start is None or bar.bar_open_at >= start)
            and (end is None or bar.bar_open_at < end)
            and (through is None or bar.market_as_of <= through)
        )
        return filtered if limit is None else filtered[-limit:]

    async def fetch_record_at(
        self,
        key: MarketSeriesKey,
        bar_open_at: datetime,
    ) -> CanonicalMarketRecord | None:
        self._validate_key(key)
        require_utc(bar_open_at, field_name="bar_open_at")
        return next(
            (
                record
                for record in self._records.get(key, ())
                if record.bar.bar_open_at == bar_open_at
            ),
            None,
        )

    @staticmethod
    def _validate_key(key: MarketSeriesKey) -> None:
        if not isinstance(key, MarketSeriesKey):
            raise TypeError("key must be MarketSeriesKey")


def _row_value(row: Any, name: str) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError) as exc:
        raise CanonicalHistoryError(f"DB row missing {name}") from exc


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalHistoryError(f"{field_name} must be non-empty text")
    return value.strip()


def _utc(value: object, field_name: str) -> datetime:
    try:
        return require_utc(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise CanonicalHistoryError(str(exc)) from exc


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise CanonicalHistoryError(f"{field_name} must be Decimal") from exc
    else:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise CanonicalHistoryError(f"{field_name} must be Decimal") from exc
    if not result.is_finite():
        raise CanonicalHistoryError(f"{field_name} must be finite")
    return result


__all__ = [
    "CanonicalHistoryError",
    "CanonicalMarketHistoryRepository",
    "CanonicalMarketRecord",
    "InMemoryCanonicalMarketHistoryRepository",
]
