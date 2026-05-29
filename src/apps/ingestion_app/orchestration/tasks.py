import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

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

@retry(
    retry=retry_if_exception_type(DataIngestionError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=5, max=60),
    reraise=True,
)
async def _top_up_binance_ohlcv(binance_adapter, symbol: str, timeframe: str) -> None:
    """Fetch recent candles via native Binance adapter with exponential backoff on failure.

    Reads the last known timestamp from TimescaleDB and fetches up to 1000 candles
    from that point forward. Raises DataIngestionError on any fetch or write failure
    so tenacity can retry.
    """
    try:
        reader = TimescaleReader(DBPoolManager.get_reader_pool())
        max_ts = await reader.get_max_timestamp(symbol, timeframe)
    except RuntimeError:
        logger.warning(f"[{symbol}:{timeframe}] DB reader pool not ready, defaulting to 1-hour lookback.")
        max_ts = 0

    since_ms = (max_ts + 1) if max_ts > 0 else int(
        (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp() * 1000
    )

    try:
        ts_writer = TimescaleWriter(DBPoolManager.get_writer_pool())
    except RuntimeError:
        raise DataIngestionError(
            f"[{symbol}:{timeframe}] DB writer pool not initialized — cannot persist top-up",
            context={"symbol": symbol, "timeframe": timeframe},
        )

    df = await binance_adapter.get_historical_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
    if df.empty:
        logger.info(f"[{symbol}:{timeframe}] No new candles to top-up.")
        return

    records = [
        OHLCVRecord(
            symbol=symbol,
            timestamp=int(row.timestamp),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in df.itertuples(index=False)
    ]
    await ts_writer.insert_ohlcv(records, timeframe=timeframe)
    logger.info(f"[{symbol}:{timeframe}] Top-up inserted {len(records)} candle(s).")


async def poll_binance_ohlcv(
    ctx: Dict[str, Any],
    symbol: str | None = None,
    timeframe: str | None = None,
) -> None:
    """Top-up recent OHLCV candles for one or all configured assets via the native Binance adapter.

    Runs as a cron job (default: every 15 min). Fetches from the last known timestamp in
    TimescaleDB to now, covering gaps that the WebSocket stream may have missed.

    When called without symbol/timeframe (cron invocation), iterates all assets in
    ingestion.assets.target_list using ingestion.timeframes.default as the timeframe.
    """
    tf = timeframe or config_manager.get("ingestion.timeframes.default", "15m")

    binance_adapter = ctx.get("binance_adapter")
    if not binance_adapter:
        raise DataIngestionError(
            "Binance adapter not found in worker context",
            context={"symbol": symbol or "all", "timeframe": tf},
        )

    symbols = [symbol] if symbol is not None else config_manager.get("ingestion.assets.target_list", ["BTCUSDT"])

    for sym in symbols:
        logger.info(f"[{sym}:{tf}] Starting native Binance top-up.")
        await _top_up_binance_ohlcv(binance_adapter, sym, tf)

    logger.info(f"poll_binance_ohlcv completed for {len(symbols)} asset(s).")


# Exponential backoff layer (Layer 4)
# Retries on DataIngestionError because CCXTAdapter wraps all ccxt exceptions into
# DataIngestionError before they propagate — raw ccxt types never reach this decorator.
@retry(
    retry=retry_if_exception_type(DataIngestionError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=4, max=60),
    reraise=True,
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
        ts_writer = TimescaleWriter(DBPoolManager.get_writer_pool())
    except RuntimeError as e:
        raise DataIngestionError(
            f"DB writer pool not initialized — cannot persist gap-fill for {symbol}",
            context={"symbol": symbol},
        ) from e

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
                
            if records:
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
    if coordinator is None:
        raise DataIngestionError(
            "coordinator not found in worker context — state machine cannot progress",
            context={"exchange": exchange, "assets": assets},
        )
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    concurrency_limit = config_manager.get("ingestion.concurrency.gap_fill_limit", 5)
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def process_asset(symbol: str):
        async with semaphore:
            await coordinator.transition(symbol, base_timeframe, IngestionState.BACKFILLING)
            try:
                await _fetch_asset_gap(ctx, ccxt_adapter, symbol)
                await coordinator.transition(symbol, base_timeframe, IngestionState.WARMING)
            except Exception as e:
                logger.error(f"Failed to gap-fill {symbol}: {e}")
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
