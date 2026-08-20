"""flipperAgent API app — FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api_app.routers import config as config_router
from apps.api_app.routers import execution as execution_router
from apps.api_app.routers import health as health_router
from apps.api_app.routers import ingestion as ingestion_router
from apps.api_app.routers import portfolio as portfolio_router
from apps.api_app.routers import risk as risk_router
from libs.common.config import ConfigManager
from libs.common.connections import init_db_pools
from libs.common.constants import (
    CONFIG_FILE_EXECUTION,
    CONFIG_FILE_FEATURES,
    CONFIG_FILE_MODELS,
    CONFIG_FILE_OPTIMIZATION,
    CONFIG_FILE_PORTFOLIO,
    CONFIG_FILE_RISK,
    CONFIG_FILE_SELECTION,
    CONFIG_FILE_TRADINGVIEW,
)
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

_ALL_CONFIG_FILES = [
    CONFIG_FILE_FEATURES,
    CONFIG_FILE_MODELS,
    CONFIG_FILE_RISK,
    CONFIG_FILE_EXECUTION,
    CONFIG_FILE_PORTFOLIO,
    CONFIG_FILE_OPTIMIZATION,
    CONFIG_FILE_SELECTION,
    CONFIG_FILE_TRADINGVIEW,
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_mgr = ConfigManager()
    for cfg_file in _ALL_CONFIG_FILES:
        config_mgr.register_file(cfg_file)
    await init_db_pools(config_mgr)
    logger.info("API server started — all config files registered.")
    yield
    await DBPoolManager.close_pools()
    config_mgr.shutdown()
    logger.info("API server shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="flipperAgent API",
        description="Config management and operational API for the flipperAgent quant stack.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(health_router.router)
    app.include_router(config_router.router)
    app.include_router(ingestion_router.router)
    app.include_router(risk_router.router)
    app.include_router(execution_router.router)
    app.include_router(portfolio_router.router)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass

    return app


app = create_app()
