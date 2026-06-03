"""Tests for IdempotencyStore — is_duplicate, mark_processed, LRU eviction."""

from __future__ import annotations

import pytest

from libs.execution.idempotency import IdempotencyStore


class TestIdempotencyBasic:
    def test_new_key_not_duplicate(self):
        store = IdempotencyStore(max_size=100)
        assert store.is_duplicate("key-1") is False

    def test_processed_key_is_duplicate(self):
        store = IdempotencyStore(max_size=100)
        store.mark_processed("key-1", 1700000000.0)
        assert store.is_duplicate("key-1") is True

    def test_different_keys_not_duplicate(self):
        store = IdempotencyStore(max_size=100)
        store.mark_processed("key-1", 1700000000.0)
        assert store.is_duplicate("key-2") is False


class TestIdempotencyLRUEviction:
    def test_eviction_at_capacity(self):
        store = IdempotencyStore(max_size=3)

        store.mark_processed("key-1", 1.0)
        store.mark_processed("key-2", 2.0)
        store.mark_processed("key-3", 3.0)

        # All three should be present
        assert store.is_duplicate("key-1") is True
        assert store.is_duplicate("key-2") is True
        assert store.is_duplicate("key-3") is True

        # Adding a fourth should evict the oldest (key-1)
        store.mark_processed("key-4", 4.0)
        assert store.is_duplicate("key-1") is False
        assert store.is_duplicate("key-2") is True
        assert store.is_duplicate("key-4") is True

    def test_reprocessing_moves_to_end(self):
        store = IdempotencyStore(max_size=3)

        store.mark_processed("key-1", 1.0)
        store.mark_processed("key-2", 2.0)
        store.mark_processed("key-3", 3.0)

        # Re-mark key-1, should move it to end
        store.mark_processed("key-1", 4.0)

        # Adding key-4 should evict key-2 (now oldest)
        store.mark_processed("key-4", 5.0)
        assert store.is_duplicate("key-1") is True
        assert store.is_duplicate("key-2") is False
        assert store.is_duplicate("key-3") is True
        assert store.is_duplicate("key-4") is True

    def test_max_size_one(self):
        store = IdempotencyStore(max_size=1)

        store.mark_processed("key-1", 1.0)
        assert store.is_duplicate("key-1") is True

        store.mark_processed("key-2", 2.0)
        assert store.is_duplicate("key-1") is False
        assert store.is_duplicate("key-2") is True


class TestIdempotencyPersistence:
    @pytest.mark.asyncio
    async def test_check_duplicate_uses_db_fallback(self):
        class _Conn:
            def __init__(self) -> None:
                self.fetchrow = AsyncMock(return_value={"ts": 123.0})

        class _Acquire:
            def __init__(self, conn):
                self.conn = conn

            async def __aenter__(self):
                return self.conn

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Pool:
            def __init__(self, conn):
                self.conn = conn

            def acquire(self):
                return _Acquire(self.conn)

        from unittest.mock import AsyncMock

        store = IdempotencyStore(max_size=2)
        found = await store.check_duplicate("persisted-key", _Pool(_Conn()))

        assert found is True
        assert store.is_duplicate("persisted-key") is True

    @pytest.mark.asyncio
    async def test_save_does_not_prune_existing_db_rows(self):
        executed = []

        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Conn:
            async def execute(self, query, *args):
                executed.append(query)

            def transaction(self):
                return _Tx()

        class _Acquire:
            def __init__(self, conn):
                self.conn = conn

            async def __aenter__(self):
                return self.conn

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Pool:
            def __init__(self, conn):
                self.conn = conn

            def acquire(self):
                return _Acquire(self.conn)

        store = IdempotencyStore(max_size=2)
        store.mark_processed("key-1", 1.0)
        await store.save(_Pool(_Conn()))

        assert not any("DELETE FROM execution_idempotency_keys" in query for query in executed)
