"""Phase 2 package A: read path. Differential, scale and EXPLAIN tests."""

from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import timedelta

import pytest
from scraper_v2_support import (
    FakeClock,
    make_bar,
    make_spec,
    require_test_database,
    utc,
)

from apps.scraper_app.storage.repository import (
    InMemoryScraperRepository,
    PostgresScraperRepository,
    ReadRecord,
    _Observation,
    compose_fetch_bars,
)

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
needs_postgres = pytest.mark.skipif(
    not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI not set"
)
BASE = utc(2026, 1, 1)


def _hours(n: float) -> timedelta:
    return timedelta(hours=n)


# --- twin-only semantics (no database) ---------------------------------------


def _twin(horizon: int = 7200) -> tuple[InMemoryScraperRepository, object]:
    spec = make_spec(finality_horizon_seconds=horizon)
    clock = FakeClock(BASE)
    return InMemoryScraperRepository({spec.id: spec}, clock=clock), spec


@pytest.mark.asyncio
async def test_newest_first_is_the_reverse_and_limit_applies_after_the_finality_filter() -> (
    None
):
    repo, spec = _twin(horizon=3600)
    clock = repo._clock
    bars = [make_bar(BASE + _hours(h), h) for h in range(8)]
    await repo.commit_ok_read(
        spec,
        trigger="schedule",
        started_at=BASE,
        provider_time=BASE,
        bars=bars,
        gap_before=False,
    )
    # a read long after: all bars are final except the last two (close + 1h horizon)
    clock.now = BASE + _hours(8) + timedelta(seconds=1)
    await repo.commit_ok_read(
        spec,
        trigger="schedule",
        started_at=BASE,
        provider_time=clock.now,
        bars=bars[:6],
        gap_before=False,
    )
    asc = await repo.fetch_bars(spec.id, mode="final", limit=100)
    desc = await repo.fetch_bars(spec.id, mode="final", newest_first=True, limit=100)
    assert [b.bar_open for b in desc] == [b.bar_open for b in reversed(asc)]
    assert len(asc) == 6
    assert [b.bar_open for b in await repo.fetch_bars(spec.id, limit=2)] == [
        b.bar_open for b in asc[:2]
    ]
    assert [
        b.bar_open for b in await repo.fetch_bars(spec.id, newest_first=True, limit=2)
    ] == [b.bar_open for b in asc[-2:][::-1]]


@pytest.mark.asyncio
async def test_head_and_revision_counts_for_empty_and_failed_only_datasets() -> None:
    repo, spec = _twin()
    head = await repo.dataset_head(spec.id)
    assert (head.first_ok_read_finished_at, head.latest_ok_read) == (None, None)
    assert (head.first_bar_open, head.last_bar_open) == (None, None)
    assert await repo.revisions_after_horizon(spec.id) == 0
    await repo.record_failed_read(
        spec.id,
        trigger="schedule",
        started_at=BASE,
        error_code="timeout",
        error_detail="",
    )
    head = await repo.dataset_head(spec.id)
    assert head.latest_ok_read is None and head.first_ok_read_finished_at is None
    assert await repo.revisions_after_horizon(spec.id) == 0


def test_composed_statement_has_no_optional_predicates_or_joins() -> None:
    for mode in ("final", "as_of"):
        for start in (None, BASE):
            for end in (None, BASE):
                sql, args = compose_fetch_bars(
                    "d",
                    mode=mode,
                    as_of=BASE if mode == "as_of" else None,
                    start=start,
                    end=end,
                    newest_first=True,
                    final_gap_seconds=3600.0,
                    limit=5,
                )
                assert " IS NULL OR " not in sql.upper().replace("\n", " ")
                assert "JOIN" not in sql.upper()
                assert len(args) == 3 + (start is not None) + (end is not None) + (
                    mode == "as_of"
                )


# --- differential: SQL vs twin on identical data -------------------------------


