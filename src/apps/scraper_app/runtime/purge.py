"""The retention task: one purge pass per slot, through the ``scraper_purge`` role.

It runs only while the advisory lock is held and never ends on an error. The
collector's own pool cannot delete; this task owns a separate pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from apps.scraper_app.runtime.slots import Clock, Sleep, run_slot_loop
from apps.scraper_app.runtime.status import PurgeState
from apps.scraper_app.settings import RetentionSettings
from apps.scraper_app.storage.repository import (
    PURGE_COINGLASS,
    PURGE_TRADINGVIEW,
    PurgeRepository,
)
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)


def retention_days(settings: RetentionSettings) -> dict[str, int | None]:
    return {
        PURGE_TRADINGVIEW: settings.tradingview_days,
        PURGE_COINGLASS: settings.coinglass_days,
    }


class PurgeTask:
    def __init__(
        self,
        *,
        repository: PurgeRepository,
        settings: RetentionSettings,
        tradingview_ids: Sequence[str],
        coinglass_ids: Sequence[str],
        state: PurgeState,
        clock: Clock,
        sleep: Sleep = asyncio.sleep,
        can_write: Callable[[], bool] = lambda: True,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._state = state
        self._clock = clock
        self._sleep = sleep
        self._can_write = can_write
        if state.started_at is None:
            state.started_at = clock()
        self._targets: list[tuple[str, str, int]] = []
        if settings.tradingview_days is not None:
            self._targets += [
                (i, PURGE_TRADINGVIEW, settings.tradingview_days)
                for i in tradingview_ids
            ]
        if settings.coinglass_days is not None:
            self._targets += [
                (i, PURGE_COINGLASS, settings.coinglass_days) for i in coinglass_ids
            ]

    async def run(self) -> None:
        await run_slot_loop(
            slots=self._settings,
            clock=self._clock,
            sleep=self._sleep,
            can_write=self._can_write,
            run_pass=self.run_pass,
        )

    async def run_pass(self, trigger: str) -> None:
        try:
            await self._pass(trigger)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("purge pass crashed trigger=%s", trigger, exc_info=True)

    async def _pass(self, trigger: str) -> None:
        deleted: dict[str, int] = {}
        failures: list[str] = []
        first_error: BaseException | None = None
        for dataset_id, kind, days in self._targets:
            if not self._can_write():
                logger.error("advisory lock not held; purge pass abandoned")
                return
            try:
                result = await self._repository.purge_dataset(
                    dataset_id,
                    kind=kind,
                    days=days,
                    batch_rows=self._settings.batch_rows,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one dataset must not stop the pass
                failures.append(dataset_id)
                first_error = first_error or exc
                continue
            for table, count in result.deleted.items():
                deleted[table] = deleted.get(table, 0) + count
        now = self._clock()
        self._state.last_run_at = now
        self._state.deleted = deleted
        if failures:
            logger.warning(
                "purge pass failed trigger=%s datasets=%s deleted=%s",
                trigger,
                failures,
                deleted,
                exc_info=first_error,
            )
            return
        self._state.last_ok_at = now
        logger.info("purge pass finished trigger=%s deleted=%s", trigger, deleted)


__all__ = ["PurgeTask", "retention_days"]
