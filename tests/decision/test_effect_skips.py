from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.storage.effect_skips import (
    InMemoryLaneEffectSkipsRepository,
    LaneEffectSkip,
    LaneEffectSkipConflictError,
    LaneEffectSkipsRepository,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 1, 5, tzinfo=UTC)
IDENTITY = LaneExecutionIdentity(
    lane_id="BTCUSDT:momentum_1h",
    effective_lane_revision="lane-r1",
    feature_plan_fingerprint="features-f1",
)


def _skip(through_index: int, *, reason: str = "restart") -> LaneEffectSkip:
    return LaneEffectSkip(
        identity=IDENTITY,
        skipped_from=BASE + timedelta(hours=1),
        skipped_through=BASE + timedelta(hours=through_index),
        cutoff_count=through_index,
        reason=reason,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_in_memory_skip_upsert_is_idempotent_and_extends_one_range() -> None:
    repository = InMemoryLaneEffectSkipsRepository()

    first = await repository.upsert(_skip(3))
    identical = await repository.upsert(_skip(3))
    extended = await repository.upsert(_skip(5))
    stale_retry = await repository.upsert(_skip(4))

    assert first == identical
    assert extended.skipped_through == BASE + timedelta(hours=5)
    assert extended.cutoff_count == 5
    assert stale_retry == extended
    assert repository.records == (extended,)


@pytest.mark.asyncio
async def test_skip_start_cannot_be_reused_for_a_different_reason() -> None:
    repository = InMemoryLaneEffectSkipsRepository()
    await repository.upsert(_skip(3))

    with pytest.raises(LaneEffectSkipConflictError, match="different reason"):
        await repository.upsert(_skip(4, reason="stale"))


class _Connection:
    def __init__(self) -> None:
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object, **_kwargs: object):
        self.query = query
        self.args = args
        return {
            "skipped_from": args[3],
            "skipped_through": args[4],
            "cutoff_count": args[5],
            "reason": args[6],
            "recorded_at": BASE,
        }


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_durable_skip_upsert_merges_range_idempotently() -> None:
    connection = _Connection()
    repository = LaneEffectSkipsRepository(_Pool(connection))
    result = await repository.upsert(_skip(5))

    assert result.skipped_through == BASE + timedelta(hours=5)
    assert result.cutoff_count == 5
    assert "ON CONFLICT" in connection.query
    assert "GREATEST(" in connection.query
    assert "EXCLUDED.cutoff_count" in connection.query
    assert connection.args[:3] == (
        IDENTITY.lane_id,
        IDENTITY.effective_lane_revision,
        IDENTITY.feature_plan_fingerprint,
    )


@pytest.mark.asyncio
async def test_equal_through_with_different_count_keeps_stored_row_in_both_paths() -> (
    None
):
    first = _skip(5)
    retry = LaneEffectSkip(
        identity=IDENTITY,
        skipped_from=first.skipped_from,
        skipped_through=first.skipped_through,
        cutoff_count=first.cutoff_count + 1,
        reason=first.reason,
    )
    memory = InMemoryLaneEffectSkipsRepository()
    await memory.upsert(first)
    assert await memory.upsert(retry) == first

    # The durable upsert keeps the stored count unless the range grows; the
    # fake connection returns the row that SQL would hand back.
    connection = _Connection()
    repository = LaneEffectSkipsRepository(_Pool(connection))
    stored = {
        "skipped_from": first.skipped_from,
        "skipped_through": first.skipped_through,
        "cutoff_count": first.cutoff_count,
        "reason": first.reason,
        "recorded_at": BASE,
    }

    async def _stored_row(query: str, *args: object, **_kwargs: object):
        connection.query = query
        return stored

    connection.fetchrow = _stored_row  # type: ignore[method-assign]
    durable = await repository.upsert(retry)
    assert durable.cutoff_count == first.cutoff_count
    assert durable.skipped_through == first.skipped_through
    assert "ELSE decision.lane_effect_skips.cutoff_count" in connection.query


def test_skip_table_creation_is_idempotent_and_keeps_the_declared_identity() -> None:
    schema = (ROOT / "src/apps/decision_app/storage/schema.sql").read_text()
    declaration = schema.split(
        "CREATE TABLE IF NOT EXISTS decision.lane_effect_skips", maxsplit=1
    )[1]
    assert "PRIMARY KEY (" in declaration
    assert "lane_id," in declaration
    assert "effective_lane_revision," in declaration
    assert "feature_plan_fingerprint," in declaration
    assert "skipped_from" in declaration
    assert (
        "reason IN ('restart', 'restart_rewarm', 'stale', 'foreign_entry')"
        in declaration
    )


@pytest.mark.asyncio
async def test_in_memory_skip_load_returns_stored_row_or_none() -> None:
    repository = InMemoryLaneEffectSkipsRepository()
    stored = await repository.upsert(_skip(3, reason="stale"))

    assert await repository.load(IDENTITY, stored.skipped_from) == stored
    assert (
        await repository.load(IDENTITY, stored.skipped_from + timedelta(hours=1))
        is None
    )
    other = LaneExecutionIdentity(
        lane_id=IDENTITY.lane_id,
        effective_lane_revision="lane-r2",
        feature_plan_fingerprint=IDENTITY.feature_plan_fingerprint,
    )
    assert await repository.load(other, stored.skipped_from) is None


class _LoadConnection:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.query = ""
        self.args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object, **_kwargs: object):
        self.query = query
        self.args = args
        return self.row


@pytest.mark.asyncio
async def test_durable_skip_load_selects_by_primary_key() -> None:
    row = {
        "skipped_from": BASE + timedelta(hours=1),
        "skipped_through": BASE + timedelta(hours=1),
        "cutoff_count": 1,
        "reason": "stale",
        "recorded_at": BASE,
    }
    connection = _LoadConnection(row)
    repository = LaneEffectSkipsRepository(_Pool(connection))  # type: ignore[arg-type]

    loaded = await repository.load(IDENTITY, BASE + timedelta(hours=1))

    assert loaded == LaneEffectSkip(
        identity=IDENTITY,
        skipped_from=BASE + timedelta(hours=1),
        skipped_through=BASE + timedelta(hours=1),
        cutoff_count=1,
        reason="stale",
        recorded_at=BASE,
    )
    assert connection.query.lstrip().startswith("SELECT")
    assert "FROM decision.lane_effect_skips" in connection.query
    for column in (
        "lane_id = $1",
        "effective_lane_revision = $2",
        "feature_plan_fingerprint = $3",
        "skipped_from = $4",
    ):
        assert column in connection.query
    assert "INSERT" not in connection.query
    assert connection.args == (
        IDENTITY.lane_id,
        IDENTITY.effective_lane_revision,
        IDENTITY.feature_plan_fingerprint,
        BASE + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_durable_skip_load_returns_none_for_missing_key() -> None:
    connection = _LoadConnection(None)
    repository = LaneEffectSkipsRepository(_Pool(connection))  # type: ignore[arg-type]

    assert await repository.load(IDENTITY, BASE + timedelta(hours=9)) is None
