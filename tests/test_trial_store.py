"""Tests for TrialStore utility behavior."""

from __future__ import annotations

import pytest

from libs.optim_utils.trial_store import TrialStore


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


class _Conn:
    def __init__(self):
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return []


@pytest.mark.asyncio
async def test_query_best_uses_desc_for_maximize():
    conn = _Conn()
    store = TrialStore(_Pool(conn))

    await store.query_best("study", direction="maximize")

    assert "DESC" in conn.calls[0][0]


@pytest.mark.asyncio
async def test_query_best_uses_asc_for_minimize():
    conn = _Conn()
    store = TrialStore(_Pool(conn))

    await store.query_best("study", objective_key="loss", direction="minimize")

    assert "ASC" in conn.calls[0][0]
