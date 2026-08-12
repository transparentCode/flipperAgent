"""Idempotent bootstrap for the ingestion Timescale schema."""

from __future__ import annotations

from pathlib import Path

import asyncpg

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


async def apply_ingestion_schema(pool: asyncpg.Pool) -> None:
    """Apply the ingestion schema in one transaction and propagate database errors."""
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")

    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(schema_sql)


__all__ = ["apply_ingestion_schema"]
