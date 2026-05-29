import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

import ccxt
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.tick_models import OHLCVRecord
from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

config_manager = ConfigManager()

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

async def poll_binance_ohlcv(
    ctx: Dict[str, Any],
    symbol: str | None = None,
    timeframe: str | None = None,
) -> None:
    """Placeholder task to poll Binance OHLCV data.
    Uses the adapter instances setup in ctx.
    """
    cfg = ConfigManager()
    if symbol is None:
        symbol = cfg.get("ingestion.assets.default_binance_asset", "BTCUSDT")
    if timeframe is None:
        timeframe = cfg.get("ingestion.timeframes.default", "15m")
    logger.info(f"Task poll_binance_ohlcv started for {symbol} ({timeframe})")
    
    binance_adapter = ctx.get("binance_adapter")
    if not binance_adapter:
        logger.warning("Binance adapter not found in worker context!")
        return

    # Simulate an IO-bound threaded fetch
    logger.info("Dispatching synchronous binance_adapter fetch to thread pool...")
    try:
        # e.g.: df = await asyncio.to_thread(binance_adapter.fetch_ohlcv, symbol, timeframe)
        # For now, we mock the delay:
        await asyncio.sleep(1)
        logger.info(f"Successfully processed {symbol} OHLCV.")
    except Exception as e:
        logger.error(f"Error polling OHLCV for {symbol}: {e}")
        raise DataIngestionError(f"Error polling OHLCV for {symbol}", context={"symbol": symbol}) from e


# Exponential backoff layer (Layer 4)
@retry(
    retry=retry_if_exception_type((ccxt.RateLimitExceeded, ccxt.RequestTimeout, ccxt.NetworkError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=4, max=60),
    reraise=True
)
async def _fetch_asset_gap(ctx: Dict[str, Any], ccxt_adapter, symbol: str):
    """
    Fetch history for a single asset with tenacity retries on 429 RateLimit failures.
    """
    logger.info(f"Fetching REST data for asset: {symbol}")
    
    historical_backfill_days = config_manager.get("ingestion.assets.historical_backfill_days", 2)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = now_ms - historical_backfill_days * 86400 * 1000
    
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    
    try:
        reader_pool = DBPoolManager.get_reader_pool()
        reader = TimescaleReader(reader_pool)
        max_ts = await reader.get_max_timestamp(symbol, base_timeframe)
        start_ts = max(since_ms, max_ts) if max_ts > 0 else since_ms
    except RuntimeError:
        logger.warning("DB reader pool not initialized. Starting from backfill days.")
        start_ts = since_ms

    limit = 1000
    sleep_seconds = config_manager.get("ingestion.concurrency.gap_fill_sleep_seconds", 0.5)

    try:
        ts_pool = DBPoolManager.get_writer_pool()
        ts_writer: TimescaleWriter | None = TimescaleWriter(ts_pool)
    except RuntimeError:
        logger.warning("DB writer pool not initialized. TimescaleDB inserts will be skipped.")
        ts_writer = None

    while True:
        try:
            df = await ccxt_adapter.get_historical_ohlcv(symbol, base_timeframe, since=start_ts, limit=limit)
            
            if df.empty:
                logger.info(f"No more data returned for {symbol}.")
                break
            
            # Normalize with Pydantic
            records = []
            for row in df.itertuples(index=False):
                record = OHLCVRecord(
                    symbol=symbol,
                    timestamp=int(row.timestamp),
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume
                )
                records.append(record)
                
            if records and ts_writer is not None:
                await ts_writer.insert_ohlcv(records, timeframe=base_timeframe)
            
            if len(df) < limit:
                break
                
            last_ts = int(df.iloc[-1]['timestamp'])
            start_ts = last_ts + 1
            
            await asyncio.sleep(sleep_seconds)
            
        except Exception as e:
            logger.error(f"Error fetching page for {symbol} at {start_ts}: {e}")
            raise

async def run_rest_gap_fill(ctx: Dict[str, Any], assets: List[str], exchange: str) -> None:
    """
    Checks the latest bucket in `market_1m_bars` for each asset.
    If latest bucket < current_time - 1m, fetches historical klines/trades 
    via REST to bridge the gap.
    """
    logger.info(f"Task run_rest_gap_fill started for exchange {exchange} with {len(assets)} assets")

    ccxt_adapter = ctx.get("ccxt_adapter")
    coordinator: IngestionCoordinator | None = ctx.get("coordinator")
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    concurrency_limit = config_manager.get("ingestion.concurrency.gap_fill_limit", 5)
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def process_asset(symbol: str):
        async with semaphore:
            if coordinator:
                await coordinator.transition(symbol, base_timeframe, IngestionState.BACKFILLING)
            try:
                await _fetch_asset_gap(ctx, ccxt_adapter, symbol)
                if coordinator:
                    await coordinator.transition(symbol, base_timeframe, IngestionState.WARMING)
            except Exception as e:
                logger.error(f"Failed to gap-fill {symbol}: {e}")
                if coordinator:
                    await coordinator.transition(symbol, base_timeframe, IngestionState.ERROR)
            # Space out calls after each asset completes
            await asyncio.sleep(config_manager.get("ingestion.concurrency.gap_fill_sleep_seconds", 0.5))

    await asyncio.gather(*(process_asset(symbol) for symbol in assets))
    logger.info(f"Gap fill task completed successfully for {exchange}.")

async def scheduled_gap_fill(ctx: Dict[str, Any]) -> None:
    """
    Wrapper for cron job gap fill. Looks up target_list and passes it to run_rest_gap_fill.
    """
    from apps.ingestion_app.constants import EXCHANGE_BINANCE
    target_list = config_manager.get("ingestion.assets.target_list", ["BTCUSDT"])
    await run_rest_gap_fill(ctx, target_list, EXCHANGE_BINANCE)
