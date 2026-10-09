"""The CoinGlass lane: one cycle per slot, one read per enabled dataset.

No retries: the next slot re-reads everything. The lane never ends on an error.
A database connection is held only while committing, never across a CDP await.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol

from apps.scraper_app.adapters.coinglass.client import CycleOutcome
from apps.scraper_app.adapters.coinglass.cookies import CookieStore
from apps.scraper_app.adapters.coinglass.helper import (
    HelperError,
    HelperRequest,
    HelperResult,
)
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError
from apps.scraper_app.domain.payloads import KIND_HEATMAP, PayloadSpec, gate_payload
from apps.scraper_app.runtime.slots import Clock, Sleep, run_slot_loop
from apps.scraper_app.runtime.status import RuntimeState
from apps.scraper_app.settings import CoinGlassSettings
from apps.scraper_app.storage.repository import ScraperRepository
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)


class CycleRunner(Protocol):
    async def run_cycle(
        self, requests: Sequence[HelperRequest], results: list[CycleOutcome | None]
    ) -> None: ...


class CoinGlassLane:
    def __init__(
        self,
        *,
        specs: Sequence[PayloadSpec],
        client: CycleRunner,
        repository: ScraperRepository,
        settings: CoinGlassSettings,
        state: RuntimeState,
        cookies: CookieStore,
        clock: Clock,
        sleep: Sleep = asyncio.sleep,
        can_write: Callable[[], bool] = lambda: True,
    ) -> None:
        self._specs = tuple(specs)
        self._client = client
        self._repository = repository
        self._settings = settings
        self._state = state
        self._cookies = cookies
        self._clock = clock
        self._sleep = sleep
        self._can_write = can_write
        self._announced_disabled = False
        state.coinglass_enabled = True
        self._refresh_disabled()

    def _refresh_disabled(self) -> list[PayloadSpec]:
        """Enabled specs; a login-only dataset without cookies is disabled."""
        has_cookies = bool(self._cookies.load())
        disabled = frozenset(
            s.id for s in self._specs if s.requires_login and not has_cookies
        )
        self._state.coinglass_disabled = disabled
        if disabled and not self._announced_disabled:
            logger.info(
                "coinglass datasets disabled until cookies are present: %s",
                sorted(disabled),
            )
            self._announced_disabled = True
        return [s for s in self._specs if s.id not in disabled]

    async def run(self) -> None:
        await run_slot_loop(
            slots=self._settings,
            clock=self._clock,
            sleep=self._sleep,
            can_write=self._can_write,
            run_pass=self.run_pass,
            on_first_pass=self._first_pass_done,
        )

    def _first_pass_done(self) -> None:
        self._state.coinglass_catchup_done = True

    async def run_pass(self, trigger: str) -> None:
        try:
            await self._pass(trigger)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("coinglass pass crashed trigger=%s", trigger)

    async def _pass(self, trigger: str) -> None:
        enabled = self._refresh_disabled()
        started_at = self._clock()
        logger.info(
            "coinglass pass starting trigger=%s datasets=%d", trigger, len(enabled)
        )
        if not enabled:
            return
        results, attempts = await self._cycle(enabled)
        ok = 0
        for spec, outcome in zip(enabled, results, strict=True):
            if not self._can_write():
                logger.error("advisory lock not held; coinglass pass abandoned")
                return
            if await self._record(spec, trigger, started_at, outcome, attempts):
                ok += 1
        logger.info(
            "coinglass pass finished trigger=%s ok=%d failed=%d",
            trigger,
            ok,
            len(enabled) - ok,
        )

    async def _cycle(
        self, enabled: Sequence[PayloadSpec]
    ) -> tuple[list[CycleOutcome], int]:
        """Run the cycle; one more attempt while it fails before any helper call.

        Returns the final attempt's outcomes and the number of attempts made.
        """
        s = self._settings
        attempts = 0
        while True:
            attempts += 1
            results, failure, pre_helper = await self._attempt(enabled)
            if not (pre_helper and attempts <= s.cycle_retries and self._can_write()):
                return results, attempts
            logger.warning(
                "coinglass cycle failed before the first helper call (%s); "
                "retrying in %gs (attempt %d of %d)",
                failure.code if failure else "unknown",
                s.cycle_retry_delay_seconds,
                attempts + 1,
                s.cycle_retries + 1,
            )
            await self._sleep(s.cycle_retry_delay_seconds)

    async def _attempt(
        self, enabled: Sequence[PayloadSpec]
    ) -> tuple[list[CycleOutcome], ScraperError | None, bool]:
        results: list[CycleOutcome | None] = [None] * len(enabled)
        requests = [HelperRequest.for_spec(s) for s in enabled]
        failure: ScraperError | None = None
        pre_helper = False
        deadline = asyncio.timeout(self._settings.cycle_deadline_seconds)
        try:
            async with deadline:
                await self._client.run_cycle(requests, results)
        except asyncio.CancelledError:
            raise
        except ScraperError as exc:
            failure = exc
            pre_helper = all(r is None for r in results)
        except TimeoutError:
            pass  # the cycle deadline (checked below)
        except Exception as exc:  # noqa: BLE001 - one error code for the whole cycle
            failure = ScraperError(errors.ENGINE_ERROR, type(exc).__name__)
            pre_helper = all(r is None for r in results)
        if failure is None and deadline.expired():
            failure = ScraperError(
                errors.CYCLE_DEADLINE,
                f"cycle exceeded {self._settings.cycle_deadline_seconds:g}s",
            )
        if failure is None and None not in results:
            return [r for r in results if r is not None], None, False
        fallback = failure or ScraperError(errors.ENGINE_ERROR, "no result")
        return [fallback if r is None else r for r in results], failure, pre_helper

    async def _record(
        self,
        spec: PayloadSpec,
        trigger: str,
        started_at: datetime,
        outcome: CycleOutcome,
        attempts: int,
    ) -> bool:
        meta: dict[str, Any] = {"attempts": attempts}
        try:
            if isinstance(outcome, ScraperError):
                if isinstance(outcome, HelperError):
                    meta = {**outcome.meta, "attempts": attempts}
                raise outcome
            meta = {**outcome.meta(), "attempts": attempts}
            return await self._commit(spec, trigger, started_at, outcome, meta)
        except ScraperError as exc:
            await self._fail(spec, trigger, started_at, exc.code, exc.detail, meta)
            return False

    async def _commit(
        self,
        spec: PayloadSpec,
        trigger: str,
        started_at: datetime,
        result: HelperResult,
        meta: dict[str, Any],
    ) -> bool:
        s = self._settings
        accepted = gate_payload(
            spec,
            result.text,
            returned_at=result.returned_at,
            max_payload_bytes=s.max_payload_bytes,
            max_age_seconds=s.max_provider_age_seconds,
        )
        try:
            gap_before = await self._gap_before(spec, accepted.covered_from)
            await self._repository.commit_ok_payload(
                spec.id,
                trigger=trigger,
                started_at=started_at,
                accepted=accepted,
                gap_before=gap_before,
                meta=meta,
            )
        except Exception as exc:
            raise ScraperError(errors.STORAGE_ERROR, repr(exc)) from exc
        return True

    async def _gap_before(self, spec: PayloadSpec, first_candle: datetime) -> bool:
        if spec.kind != KIND_HEATMAP or spec.expect is None:
            return False
        previous = await self._repository.latest_ok_read(spec.id)
        if previous is None or previous.covered_to is None:
            return False
        step = timedelta(seconds=spec.expect.interval_seconds)
        return first_candle > previous.covered_to + step

    async def _fail(
        self,
        spec: PayloadSpec,
        trigger: str,
        started_at: datetime,
        code: str,
        detail: str,
        meta: dict[str, Any] | None,
    ) -> None:
        logger.warning(
            "read failed dataset=%s trigger=%s error_code=%s detail=%s",
            spec.id,
            trigger,
            code,
            detail[:200],
            extra={"dataset_id": spec.id, "trigger": trigger, "error_code": code},
        )
        try:
            await self._repository.record_failed_read(
                spec.id,
                trigger=trigger,
                started_at=started_at,
                error_code=code,
                error_detail=detail,
                meta=meta,
            )
        except Exception:
            logger.exception(
                "could not record the failed read dataset=%s error_code=%s",
                spec.id,
                code,
            )


__all__ = ["CoinGlassLane", "CycleRunner"]
