"""Audit fixes, round A: gate failures, readiness liveness, lock recovery, API edges."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from datetime import timedelta

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError
from scraper_v2_coinglass_support import (
    coinglass_raw,
    default_helper,
    heatmap_spec,
    heatmap_text,
    maxpain_spec,
    update_time,
)
from scraper_v2_support import REPO_ROOT
from test_scraper_v2_api import (
    BARS,
    HEATMAP,
    NOW,
    OLD_OPEN,
    SETTINGS,
    World,
    iso,
    seeded,
)
from test_scraper_v2_coinglass_lane import _codes, _lane_for, _Tick
from test_scraper_v2_singleton_status import _Conn, _lock, _Server

from apps.scraper_app.adapters.coinglass.cdp import CdpConnection
from apps.scraper_app.adapters.coinglass.helper import (
    HelperResult,
    interpret_result,
)
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError
from apps.scraper_app.domain.payloads import canonical_json, gate_payload
from apps.scraper_app.http_api.app import create_app
from apps.scraper_app.runtime import coinglass as coinglass_module
from apps.scraper_app.runtime.status import ReadinessReport, ReadinessService
from apps.scraper_app.settings import parse_settings


def _gate(text: str, spec=None):
    return gate_payload(
        spec or heatmap_spec(),
        text,
        returned_at=update_time("1429"),
        max_payload_bytes=5_000_000,
        max_age_seconds=900,
    )


# --- F1 ------------------------------------------------------------------------


def _scaled_heatmap(factor: int) -> str:
    envelope = json.loads(heatmap_text("1429"))
    for row in envelope["data"]["prices"]:
        row[0] *= factor
    return json.dumps(envelope)


def test_millisecond_column_times_are_payload_invalid() -> None:
    with pytest.raises(ScraperError) as caught:
        _gate(_scaled_heatmap(1000))
    assert caught.value.code == errors.PAYLOAD_INVALID


def test_column_times_outside_the_update_window_are_payload_invalid() -> None:
    envelope = json.loads(heatmap_text("1429"))
    for row in envelope["data"]["prices"]:
        row[0] += 3 * 86400 // 300 * 300 * -1  # three days before updateTime
    with pytest.raises(ScraperError) as caught:
        _gate(json.dumps(envelope))
    assert caught.value.code == errors.PAYLOAD_INVALID
    assert "update window" in caught.value.detail
    assert _gate(heatmap_text("1429")).bars_seen > 0


def test_deeply_nested_values_are_payload_invalid_not_a_recursion_error() -> None:
    deep: object = 1
    for _ in range(200):
        deep = [deep]
    with pytest.raises(ScraperError) as caught:
        canonical_json(deep)
    assert caught.value.code == errors.PAYLOAD_INVALID
    row = {"symbol": "BTC", "price": 1, "x": deep}
    text = json.dumps({"code": "0", "success": True, "data": [row]})
    with pytest.raises(ScraperError) as caught:
        _gate(text, maxpain_spec(coins=("BTC",)))
    assert caught.value.code == errors.PAYLOAD_INVALID


class _TextRunner:
    def __init__(self, tick) -> None:
        self._tick = tick
        self.order: list[str] = []

    async def run_cycle(self, requests, results) -> None:
        self.order.append(requests[0].endpoint)
        for i, request in enumerate(requests):
            reply = default_helper({"endpoint": request.endpoint})
            results[i] = HelperResult(reply["text"], "1", "e", 9, self._tick())


@pytest.mark.asyncio
async def test_a_gate_exception_is_a_failed_read_and_the_pass_continues(
    monkeypatch,
) -> None:
    real = coinglass_module.gate_payload
    calls = 0

    def exploding(spec, text, **kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("year 58739 is out of range")
        return real(spec, text, **kw)

    monkeypatch.setattr(coinglass_module, "gate_payload", exploding)
    lane, repo, _ = _lane_for(coinglass_raw(), _TextRunner(_Tick()))
    await lane.run_pass("schedule")
    codes = _codes(repo)
    assert codes == {"cg.btc.heatmap": errors.PAYLOAD_INVALID, "cg.maxpain": None}
    failed = next(r for r in repo.reads if r.error_code)
    assert failed.error_detail == "ValueError"  # never the message text
    assert len(repo.payloads) == 1


# --- F9 ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_dataset_order_rotates_each_pass() -> None:
    runner = _TextRunner(_Tick())
    lane, _, _ = _lane_for(coinglass_raw(), runner)
    for _ in range(3):
        await lane.run_pass("schedule")
    assert [e.rsplit("/", 1)[-1] for e in runner.order] == [
        "liqHeatMap",
        "list",
        "liqHeatMap",
    ]


class _Ws:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def send(self, raw: str) -> None:
        call_id = json.loads(raw)["id"]
        for junk in ("[1, 2]", "null", '"text"', '{"id": [1]}', "{not json"):
            self.queue.put_nowait(junk)
        self.queue.put_nowait(json.dumps({"id": call_id, "result": {"ok": 1}}))

    async def close(self) -> None:
        self.queue.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


@pytest.mark.asyncio
async def test_the_cdp_reader_survives_messages_that_are_not_objects() -> None:
    connection = CdpConnection(_Ws(), 2.0)
    try:
        assert await connection.send("Runtime.evaluate") == {"ok": 1}
        assert await connection.send("Runtime.evaluate") == {"ok": 1}
    finally:
        await connection.close()


def test_source_length_is_kept_only_as_a_plain_integer() -> None:
    now = update_time("1429")
    for bad in ("90", 9.5, True, None, [1]):
        result = interpret_result({"text": "{}", "sourceLength": bad}, returned_at=now)
        assert result.source_length == 0
        with pytest.raises(ScraperError) as caught:
            interpret_result(
                {"error": "helper_timeout", "sourceLength": bad}, returned_at=now
            )
        assert "source_length" not in caught.value.meta
    kept = interpret_result({"text": "{}", "sourceLength": 90}, returned_at=now)
    assert kept.source_length == 90


# --- F17 -----------------------------------------------------------------------


class _Stuck:
    """A computation whose cancellation never completes (a hung cancel request)."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls = 0

    async def __call__(self) -> ReadinessReport:
        self.calls += 1
        if self.calls == 1:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.2)  # a slow cancel that swallows the first one
        return ReadinessReport("ready")


