"""Collector: request sizing, gate integration, catch-up, revisions, failure records."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
from scraper_v2_support import (
    FakeClock,
    FakeProvider,
    ReplayTransport,
    connector_for,
    dec,
    load_fixture,
    make_spec,
    production_settings,
    synth_exchange,
    tv_settings,
    utc,
)

from apps.scraper_app.adapters.tradingview.client import TradingViewClient
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.datasets import Shape
from apps.scraper_app.runtime.collector import Collector, request_size
from apps.scraper_app.storage.repository import InMemoryScraperRepository

NOW = utc(2026, 10, 9, 6, 17, 39)
SETTINGS = tv_settings()


def _rig(specs, *, start=NOW):
    clock = FakeClock(start)
    provider = FakeProvider(list(specs), clock)
    repo = InMemoryScraperRepository({s.id: s for s in specs}, clock=clock)
    client = TradingViewClient(SETTINGS, connector=provider.connector())
    collector = Collector(
        client=client, repository=repo, settings=SETTINGS, clock=clock
    )
    return clock, provider, repo, collector


# --- request sizing --------------------------------------------------------


def test_request_size_uses_initial_bars_without_history() -> None:
    spec = make_spec(initial_bars=4000)
    assert (
        request_size(spec, SETTINGS, now=NOW, last_bar_open=None, last_covered_to=None)
        == 4000
    )


def test_request_size_follows_the_watch_window_not_the_horizon() -> None:
    spec = make_spec(finality_horizon_seconds=3600, revision_watch_seconds=172800)
    recent = NOW - timedelta(hours=1)
    # anchor = now - 48h (older than covered_to): 48 bars + 3 margin
    size = request_size(
        spec, SETTINGS, now=NOW, last_bar_open=recent, last_covered_to=recent
    )
    assert size == 48 + 3
    # the horizon alone would have given the minimum
    no_watch = make_spec(finality_horizon_seconds=3600, revision_watch_seconds=3600)
    assert (
        request_size(
            no_watch, SETTINGS, now=NOW, last_bar_open=recent, last_covered_to=recent
        )
        == SETTINGS.min_bars_per_request
    )


def test_request_size_reaches_back_over_an_outage_longer_than_the_watch_window() -> (
    None
):
    spec = make_spec(revision_watch_seconds=172800)
    old = NOW - timedelta(hours=100)
    size = request_size(spec, SETTINGS, now=NOW, last_bar_open=old, last_covered_to=old)
    assert size == 100 + 3


def test_request_size_first_load_is_unchanged_by_the_watch_window() -> None:
    spec = make_spec(initial_bars=4000, revision_watch_seconds=2592000)
    assert (
        request_size(spec, SETTINGS, now=NOW, last_bar_open=None, last_covered_to=None)
        == 4000
    )


def test_request_size_is_clamped() -> None:
    short = make_spec(finality_horizon_seconds=0, revision_watch_seconds=0)
    covered = NOW - timedelta(hours=1)
    assert (
        request_size(
            short, SETTINGS, now=NOW, last_bar_open=covered, last_covered_to=covered
        )
        == SETTINGS.min_bars_per_request
    )
    ancient = NOW - timedelta(days=3650)
    assert (
        request_size(
            short, SETTINGS, now=NOW, last_bar_open=ancient, last_covered_to=ancient
        )
        == SETTINGS.max_bars_per_request
    )


# --- full pass ------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pass_over_the_twenty_datasets_stores_closed_bars_only() -> None:
    specs = [
        dataclasses.replace(s, initial_bars=40)
        for s in production_settings().dataset_specs()
    ]
    assert len(specs) == 20
    clock, provider, repo, collector = _rig(specs)

    for spec in specs:
        outcome = await collector.collect(spec, "catchup")
        assert outcome.ok, (spec.id, outcome.error_code)

    now = int(NOW.timestamp())
    for spec in specs:
        step = spec.interval_seconds
        forming_open = now - now % step
        stored = await repo.fetch_bars(
            spec.id, mode="as_of", as_of=clock.now, limit=1000
        )
        opens = [int(b.bar_open.timestamp()) for b in stored]
        assert opens, spec.id
        assert forming_open not in opens, f"forming bar stored for {spec.id}"
        assert opens[-1] == forming_open - step, spec.id
        assert all(o + step <= now for o in opens)
        assert len(stored) == 39  # 40 requested, newest dropped
    assert len(provider.opened) == 20
    assert all(t.closed for t in provider.opened)


@pytest.mark.asyncio
async def test_recorded_exchanges_are_collected_and_the_forming_bar_is_not_stored() -> (
    None
):
    cases = [
        ("index_total3_1h", make_spec(), "60", 1791526659, 5),
        (
            "oi_btc_alias_1h",
            make_spec(
                id="oi",
                request_symbol="BINANCE:BTCUSDTPERP_OI",
                canonical_symbol="BINANCE:BTCUSDT.P_OI",
                shape=Shape.OHLC,
                finality_horizon_seconds=0,
            ),
            "60",
            1791526665,
            5,
        ),
        (
            "funding_btc_1h",
            make_spec(
                id="fr",
                request_symbol="BINANCE:BTCUSDT.P_FR",
                canonical_symbol="BINANCE:BTCUSDT.P_FR",
                shape=Shape.OHLC,
                contiguous=False,
                non_negative=False,
                finality_horizon_seconds=0,
            ),
            "60",
            1791526666,
            5,
        ),
    ]
    for name, spec, _resolution, provider_time, count in cases:
        fixture = load_fixture(name)
        clock = FakeClock(utc(2026, 10, 9, 6, 17, 40))
        repo = InMemoryScraperRepository({spec.id: spec}, clock=clock)

        async def connect(fixture=fixture):
            return ReplayTransport(fixture["received"])

        collector = Collector(
            client=TradingViewClient(SETTINGS, connector=connect),
            repository=repo,
            settings=SETTINGS,
            clock=clock,
        )
        outcome = await collector.collect(spec, "schedule")
        assert outcome.ok, (name, outcome.error_code)
        assert outcome.provider_time.timestamp() == provider_time
        stored = await repo.fetch_bars(spec.id, mode="as_of", as_of=clock.now, limit=50)
        assert len(stored) == count
        assert utc(2026, 10, 9, 6) not in {b.bar_open for b in stored}


# --- failures store nothing ----------------------------------------------


@pytest.mark.asyncio
async def test_identity_mismatch_stores_nothing_and_records_the_failure() -> None:
    spec = make_spec()
    _, provider, repo, collector = _rig([spec])
    provider.pro_name_overrides[spec.request_symbol] = "CRYPTOCAP:TOTAL2"

    outcome = await collector.collect(spec, "schedule")

    assert not outcome.ok and outcome.error_code == errors.IDENTITY_MISMATCH
    assert repo.observation_count(spec.id) == 0
    (read,) = repo.reads
    assert (read.status, read.error_code) == ("failed", errors.IDENTITY_MISMATCH)
    assert read.provider_time is not None


@pytest.mark.asyncio
async def test_error_frame_timeout_and_missing_completion_store_nothing() -> None:
    spec = make_spec()
    clock = FakeClock(NOW)
    repo = InMemoryScraperRepository({spec.id: spec}, clock=clock)

    async def run(connector, settings=SETTINGS):
        collector = Collector(
            client=TradingViewClient(settings, connector=connector),
            repository=repo,
            settings=settings,
            clock=clock,
        )
        return await collector.collect(spec, "schedule")

    provider = FakeProvider([spec], clock)
    provider.fail_symbols.add(spec.request_symbol)
    assert (await run(provider.connector())).error_code == errors.SYMBOL_ERROR

    messages = synth_exchange(
        pro_name=spec.canonical_symbol,
        provider_time=int(NOW.timestamp()),
        bars=[],
        completed=False,
    )
    hanging = ReplayTransport(messages, hang_after=True)
    fast = tv_settings(read_deadline_seconds=0.05)
    assert (await run(connector_for(hanging), fast)).error_code == errors.TIMEOUT

    incomplete = ReplayTransport(messages)
    assert (await run(connector_for(incomplete))).error_code == errors.INCOMPLETE

    assert repo.observation_count(spec.id) == 0
    assert [r.status for r in repo.reads] == ["failed"] * 3


@pytest.mark.asyncio
async def test_storage_failure_is_recorded_as_storage_error() -> None:
    spec = make_spec()
    clock, provider, _repo, _ = _rig([spec])

    class Exploding(InMemoryScraperRepository):
        async def commit_ok_read(self, *args, **kwargs):
            raise RuntimeError("disk full")

    broken = Exploding({spec.id: spec}, clock=clock)
    collector = Collector(
        client=TradingViewClient(SETTINGS, connector=provider.connector()),
        repository=broken,
        settings=SETTINGS,
        clock=clock,
    )
    outcome = await collector.collect(spec, "schedule")
    assert outcome.error_code == errors.STORAGE_ERROR
    assert broken.observation_count(spec.id) == 0
    assert broken.reads[0].error_code == errors.STORAGE_ERROR


# --- catch-up -------------------------------------------------------------


class _CountingRepo(InMemoryScraperRepository):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.commits: list[list] = []

    async def commit_ok_read(self, spec, *, bars, **kwargs):
        self.commits.append([b.bar_open for b in bars])
        return await super().commit_ok_read(spec, bars=bars, **kwargs)


@pytest.mark.asyncio
async def test_after_an_outage_missed_and_new_bars_are_written_in_one_commit_in_order() -> (
    None
):
    spec = make_spec(initial_bars=30, finality_horizon_seconds=0)
    clock = FakeClock(utc(2026, 10, 9, 10, 0, 30))
    provider = FakeProvider([spec], clock)
    repo = _CountingRepo({spec.id: spec}, clock=clock)
    collector = Collector(
        client=TradingViewClient(SETTINGS, connector=provider.connector()),
        repository=repo,
        settings=SETTINGS,
        clock=clock,
    )
    assert (await collector.collect(spec, "schedule")).ok
    last_before = await repo.last_bar_open(spec.id)
    assert last_before == utc(2026, 10, 9, 9)
    repo.commits.clear()

    clock.now = utc(2026, 10, 9, 16, 0, 30)  # six hours asleep
    outcome = await collector.collect(spec, "catchup")

    assert outcome.ok and not outcome.gap_before
    (committed,) = repo.commits  # one transaction
    assert committed == sorted(committed)
    new_opens = [o for o in committed if o > last_before]
    assert new_opens == [utc(2026, 10, 9, h) for h in range(10, 16)]
    new_rows = [
        row
        for rows in repo._observations[spec.id].values()
        for row in rows
        if row.bar.bar_open > last_before
    ]
    assert {row.read_id for row in new_rows} == {repo.reads[-1].read_id}
    assert len({row.observed_at for row in new_rows}) == 1
    # the request reached back over the outage
    assert provider.requests[-1][2] >= 7


@pytest.mark.asyncio
async def test_unbridgeable_gap_is_stored_with_gap_before_and_logged(caplog) -> None:
    spec = make_spec(initial_bars=30, finality_horizon_seconds=0)
    clock, provider, repo, collector = _rig([spec], start=utc(2026, 10, 9, 10, 0, 30))
    assert (await collector.collect(spec, "schedule")).ok

    provider.history_limit = 12
    clock.now = utc(2026, 10, 12, 10, 0, 30)  # 72h later, provider keeps only 12 bars
    with caplog.at_level("ERROR"):
        outcome = await collector.collect(spec, "catchup")

    assert outcome.ok and outcome.gap_before
    assert repo.reads[-1].gap_before is True
    assert any("does not reach back" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_non_contiguous_dataset_never_sets_gap_before() -> None:
    spec = make_spec(
        id="fr",
        request_symbol="BINANCE:BTCUSDT.P_FR",
        canonical_symbol="BINANCE:BTCUSDT.P_FR",
        shape=Shape.OHLC,
        contiguous=False,
        non_negative=False,
        finality_horizon_seconds=0,
        initial_bars=30,
    )
    clock, provider, _repo, collector = _rig([spec], start=utc(2026, 10, 9, 10, 0, 30))
    assert (await collector.collect(spec, "schedule")).ok
    provider.history_limit = 12
    clock.now = utc(2026, 10, 12, 10, 0, 30)
    outcome = await collector.collect(spec, "catchup")
    assert outcome.ok and not outcome.gap_before


@pytest.mark.asyncio
async def test_a_revised_closed_bar_creates_seq_2() -> None:
    spec = make_spec(initial_bars=30, finality_horizon_seconds=86400)
    clock, provider, repo, collector = _rig([spec], start=utc(2026, 10, 9, 10, 0, 30))
    assert (await collector.collect(spec, "schedule")).ok
    revised_open = int(utc(2026, 10, 9, 9).timestamp())
    clock.now += timedelta(hours=1)
    provider.revisions[(spec.request_symbol, revised_open)] = (
        dec(900),
        dec(950),
        dec(850),
        dec(910),
        dec(5),
    )
    outcome = await collector.collect(spec, "schedule")
    assert outcome.ok and outcome.bars_written >= 1

    stored = await repo.fetch_bars(
        spec.id,
        mode="as_of",
        as_of=clock.now,
        start=utc(2026, 10, 9, 9),
        end=utc(2026, 10, 9, 10),
        limit=5,
    )
    assert [(b.seq, b.revision_count) for b in stored] == [(2, 1)]


@pytest.mark.asyncio
async def test_an_unclassified_exception_is_recorded_as_a_failed_read(caplog) -> None:
    spec = make_spec()
    clock = FakeClock(NOW)
    repo = InMemoryScraperRepository({spec.id: spec}, clock=clock)

    class Boom:
        async def fetch_series(self, *_args):
            raise ValueError("surprise")

    collector = Collector(
        client=Boom(), repository=repo, settings=SETTINGS, clock=clock
    )
    with caplog.at_level("WARNING"):
        outcome = await collector.collect(spec, "schedule")

    assert not outcome.ok and outcome.error_code == errors.PROTOCOL_ERROR
    (read,) = repo.reads
    assert read.status == "failed" and "surprise" in (read.error_detail or "")
    record = next(r for r in caplog.records if "read failed" in r.getMessage())
    assert record.name.startswith("flipper_agent.")
    assert (
        spec.id in record.getMessage() and errors.PROTOCOL_ERROR in record.getMessage()
    )


@pytest.mark.asyncio
async def test_a_hole_in_provider_history_is_stored_and_counted() -> None:
    spec = make_spec(initial_bars=30, finality_horizon_seconds=0)
    _clock, provider, repo, collector = _rig([spec], start=utc(2026, 10, 9, 10, 0, 30))
    hole = utc(2026, 10, 9, 3)
    provider.skip_times.add(int(hole.timestamp()))

    outcome = await collector.collect(spec, "schedule")

    assert outcome.ok
    assert repo.reads[-1].holes == 1
    assert await repo.contiguous_from(spec.id) == hole + timedelta(hours=1)
    assert await repo.first_bar_open(spec.id) < hole
