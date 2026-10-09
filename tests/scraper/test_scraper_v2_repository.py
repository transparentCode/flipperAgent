"""Repository semantics, run against the in-memory twin and (when available) PostgreSQL."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest
import pytest_asyncio
from scraper_v2_support import (
    FakeClock,
    make_bar,
    make_spec,
    require_test_database,
    utc,
)

from apps.scraper_app.domain import errors
from apps.scraper_app.storage.repository import (
    InMemoryScraperRepository,
    PostgresScraperRepository,
)

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
SPEC = make_spec(finality_horizon_seconds=2, max_live_lag_seconds=3600)
STARTED = utc(2026, 1, 1)


class _Memory:
    def __init__(self) -> None:
        self.clock = FakeClock(utc(2026, 10, 9, 12))
        self.repo = InMemoryScraperRepository({SPEC.id: SPEC}, clock=self.clock)

    async def now(self):
        return self.clock.now

    async def advance(self, seconds: float) -> None:
        self.clock.now += timedelta(seconds=seconds)

    async def observation_count(self) -> int:
        return self.repo.observation_count(SPEC.id)

    async def read_count(self) -> int:
        return len(self.repo.reads)


class _Postgres:
    def __init__(self, pool) -> None:
        self.pool = pool
        self.repo = PostgresScraperRepository(pool, {SPEC.id: SPEC})

    async def now(self):
        async with self.pool.acquire() as connection:
            return await connection.fetchval("SELECT clock_timestamp()")

    async def advance(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def observation_count(self) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval(
                "SELECT count(*) FROM scraper.bar_observations"
            )

    async def read_count(self) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval("SELECT count(*) FROM scraper.reads")


@pytest_asyncio.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI is not set"
            ),
        ),
    ]
)
async def backend(request):
    if request.param == "memory":
        yield _Memory()
        return
    import asyncpg

    from apps.scraper_app.storage.bootstrap import apply_scraper_schema

    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            await require_test_database(connection)
            await apply_scraper_schema(connection, "scraper-test-password")
            await connection.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, scraper.reads RESTART IDENTITY"
            )
        yield _Postgres(pool)
    finally:
        await pool.close()


async def _commit(backend, bars, *, provider_time=None, trigger="schedule", gap=False):
    return await backend.repo.commit_ok_read(
        SPEC,
        trigger=trigger,
        started_at=STARTED,
        provider_time=provider_time or await backend.now(),
        bars=bars,
        gap_before=gap,
    )


async def _final(backend, **kwargs):
    return await backend.repo.fetch_bars(SPEC.id, mode="final", limit=1000, **kwargs)


@pytest.mark.asyncio
async def test_only_changed_bars_are_written_with_increasing_seq(backend) -> None:
    base = utc(2026, 10, 1)
    bars = [make_bar(base + timedelta(hours=i), i) for i in range(3)]

    first = await _commit(backend, bars)
    assert (first.bars_seen, first.bars_written) == (3, 3)

    again = await _commit(backend, bars)
    assert (again.bars_seen, again.bars_written) == (3, 0)
    assert await backend.observation_count() == 3

    revised = [bars[0], make_bar(bars[1].bar_open, 99), bars[2]]
    await backend.advance(0.1)
    third = await _commit(backend, revised)
    assert third.bars_written == 1
    assert await backend.observation_count() == 4

    got = await _final(backend)
    assert [(b.bar_open, b.seq, b.revision_count) for b in got] == [
        (bars[0].bar_open, 1, 0),
        (bars[1].bar_open, 2, 1),
        (bars[2].bar_open, 1, 0),
    ]
    assert got[1].content_hash == revised[1].content_hash
    assert got[1].first_observed_at < got[1].observed_at


@pytest.mark.asyncio
async def test_a_failed_read_writes_only_its_read_row(backend) -> None:
    bars = [make_bar(utc(2026, 10, 1), 1)]
    await _commit(backend, bars)
    before = await backend.observation_count()

    read_id = await backend.repo.record_failed_read(
        SPEC.id,
        trigger="schedule",
        started_at=STARTED,
        error_code=errors.TIMEOUT,
        error_detail="x" * 2000,
    )
    assert read_id > 0
    assert await backend.observation_count() == before
    latest = await backend.repo.latest_read(SPEC.id)
    assert latest is not None
    assert (latest.status, latest.error_code) == ("failed", errors.TIMEOUT)
    assert latest.covered_from is None
    assert len(latest.error_detail or "") <= 500
    ok = await backend.repo.latest_ok_read(SPEC.id)
    assert ok is not None and ok.status == "ok"
    assert ok.covered_from == ok.covered_to == bars[0].bar_open


@pytest.mark.asyncio
async def test_read_summary_functions(backend) -> None:
    assert await backend.repo.latest_ok_read(SPEC.id) is None
    assert await backend.repo.last_bar_open(SPEC.id) is None
    base = utc(2026, 10, 1)
    await _commit(
        backend, [make_bar(base, 0), make_bar(base + timedelta(hours=1), 1)], gap=True
    )
    ok = await backend.repo.latest_ok_read(SPEC.id)
    assert ok is not None
    assert (ok.covered_from, ok.covered_to) == (base, base + timedelta(hours=1))
    assert (ok.bars_seen, ok.bars_written, ok.gap_before) == (2, 2, True)
    assert await backend.repo.last_bar_open(SPEC.id) == base + timedelta(hours=1)


@pytest.mark.asyncio
async def test_bar_read_shortly_after_close_is_not_final_until_a_covering_read_after_the_horizon(
    backend,
) -> None:
    close = await backend.now()
    bar = make_bar(close - timedelta(hours=1), 5)
    assert bar.bar_close == close

    await _commit(backend, [bar], provider_time=close)
    assert await _final(backend) == []  # read finished well inside the 2s horizon

    # A later read that does not cover the bar does not finalise it.
    await backend.advance(2.3)
    other = make_bar(close + timedelta(hours=1), 6)
    await _commit(backend, [other], provider_time=close + timedelta(hours=2))
    assert bar.bar_open not in {b.bar_open for b in await _final(backend)}

    # A covering read finished after close + horizon makes it final.
    await _commit(backend, [bar], provider_time=close + timedelta(seconds=3))
    final = await _final(backend)
    assert bar.bar_open in {b.bar_open for b in final}
    assert all(b.is_final for b in final)


@pytest.mark.asyncio
async def test_as_of_returns_the_values_known_at_t_including_earlier_revisions(
    backend,
) -> None:
    bar = make_bar(utc(2026, 10, 1), 1)
    revised = make_bar(bar.bar_open, 2)

    before_anything = await backend.now()
    await backend.advance(0.1)
    await _commit(backend, [bar])
    await backend.advance(0.1)
    t_between = await backend.now()
    await backend.advance(0.1)
    await _commit(backend, [revised])
    await backend.advance(0.1)
    t_after = await backend.now()

    def query(moment):
        return backend.repo.fetch_bars(SPEC.id, mode="as_of", as_of=moment, limit=10)

    assert await query(before_anything) == []
    (early,) = await query(t_between)
    assert (early.seq, early.content_hash, early.is_final) == (
        1,
        bar.content_hash,
        True,
    )
    (late,) = await query(t_after)
    assert (late.seq, late.content_hash) == (2, revised.content_hash)
    assert late.revision_count == 1
    assert late.first_observed_at == early.first_observed_at


@pytest.mark.asyncio
async def test_as_of_finality_only_counts_reads_finished_by_t(backend) -> None:
    close = await backend.now()
    bar = make_bar(close - timedelta(hours=1), 3)
    await _commit(backend, [bar], provider_time=close)
    t_early = await backend.now()
    await backend.advance(2.3)
    await _commit(backend, [bar], provider_time=close + timedelta(seconds=3))
    t_late = await backend.now()

    (early,) = await backend.repo.fetch_bars(
        SPEC.id, mode="as_of", as_of=t_early, limit=5
    )
    (late,) = await backend.repo.fetch_bars(
        SPEC.id, mode="as_of", as_of=t_late, limit=5
    )
    assert early.is_final is False
    assert late.is_final is True


@pytest.mark.asyncio
async def test_backfilled_flag_reflects_provider_lag(backend) -> None:
    now = await backend.now()
    live = make_bar(now - timedelta(hours=2), 1)  # closed 1h before the read
    old = make_bar(now - timedelta(hours=30), 2)  # closed 29h before the read
    await _commit(backend, [old, live], provider_time=now)
    got = {
        b.bar_open: b
        for b in await backend.repo.fetch_bars(
            SPEC.id, mode="as_of", as_of=await backend.now(), limit=10
        )
    }
    assert got[live.bar_open].backfilled is False
    assert got[old.bar_open].backfilled is True


@pytest.mark.asyncio
async def test_start_end_and_limit_select_a_half_open_ascending_window(backend) -> None:
    base = utc(2026, 9, 1)
    bars = [make_bar(base + timedelta(hours=i), i) for i in range(6)]
    await _commit(backend, bars)
    window = await _final(backend, start=bars[1].bar_open, end=bars[4].bar_open)
    assert [b.bar_open for b in window] == [b.bar_open for b in bars[1:4]]
    limited = await backend.repo.fetch_bars(SPEC.id, mode="final", limit=2)
    assert [b.bar_open for b in limited] == [bars[0].bar_open, bars[1].bar_open]


@pytest.mark.asyncio
async def test_argument_validation(backend) -> None:
    with pytest.raises(ValueError):
        await backend.repo.fetch_bars(SPEC.id, mode="as_of", limit=1)
    with pytest.raises(ValueError):
        await backend.repo.fetch_bars(
            SPEC.id, mode="final", as_of=utc(2026, 1, 1), limit=1
        )
    with pytest.raises(ValueError):
        await backend.repo.fetch_bars(SPEC.id, mode="final", limit=0)
    with pytest.raises(ValueError):
        await _commit(backend, [make_bar(utc(2026, 1, 1))], trigger="nope")
    with pytest.raises(ValueError):
        await _commit(backend, [])


@pytest.mark.asyncio
async def test_backfilled_is_the_flag_of_the_first_observation(backend) -> None:
    now = await backend.now()
    bar = make_bar(now - timedelta(hours=2), 1)  # first seen live
    await _commit(backend, [bar], provider_time=now - timedelta(hours=1))
    await backend.advance(0.1)
    # revised three hours later: the revision row is itself backfilled
    later = now + timedelta(hours=3)
    await _commit(backend, [make_bar(bar.bar_open, 2)], provider_time=later)
    (got,) = await backend.repo.fetch_bars(
        SPEC.id, mode="as_of", as_of=await backend.now(), limit=5
    )
    assert got.seq == 2 and got.revision_count == 1
    assert got.backfilled is False


@pytest.mark.asyncio
async def test_contiguous_from_and_first_bar_open(backend) -> None:
    assert await backend.repo.contiguous_from(SPEC.id) is None
    assert await backend.repo.first_bar_open(SPEC.id) is None
    base = utc(2026, 9, 1)
    hours = [0, 1, 2, 5, 6, 7]  # hole between hour 2 and hour 5
    await _commit(backend, [make_bar(base + timedelta(hours=h), h) for h in hours])
    assert await backend.repo.first_bar_open(SPEC.id) == base
    assert await backend.repo.contiguous_from(SPEC.id) == base + timedelta(hours=5)
    # a revision row must not change the answer
    await _commit(backend, [make_bar(base + timedelta(hours=1), 99)])
    assert await backend.repo.contiguous_from(SPEC.id) == base + timedelta(hours=5)
    # filling the hole joins the runs
    await _commit(backend, [make_bar(base + timedelta(hours=h), h) for h in (3, 4)])
    assert await backend.repo.contiguous_from(SPEC.id) == base


@pytest.mark.asyncio
async def test_contiguous_from_not_before_windows(backend) -> None:
    base = utc(2026, 9, 1)
    hours = [*range(10), *range(13, 21)]  # hole at hours 10-12
    bars = [make_bar(base + timedelta(hours=h), h) for h in hours]
    await _commit(backend, bars)
    # revision rows must not change any answer
    await backend.advance(0.1)
    await _commit(backend, [make_bar(base + timedelta(hours=4), 99)])

    def at(h):
        return base + timedelta(hours=h)

    cf = backend.repo.contiguous_from
    # gap inside the window (anchor hour 5, break at 9 -> 13)
    assert await cf(SPEC.id, not_before=at(5)) == at(13)
    # gap older than the window: only the clean tail is examined
    assert await cf(SPEC.id, not_before=at(15)) == at(15)
    assert await cf(SPEC.id, not_before=at(20)) == at(20)
    # window start falls inside the hole: newest bar at/before it is hour 9
    assert await cf(SPEC.id, not_before=at(11)) == at(13)
    # no bar at or before not_before (dataset younger than the window)
    assert await cf(SPEC.id, not_before=at(-48)) == at(13)
    # None equals the full-history answer
    assert await cf(SPEC.id) == at(13)
    assert await cf(SPEC.id, not_before=None) == at(13)


@pytest.mark.asyncio
async def test_contiguous_from_without_gap_returns_first_bar_for_old_window(
    backend,
) -> None:
    base = utc(2026, 9, 1)
    await _commit(backend, [make_bar(base + timedelta(hours=h), h) for h in range(8)])
    assert await backend.repo.contiguous_from(SPEC.id) == base
    assert (
        await backend.repo.contiguous_from(SPEC.id, not_before=base - timedelta(days=1))
        == base
    )
    assert await backend.repo.contiguous_from(
        SPEC.id, not_before=base + timedelta(hours=5)
    ) == (base + timedelta(hours=5))


@pytest.mark.skipif(not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI is not set")
@pytest.mark.asyncio
async def test_contiguous_from_is_fast_under_stale_statistics() -> None:
    """Regression: a freshly loaded, never-analysed dataset must not hit a bad plan."""
    import asyncpg

    big = make_spec(id="big", finality_horizon_seconds=0)
    others = [make_spec(id=f"seed{i}", finality_horizon_seconds=0) for i in range(6)]
    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            await require_test_database(connection)
            from apps.scraper_app.storage.bootstrap import apply_scraper_schema

            await apply_scraper_schema(connection, "scraper-test-password")
            await connection.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, scraper.reads RESTART IDENTITY"
            )
            read_id = await connection.fetchval(
                "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
                "covered_from, covered_to) VALUES ('x', 'schedule', 'ok', now(), now(), now()) "
                "RETURNING read_id"
            )
            insert = (
                "INSERT INTO scraper.bar_observations (dataset_id, bar_open, seq, bar_close, "
                "open, high, low, close, volume, content_hash, read_id, backfilled) "
                "SELECT $1, $2::timestamptz + n * interval '1 hour', 1, "
                "$2::timestamptz + (n + 1) * interval '1 hour', 1, 2, 0, 1, 1, 'h', $3, false "
                "FROM generate_series(0, $4::int - 1) n WHERE n % $5::int <> 0"
            )
            base = utc(2025, 1, 1)
            for spec in others:
                await connection.execute(insert, spec.id, base, read_id, 3000, 100000)
            await connection.execute("ANALYZE scraper.bar_observations")
            # loaded after the ANALYZE: the planner still believes the dataset is tiny
            await connection.execute(insert, "big", base, read_id, 5000, 700)

        repo = PostgresScraperRepository(pool, {s.id: s for s in [big, *others]})
        n_last = 4999
        full = await asyncio.wait_for(repo.contiguous_from("big"), timeout=5)
        assert full == base + timedelta(hours=4901)  # last hole at n = 4900
        newest = base + timedelta(hours=n_last)
        windowed = await asyncio.wait_for(
            repo.contiguous_from("big", not_before=newest - timedelta(hours=48)),
            timeout=5,
        )
        assert windowed == newest - timedelta(hours=48)
        across = await asyncio.wait_for(
            repo.contiguous_from("big", not_before=newest - timedelta(hours=150)),
            timeout=5,
        )
        assert across == base + timedelta(hours=4901)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_revision_first_seen_after_the_horizon_is_final_while_as_of_keeps_the_earlier_version(
    backend,
) -> None:
    close = await backend.now()
    bar = make_bar(close - timedelta(hours=1), 1)
    revised = make_bar(bar.bar_open, 2)

    await _commit(backend, [bar], provider_time=close)
    assert await _final(backend) == []  # inside the horizon
    await backend.advance(2.3)
    await _commit(backend, [bar], provider_time=close + timedelta(seconds=3))
    (settled,) = await _final(backend)
    assert (settled.seq, settled.is_final) == (1, True)
    await backend.advance(0.1)
    t_before = await backend.now()
    await backend.advance(0.1)

    await _commit(backend, [revised], provider_time=close + timedelta(seconds=4))
    await backend.advance(0.1)

    (final,) = await _final(backend)
    assert (final.seq, final.content_hash, final.is_final) == (
        2,
        revised.content_hash,
        True,
    )
    (known,) = await backend.repo.fetch_bars(
        SPEC.id, mode="as_of", as_of=t_before, limit=5
    )
    assert (known.seq, known.content_hash, known.is_final) == (
        1,
        bar.content_hash,
        True,
    )
