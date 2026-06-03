import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.ingestion_app.storage.bootstrap import (
    _is_idempotent_schema_error,
    _split_sql_statements,
    apply_ingestion_schema,
)


def test_split_sql_statements_ignores_comment_lines():
    schema_sql = """
    -- comment
    CREATE TABLE test_one (id INT);

    -- another comment
    ALTER TABLE test_one ADD COLUMN value INT;
    """

    statements = _split_sql_statements(schema_sql)

    assert statements == [
        "CREATE TABLE test_one (id INT)",
        "ALTER TABLE test_one ADD COLUMN value INT",
    ]


def test_is_idempotent_schema_error_detects_existing_objects():
    assert _is_idempotent_schema_error(RuntimeError("policy already exists for relation"))
    assert _is_idempotent_schema_error(RuntimeError("table is already a hypertable"))
    assert not _is_idempotent_schema_error(RuntimeError("permission denied"))


@pytest.mark.asyncio
async def test_apply_ingestion_schema_ignores_existing_policy_errors():
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = conn
    ctx.__aexit__.return_value = None
    pool.acquire.return_value = ctx

    statements_seen: list[str] = []

    async def execute_side_effect(statement: str):
        statements_seen.append(statement)
        if "add_retention_policy" in statement:
            raise RuntimeError("retention policy already exists")
        return "OK"

    conn.execute.side_effect = execute_side_effect

    with patch(
        "pathlib.Path.read_text",
        return_value="SELECT 1; SELECT add_retention_policy('ticks', INTERVAL '30 days');",
    ):
        await apply_ingestion_schema(pool)

    assert statements_seen == [
        "SELECT 1",
        "SELECT add_retention_policy('ticks', INTERVAL '30 days')",
    ]
    conn.fetchval.assert_any_await("SELECT pg_advisory_lock($1)", 48_216_421)
    conn.fetchval.assert_any_await("SELECT pg_advisory_unlock($1)", 48_216_421)
