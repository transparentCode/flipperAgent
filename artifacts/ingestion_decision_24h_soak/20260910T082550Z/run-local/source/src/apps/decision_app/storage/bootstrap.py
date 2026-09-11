"""Explicit bootstrap for the small D9A checkpoint table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.decision_app.runtime.deadlines import (
    CleanupBudget,
    Deadline,
    acquire_db_connection,
    native_timeout_kwargs,
    require_remaining,
    run_until,
)

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


async def ensure_checkpoint_schema(
    pool: Any,
    *,
    io_timeout_seconds: float | None = None,
    operation_timeout_seconds: float | None = None,
    cleanup_timeout_seconds: float | None = None,
    retained_cleanup_tasks: set[Any] | None = None,
    cleanup_budget: CleanupBudget | None = None,
) -> None:
    """Create only the decision checkpoint schema/table when explicitly called."""

    if pool is None or not hasattr(pool, "acquire"):
        raise TypeError("pool must provide asyncpg acquire()")
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    if operation_timeout_seconds is None:
        async with pool.acquire() as connection:
            await connection.execute(sql)
        return
    if cleanup_timeout_seconds is None:
        cleanup_timeout_seconds = 5.0
    if retained_cleanup_tasks is None:
        raise TypeError(
            "retained_cleanup_tasks is required for bounded schema bootstrap"
        )
    deadline = Deadline.after(operation_timeout_seconds)
    async with acquire_db_connection(
        pool,
        deadline=deadline,
        io_timeout_seconds=io_timeout_seconds,
        cleanup_timeout_seconds=cleanup_timeout_seconds,
        retained_tasks=retained_cleanup_tasks,
        cleanup_budget=cleanup_budget,
        operation="checkpoint schema bootstrap",
    ) as connection:
        await run_until(
            connection.execute(
                sql,
                **native_timeout_kwargs(
                    deadline,
                    operation="checkpoint schema execute",
                ),
            ),
            deadline,
            operation="checkpoint schema execute",
        )
    require_remaining(deadline, operation="checkpoint schema bootstrap")


__all__ = ["SCHEMA_FILE", "ensure_checkpoint_schema"]
