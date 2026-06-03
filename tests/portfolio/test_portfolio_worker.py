"""Tests for apps/portfolio_app/portfolio_worker.py — mock Valkey + DB."""

import asyncio
import pytest

from libs.portfolio.state import PortfolioState
from libs.contracts.schemas import (
    ClosedTrade,
    ExecutionReport,
    OrderFill,
    OrderStatus,
)
from libs.common.position_matcher import OpenPosition
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
        self.fetchrow_results: list = []

    async def fetch(self, query, *args):
        self.executed.append(("fetch", query, args))
        return []

    async def fetchrow(self, query, *args):
        self.executed.append(("fetchrow", query, args))
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return self.fetchrow_result

    async def execute(self, query, *args):
        self.executed.append(("execute", query, args))

    def transaction(self):
        return _TxCtx()


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


class _TxCtx:
    async def __aenter__(self):
        return self

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
    order_id: str | None = None,
    idempotency_key: str | None = None,
) -> ExecutionReport:
    return ExecutionReport(
        order_id=order_id or f"ord-{asset}-{side}-{int(ts * 1000)}",
        idempotency_key=idempotency_key or f"idem-{asset}-{side}-{int(ts * 1000)}",
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


def _make_shared_worker(
    conn: FakeConnection,
    asset: str,
    state: PortfolioState,
) -> PortfolioWorker:
    pool = FakePool(conn)
    cfg = FakeConfigManager({"portfolio": {"consumer": {"group_name": "test_group"}}})
    return PortfolioWorker(asset=asset, db_pool=pool, config_mgr=cfg, shared_state=state)


def _set_snapshot(conn: FakeConnection, equity: float = 10000.0):
    """Legacy helper retained for backwards compatibility with older tests."""
    conn.fetchrow_result = None
    conn.fetchrow_results = []


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

        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].side == "buy"
        assert positions[0].entry_price == 100.0

    @pytest.mark.asyncio
    async def test_sell_opens_short_when_no_longs(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        report = _make_report(side="sell", price=100.0, ts=1000)
        await worker._process_fill(report)

        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].side == "sell"

    @pytest.mark.asyncio
    async def test_non_filled_status_ignored(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        report = _make_report(side="buy")
        report.status = OrderStatus.REJECTED
        await worker._process_fill(report)

        assert len(worker._matcher.open_positions.get("BTCUSDT", [])) == 0

    @pytest.mark.asyncio
    async def test_entry_commission_reduces_balance(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        report = _make_report(side="buy", price=100.0, size=1.0, ts=1000)
        report.fills[0].commission = 0.25
        await worker._process_fill(report)

        assert worker._balance == pytest.approx(9999.75)


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
        assert len(worker._matcher.open_positions.get("BTCUSDT", [])) == 1

        # Close long
        await worker._process_fill(_make_report(side="sell", price=110.0, ts=2000))
        assert len(worker._matcher.open_positions.get("BTCUSDT", [])) == 0

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
        assert len(worker._matcher.open_positions.get("BTCUSDT", [])) == 1

        # Close short
        await worker._process_fill(_make_report(side="buy", price=90.0, ts=2000))
        assert len(worker._matcher.open_positions.get("BTCUSDT", [])) == 0

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

        # Check watermarks for first position (stable key)
        first_pos = worker._matcher.open_positions["BTCUSDT"][0]
        wm_key = (first_pos.asset, first_pos.timestamp, first_pos.entry_price)
        wm = worker._position_watermarks.get(wm_key)
        assert wm is not None
        assert wm["worst_price"] == 95.0  # went down to 95
        assert wm["best_price"] == 100.0  # best was entry at 100 (then 95 was worse)

    @pytest.mark.asyncio
    async def test_watermarks_init_at_entry_price(self):
        conn = FakeConnection()
        _set_snapshot(conn)
        worker = _make_worker(conn)

        await worker._process_fill(_make_report(side="buy", price=100.0, ts=1000))
        pos = worker._matcher.open_positions["BTCUSDT"][0]
        wm_key = (pos.asset, pos.timestamp, pos.entry_price)
        wm = worker._position_watermarks[wm_key]
        assert wm["worst_price"] == 100.0
        assert wm["best_price"] == 100.0


# ---------------------------------------------------------------------------
# _snapshot_equity
# ---------------------------------------------------------------------------

class TestSnapshotEquity:
    @pytest.mark.asyncio
    async def test_writes_equity_point(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        await worker._snapshot_equity(1000.0)

        # Should write an equity point (no DB read needed — computed locally)
        execute_calls = [c for c in conn.executed if c[0] == "execute"]
        assert len(execute_calls) == 1
        assert "portfolio_equity_curve" in execute_calls[0][1]

    @pytest.mark.asyncio
    async def test_default_equity_from_balance(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        await worker._snapshot_equity(1000.0)

        execute_calls = [c for c in conn.executed if c[0] == "execute"]
        assert len(execute_calls) == 1
        args = execute_calls[0][2]
        # Default balance is 10000.0, equity should match
        equity = args[1]
        assert equity == pytest.approx(10000.0)

    @pytest.mark.asyncio
    async def test_exposure_computed_from_open_positions(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        # Add a mock open long position: 1 BTC at 50000
        pos = OpenPosition(
            asset="BTCUSDT", side="buy", size=1.0,
            entry_price=50000, timestamp=900,
        )
        worker._matcher.open_positions.setdefault("BTCUSDT", []).append(pos)

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

    @pytest.mark.asyncio
    async def test_uses_mark_to_market_price_for_equity(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        pos = OpenPosition(
            asset="BTCUSDT", side="buy", size=1.0,
            entry_price=100.0, timestamp=900.0,
        )
        worker._matcher.open_positions.setdefault("BTCUSDT", []).append(pos)
        worker._position_marks[("BTCUSDT", 900.0, 100.0)] = 110.0

        await worker._snapshot_equity(1000.0)

        execute_calls = [c for c in conn.executed if c[0] == "execute" and "portfolio_equity_curve" in c[1]]
        args = execute_calls[0][2]
        assert args[1] == pytest.approx(10010.0)
        assert args[3] == pytest.approx(10.0)


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


# ---------------------------------------------------------------------------
# Decode "None" string fields
# ---------------------------------------------------------------------------

class TestDecodeNoneStringFields:
    def test_decode_none_string_fields(self):
        """'None' string in Optional fields should decode to Python None."""
        payload = {
            "order_id": "ord-none",
            "idempotency_key": "idem-none",
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
            "stop_loss_price": "None",
            "take_profit_price": "None",
            "error_message": "",
            "metadata": "{}",
        }
        report = PortfolioWorker._decode_report(payload)
        assert report.stop_loss_price is None
        assert report.take_profit_price is None


# ---------------------------------------------------------------------------
# Non-filled status skipped
# ---------------------------------------------------------------------------

class TestNonFilledStatusSkipped:
    @pytest.mark.asyncio
    async def test_non_filled_status_skipped(self):
        """_process_fill with CANCELLED status should do nothing."""
        conn = FakeConnection()
        worker = _make_worker(conn)

        report = _make_report(side="buy")
        report.status = OrderStatus.CANCELLED
        await worker._process_fill(report)

        # No positions opened
        assert len(worker._matcher.open_positions.get("BTCUSDT", [])) == 0
        # No DB writes
        execute_calls = [c for c in conn.executed if c[0] == "execute"]
        assert len(execute_calls) == 0


class TestReplaySafety:
    @pytest.mark.asyncio
    async def test_duplicate_fill_is_skipped_in_memory(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        report = _make_report(side="buy", price=100.0, size=1.0, ts=1000.0)
        await worker._process_fill(report)
        await worker._process_fill(report)

        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert len(positions) == 1

    @pytest.mark.asyncio
    async def test_close_reason_without_open_position_does_not_open_reverse(self):
        conn = FakeConnection()
        worker = _make_worker(conn)

        report = _make_report(
            side="sell",
            price=101.0,
            size=1.0,
            ts=2000.0,
            metadata={"close_reason": "sl"},
        )
        await worker._process_fill(report)

        assert worker._matcher.open_positions.get("BTCUSDT", []) == []


class TestSharedState:
    @pytest.mark.asyncio
    async def test_workers_share_balance(self):
        conn = FakeConnection()
        shared_state = PortfolioState(balance=10000.0, peak_equity=10000.0)
        btc_worker = _make_shared_worker(conn, "BTCUSDT", shared_state)
        eth_worker = _make_shared_worker(conn, "ETHUSDT", shared_state)

        report = _make_report(side="buy", price=100.0, size=1.0, ts=1000.0, asset="BTCUSDT")
        report.fills[0].commission = 0.5
        await btc_worker._process_fill(report)

        assert shared_state.balance == pytest.approx(9999.5)
        assert eth_worker._balance == pytest.approx(9999.5)


# ---------------------------------------------------------------------------
# Multi-TP partial fills
# ---------------------------------------------------------------------------

class TestPortfolioMultiTP:
    """Verify PortfolioWorker handles multi-TP partial fills correctly."""

    @pytest.mark.asyncio
    async def test_partial_close_creates_closed_trade(self):
        """A partial sell against an open long creates a ClosedTrade with correct size."""
        conn = FakeConnection()
        worker = _make_worker(conn)

        # Open long 1.0 @ 100
        open_fill = _make_report(side="buy", price=100.0, size=1.0, ts=1000.0)
        await worker._process_fill(open_fill)

        # TP1 partial close: sell 0.4 @ 101.5
        tp1_fill = _make_report(
            side="sell", price=101.5, size=0.4, ts=2000.0,
            metadata={"close_reason": "tp1", "model_name": "SB", "timeframe": "1h"},
        )
        await worker._process_fill(tp1_fill)

        # Should have recorded one ClosedTrade with size=0.4
        trade_inserts = [
            c for c in conn.executed
            if c[0] == "execute" and "closed_trades" in c[1]
        ]
        assert len(trade_inserts) == 1

        # Position should remain with size=0.6
        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].size == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_three_partial_closes_produce_three_closed_trades(self):
        """Full multi-TP lifecycle: open → TP1 → TP2 → TP3."""
        conn = FakeConnection()
        worker = _make_worker(conn)

        # Open long 1.0 @ 100
        await worker._process_fill(
            _make_report(side="buy", price=100.0, size=1.0, ts=1000.0),
        )

        # TP1: sell 0.4 @ 101.5
        await worker._process_fill(
            _make_report(side="sell", price=101.5, size=0.4, ts=2000.0,
                         metadata={"close_reason": "tp1"}),
        )
        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert positions[0].size == pytest.approx(0.6)

        # TP2: sell 0.3 @ 103.0
        await worker._process_fill(
            _make_report(side="sell", price=103.0, size=0.3, ts=3000.0,
                         metadata={"close_reason": "tp2"}),
        )
        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert positions[0].size == pytest.approx(0.3)

        # TP3: sell 0.3 @ 105.0
        await worker._process_fill(
            _make_report(side="sell", price=105.0, size=0.3, ts=4000.0,
                         metadata={"close_reason": "tp3"}),
        )
        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert len(positions) == 0

        # 3 ClosedTrade inserts total
        trade_inserts = [
            c for c in conn.executed
            if c[0] == "execute" and "closed_trades" in c[1]
        ]
        assert len(trade_inserts) == 3

    @pytest.mark.asyncio
    async def test_partial_close_pnl_correct(self):
        """PnL for partial closes is computed on the closed portion only."""
        conn = FakeConnection()
        worker = _make_worker(conn)

        # Open long 1.0 @ 100
        await worker._process_fill(
            _make_report(side="buy", price=100.0, size=1.0, ts=1000.0),
        )

        initial_balance = worker._balance

        # Sell 0.4 @ 102 → PnL = (102 - 100) * 0.4 = 0.8
        tp1_fill = _make_report(side="sell", price=102.0, size=0.4, ts=2000.0)
        await worker._process_fill(tp1_fill)

        # Balance should have increased by ~0.8 (minus proportional commission)
        commission = sum(f.commission for f in tp1_fill.fills)
        expected_pnl = 0.8  # (102 - 100) * 0.4
        expected_balance = initial_balance + expected_pnl - commission
        assert worker._balance == pytest.approx(expected_balance, abs=0.01)

    @pytest.mark.asyncio
    async def test_sl_full_close_after_partial_tp(self):
        """SL closes remaining position after one TP partial close."""
        conn = FakeConnection()
        worker = _make_worker(conn)

        # Open long 1.0 @ 100
        await worker._process_fill(
            _make_report(side="buy", price=100.0, size=1.0, ts=1000.0),
        )

        # TP1: sell 0.4 @ 101.5
        await worker._process_fill(
            _make_report(side="sell", price=101.5, size=0.4, ts=2000.0,
                         metadata={"close_reason": "tp1"}),
        )

        # SL: sell remaining 0.6 @ 100.0 (breakeven after trail)
        await worker._process_fill(
            _make_report(side="sell", price=100.0, size=0.6, ts=3000.0,
                         metadata={"close_reason": "sl"}),
        )

        positions = worker._matcher.open_positions.get("BTCUSDT", [])
        assert len(positions) == 0

        # 2 ClosedTrade inserts: TP1 + SL
        trade_inserts = [
            c for c in conn.executed
            if c[0] == "execute" and "closed_trades" in c[1]
        ]
        assert len(trade_inserts) == 2
