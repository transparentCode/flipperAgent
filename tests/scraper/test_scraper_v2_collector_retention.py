"""With a TradingView retention the collector never stores bars the purge would delete."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from scraper_v2_support import (
    FakeClock,
    FakeProvider,
    epoch,
    make_bar,
    make_spec,
    require_test_database,
    tv_settings,
    utc,
)

from apps.scraper_app.adapters.tradingview.client import TradingViewClient
from apps.scraper_app.runtime.collector import Collector
from apps.scraper_app.storage.repository import (
    InMemoryScraperRepository,
    PostgresScraperRepository,
)

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
NOW = utc(2026, 10, 9, 6, 17, 39)
CUTOFF = NOW - timedelta(days=14)
SETTINGS = tv_settings()


def _rig(spec, retention_days, provider_setup=None):
    clock = FakeClock(NOW)
    provider = FakeProvider([spec], clock)
    if provider_setup:
        provider_setup(provider)
    repo = InMemoryScraperRepository({spec.id: spec}, clock=clock)
    collector = Collector(
        client=TradingViewClient(SETTINGS, connector=provider.connector()),
        repository=repo,
        settings=SETTINGS,
        clock=clock,
        retention_days=retention_days,
    )
    return clock, provider, repo, collector


@pytest.mark.asyncio
async def test_sparse_series_stores_nothing_older_than_the_cutoff() -> None:
    # A bar only every 8th interval; a request sized in hours reaches far back.
    spec = make_spec(
        id="t.sparse.1h",
        contiguous=False,
        initial_bars=1000,
        revision_watch_seconds=172800,
    )

    def sparse(provider):
        provider.skip_times = {
            t
            for t in range(epoch(NOW) // 3600 * 3600 - 400 * 3600, epoch(NOW), 3600)
            if (t // 3600) % 8
        }

    _, _, repo, collector = _rig(spec, 14, sparse)
    assert (await collector.collect(spec, "catchup")).ok
    read = await repo.latest_ok_read(spec.id)
    assert await repo.first_bar_open(spec.id) >= CUTOFF
    assert 0 < repo.observation_count(spec.id) < read.bars_seen  # seen = provider count
    assert read.covered_from >= CUTOFF and read.bars_written == repo.observation_count(
        spec.id
    )
    again = await collector.collect(spec, "schedule")
    assert again.ok and await repo.first_bar_open(spec.id) >= CUTOFF


@pytest.mark.asyncio
async def test_daily_series_with_the_sizing_margin_and_the_first_load_are_cut() -> None:
    spec = make_spec(
        id="t.daily.1d",
        interval="1D",
        initial_bars=40,
        finality_horizon_seconds=604800,
        revision_watch_seconds=1036800,
    )
    clock, _, repo, collector = _rig(spec, 14)
    assert (await collector.collect(spec, "catchup")).ok  # first load asks for 40
    first = await repo.latest_ok_read(spec.id)
    assert first.bars_seen == 39 and repo.observation_count(spec.id) <= 15
    assert await repo.first_bar_open(spec.id) >= CUTOFF
    clock.now = NOW + timedelta(hours=1)
    assert (await collector.collect(spec, "schedule")).ok  # 12 d + 3 margin = 15 d back
    cutoff = clock.now - timedelta(days=14)
    assert await repo.first_bar_open(spec.id) >= cutoff - timedelta(days=1)
    stored = await repo.fetch_bars(spec.id, mode="as_of", as_of=clock.now, limit=100)
    assert all(b.bar_open >= CUTOFF for b in stored)


@pytest.mark.asyncio
async def test_the_newest_bar_is_kept_when_every_bar_is_older_than_the_cutoff() -> None:
    spec = make_spec(id="t.old.1h", initial_bars=30)
    _, _, repo, collector = _rig(spec, 0)  # cutoff = now: every closed bar is older
    assert (await collector.collect(spec, "catchup")).ok
    assert repo.observation_count(spec.id) == 1
    read = await repo.latest_ok_read(spec.id)
    assert read.covered_from == read.covered_to and read.bars_seen == 29


@pytest.mark.asyncio
async def test_holes_and_gap_come_from_the_stored_bars_and_none_means_unchanged() -> (
    None
):
    spec = make_spec(id="t.holes.1h", initial_bars=500)
    old_hole = epoch(NOW) - 400 * 3600  # far before the cutoff

    def hole(provider):
        provider.skip_times = {t - t % 3600 for t in (old_hole,)}

    _, _, repo, collector = _rig(spec, 14, hole)
    assert (await collector.collect(spec, "catchup")).ok
    kept = await repo.latest_ok_read(spec.id)
    assert (kept.holes, kept.gap_before) == (0, False)
    assert kept.bars_seen > repo.observation_count(spec.id)

    _, _, plain_repo, plain = _rig(spec, None, hole)
    assert (await plain.collect(spec, "catchup")).ok
    plain_read = await plain_repo.latest_ok_read(spec.id)
    assert plain_read.holes == 1
    assert plain_repo.observation_count(spec.id) == plain_read.bars_seen  # unchanged
    assert await plain_repo.first_bar_open(spec.id) < CUTOFF


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_bars_seen_override_is_recorded_on_both_backends(backend) -> None:
    spec = make_spec(id="t.seen.1h")
    bars = [make_bar(utc(2026, 10, 1) + timedelta(hours=i), i) for i in range(3)]
    kwargs = {
        "trigger": "schedule",
        "started_at": NOW,
        "provider_time": NOW,
        "gap_before": False,
    }
    if backend == "memory":
        repo = InMemoryScraperRepository({spec.id: spec}, clock=FakeClock(NOW))
        outcome = await repo.commit_ok_read(spec, bars=bars, bars_seen=10, **kwargs)
        assert outcome.bars_seen == 10 and outcome.bars_written == 3
        assert (await repo.latest_ok_read(spec.id)).bars_seen == 10
        return
    if not POSTGRES_URI:
        pytest.skip("SCRAPER_TEST_POSTGRES_URI not set")
    import asyncpg

    from apps.scraper_app.storage import bootstrap

    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)
    try:
        async with pool.acquire() as c:
            await require_test_database(c)
            await bootstrap.apply_scraper_schema(c, "scraper-test-password")
            await c.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, "
                "scraper.reads RESTART IDENTITY"
            )
        repo = PostgresScraperRepository(pool, {spec.id: spec})
        outcome = await repo.commit_ok_read(spec, bars=bars, bars_seen=10, **kwargs)
        assert outcome.bars_seen == 10 and outcome.bars_written == 3
        assert (await repo.latest_ok_read(spec.id)).bars_seen == 10
        default = await repo.commit_ok_read(spec, bars=bars, **kwargs)
        assert default.bars_seen == 3
    finally:
        await pool.close()