class _Plan:
    def __init__(self, rng: random.Random, dataset_id: str, offset: int) -> None:
        self.spec = make_spec(
            id=dataset_id, finality_horizon_seconds=rng.choice([0, 3 * 3600, 12 * 3600])
        )
        hours = sorted(rng.sample(range(70), rng.randint(8, 40)))
        self.opens = [BASE + _hours(h) for h in hours]
        self.reads: list[dict] = []
        for _ in range(rng.randint(3, 25)):
            lo, hi = sorted(rng.sample(range(len(self.opens)), 2))
            finished = (
                BASE
                + _hours(rng.randint(5, 140))
                + timedelta(minutes=rng.randint(0, 59))
            )
            self.reads.append(
                {
                    "status": "ok" if rng.random() < 0.85 else "failed",
                    "covered_from": self.opens[lo],
                    "covered_to": self.opens[hi],
                    "finished_at": finished,
                }
            )
        for i, read in enumerate(self.reads, start=1):
            read["read_id"] = offset + i
        self.obs: list[dict] = []
        for open_ in self.opens:
            observed = open_ + _hours(1) + timedelta(minutes=rng.randint(0, 600))
            for seq in range(1, rng.choice([1, 1, 2, 3]) + 1):
                self.obs.append(
                    {
                        "bar": make_bar(
                            open_, seq * 31 + int(open_.timestamp() // 3600) % 17
                        ),
                        "seq": seq,
                        "observed_at": observed,
                        "read_id": offset + rng.randint(1, len(self.reads)),
                        "backfilled": rng.random() < 0.3,
                    }
                )
                observed += _hours(rng.randint(1, 30)) + timedelta(
                    minutes=rng.randint(0, 59)
                )

    def load_twin(self, repo: InMemoryScraperRepository) -> None:
        for read in self.reads:
            ok = read["status"] == "ok"
            repo._reads.append(
                ReadRecord(
                    read_id=read["read_id"],
                    dataset_id=self.spec.id,
                    trigger="schedule",
                    status=read["status"],
                    started_at=BASE,
                    finished_at=read["finished_at"],
                    provider_time=None,
                    covered_from=read["covered_from"] if ok else None,
                    covered_to=read["covered_to"] if ok else None,
                    bars_seen=0,
                    bars_written=0,
                    gap_before=False,
                    holes=0,
                    error_code=None if ok else "timeout",
                    error_detail=None,
                )
            )
        rows = repo._observations.setdefault(self.spec.id, {})
        for o in self.obs:
            rows.setdefault(o["bar"].bar_open, []).append(
                _Observation(
                    o["bar"], o["seq"], o["observed_at"], o["read_id"], o["backfilled"]
                )
            )

    async def load_pg(self, connection) -> None:
        for read in self.reads:
            ok = read["status"] == "ok"
            await connection.execute(
                "INSERT INTO scraper.reads (read_id, dataset_id, trigger, status, started_at, "
                "finished_at, covered_from, covered_to, error_code) OVERRIDING SYSTEM VALUE "
                "VALUES ($1, $2, 'schedule', $3, $4, $5, $6, $7, $8)",
                read["read_id"],
                self.spec.id,
                read["status"],
                BASE,
                read["finished_at"],
                read["covered_from"] if ok else None,
                read["covered_to"] if ok else None,
                None if ok else "timeout",
            )
        for o in self.obs:
            bar = o["bar"]
            await connection.execute(
                "INSERT INTO scraper.bar_observations (dataset_id, bar_open, seq, bar_close, "
                "open, high, low, close, volume, content_hash, observed_at, read_id, backfilled) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
                self.spec.id,
                bar.bar_open,
                o["seq"],
                bar.bar_close,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.content_hash,
                o["observed_at"],
                o["read_id"],
                o["backfilled"],
            )


async def _pg_pool():
    import asyncpg

    from apps.scraper_app.storage.bootstrap import apply_scraper_schema

    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=3)
    async with pool.acquire() as connection:
        await require_test_database(connection)
        await apply_scraper_schema(connection, "scraper-test-password")
        await connection.execute(
            "TRUNCATE scraper.payload_observations, scraper.bar_observations, scraper.reads RESTART IDENTITY"
        )
    return pool


def _variants(rng: random.Random, plan: _Plan, count: int):
    for _ in range(count):
        pick = lambda: rng.choice([None, *plan.opens])
        t = BASE + _hours(rng.randint(0, 150)) + timedelta(minutes=rng.randint(0, 59))
        yield {
            "mode": rng.choice(["final", "as_of"]),
            "as_of_t": t,
            "start": pick(),
            "end": pick(),
            "newest_first": rng.random() < 0.5,
            "limit": rng.choice([2, 5, 1000]),
        }


