from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect
from typing import Any

from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from apps.strategy_app.control import StrategyControlStore, StrategyDesiredState
from apps.strategy_app.observability.runtime_state import StrategyRuntimeStateStore
from apps.strategy_app.runtime.worker import StrategyWorker
from apps.strategy_app.settings import StrategyWorkerSettings
from apps.strategy_app.state import StrategyPair, StrategyPairState
from libs.common.asset_manifest import ASSET_LIFECYCLE_STREAM, AssetLifecycleEvent
from libs.common.enums import SystemComponent
from libs.common.lifecycle_dedup import mark_lifecycle_event_processed
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import ensure_consumer_group
from libs.contracts.serialization import valkey_decode

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


class StrategyRuntimeRunner:
    def __init__(
        self,
        pairs: list[StrategyPair],
        *,
        worker_factory: Callable[..., StrategyWorker] | None = None,
        worker_settings: StrategyWorkerSettings | None = None,
        config_manager: Any | None = None,
    ) -> None:
        self.worker_factory = worker_factory or StrategyWorker
        self.worker_settings = worker_settings or StrategyWorkerSettings()
        self.config_manager = config_manager
        self.redis_client: Any = None
        self._catalog_pairs_by_key: dict[str, StrategyPair] = {pair.key: pair for pair in pairs}
        self._pairs_by_key: dict[str, StrategyPair] = {pair.key: pair for pair in pairs}
        self._workers_by_key: dict[str, StrategyWorker] = {}
        self._worker_tasks: dict[str, asyncio.Task[None]] = {}
        self._runtime_state: StrategyRuntimeStateStore | None = None
        self._control_state: StrategyControlStore | None = None
        self._lifecycle_task: asyncio.Task[None] | None = None
        self._supervisor_task: asyncio.Task[None] | None = None

    async def connect(self, redis_client: Any) -> list[StrategyWorker]:
        self.redis_client = redis_client
        self._runtime_state = StrategyRuntimeStateStore(redis_client)
        self._control_state = StrategyControlStore(redis_client)
        workers = await self._start_pairs(list(self._pairs_by_key.values()))
        return list(workers)

    async def start(self) -> None:
        if self.redis_client is None:
            raise RuntimeError("StrategyRuntimeRunner.connect() must be called before start().")
        await ensure_consumer_group(
            self.redis_client,
            ASSET_LIFECYCLE_STREAM,
            self.worker_settings.consumer_group,
            start_id="$",
        )
        self._lifecycle_task = asyncio.create_task(self._watch_lifecycle())
        self._supervisor_task = asyncio.create_task(self._supervise())
        try:
            results = await asyncio.gather(
                self._lifecycle_task,
                self._supervisor_task,
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result
        finally:
            self._lifecycle_task = None
            self._supervisor_task = None

    async def stop(self) -> None:
        tasks: list[asyncio.Task[Any]] = []
        if self._lifecycle_task is not None:
            tasks.append(self._lifecycle_task)
        if self._supervisor_task is not None:
            tasks.append(self._supervisor_task)
        tasks.extend(self._worker_tasks.values())
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._worker_tasks = {}
        self._workers_by_key = {}
        self._lifecycle_task = None
        self._supervisor_task = None

    async def _start_pairs(self, pairs: list[StrategyPair]) -> list[StrategyWorker]:
        started_workers: list[StrategyWorker] = []
        for pair in pairs:
            started = await self._ensure_pair_started(pair)
            if started is not None:
                started_workers.append(started)
        return started_workers

    async def _ensure_pair_started(self, pair: StrategyPair) -> StrategyWorker | None:
        if not pair.enabled or self.redis_client is None:
            return None
        if pair.key in self._worker_tasks:
            self._pairs_by_key[pair.key] = pair
            return self._workers_by_key[pair.key]
        worker = self._build_worker(pair)
        await worker.connect(self.redis_client)
        self._pairs_by_key[pair.key] = pair
        self._workers_by_key[pair.key] = worker
        self._worker_tasks[pair.key] = asyncio.create_task(worker.start())
        return worker

    async def _stop_pair(
        self,
        pair_key: str,
        *,
        state: StrategyPairState | None = None,
        reason: str | None = None,
        clear_status: bool = False,
    ) -> None:
        task = self._worker_tasks.pop(pair_key, None)
        self._workers_by_key.pop(pair_key, None)
        pair = self._pairs_by_key.get(pair_key)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if pair is not None and self._control_state is not None:
            if clear_status:
                await self._control_state.delete(pair)
            else:
                desired_state = (
                    StrategyDesiredState.PAUSED
                    if state == StrategyPairState.PAUSED
                    else StrategyDesiredState.LIVE
                )
                await self._control_state.set_desired_state(
                    pair,
                    desired_state,
                    reason=reason,
                )
        if pair is not None and self._runtime_state is not None:
            if clear_status:
                await self._runtime_state.delete(pair)
                await self._clear_pair_streams(pair)
            elif state is not None:
                await self._runtime_state.update(
                    pair,
                    state=state,
                    last_error=None,
                    replace_last_error=True,
                    detail={"phase": "lifecycle", "reason": reason or state.value.lower()},
                )
        if clear_status:
            self._pairs_by_key.pop(pair_key, None)

    async def _clear_pair_streams(self, pair: StrategyPair) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.delete(f"signals:{pair.asset}:{pair.timeframe}")

    async def _watch_lifecycle(self) -> None:
        assert self.redis_client is not None
        streams = {ASSET_LIFECYCLE_STREAM: ">"}
        consumer_name = f"{self.worker_settings.consumer_name_prefix}_lifecycle"
        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.worker_settings.consumer_group,
                    consumer_name,
                    streams,
                    count=25,
                    block=self.worker_settings.block_ms,
                )
                if not response:
                    continue
                for _stream_name, messages in response:
                    for message_id, payload in messages:
                        event = valkey_decode(payload, AssetLifecycleEvent)
                        if not await mark_lifecycle_event_processed(
                            self.redis_client,
                            consumer_namespace="strategy",
                            event_id=event.event_id,
                        ):
                            await self.redis_client.xack(
                                ASSET_LIFECYCLE_STREAM,
                                self.worker_settings.consumer_group,
                                message_id,
                            )
                            continue
                        await self._apply_lifecycle_event(event)
                        await self.redis_client.xack(
                            ASSET_LIFECYCLE_STREAM,
                            self.worker_settings.consumer_group,
                            message_id,
                        )
            except asyncio.CancelledError:
                raise
            except ValkeyTimeoutError:
                logger.warning("Strategy lifecycle watcher timed out; retrying.")
                await asyncio.sleep(1)
            except Exception as exc:
                logger.warning("Strategy lifecycle watcher failed: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def _apply_lifecycle_event(self, event: AssetLifecycleEvent) -> None:
        desired_pairs = {
            pair.key: pair
            for pair in self._desired_pairs_for_event(event)
        }
        existing_keys = [
            pair_key for pair_key in list(self._pairs_by_key)
            if pair_key.startswith(f"{event.symbol}:")
        ]
        if event.desired_state == "LIVE" and event.enabled:
            for pair_key in existing_keys:
                if pair_key not in desired_pairs:
                    await self._stop_pair(
                        pair_key,
                        state=StrategyPairState.STOPPED,
                        reason="timeframe_removed",
                        clear_status=True,
                    )
            for pair in desired_pairs.values():
                if self._control_state is not None:
                    await self._control_state.set_desired_state(
                        pair,
                        StrategyDesiredState.LIVE,
                        reason=event.reason,
                    )
                await self._ensure_pair_started(pair)
            return

        stop_state = (
            StrategyPairState.PAUSED
            if event.desired_state == "PAUSED"
            else StrategyPairState.STOPPED
        )
        clear_status = event.desired_state == "REMOVING"
        for pair_key in existing_keys:
            await self._stop_pair(
                pair_key,
                state=stop_state,
                reason=event.desired_state.lower(),
                clear_status=clear_status,
            )

    async def _supervise(self) -> None:
        while True:
            if self._lifecycle_task is not None and self._lifecycle_task.done():
                if self._lifecycle_task.cancelled():
                    raise asyncio.CancelledError
                error = self._lifecycle_task.exception()
                if error is not None:
                    raise error
                raise RuntimeError("Strategy lifecycle watcher exited unexpectedly")
            for pair_key, task in list(self._worker_tasks.items()):
                if not task.done():
                    continue
                self._worker_tasks.pop(pair_key, None)
                self._workers_by_key.pop(pair_key, None)
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error
            await asyncio.sleep(0.1)

    def _build_worker(self, pair: StrategyPair) -> StrategyWorker:
        parameters = inspect.signature(self.worker_factory).parameters
        kwargs: dict[str, Any] = {}
        if "config_manager" in parameters and self.config_manager is not None:
            kwargs["config_manager"] = self.config_manager
        if "settings" in parameters:
            kwargs["settings"] = self.worker_settings
        if "trigger_timeframe" in parameters:
            kwargs["trigger_timeframe"] = pair.trigger_timeframe or pair.timeframe
        if "trigger_mode" in parameters:
            kwargs["trigger_mode"] = pair.trigger_mode
        if "base_timeframe" in parameters:
            kwargs["base_timeframe"] = pair.base_timeframe
        if "allowed_model_names" in parameters:
            kwargs["allowed_model_names"] = list(pair.model_names)
        return self.worker_factory(pair.asset, pair.timeframe, **kwargs)

    @staticmethod
    def _event_timeframes(event: AssetLifecycleEvent) -> list[str]:
        timeframes = list(event.timeframes or [])
        if not timeframes:
            timeframes = [event.base_timeframe, *list(event.publish_timeframes or [])]
        ordered: list[str] = []
        for timeframe in timeframes:
            normalized = str(timeframe).strip()
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        return ordered

    def _desired_pairs_for_event(self, event: AssetLifecycleEvent) -> list[StrategyPair]:
        event_timeframes = set(self._event_timeframes(event))
        configured = [
            pair
            for pair in self._catalog_pairs_by_key.values()
            if pair.asset == event.symbol
            and (pair.trigger_timeframe or pair.timeframe) in event_timeframes
        ]
        if configured:
            return configured
        return [
            StrategyPair(
                asset=event.symbol,
                timeframe=timeframe,
                trigger_timeframe=timeframe,
                base_timeframe=event.base_timeframe,
                source="asset_manifest",
            )
            for timeframe in event_timeframes
        ]
