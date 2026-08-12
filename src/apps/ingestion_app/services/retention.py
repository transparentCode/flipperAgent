"""Bounded, non-authoritative retention housekeeping for ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from apps.ingestion_app.settings import RetentionSettings
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetentionCleanupEvidence:
    started_at: datetime
    candle_cutoff: datetime
    published_outbox_cutoff: datetime
    outbox_rows_deleted: int
    outbox_batches: int
    candle_chunks_dropped: tuple[str, ...]
    completed_at: datetime


def _utc_now(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value.astimezone(UTC)


class RetentionJanitor:
    """Run bounded retention work without becoming part of ingestion health."""

    def __init__(
        self,
        *,
        repository: CandleRepository,
        settings: RetentionSettings,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._stop_event = asyncio.Event()
        self._last_evidence: RetentionCleanupEvidence | None = None

    @property
    def last_evidence(self) -> RetentionCleanupEvidence | None:
        return self._last_evidence

    async def cleanup_once(self) -> RetentionCleanupEvidence:
        """Delete bounded old publication intents, then drop old candle chunks."""
        started_at = _utc_now(self._now_fn(), field_name="now")
        candle_cutoff = started_at - timedelta(days=self._settings.candle_days)
        published_outbox_cutoff = started_at - timedelta(
            days=self._settings.published_outbox_days
        )

        outbox_rows_deleted = 0
        outbox_batches = 0
        for _ in range(self._settings.outbox_max_batches_per_run):
            deleted = await self._repository.delete_published_outbox_before(
                cutoff=published_outbox_cutoff,
                limit=self._settings.outbox_delete_batch_size,
            )
            outbox_batches += 1
            outbox_rows_deleted += deleted
            if deleted < self._settings.outbox_delete_batch_size:
                break
        else:
            _LOGGER.warning(
                "Retention outbox cleanup reached its per-run batch limit; "
                "eligible rows may remain for the next run"
            )

        candle_chunks_dropped = await self._repository.drop_candle_chunks_before(
            cutoff=candle_cutoff
        )
        completed_at = _utc_now(self._now_fn(), field_name="now")
        evidence = RetentionCleanupEvidence(
            started_at=started_at,
            candle_cutoff=candle_cutoff,
            published_outbox_cutoff=published_outbox_cutoff,
            outbox_rows_deleted=outbox_rows_deleted,
            outbox_batches=outbox_batches,
            candle_chunks_dropped=candle_chunks_dropped,
            completed_at=completed_at,
        )
        self._last_evidence = evidence
        _LOGGER.info(
            "ingestion retention cleanup completed: outbox_rows_deleted=%s "
            "outbox_batches=%s candle_chunks_dropped=%s",
            evidence.outbox_rows_deleted,
            evidence.outbox_batches,
            len(evidence.candle_chunks_dropped),
        )
        return evidence

    async def run(self) -> None:
        """Run once at startup, then wait for the next bounded interval."""
        self._stop_event.clear()
        while not self._stop_event.is_set():
            try:
                await self.cleanup_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.warning(
                    "ingestion retention cleanup failed; will retry", exc_info=True
                )
                await self._wait(self._settings.error_backoff_seconds)
                continue
            await self._wait(self._settings.cleanup_interval_seconds)

    async def stop(self) -> None:
        """Wake a running janitor so shutdown does not wait for its interval."""
        self._stop_event.set()

    async def _wait(self, timeout_seconds: int) -> None:
        if timeout_seconds == 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=timeout_seconds)
        except TimeoutError:
            return


__all__ = ["RetentionCleanupEvidence", "RetentionJanitor"]
