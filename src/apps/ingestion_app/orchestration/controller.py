import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List

import arq
from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.tick_models import OHLCVRecord
from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

# --- OTel setup (graceful if not available) ---
_tracer = None
_inject_trace_context = None
try:
    from opentelemetry import trace as _trace
    from libs.common.telemetry.propagation import inject_trace_context as _itc
    _tracer = _trace.get_tracer(__name__)
    _inject_trace_context = _itc
except ImportError:
    pass

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
config_manager = ConfigManager()

async def verify_and_launch_ws(
    symbol: str,
    publish_timeframes: List[str],
    arq_pool: arq.connections.ArqRedis,
    coordinator: IngestionCoordinator,
) -> None:
    """Wait for data to warm up via Valkey state, then launch the WebSocket pipeline."""
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    logger.info(f"[{symbol}] Starting Verification Gate...")
    try:
        ready = await coordinator.wait_until_warmed(symbol, base_timeframe)
        if not ready:
            logger.error(f"[{symbol}] Gap-fill entered ERROR state. WebSocket launch aborted.")
            return
    except asyncio.TimeoutError:
        logger.error(f"[{symbol}] Warmup timed out. WebSocket launch aborted.")
        await coordinator.transition(symbol, base_timeframe, IngestionState.ERROR)
        return
    logger.info(f"[{symbol}] Data warmed up. Launching WebSocket pipeline.")
    asyncio.create_task(run_websocket_pipeline(symbol, publish_timeframes, arq_pool, coordinator))

