"""The /v2 read API over the in-memory twin (TestClient) and a PostgreSQL-gated leg."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from fastapi.testclient import TestClient
from scraper_v2_coinglass_support import heatmap_spec, heatmap_text, update_time
from scraper_v2_support import (
    FakeClock,
    make_bar,
    production_settings,
    require_test_database,
)

from apps.scraper_app.domain.payloads import gate_payload
from apps.scraper_app.http_api.app import create_app
from apps.scraper_app.http_api.auth import TokenSource
from apps.scraper_app.http_api.catalog import build_catalog
from apps.scraper_app.http_api.v2 import ApiDependencies
from apps.scraper_app.runtime.status import ReadinessReport
from apps.scraper_app.storage import bootstrap
from apps.scraper_app.storage.repository import (
    InMemoryScraperRepository,
    PostgresScraperRepository,
)

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
needs_postgres = pytest.mark.skipif(
    not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI not set"
)
TOKEN = "t" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SETTINGS = production_settings()
TV = SETTINGS.dataset_specs()[0]
assert TV.interval == "1h"
TV_ID = TV.id
HEATMAP = "cg.binance.btcusdt.liq_heatmap.5m.24h"
DISABLED = "cg.binance.ethusdt.liq_heatmap.5m.24h"
MAXPAIN = "cg.maxpain.24h"
BARS = f"/v2/datasets/{TV_ID}/bars"


def iso(moment: datetime) -> str:
    return moment.isoformat()


def _accepted():
    return gate_payload(
        heatmap_spec(),
        heatmap_text("1429"),
        returned_at=update_time("1429"),
        max_payload_bytes=5_000_000,
        max_age_seconds=900,
    )


class World:
    def __init__(self, tokens: TokenSource | None = None) -> None:
        self.clock = FakeClock(NOW)
        specs = {s.id: s for s in SETTINGS.dataset_specs()}
        self.repo = InMemoryScraperRepository(specs, clock=self.clock)
        self.tokens = tokens or TokenSource(env_token=TOKEN)
        self.deps = ApiDependencies(
            repository=self.repo,
            catalog=build_catalog(SETTINGS),
            settings=SETTINGS.api,
            tokens=self.tokens,
            disabled=lambda: frozenset({DISABLED}),
        )

        async def ready() -> ReadinessReport:
            return ReadinessReport("ready")

        self.client = TestClient(create_app(readiness=ready, api=self.deps))

    def get(self, path, **params):
        return self.client.get(path, params=params, headers=AUTH)

    async def bars(self, at: datetime, bars) -> None:
        self.clock.now = at
        await self.repo.commit_ok_read(
            TV,
            trigger="schedule",
            started_at=at,
            provider_time=at,
            bars=bars,
            gap_before=False,
        )

    async def payload(self, dataset: str, at: datetime) -> int:
        self.clock.now = at
        commit = await self.repo.commit_ok_payload(
            dataset,
            trigger="schedule",
            started_at=at,
            accepted=_accepted(),
            gap_before=False,
        )
        return commit.read_id


OLD_OPEN = NOW - timedelta(days=10)
OLD = [make_bar(OLD_OPEN + timedelta(hours=i), i) for i in range(24)]


async def seeded() -> World:
    world = World()
    await world.bars(NOW - timedelta(days=5), OLD)  # final: 4 d after every close
    recent = [make_bar(NOW - timedelta(hours=3 - i), 100 + i) for i in range(3)]
    await world.bars(NOW - timedelta(hours=2), recent)
    revised = [make_bar(recent[0].bar_open, 200)]
    await world.bars(NOW - timedelta(minutes=30), revised)
    world.clock.now = NOW
    return world


@pytest.fixture
def world():
    import asyncio

    return asyncio.run(seeded())


# --- 1 auth ------------------------------------------------------------------


def test_auth_rejects_missing_wrong_scheme_and_wrong_token(world) -> None:
    for headers in (
        {},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": "Bearer " + "x" * 40},
    ):
        r = world.client.get("/v2/datasets", headers=headers)
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "unauthorized"
        assert r.headers["www-authenticate"] == "Bearer"
    assert world.client.get("/v2/datasets", headers=AUTH).status_code == 200
    assert world.client.get("/health/live").status_code == 200  # health stays open


def test_unset_or_short_token_gives_503_while_health_answers(caplog) -> None:
    short = "s" * 10
    for tokens in (TokenSource(), TokenSource(env_token=short)):
        w = World(tokens)
        with caplog.at_level(logging.ERROR):
            r = w.client.get(
                "/v2/datasets", headers={"Authorization": f"Bearer {short}"}
            )
            w.client.get("/v2/datasets", headers={"Authorization": f"Bearer {short}"})
        assert r.status_code == 503
        assert r.json()["detail"]["code"] == "auth_not_configured"
        assert w.client.get("/health/ready").status_code == 200
    assert short not in caplog.text
    assert caplog.text.count("shorter than") == 1  # one ERROR, not one per request


def test_token_file_is_reloaded_on_mtime_change_and_never_logged(
    tmp_path, caplog
) -> None:
    path = tmp_path / "token"
    path.write_text("a" * 40 + "\n")
    w = World(TokenSource(file_path=str(path)))
    with caplog.at_level(logging.DEBUG):
        assert (
            w.client.get(
                "/v2/datasets", headers={"Authorization": "Bearer " + "a" * 40}
            ).status_code
            == 200
        )
        path.write_text("b" * 40)
        stat = path.stat()
        os.utime(path, (stat.st_atime, stat.st_mtime + 5))
        assert (
            w.client.get(
                "/v2/datasets", headers={"Authorization": "Bearer " + "a" * 40}
            ).status_code
            == 401
        )
        assert (
            w.client.get(
                "/v2/datasets", headers={"Authorization": "Bearer " + "b" * 40}
            ).status_code
            == 200
        )
    assert "a" * 40 not in caplog.text and "b" * 40 not in caplog.text
    assert TokenSource(file_path=str(tmp_path / "missing")).current() is None


# --- 2 bars ------------------------------------------------------------------


def test_final_bars_default_order_limit_and_decimal_strings(world) -> None:
    body = world.get(BARS).json()
    assert body["mode"] == "final" and body["as_of"] is None and body["order"] == "desc"
    opens = [b["bar_open"] for b in body["bars"]]
    assert len(opens) == 24 and opens == sorted(opens, reverse=True)
    assert all(b["finality"] == "final" for b in body["bars"])
    assert body["stale"] is False and body["age_seconds"] == 1800
    first = world.get(BARS, limit=1).json()["bars"]
    assert [b["bar_open"] for b in first] == [iso(OLD_OPEN + timedelta(hours=23))]
    bar = OLD[23]
    assert first[0]["open"] == format(bar.open, "f") and isinstance(
        first[0]["close"], str
    )
    asc = world.get(BARS, order="asc").json()["bars"]
    assert asc[0]["bar_open"] == iso(OLD_OPEN)


def test_as_of_shows_provisional_bars_and_current_replays_exactly(world) -> None:
    at = NOW - timedelta(minutes=40)
    body = world.get(BARS, mode="as_of", as_of=iso(at)).json()
    kinds = {b["bar_open"]: b["finality"] for b in body["bars"]}
    assert kinds[iso(NOW - timedelta(hours=3))] == "provisional"
    assert kinds[iso(OLD_OPEN)] == "final"
    current = world.get(BARS, mode="current").json()
    assert current["as_of"] == iso(NOW - timedelta(seconds=60))
    replay = world.get(BARS, mode="as_of", as_of=current["as_of"]).json()
    assert (
        replay["bars"] == current["bars"]
        and replay["last_ok_read"] == current["last_ok_read"]
    )
    revised = [b for b in current["bars"] if b["revision_count"] == 1]
    assert len(revised) == 1 and revised[0]["bar_open"] == iso(NOW - timedelta(hours=3))
    before = [b for b in body["bars"] if b["bar_open"] == iso(NOW - timedelta(hours=3))]
    assert before[0]["revision_count"] == 0  # not yet revised at that instant


def test_settle_vintage_naive_wrong_kind_and_unknown(world) -> None:
    too_recent = world.get(BARS, mode="as_of", as_of=iso(NOW - timedelta(seconds=30)))
    assert too_recent.status_code == 422
    assert too_recent.json()["detail"]["code"] == "as_of_too_recent"
    early = world.get(BARS, mode="as_of", as_of=iso(NOW - timedelta(days=6)))
    assert early.json()["detail"]["code"] == "as_of_before_vintage"
    assert early.json()["detail"]["vintage_available_from"] == iso(
        NOW - timedelta(days=5)
    )
    for params in (
        {"mode": "as_of"},
        {"as_of": iso(NOW)},
        {"start": "2026-10-01T00:00:00"},
        {"limit": "0"},
        {"limit": "5001"},
        {"order": "up"},
        {"mode": "x"},
    ):
        r = world.get(BARS, **params)
        assert r.status_code == 422, params
    wrong = world.get(f"/v2/datasets/{HEATMAP}/bars")
    assert (wrong.status_code, wrong.json()["detail"]["code"]) == (422, "wrong_kind")
    wrong = world.get(f"/v2/datasets/{TV_ID}/payload")
    assert wrong.json()["detail"]["code"] == "wrong_kind"
    assert world.get("/v2/datasets/nope/bars").status_code == 404
    assert world.get("/v2/datasets/nope").json()["detail"]["code"] == "unknown_dataset"


def test_windows_and_span_limit(world) -> None:
    explicit = world.get(
        BARS, start=iso(OLD_OPEN), end=iso(OLD_OPEN + timedelta(hours=3))
    )
    assert [b["bar_open"] for b in explicit.json()["bars"]] == [
        iso(OLD_OPEN + timedelta(hours=h)) for h in (2, 1, 0)
    ]
    wide = world.get(BARS, start=iso(NOW - timedelta(days=400)), end=iso(NOW))
    assert (wide.status_code, wide.json()["detail"]["code"]) == (422, "invalid_request")
    reversed_ = world.get(BARS, start=iso(NOW), end=iso(NOW - timedelta(hours=1)))
    assert reversed_.status_code == 422


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_next_walks_the_window_without_gaps_or_repeats(world, order) -> None:
    seen: list[str] = []
    params = {"limit": "5", "order": order}
    for _ in range(10):
        body = world.get(BARS, **params).json()
        seen += [b["bar_open"] for b in body["bars"]]
        if body["next"] is None:
            break
        params = {k: v for k, v in body["next"].items() if v is not None}
    expected = [iso(OLD_OPEN + timedelta(hours=h)) for h in range(24)]
    assert seen == (expected if order == "asc" else expected[::-1])


# --- 4 stale -----------------------------------------------------------------


def test_stale_is_503_unless_allowed(world) -> None:
    world.clock.now = NOW + timedelta(days=1)
    r = world.get(BARS)
    detail = r.json()["detail"]
    assert r.status_code == 503 and detail["code"] == "stale"
    assert detail["max_age_seconds"] == 7800 and detail["age_seconds"] > 7800
    ok = world.get(BARS, allow_stale="true")
    assert ok.status_code == 200 and ok.json()["stale"] is True


# --- 3 payloads --------------------------------------------------------------


async def _payload_world() -> tuple[World, list[int]]:
    w = World()
    ids = [
        await w.payload(HEATMAP, NOW - timedelta(hours=3)),
        await w.payload(HEATMAP, NOW - timedelta(hours=2)),
        await w.payload(HEATMAP, NOW - timedelta(minutes=10)),
    ]
    await w.payload(DISABLED, NOW - timedelta(minutes=10))
    w.clock.now = NOW
    return w, ids


def _data_text(raw: str) -> str:
    marker = ',"data":'
    return raw[raw.index(marker) + len(marker) : -1]


def test_payload_latest_by_reference_list_by_id_and_verbatim_data() -> None:
    import asyncio

    w, ids = asyncio.run(_payload_world())
    latest = w.get(f"/v2/datasets/{HEATMAP}/payload")
    assert latest.status_code == 200
    meta = latest.json()
    assert meta["observation_id"] == ids[2] and meta["stale"] is False
    assert (
        hashlib.sha256(_data_text(latest.text).encode()).hexdigest()
        == meta["content_hash"]
    )
    assert meta["data"] == __import__("json").loads(_data_text(latest.text))
    earlier = w.get(
        f"/v2/datasets/{HEATMAP}/payload", as_of=iso(NOW - timedelta(minutes=90))
    )
    assert earlier.json()["observation_id"] == ids[1]

    page = w.get(f"/v2/datasets/{HEATMAP}/payloads", limit=2).json()
    assert [p["observation_id"] for p in page["payloads"]] == [ids[2], ids[1]]
    assert set(page["payloads"][0]) == {
        "observation_id",
        "observed_at",
        "provider_time",
        "content_hash",
        "raw_bytes",
    }
    rest = w.get(
        f"/v2/datasets/{HEATMAP}/payloads",
        **{k: v for k, v in page["next"].items() if v is not None},
    ).json()
    assert [p["observation_id"] for p in rest["payloads"]] == [ids[0]] and rest[
        "next"
    ] is None
    too_new = w.get(f"/v2/datasets/{HEATMAP}/payloads", end=iso(NOW))
    assert too_new.json()["detail"]["code"] == "as_of_too_recent"

    one = w.get(f"/v2/datasets/{HEATMAP}/payloads/{ids[0]}")
    assert one.status_code == 200 and one.json()["observation_id"] == ids[0]
    assert (
        hashlib.sha256(_data_text(one.text).encode()).hexdigest()
        == one.json()["content_hash"]
    )
    assert w.get(f"/v2/datasets/{HEATMAP}/payloads/999").status_code == 404
    assert (
        w.get(
            f"/v2/datasets/{HEATMAP}/payload", as_of=iso(NOW - timedelta(hours=5))
        ).json()["detail"]["code"]
        == "as_of_before_vintage"
    )

    blocked = w.get(f"/v2/datasets/{DISABLED}/payload")
    assert (blocked.status_code, blocked.json()["detail"]["code"]) == (
        503,
        "dataset_disabled",
    )
    maxpain = w.get(f"/v2/datasets/{MAXPAIN}/payload")
    assert maxpain.status_code == 503 and maxpain.json()["detail"]["code"] == "stale"
    allowed = w.get(f"/v2/datasets/{MAXPAIN}/payload", allow_stale="true")
    assert allowed.status_code == 404 and allowed.json()["detail"]["code"] == "no_data"


def test_payload_vintage_moves_after_a_purge() -> None:
    import asyncio

    async def build():
        w = World()
        await w.payload(HEATMAP, NOW - timedelta(days=30))
        await w.payload(HEATMAP, NOW - timedelta(days=20))
        await w.payload(HEATMAP, NOW - timedelta(minutes=10))
        w.clock.now = NOW
        return w

    w = asyncio.run(build())
    path = f"/v2/datasets/{HEATMAP}"
    assert w.get(path).json()["vintage_available_from"] == iso(NOW - timedelta(days=30))
    result = asyncio.run(
        w.repo.purge_dataset(HEATMAP, kind="coinglass", days=14, batch_rows=10)
    )
    assert result.deleted["payload_observations"] == 2
    w.deps.facts = None  # the catalog reuses store facts for catalog_cache_seconds
    assert w.get(path).json()["vintage_available_from"] == iso(
        NOW - timedelta(minutes=10)
    )
    gone = w.get(f"{path}/payload", as_of=iso(NOW - timedelta(days=25)))
    assert gone.json()["detail"]["code"] == "as_of_before_vintage"


# --- 5 catalog ---------------------------------------------------------------


def test_catalog_lists_every_dataset_with_provider_fields(world) -> None:
    body = world.get("/v2/datasets").json()
    entries = {d["id"]: d for d in body["datasets"]}
    assert len(entries) == 29 and body["limits"]["max_limit"] == 5000
    bars = entries[TV_ID]
    assert (bars["provider"], bars["kind"], bars["interval"]) == (
        "tradingview",
        "bars",
        "1h",
    )
    assert bars["canonical_symbol"] and bars["revision_watch_seconds"] == 1036800
    assert bars["finality_horizon_seconds"] == 345600 and bars["retention_days"] == 14
    assert bars["max_age_seconds"] == 7800 and bars["disabled"] is False
    assert bars["revisions_after_horizon"] == 0
    assert bars["first"] == iso(OLD_OPEN) and bars["vintage_available_from"] == iso(
        NOW - timedelta(days=5)
    )
    heat = entries[HEATMAP]
    assert (heat["provider"], heat["kind"], heat["exchange"]) == (
        "coinglass",
        "liq_heatmap",
        "Binance",
    )
    assert heat["requires_login"] is False and heat["max_age_seconds"] == 2100
    assert (
        entries[DISABLED]["disabled"] is True
        and entries[DISABLED]["requires_login"] is True
    )
    assert entries[MAXPAIN]["coins"] == ["BTC", "ETH", "SOL", "BNB"]
    single = world.get(f"/v2/datasets/{TV_ID}").json()
    assert single["id"] == TV_ID and "limits" in single


def test_api_block_is_optional_and_store_errors_map_to_503(world, monkeypatch) -> None:
    assert create_app().routes is not None
    plain = TestClient(create_app())
    assert plain.get("/v2/datasets", headers=AUTH).status_code == 404

    async def timeout():
        raise TimeoutError

    async def down():
        raise asyncpg.PostgresConnectionError("down")

    monkeypatch.setattr(world.repo, "server_time", timeout)
    assert world.get(BARS).json()["detail"]["code"] == "store_timeout"
    monkeypatch.setattr(world.repo, "server_time", down)
    assert world.get(BARS).json()["detail"]["code"] == "store_unavailable"


# --- 6 database-gated --------------------------------------------------------


@needs_postgres
@pytest.mark.asyncio
async def test_api_pool_cannot_write_and_a_held_connection_does_not_delay_commits() -> (
    None
):
    admin = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)
    api = None
    try:
        async with admin.acquire() as c:
            await require_test_database(c)
            await bootstrap.apply_scraper_schema(c, "scraper-test-password", "purge-pw")
            await c.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, "
                "scraper.reads RESTART IDENTITY"
            )
        api = await asyncpg.create_pool(
            POSTGRES_URI,
            min_size=0,
            max_size=2,
            server_settings={
                "application_name": "scraper_api",
                "default_transaction_read_only": "on",
                "statement_timeout": "5000",
            },
        )
        insert = (
            "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
            "error_code) VALUES ('t', 'schedule', 'failed', now(), 'x')"
        )
        async with api.acquire() as c:
            with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
                await c.execute(insert)
        collector = PostgresScraperRepository(admin, {})
        async with api.acquire() as held:
            tx = held.transaction()
            await tx.start()
            await held.fetchval("SELECT count(*) FROM scraper.reads")
            started = time.monotonic()
            await collector.record_failed_read(
                "t",
                trigger="schedule",
                started_at=datetime.now(UTC),
                error_code="x",
                error_detail="y",
            )
            assert time.monotonic() - started < 1.0
            await tx.rollback()
        # The API repository reads what the collector committed.
        reader = PostgresScraperRepository(api, {})
        assert (await reader.latest_read("t")).error_code == "x"
    finally:
        if api is not None:
            await api.close()
        await admin.close()


def test_a_saturated_gate_answers_503_busy(world, monkeypatch) -> None:
    import asyncio

    from apps.scraper_app.http_api import v2

    monkeypatch.setattr(v2, "BUSY_WAIT_SECONDS", 0.05)
    world.deps.gate = asyncio.Semaphore(0)  # every permit is taken
    r = world.get("/v2/datasets")
    assert (r.status_code, r.json()["detail"]["code"]) == (503, "busy")
    assert world.client.get("/health/live").status_code == 200