@pytest.mark.asyncio
async def test_readiness_answers_store_timeout_while_the_query_cannot_be_cancelled(
    caplog,
) -> None:
    stuck = _Stuck()
    service = ReadinessService(stuck, wait_seconds=0.1)
    loop = asyncio.get_running_loop()
    started = loop.time()
    first = await service()
    assert loop.time() - started < 1.0
    assert first.status == "not_ready" and first.not_ready_reasons == ("store_timeout",)
    assert first.http_status == 503
    for _ in range(3):
        again = await service()
        assert again.not_ready_reasons == ("store_timeout",)
    assert stuck.calls == 1 and service.computations == 1
    assert sum("exceeded" in r.getMessage() for r in caplog.records) == 1
    stuck.release.set()
    await asyncio.sleep(0.01)
    # The stuck call has ended on its own: the next probe computes normally.
    nxt = await service()
    assert nxt.status == "ready" and service.computations == 2


def test_health_ready_answers_503_over_http_while_the_store_hangs() -> None:
    stuck = _Stuck()
    service = ReadinessService(stuck, wait_seconds=0.1)
    with TestClient(create_app(readiness=service)) as client:
        started = time.monotonic()
        response = client.get("/health/ready")
        assert time.monotonic() - started < 2.0
        assert response.status_code == 503
        assert response.json()["not_ready_reasons"] == ["store_timeout"]


def test_the_api_gate_does_not_wait_for_a_query_that_cannot_be_cancelled() -> None:
    world = asyncio.run(seeded())
    deps = world.deps
    deps.settings = deps.settings.model_copy(update={"query_timeout_seconds": 0.05})
    stuck = asyncio.Event()

    async def hang(*_a, **_k):
        try:
            await stuck.wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.3)  # a slow cancel that swallows the first one
        return NOW

    world.repo.server_time = hang  # type: ignore[method-assign]
    started = time.monotonic()
    response = world.get(f"/v2/datasets/{HEATMAP}")
    assert time.monotonic() - started < 3.0
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "store_timeout"


