"""One read of one dataset: size the request, fetch, gate, commit."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Protocol

from apps.scraper_app.adapters.tradingview.protocol import SeriesResult
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.bars import Bar, epoch_to_utc, validate_bars
from apps.scraper_app.domain.datasets import SIZING_MARGIN_BARS, DatasetSpec
from apps.scraper_app.domain.errors import ScraperError
from apps.scraper_app.settings import TradingViewSettings
from apps.scraper_app.storage.repository import ScraperRepository
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)


class SeriesClient(Protocol):
    async def fetch_series(
        self, request_symbol: str, resolution: str, n_bars: int
    ) -> SeriesResult: ...


@dataclass(frozen=True, slots=True)
class CollectOutcome:
    dataset_id: str
    ok: bool
    error_code: str | None = None
    provider_time: datetime | None = None
    covered_to: datetime | None = None
    gap_before: bool = False
    bars_written: int = 0


def request_size(
    spec: DatasetSpec,
    settings: TradingViewSettings,
    *,
    now: datetime,
    last_bar_open: datetime | None,
    last_covered_to: datetime | None,
) -> int:
    """Bars to ask for.

    With stored history the window starts at the older of the last covered bar
    and ``now - revision watch window``: the watch window is re-read every slot and
    the request reaches back over any outage.
    """
    if last_bar_open is None or last_covered_to is None:
        wanted = spec.initial_bars
    else:
        anchor = min(
            last_covered_to, now - timedelta(seconds=spec.revision_watch_seconds)
        )
        span = max((now - anchor).total_seconds(), 0.0)
        wanted = math.ceil(span / spec.interval_seconds) + SIZING_MARGIN_BARS
    return max(
        settings.min_bars_per_request, min(settings.max_bars_per_request, wanted)
    )


def drop_expired(bars: list[Bar], *, cutoff: datetime) -> list[Bar]:
    """Bars the purge would delete at once are not stored; the newest always is."""
    kept = [b for b in bars if b.bar_open >= cutoff]
    return kept or bars[-1:]


def count_holes(spec: DatasetSpec, bars: list[Bar]) -> int:
    if not spec.contiguous:
        return 0
    step = spec.interval_seconds
    return sum(
        max(int((b.bar_open - a.bar_open).total_seconds()) // step - 1, 0)
        for a, b in pairwise(bars)
    )


class Collector:
    """Reads a dataset and records the outcome; never raises on a failed read."""

    def __init__(
        self,
        *,
        client: SeriesClient,
        repository: ScraperRepository,
        settings: TradingViewSettings,
        clock: Callable[[], datetime],
        retention_days: int | None = None,
    ) -> None:
        self._retention_days = retention_days
        self._client = client
        self._repository = repository
        self._settings = settings
        self._clock = clock
        # Provider time minus local time, from the last good read.
        self._offset = timedelta(0)

    async def collect(self, spec: DatasetSpec, trigger: str) -> CollectOutcome:
        started_at = self._clock()
        provider_time: datetime | None = None
        try:
            last_ok = await self._repository.latest_ok_read(spec.id)
            last_bar_open = await self._repository.last_bar_open(spec.id)
        except Exception as exc:  # noqa: BLE001 - classified as a storage failure
            return await self._fail(
                spec, trigger, started_at, None, errors.STORAGE_ERROR, repr(exc)
            )

        try:
            n_bars = request_size(
                spec,
                self._settings,
                now=started_at + self._offset,
                last_bar_open=last_bar_open,
                last_covered_to=None if last_ok is None else last_ok.covered_to,
            )
            result = await self._client.fetch_series(
                spec.request_symbol, spec.resolution, n_bars
            )
            provider_time = epoch_to_utc(result.provider_time)
            gate = validate_bars(
                spec,
                pro_name=result.pro_name,
                provider_time=result.provider_time,
                raw_bars=result.bars,
            )
            bars = gate.bars
            holes = gate.holes
            seen = len(bars)
            if self._retention_days is not None:
                bars = drop_expired(
                    bars,
                    cutoff=started_at
                    + self._offset
                    - timedelta(days=self._retention_days),
                )
                holes = count_holes(spec, bars) if len(bars) != seen else holes
        except ScraperError as exc:
            return await self._fail(
                spec, trigger, started_at, provider_time, exc.code, exc.detail
            )
        except Exception as exc:  # noqa: BLE001 - never escape as an unrecorded crash
            return await self._fail(
                spec,
                trigger,
                started_at,
                provider_time,
                errors.PROTOCOL_ERROR,
                repr(exc),
            )

        # Catch-up first: a contiguous dataset must not skip over bars it never
        # stored. The read below writes the whole range in one transaction, so
        # no newer bar is visible before the older missing ones.
        gap_before = (
            spec.contiguous
            and last_bar_open is not None
            and bars[0].bar_open
            > last_bar_open + timedelta(seconds=spec.interval_seconds)
        )
        if gap_before:
            logger.error(
                "dataset=%s trigger=%s provider history does not reach back to the "
                "last stored bar (last stored %s, first returned %s)",
                spec.id,
                trigger,
                last_bar_open.isoformat(),  # type: ignore[union-attr]
                bars[0].bar_open.isoformat(),
                extra={"dataset_id": spec.id, "trigger": trigger},
            )
        try:
            outcome = await self._repository.commit_ok_read(
                spec,
                trigger=trigger,
                started_at=started_at,
                provider_time=provider_time,
                bars=bars,
                gap_before=gap_before,
                holes=holes,
                bars_seen=seen,
            )
        except Exception as exc:  # noqa: BLE001 - nothing was committed
            return await self._fail(
                spec,
                trigger,
                started_at,
                provider_time,
                errors.STORAGE_ERROR,
                repr(exc),
            )

        self._offset = provider_time - started_at
        return CollectOutcome(
            dataset_id=spec.id,
            ok=True,
            provider_time=provider_time,
            covered_to=bars[-1].bar_open,
            gap_before=gap_before,
            bars_written=outcome.bars_written,
        )

    async def _fail(
        self,
        spec: DatasetSpec,
        trigger: str,
        started_at: datetime,
        provider_time: datetime | None,
        code: str,
        detail: str,
    ) -> CollectOutcome:
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
                provider_time=provider_time,
            )
        except Exception:
            logger.exception(
                "could not record the failed read dataset=%s error_code=%s",
                spec.id,
                code,
            )
        return CollectOutcome(
            dataset_id=spec.id, ok=False, error_code=code, provider_time=provider_time
        )


__all__ = [
    "CollectOutcome",
    "Collector",
    "SeriesClient",
    "count_holes",
    "drop_expired",
    "request_size",
]
