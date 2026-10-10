"""Retention purge: both backends (PostgreSQL when SCRAPER_TEST_POSTGRES_URI is set)."""

from __future__ import annotations

import copy
import logging
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import yaml
from pydantic import ValidationError
from scraper_v2_coinglass_support import heatmap_spec, heatmap_text, update_time
from scraper_v2_support import (
    REPO_ROOT,
    FakeClock,
    make_bar,
    make_spec,
    production_settings,
    require_test_database,
)

from apps.scraper_app.domain.payloads import gate_payload
from apps.scraper_app.runtime.purge import PurgeTask
from apps.scraper_app.runtime.status import (
    DEGRADED,
    PurgeState,
    RuntimeState,
    compute_readiness,
)
from apps.scraper_app.settings import RetentionSettings, parse_settings
from apps.scraper_app.storage import bootstrap
from apps.scraper_app.storage.repository import (
    PURGE_BAR_DELETE_SQL,
    PURGE_BAR_SELECT_SQL,
    PURGE_COINGLASS,
    PURGE_PAYLOAD_DELETE_SQL,
    PURGE_PAYLOAD_SELECT_SQL,
    PURGE_READ_DELETE_SQL,
    PURGE_READ_SELECT_SQL,
    PURGE_TRADINGVIEW,
    InMemoryScraperRepository,
    PostgresPurgeRepository,
    PostgresScraperRepository,
)

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
needs_postgres = pytest.mark.skipif(
    not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI not set"
)
NOW = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
STARTED = NOW - timedelta(days=60)
TV = make_spec(finality_horizon_seconds=2, max_live_lag_seconds=10**9)
TV2 = make_spec(id="t.other.1h", finality_horizon_seconds=2, max_live_lag_seconds=10**9)
CG, CG2 = "cg.btc.heatmap", "cg.eth.heatmap"
FAR_FUTURE = NOW + timedelta(days=365)


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def _accepted():
    name = "1429"
    return gate_payload(
        heatmap_spec(),
        heatmap_text(name),
        returned_at=update_time(name),
        max_payload_bytes=5_000_000,
        max_age_seconds=900,
    )


class Env:
    """Writes data stamped in the past and purges it, on either backend."""

    def __init__(self, kind, repo, purge, pool=None) -> None:
        self.kind, self.repo, self.purge_repo, self.pool = kind, repo, purge, pool
        self.clock = getattr(repo, "_clock", None)

    async def _backdate(self, read_id: int, ts: datetime, *tables: str) -> None:
        if self.pool is None:
            return
        async with self.pool.acquire() as c:
            await c.execute(
                "UPDATE scraper.reads SET finished_at = $2 WHERE read_id = $1",
                read_id,
                ts,
            )
            for table in tables:
                await c.execute(
                    f"UPDATE scraper.{table} SET observed_at = $2 WHERE read_id = $1",
                    read_id,
                    ts,
                )

    async def _at(self, ts: datetime):
        if self.clock is not None:
            self.clock.now = ts

    async def payload(self, dataset: str, age: float) -> int:
        ts = ago(age)
        await self._at(ts)
        commit = await self.repo.commit_ok_payload(
            dataset,
            trigger="schedule",
            started_at=ts,
            accepted=_accepted(),
            gap_before=False,
        )
        await self._backdate(commit.read_id, ts, "payload_observations")
        return commit.read_id

    async def failed(self, dataset: str, age: float) -> int:
        ts = ago(age)
        await self._at(ts)
        read_id = await self.repo.record_failed_read(
            dataset,
            trigger="schedule",
            started_at=ts,
            error_code="timeout",
            error_detail="x",
        )
        await self._backdate(read_id, ts)
        return read_id

    async def bars(self, spec, bars, age: float) -> int:
        ts = ago(age)
        await self._at(ts)
        outcome = await self.repo.commit_ok_read(
            spec,
            trigger="schedule",
            started_at=ts,
            provider_time=ts,
            bars=bars,
            gap_before=False,
        )
        await self._backdate(outcome.read_id, ts, "bar_observations")
        return outcome.read_id

    async def count(self, table: str, dataset: str) -> int:
        if self.pool is None:
            if table == "payload_observations":
                return sum(p.dataset_id == dataset for p in self.repo.payloads)
            if table == "reads":
                return sum(r.dataset_id == dataset for r in self.repo.reads)
            return self.repo.observation_count(dataset)
        async with self.pool.acquire() as c:
            return await c.fetchval(
                f"SELECT count(*) FROM scraper.{table} WHERE dataset_id = $1", dataset
            )

    async def read_ids(self, dataset: str) -> set[int]:
        if self.pool is None:
            return {r.read_id for r in self.repo.reads if r.dataset_id == dataset}
        async with self.pool.acquire() as c:
            rows = await c.fetch(
                "SELECT read_id FROM scraper.reads WHERE dataset_id = $1", dataset
            )
        return {r["read_id"] for r in rows}

    async def purge(self, dataset, kind, days, batch_rows=5000):
        if self.clock is not None:
            self.clock.now = NOW
        return await self.purge_repo.purge_dataset(
            dataset, kind=kind, days=days, batch_rows=batch_rows
        )