# --- F3 ------------------------------------------------------------------------


class _HangingClose(_Conn):
    async def close(self):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_a_lock_connection_whose_close_hangs_does_not_block_recovery() -> None:
    server = _Server()
    conns: list[_Conn] = []

    async def connect():
        conn = _HangingClose(server)
        conns.append(conn)
        return conn

    async def nosleep(_):
        return None

    lock = _lock(server)
    lock._connect = connect
    assert await asyncio.wait_for(lock.try_acquire(), 1.0)
    conns[0].dead = True
    assert not await asyncio.wait_for(lock.check(), 1.0)
    assert conns[0].closed  # terminated, not gracefully closed
    assert await asyncio.wait_for(lock.try_acquire(), 1.0)
    await asyncio.wait_for(lock.release(), 1.0)


# --- F2 / F11 / F13 / F16 ----------------------------------------------------


def test_bars_report_history_from_and_truncation(monkeypatch) -> None:
    world = asyncio.run(seeded())
    default = world.get(BARS).json()
    assert default["history_from"] == iso(OLD_OPEN)
    assert default["window"]["start"] == iso(OLD_OPEN)  # clamped, not ~208 days back
    assert default["truncated"] is False
    early = world.get(BARS, start=iso(OLD_OPEN - timedelta(days=3))).json()
    assert early["truncated"] is True and early["history_from"] == iso(OLD_OPEN)
    # a page that ends exactly at the oldest retained bar has no next below it
    page = world.get(
        BARS,
        start=iso(OLD_OPEN - timedelta(hours=3)),
        end=iso(OLD_OPEN + timedelta(hours=24)),
        limit="24",
        order="desc",
    ).json()
    assert len(page["bars"]) == 24 and page["next"] is None


def test_payload_responses_carry_history_from() -> None:
    from test_scraper_v2_api import _payload_world

    w, _ = asyncio.run(_payload_world())
    expected = iso(NOW - timedelta(hours=3))
    assert w.get(f"/v2/datasets/{HEATMAP}/payload").json()["history_from"] == expected
    assert w.get(f"/v2/datasets/{HEATMAP}/payloads").json()["history_from"] == expected


def test_extreme_timestamps_are_422_not_500() -> None:
    world = World()
    for params in (
        {"start": "0001-01-01T00:00:00+05:00"},
        {"end": "0001-01-01T00:00:00Z"},
        {"end": "9999-12-31T23:59:59.999999-05:00"},
        {"mode": "as_of", "as_of": "0001-01-01T00:00:00+14:00"},
    ):
        response = world.get(BARS, **params)
        assert response.status_code in (422, 503), (params, response.status_code)
        assert response.status_code != 500
    for params in (
        {"start": "0001-01-01T00:00:00+05:00"},
        {"end": "0001-01-01T00:00:00+05:00"},
    ):
        response = world.get(f"/v2/datasets/{HEATMAP}/payloads", **params)
        assert response.status_code == 422, params
    overflow = world.get(BARS, start="0001-01-01T00:00:00+05:00")
    assert overflow.status_code == 422
    assert overflow.json()["detail"]["code"] == "invalid_request"


def test_settle_must_cover_three_command_timeouts() -> None:
    raw = yaml.safe_load((REPO_ROOT / "configs" / "scraper.yaml").read_text())[
        "scraper"
    ]
    timeout = raw["database"]["command_timeout_seconds"]
    ok = copy.deepcopy(raw)
    ok["api"]["as_of_settle_seconds"] = int(3 * timeout)
    parse_settings(ok)
    bad = copy.deepcopy(raw)
    bad["api"]["as_of_settle_seconds"] = int(3 * timeout) - 1
    with pytest.raises(ValidationError, match="as_of_settle_seconds"):
        parse_settings(bad)
    assert SETTINGS.api.as_of_settle_seconds >= 3 * timeout


def test_interactive_docs_are_off_and_the_schema_needs_the_token() -> None:
    world = World()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert world.client.get(path).status_code == 404
    assert world.client.get("/v2/openapi.json").status_code == 401
    schema = world.get("/v2/openapi.json")
    assert schema.status_code == 200
    assert "/v2/datasets" in schema.json()["paths"]
