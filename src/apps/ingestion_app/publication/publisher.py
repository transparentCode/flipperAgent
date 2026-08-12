"""Durable ingestion outbox publication to bounded Valkey streams."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.publication.outbox import OutboxEvent
from apps.ingestion_app.publication.stream_keys import canonical_lane_stream_key
from apps.ingestion_app.settings import PublicationSettings
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


def _event_occurred_at(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("event occurred_at must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _event_fields(event: OutboxEvent) -> dict[str, str]:
    if not isinstance(event.event_id, UUID):
        raise TypeError("event_id must be a UUID")
    if not isinstance(event.payload_json, str):
        raise TypeError("payload_json must be a string")
    return {
        "event_id": str(event.event_id),
        "event_type": str(event.event_type),
        "schema_version": str(event.schema_version),
        "producer": str(event.producer),
        "occurred_at": _event_occurred_at(event.occurred_at),
        "payload": event.payload_json,
    }


class OutboxPublisher:
    """Publish pending outbox rows with explicit at-least-once semantics."""

    def __init__(
        self,
        *,
        repository: CandleRepository,
        valkey_client: Any,
        publication: PublicationSettings,
        now_fn: Callable[[], datetime] | None = None,
        observability: IngestionObservability | None = None,
        on_connection_restored: Callable[[], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.valkey_client = valkey_client
        self.publication = publication
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._stop_event = asyncio.Event()
        self.observability = observability or IngestionObservability()
        self._on_connection_restored = on_connection_restored

    async def _refresh_observability_state(self) -> None:
        fetch_state = getattr(self.repository, "fetch_pending_outbox_state", None)
        if not callable(fetch_state):
            return
        try:
            pending, oldest_pending = await fetch_state()
            self.observability.set_outbox_state(
                pending=pending,
                oldest_pending=oldest_pending,
            )
        except Exception:
            _LOGGER.warning(
                "Failed to refresh ingestion outbox observability state", exc_info=True
            )

    async def publish_once(self) -> int:
        """Publish one ordered pending batch, stopping on the first failure."""
        events = await self.repository.fetch_pending_outbox(
            limit=self.publication.batch_size,
        )
        if not events:
            return 0

        started = perf_counter()
        published_count = 0
        failed = False
        with self.observability.outbox_publish_span(len(events)) as span:
            try:
                for event in events:
                    stream_key = canonical_lane_stream_key(event)
                    await self.valkey_client.xadd(
                        stream_key,
                        _event_fields(event),
                        maxlen=self.publication.stream_maxlen,
                        approximate=self.publication.stream_approximate,
                    )
                    marked = await self.repository.mark_outbox_published(
                        event_id=event.event_id,
                        published_at=self._now_fn(),
                    )
                    if not marked:
                        raise DataIngestionError(
                            f"outbox mark miss after XADD for event {event.event_id}"
                        )
                    published_count += 1
                    self.observability.record_outbox_published()
            except BaseException:
                failed = True
                raise
            finally:
                duration_ms = (perf_counter() - started) * 1000
                self.observability.record_publish_batch(
                    batch_size=len(events),
                    successful_publishes=published_count,
                    duration_ms=duration_ms,
                    failed=failed,
                )
                span.set_attribute("successful_publishes", published_count)

        await self._refresh_observability_state()
        return published_count

    async def _wait_for_stop_or_timeout(self, timeout: int) -> None:
        if timeout == 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout)
        except TimeoutError:
            return

    async def run(self) -> None:
        """Continuously drain pending rows until stopped or cancelled."""
        _LOGGER.info("outbox publisher started")
        connection_established = True
        try:
            while not self._stop_event.is_set():
                try:
                    ping = getattr(self.valkey_client, "ping", None)
                    if callable(ping):
                        await ping()
                    if (
                        not connection_established
                        and self._on_connection_restored is not None
                    ):
                        try:
                            result = self._on_connection_restored()
                            if hasattr(result, "__await__"):
                                await result
                        except Exception:
                            _LOGGER.warning(
                                "ingestion broker reconnect reconciliation failed",
                                exc_info=True,
                            )
                        connection_established = True
                    published_count = await self.publish_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    connection_established = False
                    _LOGGER.warning("outbox publication failed", exc_info=True)
                    await self._wait_for_stop_or_timeout(
                        self.publication.error_backoff_seconds,
                    )
                    continue

                if published_count:
                    continue
                await self._wait_for_stop_or_timeout(
                    self.publication.idle_sleep_seconds,
                )
        finally:
            _LOGGER.info("outbox publisher stopped")

    def stop(self) -> None:
        """Request a prompt, non-destructive publisher shutdown."""
        self._stop_event.set()


__all__ = ["OutboxPublisher"]
