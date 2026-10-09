"""Wall-clock slots, catch-up, and the single serial lane.

Slots are recomputed from the clock on every loop and sleeps never accumulate,
so a laptop sleep or a slow pass cannot shift the schedule. A pass is a
sequential walk over the catalog; one dataset failing never stops the rest.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Protocol

from apps.scraper_app.domain.bars import expected_latest_closed_bar_open
from apps.scraper_app.domain.datasets import DatasetSpec
from apps.scraper_app.runtime.collector import CollectOutcome
from apps.scraper_app.runtime.slots import (
    Clock,
    Sleep,
    next_slot_after,
    run_slot_loop,
    slot_at_or_before,
)
from apps.scraper_app.runtime.status import RuntimeState
from apps.scraper_app.settings import ScheduleSettings, TradingViewSettings
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)


class DatasetCollector(Protocol):
    async def collect(self, spec: DatasetSpec, trigger: str) -> CollectOutcome: ...


class Scheduler:
    def __init__(
        self,
        *,
        specs: Sequence[DatasetSpec],
        collector: DatasetCollector,
        tradingview: TradingViewSettings,
        schedule: ScheduleSettings,
        state: RuntimeState,
        clock: Clock,
        sleep: Sleep = asyncio.sleep,
        can_write: Callable[[], bool] = lambda: True,
    ) -> None:
        self._specs = tuple(specs)
        self._collector = collector
        self._tv = tradingview
        self._schedule = schedule
        self._state = state
        self._clock = clock
        self._sleep = sleep
        self._can_write = can_write

    async def run(self) -> None:
        await run_slot_loop(
            slots=self._schedule,
            clock=self._clock,
            sleep=self._sleep,
            can_write=self._can_write,
            run_pass=self.run_pass,
            on_first_pass=self._first_pass_done,
        )

    def _first_pass_done(self) -> None:
        self._state.startup_catchup_done = True

    async def run_pass(self, trigger: str) -> None:
        logger.info(
            "collection pass starting trigger=%s datasets=%d", trigger, len(self._specs)
        )
        ok = failed = 0
        for index, spec in enumerate(self._specs):
            if not self._can_write():
                logger.error(
                    "advisory lock not held; pass abandoned trigger=%s after %d ok, %d failed",
                    trigger,
                    ok,
                    failed,
                )
                return
            if index:
                await self._sleep(self._tv.request_spacing_seconds)
            try:
                outcome = await self._run_dataset(spec, trigger)
                if outcome is not None and outcome.ok:
                    ok += 1
                else:
                    failed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                failed += 1
                logger.exception(
                    "dataset pass crashed dataset=%s trigger=%s",
                    spec.id,
                    trigger,
                    extra={"dataset_id": spec.id, "trigger": trigger},
                )
        self._state.last_pass_finished_at = self._clock()
        logger.info(
            "collection pass finished trigger=%s ok=%d failed=%d", trigger, ok, failed
        )

    async def _run_dataset(self, spec: DatasetSpec, trigger: str) -> CollectOutcome:
        outcome = await self._attempt_with_retries(spec, trigger)
        if not outcome.ok or not spec.contiguous:
            return outcome  # funding-style datasets legitimately skip hours
        for _ in range(self._schedule.late_bar_retries):
            if not self._is_late(spec, outcome) or not self._can_write():
                return outcome
            await self._sleep(self._schedule.late_bar_retry_seconds)
            retry = await self._collector.collect(spec, "late_bar")
            if retry.ok:
                outcome = retry
        return outcome

    async def _attempt_with_retries(
        self, spec: DatasetSpec, trigger: str
    ) -> CollectOutcome:
        outcome = await self._collector.collect(spec, trigger)
        for delay in self._tv.retry_backoff_seconds[
            : self._tv.max_attempts_per_slot - 1
        ]:
            if outcome.ok or not self._can_write():
                break
            await self._sleep(delay)
            outcome = await self._collector.collect(spec, trigger)
        return outcome

    @staticmethod
    def _is_late(spec: DatasetSpec, outcome: CollectOutcome) -> bool:
        if outcome.provider_time is None or outcome.covered_to is None:
            return False
        expected = expected_latest_closed_bar_open(
            outcome.provider_time, spec.interval_seconds
        )
        return outcome.covered_to < expected


__all__ = ["DatasetCollector", "Scheduler", "next_slot_after", "slot_at_or_before"]
