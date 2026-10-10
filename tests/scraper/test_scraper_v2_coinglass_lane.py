"""The CoinGlass lane against a fake CDP engine on a real local socket."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from pydantic import ValidationError
from scraper_v2_coinglass_support import (
    FakeEngine,
    coinglass_raw,
    coinglass_settings,
    default_helper,
    eventually,
    update_time,
)
from scraper_v2_support import (
    FakeClock,
    FakeProvider,
    make_spec,
    tv_settings,
)

from apps.scraper_app.adapters.coinglass.client import CoinGlassClient
from apps.scraper_app.adapters.coinglass.cookies import CookieStore
from apps.scraper_app.domain import errors
from apps.scraper_app.runtime.coinglass import CoinGlassLane
from apps.scraper_app.runtime.collector import Collector
from apps.scraper_app.runtime.status import (
    DEGRADED,
    READY,
    CoinGlassReadiness,
    RuntimeState,
    compute_readiness,
)
from apps.scraper_app.settings import parse_settings
from apps.scraper_app.storage.repository import InMemoryScraperRepository

pytestmark = pytest.mark.asyncio
HEATMAP, MAXPAIN = "cg.btc.heatmap", "cg.maxpain"


class _Tick:
    """Clock a little past the recorded updateTime; every call moves it on."""

    def __init__(self) -> None:
        self.now = update_time("1429")

    def __call__(self):
        self.now += __import__("datetime").timedelta(milliseconds=50)
        return self.now


async def _noop_sleep(_: float) -> None:
    await asyncio.sleep(0)


def _lane(engine_url, *, cookies_path=None, **overrides):
    settings = coinglass_settings(engine_url, cookies_path=cookies_path, **overrides)
    clock = _Tick()
    repo = InMemoryScraperRepository({}, clock=clock)
    state = RuntimeState()
    store = CookieStore(cookies_path)
    client = CoinGlassClient(settings, cookies=store, clock=clock, sleep=_noop_sleep)
    lane = CoinGlassLane(
        specs=settings.payload_specs(),
        client=client,
        repository=repo,
        settings=settings,
        state=state,
        cookies=store,
        clock=clock,
        sleep=_noop_sleep,
    )
    return lane, repo, state


def _codes(repo) -> dict[str, str | None]:
    return {r.dataset_id: r.error_code for r in repo.reads}


@pytest_asyncio.fixture
async def engine():
    fake = await FakeEngine().start()
    yield fake
    await fake.stop()


async def test_a_cycle_stores_both_datasets_and_sweeps_stale_targets(engine) -> None:
    engine.targets = ["stale-1", "stale-2"]
    lane, repo, _ = _lane(engine.url)
    await lane.run_pass("catchup")
    assert _codes(repo) == {HEATMAP: None, MAXPAIN: None}
    assert {"stale-1", "stale-2"} <= set(engine.closed)
    assert engine.targets == []  # swept, and its own page closed afterwards
    assert len(repo.payloads) == 2
    ok = await repo.latest_ok_read(HEATMAP)
    assert ok.meta["module"] == "89390" and ok.meta["export"] == "EJf"
    methods = [m["method"] for m in engine.received]
    assert methods.index("Target.getTargets") < methods.index("Target.createTarget")
    assert "Network.setCacheDisabled" in methods and "Page.navigate" in methods


async def test_engine_restart_between_cycles_is_tolerated(engine) -> None:
    lane, repo, _ = _lane(engine.url)
    await lane.run_pass("schedule")
    port = engine.port
    await engine.stop()
    await lane.run_pass("schedule")
    assert [r.error_code for r in repo.reads[2:]] == [errors.ENGINE_UNREACHABLE] * 2
    await engine.start(port)
    await lane.run_pass("schedule")
    assert [r.status for r in repo.reads[4:]] == ["ok", "ok"]


async def _free_port() -> int:
    server = await asyncio.start_server(lambda *_: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


def _big_reply() -> str:
    return json.dumps({"id": 0, "pad": "x" * (3 << 20)})


FAILURES = {
    "refused": (errors.ENGINE_UNREACHABLE, None),
    "dns": (errors.ENGINE_UNREACHABLE, None),
    "closed_mid_evaluate": (
        errors.ENGINE_UNREACHABLE,
        lambda e: e.die_on.add("helper"),
    ),
    "evaluate_never_returns": (
        errors.HELPER_TIMEOUT,
        lambda e: e.hang.add("helper"),
    ),
    "hanging_close": (None, lambda e: e.hang.add("Target.closeTarget")),
    "oversize": (
        errors.PAYLOAD_TOO_LARGE,
        lambda e: setattr(e, "huge_reply", _big_reply()),
    ),
}


@pytest.mark.parametrize("mode", sorted(FAILURES))
async def test_lane_isolation(mode, engine) -> None:
    code, arrange = FAILURES[mode]
    if arrange:
        arrange(engine)
    url = engine.url
    if mode == "refused":
        url = f"http://127.0.0.1:{await _free_port()}"
    elif mode == "dns":
        url = "http://engine.invalid:9222"
    lane, repo, state = _lane(
        url, **({"max_payload_bytes": 1000} if mode == "oversize" else {})
    )
    tv = make_spec()
    clock = FakeClock(update_time("1429"))
    provider = FakeProvider([tv], lambda: clock.now)
    tv_repo = InMemoryScraperRepository({tv.id: tv}, clock=lambda: clock.now)
    collector = Collector(
        client=__import__(
            "apps.scraper_app.adapters.tradingview.client", fromlist=["x"]
        ).TradingViewClient(tv_settings(), connector=provider.connector()),
        repository=tv_repo,
        settings=tv_settings(),
        clock=lambda: clock.now,
    )
    outcome, _ = await asyncio.gather(
        collector.collect(tv, "schedule"), lane.run_pass("schedule")
    )
    assert outcome.ok  # a concurrent TradingView read is unaffected
    codes = [r.error_code for r in repo.reads]
    if mode == "hanging_close":
        assert codes == [None, None]
    else:
        assert len(codes) == 2 and codes[0] == code
        assert all(r.status == "failed" for r in repo.reads) and not repo.payloads
    if mode == "oversize":
        assert codes[1] in (errors.PAYLOAD_TOO_LARGE, errors.ENGINE_UNREACHABLE)
    # the loop itself never ends on an error
    task = asyncio.create_task(lane.run())
    await eventually(lambda: state.coinglass_catchup_done)
    assert not task.done()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_a_helper_failure_fails_only_that_dataset(engine) -> None:
    engine.helper = lambda p: (
        {
            "error": "helper_timeout",
            "module": "89390",
            "export": "EJf",
            "sourceLength": 90,
        }
        if p["endpoint"].endswith("liqHeatMap")
        else default_helper(p)
    )
    lane, repo, _ = _lane(engine.url)
    await lane.run_pass("schedule")
    assert _codes(repo) == {HEATMAP: errors.HELPER_TIMEOUT, MAXPAIN: None}
    assert repo.reads[0].meta == {
        "module": "89390",
        "export": "EJf",
        "source_length": 90,
        "attempts": 1,
    }


@pytest.mark.parametrize(
    "answer",
    [
        {"error": "module_count", "count": 0},
        {"error": "module_count", "count": 2},
        {"error": "export_count", "count": 0},
        {"error": "export_count", "count": 2},
        {"error": "no_registry"},
        {"error": "no_chunk_store"},
    ],
)
async def test_helper_lookup_failures_are_helper_missing(engine, answer) -> None:
    engine.helper = lambda p: answer
    lane, repo, _ = _lane(engine.url)
    await lane.run_pass("schedule")
    assert set(_codes(repo).values()) == {errors.HELPER_MISSING}


async def test_cycle_deadline_fails_unfinished_datasets(engine) -> None:
    engine.hang.add("Page.navigate")
    lane, repo, _ = _lane(
        engine.url, cycle_deadline_seconds=0.6, command_timeout_seconds=5
    )
    await lane.run_pass("schedule")
    assert set(_codes(repo).values()) == {errors.CYCLE_DEADLINE}


async def test_gate_failure_is_a_failed_read_without_payload(engine) -> None:
    engine.helper = lambda p: {
        **default_helper(p),
        "text": json.dumps({"code": "40000", "success": False}),
    }
    lane, repo, _ = _lane(engine.url)
    await lane.run_pass("schedule")
    assert set(_codes(repo).values()) == {errors.NOT_AUTHORIZED}
    assert not repo.payloads


class _Spy:
    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def __getattr__(self, name):
        self.calls.append(name)
        return getattr(self.inner, name)


async def test_readiness_is_degraded_not_unready_when_the_engine_is_down() -> None:
    lane, repo, state = _lane(f"http://127.0.0.1:{await _free_port()}")
    state.startup_catchup_done = True  # TradingView has caught up
    spy = _Spy(repo)
    cg = CoinGlassReadiness((HEATMAP, MAXPAIN), 2400)

    def report():
        return compute_readiness(
            specs=[],
            repository=spy,
            state=state,
            lock_held=lambda: True,
            clock=lambda: update_time("1429"),
            max_read_age_seconds=3600,
            coinglass=cg,
        )

    before = await report()
    assert before.status == DEGRADED and before.http_status == 200
    assert "coinglass_catchup_pending" in before.service_reasons
    await lane.run_pass("catchup")
    state.coinglass_catchup_done = True
    after = await report()
    assert after.status == DEGRADED and after.http_status == 200
    assert after.service_reasons == ()
    assert {d.last_error_code for d in after.datasets} == {errors.ENGINE_UNREACHABLE}
    assert set(spy.calls) <= {"latest_reads"}  # reads table only, one statement


async def test_multi_minute_update_lag_gives_no_skew_or_bar_reasons(engine) -> None:
    lane, repo, state = _lane(engine.url)
    state.startup_catchup_done = True
    await lane.run_pass("catchup")
    state.coinglass_catchup_done = True
    spy = _Spy(repo)
    now = update_time("1429") + __import__("datetime").timedelta(minutes=9)
    report = await compute_readiness(
        specs=[],
        repository=spy,
        state=state,
        lock_held=lambda: True,
        clock=lambda: now,
        max_read_age_seconds=3600,
        coinglass=CoinGlassReadiness((HEATMAP, MAXPAIN), 2400),
    )
    assert report.status == READY and report.clock_skew_seconds is None
    assert all(d.clock_skew_seconds is None and not d.reasons for d in report.datasets)
    assert set(spy.calls) <= {"latest_reads"}  # reads table only, one statement


COOKIES = [
    {
        "name": "sid",
        "value": "SECRET-ONE",
        "domain": ".coinglass.com",
        "path": "/",
        "sameSite": "lax",
    },
    {"name": "a", "value": "SECRET-TWO", "domain": "www.coinglass.com"},
    {"name": "b", "value": "SECRET-THREE", "domain": "coinglass.com"},
    {"name": "c", "value": "SECRET-FOUR", "domain": "evil.com"},
    {"name": "d", "value": "SECRET-FIVE", "domain": "notcoinglass.com"},
    {"name": "e", "value": "SECRET-SIX", "domain": "coinglass.com.evil.com"},
]


async def test_cookies_scope_logging_and_reload(engine, tmp_path, caplog) -> None:
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps(COOKIES))
    engine.errors["Network.setCookies"] = "bad cookie SECRET-ONE"
    caplog.set_level(logging.DEBUG)
    lane, repo, _ = _lane(engine.url, cookies_path=str(path))
    await lane.run_pass("schedule")
    # the engine refused the cookies: failed reads, and no value anywhere
    assert set(_codes(repo).values()) == {errors.ENGINE_ERROR}
    del engine.errors["Network.setCookies"]
    await lane.run_pass("schedule")
    batch = engine.cookie_batches[-1]
    assert sorted(c["domain"] for c in batch) == [
        ".coinglass.com",
        "coinglass.com",
        "www.coinglass.com",
    ]
    assert next(c for c in batch if c["name"] == "sid")["sameSite"] == "Lax"
    # reload on mtime change
    path.write_text(json.dumps(COOKIES[:1]))
    os.utime(path, (time.time() + 5, time.time() + 5))
    await lane.run_pass("schedule")
    assert len(engine.cookie_batches[-1]) == 1
    everything = caplog.text + " ".join(
        f"{r.error_detail} {r.meta}" for r in repo.reads
    )
    assert "SECRET" not in everything


async def test_missing_cookie_file_disables_login_datasets_only(
    engine, tmp_path
) -> None:
    raw = coinglass_raw(engine.url, cookies_path=str(tmp_path / "absent.json"))
    raw["datasets"].append(
        {
            **copy.deepcopy(raw["datasets"][0]),
            "id": "cg.eth.heatmap",
            "requires_login": True,
        }
    )
    from apps.scraper_app.settings import CoinGlassSettings

    settings = CoinGlassSettings.model_validate(raw)
    clock = _Tick()
    repo = InMemoryScraperRepository({}, clock=clock)
    state = RuntimeState()
    store = CookieStore(settings.cookies_path)
    lane = CoinGlassLane(
        specs=settings.payload_specs(),
        client=CoinGlassClient(settings, cookies=store, clock=clock, sleep=_noop_sleep),
        repository=repo,
        settings=settings,
        state=state,
        cookies=store,
        clock=clock,
        sleep=_noop_sleep,
    )
    assert state.coinglass_disabled == {"cg.eth.heatmap"}
    await lane.run_pass("schedule")
    assert _codes(repo) == {HEATMAP: None, MAXPAIN: None}
    state.coinglass_catchup_done = state.startup_catchup_done = True
    report = await compute_readiness(
        specs=[],
        repository=repo,
        state=state,
        lock_held=lambda: True,
        clock=clock,
        max_read_age_seconds=3600,
        coinglass=CoinGlassReadiness((HEATMAP, MAXPAIN, "cg.eth.heatmap"), 2400),
    )
    disabled = next(d for d in report.datasets if d.dataset_id == "cg.eth.heatmap")
    assert disabled.disabled and not disabled.degraded and report.status == READY


def test_settings_lane_is_off_without_the_block_and_strict_with_it() -> None:
    raw = copy.deepcopy(
        yaml.safe_load(Path("configs/scraper.yaml").read_text())["scraper"]
    )
    del raw["coinglass"]
    absent = parse_settings(raw)
    assert absent.coinglass is None and absent.payload_specs() == ()
    raw["coinglass"] = coinglass_raw()
    ok = parse_settings(raw)
    assert [s.id for s in ok.payload_specs()] == [HEATMAP, MAXPAIN]
    dup = copy.deepcopy(raw)
    dup["coinglass"]["datasets"][1]["id"] = ok.datasets[0].id
    with pytest.raises(ValidationError):
        parse_settings(dup)
    for mutate in (
        lambda r: r["coinglass"].update(extra=1),
        lambda r: r["coinglass"]["datasets"][0].update(extra=1),
        lambda r: r["coinglass"]["datasets"][0].pop("expect"),
        lambda r: r["coinglass"]["readiness"].update(extra=1),
    ):
        bad = copy.deepcopy(raw)
        mutate(bad)
        with pytest.raises(ValidationError):
            parse_settings(bad)


@pytest.mark.skipif(
    os.environ.get("SCRAPER_LIVE_COINGLASS") != "1"
    or not os.environ.get("SCRAPER_ENGINE_URL"),
    reason="set SCRAPER_LIVE_COINGLASS=1 and SCRAPER_ENGINE_URL for a real cycle",
)
async def test_live_one_real_cycle() -> None:
    from datetime import UTC, datetime

    raw = coinglass_raw(
        os.environ["SCRAPER_ENGINE_URL"],
        navigation_timeout_seconds=30,
        helper_timeout_seconds=20,
        command_timeout_seconds=30,
        cycle_deadline_seconds=90,
    )
    raw["datasets"][0]["expect"]["columns"] = 288
    from apps.scraper_app.settings import CoinGlassSettings

    settings = CoinGlassSettings.model_validate(raw)
    clock = lambda: datetime.now(UTC)
    repo = InMemoryScraperRepository({}, clock=clock)
    store = CookieStore(None)
    lane = CoinGlassLane(
        specs=settings.payload_specs(),
        client=CoinGlassClient(settings, cookies=store, clock=clock),
        repository=repo,
        settings=settings,
        state=RuntimeState(),
        cookies=store,
        clock=clock,
    )
    await lane.run_pass("catchup")
    assert [r.status for r in repo.reads] == ["ok", "ok"], [
        r.error_code for r in repo.reads
    ]


LIQMAP = "cg.binance.btcusdt.liq_map.1d"


def _with_liq_map(raw: dict) -> dict:
    raw["datasets"].append(
        {
            "id": LIQMAP,
            "kind": "liq_map",
            "endpoint": "/api/index/5/liqMap",
            "args": {
                "merge": True,
                "symbol": "Binance_BTCUSDT",
                "interval": 1,
                "limit": 1500,
            },
            "expect": {"exchange": "Binance", "instrument": "BTCUSDT"},
            "requires_login": True,
        }
    )
    return raw


def _lane_for(raw: dict, runner=None, *, cookies_path=None, sleeps=None):
    from apps.scraper_app.settings import CoinGlassSettings

    settings = CoinGlassSettings.model_validate(raw)
    clock = _Tick()
    repo = InMemoryScraperRepository({}, clock=clock)
    state = RuntimeState()
    store = CookieStore(cookies_path)

    async def sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    client = runner or CoinGlassClient(
        settings, cookies=store, clock=clock, sleep=sleep
    )
    lane = CoinGlassLane(
        specs=settings.payload_specs(),
        client=client,
        repository=repo,
        settings=settings,
        state=state,
        cookies=store,
        clock=clock,
        sleep=sleep,
    )
    return lane, repo, state


async def test_liq_map_is_stored_with_instant_bounds_and_skipped_without_cookies(
    engine, tmp_path
) -> None:
    raw = _with_liq_map(coinglass_raw(engine.url))
    lane, repo, state = _lane_for(raw, cookies_path=str(tmp_path / "absent.json"))
    assert LIQMAP in state.coinglass_disabled
    await lane.run_pass("schedule")
    assert LIQMAP not in _codes(repo)
    cookies = tmp_path / "cookies.json"
    cookies.write_text(
        json.dumps([{"name": "obe", "value": "SECRET-X", "domain": ".coinglass.com"}])
    )
    raw = _with_liq_map(coinglass_raw(engine.url, cookies_path=str(cookies)))
    lane, repo, state = _lane_for(raw, cookies_path=str(cookies))
    assert LIQMAP not in state.coinglass_disabled
    await lane.run_pass("schedule")
    assert _codes(repo)[LIQMAP] is None
    ok = await repo.latest_ok_read(LIQMAP)
    assert ok.provider_time is None and ok.covered_from == ok.covered_to
    assert ok.bars_seen == 174 and len(repo.payloads) == 3


class _Runner:
    """Stands in for the client: fails N attempts before the first helper call."""

    def __init__(self, settings, failures: int, *, helper_error=False) -> None:
        self.failures, self.attempts, self.helper_error = failures, 0, helper_error
        self._clock = _Tick()

    async def run_cycle(self, requests, results) -> None:
        from apps.scraper_app.adapters.coinglass.helper import HelperResult
        from apps.scraper_app.domain.errors import ScraperError

        self.attempts += 1
        if self.attempts <= self.failures:
            raise ScraperError(
                errors.NAVIGATION_FAILED, "net::ERR_HTTP_RESPONSE_CODE_FAILURE"
            )
        for i, request in enumerate(requests):
            if self.helper_error:
                results[i] = ScraperError(errors.HELPER_MISSING, "module_count")
                continue
            reply = default_helper({"endpoint": request.endpoint})
            results[i] = HelperResult(reply["text"], "89390", "EJf", 90, self._clock())


def _retry_raw(**kw):
    return coinglass_raw(cycle_retries=1, cycle_retry_delay_seconds=20, **kw)


async def test_cycle_retry_succeeds_on_the_second_attempt(caplog) -> None:
    raw = _retry_raw()
    sleeps: list[float] = []
    runner = _Runner(None, failures=1)
    lane, repo, _ = _lane_for(raw, runner, sleeps=sleeps)
    caplog.set_level(logging.WARNING)
    await lane.run_pass("schedule")
    assert _codes(repo) == {HEATMAP: None, MAXPAIN: None}
    assert [r.meta["attempts"] for r in repo.reads] == [2, 2]
    assert sleeps == [20]
    retries = [r for r in caplog.records if "retrying" in r.getMessage()]
    assert len(retries) == 1 and retries[0].levelno == logging.WARNING


async def test_both_attempts_failing_records_the_final_attempt_only() -> None:
    sleeps: list[float] = []
    runner = _Runner(None, failures=5)
    lane, repo, _ = _lane_for(_retry_raw(), runner, sleeps=sleeps)
    await lane.run_pass("schedule")
    assert runner.attempts == 2 and sleeps == [20]
    assert len(repo.reads) == 2
    assert {r.error_code for r in repo.reads} == {errors.NAVIGATION_FAILED}
    assert all(r.meta == {"attempts": 2} for r in repo.reads)


async def test_a_helper_level_failure_is_not_retried() -> None:
    sleeps: list[float] = []
    runner = _Runner(None, failures=0, helper_error=True)
    lane, repo, _ = _lane_for(_retry_raw(), runner, sleeps=sleeps)
    await lane.run_pass("schedule")
    assert runner.attempts == 1 and sleeps == []
    assert {r.error_code for r in repo.reads} == {errors.HELPER_MISSING}
    assert all(r.meta["attempts"] == 1 for r in repo.reads)


async def test_no_retries_by_default() -> None:
    runner = _Runner(None, failures=1)
    lane, repo, _ = _lane_for(coinglass_raw(), runner)
    await lane.run_pass("schedule")
    assert runner.attempts == 1
    assert {r.error_code for r in repo.reads} == {errors.NAVIGATION_FAILED}