@pytest_asyncio.fixture(
    params=["memory", pytest.param("postgres", marks=needs_postgres)]
)
async def env(request):
    specs = {TV.id: TV, TV2.id: TV2}
    if request.param == "memory":
        repo = InMemoryScraperRepository(specs, clock=FakeClock(NOW))
        yield Env("memory", repo, repo)
        return
    import asyncpg

    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)

    async def as_purge_role(connection) -> None:
        await connection.execute("SET ROLE scraper_purge")

    purge_pool = None
    try:
        async with pool.acquire() as c:
            await require_test_database(c)
            await bootstrap.apply_scraper_schema(c, "scraper-test-password", "purge-pw")
            await c.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, "
                "scraper.reads RESTART IDENTITY"
            )
        purge_pool = await asyncpg.create_pool(
            POSTGRES_URI, min_size=1, max_size=2, setup=as_purge_role
        )
        yield Env(
            "postgres",
            PostgresScraperRepository(pool, specs),
            PostgresPurgeRepository(purge_pool),
            pool,
        )
    finally:
        if purge_pool is not None:
            await purge_pool.close()
        await pool.close()


# --- acceptance 1: CoinGlass purge ------------------------------------------


@pytest.mark.asyncio
async def test_coinglass_purge_keeps_newest_ok_read_and_recent_data(env) -> None:
    for age in (30, 20, 10):
        await env.payload(CG, age)
    only = await env.payload(CG2, 40)  # the only ok read, older than the cutoff
    await env.failed(CG2, 35)
    await env.failed(CG, 25)
    recent_failed = await env.failed(CG, 5)
    tv_bar = make_bar(ago(40) - timedelta(hours=1), 1)
    await env.bars(TV, [tv_bar], 40)

    first = await env.purge(CG, PURGE_COINGLASS, 14)
    second = await env.purge(CG2, PURGE_COINGLASS, 14)

    assert first.deleted == {"payload_observations": 2, "reads": 3}
    assert second.deleted == {"payload_observations": 0, "reads": 1}
    assert await env.count("payload_observations", CG) == 1
    assert await env.count("reads", CG) == 2  # the 10 day ok read and the 5 day failure
    assert recent_failed in await env.read_ids(CG)
    # The last known value survives an outage longer than the retention.
    assert await env.count("payload_observations", CG2) == 1
    assert await env.read_ids(CG2) == {only}
    assert (await env.repo.latest_payload(CG2)).read_id == only
    assert await env.count("bar_observations", TV.id) == 1  # never touched by CG


@pytest.mark.asyncio
async def test_tradingview_untouched_when_its_retention_is_null(env) -> None:
    await env.bars(TV, [make_bar(ago(40), 1)], 40)
    await env.bars(TV, [make_bar(ago(39), 2)], 39)
    await env.payload(CG, 40)
    await env.payload(CG, 1)
    state = PurgeState(
        enabled=True,
        configured=True,
        retention_days={"tradingview": None, "coinglass": 14},
        max_age_seconds=100,
    )
    task = PurgeTask(
        repository=env.purge_repo,
        settings=_retention(tradingview_days=None, coinglass_days=14),
        tradingview_ids=[TV.id],
        coinglass_ids=[CG],
        state=state,
        clock=lambda: NOW,
    )
    if env.clock is not None:
        env.clock.now = NOW
    await task.run_pass("catchup")
    assert await env.count("bar_observations", TV.id) == 2
    assert await env.count("reads", TV.id) == 2
    assert await env.count("payload_observations", CG) == 1
    assert state.last_ok_at == NOW and state.deleted["payload_observations"] == 1


# --- acceptance 2 and 3: TradingView purge, batching ------------------------


@pytest.mark.asyncio
async def test_tradingview_purge_drops_old_bars_keeps_answers_for_retained_ones(
    env,
) -> None:
    old1, old2 = ago(31), ago(31) + timedelta(hours=1)
    keep1, keep2 = ago(13), ago(2)
    await env.bars(TV, [make_bar(old1, 1), make_bar(old2, 2)], 30)
    await env.bars(TV, [make_bar(old1, 9)], 20)  # revises old1 -> seq 2
    await env.bars(TV, [make_bar(old2, 2)], 18)  # unchanged: writes no bar rows
    await env.bars(TV, [make_bar(keep1, 3)], 12)
    await env.bars(TV, [make_bar(keep1, 8)], 11)  # revises keep1 -> seq 2
    await env.bars(TV, [make_bar(keep2, 4)], 1)
    await env.bars(TV2, [make_bar(old1, 5)], 40)  # its only ok read, bar too old
    assert await env.count("bar_observations", TV.id) == 6

    retained = ago(14)
    as_of = ago(11) + timedelta(hours=1)

    async def answers():
        final = await env.repo.fetch_bars(TV.id, mode="final", limit=1000)
        known = await env.repo.fetch_bars(TV.id, mode="as_of", as_of=as_of, limit=1000)
        return (
            [b for b in final if b.bar_open > retained],
            [b for b in known if b.bar_open > retained],
        )

    before = await answers()
    assert before[0] and before[1]
    result = await env.purge(TV.id, PURGE_TRADINGVIEW, 14, batch_rows=2)
    other = await env.purge(TV2.id, PURGE_TRADINGVIEW, 14, batch_rows=2)

    # 3 old bar rows in 2 batches; 3 unreferenced old reads in 2 batches.
    assert result.deleted == {"bar_observations": 3, "reads": 3}
    assert result.batches == 4
    # The newest bar of a dataset is kept even when it is past the cutoff.
    assert other.deleted == {"bar_observations": 0, "reads": 0}
    assert await env.count("bar_observations", TV2.id) == 1
    assert await env.count("bar_observations", TV.id) == 3
    assert await env.count("reads", TV.id) == 3
    assert await env.count("reads", TV2.id) == 1  # newest ok read kept
    assert await answers() == before


@pytest.mark.asyncio
async def test_purge_batches_delete_whole_bars_and_keep_the_newest_bar(env) -> None:
    old1, old2 = ago(31), ago(31) + timedelta(hours=1)
    await env.bars(TV, [make_bar(old1, 1), make_bar(old2, 2)], 30)
    await env.bars(TV, [make_bar(old1, 5)], 29)  # old1 -> seq 2
    await env.bars(TV, [make_bar(old1, 6)], 28)  # old1 -> seq 3
    assert await env.count("bar_observations", TV.id) == 4
    # batch_rows=2 selects the first two rows, both of old1; its third row must
    # go with them, and old2 (the newest bar) stays although it is past the cutoff.
    result = await env.purge(TV.id, PURGE_TRADINGVIEW, 14, batch_rows=2)
    assert result.deleted["bar_observations"] == 3
    assert await env.count("bar_observations", TV.id) == 1
    remaining = await env.repo.fetch_bars(TV.id, mode="final", limit=100)
    assert [b.bar_open for b in remaining] == [old2]
    again = await env.purge(TV.id, PURGE_TRADINGVIEW, 14, batch_rows=2)
    assert again.deleted["bar_observations"] == 0


@pytest.mark.asyncio
async def test_batching_removes_everything_in_several_statements(env) -> None:
    for age in range(30, 23, -1):
        await env.payload(CG, age)
    await env.payload(CG, 1)
    result = await env.purge(CG, PURGE_COINGLASS, 14, batch_rows=3)
    assert result.deleted == {"payload_observations": 7, "reads": 7}
    assert result.batches == 6  # ceil(7 / 3) payload batches + ceil(7 / 3) read batches
    assert await env.count("payload_observations", CG) == 1
    assert await env.count("reads", CG) == 1


# --- acceptance 4: roles (PostgreSQL only) ----------------------------------


@needs_postgres
@pytest.mark.asyncio
async def test_purge_role_can_select_and_delete_only_and_bootstrap_is_idempotent() -> (
    None
):
    import asyncpg

    admin = await asyncpg.connect(POSTGRES_URI)
    await require_test_database(admin)
    try:
        await bootstrap.apply_scraper_schema(admin, "pw-app", "pw-purge")
        await bootstrap.apply_scraper_schema(admin, "pw-app", "pw-purge")
        await admin.execute(
            "TRUNCATE scraper.payload_observations, scraper.bar_observations, "
            "scraper.reads RESTART IDENTITY"
        )
        insert = (
            "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
            "error_code) VALUES ('t', 'schedule', 'failed', now(), 'timeout')"
        )
        await admin.execute(insert)
        await admin.execute("SET ROLE scraper_purge")
        assert await admin.fetchval("SELECT count(*) FROM scraper.reads") == 1
        for statement in (
            insert,
            "UPDATE scraper.reads SET dataset_id = 'x'",
            "TRUNCATE scraper.reads",
            "CREATE TABLE scraper.x (a int)",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await admin.execute(statement)
        assert await admin.execute("DELETE FROM scraper.reads") == "DELETE 1"
        await admin.execute("RESET ROLE")
        await admin.execute(insert)
        await admin.execute("SET ROLE scraper_app")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await admin.execute("DELETE FROM scraper.reads")
        await admin.execute("RESET ROLE")
        index = await admin.fetchval(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'bar_observations_read'"
        )
        assert index == 1
    finally:
        await admin.execute("RESET ROLE")
        await admin.execute("DELETE FROM scraper.reads WHERE dataset_id = 't'")
        await admin.close()


def test_purge_grants_and_statements_are_bounded_and_plan_robust() -> None:
    grants = bootstrap.purge_grant_statements()
    assert (
        "GRANT SELECT, DELETE ON scraper.reads, scraper.bar_observations, "
        "scraper.payload_observations TO scraper_purge" in grants
    )
    text = " ".join(grants).upper()
    assert "INSERT" not in text and "UPDATE" not in text and "SEQUENCE" not in text
    selects = [
        PURGE_PAYLOAD_SELECT_SQL,
        PURGE_BAR_SELECT_SQL,
        *PURGE_READ_SELECT_SQL.values(),
    ]
    assert all("LIMIT $" in s and "ORDER BY" in s for s in selects)
    deletes = [PURGE_PAYLOAD_DELETE_SQL, PURGE_BAR_DELETE_SQL, PURGE_READ_DELETE_SQL]
    assert all(" JOIN " not in s.upper() and "USING" not in s.upper() for s in deletes)


# --- acceptance 5: settings -------------------------------------------------


def _raw() -> dict:
    return copy.deepcopy(
        yaml.safe_load((REPO_ROOT / "configs" / "scraper.yaml").read_text())["scraper"]
    )


def _retention(**overrides) -> RetentionSettings:
    base = {
        "slot_minutes": [45],
        "slot_second": 0,
        "wake_check_seconds": 30,
        "batch_rows": 5000,
        "tradingview_days": None,
        "coinglass_days": 14,
        "readiness_max_age_seconds": 10800,
    }
    return RetentionSettings(**{**base, **overrides})


def test_retention_block_absent_means_off_and_production_values_parse() -> None:
    raw = _raw()
    prod = parse_settings(raw)
    assert prod.retention is not None and prod.retention.enabled
    assert prod.retention.coinglass_days == 14
    assert prod.retention.tradingview_days == 14
    assert production_settings().retention == prod.retention
    del raw["retention"]
    assert parse_settings(raw).retention is None


def test_retention_validators_and_strict_keys() -> None:
    raw = _raw()
    # 12 day watch + 2 daily intervals does not fit into 13 days of retention.
    raw["retention"]["tradingview_days"] = 13
    with pytest.raises(ValidationError, match="tradingview_days"):
        parse_settings(raw)
    raw["retention"]["tradingview_days"] = 14
    assert parse_settings(raw).retention.tradingview_days == 14
    raw["retention"]["tradingview_days"] = None
    raw["retention"]["coinglass_days"] = 1  # a heatmap read holds 24 h of history
    with pytest.raises(ValidationError, match="coinglass_days"):
        parse_settings(raw)
    raw["retention"]["coinglass_days"] = 14
    raw["retention"]["surprise"] = 1
    with pytest.raises(ValidationError):
        parse_settings(raw)
    del raw["retention"]["surprise"]
    raw["retention"]["batch_rows"] = 0
    with pytest.raises(ValidationError):
        parse_settings(raw)


# --- acceptance 6: lock, failure, readiness ----------------------------------


class _Boom:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = True

    async def purge_dataset(self, dataset_id, *, kind, days, batch_rows):
        self.calls += 1
        if self.fail:
            raise RuntimeError("database is gone")
        from apps.scraper_app.storage.repository import PurgeResult

        return PurgeResult({"reads": 0}, 0)


def _task(repository, clock, state, **kwargs):
    return PurgeTask(
        repository=repository,
        settings=_retention(),
        tradingview_ids=[],
        coinglass_ids=[CG],
        state=state,
        clock=clock,
        **kwargs,
    )


def _state() -> PurgeState:
    return PurgeState(
        enabled=True,
        configured=True,
        retention_days={"tradingview": None, "coinglass": 14},
        max_age_seconds=3600,
    )


@pytest.mark.asyncio
async def test_lock_not_held_means_no_deletes() -> None:
    boom = _Boom()
    state = _state()
    task = _task(boom, lambda: NOW, state, can_write=lambda: False)
    await task.run_pass("schedule")
    assert boom.calls == 0 and state.last_run_at is None and state.last_ok_at is None


@pytest.mark.asyncio
async def test_failure_warns_survives_and_turns_readiness_degraded(caplog) -> None:
    clock = FakeClock(NOW)
    boom = _Boom()
    state = _state()
    task = _task(boom, clock, state)
    runtime = RuntimeState(startup_catchup_done=True, purge=state)

    async def report():
        return await compute_readiness(
            specs=[],
            repository=InMemoryScraperRepository({}, clock=clock),
            state=runtime,
            lock_held=lambda: True,
            clock=clock,
            max_read_age_seconds=3600,
        )

    with caplog.at_level(logging.WARNING):
        await task.run_pass("schedule")
    assert [r.levelname for r in caplog.records if "purge" in r.message] == ["WARNING"]
    assert state.last_ok_at is None and state.last_run_at == NOW
    assert (await report()).service_reasons == ()  # inside the age limit

    clock.now += timedelta(seconds=3601)
    await task.run_pass("schedule")  # the task survives and fails again
    degraded = await report()
    assert degraded.status == DEGRADED and degraded.http_status == 200
    assert degraded.service_reasons == ("purge_failing",)
    assert degraded.payload()["purge"]["last_ok_at"] is None

    boom.fail = False
    await task.run_pass("schedule")
    healed = await report()
    assert healed.service_reasons == () and healed.payload()["purge"]["last_ok_at"]


@pytest.mark.asyncio
async def test_missing_purge_uri_is_a_degraded_service_reason() -> None:
    state = PurgeState(
        enabled=True,
        configured=False,
        retention_days={"tradingview": None, "coinglass": 14},
        max_age_seconds=3600,
    )
    report = await compute_readiness(
        specs=[],
        repository=InMemoryScraperRepository({}, clock=lambda: NOW),
        state=RuntimeState(startup_catchup_done=True, purge=state),
        lock_held=lambda: True,
        clock=lambda: NOW,
        max_read_age_seconds=3600,
    )
    assert report.status == DEGRADED
    assert report.service_reasons == ("purge_not_configured",)
    absent = await compute_readiness(
        specs=[],
        repository=InMemoryScraperRepository({}, clock=lambda: NOW),
        state=RuntimeState(startup_catchup_done=True),
        lock_held=lambda: True,
        clock=lambda: NOW,
        max_read_age_seconds=3600,
    )
    assert "purge" not in absent.payload() and absent.status == "ready"


def test_purge_uri_comes_only_from_the_environment() -> None:
    from apps.scraper_app.settings import purge_database_uri

    assert purge_database_uri({}) is None
    assert purge_database_uri({"SCRAPER_PURGE_POSTGRES_URI": " postgresql://p "}) == (
        "postgresql://p"
    )


# --- acceptance 7: one timestamp per read ------------------------------------


@pytest.mark.asyncio
async def test_bar_rows_of_one_read_share_the_reads_finished_at(env) -> None:
    bars = [make_bar(ago(5) + timedelta(hours=i), i) for i in range(4)]
    first = await env.bars(TV, bars, 1)
    revised = [make_bar(bars[0].bar_open, 99), bars[1]]
    second = await env.bars(TV, revised, 0.5)
    reads = {r.read_id: r for r in await _reads(env)}
    seen = await env.repo.fetch_bars(TV.id, mode="as_of", as_of=FAR_FUTURE, limit=100)
    by_read = {first: [], second: []}
    for record in seen:
        by_read[record.read_id].append(record.observed_at)
    assert len(by_read[first]) == 3 and len(by_read[second]) == 1
    for read_id, stamps in by_read.items():
        assert set(stamps) == {reads[read_id].finished_at}


async def _reads(env):
    if env.pool is None:
        return env.repo.reads
    from types import SimpleNamespace

    async with env.pool.acquire() as c:
        rows = await c.fetch("SELECT read_id, finished_at FROM scraper.reads")
    return [SimpleNamespace(**dict(r)) for r in rows]
