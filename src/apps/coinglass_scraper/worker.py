"""Backward-compatible CoinGlass worker shim."""

from apps.scraper_app.providers.coinglass import worker as _worker

DEFAULT_HEATMAP_TARGETS = _worker.DEFAULT_HEATMAP_TARGETS
HEATMAP_TARGETS = _worker.HEATMAP_TARGETS
config_manager = _worker.config_manager


async def fetch_coinglass_heatmaps(ctx):
    _worker.HEATMAP_TARGETS = HEATMAP_TARGETS
    return await _worker.fetch_coinglass_heatmaps(ctx)


async def startup(ctx):
    return await _worker.startup(ctx)


async def shutdown(ctx):
    return await _worker.shutdown(ctx)


class WorkerSettings(_worker.WorkerSettings):
    functions = [fetch_coinglass_heatmaps]


__all__ = [
    "DEFAULT_HEATMAP_TARGETS",
    "HEATMAP_TARGETS",
    "WorkerSettings",
    "config_manager",
    "fetch_coinglass_heatmaps",
    "shutdown",
    "startup",
]
