from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.runtime import deadlines as deadlines_module
from apps.decision_app.runtime.deadlines import (
    CleanupBudget,
    CleanupTimeout,
    Deadline,
    OperationTimeout,
    acquire_db_connection,
    cleanup_with_timeout,
)
from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.storage.checkpoints import (
    CheckpointRepository,
    LaneStateCheckpoint,
)
from apps.decision_app.storage.market_history import CanonicalMarketHistoryRepository
from apps.decision_app.storage.shadow_progress import (
    LaneEffectProgress,
    LaneEffectProgressRepository,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
KEY = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)
IDENTITY = LaneExecutionIdentity(
    lane_id="BTCUSDT:1h",
    effective_lane_revision="lane-rev",
    feature_plan_fingerprint="feature-rev",
    data_plan_fingerprint="data-rev",
)


class _AcquireContext:
    def __init__(self, pool: _Pool, delay: float = 0.0) -> None:
        self._pool = pool
        self._delay = delay

    async def __aenter__(self) -> _Connection:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._pool.connection

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Transaction:
    def __init__(self, connection: _Connection, *, start_delay: float = 0.0) -> None:
        self._connection = connection
        self._start_delay = start_delay

    async def start(self) -> None:
        self._connection.transaction_events.append("start")
        if self._start_delay:
            await asyncio.sleep(self._start_delay)

    async def commit(self) -> None:
        self._connection.transaction_events.append("commit")

    async def rollback(self) -> None:
        self._connection.transaction_events.append("rollback")


class _Connection:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        start_delay: float = 0.0,
        fetchrow_delay: float = 0.0,
    ) -> None:
        self.row = row
        self.start_delay = start_delay
        self.fetchrow_delay = fetchrow_delay
        self.fetchrow_calls: list[tuple[str, float | None]] = []
        self.execute_calls: list[tuple[str, float | None]] = []
        self.transaction_events: list[str] = []
        self.terminate_calls = 0

    async def fetchrow(
        self,
        query: str,
        *_args: object,
        timeout: float | None = None,
    ) -> dict[str, object] | None:
        self.fetchrow_calls.append((query, timeout))
        if self.fetchrow_delay:
            await asyncio.sleep(self.fetchrow_delay)
        return self.row

    async def execute(
        self,
        query: str,
        *_args: object,
        timeout: float | None = None,
    ) -> str:
        self.execute_calls.append((query, timeout))
        return "INSERT 0 1"

    def transaction(self) -> _Transaction:
        return _Transaction(self, start_delay=self.start_delay)

    def terminate(self) -> None:
        self.terminate_calls += 1


class _Pool:
    def __init__(
        self,
        connection: _Connection,
        *,
        acquire_delay: float = 0.0,
        release_gate: asyncio.Event | None = None,
        release_error: BaseException | None = None,
        cancel_owner_during_release: bool = False,
    ) -> None:
        self.connection = connection
        self.acquire_delay = acquire_delay
        self.release_gate = release_gate
        self.release_error = release_error
        self.cancel_owner_during_release = cancel_owner_during_release
        self.owner_task: asyncio.Task[object] | None = None
        self.acquire_timeouts: list[float | None] = []
        self.release_timeouts: list[float | None] = []
        self.release_started = asyncio.Event()
        self.release_done = asyncio.Event()

    def acquire(self, *, timeout: float | None = None) -> _AcquireContext:
        self.acquire_timeouts.append(timeout)
        return _AcquireContext(self, self.acquire_delay)

    async def release(
        self, _connection: _Connection, *, timeout: float | None = None
    ) -> None:
        self.release_timeouts.append(timeout)
        self.release_started.set()
        if self.cancel_owner_during_release and self.owner_task is not None:
            self.owner_task.cancel()
        if self.release_gate is not None:
            try:
                await self.release_gate.wait()
            except asyncio.CancelledError:
                await self.release_gate.wait()
        if self.release_error is not None:
            raise self.release_error
        self.release_done.set()


def _cutoff_row() -> dict[str, object]:
    return {
        "close_time": BASE + timedelta(hours=1),
        "source_type": "provider",
        "source_provider": "test",
        "source_timeframe": None,
    }


def _checkpoint() -> LaneStateCheckpoint:
    return LaneStateCheckpoint.create(
        identity=IDENTITY,
        market_as_of=BASE + timedelta(hours=1),
        state_inception_at=BASE,
        state_by_binding={"binding-a": {"count": 1}},
    )


def _progress() -> LaneEffectProgress:
    return LaneEffectProgress.create(
        identity=IDENTITY,
        market_as_of=BASE + timedelta(hours=1),
        last_disposition="published",
    )


