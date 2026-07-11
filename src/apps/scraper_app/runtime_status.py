from __future__ import annotations

import inspect
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

_SCRAPER_RUNTIME_STATUS_KEY_PREFIX = "scraper:runtime_status"


class ScraperRuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    worker_name: str
    provider: str
    job_name: str
    status: Literal["running", "succeeded", "failed"]
    updated_at: float
    cadence_seconds: float | None = None
    last_started_at: float | None = None
    last_finished_at: float | None = None
    last_success_at: float | None = None
    last_duration_seconds: float | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    source: str = "scraper_app"

    @field_validator("worker_name", "provider", "job_name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> str:
        return str(value).strip().lower()


def scraper_runtime_status_key(worker_name: str, job_name: str) -> str:
    normalized_worker = str(worker_name).strip().lower()
    normalized_job = str(job_name).strip().lower()
    return f"{_SCRAPER_RUNTIME_STATUS_KEY_PREFIX}:{normalized_worker}:{normalized_job}"


class ScraperRuntimeStatusStore:
    def __init__(self, redis_client: Any) -> None:
        self.redis_client = redis_client

    async def write_status(self, status: ScraperRuntimeStatus) -> None:
        await self.redis_client.set(
            scraper_runtime_status_key(status.worker_name, status.job_name),
            status.model_dump_json(),
        )

    async def read_status(
        self,
        worker_name: str,
        job_name: str,
    ) -> ScraperRuntimeStatus | None:
        getter = getattr(self.redis_client, "get", None)
        if getter is None:
            return None
        raw = getter(scraper_runtime_status_key(worker_name, job_name))
        if inspect.isawaitable(raw):
            raw = await raw
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            return None
        return ScraperRuntimeStatus.model_validate_json(raw)


__all__ = [
    "ScraperRuntimeStatus",
    "ScraperRuntimeStatusStore",
    "scraper_runtime_status_key",
]
