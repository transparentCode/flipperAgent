import asyncio
from typing import List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI
import arq
from arq.connections import create_pool, RedisSettings
from datetime import datetime, timezone
import logging

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent
from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader
from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from apps.ingestion_app.models.tick_models import OHLCVRecord
from apps.ingestion_app.constants import EXCHANGE_BINANCE
import json

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
config_manager = ConfigManager()

# Global state for lifespan
app_state: Dict[str, Any] = {}

async def verify_and_launch_ws(symbol: str, arq_pool: arq.connections.ArqRedis):
    """
    Periodically checks if the DB is caught up to near-real-time.
    Once verified, launches the WebSocket stream for the asset.
    """
    warmup_threshold_ms = config_manager.get("ingestion.websocket.warmup_threshold_ms", 300000)
    verification_sleep_seconds = config_manager.get("ingestion.websocket.verification_sleep_seconds", 10)
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    
    logger.info(f"[{symbol}] Starting Verification Gate loop...")
    while True:
        try:
            ts_pool = DBPoolManager.get_reader_pool()
            reader = TimescaleReader(ts_pool)
            max_ts = await reader.get_max_timestamp(symbol, base_timeframe)
            
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            
            if max_ts == 0 or (now_ms - max_ts) > warmup_threshold_ms:
                logger.info(f"[{symbol}] Data is stale or missing. max_ts={max_ts}, now={now_ms}. Still waiting for REST gap-fill.")
                await asyncio.sleep(verification_sleep_seconds)
                continue
            
            logger.info(f"[{symbol}] Data is caught up! Proceeding to launch WebSocket.")
            break
            
        except Exception as e:
            logger.error(f"[{symbol}] Error in Verification Gate: {e}")
            await asyncio.sleep(verification_sleep_seconds)

    # Launch WebSocket pipeline for this asset
    asyncio.create_task(run_websocket_pipeline(symbol))

async def run_websocket_pipeline(symbol: str):
    """
    Launches the live WebSocket pipeline for the given asset.
    """
    logger.info(f"[{symbol}] Launching WebSocket pipeline...")
    loop = asyncio.get_event_loop()
    reconnect_sleep_seconds = config_manager.get("ingestion.websocket.reconnect_sleep_seconds", 5)
    
    while True:
        try:
            queue = asyncio.Queue()
            adapter = BinanceNativeAdapter()
            
            async for msg in adapter.stream_multiplex_socket([symbol], loop, queue):
                if isinstance(msg, str):
                    msg = json.loads(msg)
                
                if isinstance(msg, dict) and "data" in msg and "k" in msg["data"]:
                    kline = msg["data"]["k"]
                    
                    record = OHLCVRecord(
                        symbol=symbol,
                        timestamp=int(kline["t"]),
                        open=float(kline["o"]),
                        high=float(kline["h"]),
                        low=float(kline["l"]),
                        close=float(kline["c"]),
                        volume=float(kline["v"])
                    )
                    
                    ts_pool = DBPoolManager.get_writer_pool()
                    if ts_pool is not None:
                        writer = TimescaleWriter(ts_pool)
                        await writer.insert_ohlcv([record], timeframe=kline["i"])
                        
        except asyncio.CancelledError:
            logger.info(f"[{symbol}] WebSocket task canceled.")
            break
        except Exception as e:
            logger.error(f"[{symbol}] WebSocket stream failed: {e}. Reconnecting in {reconnect_sleep_seconds}s...")
            await asyncio.sleep(reconnect_sleep_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # a. Boot: Read target assets list
    target_assets = config_manager.get("ingestion.assets.target_list", ["BTCUSDT"])
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    import os
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URI") or config_manager.get("redis.uri", "redis://localhost:6379/0"))

    # b. Connect DB
    logger.info("Initializing DB pools...")
    await DBPoolManager.init_pools()
    
    # Initialize ARQ pool
    logger.info("Connecting to ARQ redis...")
    arq_pool = await create_pool(redis_settings)
    app_state["arq_pool"] = arq_pool
    
    for symbol in target_assets:
        try:
            ts_pool = DBPoolManager.get_reader_pool()
            reader = TimescaleReader(ts_pool)
            
            # c. Assess DB
            max_ts = await reader.get_max_timestamp(symbol, base_timeframe)
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            
            warmup_threshold_ms = config_manager.get("ingestion.websocket.warmup_threshold_ms", 300000)
            
            # d. REST Handoff if stale
            if max_ts == 0 or (now_ms - max_ts) > warmup_threshold_ms:
                logger.info(f"[{symbol}] Stale/missing data. Dispatching REST gap-fill task. Marking BACKFILLING.")
                await arq_pool.enqueue_job("run_rest_gap_fill", [symbol], EXCHANGE_BINANCE)
            else:
                logger.info(f"[{symbol}] Data is up-to-date. Skipping REST gap-fill.")

            # e. Start Verification Gate loop
            asyncio.create_task(verify_and_launch_ws(symbol, arq_pool))
            
        except Exception as e:
            logger.error(f"Error initializing asset {symbol}: {e}")

    yield

    logger.info("Shutting down... Cleaning up DB pools.")
    await DBPoolManager.close_pools()
    await app_state["arq_pool"].close()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {"status": "ok"}
