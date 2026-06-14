"""Tests for apps/portfolio_app/runtime/mark_worker.py."""

from __future__ import annotations

import pytest

from apps.portfolio_app.runtime.mark_worker import PortfolioMarkWorker
from libs.common.position_matcher import OpenPosition
from libs.contracts.schemas import PriceUpdate, valkey_encode
from libs.portfolio.state import PortfolioState


class FakeConnection:
    def __init__(self):
        self.executed: list[tuple] = []

    async def execute(self, query, *args):
        self.executed.append(("execute", query, args))


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


class FakeConfigManager:
    def __init__(self, data: dict | None = None):
        self._data = data or {}

    def get(self, key: str, default=None):
        parts = key.split(".")
        current = self._data
        for part in parts:
            if not isinstance(current, dict):
                return default
            current = current.get(part)
            if current is None:
                return default
        return current


@pytest.mark.asyncio
async def test_mark_worker_updates_state_and_persists_equity_snapshot() -> None:
    conn = FakeConnection()
    state = PortfolioState(balance=10_000.0, peak_equity=10_000.0)
    state.matcher.open_positions.setdefault("BTCUSDT", []).append(
        OpenPosition(
            asset="BTCUSDT",
            side="buy",
            size=1.0,
            entry_price=100.0,
            timestamp=1000.0,
            metadata={},
        ),
    )
    worker = PortfolioMarkWorker(
        asset="BTCUSDT",
        timeframe="1h",
        db_pool=FakePool(conn),
        config_mgr=FakeConfigManager({}),
        shared_state=state,
    )

    payload = valkey_encode(
        PriceUpdate(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=2000.0,
            open=100.0,
            high=112.0,
            low=97.0,
            close=110.0,
            volume=1.0,
        ),
        inject_trace=False,
    )
    await worker.process_message("1-0", payload)

    key = ("BTCUSDT", 1000.0, 100.0)
    assert state.position_marks[key] == pytest.approx(110.0)
    assert state.position_watermarks[key]["worst_price"] == pytest.approx(97.0)
    assert state.position_watermarks[key]["best_price"] == pytest.approx(112.0)
    execute_calls = [call for call in conn.executed if call[0] == "execute"]
    assert execute_calls
    assert "portfolio_equity_curve" in execute_calls[0][1]
    assert execute_calls[0][2][1] == pytest.approx(10010.0)
    assert execute_calls[0][2][3] == pytest.approx(10.0)
