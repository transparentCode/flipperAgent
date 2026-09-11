"""Internal FastAPI application for scraper consumers."""

from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from apps.scraper_app.api.routes import router
from apps.scraper_app.service import ScraperFetchService, ScraperJobService
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_mgr = ConfigManager()
    redis_client: Any | None = getattr(app.state, "redis_client", None)
    owns_redis = False

    if redis_client is None:
        try:
            redis_client = await create_valkey_client(config_mgr)
            owns_redis = True
        except Exception as exc:
            logger.warning(f"Scraper service starting without Valkey client: {exc}")
            redis_client = None

    fetch_service = getattr(app.state, "fetch_service", None)
    if fetch_service is None:
        fetch_service = ScraperFetchService(redis_client=redis_client)

    job_service = getattr(app.state, "job_service", None)
    if job_service is None:
        job_service = ScraperJobService(
            fetch_service=fetch_service,
            redis_client=redis_client,
            job_ttl_seconds=int(config_mgr.get("scraper_service.job_ttl_seconds", 3600)),
        )

    app.state.redis_client = redis_client
    app.state.fetch_service = fetch_service
    app.state.job_service = job_service
    app.state._owns_redis = owns_redis

    recovered_jobs = await job_service.recover_pending_jobs()
    if recovered_jobs:
        logger.info(f"Recovered {recovered_jobs} pending scraper jobs from Valkey.")

    logger.info("Scraper service started.")
    try:
        yield
    finally:
        await job_service.shutdown()
        if owns_redis and redis_client is not None:
            await redis_client.aclose()
        logger.info("Scraper service shutting down.")


def create_app(
    *,
    fetch_service: ScraperFetchService | None = None,
    job_service: ScraperJobService | None = None,
    redis_client: Any | None = None,
) -> FastAPI:
    app = FastAPI(
        title="flipperAgent Scraper Service",
        description="Internal browser-backed scraper API for TradingView and CoinGlass.",
        version="1.0.0",
        lifespan=lifespan,
    )
    if fetch_service is not None:
        app.state.fetch_service = fetch_service
    if job_service is not None:
        app.state.job_service = job_service
    if redis_client is not None:
        app.state.redis_client = redis_client
    app.include_router(router)
    return app


app = create_app()
