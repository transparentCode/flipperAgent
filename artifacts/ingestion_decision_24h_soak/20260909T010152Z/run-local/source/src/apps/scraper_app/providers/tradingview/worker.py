"""ARQ worker for periodic TradingView index data fetching."""

from __future__ import annotations

import os
import time
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from apps.scraper_app.providers.tradingview.config import config_manager
from apps.scraper_app.providers.tradingview.storage import (
    FundingRateRecord,
    OIRecord,
    TradingViewTimescaleWriter,
)
from apps.scraper_app.runtime_status import (
    ScraperRuntimeStatus,
    ScraperRuntimeStatusStore,
)
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

# Indices to fetch — driven by tradingview.indices config
_default_indices = [
    "CRYPTOCAP:TOTAL2",
    "CRYPTOCAP:TOTAL3",
    "CRYPTOCAP:TOTAL3ES",
    "CRYPTOCAP:BTC.D",
]
TV_INDICES: list[str] = config_manager.get("tradingview.indices", _default_indices)

# Map TV symbols to short names for Valkey keys (derived: "EXCHANGE:NAME" → "NAME")
INDEX_KEY_MAP: dict[str, str] = {sym: sym.split(":")[-1] for sym in TV_INDICES}
TV_WORKER_NAME = "tradingview"
TV_INDICES_JOB_NAME = "fetch_tv_indices"
TV_DERIVATIVES_JOB_NAME = "fetch_tv_derivatives"


def _job_cadence_seconds() -> float:
    minutes = sorted(
        {
            int(minute)
            for minute in config_manager.get("tradingview.cron_minutes", [0, 30])
        }
    )
    if not minutes:
        return 1800.0
    if len(minutes) == 1:
        return 3600.0
    deltas = [
        (minutes[(index + 1) % len(minutes)] - minutes[index]) % 60
        for index in range(len(minutes))
    ]
    positive_deltas = [delta for delta in deltas if delta > 0]
    if not positive_deltas:
        return 1800.0
    return float(min(positive_deltas) * 60)


def _summarize_issues(issues: list[str]) -> str:
    if not issues:
        return ""
    sample = ", ".join(issues[:3])
    if len(issues) > 3:
        sample = f"{sample}, +{len(issues) - 3} more"
    return sample


async def _write_runtime_status(
    ctx: dict[str, Any],
    *,
    job_name: str,
    status: str,
    started_at: float,
    error: str | None = None,
) -> None:
    redis_client = ctx.get("redis")
    if redis_client is None:
        return

    store = ScraperRuntimeStatusStore(redis_client)
    previous = await store.read_status(TV_WORKER_NAME, job_name)
    now_ts = time.time()
    status_record = ScraperRuntimeStatus(
        worker_name=TV_WORKER_NAME,
        provider="tradingview",
        job_name=job_name,
        status=status,
        updated_at=now_ts,
        cadence_seconds=_job_cadence_seconds(),
        last_started_at=started_at,
        last_finished_at=(
            now_ts if status in {"succeeded", "failed"} else previous.last_finished_at if previous else None
        ),
        last_success_at=(
            now_ts if status == "succeeded" else previous.last_success_at if previous else None
        ),
        last_duration_seconds=(
            max(now_ts - started_at, 0.0)
            if status in {"succeeded", "failed"}
            else previous.last_duration_seconds if previous else None
        ),
        consecutive_failures=(
            0
            if status == "succeeded"
            else (previous.consecutive_failures if previous else 0) + 1
            if status == "failed"
            else previous.consecutive_failures if previous else 0
        ),
        last_error=error if status == "failed" else None,
    )
    await store.write_status(status_record)


