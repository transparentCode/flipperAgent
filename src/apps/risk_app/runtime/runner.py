"""Runtime orchestration for risk_app."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from libs.common.asset_manifest import ASSET_LIFECYCLE_STREAM, AssetLifecycleEvent
from libs.common.enums import SystemComponent
from libs.common.lifecycle_dedup import mark_lifecycle_event_processed
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import ensure_consumer_group
from libs.contracts.serialization import valkey_decode
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)

SuperviseConsumerFn = Callable[[str, Callable[[], Any], Any, int], Awaitable[None]]
PersistStateLoopFn = Callable[[AccountState, PositionTracker, int], Awaitable[None]]


async def persist_state_loop(
    account: AccountState,
    positions: PositionTracker,
    interval_seconds: int = 60,
) -> None:
    """Periodically persist account and position state to TimescaleDB."""
    from libs.common.db.pool_manager import DBPoolManager

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            db_pool = DBPoolManager.get_writer_pool()
            await account.update_unrealized(positions.all_positions())
            await account.save_snapshot(
                db_pool,
                open_position_count=positions.get_position_count(),
            )
            await positions.save_positions(db_pool)
            logger.debug("Persisted account and position state to DB")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to persist state to DB")


async def supervise_consumer(
    label: str,
    build_consumer: Callable[[], Any],
    redis_client: Any,
    restart_delay_seconds: int = 5,
) -> None:
    """Restart a long-running consumer when it exits unexpectedly."""
    while True:
        consumer = build_consumer()
        await consumer.connect(redis_client)
        try:
            await consumer.start()
            logger.error(
                "%s exited its consumer loop unexpectedly; restarting in %ss",
                label,
                restart_delay_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "%s crashed; restarting in %ss",
                label,
                restart_delay_seconds,
            )
        await asyncio.sleep(restart_delay_seconds)


class RiskRuntimeRunner:
    """Coordinates risk workers, fill listeners, and persistence tasks."""

    def __init__(
        self,
        *,
        asset_map: dict[str, list[str]],
        redis_client: Any,
        risk_engine: Any,
        signal_aggregator: Any,
        account: AccountState,
        positions: PositionTracker,
        risk_config: dict[str, Any],
        risk_worker_factory: Callable[..., Any],
        fill_listener_factory: Callable[..., Any],
        restart_delay_seconds: int,
        fill_listener_assets: set[str] | None = None,
        persistence_interval_seconds: int = 60,
        enable_lifecycle: bool = True,
        supervise_consumer_fn: SuperviseConsumerFn = supervise_consumer,
        persistence_loop_fn: PersistStateLoopFn = persist_state_loop,
    ) -> None:
        self.asset_map = asset_map
        self.redis_client = redis_client
        self.risk_engine = risk_engine
        self.signal_aggregator = signal_aggregator
        self.account = account
        self.positions = positions
        self.risk_config = risk_config
        self.risk_worker_factory = risk_worker_factory
        self.fill_listener_factory = fill_listener_factory
        self.restart_delay_seconds = restart_delay_seconds
        self.persistence_interval_seconds = persistence_interval_seconds
        self.enable_lifecycle = enable_lifecycle
        self.supervise_consumer_fn = supervise_consumer_fn
        self.persistence_loop_fn = persistence_loop_fn
        self._worker_timeframes: dict[str, list[str]] = {
            asset: list(timeframes) for asset, timeframes in asset_map.items()
        }
        self._fill_listener_assets: set[str] = set(fill_listener_assets or set(asset_map))
        self._risk_worker_tasks: dict[str, asyncio.Task[Any]] = {}
        self._fill_listener_tasks: dict[str, asyncio.Task[Any]] = {}
        self._persistence_task: asyncio.Task[Any] | None = None
        self._lifecycle_task: asyncio.Task[Any] | None = None
        self._supervisor_task: asyncio.Task[Any] | None = None
        self.lifecycle_group_name = str(risk_config.get("lifecycle_group_name", "risk_app_group"))
        self.lifecycle_consumer_name = str(
            risk_config.get("lifecycle_consumer_name", "risk_app_lifecycle"),
        )
        self.lifecycle_block_ms = int(risk_config.get("lifecycle_block_ms", 1000))

    async def run(self) -> None:
        """Start supervised risk workers, fill listeners, and state persistence."""
        tasks: list[asyncio.Task[Any]] = []
        try:
            self._persistence_task = asyncio.create_task(
                self.persistence_loop_fn(
                    self.account,
                    self.positions,
                    self.persistence_interval_seconds,
                ),
            )
            tasks.append(self._persistence_task)

            for asset, timeframes in self._worker_timeframes.items():
                await self._ensure_risk_worker_started(asset, timeframes)
            for asset in self._fill_listener_assets:
                await self._ensure_fill_listener_started(asset)

            if self.enable_lifecycle:
                await ensure_consumer_group(
                    self.redis_client,
                    ASSET_LIFECYCLE_STREAM,
                    self.lifecycle_group_name,
                    start_id="$",
                )
                self._lifecycle_task = asyncio.create_task(self._watch_lifecycle())
            self._supervisor_task = asyncio.create_task(self._supervise())
            tasks.extend(
                task
                for task in [self._lifecycle_task, self._supervisor_task]
                if task is not None
            )

            logger.info(
                "Spawned %s risk workers and %s fill listeners",
                len(self._risk_worker_tasks),
                len(self._fill_listener_tasks),
            )
            await asyncio.gather(*tasks)
        except BaseException:
            for task in self._managed_tasks(tasks):
                task.cancel()
            managed_tasks = self._managed_tasks(tasks)
            if managed_tasks:
                await asyncio.gather(*managed_tasks, return_exceptions=True)
            raise

    async def _ensure_risk_worker_started(self, asset: str, timeframes: list[str]) -> None:
        existing = self._worker_timeframes.get(asset)
        if asset in self._risk_worker_tasks and existing == list(timeframes):
            return
        if asset in self._risk_worker_tasks and existing != list(timeframes):
            await self._stop_risk_worker(asset)
        self._worker_timeframes[asset] = list(timeframes)
        self._risk_worker_tasks[asset] = asyncio.create_task(
            self.supervise_consumer_fn(
                label=f"RiskWorker[{asset}]",
                build_consumer=lambda asset=asset, timeframes=list(timeframes): self.risk_worker_factory(
                    asset=asset,
                    timeframes=timeframes,
                    risk_engine=self.risk_engine,
                    signal_aggregator=self.signal_aggregator,
                    account=self.account,
                    positions=self.positions,
                    risk_config=self.risk_config,
                ),
                redis_client=self.redis_client,
                restart_delay_seconds=self.restart_delay_seconds,
            ),
        )

    async def _ensure_fill_listener_started(self, asset: str) -> None:
        if asset in self._fill_listener_tasks:
            return
        self._fill_listener_assets.add(asset)
        self._fill_listener_tasks[asset] = asyncio.create_task(
            self.supervise_consumer_fn(
                label=f"FillListener[{asset}]",
                build_consumer=lambda asset=asset: self.fill_listener_factory(
                    asset=asset,
                    account=self.account,
                    positions=self.positions,
                ),
                redis_client=self.redis_client,
                restart_delay_seconds=self.restart_delay_seconds,
            ),
        )

    async def _stop_risk_worker(self, asset: str) -> None:
        task = self._risk_worker_tasks.pop(asset, None)
        self._worker_timeframes.pop(asset, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _stop_fill_listener(self, asset: str) -> None:
        task = self._fill_listener_tasks.pop(asset, None)
        self._fill_listener_assets.discard(asset)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _watch_lifecycle(self) -> None:
        streams = {ASSET_LIFECYCLE_STREAM: ">"}
        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.lifecycle_group_name,
                    self.lifecycle_consumer_name,
                    streams,
                    count=25,
                    block=self.lifecycle_block_ms,
                )
                if not response:
                    continue
                for _stream_name, messages in response:
                    for message_id, payload in messages:
                        event = valkey_decode(payload, AssetLifecycleEvent)
                        if not await mark_lifecycle_event_processed(
                            self.redis_client,
                            consumer_namespace="risk",
                            event_id=event.event_id,
                        ):
                            await self.redis_client.xack(
                                ASSET_LIFECYCLE_STREAM,
                                self.lifecycle_group_name,
                                message_id,
                            )
                            continue
                        await self._apply_lifecycle_event(event)
                        await self.redis_client.xack(
                            ASSET_LIFECYCLE_STREAM,
                            self.lifecycle_group_name,
                            message_id,
                        )
            except asyncio.CancelledError:
                raise
            except ValkeyTimeoutError:
                logger.warning("Risk lifecycle watcher timed out; retrying.")
                await asyncio.sleep(1)
            except Exception as exc:
                logger.warning("Risk lifecycle watcher failed: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def _apply_lifecycle_event(self, event: AssetLifecycleEvent) -> None:
        timeframes = self._event_timeframes(event)
        asset = event.symbol

        if event.desired_state == "LIVE" and event.enabled:
            await self._ensure_fill_listener_started(asset)
            await self._ensure_risk_worker_started(asset, timeframes)
            return

        await self._stop_risk_worker(asset)

        if event.desired_state == "REMOVING" and self.positions.get_asset_exposure(asset) <= 0:
            await self._stop_fill_listener(asset)

    async def _supervise(self) -> None:
        while True:
            if self._persistence_task is not None and self._persistence_task.done():
                if self._persistence_task.cancelled():
                    raise asyncio.CancelledError
                error = self._persistence_task.exception()
                if error is not None:
                    raise error
                raise RuntimeError("Risk persistence loop exited unexpectedly")
            if self._lifecycle_task is not None and self._lifecycle_task.done():
                if self._lifecycle_task.cancelled():
                    raise asyncio.CancelledError
                error = self._lifecycle_task.exception()
                if error is not None:
                    raise error
                raise RuntimeError("Risk lifecycle watcher exited unexpectedly")
            for task_map_name, task_map in (
                ("risk worker", self._risk_worker_tasks),
                ("fill listener", self._fill_listener_tasks),
            ):
                for asset, task in list(task_map.items()):
                    if not task.done():
                        continue
                    task_map.pop(asset, None)
                    if task.cancelled():
                        continue
                    error = task.exception()
                    if error is not None:
                        raise error
                    raise RuntimeError(f"Risk {task_map_name} for {asset} exited unexpectedly")
            await asyncio.sleep(0.1)

    def _managed_tasks(self, initial_tasks: list[asyncio.Task[Any]]) -> list[asyncio.Task[Any]]:
        tasks = list(initial_tasks)
        tasks.extend(self._risk_worker_tasks.values())
        tasks.extend(self._fill_listener_tasks.values())
        return list(dict.fromkeys(task for task in tasks if task is not None))

    @staticmethod
    def _event_timeframes(event: AssetLifecycleEvent) -> list[str]:
        timeframes = list(event.publish_timeframes or [])
        if not timeframes:
            timeframes = [event.base_timeframe]
        return [timeframe for timeframe in timeframes if timeframe]
