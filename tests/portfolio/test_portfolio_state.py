"""Tests for shared portfolio state restoration and mark sync."""

from __future__ import annotations

import json

import pytest

from libs.common.position_matcher import OpenPosition
from libs.portfolio.state import PortfolioState


class FakeRecord(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def get(self, key, default=None):
        return super().get(key, default)


class FakeConnection:
    def __init__(self):
        self.executed: list[tuple] = []
        self.fetchrow_results: list = []
        self.fetch_results: list = []

    async def execute(self, query, *args):
        self.executed.append(("execute", query, args))

    async def fetchrow(self, query, *args):
        self.executed.append(("fetchrow", query, args))
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def fetch(self, query, *args):
        self.executed.append(("fetch", query, args))
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
async def test_load_restores_balance_positions_and_processed_fills():
    conn = FakeConnection()
    conn.fetchrow_results = [
        FakeRecord(balance=9999.5, equity=10010.0),
        FakeRecord(peak_equity=10025.0),
    ]
    conn.fetch_results = [
        [FakeRecord(order_id="ord-1"), FakeRecord(order_id="ord-2")],
        [
            FakeRecord(
                asset="BTCUSDT",
                direction=1,
                entry_price=100.0,
                current_price=105.0,
                size=0.5,
                unrealized_pnl=2.5,
                entry_timestamp=1000.0,
                source_model="MR",
                source_timeframe="1h",
                stop_loss_price=None,
                take_profit_price=None,
                trailing_stop_distance=None,
                original_size=0.5,
                tp_levels=json.dumps([]),
                tp_portions=json.dumps([]),
                tp_levels_hit=json.dumps([]),
                original_stop_loss=None,
                trail_to_breakeven=False,
            ),
        ],
    ]

    state = await PortfolioState.load(FakePool(conn), initial_balance=10000.0)

    assert state.balance == pytest.approx(9999.5)
    assert state.peak_equity == pytest.approx(10025.0)
    assert state.processed_fill_ids == {"ord-1", "ord-2"}
    positions = state.matcher.open_positions["BTCUSDT"]
    assert len(positions) == 1
    assert positions[0].size == pytest.approx(0.5)
    assert state.position_marks[("BTCUSDT", 1000.0, 100.0)] == pytest.approx(105.0)


def test_apply_price_update_updates_marks_and_watermarks() -> None:
    state = PortfolioState(balance=10_000.0, peak_equity=10_000.0)
    position = OpenPosition(
        asset="BTCUSDT",
        side="buy",
        size=1.0,
        entry_price=100.0,
        timestamp=1000.0,
        metadata={},
    )
    state.matcher.open_positions.setdefault("BTCUSDT", []).append(position)

    state.apply_price_update("BTCUSDT", high=110.0, low=95.0, close=108.0)

    key = ("BTCUSDT", 1000.0, 100.0)
    assert state.position_marks[key] == pytest.approx(108.0)
    assert state.position_watermarks[key]["worst_price"] == pytest.approx(95.0)
    assert state.position_watermarks[key]["best_price"] == pytest.approx(110.0)
