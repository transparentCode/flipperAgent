from __future__ import annotations

from pathlib import Path
from typing import Iterable

import asyncpg

from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component="ALERTING")

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_SCHEMA_BOOTSTRAP_LOCK_ID = 48_216_422


def _split_sql_statements(schema_sql: str) -> list[str]:
    lines: list[str] = []
    for line in schema_sql.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]


def _is_idempotent_schema_error(exc: Exception) -> bool:
    message = str(exc).lower()
    duplicate_markers: Iterable[str] = ("already exists",)
    return any(marker in message for marker in duplicate_markers)


async def apply_alert_schema(pool: asyncpg.Pool) -> None:
    statements = _split_sql_statements(_SCHEMA_PATH.read_text())
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT pg_advisory_lock($1)", _SCHEMA_BOOTSTRAP_LOCK_ID)
        try:
            for statement in statements:
                try:
                    await conn.execute(statement)
                except Exception as exc:
                    if _is_idempotent_schema_error(exc):
                        logger.info(
                            "Skipping existing alert schema statement: %s",
                            statement.splitlines()[0],
                        )
                        continue
                    raise
        finally:
            await conn.fetchval("SELECT pg_advisory_unlock($1)", _SCHEMA_BOOTSTRAP_LOCK_ID)

