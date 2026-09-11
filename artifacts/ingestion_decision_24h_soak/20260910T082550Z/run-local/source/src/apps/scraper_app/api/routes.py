"""HTTP routes for the internal scraper service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from apps.scraper_app.core.models import (
    HealthResponse,
    ScrapeJobRecord,
    ScrapeRequest,
    ScrapeResult,
    TradingViewSeriesField,
)
from apps.scraper_app.service import ScraperFetchService, ScraperJobService
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

router = APIRouter(tags=["scraper"])
logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)


def _fetch_service(request: Request) -> ScraperFetchService:
    return request.app.state.fetch_service


def _job_service(request: Request) -> ScraperJobService:
    return request.app.state.job_service


@router.get("/health", response_model=HealthResponse, summary="Scraper service health")
async def health(request: Request) -> HealthResponse:
    redis_client = getattr(request.app.state, "redis_client", None)
    valkey_available = False
    if redis_client is not None:
        try:
            valkey_available = bool(await redis_client.ping())
        except Exception:
            valkey_available = False
    return HealthResponse(status="ok", valkey_available=valkey_available)


@router.get(
    "/latest/tradingview/ohlcv",
    response_model=ScrapeResult,
    summary="Get latest cached TradingView OHLCV snapshot",
)
async def latest_tradingview_ohlcv(
    request: Request,
    symbol: str = Query(..., description="TradingView symbol, e.g. CRYPTOCAP:TOTAL3ES"),
    timeframe: str = Query("1h"),
    max_age_s: int | None = Query(default=None, ge=0),
) -> ScrapeResult:
    service = _fetch_service(request)
    try:
        result = await service.get_latest_tradingview_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            max_age_s=max_age_s,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="No fresh TradingView OHLCV cache entry found.")
    return result


@router.get(
    "/latest/tradingview/series",
    response_model=ScrapeResult,
    summary="Get latest cached TradingView derivative series snapshot",
)
async def latest_tradingview_series(
    request: Request,
    asset: str = Query(..., description="Asset key used in derivative cache, e.g. SOLUSDT"),
    field: TradingViewSeriesField = Query(...),
    timeframe: str = Query("1h"),
    max_age_s: int | None = Query(default=None, ge=0),
) -> ScrapeResult:
    service = _fetch_service(request)
    try:
        result = await service.get_latest_tradingview_series(
            asset=asset,
            field=field,
            timeframe=timeframe,
            max_age_s=max_age_s,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="No fresh TradingView series cache entry found.")
    return result


@router.get(
    "/latest/coinglass/heatmap",
    response_model=ScrapeResult,
    summary="Get latest cached CoinGlass heatmap snapshot",
)
async def latest_coinglass_heatmap(
    request: Request,
    exchange: str = Query("Binance"),
    short_name: str = Query(..., description="Configured short_name, e.g. SOLUSDT"),
    max_age_s: int | None = Query(default=None, ge=0),
) -> ScrapeResult:
    service = _fetch_service(request)
    try:
        result = await service.get_latest_coinglass_heatmap(
            exchange=exchange,
            short_name=short_name,
            max_age_s=max_age_s,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="No fresh CoinGlass cache entry found.")
    return result


@router.post(
    "/fetch/sync",
    response_model=ScrapeResult,
    summary="Fetch provider data immediately",
)
async def fetch_sync(request: Request, body: ScrapeRequest) -> ScrapeResult:
    service = _fetch_service(request)
    try:
        return await service.fetch(body)
    except Exception as exc:
        logger.warning("Synchronous scraper fetch failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Provider fetch failed. Check scraper-service logs for details.",
        ) from exc


@router.post(
    "/jobs",
    response_model=ScrapeJobRecord,
    summary="Create an async scraper fetch job",
)
async def create_job(request: Request, body: ScrapeRequest) -> ScrapeJobRecord:
    service = _job_service(request)
    return await service.submit(body)


@router.get(
    "/jobs/{job_id}",
    response_model=ScrapeJobRecord,
    summary="Get async scraper job status",
)
async def get_job(
    request: Request,
    job_id: str,
    include_result: bool = Query(default=True),
) -> ScrapeJobRecord:
    service = _job_service(request)
    record = await service.get(job_id, include_result=include_result)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown scraper job '{job_id}'.")
    return record
