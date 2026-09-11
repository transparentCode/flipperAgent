"""ARQ worker for periodic CoinGlass liquidation heatmap fetching."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from apps.scraper_app.providers.coinglass.config import config_manager

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

DEFAULT_HEATMAP_TARGETS = [
    {
        "coin": "SOL",
        "market_type": "pair",
        "exchange": "Binance",
        "symbol": "SOLUSDT",
        "short_name": "SOLUSDT",
    }
]

HEATMAP_TARGETS: list[dict[str, str]] = config_manager.get(
    "coinglass.heatmaps", DEFAULT_HEATMAP_TARGETS
)


async def fetch_coinglass_heatmaps(ctx: dict[str, Any]) -> None:
    """Fetch CoinGlass heatmap payloads and publish them to Valkey."""
    redis_client = ctx.get("redis")
    interceptor = ctx.get("coinglass_interceptor")

    if interceptor is None:
        logger.warning("CoinGlass interceptor not available in worker context")
        return

    ttl_seconds = int(config_manager.get("coinglass.staleness_ttl_seconds", 1800))
    try:
        captured = await interceptor.fetch_heatmaps(HEATMAP_TARGETS)
    except Exception as exc:
        logger.error(f"Failed to fetch CoinGlass heatmaps: {exc}", exc_info=True)
        return

    for target in HEATMAP_TARGETS:
        key = interceptor.target_key(target)
        envelope = captured.get(key)
        if envelope is None:
            logger.warning(f"No CoinGlass envelope returned for {key}")
            continue

        fetched_at = time.time()
        if redis_client:
            hash_key = (
                f"coinglass:latest:liquidation_heatmap:"
                f"{target.get('exchange', 'Binance')}:{target.get('short_name', target['coin'])}"
            )
            await redis_client.hset(
                hash_key,
                mapping={
                    "coin": envelope["coin"],
                    "exchange": envelope["exchange"],
                    "symbol": envelope["symbol"],
                    "market_type": envelope["market_type"],
                    "shape": envelope["shape"],
                    "response_url": envelope["response_url"],
                    "page_url": envelope["page_url"],
                    "captured_at_ms": str(envelope["captured_at_ms"]),
                    "payload_json": json.dumps(envelope["payload"], separators=(",", ":")),
                    "fetched_at": str(fetched_at),
                },
            )
            if ttl_seconds > 0:
                await redis_client.expire(hash_key, ttl_seconds)
            logger.info(f"Published CoinGlass heatmap to Valkey: {hash_key}")


async def startup(ctx: dict[str, Any]) -> None:
    """Initialize CoinGlass worker connections."""
    from apps.scraper_app.providers.coinglass.interceptor import CoinGlassHeatmapInterceptor

    logger.info("Initializing CoinGlass scraper worker...")
    ctx["coinglass_interceptor"] = CoinGlassHeatmapInterceptor()

    try:
        from libs.common.connections import create_valkey_client

        ctx["redis"] = await create_valkey_client(config_manager)
    except Exception as exc:
        logger.error(f"Failed to create Valkey client: {exc}")
        ctx["redis"] = None


async def shutdown(ctx: dict[str, Any]) -> None:
    """Cleanup worker resources."""
    interceptor = ctx.get("coinglass_interceptor")
    if interceptor is not None:
        await interceptor.close()
    redis = ctx.get("redis")
    if redis:
        await redis.aclose()
    logger.info("CoinGlass scraper worker shut down.")


class WorkerSettings:
    """ARQ worker settings for CoinGlass heatmap fetching."""

    functions = [fetch_coinglass_heatmaps]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = "arq:coinglass-scraper"

    cron_jobs = [
        cron(
            fetch_coinglass_heatmaps,
            minute=set(config_manager.get("coinglass.cron_minutes", [0, 30])),
            second=config_manager.get("coinglass.cron_second", 45),
            run_at_startup=config_manager.get("coinglass.run_at_startup", False),
        )
    ]

    redis_settings = RedisSettings.from_dsn(
        os.getenv("VALKEY_URI")
        or os.getenv("REDIS_URI")
        or config_manager.get("valkey.uri", "redis://localhost:6379/0")
    )

    max_jobs = config_manager.get("coinglass.max_concurrent_jobs", 1)
    job_timeout = config_manager.get("coinglass.job_timeout_seconds", 120)
