"""Bounded direct-cursor input for the D9B live decision primitive.

This module is intentionally a transport/acceptance seam, not a worker.  It
uses direct XREAD, starts strictly after D9A's captured tails, and never owns
model progress or publication state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from apps.decision_app.contracts import InputReadCursor
from apps.decision_app.ingestion_input import (
    CanonicalIngestionEventError,
    CanonicalMarketEvent,
    canonical_ingestion_stream_key,
    parse_canonical_ingestion_event,
)
from apps.decision_app.market_state import (
    BarConflictError,
    BarOrderError,
    BarStore,
    MarketSeriesKey,
    TimeframeGrid,
)
from apps.decision_app.startup import SeriesStartupPosition
from apps.decision_app.storage.market_history import CanonicalMarketRecord
from libs.contracts.decision import CausalBarView, FrozenMapping, require_utc

InputDisposition = Literal[
    "INSERTED",
    "DUPLICATE",
    "ALREADY_REPRESENTED",
    "RECONSTRUCTION_REQUIRED",
    "CONFLICT",
    "MALFORMED",
]


class LiveInputError(ValueError):
    """Base error for direct-cursor input contract violations."""


class InputTransportError(LiveInputError):
    """Raised when the direct XREAD transport cannot be used safely."""


class StreamIdError(LiveInputError):
    """Raised for malformed or non-forward stream IDs."""


def _text(value: object, field_name: str) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StreamIdError(f"{field_name} is not UTF-8") from exc
    if not isinstance(value, str) or not value.strip():
        raise StreamIdError(f"{field_name} must be non-empty text")
    return value.strip()


def normalize_stream_id(value: object) -> str:
    """Normalize and validate a Redis/Valkey stream ID."""

    normalized = _text(value, "stream_id")
    parts = normalized.split("-")
    if len(parts) != 2 or any(not part.isdigit() for part in parts):
        raise StreamIdError("stream_id must be <non-negative-ms>-<non-negative-seq>")
    return f"{int(parts[0])}-{int(parts[1])}"


def compare_stream_ids(left: object, right: object) -> int:
    """Compare stream IDs numerically rather than lexicographically."""

    left_parts = tuple(int(part) for part in normalize_stream_id(left).split("-"))
    right_parts = tuple(int(part) for part in normalize_stream_id(right).split("-"))
    return (left_parts > right_parts) - (left_parts < right_parts)


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingInputRecord:
    """Parsed record awaiting cutoff-group acceptance."""

    stream_key: str
    stream_id: str
    event: CanonicalMarketEvent
    ordinal: int

    def __post_init__(self) -> None:
        if self.stream_key != self.event.stream_key:
            raise ValueError("pending stream key must match event")
        if self.stream_id != self.event.stream_id:
            raise ValueError("pending stream ID must match event")
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("pending ordinal must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class InputRecordResult:
    """Bounded evidence for one parsed or accepted input record."""

    stream_key: str
    stream_id: str | None
    series_key: MarketSeriesKey | None
    market_as_of: datetime | None
    disposition: InputDisposition
    event: CanonicalMarketEvent | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stream_key, str) or not self.stream_key.strip():
            raise ValueError("input result stream_key must be non-empty")
        if self.stream_id is not None:
            object.__setattr__(self, "stream_id", normalize_stream_id(self.stream_id))
        if self.series_key is not None and not isinstance(
            self.series_key, MarketSeriesKey
        ):
            raise TypeError("input result series_key must be MarketSeriesKey")
        if self.market_as_of is not None:
            require_utc(self.market_as_of, field_name="input market_as_of")
        if self.disposition not in {
            "INSERTED",
            "DUPLICATE",
            "ALREADY_REPRESENTED",
            "RECONSTRUCTION_REQUIRED",
            "CONFLICT",
            "MALFORMED",
        }:
            raise ValueError("unsupported input disposition")
        if self.event is not None:
            if self.event.stream_key != self.stream_key:
                raise ValueError("input result event stream does not match")
            if self.stream_id != self.event.stream_id:
                raise ValueError("input result event ID does not match")
            if self.series_key != self.event.series_key:
                raise ValueError("input result event series does not match")
            if self.market_as_of != self.event.bar.market_as_of:
                raise ValueError("input result event cutoff does not match")
        if self.reason is not None and (
            not isinstance(self.reason, str) or not self.reason.strip()
        ):
            raise ValueError("input result reason must be non-empty")


@dataclass(frozen=True, slots=True, kw_only=True)
class InputReadBatch:
    """One bounded XREAD result before live cutoff processing."""

    records: tuple[PendingInputRecord, ...] = ()
    failures: tuple[InputRecordResult, ...] = ()


def _record_matches_event(
    record: CanonicalMarketRecord | None,
    event: CanonicalMarketEvent,
) -> bool:
    return bool(
        record is not None
        and record.series_key == event.series_key
        and record.bar == event.bar
        and record.source_type == event.source_type
        and record.source_provider == event.source_provider
        and record.source_timeframe == event.source_timeframe
    )


class DirectCursorInput:
    """Read and accept canonical ingestion records with independent cursors."""

    def __init__(
        self,
        *,
        stream_client: Any,
        startup_positions: Mapping[MarketSeriesKey, SeriesStartupPosition],
        bar_store: BarStore,
        history_repository: Any,
        timeframe_grid: TimeframeGrid,
        batch_size: int = 10,
        block_ms: int = 1000,
    ) -> None:
        if stream_client is None or not callable(getattr(stream_client, "xread", None)):
            raise TypeError("stream_client must provide direct xread()")
        if not isinstance(startup_positions, Mapping) or not startup_positions:
            raise ValueError("startup_positions must not be empty")
        if not isinstance(bar_store, BarStore):
            raise TypeError("bar_store must be BarStore")
        if not callable(getattr(history_repository, "fetch_record_at", None)):
            raise TypeError("history_repository must provide fetch_record_at()")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be TimeframeGrid")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
        ):
            raise ValueError("batch_size must be positive")
        if isinstance(block_ms, bool) or not isinstance(block_ms, int) or block_ms < 0:
            raise ValueError("block_ms must be non-negative")
        self._stream_client = stream_client
        self._bar_store = bar_store
        self._history = history_repository
        self._grid = timeframe_grid
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._series_by_stream: dict[str, MarketSeriesKey] = {}
        self._positions: dict[MarketSeriesKey, SeriesStartupPosition] = {}
        self._cursors: dict[str, InputReadCursor] = {}
        for key, position in startup_positions.items():
            if not isinstance(key, MarketSeriesKey) or not isinstance(
                position, SeriesStartupPosition
            ):
                raise TypeError("startup_positions must contain typed positions")
            if key != position.series_key:
                raise ValueError("startup position key must match series")
            stream_key = canonical_ingestion_stream_key(key)
            if stream_key != position.stream_key:
                raise ValueError("startup position stream key is not canonical")
            if stream_key in self._series_by_stream:
                raise ValueError("duplicate startup stream key")
            self._series_by_stream[stream_key] = key
            self._positions[key] = position
            self._cursors[stream_key] = InputReadCursor(
                stream_key=stream_key,
                latest_stream_id=position.captured_tail_id,
                latest_market_as_of=position.warm_cutoff,
            )
        self._blocked_streams: dict[str, str] = {}

    @property
    def cursors(self) -> Mapping[str, InputReadCursor]:
        return FrozenMapping(dict(sorted(self._cursors.items())))

    @property
    def blocked_streams(self) -> Mapping[str, str]:
        return FrozenMapping(dict(sorted(self._blocked_streams.items())))

    @property
    def stream_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._series_by_stream))

    def cursor_for(self, key_or_stream: MarketSeriesKey | str) -> InputReadCursor:
        stream_key = (
            canonical_ingestion_stream_key(key_or_stream)
            if isinstance(key_or_stream, MarketSeriesKey)
            else _text(key_or_stream, "stream_key")
        )
        try:
            return self._cursors[stream_key]
        except KeyError as exc:
            raise KeyError(f"unknown input stream: {stream_key}") from exc

    def block_stream(self, stream_key: str, reason: str) -> None:
        stream_key = _text(stream_key, "stream_key")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("stream block reason must be non-empty")
        self._blocked_streams.setdefault(stream_key, reason)

    async def read_once(self) -> InputReadBatch:
        """Perform exactly one bounded direct XREAD."""

        active = {
            stream_key: (
                cursor.latest_stream_id
                if cursor.latest_stream_id is not None
                else "0-0"
            )
            for stream_key, cursor in self._cursors.items()
            if stream_key not in self._blocked_streams
        }
        if not active:
            return InputReadBatch()
        try:
            raw = await self._xread(active)
        except Exception as exc:
            raise InputTransportError(f"direct XREAD failed: {exc}") from exc
        records: list[PendingInputRecord] = []
        failures: list[InputRecordResult] = []
        ordinal = 0
        if raw is None:
            return InputReadBatch()
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise InputTransportError("XREAD result must be a sequence")
        for raw_stream_item in raw:
            if (
                isinstance(raw_stream_item, (str, bytes))
                or not isinstance(raw_stream_item, Sequence)
                or len(raw_stream_item) != 2
            ):
                raise InputTransportError(
                    "XREAD stream result must be a stream/entries pair"
                )
            raw_stream, raw_entries = raw_stream_item
            try:
                stream_key = _text(raw_stream, "returned stream key")
            except StreamIdError as exc:
                raise InputTransportError(str(exc)) from exc
            key = self._series_by_stream.get(stream_key)
            if key is None:
                self.block_stream(stream_key, "unexpected stream key")
                failures.append(
                    InputRecordResult(
                        stream_key=stream_key,
                        stream_id=None,
                        series_key=None,
                        market_as_of=None,
                        disposition="MALFORMED",
                        reason="unexpected stream key",
                    )
                )
                continue
            if stream_key in self._blocked_streams:
                continue
            if isinstance(raw_entries, (str, bytes)) or not isinstance(
                raw_entries, Sequence
            ):
                self.block_stream(stream_key, "stream entries are not a sequence")
                failures.append(
                    InputRecordResult(
                        stream_key=stream_key,
                        stream_id=None,
                        series_key=key,
                        market_as_of=None,
                        disposition="MALFORMED",
                        reason="stream entries are not a sequence",
                    )
                )
                continue
            previous_id = self._cursors[stream_key].latest_stream_id or "0-0"
            for raw_entry in raw_entries:
                if (
                    isinstance(raw_entry, (str, bytes))
                    or not isinstance(raw_entry, Sequence)
                    or len(raw_entry) != 2
                ):
                    reason = "stream entry must be an ID/fields pair"
                    failures.append(
                        InputRecordResult(
                            stream_key=stream_key,
                            stream_id=None,
                            series_key=key,
                            market_as_of=None,
                            disposition="MALFORMED",
                            reason=reason,
                        )
                    )
                    break
                raw_id, fields = raw_entry
                stream_id: str | None = None
                try:
                    stream_id = normalize_stream_id(raw_id)
                    if compare_stream_ids(stream_id, previous_id) <= 0:
                        raise StreamIdError(
                            "returned stream ID is not strictly forward"
                        )
                    event = parse_canonical_ingestion_event(
                        stream_key=stream_key,
                        stream_id=stream_id,
                        fields=fields,
                        expected_series=key,
                        timeframe_grid=self._grid,
                    )
                except (
                    CanonicalIngestionEventError,
                    StreamIdError,
                    TypeError,
                    ValueError,
                ) as exc:
                    reason = str(exc)
                    failures.append(
                        InputRecordResult(
                            stream_key=stream_key,
                            stream_id=stream_id,
                            series_key=key,
                            market_as_of=None,
                            disposition="MALFORMED",
                            reason=reason,
                        )
                    )
                    break
                records.append(
                    PendingInputRecord(
                        stream_key=stream_key,
                        stream_id=stream_id,
                        event=event,
                        ordinal=ordinal,
                    )
                )
                ordinal += 1
                previous_id = stream_id
        return InputReadBatch(records=tuple(records), failures=tuple(failures))

    async def accept(self, pending: PendingInputRecord) -> InputRecordResult:
        """Classify one parsed event and advance only its transport cursor."""

        if not isinstance(pending, PendingInputRecord):
            raise TypeError("pending must be PendingInputRecord")
        event = pending.event
        stream_key = pending.stream_key
        key = event.series_key
        if stream_key in self._blocked_streams:
            return self._result(
                pending,
                "RECONSTRUCTION_REQUIRED",
                self._blocked_streams[stream_key],
            )
        cursor = self._cursors[stream_key]
        previous_id = cursor.latest_stream_id or "0-0"
        if compare_stream_ids(pending.stream_id, previous_id) <= 0:
            self.block_stream(stream_key, "accepted record is not forward")
            return self._result(
                pending,
                "MALFORMED",
                "accepted record is not forward",
            )

        warm_cutoff = self._positions[key].warm_cutoff
        if warm_cutoff is not None and event.bar.market_as_of <= warm_cutoff:
            record = await self._history.fetch_record_at(key, event.bar.bar_open_at)
            if _record_matches_event(record, event):
                self._advance_cursor(stream_key, pending.stream_id, event)
                return self._result(pending, "ALREADY_REPRESENTED", "startup DB match")
            self.block_stream(stream_key, "startup history does not match event")
            return self._result(
                pending,
                "CONFLICT" if record is not None else "RECONSTRUCTION_REQUIRED",
                "startup history does not match event",
            )

        retained = self._retained_bar(
            key,
            event.bar.bar_open_at,
            event.bar.bar_close_at,
        )
        if retained is not None:
            if retained != event.bar:
                self.block_stream(stream_key, "conflicting retained canonical bar")
                return self._result(
                    pending,
                    "CONFLICT",
                    "conflicting retained canonical bar",
                )
            record = await self._history.fetch_record_at(key, event.bar.bar_open_at)
            if record is None:
                self.block_stream(stream_key, "retained bar lacks durable provenance")
                return self._result(
                    pending,
                    "RECONSTRUCTION_REQUIRED",
                    "retained bar lacks durable provenance",
                )
            if _record_matches_event(record, event):
                self._advance_cursor(stream_key, pending.stream_id, event)
                return self._result(
                    pending,
                    "DUPLICATE",
                    "exact retained canonical duplicate",
                )
            self.block_stream(stream_key, "conflicting durable canonical identity")
            return self._result(
                pending,
                "CONFLICT",
                "conflicting durable canonical identity",
            )

        latest = self._bar_store.latest_at_or_before(
            key, datetime.max.replace(tzinfo=event.bar.bar_open_at.tzinfo)
        )
        if latest is None:
            try:
                self._bar_store.append(key, event.bar)
            except (BarConflictError, BarOrderError, ValueError) as exc:
                self.block_stream(stream_key, str(exc))
                return self._result(pending, "CONFLICT", str(exc))
            self._advance_cursor(stream_key, pending.stream_id, event)
            return self._result(pending, "INSERTED")

        if event.bar.bar_open_at < latest.bar_open_at:
            self.block_stream(stream_key, "late post-startup historical event")
            return self._result(
                pending,
                "RECONSTRUCTION_REQUIRED",
                "late post-startup historical event",
            )
        if event.bar.bar_open_at == latest.bar_open_at:
            self.block_stream(stream_key, "conflicting canonical identity")
            return self._result(pending, "CONFLICT", "conflicting canonical identity")
        if event.bar.bar_open_at > latest.bar_close_at:
            self.block_stream(stream_key, "forward canonical market gap")
            return self._result(
                pending,
                "RECONSTRUCTION_REQUIRED",
                "forward canonical market gap",
            )
        if event.bar.bar_open_at < latest.bar_close_at:
            self.block_stream(stream_key, "overlapping canonical bar")
            return self._result(pending, "CONFLICT", "overlapping canonical bar")

        try:
            self._bar_store.append(key, event.bar)
        except (BarConflictError, BarOrderError, ValueError) as exc:
            self.block_stream(stream_key, str(exc))
            return self._result(pending, "CONFLICT", str(exc))
        self._advance_cursor(stream_key, pending.stream_id, event)
        return self._result(pending, "INSERTED")

    def _retained_bar(
        self,
        key: MarketSeriesKey,
        bar_open_at: datetime,
        through: datetime,
    ) -> CausalBarView | None:
        return next(
            (
                bar
                for bar in self._bar_store.bars_at(key, through)
                if bar.bar_open_at == bar_open_at
            ),
            None,
        )

    async def _xread(self, streams: Mapping[str, str]) -> Any:
        return await self._stream_client.xread(
            streams,
            count=self._batch_size,
            block=self._block_ms,
        )

    def _advance_cursor(
        self,
        stream_key: str,
        stream_id: str,
        event: CanonicalMarketEvent,
    ) -> None:
        cursor = self._cursors[stream_key]
        latest_market = cursor.latest_market_as_of
        event_cutoff = event.bar.market_as_of
        if latest_market is None or event_cutoff > latest_market:
            latest_market = event_cutoff
        self._cursors[stream_key] = InputReadCursor(
            stream_key=stream_key,
            latest_stream_id=normalize_stream_id(stream_id),
            latest_market_as_of=latest_market,
        )

    @staticmethod
    def _result(
        pending: PendingInputRecord,
        disposition: InputDisposition,
        reason: str | None = None,
    ) -> InputRecordResult:
        return InputRecordResult(
            stream_key=pending.stream_key,
            stream_id=pending.stream_id,
            series_key=pending.event.series_key,
            market_as_of=pending.event.bar.market_as_of,
            disposition=disposition,
            event=pending.event,
            reason=reason,
        )


__all__ = [
    "DirectCursorInput",
    "InputDisposition",
    "InputReadBatch",
    "InputRecordResult",
    "InputTransportError",
    "LiveInputError",
    "PendingInputRecord",
    "StreamIdError",
    "compare_stream_ids",
    "normalize_stream_id",
]