@pytest.mark.asyncio
async def test_history_uses_native_command_timeout_and_bounded_acquire() -> None:
    connection = _Connection(row=_cutoff_row())
    pool = _Pool(connection)
    repository = CanonicalMarketHistoryRepository(
        pool,
        io_timeout_seconds=0.01,
        operation_timeout_seconds=0.2,
        cleanup_timeout_seconds=0.05,
    )

    assert await repository.fetch_latest_cutoff(KEY) == BASE + timedelta(hours=1)
    assert 0 < pool.acquire_timeouts[0] <= 0.01
    assert 0.01 < connection.fetchrow_calls[0][1] <= 0.2
    assert pool.release_timeouts[0] is not None


@pytest.mark.asyncio
async def test_acquisition_ignoring_native_timeout_is_still_outer_bounded() -> None:
    connection = _Connection(row=_cutoff_row())
    pool = _Pool(connection, acquire_delay=0.05)
    repository = CanonicalMarketHistoryRepository(
        pool,
        io_timeout_seconds=0.01,
        operation_timeout_seconds=0.2,
        cleanup_timeout_seconds=0.05,
    )

    with pytest.raises(OperationTimeout, match="acquisition"):
        await repository.fetch_latest_cutoff(KEY)
    assert 0 < pool.acquire_timeouts[0] <= 0.01
    assert connection.fetchrow_calls == []


@pytest.mark.asyncio
async def test_outer_cancellation_uses_cleanup_budget_for_lease_release() -> None:
    connection = _Connection(row=_cutoff_row())
    pool = _Pool(connection)
    retained: set[asyncio.Task[object]] = set()
    deadline = Deadline.after(1.0)

    async def hold_lease() -> None:
        async with acquire_db_connection(
            pool,
            deadline=deadline,
            io_timeout_seconds=0.01,
            cleanup_timeout_seconds=0.01,
            retained_tasks=retained,
            operation="outer generation",
        ):
            await asyncio.Event().wait()

    task = asyncio.create_task(hold_lease())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(pool.release_timeouts) == 1
    assert 0 < pool.release_timeouts[0] <= 0.01
    assert not retained


@pytest.mark.asyncio
async def test_operation_timeout_body_uses_cleanup_budget_before_operation_deadline() -> (
    None
):
    connection = _Connection(row=_cutoff_row())
    pool = _Pool(connection)
    retained: set[asyncio.Task[object]] = set()
    deadline = Deadline.after(1.0)
    cleanup_budget = CleanupBudget(0.01)

    with pytest.raises(OperationTimeout, match="driver"):
        async with acquire_db_connection(
            pool,
            deadline=deadline,
            io_timeout_seconds=0.01,
            cleanup_timeout_seconds=0.1,
            retained_tasks=retained,
            cleanup_budget=cleanup_budget,
            operation="operation-timeout body",
        ):
            raise OperationTimeout("query", 0.01, source="driver")

    assert 0 < pool.release_timeouts[0] <= 0.01
    assert not retained


@pytest.mark.asyncio
async def test_new_cleanup_cancellation_wins_over_earlier_body_failure() -> None:
    connection = _Connection(row=_cutoff_row())
    pool = _Pool(connection, cancel_owner_during_release=True)
    retained: set[asyncio.Task[object]] = set()
    deadline = Deadline.after(1.0)

    async def body() -> None:
        pool.owner_task = asyncio.current_task()
        async with acquire_db_connection(
            pool,
            deadline=deadline,
            io_timeout_seconds=0.01,
            cleanup_timeout_seconds=0.1,
            retained_tasks=retained,
            operation="cleanup cancellation race",
        ):
            raise ValueError("body failed")

    with pytest.raises(asyncio.CancelledError):
        await body()
    await asyncio.sleep(0)
    assert not retained


@pytest.mark.asyncio
async def test_cancelled_body_with_confirmed_release_keeps_lease_reusable() -> None:
    connection = _Connection(row=_cutoff_row(), fetchrow_delay=1.0)
    pool = _Pool(connection)
    repository = CanonicalMarketHistoryRepository(
        pool,
        io_timeout_seconds=0.1,
        operation_timeout_seconds=1.0,
        cleanup_timeout_seconds=0.1,
    )

    task = asyncio.create_task(repository.fetch_latest_cutoff(KEY))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repository.poisoned is False
    assert not repository._retained_cleanup_tasks
    connection.fetchrow_delay = 0.0
    assert await repository.fetch_latest_cutoff(KEY) == BASE + timedelta(hours=1)


@pytest.mark.asyncio
async def test_cancelled_body_preserves_cancellation_when_release_fails() -> None:
    connection = _Connection(fetchrow_delay=1.0)
    pool = _Pool(connection, release_error=RuntimeError("release failed"))
    repository = CanonicalMarketHistoryRepository(
        pool,
        io_timeout_seconds=0.1,
        operation_timeout_seconds=1.0,
        cleanup_timeout_seconds=0.1,
    )

    task = asyncio.create_task(repository.fetch_latest_cutoff(KEY))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repository.poisoned is True
    assert connection.terminate_calls == 1


