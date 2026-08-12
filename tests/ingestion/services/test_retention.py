from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from apps.ingestion_app.services.retention import RetentionJanitor
from apps.ingestion_app.settings import RetentionSettings

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _settings(
    *,
    cleanup_interval_seconds: int = 86_400,
    error_backoff_seconds: int = 60,
    batch_size: int = 2,
    max_batches: int = 3,
) -> RetentionSettings:
    return RetentionSettings(
        candle_days=90,
        published_outbox_days=7,
        cleanup_interval_seconds=cleanup_interval_seconds,
        error_backoff_seconds=error_backoff_seconds,
        outbox_delete_batch_size=batch_size,
        outbox_max_batches_per_run=max_batches,
    )


class _Repository:
    def __init__(self, deleted: list[int], *, fail_count: int = 0) -> None:
        self.deleted = list(deleted)
        self.fail_count = fail_count
        self.calls: list[tuple[str, object]] = []

    async def delete_published_outbox_before(self, *, cutoff, limit: int) -> int:
        self.calls.append(("outbox", cutoff, limit))
        if self.fail_count:
            self.fail_count -= 1
            raise RuntimeError("temporary database failure")
        return self.deleted.pop(0) if self.deleted else 0

    async def drop_candle_chunks_before(self, *, cutoff):
        self.calls.append(("candles", cutoff))
        return ("_hyper_1_1_chunk",)


@pytest.mark.asyncio
async def test_cleanup_once_is_bounded_and_deletes_outbox_before_chunks() -> None:
    repository = _Repository([2, 1])
    janitor = RetentionJanitor(
        repository=repository,  # type: ignore[arg-type]
        settings=_settings(),
        now_fn=lambda: NOW,
    )

    evidence = await janitor.cleanup_once()

    assert evidence.started_at == NOW
    assert evidence.candle_cutoff == NOW - timedelta(days=90)
    assert evidence.published_outbox_cutoff == NOW - timedelta(days=7)
    assert evidence.outbox_rows_deleted == 3
    assert evidence.outbox_batches == 2
    assert evidence.candle_chunks_dropped == ("_hyper_1_1_chunk",)
    assert [call[0] for call in repository.calls] == [
        "outbox",
        "outbox",
        "candles",
    ]
    assert janitor.last_evidence == evidence


@pytest.mark.asyncio
async def test_run_retries_transient_failure_without_external_wake() -> None:
    repository = _Repository([0], fail_count=1)
    janitor = RetentionJanitor(
        repository=repository,
        settings=_settings(cleanup_interval_seconds=86_400, error_backoff_seconds=0),
        now_fn=lambda: NOW,
    )  # type: ignore[arg-type]
    task = asyncio.create_task(janitor.run())

    try:
        for _ in range(100):
            if len([call for call in repository.calls if call[0] == "outbox"]) >= 2:
                break
            await asyncio.sleep(0)
        assert len([call for call in repository.calls if call[0] == "outbox"]) == 2
        assert janitor.last_evidence is not None
        assert not task.done()
    finally:
        await janitor.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_persistent_failure_is_backed_off_and_cancellation_is_prompt() -> None:
    repository = _Repository([], fail_count=10_000)
    janitor = RetentionJanitor(
        repository=repository,
        settings=_settings(error_backoff_seconds=1),
        now_fn=lambda: NOW,
    )  # type: ignore[arg-type]
    task = asyncio.create_task(janitor.run())

    await asyncio.sleep(0.05)
    assert len(repository.calls) == 1
    assert not task.done()

    await janitor.stop()
    await asyncio.wait_for(task, timeout=0.5)
    assert not task.cancelled()
