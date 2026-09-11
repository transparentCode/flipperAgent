"""Minimal async job orchestration for scraper fetch requests."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from apps.scraper_app.core.models import (
    ScrapeIntent,
    ScrapeJobRecord,
    ScrapeJobStatus,
    ScrapeRequest,
    ScrapeResult,
)
from apps.scraper_app.service.fetch_service import ScraperFetchService


class ScraperJobService:
    """Persist lightweight fetch jobs and execute them asynchronously."""

    def __init__(
        self,
        *,
        fetch_service: ScraperFetchService,
        redis_client: Any | None = None,
        job_ttl_seconds: int = 3600,
    ) -> None:
        self.fetch_service = fetch_service
        self.redis_client = redis_client
        self.job_ttl_seconds = job_ttl_seconds
        self._memory_jobs: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def submit(self, request: ScrapeRequest) -> ScrapeJobRecord:
        """Deduplicate and queue a scrape job."""
        job_id = self.build_job_id(request)
        existing = await self.get(job_id)
        if existing:
            if existing.status in {ScrapeJobStatus.QUEUED, ScrapeJobStatus.RUNNING}:
                existing.deduped = True
                return existing
            if existing.status == ScrapeJobStatus.SUCCEEDED and self._should_reuse_completed(
                existing, request
            ):
                existing.deduped = True
                return existing

        now = time.time()
        record = ScrapeJobRecord(
            job_id=job_id,
            status=ScrapeJobStatus.QUEUED,
            request=request,
            created_at=now,
            updated_at=now,
        )

        async with self._lock:
            await self._save(record)
            self._schedule_job(job_id, request)
        return record

    async def get(self, job_id: str, *, include_result: bool = True) -> ScrapeJobRecord | None:
        """Return the current job state."""
        payload = await self._load(job_id)
        if payload is None:
            return None
        record = ScrapeJobRecord.model_validate_json(payload)
        if include_result and record.result is None and record.result_key is not None:
            record.result = await self._load_result(record.result_key)
        if not include_result:
            record.result = None
        return record

    async def shutdown(self) -> None:
        """Cancel any in-flight tasks owned by this service."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def recover_pending_jobs(self) -> int:
        """Resume queued/running jobs persisted in Valkey after process restart."""
        if self.redis_client is None:
            return 0

        recovered = 0
        async for job_key in self._iter_job_keys():
            payload = await self.redis_client.get(job_key)
            if payload is None:
                continue
            record = ScrapeJobRecord.model_validate_json(payload)
            if record.status not in {ScrapeJobStatus.QUEUED, ScrapeJobStatus.RUNNING}:
                continue
            if record.job_id in self._tasks:
                continue
            record.status = ScrapeJobStatus.QUEUED
            record.updated_at = time.time()
            await self._save(record)
            self._schedule_job(record.job_id, record.request)
            recovered += 1
        return recovered

    async def _run_job(self, job_id: str, request: ScrapeRequest) -> None:
        record = await self.get(job_id)
        if record is None:
            return

        record.status = ScrapeJobStatus.RUNNING
        record.updated_at = time.time()
        await self._save(record)

        try:
            record.result = await self.fetch_service.fetch(request)
            record.result_key = self._result_key(job_id) if self.redis_client is not None else None
            record.status = ScrapeJobStatus.SUCCEEDED
            record.error = None
        except asyncio.CancelledError:
            record.status = ScrapeJobStatus.QUEUED
            record.error = "job interrupted before completion"
            record.result = None
            record.updated_at = time.time()
            await self._save(record)
            raise
        except Exception as exc:
            record.status = ScrapeJobStatus.FAILED
            record.error = str(exc)
            record.result = None
            record.result_key = None

        record.updated_at = time.time()
        await self._save(record)

    async def _save(self, record: ScrapeJobRecord) -> None:
        record_to_store = record.model_copy(deep=True)
        key = self._job_key(record.job_id)
        if self.redis_client is not None:
            if record.result is not None:
                result_key = self._result_key(record.job_id)
                await self.redis_client.set(
                    result_key,
                    record.result.model_dump_json(),
                    ex=self.job_ttl_seconds,
                )
                record_to_store.result_key = result_key
                record_to_store.result = None
            elif record_to_store.result_key is not None:
                await self.redis_client.delete(record_to_store.result_key)
                record_to_store.result_key = None
            await self.redis_client.set(key, record_to_store.model_dump_json(), ex=self.job_ttl_seconds)
            return
        self._memory_jobs[key] = record_to_store.model_dump_json()

    async def _load(self, job_id: str) -> str | None:
        key = self._job_key(job_id)
        if self.redis_client is not None:
            return await self.redis_client.get(key)
        return self._memory_jobs.get(key)

    async def _load_result(self, result_key: str | None) -> ScrapeResult | None:
        if result_key is None:
            return None
        if self.redis_client is not None:
            payload = await self.redis_client.get(result_key)
            if payload is None:
                return None
            return ScrapeResult.model_validate_json(payload)
        payload = self._memory_jobs.get(result_key)
        if payload is None:
            return None
        return ScrapeResult.model_validate_json(payload)

    def _schedule_job(self, job_id: str, request: ScrapeRequest) -> None:
        task = asyncio.create_task(self._run_job(job_id, request))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    async def _iter_job_keys(self):
        if self.redis_client is None:
            return
        scan_iter = getattr(self.redis_client, "scan_iter", None)
        if callable(scan_iter):
            async for key in scan_iter(match="scraper:job:scrape-*"):
                if ":result:" in key:
                    continue
                yield key
            return
        for key in await self.redis_client.keys("scraper:job:scrape-*"):
            if ":result:" not in key:
                yield key

    @staticmethod
    def _should_reuse_completed(existing: ScrapeJobRecord, request: ScrapeRequest) -> bool:
        if request.intent == ScrapeIntent.HISTORICAL_BACKFILL:
            return True
        if request.freshness_s is None:
            return False
        result = existing.result
        if result is None or result.fetched_at is None:
            return False
        return (time.time() - result.fetched_at) <= request.freshness_s

    @staticmethod
    def build_job_id(request: ScrapeRequest) -> str:
        payload = json.dumps(
            request.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"scrape-{request.provider.value}-{request.dataset.value}-{digest}"

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"scraper:job:{job_id}"

    @staticmethod
    def _result_key(job_id: str) -> str:
        return f"scraper:job:result:{job_id}"