async def fetch_tv_indices(ctx: dict[str, Any]) -> None:
    """Fetch latest closed candles for all configured TV indices.

    Single browser session fetches all indices sequentially, then publishes
    each to Valkey hash and upserts into TimescaleDB.
    """
    redis_client = ctx.get("redis")
    db_pool = ctx.get("db_pool")
    interceptor = ctx.get("tv_interceptor")
    started_at = time.time()
    await _write_runtime_status(
        ctx,
        job_name=TV_INDICES_JOB_NAME,
        status="running",
        started_at=started_at,
    )

    if interceptor is None:
        logger.warning("TV interceptor not available in worker context, skipping fetch")
        await _write_runtime_status(
            ctx,
            job_name=TV_INDICES_JOB_NAME,
            status="failed",
            started_at=started_at,
            error="TV interceptor not available in worker context",
        )
        return

    timeframe = config_manager.get("tradingview.timeframe", "1h")
    ttl_seconds = int(config_manager.get("tradingview.staleness_ttl_seconds", 1800))
    try:
        symbol_frames = await interceptor.get_historical_ohlcv_batch(
            TV_INDICES, timeframe
        )
    except Exception as e:
        logger.error(f"Failed to fetch TradingView batch: {e}", exc_info=True)
        await _write_runtime_status(
            ctx,
            job_name=TV_INDICES_JOB_NAME,
            status="failed",
            started_at=started_at,
            error=f"Failed to fetch TradingView batch: {e}",
        )
        return

    issues: list[str] = []
    for tv_symbol in TV_INDICES:
        short_name = INDEX_KEY_MAP.get(tv_symbol, tv_symbol)
        try:
            df = symbol_frames.get(tv_symbol)
            if df is None:
                logger.warning(f"No batch result returned for {tv_symbol}")
                issues.append(f"no_batch_result:{tv_symbol}")
                continue

            if df.empty:
                logger.warning(f"No data returned for {tv_symbol}")
                issues.append(f"no_data:{tv_symbol}")
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
                        "timeframe": timeframe,
                        "fetched_at": str(fetched_at),
                    },
                )
                if ttl_seconds > 0:
                    await redis_client.expire(hash_key, ttl_seconds)
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
                    issues.append(f"db_upsert_failed:{short_name}")

        except Exception as e:
            logger.error(f"Failed to fetch {tv_symbol}: {e}", exc_info=True)
            issues.append(f"exception:{tv_symbol}")
            continue

    await _write_runtime_status(
        ctx,
        job_name=TV_INDICES_JOB_NAME,
        status="failed" if issues else "succeeded",
        started_at=started_at,
        error=(
            f"TradingView index refresh degraded: {_summarize_issues(issues)}"
            if issues
            else None
        ),
    )


