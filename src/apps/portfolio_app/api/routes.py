from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from apps.portfolio_app.api.models import (
    PortfolioAttributionResponse,
    PortfolioBenchmarkRequest,
    PortfolioBenchmarkResponse,
    PortfolioExposureGroupResponse,
    PortfolioPerformanceResponse,
    PortfolioRebalanceResponse,
    PortfolioSleevesResponse,
    PortfolioTradesResponse,
)
from apps.portfolio_app.observability import PortfolioObservabilityService
from apps.portfolio_app.policy import PortfolioPolicyService

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _service(request: Request) -> PortfolioObservabilityService:
    return request.app.state.observability_service


@router.get("/health", summary="Portfolio observability health")
async def health(request: Request) -> dict[str, Any]:
    return await _service(request).health()


@router.get("/summary", summary="Portfolio equity and recent trade stats")
async def portfolio_summary(request: Request) -> dict[str, Any]:
    return await _service(request).summary()


@router.get("/equity/latest", summary="Latest portfolio equity snapshot")
async def portfolio_latest_equity(request: Request) -> dict[str, Any]:
    result = await _service(request).latest_equity()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/equity/curve", summary="Portfolio equity curve history")
async def portfolio_equity_curve(
    request: Request,
    start_timestamp: float | None = Query(default=None),
    end_timestamp: float | None = Query(default=None),
    max_points: int = Query(default=1000, ge=1, le=100000),
) -> dict[str, Any]:
    result = await _service(request).equity_curve(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        max_points=max_points,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/positions/open", summary="Current open positions from portfolio view")
async def open_positions(request: Request) -> dict[str, Any]:
    result = await _service(request).open_positions()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/exposure/by-asset", summary="Current notional exposure grouped by asset")
async def exposure_by_asset(request: Request) -> dict[str, Any]:
    result = await _service(request).exposure_by_asset()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return result


@router.get("/exposure/by-model", response_model=PortfolioExposureGroupResponse, summary="Current notional exposure grouped by source model")
async def exposure_by_model(request: Request) -> PortfolioExposureGroupResponse:
    result = await _service(request).exposure_by_model()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioExposureGroupResponse(**result)


@router.get("/exposure/by-timeframe", response_model=PortfolioExposureGroupResponse, summary="Current notional exposure grouped by source timeframe")
async def exposure_by_timeframe(request: Request) -> PortfolioExposureGroupResponse:
    result = await _service(request).exposure_by_timeframe()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioExposureGroupResponse(**result)


@router.get("/sleeves", response_model=PortfolioSleevesResponse, summary="Portfolio sleeve summary across assets, models, and timeframes")
async def portfolio_sleeves(request: Request) -> PortfolioSleevesResponse:
    result = await _service(request).sleeves_summary()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioSleevesResponse(**result)


@router.get(
    "/rebalance/recommendation",
    response_model=PortfolioRebalanceResponse,
    summary="Recommendation-only portfolio rebalance targets from current sleeve concentration",
)
async def portfolio_rebalance_recommendation(request: Request) -> PortfolioRebalanceResponse:
    result = await PortfolioPolicyService(_service(request)).recommend_rebalance()
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioRebalanceResponse(**result)


@router.get("/trades", response_model=PortfolioTradesResponse, summary="Closed trades with optional filters")
async def portfolio_trades(
    request: Request,
    asset: str | None = Query(default=None),
    model: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    start_timestamp: float | None = Query(default=None),
    end_timestamp: float | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
) -> PortfolioTradesResponse:
    result = await _service(request).closed_trades(
        asset=asset,
        model=model,
        timeframe=timeframe,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        limit=limit,
        offset=offset,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioTradesResponse(**result)


@router.get("/performance", response_model=PortfolioPerformanceResponse, summary="Aggregate portfolio performance summary")
async def portfolio_performance(
    request: Request,
    asset: str | None = Query(default=None),
    model: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    start_timestamp: float | None = Query(default=None),
    end_timestamp: float | None = Query(default=None),
    resample_interval_seconds: int = Query(default=3600, ge=1),
    risk_free_rate: float = Query(default=0.0),
) -> PortfolioPerformanceResponse:
    result = await _service(request).performance_summary(
        asset=asset,
        model=model,
        timeframe=timeframe,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        resample_interval_seconds=resample_interval_seconds,
        risk_free_rate=risk_free_rate,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioPerformanceResponse(**result)


@router.get("/attribution", response_model=PortfolioAttributionResponse, summary="PnL attribution by asset, model, or timeframe")
async def portfolio_attribution(
    request: Request,
    group_by: str = Query(..., pattern="^(asset|model|timeframe)$"),
    asset: str | None = Query(default=None),
    model: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    start_timestamp: float | None = Query(default=None),
    end_timestamp: float | None = Query(default=None),
) -> PortfolioAttributionResponse:
    result = await _service(request).pnl_attribution(
        group_by=group_by,
        asset=asset,
        model=model,
        timeframe=timeframe,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioAttributionResponse(**result)


@router.post("/benchmark", response_model=PortfolioBenchmarkResponse, summary="Compare portfolio returns vs a supplied benchmark price series")
async def portfolio_benchmark(
    request: Request,
    body: PortfolioBenchmarkRequest,
) -> PortfolioBenchmarkResponse:
    result = await _service(request).benchmark_comparison(
        benchmark_name=body.benchmark_name,
        benchmark_prices=[(point.timestamp, point.price) for point in body.benchmark_prices],
        start_timestamp=body.start_timestamp,
        end_timestamp=body.end_timestamp,
        interval_seconds=body.interval_seconds,
        risk_free_rate=body.risk_free_rate,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result["error"])
    return PortfolioBenchmarkResponse(**result)