@pytest.mark.asyncio
async def test_expired_transaction_does_not_start_a_fresh_sql_phase() -> None:
    connection = _Connection(start_delay=0.05)
    pool = _Pool(connection)
    repository = CheckpointRepository(
        pool,
        io_timeout_seconds=0.01,
        operation_timeout_seconds=0.01,
        cleanup_timeout_seconds=0.05,
    )

    with pytest.raises(OperationTimeout):
        await repository.save(_checkpoint())
    assert connection.transaction_events == ["start"]
    assert connection.fetchrow_calls == []
    assert connection.execute_calls == []


@pytest.mark.asyncio
async def test_cancelled_cleanup_child_is_not_confirmed_success() -> None:
    retained: set[asyncio.Task[object]] = set()
    child = asyncio.create_task(asyncio.sleep(1.0))
    child.cancel()

    with pytest.raises(CleanupTimeout, match="cancelled"):
        await cleanup_with_timeout(
            child,
            0.1,
            operation="cancelled cleanup",
            retained_tasks=retained,
        )

    assert child.cancelled()
    assert retained == {child}
    await asyncio.sleep(0)
    assert not retained


@pytest.mark.asyncio
async def test_rollback_cleanup_can_confirm_lease_reset_without_poisoning() -> None:
    connection = _Connection(fetchrow_delay=0.05)
    pool = _Pool(connection)
    repository = CheckpointRepository(
        pool,
        io_timeout_seconds=0.01,
        operation_timeout_seconds=0.01,
        cleanup_timeout_seconds=0.1,
    )

    with pytest.raises(OperationTimeout):
        await repository.save(_checkpoint())

    assert connection.transaction_events == ["start", "rollback"]
    assert repository.poisoned is False
    assert not repository._retained_cleanup_tasks
    assert pool.release_timeouts[0] < 0.1


@pytest.mark.asyncio
async def test_real_checkpoint_lock_timeout_releases_and_reuses_pool() -> None:
    dsn = os.getenv("DECISION_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set DECISION_TEST_POSTGRES_DSN for the isolated backend probe")

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1, timeout=1.0)
    blocker = await asyncpg.connect(dsn, timeout=1.0)
    monitor = await asyncpg.connect(dsn, timeout=1.0)
    retained: set[asyncio.Task[object]] = set()
    try:
        await ensure_checkpoint_schema(
            pool,
            io_timeout_seconds=0.05,
            operation_timeout_seconds=0.5,
            cleanup_timeout_seconds=0.1,
            retained_cleanup_tasks=retained,
        )
        await blocker.execute("BEGIN")
        await blocker.execute(
            "LOCK TABLE decision.state_checkpoints IN ACCESS EXCLUSIVE MODE"
        )

        repository = CheckpointRepository(
            pool,
            io_timeout_seconds=0.05,
            operation_timeout_seconds=0.1,
            cleanup_timeout_seconds=0.1,
        )
        with pytest.raises(OperationTimeout):
            await repository.save(_checkpoint())

        assert repository.poisoned is False
        assert not repository._retained_cleanup_tasks
        assert pool.get_idle_size() == 1
        assert (
            await monitor.fetchval(
                """
                SELECT count(*)
                  FROM pg_locks
                 WHERE relation = 'decision.state_checkpoints'::regclass
                   AND pid <> pg_backend_pid()
                """
            )
            >= 1
        )

        await blocker.execute("ROLLBACK")
        assert (
            await monitor.fetchval(
                """
                SELECT count(*)
                  FROM pg_locks
                 WHERE relation = 'decision.state_checkpoints'::regclass
                   AND pid <> pg_backend_pid()
                """
            )
            == 0
        )
        assert await repository.load(IDENTITY) is None
    finally:
        if not blocker.is_closed():
            await blocker.close()
        if not monitor.is_closed():
            await monitor.close()
        await pool.close()


@pytest.mark.asyncio
async def test_real_shadow_progress_lock_timeout_releases_and_reuses_pool() -> None:
    dsn = os.getenv("DECISION_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set DECISION_TEST_POSTGRES_DSN for the isolated backend probe")

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1, timeout=1.0)
    blocker = await asyncpg.connect(dsn, timeout=1.0)
    try:
        await ensure_checkpoint_schema(
            pool,
            io_timeout_seconds=0.05,
            operation_timeout_seconds=0.5,
            cleanup_timeout_seconds=0.1,
            retained_cleanup_tasks=set(),
        )
        await blocker.execute("BEGIN")
        await blocker.execute(
            "LOCK TABLE decision.shadow_progress IN ACCESS EXCLUSIVE MODE"
        )
        repository = LaneEffectProgressRepository(
            pool,
            io_timeout_seconds=0.05,
            operation_timeout_seconds=0.1,
            cleanup_timeout_seconds=0.1,
        )

        with pytest.raises(OperationTimeout):
            await repository.save(_progress())

        assert repository.poisoned is False
        assert not repository._retained_cleanup_tasks
        assert pool.get_idle_size() == 1
        await blocker.execute("ROLLBACK")
        assert await repository.load(IDENTITY) is None
    finally:
        if not blocker.is_closed():
            await blocker.close()
        await pool.close()