@needs_postgres
@pytest.mark.asyncio
async def test_sql_and_twin_agree_on_random_histories() -> None:
    rng = random.Random(20261009)
    plans = [_Plan(rng, f"d{i}", i * 1000) for i in range(40)]
    pool = await _pg_pool()
    try:
        specs = {p.spec.id: p.spec for p in plans}
        sql_repo = PostgresScraperRepository(pool, specs)
        twin = InMemoryScraperRepository(specs, clock=FakeClock(BASE))
        async with pool.acquire() as connection:
            for plan in plans:
                await plan.load_pg(connection)
        for plan in plans:
            plan.load_twin(twin)

        compared = 0
        non_empty = 0
        seen_final: set[bool] = set()
        seen_revised: set[bool] = set()
        for plan in plans:
            for v in _variants(rng, plan, 14):
                kwargs = {
                    "mode": v["mode"],
                    "as_of": v["as_of_t"] if v["mode"] == "as_of" else None,
                    "start": v["start"],
                    "end": v["end"],
                    "newest_first": v["newest_first"],
                    "limit": v["limit"],
                }
                got = await sql_repo.fetch_bars(plan.spec.id, **kwargs)
                want = await twin.fetch_bars(plan.spec.id, **kwargs)
                assert got == want, (plan.spec.id, kwargs)
                if got:
                    non_empty += 1
                    seen_final.update(b.is_final for b in got)
                    seen_revised.update(b.seq > 1 for b in got)
                compared += 1
            at = BASE + _hours(rng.randint(0, 150))
            for point in (None, at):
                assert await sql_repo.dataset_head(
                    plan.spec.id, at=point
                ) == await twin.dataset_head(plan.spec.id, at=point), plan.spec.id
            assert await sql_repo.revisions_after_horizon(plan.spec.id) == (
                await twin.revisions_after_horizon(plan.spec.id)
            )
        assert compared == 40 * 14
        # the random histories must exercise the interesting cases
        assert (
            non_empty > 150
            and seen_final == {True, False}
            and seen_revised == {True, False}
        )
        empty = make_spec(id="nothing")
        repo = PostgresScraperRepository(pool, {"nothing": empty})
        head = await repo.dataset_head("nothing")
        assert (
            head.latest_ok_read,
            head.first_bar_open,
            head.first_ok_read_finished_at,
        ) == (
            None,
            None,
            None,
        )
        assert await repo.revisions_after_horizon("nothing") == 0
    finally:
        await pool.close()


# --- scale and EXPLAIN ------------------------------------------------------

_SEED_READS = (
    "INSERT INTO scraper.reads (read_id, dataset_id, trigger, status, started_at, "
    "finished_at, covered_from, covered_to) OVERRIDING SYSTEM VALUE "
    "SELECT $3::bigint + n + 1, $1, 'schedule', 'ok', $2::timestamptz, "
    "$2::timestamptz + (n + 1) * interval '1 hour' + interval '30 seconds', "
    "$2::timestamptz + greatest(n - 336, 0) * interval '1 hour', "
    "$2::timestamptz + n * interval '1 hour' "
    "FROM generate_series(0, $4::int - 1) n"
)
_SEED_BARS = (
    "INSERT INTO scraper.bar_observations (dataset_id, bar_open, seq, bar_close, open, high, "
    "low, close, volume, content_hash, observed_at, read_id, backfilled) "
    "SELECT $1, $2::timestamptz + n * interval '1 hour', 1, "
    "$2::timestamptz + (n + 1) * interval '1 hour', 1, 10, 0, 2, 5, 'h' || n || '-1', "
    "$2::timestamptz + (n + 1) * interval '1 hour' + interval '30 seconds', "
    "$3::bigint + n + 1, false FROM generate_series(0, $4::int - 1) n "
    "UNION ALL "
    "SELECT $1, $2::timestamptz + n * interval '1 hour', 2, "
    "$2::timestamptz + (n + 1) * interval '1 hour', 1, 10, 0, 3, 5, 'h' || n || '-2', "
    "$2::timestamptz + (n + 2) * interval '1 hour' + interval '30 seconds', "
    "$3::bigint + n + 2, false FROM generate_series(0, $4::int - 2) n WHERE n % 5 = 0"
)
_SCALE_N = 12000
_T0 = utc(2024, 1, 1)


