from __future__ import annotations

from datetime import UTC, datetime

import pytest

# Import the publication package before the storage package.  This preserves
# the repository's existing package initialization order for this focused
# module; the application composition imports publication first as well.
from apps.ingestion_app.publication.outbox import OutboxEvent  # noqa: F401
from apps.ingestion_app.storage.repository import CandleRepository


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class _Connection:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> _Transaction:
        return _Transaction()

    async def fetch(self, query: str, *args: object):
        self.fetch_calls.append((query, args))
        return [{"chunk_name": "_hyper_1_42_chunk"}]

    async def execute(self, query: str, *args: object):
        self.execute_calls.append((query, args))


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_drop_candle_chunks_reports_names_and_uses_fixed_table() -> None:
    connection = _Connection()
    repository = CandleRepository(_Pool(connection))
    cutoff = datetime(2026, 5, 13, tzinfo=UTC)

    result = await repository.drop_candle_chunks_before(cutoff=cutoff)

    assert result == ("_hyper_1_42_chunk",)
    assert len(connection.fetch_calls) == 1
    assert len(connection.execute_calls) == 1
    select_query, select_args = connection.fetch_calls[0]
    drop_query, drop_args = connection.execute_calls[0]
    assert "show_chunks(" in select_query
    assert "'ingestion.candles'" in select_query
    assert "drop_chunks('ingestion.candles'" in drop_query
    assert select_args == (cutoff,)
    assert drop_args == (cutoff,)


@pytest.mark.asyncio
async def test_drop_candle_chunks_rejects_non_utc_cutoff() -> None:
    connection = _Connection()
    repository = CandleRepository(_Pool(connection))

    with pytest.raises(ValueError, match="cutoff"):
        await repository.drop_candle_chunks_before(
            cutoff=datetime(2026, 5, 13),  # noqa: DTZ001
        )

    assert connection.fetch_calls == []
    assert connection.execute_calls == []
