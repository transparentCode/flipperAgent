"""ARQ worker for periodic TradingView index data fetching."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_TRADINGVIEW
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

config_manager = ConfigManager()
config_manager.register_file(CONFIG_FILE_TRADINGVIEW)

# Indices to fetch — driven by tradingview.indices config
_default_indices = [
    "CRYPTOCAP:TOTAL2",
    "CRYPTOCAP:TOTAL3",
    "CRYPTOCAP:BTC.D",
]
TV_INDICES: list[str] = config_manager.get("tradingview.indices", _default_indices)

# Map TV symbols to short names for Valkey keys (derived: "EXCHANGE:NAME" → "NAME")
INDEX_KEY_MAP: dict[str, str] = {sym: sym.split(":")[-1] for sym in TV_INDICES}


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
            # limit param is intentionally omitted — TV returns ~300 bars naturally,
            # giving us passive gap-fill coverage of ~6d (30m) / ~12d (1h) on every fetch.
            df = await interceptor.get_historical_ohlcv(tv_symbol, timeframe)

            if df.empty:
                logger.warning(f"No data returned for {tv_symbol}")
                continue

            # Latest closed candle — published to Valkey for real-time consumption
            latest = df.iloc[-1]
            fetched_at = time.time()

            # 1. Publish latest bar to Valkey hash
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

            # 2. Upsert ALL returned bars into TimescaleDB.
            # On CONFLICT is idempotent — already-present bars are updated in place.
            # This passively heals any gaps from missed fetch cycles at no extra cost.
            if db_pool:
                try:
                    async with db_pool.acquire() as conn:
                        rows = [
                            (
                                short_name,
                                timeframe,
                                int(row["timestamp"]),
                                float(row["open"]),
                                float(row["high"]),
                                float(row["low"]),
                                float(row["close"]),
                                float(row.get("volume", 0.0)),
                            )
                            for _, row in df.iterrows()
                        ]
                        await conn.executemany(
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
                            rows,
                        )
                        logger.info(f"Upserted {len(rows)} bars for {short_name}")
                except Exception as db_err:
                    logger.error(f"DB upsert failed for {short_name}: {db_err}")

        except Exception as e:
            logger.error(f"Failed to fetch {tv_symbol}: {e}", exc_info=True)
            continue

        # Small delay between index fetches to avoid detection
        await asyncio.sleep(config_manager.get("tradingview.fetch_delay_seconds", 2))


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

    # Dedicated queue isolates tv-scraper jobs from the ingestion worker's default queue
    queue_name = "arq:tv-scraper"

    cron_jobs = [
        cron(
            fetch_tv_indices,
            # set of minutes fires at both :00:30 (1h/4h closes) and :30:30 (30m close)
            minute=set(config_manager.get("tradingview.cron_minutes", [0, 30])),
            second=config_manager.get("tradingview.cron_second", 30),
            run_at_startup=config_manager.get("tradingview.run_at_startup", False),
        ),
    ]

    # Respect VALKEY_URI / REDIS_URI env vars (Docker override) before falling back to config
    redis_settings = RedisSettings.from_dsn(
        os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
        or config_manager.get("valkey.uri", "redis://localhost:6379/0")
    )

    max_jobs = config_manager.get("tradingview.max_concurrent_jobs", 1)
    job_timeout = config_manager.get("tradingview.job_timeout_seconds", 120)
