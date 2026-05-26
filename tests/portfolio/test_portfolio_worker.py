"""Tests for apps/portfolio_app/portfolio_worker.py — mock Valkey + DB."""

import pytest

from libs.contracts.schemas import (
    ClosedTrade,
    ExecutionReport,
    OrderFill,
    OrderStatus,
    PositionState,
)
from apps.portfolio_app.portfolio_worker import PortfolioWorker


# ---------------------------------------------------------------------------
# Fake DB pool
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class FakeConnection:
    def __init__(self):
        self.executed: list[tuple] = []
        self.fetchrow_result: dict | None = None

    async def fetch(self, query, *args):
        self.executed.append(("fetch", query, args))
        return []

    async def fetchrow(self, query, *args):
        self.executed.append(("fetchrow", query, args))
        return self.fetchrow_result

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


# ---------------------------------------------------------------------------
# Fake ConfigManager
# ---------------------------------------------------------------------------

class FakeConfigManager:
    def __init__(self, data: dict | None = None):
        self._data = data or {}

    def get(self, key: str, default=None):
        parts = key.split(".")
        d = self._data
        for p in parts:
            if isinstance(d, dict):
                d = d.get(p)
            else:
                return default
            if d is None:
                return default
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_report(
    side: str = "buy",
    price: float = 100.0,
    size: float = 1.0,
    ts: float = 1000.0,
    asset: str = "BTCUSDT",
    metadata: dict | None = None,
    fills: list | None = None,
) -> ExecutionReport:
    return ExecutionReport(
        order_id="ord-1",
        idempotency_key="idem-1",
        asset=asset,
        side=side,
        requested_size=size,
        filled_size=size,
        requested_price=price,
        average_fill_price=price,
        status=OrderStatus.FILLED,
        fills=fills or [
            OrderFill(fill_id="f1", asset=asset, side=side, size=size,
                      fill_price=price, timestamp=ts)
        ],
        slippage_bps=1.0,
        timestamp=ts,
        metadata=metadata or {},
    )


def _make_worker(conn: FakeConnection) -> PortfolioWorker:
    pool = FakePool(conn)
    cfg = FakeConfigManager({"portfolio": {"consumer": {"group_name": "test_group"}}})
    return PortfolioWorker(asset="BTCUSDT", db_pool=pool, config_mgr=cfg)


def _set_snapshot(conn: FakeConnection, equity: float = 10000.0):
    """Configure the mock to return an account snapshot for _snapshot_equity."""
    conn.fetchrow_result = FakeRecord(
        equity=equity,
        balance=equity,
        unrealized_pnl=0.0,
        drawdown_pct=0.0,
        open_position_count=0,
    )


# ---------------------------------------------------------------------------
# _decode_report
# ---------------------------------------------------------------------------

class TestDecodeReport:
    def test_decode_string_payload(self):
        payload = {
            "order_id": "ord-1",
            "idempotency_key": "idem-1",
            "asset": "BTCUSDT",
            "side": "buy",
            "requested_size": "1.0",
            "filled_size": "1.0",
            "requested_price": "100.0",
            "average_fill_price": "100.0",
            "status": "FILLED",
            "fills": "[]",
            "slippage_bps": "1.0",
            "timestamp": "1000.0",
            "metadata": '{"model_name": "TestModel"}',
        }
        report = PortfolioWorker._decode_report(payload)
        assert report.order_id == "ord-1"
        assert report.average_fill_price == 100.0
        assert report.metadata["model_name"] == "TestModel"

    def test_decode_bytes_payload(self):
        payload = {
            b"order_id": b"ord-1",
            b"idempotency_key": b"idem-1",
            b"asset": b"BTCUSDT",
            b"side": b"buy",
            b"requested_size": b"1.0",
            b"filled_size": b"1.0",
            b"requested_price": b"100.0",
            b"average_fill_price": b"100.0",
            b"status": b"FILLED",
            b"fills": b"[]",
            b"slippage_bps": b"1.0",
            b"timestamp": b"1000.0",
            b"metadata": b"{}",
        }
        report = PortfolioWorker._decode_report(payload)
        assert report.asset == "BTCUSDT"


# ---------------------------------------------------------------------------
# _process_fill — open positions
# ---------------------------------------------------------------------------

