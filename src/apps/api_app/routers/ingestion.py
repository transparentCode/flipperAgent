"""Central API scraper compatibility bridge.

Legacy ingestion control and observability are owned by the retired package's
former runtime and are no longer exposed from the central API.  Ingestion
owns its control plane at its own service boundary; these routes remain only
for clients of the existing scraper bridge.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api_app.clients import ScraperServiceClient, ScraperServiceClientError
from apps.scraper_app.core.models import ScrapeJobRecord, ScrapeRequest, ScrapeResult
from libs.common.config import ConfigManager

router = APIRouter(prefix="/ingestion", tags=["ingestion"])
config_manager = ConfigManager()


@router.post(
    "/scraper/fetch",
    response_model=ScrapeResult,
    summary="Request on-demand scraper-backed provider data synchronously",
)
async def ingestion_scraper_fetch(body: ScrapeRequest) -> ScrapeResult:
    """Bridge an on-demand provider pull through scraper_app."""
    try:
        return await _scraper_client().fetch_sync(body)
    except ScraperServiceClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "/scraper/jobs",
    response_model=ScrapeJobRecord,
    summary="Queue an async on-demand scraper request",
)
async def ingestion_scraper_create_job(body: ScrapeRequest) -> ScrapeJobRecord:
    try:
        return await _scraper_client().create_job(body)
    except ScraperServiceClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/scraper/jobs/{job_id}",
    response_model=ScrapeJobRecord,
    summary="Get async on-demand scraper job status",
)
async def ingestion_scraper_get_job(
    job_id: str,
    include_result: bool = True,
) -> ScrapeJobRecord:
    try:
        return await _scraper_client().get_job(job_id, include_result=include_result)
    except ScraperServiceClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _scraper_client() -> ScraperServiceClient:
    return ScraperServiceClient(config_manager=config_manager)