@pytest.mark.asyncio
async def test_real_asyncpg_query_cancellation_and_repeated_pool_cycles() -> None:
    dsn = os.getenv("DECISION_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set DECISION_TEST_POSTGRES_DSN for the isolated backend probe")

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=1, timeout=1.0)
    try:
        async with pool.acquire() as connection:
            with pytest.raises((TimeoutError, asyncpg.PostgresError)):
                await connection.fetchval("SELECT pg_sleep(1)", timeout=0.05)
            assert await connection.fetchval("SELECT 1", timeout=0.2) == 1

        for cycle in range(5):
            async with pool.acquire() as connection:
                assert (
                    await connection.fetchval("SELECT $1::integer", cycle, timeout=0.2)
                    == cycle
                )
        assert pool.get_size() == 1
        assert pool.get_idle_size() == 1
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_real_asyncpg_commit_can_be_reconciled_after_connection_close() -> None:
    dsn = os.getenv("DECISION_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set DECISION_TEST_POSTGRES_DSN for the isolated backend probe")

    probe_id = f"commit-{asyncio.get_running_loop().time():.9f}"
    writer = await asyncpg.connect(dsn, timeout=1.0)
    reader = await asyncpg.connect(dsn, timeout=1.0)
    try:
        await writer.execute(
            """
            CREATE TABLE IF NOT EXISTS decision.deadline_commit_probe (
                probe_id text PRIMARY KEY,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        await writer.execute("BEGIN")
        await writer.execute(
            "INSERT INTO decision.deadline_commit_probe (probe_id) VALUES ($1)",
            probe_id,
        )
        await writer.execute("COMMIT", timeout=0.2)
        await writer.close()
        writer = None
        assert (
            await reader.fetchval(
                "SELECT count(*) FROM decision.deadline_commit_probe WHERE probe_id = $1",
                probe_id,
                timeout=0.2,
            )
            == 1
        )
    finally:
        if writer is not None and not writer.is_closed():
            await writer.close()
        await reader.execute(
            "DELETE FROM decision.deadline_commit_probe WHERE probe_id = $1",
            probe_id,
        )
        await reader.execute("DROP TABLE IF EXISTS decision.deadline_commit_probe")
        await reader.close()


@pytest.mark.asyncio
async def test_release_timeout_poisoned_repository_blocks_reuse() -> None:
    release_gate = asyncio.Event()
    connection = _Connection(row=_cutoff_row())
    pool = _Pool(connection, release_gate=release_gate)
    repository = CanonicalMarketHistoryRepository(
        pool,
        io_timeout_seconds=0.01,
        operation_timeout_seconds=0.01,
        cleanup_timeout_seconds=0.01,
    )

    with pytest.raises(CleanupTimeout):
        await repository.fetch_latest_cutoff(KEY)
    assert repository.poisoned is True
    assert connection.terminate_calls == 1
    assert repository._retained_cleanup_tasks

    with pytest.raises(RuntimeError, match="poisoned"):
        await repository.fetch_latest_cutoff(KEY)

    release_gate.set()
    await asyncio.wait_for(pool.release_done.wait(), timeout=0.1)
    await asyncio.sleep(0)
    assert not repository._retained_cleanup_tasks


@pytest.mark.asyncio
async def test_cleanup_completion_race_preserves_caller_cancellation(
    monkeypatch,
) -> None:
    retained: set[asyncio.Task[object]] = set()

    async def cleanup() -> None:
        return None

    child = asyncio.create_task(cleanup())
    await child
    owner_ref: dict[str, asyncio.Task[object]] = {}

    async def cancel_owner_after_shield(awaitable):
        asyncio.get_running_loop().call_soon(owner_ref["task"].cancel)
        await asyncio.sleep(0)
        return await awaitable

    monkeypatch.setattr(deadlines_module.asyncio, "shield", cancel_owner_after_shield)
    owner = asyncio.create_task(
        cleanup_with_timeout(
            child,
            0.1,
            operation="completion race",
            retained_tasks=retained,
        )
    )
    owner_ref["task"] = owner
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert child.done() is True
    assert not retained
