from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from libs.models.sr_v2.domain.bars import SRBar
from libs.models.sr_v2.domain.identity import fingerprint_sequence_hash
from libs.models.sr_v2.features.time import grid_for
from libs.models.sr_v2.persistence import (
    CheckpointCorruptionError,
    CheckpointDisposition,
    CheckpointRecord,
    SRV2LaneIdentity,
    TimescaleCheckpointRepository,
    apply_schema,
    classify_commit,
)
from libs.models.sr_v2.runtime.live import LiveCommitResult, LiveRuntime
from libs.models.sr_v2.runtime.offline import OfflineCompute

_IDENTITY = {
    "venue": "binance_usdm",
    "instrument_id": "BTCUSDT",
    "asset": "BTCUSDT",
}


def _extend_bars(bars_by_timeframe, cutoff):
    result = {}
    for timeframe, values in bars_by_timeframe.items():
        current = list(values)
        duration = grid_for(timeframe).duration
        expected = grid_for(timeframe).expected_closed_cutoff(cutoff)
        while current[-1].bar_close_at < expected:
            opened = current[-1].bar_close_at
            base = current[-1].close + 1
            current.append(
                SRBar(
                    timeframe=timeframe,
                    bar_open_at=opened,
                    bar_close_at=opened + duration,
                    market_as_of=opened + duration,
                    open=base,
                    high=base + 1,
                    low=base - 1,
                    close=base + Decimal("0.2"),
                    volume=current[-1].volume,
                    taker_buy_base=current[-1].taker_buy_base,
                )
            )
        result[timeframe] = tuple(current)
    return result


class _InMemoryCheckpointRepository:
    """Test double for the same latest-only generation-CAS contract."""

    def __init__(self):
        self.items = {}

    async def load(self, identity):
        return self.items.get(identity)

    async def commit(self, proposal, *, expected_generation):
        current = self.items.get(proposal.identity)
        disposition = classify_commit(
            current,
            proposal,
            expected_generation=expected_generation,
        )
        if disposition in {
            CheckpointDisposition.INSERTED,
            CheckpointDisposition.UPDATED,
        }:
            self.items[proposal.identity] = proposal
        return disposition


def _record_from_result(result, config):
    identity = SRV2LaneIdentity(
        venue=result.venue,
        instrument_id=result.instrument_id,
        asset=result.asset,
        config_fingerprint=config.config_fingerprint,
    )
    return CheckpointRecord.from_state(identity=identity, state=result.state)


def _alternate_same_position(record):
    sequences = {
        timeframe: tuple(values)
        for timeframe, values in record.state.source_fingerprint_sequences.items()
    }
    trigger = record.state.source_cutoffs.keys().__iter__().__next__()
    changed = list(sequences[trigger])
    changed[-1] = changed[-1] + "-corrected"
    sequences[trigger] = tuple(changed)
    fingerprints = {
        timeframe: fingerprint_sequence_hash(values)
        for timeframe, values in sequences.items()
    }
    state = replace(
        record.state,
        source_fingerprint_sequences=sequences,
        source_fingerprints=fingerprints,
    )
    return CheckpointRecord.from_state(identity=record.identity, state=state)


