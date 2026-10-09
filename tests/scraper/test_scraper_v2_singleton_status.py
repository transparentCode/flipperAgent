"""Advisory lock behaviour and readiness states."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import pytest
from scraper_v2_support import FakeClock, make_bar, make_spec, utc

from apps.scraper_app.http_api.app import create_app
from apps.scraper_app.runtime.singleton import ADVISORY_LOCK_KEY, AdvisoryLock
from apps.scraper_app.runtime.status import (
    ReadinessReporter,
    ReadinessService,
    RuntimeState,
    compute_readiness,
)
from apps.scraper_app.storage.repository import InMemoryScraperRepository


class _Server:
    def __init__(self) -> None:
        self.holder: object | None = None
        self.keys: list[int] = []


class _Conn:
    def __init__(self, server: _Server) -> None:
        self.server = server
        self.closed = False
        self.dead = False

    async def fetchval(self, query, *args):
        if self.dead:
            raise ConnectionError("gone")
        if "pg_try_advisory_lock" in query:
            self.server.keys.append(args[0])
            if self.server.holder in (None, self):
                self.server.holder = self
                return True
            return False
        return 1

    async def close(self):
        self.closed = True
        if self.server.holder is self:
            self.server.holder = None

    def is_closed(self):
        return self.closed


def _lock(server, conns=None, **kw):
    async def connect():
        c = _Conn(server)
        if conns is not None:
            conns.append(c)
        return c

    async def nosleep(_):
        return None

    return AdvisoryLock(connect, sleep=nosleep, **kw)


@pytest.mark.asyncio
async def test_second_instance_cannot_take_the_lock_until_the_first_releases() -> None:
    server = _Server()
    first, second = _lock(server), _lock(server)
    assert await first.try_acquire() and first.held
    assert not await second.try_acquire() and not second.held
    assert server.keys == [ADVISORY_LOCK_KEY, ADVISORY_LOCK_KEY]
    await first.release()
    assert not first.held
    assert await second.try_acquire()


@pytest.mark.asyncio
async def test_lost_connection_clears_held_and_supervise_reacquires() -> None:
    server, conns = _Server(), []
    lock = _lock(server, conns)
    assert await lock.try_acquire()
    conns[0].dead = True
    assert not await lock.check()
    assert not lock.held

    class _Done(Exception):
        pass

    ticks = 0

    async def sleep(_):
        nonlocal ticks
        ticks += 1
        if ticks > 3:
            raise _Done

    lock._sleep = sleep
    server.holder = None
    with pytest.raises(_Done):
        await lock.supervise()
    assert lock.held


@pytest.mark.asyncio
async def test_unreachable_database_means_not_held() -> None:
    async def connect():
        raise OSError("down")

    lock = AdvisoryLock(connect)
    assert not await lock.try_acquire()


# --- readiness ------------------------------------------------------------

SPEC = make_spec(finality_horizon_seconds=0)
NOW = utc(2026, 10, 9, 10, 20)


async def _report(repo, *, lock=True, done=True, now=NOW, specs=(SPEC,)):
    state = RuntimeState(startup_catchup_done=done)
    return await compute_readiness(
        specs=list(specs),
        repository=repo,
        state=state,
        lock_held=lambda: lock,
        clock=lambda: now,
        max_read_age_seconds=7800,
    )


def _repo(clock_time=NOW):
    clock = FakeClock(clock_time)
    return clock, InMemoryScraperRepository({SPEC.id: SPEC}, clock=clock)


async def _ok(repo, last_open, *, gap=False, provider=NOW):
    await repo.commit_ok_read(
        SPEC,
        trigger="schedule",
        started_at=NOW,
        provider_time=provider,
        bars=[make_bar(last_open - timedelta(hours=1), 1), make_bar(last_open, 2)],
        gap_before=gap,
    )


@pytest.mark.asyncio
async def test_ready_when_latest_bar_covered_and_fresh() -> None:
    _, repo = _repo()
    await _ok(repo, utc(2026, 10, 9, 9))
    report = await _report(repo)
    assert report.status == "ready" and report.http_status == 200
    assert (
        report.payload()["datasets"][SPEC.id]["covered_to"]
        == "2026-10-09T09:00:00+00:00"
    )


@pytest.mark.asyncio
async def test_not_ready_without_lock_startup_or_database() -> None:
    _, repo = _repo()
    await _ok(repo, utc(2026, 10, 9, 9))
    assert (await _report(repo, lock=False)).status == "not_ready"
    pending = await _report(repo, done=False)
    assert pending.status == "not_ready" and pending.http_status == 503

    class Broken(InMemoryScraperRepository):
        async def latest_ok_read(self, dataset_id):
            raise OSError("db down")

    broken = Broken({SPEC.id: SPEC}, clock=FakeClock(NOW))
    report = await _report(broken)
    assert report.status == "not_ready"
    assert "database_unreachable" in report.not_ready_reasons


async def _history(repo, opens, *, provider=NOW):
    await repo.commit_ok_read(
        SPEC,
        trigger="schedule",
        started_at=NOW,
        provider_time=provider,
        bars=[make_bar(o, i) for i, o in enumerate(opens)],
        gap_before=False,
    )


def _hours(first, count, skip=()):
    return [first + timedelta(hours=h) for h in range(count) if h not in skip]


@pytest.mark.asyncio
async def test_degraded_reasons_are_listed_per_dataset() -> None:
    clock, repo = _repo()
    never = await _report(repo)
    assert never.status == "degraded"
    assert never.payload()["degraded"][0] == {
        "dataset_id": SPEC.id,
        "reasons": ["never_succeeded"],
        "last_error_code": None,
    }

    await _ok(repo, utc(2026, 10, 9, 7))  # misses 09:00
    await repo.record_failed_read(
        SPEC.id,
        trigger="schedule",
        started_at=NOW,
        error_code="timeout",
        error_detail="",
    )
    clock.now += timedelta(seconds=1)
    report = await _report(repo, now=NOW + timedelta(hours=3))
    (entry,) = report.payload()["degraded"]
    assert set(entry["reasons"]) == {"stale", "missing_latest_bar"}
    assert entry["last_error_code"] == "timeout"
    assert report.http_status == 200


@pytest.mark.asyncio
async def test_latest_bar_grace_absorbs_the_boundary_window() -> None:
    _, repo = _repo()
    await _ok(repo, utc(2026, 10, 9, 8))  # 09:00 bar not collected yet
    just_after = utc(2026, 10, 9, 10, 0, 40)
    strict = await _report(repo, now=just_after)
    assert "missing_latest_bar" in strict.payload()["degraded"][0]["reasons"]
    graced = await compute_readiness(
        specs=[SPEC],
        repository=repo,
        state=RuntimeState(startup_catchup_done=True),
        lock_held=lambda: True,
        clock=lambda: just_after,
        max_read_age_seconds=7800,
        latest_bar_grace_seconds=300,
    )
    assert graced.status == "ready"


@pytest.mark.asyncio
async def test_recent_hole_degrades_but_a_deep_historical_hole_does_not() -> None:
    now = utc(2026, 10, 9, 10, 20)
    # hole 3 hours ago, older bars exist: contiguous run starts inside the window
    _, repo = _repo()
    await _history(repo, _hours(utc(2026, 10, 8, 0), 34, skip={20}))
    recent = await _report(repo, now=now)
    (entry,) = recent.payload()["degraded"]
    assert entry["reasons"] == ["recent_gap"]
    assert recent.payload()["datasets"][SPEC.id]["recent_gap_from"] == (
        "2026-10-08T21:00:00+00:00"
    )

    # the same shape of hole, but 6 days back: only history is affected
    _, deep = _repo()
    await _history(deep, _hours(utc(2026, 10, 3, 0), 154, skip={10}))
    ok = await _report(deep, now=now)
    assert ok.status == "ready"
    assert ok.payload()["datasets"][SPEC.id]["recent_gap_from"] is None


@pytest.mark.asyncio
async def test_clock_skew_is_reported_and_degrades_past_the_limit() -> None:
    clock, repo = _repo()
    await _ok(repo, utc(2026, 10, 9, 9), provider=NOW + timedelta(seconds=300))
    report = await _report(repo)
    assert report.status == "degraded"
    assert report.service_reasons == ("clock_skew",)
    assert report.payload()["clock_skew_seconds"] == -300.0
    del clock

    _, fine = _repo()
    await _ok(fine, utc(2026, 10, 9, 9), provider=NOW - timedelta(seconds=2))
    assert (await _report(fine)).payload()["clock_skew_seconds"] == 2.0
    assert (await _report(fine)).status == "ready"


@pytest.mark.asyncio
async def test_non_contiguous_dataset_is_not_degraded_by_a_skipped_hour() -> None:
    funding = make_spec(id="fr", contiguous=False, finality_horizon_seconds=0)
    clock = FakeClock(NOW)
    repo = InMemoryScraperRepository({funding.id: funding}, clock=clock)
    await repo.commit_ok_read(
        funding,
        trigger="schedule",
        started_at=NOW,
        provider_time=NOW,
        bars=[make_bar(utc(2026, 10, 9, 5), 1)],
        gap_before=False,
    )
    assert (await _report(repo, specs=(funding,))).status == "ready"


def test_http_routes() -> None:
    from fastapi.testclient import TestClient

    from apps.scraper_app.runtime.status import ReadinessReport

    async def not_ready():
        return ReadinessReport("not_ready", ("lock_not_held",))

    async def degraded():
        return ReadinessReport("degraded")

    with TestClient(create_app(readiness=not_ready)) as client:
        assert client.get("/health/live").json() == {"status": "live"}
        response = client.get("/health/ready")
        assert response.status_code == 503 and response.json()["status"] == "not_ready"
        assert client.get("/other").status_code == 404
    with TestClient(create_app(readiness=degraded)) as client:
        assert client.get("/health/ready").status_code == 200
    with TestClient(create_app()) as client:
        assert client.get("/health/ready").status_code == 503


# --- single flight, deadline, throttled logging ------------------------------


@pytest.mark.asyncio
async def test_concurrent_probes_share_one_computation() -> None:
    gate = asyncio.Event()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        await gate.wait()
        return ReadinessReport("ready")

    from apps.scraper_app.runtime.status import ReadinessReport

    service = ReadinessService(compute)
    pending = [asyncio.ensure_future(service()) for _ in range(6)]
    await asyncio.sleep(0.01)
    gate.set()
    reports = await asyncio.gather(*pending)
    assert calls == 1 and service.computations == 1
    assert all(r is reports[0] for r in reports)
    await service()  # a later probe starts a new computation
    assert calls == 2


@pytest.mark.asyncio
async def test_a_hanging_query_gives_store_timeout_within_the_deadline_and_never_blocks_writes() -> (
    None
):
    clock = FakeClock(NOW)

    class Hanging(InMemoryScraperRepository):
        async def latest_ok_read(self, dataset_id):
            await asyncio.Event().wait()

    repo = Hanging({SPEC.id: SPEC}, clock=clock)
    loop = asyncio.get_running_loop()
    started = loop.time()
    report, commit = await asyncio.gather(
        compute_readiness(
            specs=[SPEC],
            repository=repo,
            state=RuntimeState(startup_catchup_done=True),
            lock_held=lambda: True,
            clock=clock,
            max_read_age_seconds=7800,
            probe_timeout_seconds=0.1,
        ),
        repo.commit_ok_read(
            SPEC,
            trigger="schedule",
            started_at=NOW,
            provider_time=NOW,
            bars=[make_bar(utc(2026, 10, 9, 9), 1)],
            gap_before=False,
        ),
    )
    assert loop.time() - started < 1.0
    assert report.status == "not_ready"
    assert report.not_ready_reasons == ("store_timeout",)
    assert report.http_status == 503
    assert commit.bars_written == 1


@pytest.mark.asyncio
async def test_query_timeout_is_store_timeout_other_errors_stay_unreachable() -> None:
    class Failing(InMemoryScraperRepository):
        error: Exception

        async def latest_ok_read(self, dataset_id):
            raise self.error

    repo = Failing({SPEC.id: SPEC}, clock=FakeClock(NOW))
    for error, reason in (
        (TimeoutError(), "store_timeout"),
        (OSError("x"), "database_unreachable"),
    ):
        repo.error = error
        report = await _report(repo)
        assert report.not_ready_reasons == (reason,)


def test_readiness_logging_is_throttled(caplog) -> None:
    now = [0.0]
    reporter = ReadinessReporter(interval_seconds=60, monotonic=lambda: now[0])
    boom = TimeoutError()
    with caplog.at_level(logging.INFO):
        reporter.failed("d1", boom, 5.0)  # first: warning with traceback
        for t in (10, 20, 59):
            now[0] = t
            reporter.failed("d1", boom, 5.0)  # suppressed
        now[0] = 61
        reporter.failed("d1", boom, 5.0)  # one line per minute
        reporter.recovered()
        reporter.recovered()  # no second recovery line
        reporter.failed("d2", boom, 1.0)  # new episode: loud again
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(warnings) == 3
    assert warnings[0].exc_info is not None and warnings[1].exc_info is None
    assert (
        "dataset=d1" in warnings[0].getMessage()
        and "TimeoutError" in warnings[0].getMessage()
    )
    assert "3 similar suppressed" in warnings[1].getMessage()
    assert warnings[2].exc_info is not None
    assert len(infos) == 1 and "recovered" in infos[0].getMessage()
