"""Payload store: both backends (PostgreSQL when SCRAPER_TEST_POSTGRES_URI is set)."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
import pytest_asyncio
from scraper_v2_coinglass_support import (
    heatmap_spec,
    heatmap_text,
    maxpain_spec,
    maxpain_text,
    update_time,
)
from scraper_v2_support import require_test_database, utc

from apps.scraper_app.domain import errors
from apps.scraper_app.domain.payloads import canonical_hash, gate_payload
from apps.scraper_app.storage import bootstrap
from apps.scraper_app.storage.repository import (
    InMemoryScraperRepository,
    PostgresScraperRepository,
)

POSTGRES_URI = os.environ.get("SCRAPER_TEST_POSTGRES_URI")
needs_postgres = pytest.mark.skipif(
    not POSTGRES_URI, reason="SCRAPER_TEST_POSTGRES_URI not set"
)
STARTED = utc(2026, 10, 9, 14, 29)
pytestmark = pytest.mark.asyncio


class _TickingClock:
    """Every call is one second later, like successive reads."""

    def __init__(self) -> None:
        self.now = utc(2026, 10, 9, 14, 30)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


@pytest_asyncio.fixture(
    params=["memory", pytest.param("postgres", marks=needs_postgres)]
)
async def repo(request):
    if request.param == "memory":
        yield InMemoryScraperRepository({}, clock=_TickingClock()), None
        return
    import asyncpg

    pool = await asyncpg.create_pool(POSTGRES_URI, min_size=1, max_size=2)
    try:
        async with pool.acquire() as connection:
            await require_test_database(connection)
            await bootstrap.apply_scraper_schema(connection, "scraper-test-password")
            await connection.execute(
                "TRUNCATE scraper.payload_observations, scraper.bar_observations, "
                "scraper.reads RESTART IDENTITY"
            )
        yield PostgresScraperRepository(pool, {}), pool
    finally:
        await pool.close()


def _accepted(name: str):
    return gate_payload(
        heatmap_spec(),
        heatmap_text(name),
        returned_at=update_time(name),
        max_payload_bytes=5_000_000,
        max_age_seconds=900,
    )


async def test_latest_payload_at_finished_at_returns_that_reads_payload(repo) -> None:
    repository, _ = repo
    reads = []
    for name in ("1429", "1432", "1436"):
        accepted = _accepted(name)
        commit = await repository.commit_ok_payload(
            "cg.btc.heatmap",
            trigger="schedule",
            started_at=STARTED,
            accepted=accepted,
            gap_before=False,
            meta={"module": "89390"},
        )
        reads.append((commit, accepted))
    assert len({a.content_hash for _, a in reads}) == 3
    for commit, accepted in reads:
        row = await repository.latest_payload("cg.btc.heatmap", at=commit.observed_at)
        assert row.read_id == commit.read_id
        assert row.text() == accepted.text
        assert canonical_hash(row.text()) == row.content_hash == accepted.content_hash
        assert row.raw_bytes == accepted.raw_bytes
    newest = await repository.latest_payload("cg.btc.heatmap")
    assert newest.read_id == reads[-1][0].read_id
    before_all = reads[0][0].observed_at - timedelta(days=1)
    assert await repository.latest_payload("cg.btc.heatmap", at=before_all) is None
    assert await repository.latest_payload("other") is None


async def test_ok_read_has_one_payload_row_and_failed_read_none(repo) -> None:
    repository, pool = repo
    accepted = _accepted("1429")
    commit = await repository.commit_ok_payload(
        "cg.btc.heatmap",
        trigger="schedule",
        started_at=STARTED,
        accepted=accepted,
        gap_before=False,
        meta={"module": "89390", "payload_bytes": 5},
    )
    await repository.record_failed_read(
        "cg.btc.heatmap",
        trigger="schedule",
        started_at=STARTED,
        error_code=errors.PAYLOAD_INVALID,
        error_detail="x",
        meta={"module": "89390"},
    )
    ok = await repository.latest_ok_read("cg.btc.heatmap")
    assert ok.read_id == commit.read_id
    assert (ok.covered_from, ok.covered_to) == (
        accepted.covered_from,
        accepted.covered_to,
    )
    assert ok.provider_time == accepted.provider_time
    assert (ok.bars_seen, ok.holes, ok.gap_before) == (12, 0, False)
    assert ok.meta == {"module": "89390", "payload_bytes": 5}
    failed = await repository.latest_read("cg.btc.heatmap")
    assert failed.status == "failed" and failed.meta == {"module": "89390"}
    if pool is None:
        assert len(repository.payloads) == 1
    else:
        async with pool.acquire() as connection:
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM scraper.payload_observations"
                )
                == 1
            )
            row = await connection.fetchrow(
                "SELECT observed_at, read_id FROM scraper.payload_observations"
            )
            finished = await connection.fetchval(
                "SELECT finished_at FROM scraper.reads WHERE read_id = $1",
                row["read_id"],
            )
            assert row["observed_at"] == finished


async def test_two_max_pain_fetches_in_one_window_give_two_rows(repo) -> None:
    repository, _ = repo
    spec = maxpain_spec()
    commits = []
    for offset in (0, 30):
        returned = utc(2026, 10, 9, 14, 30) + timedelta(seconds=offset)
        accepted = gate_payload(
            spec,
            maxpain_text(),
            returned_at=returned,
            max_payload_bytes=1_000_000,
            max_age_seconds=900,
        )
        commits.append(
            await repository.commit_ok_payload(
                spec.id,
                trigger="schedule",
                started_at=returned,
                accepted=accepted,
                gap_before=False,
            )
        )
    assert commits[0].read_id != commits[1].read_id
    for commit in commits:
        row = await repository.latest_payload(spec.id, at=commit.observed_at)
        assert row.read_id == commit.read_id


@needs_postgres
async def test_bootstrap_keeps_data_adds_meta_and_grants_select_insert_only() -> None:
    import asyncpg

    admin = await asyncpg.connect(POSTGRES_URI)
    try:
        await require_test_database(admin)
        await bootstrap.apply_scraper_schema(admin, "scraper-test-password")
        await admin.execute(
            "TRUNCATE scraper.payload_observations, scraper.bar_observations, scraper.reads"
        )
        # An older database: no payload table, no meta column, existing data.
        await admin.execute("DROP TABLE scraper.payload_observations")
        await admin.execute("ALTER TABLE scraper.reads DROP COLUMN meta")
        await admin.execute(
            "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, error_code) "
            "VALUES ('keep', 'schedule', 'failed', now(), 'timeout')"
        )
        from apps.scraper_app.main import schema_is_applied

        class _Pool:
            def acquire(self_inner):
                class _C:
                    async def __aenter__(_s):
                        return admin

                    async def __aexit__(_s, *a):
                        return None

                return _C()

        assert await schema_is_applied(_Pool()) is True
        assert await schema_is_applied(_Pool(), coinglass=True) is False
        await bootstrap.apply_scraper_schema(admin, "scraper-test-password")
        assert await schema_is_applied(_Pool(), coinglass=True) is True
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM scraper.reads WHERE dataset_id = 'keep'"
            )
            == 1
        )
        assert (
            await admin.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'scraper' AND table_name = 'reads' AND column_name = 'meta'"
            )
            == 1
        )
        privileges = {
            p: await admin.fetchval(
                "SELECT has_table_privilege('scraper_app', 'scraper.payload_observations', $1)",
                p,
            )
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }
        assert privileges == {
            "SELECT": True,
            "INSERT": True,
            "UPDATE": False,
            "DELETE": False,
            "TRUNCATE": False,
        }
    finally:
        await admin.execute("DELETE FROM scraper.reads WHERE dataset_id = 'keep'")
        await admin.close()
