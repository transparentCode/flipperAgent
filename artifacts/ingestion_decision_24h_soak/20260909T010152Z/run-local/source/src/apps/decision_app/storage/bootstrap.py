"""Explicit bootstrap for the small D9A checkpoint table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


async def ensure_checkpoint_schema(pool: Any) -> None:
    """Create only the decision checkpoint schema/table when explicitly called."""

    if pool is None or not hasattr(pool, "acquire"):
        raise TypeError("pool must provide asyncpg acquire()")
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    async with pool.acquire() as connection:
        await connection.execute(sql)


__all__ = ["SCHEMA_FILE", "ensure_checkpoint_schema"]
