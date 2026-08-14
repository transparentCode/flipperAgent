"""Direct-cursor asset lifecycle notifications for D9C.

Lifecycle records are notifications only.  ``AssetManifestStore`` remains the
authority; a relevant notification asks the service to build a fresh D9A/D9B
generation from current manifests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from apps.decision_app.live_input import compare_stream_ids, normalize_stream_id
from libs.common.asset_manifest import (
    ASSET_LIFECYCLE_STREAM,
    AssetLifecycleEvent,
)
from libs.contracts.serialization import valkey_decode


class LifecycleNotificationError(ValueError):
    """Raised when lifecycle cursor transport cannot be trusted."""


async def capture_lifecycle_tail(stream_client: Any) -> str:
    """Capture the current lifecycle tail, using ``0-0`` for an absent stream."""

    if stream_client is None or not callable(getattr(stream_client, "xrevrange", None)):
        raise TypeError("stream_client must provide xrevrange()")
    records = await stream_client.xrevrange(
        ASSET_LIFECYCLE_STREAM,
        "+",
        "-",
        count=1,
    )
    if not records:
        return "0-0"
    if not isinstance(records, Sequence):
        raise LifecycleNotificationError("lifecycle tail must be a sequence")
    return normalize_stream_id(records[0][0])


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleReadResult:
    """Bounded evidence from one lifecycle XREAD attempt."""

    cursor: str
    event_ids: tuple[str, ...] = ()
    relevant_events: tuple[AssetLifecycleEvent, ...] = ()
    ignored_symbols: tuple[str, ...] = ()
    malformed_ids: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def rebuild_requested(self) -> bool:
        return bool(self.relevant_events or self.malformed_ids)


def _entry_parts(entry: object) -> tuple[str, Mapping[object, object]]:
    if not isinstance(entry, Sequence) or len(entry) != 2:
        raise LifecycleNotificationError("lifecycle entry must be ID/fields")
    stream_id = normalize_stream_id(entry[0])
    fields = entry[1]
    if not isinstance(fields, Mapping):
        raise LifecycleNotificationError("lifecycle fields must be a mapping")
    return stream_id, fields


def _stream_entries(raw: object) -> Iterable[tuple[str, object]]:
    if isinstance(raw, Mapping):
        items = raw.items()
    elif isinstance(raw, Sequence):
        items = raw
    else:
        raise LifecycleNotificationError("XREAD result must be a sequence or mapping")
    for item in items:
        if isinstance(raw, Mapping):
            stream_key, entries = item
        else:
            if not isinstance(item, Sequence) or len(item) != 2:
                raise LifecycleNotificationError("XREAD stream result is invalid")
            stream_key, entries = item
        if isinstance(stream_key, bytes):
            stream_key = stream_key.decode("utf-8")
        if stream_key != ASSET_LIFECYCLE_STREAM:
            raise LifecycleNotificationError(
                f"unexpected lifecycle stream: {stream_key!r}"
            )
        if not isinstance(entries, Sequence):
            raise LifecycleNotificationError("XREAD lifecycle entries are invalid")
        for entry in entries:
            yield stream_key, entry


class LifecycleNotificationReader:
    """Small direct-XREAD lifecycle reader with a monotonic in-memory cursor."""

    def __init__(
        self,
        *,
        stream_client: Any,
        cursor: str,
        configured_manifest_assets: Iterable[str],
        block_ms: int = 1000,
        batch_size: int = 100,
    ) -> None:
        if stream_client is None or not callable(getattr(stream_client, "xread", None)):
            raise TypeError("stream_client must provide direct xread()")
        self._client = stream_client
        self._cursor = normalize_stream_id(cursor)
        assets = tuple(
            str(asset).strip().upper() for asset in configured_manifest_assets
        )
        if any(not asset for asset in assets):
            raise ValueError("configured lifecycle assets must be non-empty")
        self._configured_assets = frozenset(assets)
        if isinstance(block_ms, bool) or not isinstance(block_ms, int) or block_ms < 0:
            raise ValueError("block_ms must be a non-negative integer")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
        ):
            raise ValueError("batch_size must be positive")
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._last_result = LifecycleReadResult(cursor=self._cursor)

    @property
    def cursor(self) -> str:
        return self._cursor

    @property
    def block_ms(self) -> int:
        return self._block_ms

    @property
    def last_result(self) -> LifecycleReadResult:
        return self._last_result

    async def read_once(self) -> LifecycleReadResult:
        """Read after the captured cursor and advance past every seen record."""

        try:
            raw = await self._client.xread(
                {ASSET_LIFECYCLE_STREAM: self._cursor},
                count=self._batch_size,
                block=self._block_ms,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise LifecycleNotificationError(f"lifecycle XREAD failed: {exc}") from exc

        if not raw:
            result = LifecycleReadResult(cursor=self._cursor)
            self._last_result = result
            return result

        event_ids: list[str] = []
        relevant: list[AssetLifecycleEvent] = []
        ignored: list[str] = []
        malformed: list[str] = []
        reasons: list[str] = []
        for _stream_key, raw_entry in _stream_entries(raw):
            try:
                stream_id, fields = _entry_parts(raw_entry)
            except Exception as exc:
                # There is no trustworthy ID to advance to.  Surface the
                # transport/shape failure without changing the cursor.
                raise LifecycleNotificationError(str(exc)) from exc
            if compare_stream_ids(stream_id, self._cursor) <= 0:
                malformed.append(stream_id)
                reasons.append(f"non-forward lifecycle ID {stream_id}")
                continue
            self._cursor = stream_id
            event_ids.append(stream_id)
            try:
                event = valkey_decode(dict(fields), AssetLifecycleEvent)
                if event.source != "ingestion" or event.requested_by != "ingestion":
                    raise ValueError("lifecycle event is not ingestion-owned")
            except Exception as exc:  # noqa: BLE001
                malformed.append(stream_id)
                reasons.append(f"malformed lifecycle event {stream_id}: {exc}")
                continue
            if event.symbol in self._configured_assets:
                relevant.append(event)
            else:
                ignored.append(event.symbol)

        result = LifecycleReadResult(
            cursor=self._cursor,
            event_ids=tuple(event_ids),
            relevant_events=tuple(relevant),
            ignored_symbols=tuple(sorted(set(ignored))),
            malformed_ids=tuple(malformed),
            reason="; ".join(reasons) if reasons else None,
        )
        self._last_result = result
        return result


__all__ = [
    "ASSET_LIFECYCLE_STREAM",
    "LifecycleNotificationError",
    "LifecycleNotificationReader",
    "LifecycleReadResult",
    "capture_lifecycle_tail",
]
