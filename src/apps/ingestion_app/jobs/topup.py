from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

from apps.ingestion_app.jobs.shared import (
    build_ohlcv_records,
    config_manager,
    list_schedulable_symbols,
    require_context_value,
)

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


@retry(
    retry=retry_if_exception_type(DataIngestionError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=5, max=60),
    reraise=True,
)
async def _top_up_binance_ohlcv(binance_adapter: Any, symbol: str, timeframe: str) -> None:
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
    except RuntimeError as exc:
        raise DataIngestionError(
            f"[{symbol}:{timeframe}] DB writer pool not initialized — cannot persist top-up",
            context={"symbol": symbol, "timeframe": timeframe},
        ) from exc

    frame = await binance_adapter.get_historical_ohlcv(symbol, timeframe, since=since_ms, limit=1000)
    if frame.empty:
        logger.info(f"[{symbol}:{timeframe}] No new candles to top-up.")
        return

    await ts_writer.insert_ohlcv(build_ohlcv_records(symbol, frame), timeframe=timeframe)
    logger.info(f"[{symbol}:{timeframe}] Top-up inserted {len(frame)} candle(s).")


async def poll_binance_ohlcv(
    ctx: dict[str, Any],
    symbol: str | None = None,
    timeframe: str | None = None,
) -> None:
    tf = timeframe or config_manager.get("ingestion.timeframes.default", "15m")
    binance_adapter = require_context_value(
        ctx,
        "binance_adapter",
        error_message="Binance adapter not found in worker context",
        context={"symbol": symbol or "all", "timeframe": tf},
    )
    symbols = [symbol] if symbol is not None else await list_schedulable_symbols()
    if not symbols:
        logger.info("poll_binance_ohlcv skipped: no schedulable assets.")
        return

    for current_symbol in symbols:
        logger.info(f"[{current_symbol}:{tf}] Starting native Binance top-up.")
        await _top_up_binance_ohlcv(binance_adapter, current_symbol, tf)

    logger.info(f"poll_binance_ohlcv completed for {len(symbols)} asset(s).")
