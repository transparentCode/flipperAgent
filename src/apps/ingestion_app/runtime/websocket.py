from __future__ import annotations

import asyncio
import json
from typing import Any

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.events import publish_ingestion_runtime_event
from apps.ingestion_app.models.tick_models import OHLCVRecord
from apps.ingestion_app.runtime.shared import runtime_stream_timeframes
from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from apps.ingestion_app.runtime.shared import config_manager, logger, track_task
from apps.ingestion_app.jobs.shared import utc_now_ms
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager
from libs.common.timeframes import timeframe_to_seconds
from libs.contracts.schemas import IngestionEventType, StreamOHLCVPayload, valkey_encode

_tracer = None
_inject_trace_context = None
try:
    from opentelemetry import trace as _trace

    from libs.common.telemetry.propagation import inject_trace_context as _itc

    _tracer = _trace.get_tracer(__name__)
    _inject_trace_context = _itc
except ImportError:
    pass


async def verify_and_launch_ws(
    symbol: str,
    stream_timeframes: list[str],
    arq_pool: Any,
    coordinator: IngestionCoordinator,
    task_registry: set[asyncio.Task[Any]] | None = None,
) -> None:
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    logger.info(f"[{symbol}] Starting Verification Gate...")
    try:
        ready = await coordinator.wait_until_warmed(symbol, base_timeframe)
        if not ready:
            logger.error(f"[{symbol}] Gap-fill entered ERROR state. WebSocket launch aborted.")
            return
    except asyncio.TimeoutError:
        logger.error(f"[{symbol}] Warmup timed out. WebSocket launch aborted.")
        await coordinator.transition(
            symbol,
            base_timeframe,
            IngestionState.ERROR,
            reason="warmup_timeout",
            provenance="verification_gate",
        )
        return

    logger.info(f"[{symbol}] Data warmed up. Launching WebSocket pipeline.")
    websocket_task = asyncio.create_task(
        run_websocket_pipeline(symbol, stream_timeframes, arq_pool=arq_pool, coordinator=coordinator)
    )
    if task_registry is not None:
        track_task(task_registry, websocket_task)


