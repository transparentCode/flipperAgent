"""Tests for FillListener."""

from __future__ import annotations

import json

import pytest

from apps.risk_app.fill_listener import FillListener
from libs.contracts.schemas import ExecutionReport, OrderStatus, PositionState
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker


def _make_report(
    side: str = "buy",
    price: float = 50_000.0,
    size: float = 0.1,
    status: OrderStatus = OrderStatus.FILLED,
    asset: str = "BTCUSDT",
) -> ExecutionReport:
    return ExecutionReport(
        order_id="order-1",
        idempotency_key="key-1",
        asset=asset,
        side=side,
        requested_size=size,
        filled_size=size,
        requested_price=price,
        average_fill_price=price,
        status=status,
        fills=[],
        timestamp=1_700_000_000.0,
    )


def _make_listener() -> FillListener:
    return FillListener(
        asset="BTCUSDT",
        account=AccountState(10_000.0),
        positions=PositionTracker(),
    )


# ------------------------------------------------------------------
# _decode_execution_report
# ------------------------------------------------------------------


class TestDecodeExecutionReport:
    def test_string_payload(self) -> None:
        payload = {
            "order_id": "o1",
            "idempotency_key": "k1",
            "asset": "BTCUSDT",
            "side": "buy",
            "requested_size": "0.1",
            "filled_size": "0.1",
            "requested_price": "50000.0",
            "average_fill_price": "50000.0",
            "status": "FILLED",
            "fills": "[]",
            "timestamp": "1700000000.0",
        }
        report = FillListener._decode_execution_report(payload)
        assert isinstance(report, ExecutionReport)
        assert report.asset == "BTCUSDT"
        assert report.status == OrderStatus.FILLED

    def test_bytes_payload(self) -> None:
        payload = {
            b"order_id": b"o2",
            b"idempotency_key": b"k2",
            b"asset": b"ETHUSDT",
            b"side": b"sell",
            b"requested_size": b"1.0",
            b"filled_size": b"1.0",
            b"requested_price": b"2000.0",
            b"average_fill_price": b"2000.0",
            b"status": b"FILLED",
            b"fills": b"[]",
            b"timestamp": b"1700000001.0",
        }
        report = FillListener._decode_execution_report(payload)
        assert isinstance(report, ExecutionReport)
        assert report.asset == "ETHUSDT"
        assert report.side == "sell"


# ------------------------------------------------------------------
# _apply_fill
# ------------------------------------------------------------------


class TestApplyFill:
    @pytest.mark.asyncio
    async def test_buy_opens_long(self) -> None:
        fl = _make_listener()
        report = _make_report(side="buy", price=50_000.0, size=0.1)
        await fl._apply_fill(report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].direction == 1
        assert positions[0].entry_price == 50_000.0

    @pytest.mark.asyncio
    async def test_sell_closes_fifo_long(self) -> None:
        fl = _make_listener()
        # Open a long
        await fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.1))
        # Sell closes it
        await fl._apply_fill(_make_report(side="sell", price=51_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 0
        # PnL = direction(1) * (51000 - 50000) * 0.1 = 100
        assert fl.account.realized_pnl == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_sell_no_long_opens_short(self) -> None:
        fl = _make_listener()
        await fl._apply_fill(_make_report(side="sell", price=50_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].direction == -1
        assert positions[0].entry_price == 50_000.0

    @pytest.mark.asyncio
    async def test_buy_closes_fifo_short(self) -> None:
        """G5: buy-side must close existing short positions (bidirectional FIFO)."""
        fl = _make_listener()
        # Open a short via sell with no existing long
        await fl._apply_fill(_make_report(side="sell", price=50_000.0, size=0.1))
        assert len(fl.positions.positions.get("BTCUSDT", [])) == 1

        # Buy should close the short, not open a new long
        await fl._apply_fill(_make_report(side="buy", price=49_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 0
        # PnL = direction(-1) * (49000 - 50000) * 0.1 = (-1)*(-1000)*0.1 = 100
        assert fl.account.realized_pnl == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_buy_no_short_opens_long(self) -> None:
        fl = _make_listener()
        await fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].direction == 1

    @pytest.mark.asyncio
    async def test_non_filled_status_skipped(self) -> None:
        fl = _make_listener()
        report = _make_report(status=OrderStatus.CANCELLED)
        await fl._apply_fill(report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 0


# ------------------------------------------------------------------
# Partial fill + FIFO matching
# ------------------------------------------------------------------


class TestPartialFillFIFO:
    @pytest.mark.asyncio
    async def test_partial_fill_reduces_position(self) -> None:
        """A fill smaller than position size reduces the position instead of closing."""
        fl = _make_listener()
        # Open long of 0.5 BTC
        await fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.5))
        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].size == pytest.approx(0.5)

        # Partial sell of 0.2 BTC — should reduce position to 0.3
        await fl._apply_fill(_make_report(side="sell", price=51_000.0, size=0.2))
        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].size == pytest.approx(0.3)
        # PnL = 1 * (51000 - 50000) * 0.2 = 200
        assert fl.account.realized_pnl == pytest.approx(200.0)

    @pytest.mark.asyncio
    async def test_fifo_order_respected(self) -> None:
        """When two positions exist, a close fill matches the first one (FIFO)."""
        fl = _make_listener()
        # Open two longs at different prices
        await fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.1))
        await fl._apply_fill(_make_report(side="buy", price=52_000.0, size=0.1))
        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 2

        # Sell 0.1 — should close the FIRST position (entry 50000)
        await fl._apply_fill(_make_report(side="sell", price=51_000.0, size=0.1))
        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        # Remaining position should be the second one (entry 52000)
        assert positions[0].entry_price == pytest.approx(52_000.0)
        # PnL from first: 1 * (51000 - 50000) * 0.1 = 100
        assert fl.account.realized_pnl == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_remaining_fill_opens_new_position(self) -> None:
        """Fill larger than opposite position closes it and opens new with excess."""
        fl = _make_listener()
        # Open long of 0.1
        await fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.1))

        # Sell 0.3 — closes 0.1 long, opens 0.2 short with remaining
        await fl._apply_fill(_make_report(side="sell", price=51_000.0, size=0.3))
        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].direction == -1  # short
        assert positions[0].size == pytest.approx(0.2)
