"""IdempotencyStore — bounded LRU dedup for order execution."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


class IdempotencyStore:
    def __init__(self, max_size: int = 10_000) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size

    def is_duplicate(self, key: str) -> bool:
        return key in self._seen

    def mark_processed(self, key: str, timestamp: float) -> None:
        if key in self._seen:
            self._seen.move_to_end(key)
        self._seen[key] = timestamp
        while len(self._seen) > self._max_size:
            self._seen.popitem(last=False)

    async def save(self, db_pool: Any) -> None:
        """Persist current state to database. Requires asyncpg pool."""
        if db_pool is None:
            logger.debug("No db_pool provided — skipping idempotency save")
            return
        async with db_pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS execution_idempotency_keys "
                "(key TEXT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL)"
            )
            await conn.execute("DELETE FROM execution_idempotency_keys")
            for key, ts in self._seen.items():
                await conn.execute(
                    "INSERT INTO execution_idempotency_keys (key, ts) VALUES ($1, $2)",
                    key,
                    ts,
                )

    @classmethod
    async def load(cls, db_pool: Any, max_size: int = 10_000) -> IdempotencyStore:
        """Load from database. Returns empty store if table doesn't exist."""
        store = cls(max_size=max_size)
        if db_pool is None:
            return store
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT key, ts FROM execution_idempotency_keys ORDER BY ts"
                )
                for row in rows:
                    store.mark_processed(row["key"], row["ts"])
        except Exception:
            logger.debug("idempotency_keys table not found — starting empty")
        return store
