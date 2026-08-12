from __future__ import annotations

from typing import Self

import pytest

from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema


class _Transaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None
        return False


class _Connection:
    def __init__(self, error: Exception | None = None) -> None:
        self.transaction_context = _Transaction()
        self.schema_sql: str | None = None
        self.error = error

    def transaction(self) -> _Transaction:
        return self.transaction_context

    async def execute(self, schema_sql: str) -> None:
        if self.error is not None:
            raise self.error
        self.schema_sql = schema_sql


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        return False


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_bootstrap_executes_schema_once_inside_transaction() -> None:
    connection = _Connection()

    await apply_ingestion_schema(_Pool(connection))

    assert connection.transaction_context.committed
    assert not connection.transaction_context.rolled_back
    assert connection.schema_sql is not None
    assert "CREATE SCHEMA IF NOT EXISTS ingestion" in connection.schema_sql
    assert "CREATE TABLE IF NOT EXISTS ingestion.candles" in connection.schema_sql
    assert "CREATE TABLE IF NOT EXISTS ingestion.outbox" in connection.schema_sql
    assert "create_hypertable" in connection.schema_sql


@pytest.mark.asyncio
async def test_bootstrap_propagates_database_errors() -> None:
    connection = _Connection(RuntimeError("schema failure"))

    with pytest.raises(RuntimeError, match="schema failure"):
        await apply_ingestion_schema(_Pool(connection))

    assert connection.transaction_context.rolled_back
    assert not connection.transaction_context.committed
