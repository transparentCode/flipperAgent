"""CoinGlass scraper provider."""

from apps.scraper_app.providers.coinglass.config import config_manager
from apps.scraper_app.providers.coinglass.interceptor import CoinGlassHeatmapInterceptor
from apps.scraper_app.providers.coinglass.worker import (
    DEFAULT_HEATMAP_TARGETS,
    HEATMAP_TARGETS,
    WorkerSettings,
    fetch_coinglass_heatmaps,
    shutdown,
    startup,
)

__all__ = [
    "CoinGlassHeatmapInterceptor",
    "DEFAULT_HEATMAP_TARGETS",
    "HEATMAP_TARGETS",
    "WorkerSettings",
    "config_manager",
    "fetch_coinglass_heatmaps",
    "shutdown",
    "startup",
]