def test_live_restart_duplicate_and_same_cutoff_correction_fail_closed(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    async def run():
        repository = _InMemoryCheckpointRepository()
        live = LiveRuntime(
            sr_v2_config,
            **_IDENTITY,
            checkpoint_repository=repository,
            allow_genesis=True,
        )
        inserted = await live.on_closed_bar(sr_v2_bars)
        assert inserted.disposition is CheckpointDisposition.INSERTED
        assert inserted.result is not None

        offline = OfflineCompute(sr_v2_config, **_IDENTITY).run(
            sr_v2_bars,
            cutoff=sr_v2_now,
        )
        assert inserted.result == offline.final_result

        next_cutoff = sr_v2_now + sr_v2_config.trigger_duration
        next_bars = _extend_bars(sr_v2_bars, next_cutoff)
        restarted = LiveRuntime(
            sr_v2_config,
            **_IDENTITY,
            checkpoint_repository=repository,
        )
        updated = await restarted.on_closed_bar(
            {"15m": next_bars["15m"], "30m": next_bars["30m"]}
        )
        assert updated.disposition is CheckpointDisposition.UPDATED
        assert updated.result is not None

        duplicate = await restarted.on_closed_bar({"15m": next_bars["15m"]})
        assert duplicate.disposition is CheckpointDisposition.IDENTICAL
        assert duplicate.result is None

        changed = replace(next_bars["15m"][-1], close=next_bars["15m"][-1].close + Decimal(".1"))
        with pytest.raises(ValueError, match="content"):
            await restarted.on_closed_bar({"15m": (*next_bars["15m"][:-1], changed)})
        assert (await repository.load(live.identity)).state == updated.result.state

    asyncio.run(run())


def test_live_genesis_requires_explicit_permission(sr_v2_config, sr_v2_bars):
    async def run():
        with pytest.raises(ValueError, match="allow_genesis=True"):
            await LiveRuntime(
                sr_v2_config,
                **_IDENTITY,
                checkpoint_repository=_InMemoryCheckpointRepository(),
            ).on_closed_bar(sr_v2_bars)

    asyncio.run(run())


class _AlwaysConflictRepository:
    async def load(self, _identity):
        return None

    async def commit(self, _proposal, *, expected_generation):
        assert expected_generation is None
        return CheckpointDisposition.CONFLICT


def test_live_cas_loser_does_not_publish_structural_result(sr_v2_config, sr_v2_bars):
    async def run():
        outcome = await LiveRuntime(
            sr_v2_config,
            **_IDENTITY,
            checkpoint_repository=_AlwaysConflictRepository(),
            allow_genesis=True,
        ).on_closed_bar(sr_v2_bars)
        assert outcome.disposition is CheckpointDisposition.CONFLICT
        assert outcome.result is None

    asyncio.run(run())


def test_live_commit_result_requires_result_iff_commit_wins(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    final = OfflineCompute(sr_v2_config, **_IDENTITY).run(
        sr_v2_bars,
        cutoff=sr_v2_now,
    ).final_result
    identity = SRV2LaneIdentity(
        venue=final.venue,
        instrument_id=final.instrument_id,
        asset=final.asset,
        config_fingerprint=final.config_fingerprint,
    )
    with pytest.raises(ValueError, match="must include"):
        LiveCommitResult(
            identity=identity,
            cutoff=final.market_as_of,
            disposition=CheckpointDisposition.INSERTED,
            result=None,
        )
    with pytest.raises(ValueError, match="cannot publish"):
        LiveCommitResult(
            identity=identity,
            cutoff=final.market_as_of,
            disposition=CheckpointDisposition.CONFLICT,
            result=final,
        )


def test_generation_cas_has_all_dispositions_and_same_input_retry_is_identical(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    async def run():
        repository = _InMemoryCheckpointRepository()
        compute = OfflineCompute(sr_v2_config, **_IDENTITY)
        first = compute.run(sr_v2_bars, cutoff=sr_v2_now)
        next_cutoff = sr_v2_now + sr_v2_config.trigger_duration
        next_bars = _extend_bars(sr_v2_bars, next_cutoff)
        second = compute.run(
            next_bars,
            checkpoint=first.state,
            cutoff=next_cutoff,
            mode="CHECKPOINT_EXACT",
        )
        first_record = _record_from_result(first.final_result, sr_v2_config)
        second_record = _record_from_result(second.final_result, sr_v2_config)
        different = _alternate_same_position(second_record)

        assert classify_commit(None, first_record, expected_generation=None) is CheckpointDisposition.INSERTED
        assert await repository.commit(first_record, expected_generation=None) is CheckpointDisposition.INSERTED
        assert await repository.commit(first_record, expected_generation=1) is CheckpointDisposition.IDENTICAL
        assert await repository.commit(second_record, expected_generation=1) is CheckpointDisposition.UPDATED
        assert await repository.commit(second_record, expected_generation=1) is CheckpointDisposition.IDENTICAL
        assert await repository.commit(different, expected_generation=2) is CheckpointDisposition.CONFLICT
        assert await repository.commit(first_record, expected_generation=2) is CheckpointDisposition.REJECTED_OLDER
        assert classify_commit(None, second_record, expected_generation=None) is CheckpointDisposition.CONFLICT

        lower_generation_later_cutoff = CheckpointRecord.from_state(
            identity=first_record.identity,
            state=replace(
                first_record.state,
                last_trigger_at=second_record.cutoff + sr_v2_config.trigger_duration,
            ),
        )
        higher_generation_older_cutoff = CheckpointRecord.from_state(
            identity=second_record.identity,
            state=replace(
                second_record.state,
                generation=second_record.generation + 1,
                last_trigger_at=first_record.cutoff,
            ),
        )
        assert classify_commit(
            second_record,
            lower_generation_later_cutoff,
            expected_generation=second_record.generation,
        ) is CheckpointDisposition.CONFLICT
        assert classify_commit(
            second_record,
            higher_generation_older_cutoff,
            expected_generation=second_record.generation,
        ) is CheckpointDisposition.CONFLICT

    asyncio.run(run())


def test_checkpoint_record_rejects_genesis_and_tampered_payload(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    result = OfflineCompute(sr_v2_config, **_IDENTITY).run(sr_v2_bars, cutoff=sr_v2_now)
    record = _record_from_result(result.final_result, sr_v2_config)
    with pytest.raises(CheckpointCorruptionError, match="checksum"):
        CheckpointRecord(
            identity=record.identity,
            schema_version=record.schema_version,
            generation=record.generation,
            cutoff=record.cutoff,
            state=record.state,
            state_payload=record.state_payload,
            state_checksum="0" * 64,
        )
    with pytest.raises(ValueError, match="genesis"):
        CheckpointRecord.from_state(
            identity=record.identity,
            state=replace(record.state, generation=0, last_trigger_at=None),
        )


def _row(record, **overrides):
    values = {
        "state_schema_version": record.schema_version,
        "generation": record.generation,
        "cutoff": record.cutoff,
        "state_checksum": record.state_checksum,
        "state_payload": record.state_payload,
        "venue": record.identity.venue,
        "instrument_id": record.identity.instrument_id,
        "asset": record.identity.asset,
        "config_fingerprint": record.identity.config_fingerprint,
    }
    values.update(overrides)
    return values


class _AcquireContext:
    def __init__(self, connection):
        self.connection = connection
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited = True
        return False


class _FakeConnection:
    def __init__(self, row):
        self.row = row
        self.executed = []

    async def fetchrow(self, *_args):
        return self.row

    def transaction(self):
        return _TransactionContext()

    async def execute(self, statement, *_args):
        self.executed.append(statement)
        return "INSERT 0 1"


class _TransactionContext:
    def __init__(self):
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited = True
        return False


class _FakePool:
    def __init__(self, connection):
        self.context = _AcquireContext(connection)

    def acquire(self):
        return self.context


def test_timescale_adapter_rejects_bad_state_checksum_and_identity(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    result = OfflineCompute(sr_v2_config, **_IDENTITY).run(sr_v2_bars, cutoff=sr_v2_now)
    record = _record_from_result(result.final_result, sr_v2_config)
    for overrides, message in (
        ({"state_checksum": "0" * 64}, "canonical state"),
        ({"venue": "other"}, "identity"),
        ({"state_payload": b"{}"}, "invalid"),
    ):
        pool = _FakePool(_FakeConnection(_row(record, **overrides)))
        with pytest.raises(CheckpointCorruptionError, match=message):
            asyncio.run(TimescaleCheckpointRepository(pool).load(record.identity))
        assert pool.context.entered and pool.context.exited


def test_timescale_commit_uses_short_transaction_and_schema_bootstrap(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    result = OfflineCompute(sr_v2_config, **_IDENTITY).run(sr_v2_bars, cutoff=sr_v2_now)
    record = _record_from_result(result.final_result, sr_v2_config)
    connection = _FakeConnection(None)
    pool = _FakePool(connection)
    repository = TimescaleCheckpointRepository(pool)
    assert asyncio.run(repository.commit(record, expected_generation=None)) is CheckpointDisposition.INSERTED
    asyncio.run(apply_schema(pool))
    assert any("CREATE SCHEMA IF NOT EXISTS sr_v2" in statement for statement in connection.executed)


def test_timescale_absent_row_rejects_non_genesis_without_insert(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    result = OfflineCompute(sr_v2_config, **_IDENTITY).run(sr_v2_bars, cutoff=sr_v2_now)
    record = _record_from_result(result.final_result, sr_v2_config)
    connection = _FakeConnection(None)
    outcome = asyncio.run(
        TimescaleCheckpointRepository(_FakePool(connection)).commit(
            record,
            expected_generation=1,
        )
    )
    assert outcome is CheckpointDisposition.CONFLICT
    assert connection.executed == []


class _BlockingConnection:
    def __init__(self, started):
        self.started = started
        self.release = asyncio.Event()

    async def fetchrow(self, *_args):
        self.started.set()
        await self.release.wait()


class _BlockingCommitConnection:
    def __init__(self, started):
        self.started = started
        self.release = asyncio.Event()
        self.transaction_context = _TransactionContext()

    def transaction(self):
        return self.transaction_context

    async def fetchrow(self, *_args):
        return None

    async def execute(self, *_args):
        self.started.set()
        await self.release.wait()


def test_timescale_load_cancellation_releases_injected_pool_connection():
    async def run():
        started = asyncio.Event()
        connection = _BlockingConnection(started)
        pool = _FakePool(connection)
        identity = SRV2LaneIdentity(
            venue="binance_usdm",
            instrument_id="BTCUSDT",
            asset="BTCUSDT",
            config_fingerprint="config",
        )
        task = asyncio.create_task(TimescaleCheckpointRepository(pool).load(identity))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.context.exited

    asyncio.run(run())


def test_timescale_commit_cancellation_rolls_back_and_releases_connection(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    async def run():
        result = OfflineCompute(sr_v2_config, **_IDENTITY).run(sr_v2_bars, cutoff=sr_v2_now)
        record = _record_from_result(result.final_result, sr_v2_config)
        started = asyncio.Event()
        connection = _BlockingCommitConnection(started)
        pool = _FakePool(connection)
        task = asyncio.create_task(
            TimescaleCheckpointRepository(pool).commit(record, expected_generation=None)
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.context.exited
        assert connection.transaction_context.entered
        assert connection.transaction_context.exited

    asyncio.run(run())


def test_live_and_core_modules_have_no_database_or_background_task_dependency():
    root = Path("src/libs/models/sr_v2")
    for relative in ("structural.py", "runtime/offline.py", "runtime/live.py"):
        source = (root / relative).read_text()
        assert "asyncpg" not in source
        assert "create_pool" not in source
        assert "create_task" not in source
        assert "asyncio.Lock" not in source


@pytest.mark.skipif(
    os.getenv("SR_V2_RUN_DB_INTEGRATION") != "1",
    reason="set SR_V2_RUN_DB_INTEGRATION=1 for live PostgreSQL validation",
)
def test_timescale_postgresql_crud_and_cas(
    sr_v2_config,
    sr_v2_bars,
    sr_v2_now,
):
    async def run():
        import asyncpg

        dsn = os.getenv(
            "SR_V2_POSTGRES_URI",
            os.getenv("POSTGRES_URI", "postgresql://flipper:flipperpass@localhost:5432/flipper_db"),
        )
        identity_values = {
            "venue": "binance_usdm",
            "instrument_id": f"sr_v2_db_test_{uuid4().hex}",
            "asset": "BTCUSDT",
        }
        race_same_values = {
            "venue": "binance_usdm",
            "instrument_id": f"sr_v2_db_race_same_{uuid4().hex}",
            "asset": "BTCUSDT",
        }
        race_different_values = {
            "venue": "binance_usdm",
            "instrument_id": f"sr_v2_db_race_diff_{uuid4().hex}",
            "asset": "BTCUSDT",
        }
        cleanup_values = (identity_values, race_same_values, race_different_values)
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        try:
            await apply_schema(pool)
            await apply_schema(pool)
            async with pool.acquire() as connection:
                columns = await connection.fetch(
                    """
                    SELECT column_name
                      FROM information_schema.columns
                     WHERE table_schema = $1 AND table_name = $2
                     ORDER BY ordinal_position
                    """,
                    "sr_v2",
                    "checkpoints",
                )
                assert tuple(row["column_name"] for row in columns) == (
                    "venue",
                    "instrument_id",
                    "asset",
                    "config_fingerprint",
                    "state_schema_version",
                    "generation",
                    "cutoff",
                    "state_checksum",
                    "state_payload",
                )
                relkind = await connection.fetchval(
                    """
                    SELECT c.relkind
                      FROM pg_class AS c
                      JOIN pg_namespace AS n ON n.oid = c.relnamespace
                     WHERE n.nspname = $1 AND c.relname = $2
                    """,
                    "sr_v2",
                    "checkpoints",
                )
                if isinstance(relkind, bytes):
                    relkind = relkind.decode("ascii")
                assert relkind == "r"
                hypertables = await connection.fetchval(
                    """
                    SELECT COUNT(*)
                      FROM timescaledb_information.hypertables
                     WHERE hypertable_schema = $1 AND hypertable_name = $2
                    """,
                    "sr_v2",
                    "checkpoints",
                )
                assert hypertables == 0
                size_constraint = await connection.fetchrow(
                    """
                    SELECT conname, pg_get_constraintdef(oid) AS definition
                      FROM pg_constraint
                     WHERE conrelid = 'sr_v2.checkpoints'::regclass
                       AND conname = 'state_payload_size_check'
                    """
                )
                assert size_constraint is not None
                size_definition = size_constraint["definition"]
                assert "octet_length(state_payload)" in size_definition
                assert "16" in size_definition
                assert size_definition.count("1024") == 2
            result = OfflineCompute(sr_v2_config, **identity_values).run(
                sr_v2_bars,
                cutoff=sr_v2_now,
            )
            record = _record_from_result(result.final_result, sr_v2_config)
            repository = TimescaleCheckpointRepository(pool)
            assert await repository.commit(record, expected_generation=None) is CheckpointDisposition.INSERTED
            assert await repository.load(record.identity) == record
            assert await repository.commit(record, expected_generation=record.generation) is CheckpointDisposition.IDENTICAL
            next_cutoff = sr_v2_now + sr_v2_config.trigger_duration
            next_bars = _extend_bars(sr_v2_bars, next_cutoff)
            continued = OfflineCompute(sr_v2_config, **identity_values).run(
                next_bars,
                checkpoint=result.state,
                cutoff=next_cutoff,
                mode="CHECKPOINT_EXACT",
            )
            next_record = _record_from_result(continued.final_result, sr_v2_config)
            assert await repository.commit(next_record, expected_generation=record.generation) is CheckpointDisposition.UPDATED
            assert await repository.commit(record, expected_generation=next_record.generation) is CheckpointDisposition.REJECTED_OLDER
            assert await repository.commit(_alternate_same_position(next_record), expected_generation=next_record.generation) is CheckpointDisposition.CONFLICT

            async def records_for(identity):
                compute = OfflineCompute(sr_v2_config, **identity)
                first_result = compute.run(sr_v2_bars, cutoff=sr_v2_now)
                next_result = compute.run(
                    next_bars,
                    checkpoint=first_result.state,
                    cutoff=next_cutoff,
                    mode="CHECKPOINT_EXACT",
                )
                return (
                    _record_from_result(first_result.final_result, sr_v2_config),
                    _record_from_result(next_result.final_result, sr_v2_config),
                )

            same_current, same_next = await records_for(race_same_values)
            await repository.commit(same_current, expected_generation=None)
            same_outcomes = await asyncio.gather(
                repository.commit(same_next, expected_generation=same_current.generation),
                repository.commit(same_next, expected_generation=same_current.generation),
            )
            assert {item for item in same_outcomes} == {
                CheckpointDisposition.UPDATED,
                CheckpointDisposition.IDENTICAL,
            }

            different_current, different_next = await records_for(race_different_values)
            await repository.commit(different_current, expected_generation=None)
            different_proposal = _alternate_same_position(different_next)
            different_outcomes = await asyncio.gather(
                repository.commit(different_next, expected_generation=different_current.generation),
                repository.commit(different_proposal, expected_generation=different_current.generation),
            )
            assert {item for item in different_outcomes} == {
                CheckpointDisposition.UPDATED,
                CheckpointDisposition.CONFLICT,
            }
        finally:
            async with pool.acquire() as connection, connection.transaction():
                for cleanup in cleanup_values:
                    await connection.execute(
                        """
                        DELETE FROM sr_v2.checkpoints
                         WHERE venue = $1 AND instrument_id = $2 AND asset = $3
                        """,
                        cleanup["venue"],
                        cleanup["instrument_id"],
                        cleanup["asset"],
                    )
            await pool.close()

    asyncio.run(run())