async def run_websocket_pipeline(
    symbol: str,
    publish_timeframes: List[str],
    arq_pool=None,
    coordinator: IngestionCoordinator | None = None,
) -> None:
    """Persistent WebSocket pipeline for a single symbol."""
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    loop = asyncio.get_running_loop()
    reconnect_sleep_seconds = config_manager.get("ingestion.websocket.reconnect_sleep_seconds", 5)

    redis_client = None

    try:
        while True:
            try:
                # Close stale client before creating a new one on reconnect
                if redis_client is not None:
                    await redis_client.aclose()
                redis_client = await create_valkey_client(config_manager)

                # Create TimescaleWriter once per connection cycle
                try:
                    ts_writer = TimescaleWriter(DBPoolManager.get_writer_pool())
                except RuntimeError:
                    logger.error(f"[{symbol}] DB writer pool not initialized — cannot persist WS candles. Aborting.")
                    break

                queue = asyncio.Queue()
                adapter = BinanceNativeAdapter()

                symbols_timeframes = {symbol: list(set(["1m"] + publish_timeframes))}

                # Signal LIVE before entering the message loop
                if coordinator:
                    await coordinator.transition(symbol, base_timeframe, IngestionState.LIVE)

                async for msg in adapter.stream_multiplex_socket(symbols_timeframes, loop, queue):
                    if isinstance(msg, str):
                        msg = json.loads(msg)

                    if isinstance(msg, dict) and "data" in msg and "k" in msg["data"]:
                        kline = msg["data"]["k"]
                        is_closed = bool(kline.get("x", False))
                        timeframe = kline.get("i", "1m")

                        record = OHLCVRecord(
                            symbol=symbol,
                            timestamp=int(kline["t"]),
                            open=float(kline["o"]),
                            high=float(kline["h"]),
                            low=float(kline["l"]),
                            close=float(kline["c"]),
                            volume=float(kline["v"]),
                            taker_buy_base=float(kline.get("Q", 0.0)),
                            is_closed=is_closed
                        )

                        # 1. Insert closed 1m candles into TimescaleDB
                        if timeframe == "1m" and is_closed:
                            await ts_writer.insert_ohlcv([record], timeframe=timeframe)

                        # 2. Filter Valkey publish based on config
                        if is_closed and timeframe in publish_timeframes:
                            stream_key = f"stream:ohlcv:{symbol.lower()}:{timeframe}"
                            now_utc = int(datetime.now(timezone.utc).timestamp() * 1000)

                            # TODO: replace with StreamOHLCVPayload schema + valkey_encode
                            payload = {
                                "exchange": EXCHANGE_BINANCE,
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "timestamp": str(record.timestamp.timestamp()),
                                "open": str(record.open),
                                "high": str(record.high),
                                "low": str(record.low),
                                "close": str(record.close),
                                "volume": str(record.volume),
                                "taker_buy_base": str(record.taker_buy_base),
                                "bar_closed": "True",
                                "ingestion_timestamp": str(now_utc)
                            }

                            if _tracer and _inject_trace_context:
                                with _tracer.start_as_current_span(
                                    "ingestion.publish_ohlcv",
                                    attributes={
                                        "messaging.system": "valkey",
                                        "messaging.destination": stream_key,
                                        "ingestion.symbol": symbol,
                                        "ingestion.timeframe": timeframe,
                                    },
                                ):
                                    _inject_trace_context(payload)
                                    pipe = redis_client.pipeline(transaction=False)
                                    pipe.xadd(stream_key, payload, maxlen=10000, approximate=True)
                                    await pipe.execute()
                            else:
                                pipe = redis_client.pipeline(transaction=False)
                                pipe.xadd(stream_key, payload, maxlen=10000, approximate=True)
                                await pipe.execute()

            except asyncio.CancelledError:
                logger.info(f"[{symbol}] WebSocket task canceled.")
                if coordinator:
                    await coordinator.transition(symbol, base_timeframe, IngestionState.COLD)
                break
            except Exception as e:
                logger.error(f"[{symbol}] WebSocket stream failed: {e}. Reconnecting in {reconnect_sleep_seconds}s...")
                if coordinator:
                    await coordinator.transition(symbol, base_timeframe, IngestionState.COLD)
                # Trigger gap-fill immediately after WS disconnect to cover missed data
                if arq_pool is not None:
                    try:
                        await arq_pool.enqueue_job("run_rest_gap_fill", [symbol], EXCHANGE_BINANCE)
                        logger.info(f"[{symbol}] Enqueued gap-fill task after WS disconnect")
                    except Exception as gf_err:
                        logger.warning(f"[{symbol}] Failed to enqueue gap-fill: {gf_err}")

                # Circuit breaker: escalate sleep if disconnect rate exceeds threshold
                sleep_s = reconnect_sleep_seconds
                if coordinator:
                    cb_threshold = config_manager.get("ingestion.observability.circuit_breaker_threshold", 5)
                    cb_sleep = config_manager.get("ingestion.observability.circuit_breaker_sleep_seconds", 300)
                    disconnect_count = await coordinator.get_disconnect_count(symbol, base_timeframe)
                    if disconnect_count >= cb_threshold:
                        logger.critical(
                            f"[{symbol}] Circuit breaker triggered: {disconnect_count} disconnects "
                            f"in window. Backing off for {cb_sleep}s."
                        )
                        sleep_s = cb_sleep

                await asyncio.sleep(sleep_s)
    finally:
        if redis_client is not None:
            await redis_client.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = config_manager
    target_assets = cfg.get("ingestion.assets.target_list", ["BTCUSDT"])
    publish_timeframes = cfg.get("ingestion.assets.publish_timeframes", {})
    base_timeframe = cfg.get("ingestion.timeframes.base_gap_fill", "1m")
    redis_settings = RedisSettings.from_dsn(
        os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
        or cfg.get("valkey.uri", "redis://localhost:6379/0")
    )

    logger.info("Initializing DB pools...")
    await DBPoolManager.init_pools(config_manager=config_manager)

    logger.info("Connecting to ARQ redis...")
    arq_pool = await create_pool(redis_settings)

    redis_client = await create_valkey_client(cfg)
    coordinator = IngestionCoordinator(redis_client, cfg)

    for symbol in target_assets:
        try:
            try:
                stale = await coordinator.is_stale(symbol, base_timeframe)
            except Exception as stale_err:
                logger.warning(f"[{symbol}] is_stale() check failed ({stale_err}), treating as stale.")
                stale = True

            if stale:
                logger.info(f"[{symbol}] Stale/missing data. Dispatching REST gap-fill.")
                await arq_pool.enqueue_job("run_rest_gap_fill", [symbol], EXCHANGE_BINANCE)
            else:
                logger.info(f"[{symbol}] Data is up-to-date. Marking WARMING.")
                await coordinator.transition(symbol, base_timeframe, IngestionState.WARMING)

            asset_publish_timeframes = publish_timeframes.get(symbol, [])
            asyncio.create_task(verify_and_launch_ws(symbol, asset_publish_timeframes, arq_pool, coordinator))

        except Exception as e:
            logger.error(f"Error initializing asset {symbol}: {e}")

    yield

    logger.info("Shutting down... Cleaning up.")
    await DBPoolManager.close_pools()
    await arq_pool.close()
    await redis_client.aclose()

app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
