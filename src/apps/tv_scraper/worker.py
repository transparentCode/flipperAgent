"""ARQ worker for periodic TradingView index data fetching."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from arq import cron

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

config_manager = ConfigManager()

# Indices to fetch
TV_INDICES = [
    "CRYPTOCAP:TOTAL2",
    "CRYPTOCAP:TOTAL3",
    "CRYPTOCAP:BTC.D",
]

# Map TV symbols to short names for Valkey keys
INDEX_KEY_MAP = {
    "CRYPTOCAP:TOTAL2": "TOTAL2",
    "CRYPTOCAP:TOTAL3": "TOTAL3",
    "CRYPTOCAP:BTC.D": "BTC.D",
}


async def fetch_tv_indices(ctx: dict[str, Any]) -> None:
    """Fetch latest closed candles for all configured TV indices.

    Single browser session fetches all indices sequentially, then publishes
    each to Valkey hash and upserts into TimescaleDB.
    """
    redis_client = ctx.get("redis")
    db_pool = ctx.get("db_pool")
    interceptor = ctx.get("tv_interceptor")

    if interceptor is None:
        logger.warning("TV interceptor not available in worker context, skipping fetch")
        return

    timeframe = config_manager.get("tradingview.timeframe", "1h")

    for tv_symbol in TV_INDICES:
        short_name = INDEX_KEY_MAP.get(tv_symbol, tv_symbol)
        try:
            df = await interceptor.get_historical_ohlcv(tv_symbol, timeframe, limit=1)

            if df.empty:
                logger.warning(f"No data returned for {tv_symbol}")
                continue

            # Get the latest (last) closed candle
            latest = df.iloc[-1]

            fetched_at = time.time()

            # 1. Publish to Valkey hash for real-time consumption
            if redis_client:
                hash_key = f"index:latest:{short_name}"
                await redis_client.hset(
                    hash_key,
                    mapping={
                        "symbol": short_name,
                        "timestamp": str(latest["timestamp"]),
                        "open": str(latest["open"]),
                        "high": str(latest["high"]),
                        "low": str(latest["low"]),
                        "close": str(latest["close"]),
                        "volume": str(latest.get("volume", 0.0)),
                        "fetched_at": str(fetched_at),
                    },
                )
                logger.info(f"Published {short_name} to Valkey hash: close={latest['close']}")

            # 2. Upsert into TimescaleDB for historical record
            if db_pool:
                try:
                    async with db_pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO tv_index_ohlcv (symbol, timeframe, timestamp, open, high, low, close, volume)
                            VALUES ($1, $2, to_timestamp($3 / 1000.0), $4, $5, $6, $7, $8)
                            ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
                                open = EXCLUDED.open,
                                high = EXCLUDED.high,
                                low = EXCLUDED.low,
                                close = EXCLUDED.close,
                                volume = EXCLUDED.volume,
                                fetched_at = NOW()
                            """,
                            short_name,
                            timeframe,
                            int(latest["timestamp"]),
                            float(latest["open"]),
                            float(latest["high"]),
                            float(latest["low"]),
                            float(latest["close"]),
                            float(latest.get("volume", 0.0)),
                        )
                except Exception as db_err:
                    logger.error(f"DB upsert failed for {short_name}: {db_err}")

        except Exception as e:
            logger.error(f"Failed to fetch {tv_symbol}: {e}", exc_info=True)
            continue

        # Small delay between index fetches to avoid detection
        await asyncio.sleep(2)


async def startup(ctx: dict[str, Any]) -> None:
    """Worker startup — initialize TV interceptor and connections."""
    from apps.tv_scraper.interceptor import TradingViewInterceptor

    logger.info("Initializing TV scraper worker...")

    ctx["tv_interceptor"] = TradingViewInterceptor()

    # Redis connection
    try:
        from libs.common.connections import create_valkey_client

        ctx["redis"] = await create_valkey_client(config_manager)
    except Exception as e:
        logger.error(f"Failed to create Valkey client: {e}")
        ctx["redis"] = None

    # DB connection (optional — may not have asyncpg in TV container)
    try:
        from libs.common.connections import init_db_pools
        from libs.common.db.pool_manager import DBPoolManager

        await init_db_pools(config_manager)
        ctx["db_pool"] = DBPoolManager.get_writer_pool()
    except Exception as e:
        logger.warning(f"DB pool not available: {e}")
        ctx["db_pool"] = None


async def shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown — cleanup connections."""
    redis = ctx.get("redis")
    if redis:
        await redis.aclose()
    logger.info("TV scraper worker shut down.")


class WorkerSettings:
    """ARQ worker settings for TV index fetching."""

    functions = [fetch_tv_indices]
    on_startup = startup
    on_shutdown = shutdown

    # Run at :00:30 of every hour (30s after candle close)
    cron_jobs = [
        cron(fetch_tv_indices, minute=0, second=30),
    ]

    # Valkey connection for ARQ queue
    redis_settings = None  # Will be configured from env at runtime

    max_jobs = 1
    job_timeout = 120  # 2 minutes should be plenty for 3 index fetches
