"""Runtime state and the readiness computation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from apps.scraper_app.domain.bars import expected_latest_closed_bar_open
from apps.scraper_app.domain.datasets import DatasetSpec
from apps.scraper_app.storage.repository import ReadRecord, ScraperRepository
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

READY = "ready"
DEGRADED = "degraded"
NOT_READY = "not_ready"

REASON_NEVER_SUCCEEDED = "never_succeeded"
REASON_STALE = "stale"
REASON_MISSING_LATEST_BAR = "missing_latest_bar"
REASON_RECENT_GAP = "recent_gap"
REASON_CLOCK_SKEW = "clock_skew"
REASON_COINGLASS_CATCHUP = "coinglass_catchup_pending"
REASON_PURGE_NOT_CONFIGURED = "purge_not_configured"
REASON_PURGE_FAILING = "purge_failing"
STORE_TIMEOUT = "store_timeout"
DATABASE_UNREACHABLE = "database_unreachable"

_LOG_INTERVAL_SECONDS = 60.0


class ReadinessReporter:
    """Throttled readiness logging: first failure loud, then one line a minute."""

    def __init__(
        self,
        *,
        interval_seconds: float = _LOG_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = interval_seconds
        self._monotonic = monotonic
        self._failing = False
        self._last_logged = 0.0
        self._suppressed = 0

    def failed(self, dataset_id: str, exc: BaseException, elapsed: float) -> None:
        now = self._monotonic()
        first = not self._failing
        if not first and now - self._last_logged < self._interval:
            self._suppressed += 1
            return
        suffix = "" if first else f" ({self._suppressed} similar suppressed)"
        message = (
            "readiness could not read the store: %s evaluating dataset=%s after %.1fs%s"
        )
        args = (type(exc).__name__, dataset_id or "-", elapsed, suffix)
        if first:
            logger.warning(message, *args, exc_info=exc)
        else:
            logger.warning(message, *args)
        self._failing = True
        self._last_logged = now
        self._suppressed = 0

    def recovered(self) -> None:
        if self._failing:
            logger.info("readiness recovered: the store is readable again")
            self._failing = False
            self._suppressed = 0


@dataclass(slots=True)
class PurgeState:
    """What the purge task publishes for readiness. Present only when configured."""

    enabled: bool
    configured: bool
    retention_days: dict[str, int | None]
    max_age_seconds: int
    started_at: datetime | None = None
    last_run_at: datetime | None = None
    last_ok_at: datetime | None = None
    deleted: dict[str, int] = field(default_factory=dict)

    def failing(self, now: datetime) -> bool:
        """No successful pass within the age limit (counted from startup)."""
        reference = self.last_ok_at or self.started_at
        if reference is None:
            return False
        return (now - reference).total_seconds() > self.max_age_seconds

    def payload(self) -> dict[str, Any]:
        def stamp(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat()

        return {
            "enabled": self.enabled,
            "last_run_at": stamp(self.last_run_at),
            "last_ok_at": stamp(self.last_ok_at),
            "deleted": dict(self.deleted),
            "retention": dict(self.retention_days),
        }


@dataclass(slots=True)
class RuntimeState:
    """Mutable facts the scheduler publishes for readiness."""

    startup_catchup_done: bool = False
    last_pass_finished_at: datetime | None = None
    # CoinGlass lane: off unless configured; its catch-up never gates readiness.
    coinglass_enabled: bool = False
    coinglass_catchup_done: bool = False
    coinglass_disabled: frozenset[str] = frozenset()
    purge: PurgeState | None = None


@dataclass(frozen=True, slots=True)
class CoinGlassReadiness:
    """What readiness needs to judge the CoinGlass datasets (reads table only)."""

    dataset_ids: tuple[str, ...]
    max_read_age_seconds: int


@dataclass(frozen=True, slots=True)
class DatasetStatus:
    dataset_id: str
    reasons: tuple[str, ...]
    last_error_code: str | None
    last_ok_read_at: datetime | None
    covered_to: datetime | None
    recent_gap_from: datetime | None = None
    clock_skew_seconds: float | None = None
    disabled: bool = False

    @property
    def degraded(self) -> bool:
        return bool(self.reasons)


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    status: str
    not_ready_reasons: tuple[str, ...] = ()
    datasets: tuple[DatasetStatus, ...] = field(default_factory=tuple)
    service_reasons: tuple[str, ...] = ()
    clock_skew_seconds: float | None = None
    purge: dict[str, Any] | None = None

    @property
    def http_status(self) -> int:
        return 503 if self.status == NOT_READY else 200

    def payload(self) -> dict[str, Any]:
        def stamp(value: datetime | None) -> str | None:
            return None if value is None else value.isoformat()

        purge = {} if self.purge is None else {"purge": self.purge}
        return {
            **purge,
            "status": self.status,
            "not_ready_reasons": list(self.not_ready_reasons),
            "service_reasons": list(self.service_reasons),
            "clock_skew_seconds": self.clock_skew_seconds,
            "degraded": [
                {
                    "dataset_id": d.dataset_id,
                    "reasons": list(d.reasons),
                    "last_error_code": d.last_error_code,
                }
                for d in self.datasets
                if d.degraded
            ],
            "datasets": {
                d.dataset_id: {
                    "last_ok_read_at": stamp(d.last_ok_read_at),
                    "covered_to": stamp(d.covered_to),
                    "recent_gap_from": stamp(d.recent_gap_from),
                    "last_error_code": d.last_error_code,
                    **({"disabled": True} if d.disabled else {}),
                }
                for d in self.datasets
            },
        }


async def _dataset_status(
    spec: DatasetSpec,
    repository: ScraperRepository,
    *,
    latest_ok: ReadRecord | None,
    latest: ReadRecord | None,
    first: datetime | None,
    now: datetime,
    max_read_age_seconds: int,
    latest_bar_grace_seconds: int,
    recent_gap_window_seconds: int,
) -> DatasetStatus:
    last_error = latest.error_code if latest is not None else None
    if latest_ok is None:
        return DatasetStatus(spec.id, (REASON_NEVER_SUCCEEDED,), last_error, None, None)
    reasons: list[str] = []
    recent_gap_from: datetime | None = None
    if (now - latest_ok.finished_at).total_seconds() > max_read_age_seconds:
        reasons.append(REASON_STALE)
    if spec.contiguous:
        # The slot runs shortly after the boundary and a pass takes time: judge
        # "latest closed bar" as of a moment slightly in the past.
        expected = expected_latest_closed_bar_open(
            now - timedelta(seconds=latest_bar_grace_seconds), spec.interval_seconds
        )
        if latest_ok.covered_to is None or latest_ok.covered_to < expected:
            reasons.append(REASON_MISSING_LATEST_BAR)
        window_start = now - timedelta(seconds=recent_gap_window_seconds)
        # Bounded to the window: readiness never scans the full history.
        run_start = await repository.contiguous_from(spec.id, not_before=window_start)
        if (
            run_start is not None
            and first is not None
            and run_start > first
            and run_start > window_start
        ):
            reasons.append(REASON_RECENT_GAP)
            recent_gap_from = run_start
    skew = (
        None
        if latest_ok.provider_time is None
        else (latest_ok.finished_at - latest_ok.provider_time).total_seconds()
    )
    return DatasetStatus(
        spec.id,
        tuple(reasons),
        last_error,
        latest_ok.finished_at,
        latest_ok.covered_to,
        recent_gap_from,
        skew,
    )


async def _coinglass_status(
    dataset_id: str,
    *,
    latest_ok: ReadRecord | None,
    latest: ReadRecord | None,
    now: datetime,
    max_read_age_seconds: int,
    disabled: frozenset[str],
) -> DatasetStatus:
    """Reads-table only: no bar queries, no gap query, no clock skew."""
    if dataset_id in disabled:
        return DatasetStatus(dataset_id, (), None, None, None, disabled=True)
    last_error = latest.error_code if latest is not None else None
    if latest_ok is None:
        return DatasetStatus(
            dataset_id, (REASON_NEVER_SUCCEEDED,), last_error, None, None
        )
    reasons = (
        (REASON_STALE,)
        if (now - latest_ok.finished_at).total_seconds() > max_read_age_seconds
        else ()
    )
    return DatasetStatus(
        dataset_id, reasons, last_error, latest_ok.finished_at, latest_ok.covered_to
    )


async def compute_readiness(
    *,
    specs: Sequence[DatasetSpec],
    repository: ScraperRepository,
    state: RuntimeState,
    lock_held: Callable[[], bool],
    clock: Callable[[], datetime],
    max_read_age_seconds: int,
    latest_bar_grace_seconds: int = 0,
    recent_gap_window_seconds: int = 172800,
    max_clock_skew_seconds: int = 120,
    probe_timeout_seconds: float | None = None,
    reporter: ReadinessReporter | None = None,
    coinglass: CoinGlassReadiness | None = None,
) -> ReadinessReport:
    not_ready: list[str] = []
    if not lock_held():
        not_ready.append("lock_not_held")
    if not state.startup_catchup_done:
        not_ready.append("startup_catchup_pending")

    datasets: list[DatasetStatus] = []
    evaluating = ""
    started = time.monotonic()
    try:
        now = clock()
        async with asyncio.timeout(probe_timeout_seconds):
            # Two statements for every dataset, then one window-bounded
            # contiguity query per contiguous dataset.
            wanted = [s.id for s in specs]
            if coinglass is not None:
                wanted += [
                    i
                    for i in coinglass.dataset_ids
                    if i not in state.coinglass_disabled
                ]
            evaluating = "*"
            reads = await repository.latest_reads(wanted)
            contiguous = [s.id for s in specs if s.contiguous]
            firsts = await repository.first_bar_opens(contiguous) if contiguous else {}
            for spec in specs:
                evaluating = spec.id
                latest_ok, latest = reads.get(spec.id, (None, None))
                datasets.append(
                    await _dataset_status(
                        spec,
                        repository,
                        latest_ok=latest_ok,
                        latest=latest,
                        first=firsts.get(spec.id),
                        now=now,
                        max_read_age_seconds=max_read_age_seconds,
                        latest_bar_grace_seconds=latest_bar_grace_seconds,
                        recent_gap_window_seconds=recent_gap_window_seconds,
                    )
                )
            if coinglass is not None:
                for dataset_id in coinglass.dataset_ids:
                    evaluating = dataset_id
                    latest_ok, latest = reads.get(dataset_id, (None, None))
                    datasets.append(
                        await _coinglass_status(
                            dataset_id,
                            latest_ok=latest_ok,
                            latest=latest,
                            now=now,
                            max_read_age_seconds=coinglass.max_read_age_seconds,
                            disabled=state.coinglass_disabled,
                        )
                    )
        if reporter is not None:
            reporter.recovered()
    except Exception as exc:  # noqa: BLE001 - any store failure means not ready
        # TimeoutError covers the whole-probe deadline and asyncpg's command timeout.
        not_ready.append(
            STORE_TIMEOUT if isinstance(exc, TimeoutError) else DATABASE_UNREACHABLE
        )
        if reporter is not None:
            reporter.failed(evaluating, exc, time.monotonic() - started)

    skews = [d.clock_skew_seconds for d in datasets if d.clock_skew_seconds is not None]
    worst_skew = max(skews, key=abs) if skews else None
    service_reasons: list[str] = []
    if worst_skew is not None and abs(worst_skew) > max_clock_skew_seconds:
        service_reasons.append(REASON_CLOCK_SKEW)
    if state.coinglass_enabled and not state.coinglass_catchup_done:
        service_reasons.append(REASON_COINGLASS_CATCHUP)
    purge = state.purge
    purge_payload: dict[str, Any] | None = None
    if purge is not None:
        purge_payload = purge.payload()
        if purge.enabled and not purge.configured:
            service_reasons.append(REASON_PURGE_NOT_CONFIGURED)
        elif purge.enabled and purge.failing(clock()):
            service_reasons.append(REASON_PURGE_FAILING)

    if not_ready:
        return ReadinessReport(
            NOT_READY,
            tuple(not_ready),
            tuple(datasets),
            tuple(service_reasons),
            worst_skew,
            purge_payload,
        )
    degraded = any(d.degraded for d in datasets) or bool(service_reasons)
    return ReadinessReport(
        DEGRADED if degraded else READY,
        (),
        tuple(datasets),
        tuple(service_reasons),
        worst_skew,
        purge_payload,
    )


class ReadinessService:
    """Single flight: concurrent probes share one computation (one connection).

    Callers wait for the shared computation at most ``wait_seconds``, never for
    the cancellation of a stuck query: cancelling an asyncpg query against a
    hung server waits on a cancel request without limit. On expiry the caller
    gets ``not_ready`` / ``store_timeout`` at once and the stuck task stays the
    single flight until it finishes by itself.
    """

    def __init__(
        self,
        compute: Callable[[], Awaitable[ReadinessReport]],
        *,
        wait_seconds: float | None = None,
    ) -> None:
        self._compute = compute
        self._wait_seconds = wait_seconds
        self._inflight: asyncio.Task[ReadinessReport] | None = None
        self._stuck_logged = False
        self.computations = 0

    async def __call__(self) -> ReadinessReport:
        task = self._inflight
        if task is None or task.done():
            self.computations += 1
            self._stuck_logged = False
            task = asyncio.ensure_future(self._compute())
            self._inflight = task
        # Waiting on the task through asyncio.wait neither cancels it when this
        # caller goes away nor waits for it after the deadline.
        done, _ = await asyncio.wait({task}, timeout=self._wait_seconds)
        if task in done:
            return task.result()
        if not self._stuck_logged:
            self._stuck_logged = True
            logger.warning(
                "readiness computation exceeded %.1fs; answering store_timeout "
                "until it finishes",
                self._wait_seconds,
            )
        return ReadinessReport(NOT_READY, (STORE_TIMEOUT,))


__all__ = [
    "DEGRADED",
    "NOT_READY",
    "READY",
    "CoinGlassReadiness",
    "DatasetStatus",
    "PurgeState",
    "ReadinessReport",
    "ReadinessReporter",
    "ReadinessService",
    "RuntimeState",
    "compute_readiness",
]
