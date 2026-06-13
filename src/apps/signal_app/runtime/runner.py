from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect
from typing import Any

from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.models import SignalPair
from apps.signal_app.runtime.worker import SignalRuntimeWorker
from apps.signal_app.settings import SignalWorkerSettings


class SignalRuntimeRunner:
    """Signal runtime coordinator for the effective pair catalog."""

    def __init__(
        self,
        catalog: SignalPairCatalog | None = None,
        worker_factory: Callable[[str, str], SignalRuntimeWorker] | None = None,
        worker_settings: SignalWorkerSettings | None = None,
    ) -> None:
        self.catalog = catalog or SignalPairCatalog()
        self.worker_factory = worker_factory or SignalRuntimeWorker
        self.worker_settings = worker_settings or SignalWorkerSettings()
        self.redis_client: Any = None
        self.workers: list[SignalRuntimeWorker] = []
        self._tasks: list[asyncio.Task[None]] = []

    def list_pairs(self) -> list[SignalPair]:
        return self.catalog.list_pairs()

    def build_workers(self) -> list[SignalRuntimeWorker]:
        self.workers = [
            self._build_worker(pair)
            for pair in self.list_pairs()
            if pair.enabled
        ]
        return list(self.workers)

    def _build_worker(self, pair: SignalPair) -> SignalRuntimeWorker:
        parameters = inspect.signature(self.worker_factory).parameters
        if "settings" in parameters:
            return self.worker_factory(
                pair.asset,
                pair.timeframe,
                settings=self.worker_settings,
            )
        return self.worker_factory(pair.asset, pair.timeframe)

    async def connect(self, redis_client: Any) -> list[SignalRuntimeWorker]:
        self.redis_client = redis_client
        workers = self.build_workers()
        for worker in workers:
            await worker.connect(redis_client)
        return list(workers)

    async def start(self) -> None:
        if self.redis_client is None:
            raise RuntimeError("SignalRuntimeRunner.connect() must be called before start().")

        workers = self.workers or self.build_workers()
        self._tasks = [asyncio.create_task(worker.start()) for worker in workers]
        try:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result
        finally:
            self._tasks = []

    async def stop(self) -> None:
        if not self._tasks:
            return

        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks = []
