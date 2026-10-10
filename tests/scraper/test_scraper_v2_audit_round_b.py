"""Audit fixes, round B: batched reads, catalog cache, payload LRU, cursor, pools."""

from __future__ import annotations

import asyncio
import copy
import os
from datetime import timedelta

import asyncpg
import pytest
import yaml
from pydantic import ValidationError
from scraper_v2_support import (
    REPO_ROOT,
    FakeClock,
    make_bar,
    production_settings,
    require_test_database,
)
from test_scraper_v2_api import (
    HEATMAP,
    NOW,
    World,
    _data_text,
    _payload_world,
    iso,
)

from apps.scraper_app.http_api.v2 import PayloadTextCache
from apps.scraper_app.runtime.status import (
    CoinGlassReadiness,
    RuntimeState,
    compute_readiness,
)
from apps.scraper_app.settings import parse_settings
from apps.scraper_app.storage import bootstrap
from apps.scraper_app.storage.repository import (
    _BAR_EDGE_SQL,
    _LATEST_READS_SQL,
    InMemoryScraperRepository,
    PostgresScraperRepository,
)

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
needs_postgres = pytest.mark.skipif(
    not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI not set"
)
SETTINGS = production_settings()
SPECS = SETTINGS.dataset_specs()
CG_IDS = tuple(s.id for s in SETTINGS.payload_specs())
# Before F5: two reads per dataset, a first_bar per contiguous dataset, and the
# window-bounded contiguity query per contiguous dataset.
CONTIGUOUS = sum(s.contiguous for s in SPECS)
STATEMENTS_BEFORE = 2 * (len(SPECS) + len(CG_IDS)) + 2 * CONTIGUOUS
STATEMENT_BUDGET = 25


class CountingPool:
    """Counts every statement run through a pool (fetch, fetchval, fetchrow, execute)."""

    def __init__(self, pool) -> None:
        self._pool = pool
        self.statements: list[str] = []

    def acquire(self):
        return _CountingAcquire(self)

    def __getattr__(self, name):
        return getattr(self._pool, name)


class _CountingAcquire:
    def __init__(self, owner: CountingPool) -> None:
        self._owner = owner
        self._cm = owner._pool.acquire()

    async def __aenter__(self):
        return _CountingConnection(await self._cm.__aenter__(), self._owner)

    async def __aexit__(self, *exc):
        return await self._cm.__aexit__(*exc)


class _CountingConnection:
    def __init__(self, connection, owner: CountingPool) -> None:
        self._c, self._owner = connection, owner

    def __getattr__(self, name):
        attr = getattr(self._c, name)
        if name in ("fetch", "fetchval", "fetchrow", "execute"):

            async def counted(query, *args, **kw):
                self._owner.statements.append(str(query))
                return await attr(query, *args, **kw)

            return counted
        return attr


class CountingRepo:
    """Counts repository calls of the in-memory twin (one call is one statement)."""

    def __init__(self, inner) -> None:
        self.inner, self.calls = inner, []

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr

        async def counted(*a, **k):
            self.calls.append(name)
            return await attr(*a, **k)

        return counted


async def _probe(repo):
    return await compute_readiness(
        specs=SPECS,
        repository=repo,
        state=RuntimeState(startup_catchup_done=True),
        lock_held=lambda: True,
        clock=lambda: NOW,
        max_read_age_seconds=7800,
        coinglass=CoinGlassReadiness(CG_IDS, 2400),
    )


# --- F5 ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_readiness_probe_is_a_handful_of_repository_calls() -> None:
    inner = InMemoryScraperRepository({s.id: s for s in SPECS}, clock=FakeClock(NOW))
    # The twin implements the batched calls on top of the single ones, so count
    # the calls the readiness code makes, not what the twin does underneath.
    seen: list[str] = []

    class Spy:
        def __getattr__(self, name):
            fn = getattr(inner, name)

            async def call(*a, **k):
                seen.append(name)
                return await fn(*a, **k)

            return call

    await _probe(Spy())
    batched = [c for c in seen if c in ("latest_reads", "first_bar_opens")]
    assert batched == ["latest_reads", "first_bar_opens"]
    assert seen.count("contiguous_from") == 0  # nothing stored, nothing to scan
    assert not {"latest_ok_read", "latest_read", "first_bar_open"} & set(seen)


@needs_postgres
@pytest.mark.asyncio
async def test_postgres_probe_statement_count_before_and_after() -> None:
    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)
    try:
        async with pool.acquire() as c:
            await require_test_database(c)
            await bootstrap.apply_scraper_schema(c, "scraper-test-password", "purge-pw")
            await c.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, "
                "scraper.reads RESTART IDENTITY"
            )
        counting = CountingPool(pool)
        repo = PostgresScraperRepository(counting, {s.id: s for s in SPECS})
        start = NOW - timedelta(hours=3)
        for spec in SPECS:
            if spec.interval_seconds == 3600:
                await repo.commit_ok_read(
                    spec,
                    trigger="schedule",
                    started_at=start,
                    provider_time=start,
                    bars=[make_bar(NOW - timedelta(days=1 + i), i) for i in range(3)],
                    gap_before=False,
                )
        counting.statements.clear()
        report = await _probe(repo)
        used = len(counting.statements)
        print(
            f"readiness statements per probe: before={STATEMENTS_BEFORE} after={used}"
        )
        assert used <= STATEMENT_BUDGET < STATEMENTS_BEFORE
        assert 2 + CONTIGUOUS <= STATEMENT_BUDGET  # worst case: every dataset has bars
        assert report.status in ("ready", "degraded", "not_ready")
    finally:
        await pool.close()


@needs_postgres
@pytest.mark.asyncio
async def test_batched_lookups_are_correct_and_index_driven_with_stale_statistics() -> (
    None
):
    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)
    try:
        async with pool.acquire() as c:
            await require_test_database(c)
            await bootstrap.apply_scraper_schema(c, "scraper-test-password", "purge-pw")
            await c.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, "
                "scraper.reads RESTART IDENTITY"
            )
            await c.execute(
                "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
                "finished_at, covered_from, covered_to, error_code) SELECT 'd' || (g % 3), 'schedule', "
                "CASE WHEN g % 7 = 0 THEN 'failed' ELSE 'ok' END, now(), "
                "now() - make_interval(mins => g), "
                "CASE WHEN g % 7 = 0 THEN NULL ELSE now() END, "
                "CASE WHEN g % 7 = 0 THEN NULL ELSE now() END, "
                "CASE WHEN g % 7 = 0 THEN 'x' END "
                "FROM generate_series(1, 3000) g"
            )
            await c.execute("ANALYZE scraper.reads")
            # Statistics that claim an almost empty table.
            await c.execute(
                "UPDATE pg_class SET reltuples = 1, relpages = 1 "
                "WHERE oid = 'scraper.reads'::regclass"
            )
            ids = ["d0", "d1", "d2", "missing"]
            plan = "\n".join(
                r[0]
                for r in await c.fetch(
                    "EXPLAIN " + _LATEST_READS_SQL.replace("$1", "$1::text[]"), ids
                )
            )
            assert "Seq Scan on reads" not in plan, plan
            repo = PostgresScraperRepository(pool, {})
            batched = await repo.latest_reads(ids)
            for dataset in ids:
                assert batched[dataset] == (
                    await repo.latest_ok_read(dataset),
                    await repo.latest_read(dataset),
                )
            assert batched["missing"] == (None, None)
            bars_plan = "\n".join(
                r[0]
                for r in await c.fetch(
                    "EXPLAIN " + _BAR_EDGE_SQL.format(order="ASC"), ids
                )
            )
            assert "Seq Scan on bar_observations" not in bars_plan, bars_plan
    finally:
        await pool.close()


# --- F6 / F7 / F12 -------------------------------------------------------------


def test_catalog_store_facts_are_reused_then_refreshed() -> None:
    world = World()
    inner = world.repo
    calls: list[str] = []
    real_heads, real_rev = inner.dataset_heads, inner.revisions_after_horizon_many

    async def heads(*a, **k):
        calls.append("heads")
        return await real_heads(*a, **k)

    async def revisions(*a, **k):
        calls.append("revisions")
        return await real_rev(*a, **k)

    inner.dataset_heads, inner.revisions_after_horizon_many = heads, revisions
    ticks = [0.0]
    world.deps.clock = lambda: ticks[0]
    for _ in range(3):
        assert world.get("/v2/datasets").status_code == 200
    assert world.get(f"/v2/datasets/{HEATMAP}").status_code == 200
    assert calls == ["heads", "revisions"]  # one batch for everything
    ticks[0] = 11.0  # past api.catalog_cache_seconds (10)
    world.get("/v2/datasets")
    assert calls == ["heads", "revisions", "heads", "revisions"]


def test_catalog_skips_bar_queries_for_payload_datasets() -> None:
    world = World()
    seen: dict[str, object] = {}
    real = world.repo.dataset_heads

    async def heads(ids, *, bar_ids=None):
        seen["bar_ids"] = list(bar_ids)
        return await real(ids, bar_ids=bar_ids)

    world.repo.dataset_heads = heads
    assert world.get("/v2/datasets").status_code == 200
    assert seen["bar_ids"] and all(i.startswith("tv.") for i in seen["bar_ids"])


def test_bars_endpoint_makes_one_head_call_per_request() -> None:
    import asyncio as aio

    from test_scraper_v2_api import BARS, seeded

    world = aio.run(seeded())
    calls: list[object] = []
    real = world.repo.dataset_head

    async def head(dataset_id, *, at=None):
        calls.append(at)
        return await real(dataset_id, at=at)

    world.repo.dataset_head = head
    for params in (
        {},
        {"mode": "current"},
        {"mode": "as_of", "as_of": iso(NOW - timedelta(hours=2))},
    ):
        calls.clear()
        assert world.get(BARS, **params).status_code == 200, params
        assert len(calls) == 1, (params, calls)


def test_payload_text_cache_is_a_byte_bounded_lru() -> None:
    cache = PayloadTextCache(10)
    cache.put(1, "aaaa")
    cache.put(2, "bbbb")
    assert cache.get(1) == "aaaa"  # 1 is now the most recent
    cache.put(3, "cccc")  # 12 bytes > 10: evicts 2
    assert cache.get(2) is None and cache.get(1) == "aaaa" and cache.get(3) == "cccc"
    assert cache.size <= 10
    cache.put(4, "x" * 11)  # larger than the whole cache: not kept
    assert cache.get(4) is None


def test_repeat_payload_requests_are_served_from_the_cache() -> None:
    w, ids = asyncio.run(_payload_world())
    fetched: list[int] = []
    real = w.repo.payload_by_id

    async def by_id(dataset_id, read_id, *, blob=True):
        if blob:
            fetched.append(read_id)
        return await real(dataset_id, read_id, blob=blob)

    w.repo.payload_by_id = by_id
    first = w.get(f"/v2/datasets/{HEATMAP}/payload")
    second = w.get(f"/v2/datasets/{HEATMAP}/payload")
    by_id_body = w.get(f"/v2/datasets/{HEATMAP}/payloads/{ids[-1]}")
    assert first.status_code == second.status_code == by_id_body.status_code == 200
    assert (
        _data_text(first.text) == _data_text(second.text) == _data_text(by_id_body.text)
    )
    assert fetched == [ids[-1]]  # the blob was read and decompressed once


def test_payload_list_cursor_does_not_skip_rows_sharing_a_timestamp() -> None:
    async def build():
        w = World()
        for i in range(5):
            await w.payload(HEATMAP, NOW - timedelta(hours=1))  # same observed_at
        await w.payload(HEATMAP, NOW - timedelta(minutes=30))
        w.clock.now = NOW
        return w

    w = asyncio.run(build())
    seen: list[int] = []
    params: dict = {"limit": "2"}
    for _ in range(10):
        body = w.get(f"/v2/datasets/{HEATMAP}/payloads", **params).json()
        seen += [p["observation_id"] for p in body["payloads"]]
        if body["next"] is None:
            break
        params = {k: v for k, v in body["next"].items() if v is not None}
    assert sorted(seen) == sorted(set(seen)) and len(seen) == 6
    assert seen == sorted(seen, reverse=True)


# --- F10 -----------------------------------------------------------------------


def _raw() -> dict:
    return copy.deepcopy(
        yaml.safe_load((REPO_ROOT / "configs" / "scraper.yaml").read_text())["scraper"]
    )


def test_pool_sizes_are_configurable_with_production_defaults() -> None:
    settings = parse_settings(_raw())
    assert settings.database.pool_max_size == 3
    assert settings.retention.pool_max_size == 2
    raw = _raw()
    del raw["database"]["pool_max_size"]
    del raw["retention"]["pool_max_size"]
    settings = parse_settings(raw)
    assert (settings.database.pool_max_size, settings.retention.pool_max_size) == (3, 2)
    raw = _raw()
    raw["database"]["pool_max_size"] = 2  # two lanes + readiness need three
    with pytest.raises(ValidationError, match="pool_max_size"):
        parse_settings(raw)
    raw = _raw()
    raw["retention"]["pool_max_size"] = 0
    with pytest.raises(ValidationError, match="pool_max_size"):
        parse_settings(raw)


def test_api_cache_settings_have_defaults_and_bounds() -> None:
    assert SETTINGS.api.catalog_cache_seconds == 10
    assert SETTINGS.api.payload_cache_bytes == 33554432
    raw = _raw()
    raw["api"]["catalog_cache_seconds"] = -1
    with pytest.raises(ValidationError):
        parse_settings(raw)


# --- F8 ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_gate_runs_off_the_event_loop_thread(monkeypatch) -> None:
    import threading

    from scraper_v2_coinglass_support import coinglass_raw
    from test_scraper_v2_audit_round_a import _TextRunner
    from test_scraper_v2_coinglass_lane import _codes, _lane_for, _Tick

    from apps.scraper_app.runtime import coinglass as module

    loop_thread = threading.get_ident()
    threads: list[int] = []
    real = module.gate_payload

    def spy(*a, **k):
        threads.append(threading.get_ident())
        return real(*a, **k)

    monkeypatch.setattr(module, "gate_payload", spy)
    lane, repo, _ = _lane_for(coinglass_raw(), _TextRunner(_Tick()))
    await lane.run_pass("schedule")
    assert threads and all(t != loop_thread for t in threads)
    assert set(_codes(repo).values()) == {None}


# --- F4 ------------------------------------------------------------------------


def test_require_pg_helper_recognises_the_database_skips(monkeypatch) -> None:
    from scraper_v2_support import is_postgres_skip, postgres_required

    monkeypatch.delenv("SCRAPER_REQUIRE_PG", raising=False)
    assert not postgres_required()
    monkeypatch.setenv("SCRAPER_REQUIRE_PG", "1")
    assert postgres_required()
    assert is_postgres_skip("SCRAPER_TEST_POSTGRES_URI not set")
    assert is_postgres_skip("SCRAPER_TEST_POSTGRES_URI is not set")
    assert not is_postgres_skip("live test: set SCRAPER_LIVE=1")