class TestProcessFillOpen:
    @pytest.mark.asyncio
    async def test_buy_opens_long(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        report = _make_report(side="buy", price=100.0, ts=1000)
        await worker._process_fill(report)

        assert len(worker._open_positions) == 1
        assert worker._open_positions[0].direction == 1
        assert worker._open_positions[0].entry_price == 100.0

    @pytest.mark.asyncio
    async def test_sell_opens_short_when_no_longs(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        report = _make_report(side="sell", price=100.0, ts=1000)
        await worker._process_fill(report)

        assert len(worker._open_positions) == 1
        assert worker._open_positions[0].direction == -1

    @pytest.mark.asyncio
    async def test_non_filled_status_ignored(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        report = _make_report(side="buy")
        report.status = OrderStatus.REJECTED
        await worker._process_fill(report)

        assert len(worker._open_positions) == 0


# ---------------------------------------------------------------------------
# _process_fill — close positions
# ---------------------------------------------------------------------------

class TestProcessFillClose:
    @pytest.mark.asyncio
    async def test_sell_closes_long_fifo(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        # Open long
        await worker._process_fill(_make_report(side="buy", price=100.0, ts=1000))
        assert len(worker._open_positions) == 1

        # Close long
        await worker._process_fill(_make_report(side="sell", price=110.0, ts=2000))
        assert len(worker._open_positions) == 0

        # Should have saved a closed trade
        trade_inserts = [
            c for c in conn.executed
            if c[0] == "execute" and "portfolio_closed_trades" in c[1]
        ]
        assert len(trade_inserts) == 1

    @pytest.mark.asyncio
    async def test_buy_closes_short_fifo(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        # Open short
        await worker._process_fill(_make_report(side="sell", price=100.0, ts=1000))
        assert len(worker._open_positions) == 1

        # Close short
        await worker._process_fill(_make_report(side="buy", price=90.0, ts=2000))
        assert len(worker._open_positions) == 0

    @pytest.mark.asyncio
    async def test_pnl_calculation_long(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        # Long: buy at 100, sell at 110, size 1 => pnl = 10
        await worker._process_fill(_make_report(side="buy", price=100.0, ts=1000))
        await worker._process_fill(_make_report(side="sell", price=110.0, ts=2000))

        # Find the save_closed_trade execute call
        execute_calls = [c for c in conn.executed if c[0] == "execute" and "portfolio_closed_trades" in c[1]]
        assert len(execute_calls) == 1
        args = execute_calls[0][2]
        # realized_pnl is the 7th param (index 6)
        realized_pnl = args[6]
        assert realized_pnl == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# MAE/MFE tracking
# ---------------------------------------------------------------------------

class TestMaeMfe:
    @pytest.mark.asyncio
    async def test_mae_mfe_for_long(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        # Open long at 100
        await worker._process_fill(_make_report(side="buy", price=100.0, ts=1000))

        # Simulate price drop (adversity) via another fill at 95
        # This updates watermarks for all open positions
        await worker._process_fill(
            _make_report(side="buy", price=95.0, ts=1500, asset="BTCUSDT")
        )

        # Now close first position at 110
        # Pop first long which had watermarks updated
        first_pos = worker._open_positions[0]
        wm = worker._position_watermarks.get(id(first_pos))
        assert wm is not None
        assert wm["worst_price"] == 95.0  # went down to 95
        assert wm["best_price"] == 100.0  # best was entry at 100 (then 95 was worse)

    @pytest.mark.asyncio
    async def test_watermarks_init_at_entry_price(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        await worker._process_fill(_make_report(side="buy", price=100.0, ts=1000))
        pos = worker._open_positions[0]
        wm = worker._position_watermarks[id(pos)]
        assert wm["worst_price"] == 100.0
        assert wm["best_price"] == 100.0


# ---------------------------------------------------------------------------
# _snapshot_equity
# ---------------------------------------------------------------------------

class TestSnapshotEquity:
    @pytest.mark.asyncio
    async def test_writes_equity_point(self):
        conn = FakeConnection()
        _set_snapshot(conn, equity=10000.0)
        worker = _make_worker(conn)

        await worker._snapshot_equity(1000.0)

        # Should have: 1 fetchrow (account snapshot) + 1 execute (save equity point)
        fetchrow_calls = [c for c in conn.executed if c[0] == "fetchrow"]
        execute_calls = [c for c in conn.executed if c[0] == "execute"]
        assert len(fetchrow_calls) == 1
        assert len(execute_calls) == 1
        assert "portfolio_equity_curve" in execute_calls[0][1]

    @pytest.mark.asyncio
    async def test_no_snapshot_when_no_account_data(self):
        conn = FakeConnection()
        conn.fetchrow_result = None
        worker = _make_worker(conn)

        await worker._snapshot_equity(1000.0)

        execute_calls = [c for c in conn.executed if c[0] == "execute"]
        assert len(execute_calls) == 0

    @pytest.mark.asyncio
    async def test_exposure_computed_from_open_positions(self):
        conn = FakeConnection()
        _set_snapshot(conn, equity=10000.0)
        worker = _make_worker(conn)

        # Add a mock open long position: 1 BTC at 50000
        pos = PositionState(
            asset="BTCUSDT", direction=1, entry_price=50000, current_price=50000,
            size=1.0, unrealized_pnl=0, entry_timestamp=900,
            source_model="", source_timeframe="",
        )
        worker._open_positions.append(pos)

        await worker._snapshot_equity(1000.0)

        # The equity point should include exposure
        execute_calls = [c for c in conn.executed if c[0] == "execute"]
        assert len(execute_calls) == 1
        args = execute_calls[0][2]
        # net_exposure_pct = (50000 - 0) / 10000 * 100 = 500%
        net_exposure = args[6]
        gross_exposure = args[7]
        assert net_exposure == pytest.approx(500.0)
        assert gross_exposure == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Consumer group config
# ---------------------------------------------------------------------------

class TestWorkerConfig:
    def test_uses_config_group_name(self):
        conn = FakeConnection()
        cfg = FakeConfigManager({"portfolio": {"consumer": {"group_name": "my_group"}}})
        worker = PortfolioWorker(asset="BTCUSDT", db_pool=FakePool(conn), config_mgr=cfg)
        assert worker.group_name == "my_group"

    def test_defaults_when_no_config(self):
        conn = FakeConnection()
        cfg = FakeConfigManager({})
        worker = PortfolioWorker(asset="BTCUSDT", db_pool=FakePool(conn), config_mgr=cfg)
        assert worker.group_name == "portfolio_app_fills_group"
        assert worker.fill_stream_key == "fills:BTCUSDT"
        assert worker.consumer_name == "portfolio_worker_BTCUSDT"