async def fetch_tv_derivatives(ctx: dict[str, Any]) -> None:
    """Fetch latest derivatives data (OI, funding rate) for configured TV symbols.

    Single browser session fetches all derivatives sequentially, then publishes
    each to Valkey hash and upserts into TimescaleDB.
    """
    redis_client = ctx.get("redis")
    db_pool = ctx.get("db_pool")
    interceptor = ctx.get("tv_interceptor")
    started_at = time.time()
    await _write_runtime_status(
        ctx,
        job_name=TV_DERIVATIVES_JOB_NAME,
        status="running",
        started_at=started_at,
    )

    if interceptor is None:
        logger.warning("TV interceptor not available in worker context, skipping derivatives fetch")
        await _write_runtime_status(
            ctx,
            job_name=TV_DERIVATIVES_JOB_NAME,
            status="failed",
            started_at=started_at,
            error="TV interceptor not available in worker context",
        )
        return

    derivatives_config: list[dict[str, Any]] = config_manager.get("tradingview.derivatives", [])
    if not derivatives_config:
        logger.debug("No tradingview.derivatives configured, skipping")
        await _write_runtime_status(
            ctx,
            job_name=TV_DERIVATIVES_JOB_NAME,
            status="succeeded",
            started_at=started_at,
        )
        return

    timeframe = config_manager.get("tradingview.timeframe", "1h")
    ttl_seconds = int(config_manager.get("tradingview.staleness_ttl_seconds", 1800))

    all_symbols = [entry["symbol"] for entry in derivatives_config]
    try:
        symbol_frames = await interceptor.get_historical_series_batch(all_symbols, timeframe)
    except Exception as e:
        logger.error(f"Failed to fetch TradingView derivatives batch: {e}", exc_info=True)
        await _write_runtime_status(
            ctx,
            job_name=TV_DERIVATIVES_JOB_NAME,
            status="failed",
            started_at=started_at,
            error=f"Failed to fetch TradingView derivatives batch: {e}",
        )
        return

    issues: list[str] = []
    for entry in derivatives_config:
        tv_symbol = entry["symbol"]
        short_name = entry.get("short_name", tv_symbol)
        data_type = entry.get("data_type", "")
        asset = entry.get("asset", "")

        try:
            df = symbol_frames.get(tv_symbol)
            if df is None or df.empty:
                logger.warning(f"No derivatives data returned for {tv_symbol}")
                issues.append(f"no_data:{tv_symbol}")
                continue

            latest = df.iloc[-1]
            fetched_at = time.time()

            if data_type == "open_interest":
                # Publish to Valkey
                if redis_client:
                    hash_key = f"derivatives:latest:{asset}:oi"
                    await redis_client.hset(
                        hash_key,
                        mapping={
                            "symbol": asset,
                            "timestamp": str(latest["timestamp"]),
                            "value": str(latest["value"]),
                            "timeframe": timeframe,
                            "fetched_at": str(fetched_at),
                        },
                    )
                    if ttl_seconds > 0:
                        await redis_client.expire(hash_key, ttl_seconds)
                    logger.info(f"Published {short_name} OI to Valkey: value={latest['value']}")

                # Upsert into TimescaleDB
                if db_pool:
                    try:
                        writer = TradingViewTimescaleWriter(db_pool)
                        records = [
                            OIRecord(
                                timestamp=row["timestamp"],
                                symbol=asset,
                                open_interest=float(row["value"]),
                            )
                            for _, row in df.iterrows()
                        ]
                        await writer.insert_open_interest(records)
                        logger.info(f"Upserted {len(records)} OI records for {asset}")
                    except Exception as db_err:
                        logger.error(f"DB upsert failed for OI {asset}: {db_err}")
                        issues.append(f"db_upsert_failed:{short_name}")

            elif data_type == "funding_rate":
                # Publish to Valkey
                if redis_client:
                    hash_key = f"derivatives:latest:{asset}:funding"
                    await redis_client.hset(
                        hash_key,
                        mapping={
                            "symbol": asset,
                            "timestamp": str(latest["timestamp"]),
                            "value": str(latest["value"]),
                            "timeframe": timeframe,
                            "fetched_at": str(fetched_at),
                        },
                    )
                    if ttl_seconds > 0:
                        await redis_client.expire(hash_key, ttl_seconds)
                    logger.info(f"Published {short_name} funding rate to Valkey: value={latest['value']}")

                # Upsert into TimescaleDB
                if db_pool:
                    try:
                        writer = TradingViewTimescaleWriter(db_pool)
                        records = [
                            FundingRateRecord(
                                timestamp=row["timestamp"],
                                symbol=asset,
                                funding_rate=float(row["value"]),
                            )
                            for _, row in df.iterrows()
                        ]
                        await writer.insert_funding_rate(records)
                        logger.info(f"Upserted {len(records)} funding rate records for {asset}")
                    except Exception as db_err:
                        logger.error(f"DB upsert failed for funding rate {asset}: {db_err}")
                        issues.append(f"db_upsert_failed:{short_name}")

        except Exception as e:
            logger.error(f"Failed to process derivatives for {tv_symbol}: {e}", exc_info=True)
            issues.append(f"exception:{tv_symbol}")
            continue

    await _write_runtime_status(
        ctx,
        job_name=TV_DERIVATIVES_JOB_NAME,
        status="failed" if issues else "succeeded",
        started_at=started_at,
        error=(
            f"TradingView derivatives refresh degraded: {_summarize_issues(issues)}"
            if issues
            else None
        ),
    )


async def startup(ctx: dict[str, Any]) -> None:
    """Worker startup — initialize TV interceptor and connections."""
    from apps.scraper_app.providers.tradingview.interceptor import (
        TradingViewInterceptor,
    )

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
    interceptor = ctx.get("tv_interceptor")
    if interceptor is not None:
        await interceptor.close()
    redis = ctx.get("redis")
    if redis:
        await redis.aclose()
    logger.info("TV scraper worker shut down.")


class WorkerSettings:
    """ARQ worker settings for TV index fetching."""

    functions = [fetch_tv_indices, fetch_tv_derivatives]
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
        cron(
            fetch_tv_derivatives,
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