async def _seed(connection, dataset_id: str, offset: int, n: int) -> None:
    await connection.execute(_SEED_READS, dataset_id, _T0, offset, n)
    await connection.execute(_SEED_BARS, dataset_id, _T0, offset, n)


def _explain_variants(spec, newest_bar):
    for mode in ("final", "as_of"):
        for start in (None, _T0 + _hours(100)):
            for end in (None, _T0 + _hours(9000)):
                for newest_first in (False, True):
                    yield compose_fetch_bars(
                        spec.id,
                        mode=mode,
                        as_of=newest_bar if mode == "as_of" else None,
                        start=start,
                        end=end,
                        newest_first=newest_first,
                        final_gap_seconds=spec.finality_horizon_seconds
                        + spec.interval_seconds,
                        limit=5000,
                    )


async def _assert_no_joins(connection, spec) -> int:
    checked = 0
    for sql, args in _explain_variants(spec, _T0 + _hours(6000)):
        plan = "\n".join(r[0] for r in await connection.fetch("EXPLAIN " + sql, *args))
        for forbidden in ("Join", "Nested Loop", "SubPlan"):
            assert forbidden not in plan, (forbidden, plan)
        checked += 1
    return checked


@needs_postgres
@pytest.mark.asyncio
async def test_read_path_scales_and_plans_have_no_joins() -> None:
    horizon = 4 * 24 * 3600
    big = make_spec(id="big", finality_horizon_seconds=horizon)
    seeds = [
        make_spec(id=f"seed{i}", finality_horizon_seconds=horizon) for i in range(3)
    ]
    pool = await _pg_pool()
    timings: dict[str, float] = {}
    try:
        async with pool.acquire() as connection:
            for i, spec in enumerate(seeds):
                await _seed(connection, spec.id, 1_000_000 * (i + 1), 2000)
            await connection.execute("ANALYZE scraper.reads, scraper.bar_observations")
            # loaded after the ANALYZE: the planner believes "big" is tiny
            await _seed(connection, "big", 10_000_000, _SCALE_N)
            before = await _assert_no_joins(connection, big)
        repo = PostgresScraperRepository(pool, {s.id: s for s in [big, *seeds]})

        async def timed(name, coro):
            started = time.perf_counter()
            result = await asyncio.wait_for(coro, timeout=20)
            timings[name] = time.perf_counter() - started
            assert timings[name] < 2.0, (name, timings[name])
            return result

        final_bars = _SCALE_N - 96
        whole = await timed("final whole history", repo.fetch_bars("big", limit=20000))
        assert len(whole) == final_bars and whole[0].bar_open == _T0
        assert all(b.is_final for b in whole)
        assert (
            whole[0].seq == 2 and whole[1].seq == 1
        )  # a fifth of the bars are revised
        newest = await timed(
            "final newest 5000 newest first",
            repo.fetch_bars("big", newest_first=True, limit=5000),
        )
        assert len(newest) == 5000
        assert newest[0].bar_open == _T0 + _hours(final_bars - 1)
        oldest = await timed(
            "final oldest 5000 ascending", repo.fetch_bars("big", limit=5000)
        )
        assert len(oldest) == 5000 and oldest[-1].bar_open == _T0 + _hours(4999)
        t = _T0 + _hours(6000) + timedelta(seconds=45)
        known = await timed(
            "as_of mid-history, whole history",
            repo.fetch_bars("big", mode="as_of", as_of=t, limit=20000),
        )
        assert len(known) == 6000
        assert sum(b.is_final for b in known) == 5904
        revised = {b.bar_open: b.seq for b in known}
        assert revised[_T0 + _hours(5995)] == 2 and revised[_T0 + _hours(5999)] == 1

        async with pool.acquire() as connection:
            await connection.execute("ANALYZE scraper.reads, scraper.bar_observations")
            after = await _assert_no_joins(connection, big)
        assert before == after == 16
        again = await timed(
            "final whole history after ANALYZE", repo.fetch_bars("big", limit=20000)
        )
        assert len(again) == final_bars
        print("TIMINGS", {k: round(v, 3) for k, v in timings.items()})
    finally:
        await pool.close()
