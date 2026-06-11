import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from typing import Any, List, Set

import arq
from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI

from apps.ingestion_app.asset_registry import IngestionAssetCatalog
from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.constants import EXCHANGE_BINANCE, INGESTION_CONTROL_STREAM
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.events import publish_ingestion_runtime_event
from apps.ingestion_app.models.asset_registry import IngestionAssetDesiredState, IngestionAssetRecord
from apps.ingestion_app.models.tick_models import OHLCVRecord
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import IngestionEventType, StreamOHLCVPayload, valkey_encode

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

def _track_task(task_registry: Set[asyncio.Task[Any]], task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    task_registry.add(task)
    task.add_done_callback(task_registry.discard)
    return task


@dataclass(frozen=True)
class AssetRuntimeSpec:
    symbol: str
    base_timeframe: str
    publish_timeframes: tuple[str, ...]
    enabled: bool
    desired_state: IngestionAssetDesiredState

    @classmethod
    def from_asset(cls, asset: IngestionAssetRecord) -> "AssetRuntimeSpec":
        return cls(
            symbol=asset.symbol,
            base_timeframe=asset.base_timeframe,
            publish_timeframes=tuple(sorted(asset.publish_timeframes)),
            enabled=asset.enabled,
            desired_state=asset.desired_state,
        )

    def should_run(self) -> bool:
        return self.enabled and self.desired_state == IngestionAssetDesiredState.LIVE


@dataclass
class AssetRuntimeHandle:
    spec: AssetRuntimeSpec
    tasks: Set[asyncio.Task[Any]] = field(default_factory=set)


async def _initialize_asset_runtime(
    asset: IngestionAssetRecord,
    arq_pool: arq.connections.ArqRedis,
    coordinator: IngestionCoordinator,
    task_registry: Set[asyncio.Task[Any]],
) -> None:
    symbol = asset.symbol
    base_timeframe = asset.base_timeframe
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

        await verify_and_launch_ws(
            symbol,
            list(asset.publish_timeframes),
            arq_pool,
            coordinator,
            task_registry,
        )
    except asyncio.CancelledError:
        await coordinator.transition(symbol, base_timeframe, IngestionState.COLD)
        raise
    except Exception as exc:
        logger.error(f"[{symbol}] Asset runtime bootstrap failed: {exc}", exc_info=True)
        await coordinator.transition(symbol, base_timeframe, IngestionState.ERROR)


class IngestionRuntimeReconciler:
    def __init__(
        self,
        *,
        config_manager: ConfigManager,
        arq_pool: arq.connections.ArqRedis,
        coordinator: IngestionCoordinator,
        redis_client: Any,
        asset_catalog: IngestionAssetCatalog | None = None,
    ) -> None:
        self.config_manager = config_manager
        self.arq_pool = arq_pool
        self.coordinator = coordinator
        self.redis_client = redis_client
        self.asset_catalog = asset_catalog or IngestionAssetCatalog(config_manager=config_manager)
        self.asset_handles: dict[str, AssetRuntimeHandle] = {}
        self.pending_removals: set[str] = set()
        self.control_stream_last_id = "$"
        self.reconcile_interval_seconds = float(
            self.config_manager.get("ingestion.runtime.reconcile_interval_seconds", 5)
        )

    async def run(self) -> None:
        while True:
            await self.reconcile_once()
            await self._wait_for_change()

    async def reconcile_once(self) -> None:
        assets = await self.asset_catalog.list_effective_assets()
        desired_by_symbol = {asset.symbol: asset for asset in assets}
        self.pending_removals.intersection_update(
            {asset.symbol for asset in assets if asset.desired_state == IngestionAssetDesiredState.REMOVING}
        )

        for symbol, handle in list(self.asset_handles.items()):
            desired = desired_by_symbol.get(symbol)
            if desired is None:
                await self._stop_asset(symbol, handle)
                continue

            desired_spec = AssetRuntimeSpec.from_asset(desired)
            if desired.desired_state == IngestionAssetDesiredState.REMOVING or not desired_spec.should_run():
                await self._stop_asset(symbol, handle)
                continue

            if not handle.tasks or handle.spec != desired_spec:
                await self._stop_asset(symbol, handle)

        for symbol, asset in desired_by_symbol.items():
            desired_spec = AssetRuntimeSpec.from_asset(asset)
            if asset.desired_state == IngestionAssetDesiredState.REMOVING:
                await self._dispatch_asset_removal(asset)
                continue
            if not desired_spec.should_run():
                continue
            if symbol in self.asset_handles:
                continue
            await self._start_asset(asset, desired_spec)

    async def stop(self) -> None:
        for symbol, handle in list(self.asset_handles.items()):
            await self._stop_asset(symbol, handle)

    async def _start_asset(self, asset: IngestionAssetRecord, spec: AssetRuntimeSpec) -> None:
        handle = AssetRuntimeHandle(spec=spec)
        bootstrap_task = asyncio.create_task(
            _initialize_asset_runtime(asset, self.arq_pool, self.coordinator, handle.tasks)
        )
        _track_task(handle.tasks, bootstrap_task)
        self.asset_handles[asset.symbol] = handle
        logger.info(
            f"[{asset.symbol}] Runtime started "
            f"(publish_timeframes={list(spec.publish_timeframes)}, base_timeframe={spec.base_timeframe})"
        )

    async def _stop_asset(self, symbol: str, handle: AssetRuntimeHandle) -> None:
        self.asset_handles.pop(symbol, None)
        for task in list(handle.tasks):
            task.cancel()
        if handle.tasks:
            await asyncio.gather(*handle.tasks, return_exceptions=True)
        try:
            await self.coordinator.transition(symbol, handle.spec.base_timeframe, IngestionState.COLD)
        except Exception:
            logger.warning(f"[{symbol}] Failed to transition runtime to COLD during stop", exc_info=True)
        logger.info(f"[{symbol}] Runtime stopped")

    async def _dispatch_asset_removal(self, asset: IngestionAssetRecord) -> None:
        if asset.symbol in self.pending_removals:
            return

        try:
            await self.arq_pool.enqueue_job("purge_removed_asset", asset.symbol, asset.base_timeframe)
            self.pending_removals.add(asset.symbol)
            logger.info(f"[{asset.symbol}] Dispatched asset purge job")
        except Exception as exc:
            logger.warning(f"[{asset.symbol}] Failed to dispatch asset purge job: {exc}", exc_info=True)
            await publish_ingestion_runtime_event(
                self.redis_client,
                event_type=IngestionEventType.ASSET_PURGE_FAILED,
                symbol=asset.symbol,
                timeframe=asset.base_timeframe,
                severity="error",
                detail={"error": str(exc), "phase": "dispatch"},
            )

    async def _wait_for_change(self) -> None:
        stream_wait_ms = max(250, int(self.reconcile_interval_seconds * 1000))
        xread = getattr(self.redis_client, "xread", None)
        if not callable(xread):
            await asyncio.sleep(self.reconcile_interval_seconds)
            return

        try:
            response = await xread(
                {INGESTION_CONTROL_STREAM: self.control_stream_last_id},
                count=10,
                block=stream_wait_ms,
            )
            if not response or not isinstance(response, (list, tuple)):
                return
            for _stream_name, messages in response:
                if messages:
                    self.control_stream_last_id = messages[-1][0]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Runtime control stream wait failed: {exc}", exc_info=True)
            await asyncio.sleep(self.reconcile_interval_seconds)


async def verify_and_launch_ws(
    symbol: str,
    publish_timeframes: List[str],
    arq_pool: arq.connections.ArqRedis,
    coordinator: IngestionCoordinator,
    task_registry: Set[asyncio.Task[Any]] | None = None,
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
    websocket_task = asyncio.create_task(
        run_websocket_pipeline(symbol, publish_timeframes, arq_pool, coordinator)
    )
    if task_registry is not None:
        _track_task(task_registry, websocket_task)

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
    queue_maxsize = max(1, int(config_manager.get("ingestion.websocket.queue_maxsize", 1000)))

    redis_client = None
    live_confirmed = False
    retry_exhausted_emitted = False

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

                queue = asyncio.Queue(maxsize=queue_maxsize)
                adapter = BinanceNativeAdapter()

                symbols_timeframes = {symbol: list(set(["1m"] + publish_timeframes))}

                async for msg in adapter.stream_multiplex_socket(symbols_timeframes, loop, queue):
                    if isinstance(msg, str):
                        msg = json.loads(msg)

                    if isinstance(msg, dict) and "data" in msg and "k" in msg["data"]:
                        kline = msg["data"]["k"]
                        is_closed = bool(kline.get("x", False))
                        timeframe = kline.get("i", "1m")

                        if coordinator and not live_confirmed:
                            await coordinator.transition(symbol, base_timeframe, IngestionState.LIVE)
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
                            is_closed=is_closed
                        )

                        # 1. Insert closed 1m candles into TimescaleDB
                        if timeframe == "1m" and is_closed:
                            await ts_writer.insert_ohlcv([record], timeframe=timeframe)

                        # 2. Filter Valkey publish based on config
                        if is_closed and timeframe in publish_timeframes:
                            stream_key = f"stream:ohlcv:{symbol.lower()}:{timeframe}"
                            now_utc = int(datetime.now(timezone.utc).timestamp() * 1000)

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
                                    ingestion_timestamp=now_utc,
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
                live_confirmed = False
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
                        if not retry_exhausted_emitted:
                            await publish_ingestion_runtime_event(
                                redis_client,
                                event_type=IngestionEventType.RUNTIME_RETRY_EXHAUSTED,
                                symbol=symbol,
                                timeframe=base_timeframe,
                                severity="critical",
                                detail={
                                    "disconnect_count": disconnect_count,
                                    "threshold": cb_threshold,
                                    "backoff_seconds": cb_sleep,
                                },
                            )
                            retry_exhausted_emitted = True

                await asyncio.sleep(sleep_s)
    finally:
        if redis_client is not None:
            await redis_client.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = config_manager
    redis_settings = RedisSettings.from_dsn(
        os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
        or cfg.get("valkey.uri", "redis://localhost:6379/0")
    )

    logger.info("Initializing DB pools...")
    await DBPoolManager.init_pools(config_manager=config_manager)
    await apply_ingestion_schema(DBPoolManager.get_writer_pool())

    logger.info("Connecting to ARQ redis...")
    arq_pool = await create_pool(redis_settings)

    redis_client = await create_valkey_client(cfg)
    coordinator = IngestionCoordinator(redis_client, cfg)
    background_tasks: Set[asyncio.Task[Any]] = set()
    reconciler = IngestionRuntimeReconciler(
        config_manager=cfg,
        arq_pool=arq_pool,
        coordinator=coordinator,
        redis_client=redis_client,
    )

    await reconciler.reconcile_once()
    reconciler_task = _track_task(background_tasks, asyncio.create_task(reconciler.run()))

    yield

    logger.info("Shutting down... Cleaning up.")
    reconciler_task.cancel()
    await reconciler.stop()
    for task in list(background_tasks):
        task.cancel()
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
    await DBPoolManager.close_pools()
    await arq_pool.close()
    await redis_client.aclose()

app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
