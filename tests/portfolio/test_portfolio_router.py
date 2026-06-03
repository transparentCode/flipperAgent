"""Tests for portfolio API summary route."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.api_app.routers.portfolio import portfolio_summary


class FakeRecord(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class FakeConnection:
    def __init__(self, fetchrow_results=None, fetch_results=None):
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])

    async def fetchrow(self, query, *args):
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def fetch(self, query, *args):
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []


class FakePool:
    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def acquire(self):
        return _Ctx(self._conn)


class _Ctx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_portfolio_summary_nets_commissions_in_trade_stats():
    conn = FakeConnection(
        fetchrow_results=[
            FakeRecord(
                timestamp=1000.0,
                equity=10000.0,
                balance=9999.5,
                unrealized_pnl=0.5,
                drawdown_pct=0.0,
                open_position_count=1,
                net_exposure_pct=10.0,
                gross_exposure_pct=10.0,
            ),
        ],
        fetch_results=[
            [
                FakeRecord(realized_pnl=10.0, commission_total=0.5, duration_seconds=60.0, slippage_bps=2.0),
                FakeRecord(realized_pnl=-4.0, commission_total=0.25, duration_seconds=120.0, slippage_bps=4.0),
            ],
        ],
    )

    with patch(
        "apps.api_app.routers.portfolio.DBPoolManager.get_reader_pool",
        return_value=FakePool(conn),
    ):
        result = await portfolio_summary()

    assert result["equity"]["balance"] == 9999.5
    assert result["trades"]["total_pnl"] == pytest.approx(5.25)
    assert result["trades"]["avg_pnl"] == pytest.approx(2.625)
    assert result["trades"]["avg_win"] == pytest.approx(9.5)
    assert result["trades"]["avg_loss"] == pytest.approx(-4.25)
