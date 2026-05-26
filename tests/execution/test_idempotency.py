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