async def run_websocket_pipeline(
    symbol: str,
    stream_timeframes: list[str],
    *,
    arq_pool: Any = None,
    coordinator: IngestionCoordinator | None = None,
) -> None:
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    live_stream_timeframes = runtime_stream_timeframes(base_timeframe, stream_timeframes)
    loop = asyncio.get_running_loop()
    reconnect_sleep_seconds = config_manager.get("ingestion.websocket.reconnect_sleep_seconds", 5)
    queue_maxsize = max(1, int(config_manager.get("ingestion.websocket.queue_maxsize", 1000)))
    stream_maxlen = int(config_manager.get("ingestion.streams.ohlcv_maxlen", 5000))
    stream_approximate = bool(config_manager.get("ingestion.streams.ohlcv_approximate", True))

    redis_client = None
    live_confirmed = False
    retry_exhausted_emitted = False

    try:
        while True:
            try:
                if redis_client is not None:
                    await redis_client.aclose()
                redis_client = await create_valkey_client(config_manager)

                try:
                    ts_writer = TimescaleWriter(DBPoolManager.get_writer_pool())
                except RuntimeError:
                    logger.error(f"[{symbol}] DB writer pool not initialized — cannot persist WS candles. Aborting.")
                    break

                queue = asyncio.Queue(maxsize=queue_maxsize)
                adapter = BinanceNativeAdapter()
                symbols_timeframes = {
                    symbol: list(live_stream_timeframes)
                }

                async for msg in adapter.stream_multiplex_socket(symbols_timeframes, loop, queue):
                    if isinstance(msg, str):
                        msg = json.loads(msg)

                    if not (isinstance(msg, dict) and "data" in msg and "k" in msg["data"]):
                        continue

                    kline = msg["data"]["k"]
                    is_closed = bool(kline.get("x", False))
                    timeframe = kline.get("i", "1m")

                    if coordinator and not live_confirmed:
                        await coordinator.transition(
                            symbol,
                            base_timeframe,
                            IngestionState.LIVE,
                            reason="first_live_bar",
                            provenance="websocket",
                        )
                        live_confirmed = True
                        retry_exhausted_emitted = False

                    record = OHLCVRecord(
                        symbol=symbol,
                        timestamp=int(kline["t"]),
                        open=float(kline["o"]),
                        high=float(kline["h"]),
                        low=float(kline["l"]),
                        close=float(kline["c"]),
                        volume=float(kline["v"]),
                        taker_buy_base=float(kline.get("Q", 0.0)),
                        is_closed=is_closed,
                    )

                    if timeframe == "1m" and is_closed:
                        await ts_writer.insert_ohlcv([record], timeframe=timeframe)

                    if is_closed and timeframe in live_stream_timeframes:
                        stream_key = f"stream:ohlcv:{symbol.lower()}:{timeframe}"
                        bar_span_seconds = timeframe_to_seconds(timeframe)
                        close_timestamp = float(kline.get("T", 0.0)) / 1000.0
                        if close_timestamp <= 0:
                            close_timestamp = record.timestamp.timestamp() + bar_span_seconds
                        emitted_at_ms = utc_now_ms()
                        payload = valkey_encode(
                            StreamOHLCVPayload(
                                exchange=EXCHANGE_BINANCE,
                                symbol=symbol,
                                timeframe=timeframe,
                                timestamp=record.timestamp.timestamp(),
                                open=record.open,
                                high=record.high,
                                low=record.low,
                                close=record.close,
                                volume=record.volume,
                                taker_buy_base=record.taker_buy_base,
                                bar_closed=True,
                                ingestion_timestamp=emitted_at_ms,
                                base_timeframe=base_timeframe,
                                bar_span_seconds=bar_span_seconds,
                                close_timestamp=close_timestamp,
                                publication_lag_ms=max(0, emitted_at_ms - int(close_timestamp * 1000)),
                                provider="binance_native",
                                origin="live_websocket",
                            ),
                            inject_trace=False,
                        )

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
                                pipe.xadd(
                                    stream_key,
                                    payload,
                                    maxlen=stream_maxlen,
                                    approximate=stream_approximate,
                                )
                                await pipe.execute()
                        else:
                            pipe = redis_client.pipeline(transaction=False)
                            pipe.xadd(
                                stream_key,
                                payload,
                                maxlen=stream_maxlen,
                                approximate=stream_approximate,
                            )
                            await pipe.execute()

            except asyncio.CancelledError:
                logger.info(f"[{symbol}] WebSocket task canceled.")
                if coordinator:
                    await coordinator.transition(
                        symbol,
                        base_timeframe,
                        IngestionState.COLD,
                        reason="websocket_cancelled",
                        provenance="websocket",
                    )
                break
            except Exception as exc:
                logger.error(
                    f"[{symbol}] WebSocket stream failed: {exc}. Reconnecting in {reconnect_sleep_seconds}s..."
                )
                if coordinator:
                    await coordinator.transition(
                        symbol,
                        base_timeframe,
                        IngestionState.COLD,
                        reason="websocket_disconnected",
                        provenance="websocket",
                    )
                if arq_pool is not None:
                    try:
                        await arq_pool.enqueue_job("run_rest_gap_fill", [symbol], EXCHANGE_BINANCE)
                        logger.info(f"[{symbol}] Enqueued gap-fill task after WS disconnect")
                    except Exception as gap_fill_error:
                        logger.warning(f"[{symbol}] Failed to enqueue gap-fill: {gap_fill_error}")

                sleep_seconds = reconnect_sleep_seconds
                live_confirmed = False
                if coordinator:
                    breaker_threshold = config_manager.get(
                        "ingestion.observability.circuit_breaker_threshold",
                        5,
                    )
                    breaker_sleep_seconds = config_manager.get(
                        "ingestion.observability.circuit_breaker_sleep_seconds",
                        300,
                    )
                    disconnect_count = await coordinator.get_disconnect_count(symbol, base_timeframe)
                    if disconnect_count >= breaker_threshold:
                        logger.critical(
                            f"[{symbol}] Circuit breaker triggered: {disconnect_count} disconnects "
                            f"in window. Backing off for {breaker_sleep_seconds}s."
                        )
                        sleep_seconds = breaker_sleep_seconds
                        if not retry_exhausted_emitted:
                            await publish_ingestion_runtime_event(
                                redis_client,
                                event_type=IngestionEventType.RUNTIME_RETRY_EXHAUSTED,
                                symbol=symbol,
                                timeframe=base_timeframe,
                                severity="critical",
                                detail={
                                    "disconnect_count": disconnect_count,
                                    "threshold": breaker_threshold,
                                    "backoff_seconds": breaker_sleep_seconds,
                                },
                            )
                            retry_exhausted_emitted = True

                await asyncio.sleep(sleep_seconds)
    finally:
        if redis_client is not None:
            await redis_client.aclose()
