"""Backward-compatible TradingView worker shim."""

from apps.scraper_app.providers.tradingview import worker as _worker

TV_INDICES = _worker.TV_INDICES
INDEX_KEY_MAP = _worker.INDEX_KEY_MAP
config_manager = _worker.config_manager


async def fetch_tv_indices(ctx):
    _worker.TV_INDICES = TV_INDICES
    _worker.INDEX_KEY_MAP = INDEX_KEY_MAP
    return await _worker.fetch_tv_indices(ctx)


async def fetch_tv_derivatives(ctx):
    return await _worker.fetch_tv_derivatives(ctx)


async def startup(ctx):
    return await _worker.startup(ctx)


async def shutdown(ctx):
    return await _worker.shutdown(ctx)


class WorkerSettings(_worker.WorkerSettings):
    functions = [fetch_tv_indices, fetch_tv_derivatives]


__all__ = [
    "INDEX_KEY_MAP",
    "TV_INDICES",
    "WorkerSettings",
    "config_manager",
    "fetch_tv_derivatives",
    "fetch_tv_indices",
    "shutdown",
    "startup",
]
