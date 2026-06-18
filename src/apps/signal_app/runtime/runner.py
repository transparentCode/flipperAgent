from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect
from typing import Any

from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.models import SignalPair
from apps.signal_app.models import SignalPairState
from apps.signal_app.observability.runtime_state import SignalRuntimeStateStore
from apps.signal_app.runtime.worker import SignalRuntimeWorker
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.asset_manifest import ASSET_LIFECYCLE_STREAM, AssetLifecycleEvent
from libs.common.enums import SystemComponent
from libs.common.lifecycle_dedup import mark_lifecycle_event_processed
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import ensure_consumer_group
from libs.contracts.serialization import valkey_decode

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


class SignalRuntimeRunner:
    """Signal runtime coordinator for the effective pair catalog."""

    def __init__(
        self,
        catalog: SignalPairCatalog | None = None,
        worker_factory: Callable[[str, str], SignalRuntimeWorker] | None = None,
        worker_settings: SignalWorkerSettings | None = None,
        initial_pairs: list[SignalPair] | None = None,
    ) -> None:
        self.catalog = catalog or SignalPairCatalog()
        self.worker_factory = worker_factory or SignalRuntimeWorker
        self.worker_settings = worker_settings or SignalWorkerSettings()
        self._catalog_pairs_by_key: dict[str, SignalPair] = {
            pair.key: pair for pair in self.catalog.list_pairs()
        }
        self._initial_pairs = list(initial_pairs) if initial_pairs is not None else list(
            self._catalog_pairs_by_key.values()
        )
        self.redis_client: Any = None
        self.workers: list[SignalRuntimeWorker] = []
        self._workers_by_key: dict[str, SignalRuntimeWorker] = {}
        self._worker_tasks: dict[str, asyncio.Task[None]] = {}
        self._pairs_by_key: dict[str, SignalPair] = {}
        self._lifecycle_task: asyncio.Task[None] | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._state_store: SignalRuntimeStateStore | None = None

    def list_pairs(self) -> list[SignalPair]:
        if self._pairs_by_key:
            return list(self._pairs_by_key.values())
        return list(self._initial_pairs)

    def build_workers(self) -> list[SignalRuntimeWorker]:
        self.workers = [
            self._build_worker(pair)
            for pair in self.list_pairs()
            if pair.enabled
        ]
        return list(self.workers)

    def _build_worker(self, pair: SignalPair) -> SignalRuntimeWorker:
        parameters = inspect.signature(self.worker_factory).parameters
        kwargs: dict[str, Any] = {}
        if "settings" in parameters:
            kwargs["settings"] = self.worker_settings
        if "trigger_timeframe" in parameters:
            kwargs["trigger_timeframe"] = pair.trigger_timeframe or pair.timeframe
        if "trigger_mode" in parameters:
            kwargs["trigger_mode"] = pair.trigger_mode
        if "base_timeframe" in parameters:
            kwargs["base_timeframe"] = pair.base_timeframe
        if "required_context_profiles" in parameters:
            kwargs["required_context_profiles"] = list(pair.required_context_profiles)
        return self.worker_factory(pair.asset, pair.timeframe, **kwargs)

    async def connect(self, redis_client: Any) -> list[SignalRuntimeWorker]:
        self.redis_client = redis_client
        self._state_store = SignalRuntimeStateStore(redis_client)
        for pair in self._initial_pairs:
            self._pairs_by_key[pair.key] = pair
        workers = await self._start_pairs(self.list_pairs())
        return list(workers)

    async def start(self) -> None:
        if self.redis_client is None:
            raise RuntimeError("SignalRuntimeRunner.connect() must be called before start().")

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
        self.workers = []
        self._lifecycle_task = None
        self._supervisor_task = None

    async def _start_pairs(self, pairs: list[SignalPair]) -> list[SignalRuntimeWorker]:
        started_workers: list[SignalRuntimeWorker] = []
        for pair in pairs:
            started = await self._ensure_pair_started(pair)
            if started is not None:
                started_workers.append(started)
        self.workers = list(self._workers_by_key.values())
        return started_workers

    async def _ensure_pair_started(self, pair: SignalPair) -> SignalRuntimeWorker | None:
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
        self.workers = list(self._workers_by_key.values())
        return worker

    async def _stop_pair(
        self,
        pair_key: str,
        *,
        state: SignalPairState | None = None,
        reason: str | None = None,
        clear_status: bool = False,
    ) -> None:
        task = self._worker_tasks.pop(pair_key, None)
        worker = self._workers_by_key.pop(pair_key, None)
        pair = self._pairs_by_key.get(pair_key)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if pair is not None and self._state_store is not None:
            if clear_status:
                await self._state_store.delete(pair)
            elif state is not None:
                await self._state_store.update(
                    pair,
                    state=state,
                    last_error=None,
                    replace_last_error=True,
                    detail={"phase": "lifecycle", "reason": reason or state.value.lower()},
                )
        if clear_status:
            self._pairs_by_key.pop(pair_key, None)
        elif worker is None and pair is None:
            self._pairs_by_key.pop(pair_key, None)
        self.workers = list(self._workers_by_key.values())

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
                            consumer_namespace="signal",
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
                logger.warning("Signal lifecycle watcher timed out; retrying.")
                await asyncio.sleep(1)
            except Exception as exc:
                logger.warning("Signal lifecycle watcher failed: %s", exc, exc_info=True)
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
                        state=SignalPairState.STOPPED,
                        reason="timeframe_removed",
                        clear_status=True,
                    )
            for pair in desired_pairs.values():
                await self._ensure_pair_started(pair)
            return

        stop_state = (
            SignalPairState.PAUSED
            if event.desired_state == "PAUSED"
            else SignalPairState.STOPPED
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
                raise RuntimeError("Signal lifecycle watcher exited unexpectedly")
            for pair_key, task in list(self._worker_tasks.items()):
                if not task.done():
                    continue
                self._worker_tasks.pop(pair_key, None)
                worker = self._workers_by_key.pop(pair_key, None)
                self.workers = list(self._workers_by_key.values())
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error
                if worker is not None and pair_key not in self._pairs_by_key:
                    self._pairs_by_key.pop(pair_key, None)
            await asyncio.sleep(0.1)

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

    def _desired_pairs_for_event(self, event: AssetLifecycleEvent) -> list[SignalPair]:
        event_timeframes = set(self._event_timeframes(event))
        configured = [
            pair
            for pair in self._catalog_pairs_by_key.values()
            if pair.asset == event.symbol
            and (pair.trigger_timeframe or pair.timeframe) in event_timeframes
        ]
        desired_by_key = {pair.key: pair for pair in configured}
        for timeframe in event_timeframes:
            pair_key = f"{event.symbol}:{timeframe}"
            desired_by_key.setdefault(
                pair_key,
                SignalPair(
                    asset=event.symbol,
                    timeframe=timeframe,
                    trigger_timeframe=timeframe,
                    trigger_mode="on_bar_close",
                    base_timeframe=event.base_timeframe,
                    source="asset_manifest",
                ),
            )
        return list(desired_by_key.values())
