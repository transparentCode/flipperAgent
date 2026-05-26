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
    def test_buy_opens_long(self) -> None:
        fl = _make_listener()
        report = _make_report(side="buy", price=50_000.0, size=0.1)
        fl._apply_fill(report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].direction == 1
        assert positions[0].entry_price == 50_000.0

    def test_sell_closes_fifo_long(self) -> None:
        fl = _make_listener()
        # Open a long
        fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.1))
        # Sell closes it
        fl._apply_fill(_make_report(side="sell", price=51_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 0
        # PnL = direction(1) * (51000 - 50000) * 0.1 = 100
        assert fl.account.realized_pnl == pytest.approx(100.0)

    def test_sell_no_long_opens_short(self) -> None:
        fl = _make_listener()
        fl._apply_fill(_make_report(side="sell", price=50_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].direction == -1
        assert positions[0].entry_price == 50_000.0

    def test_buy_closes_fifo_short(self) -> None:
        """G5: buy-side must close existing short positions (bidirectional FIFO)."""
        fl = _make_listener()
        # Open a short via sell with no existing long
        fl._apply_fill(_make_report(side="sell", price=50_000.0, size=0.1))
        assert len(fl.positions.positions.get("BTCUSDT", [])) == 1

        # Buy should close the short, not open a new long
        fl._apply_fill(_make_report(side="buy", price=49_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 0
        # PnL = direction(-1) * (49000 - 50000) * 0.1 = (-1)*(-1000)*0.1 = 100
        assert fl.account.realized_pnl == pytest.approx(100.0)

    def test_buy_no_short_opens_long(self) -> None:
        fl = _make_listener()
        fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.1))

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].direction == 1

    def test_non_filled_status_skipped(self) -> None:
        fl = _make_listener()
        report = _make_report(status=OrderStatus.CANCELLED)
        fl._apply_fill(report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 0
