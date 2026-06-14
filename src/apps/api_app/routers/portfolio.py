"""Portfolio API router shim to the modular portfolio_app package."""

from typing import Any

from apps.portfolio_app.api.routes import (
    exposure_by_asset,
    health,
    open_positions,
    portfolio_equity_curve,
    portfolio_latest_equity,
    router,
)
from apps.portfolio_app.observability import PortfolioObservabilityService
from libs.common.db.pool_manager import DBPoolManager


async def portfolio_summary() -> dict[str, Any]:
    service = PortfolioObservabilityService(DBPoolManager.get_reader_pool())
    return await service.summary()

__all__ = [
    "router",
    "health",
    "portfolio_summary",
    "portfolio_latest_equity",
    "portfolio_equity_curve",
    "open_positions",
    "exposure_by_asset",
]
