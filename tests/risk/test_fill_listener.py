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

    @pytest.mark.asyncio
    async def test_targeted_close_matches_requested_position_not_fifo(self) -> None:
        fl = _make_listener()
        await fl._apply_fill(_make_report(side="buy", price=50_000.0, size=0.1))
        await fl._apply_fill(_make_report(side="buy", price=52_000.0, size=0.1))

        positions = fl.positions.positions["BTCUSDT"]
        first_ts = positions[0].entry_timestamp
        second_ts = positions[1].entry_timestamp

        targeted_close = ExecutionReport(
            order_id="targeted-close",
            idempotency_key="targeted-close",
            asset="BTCUSDT",
            side="sell",
            requested_size=0.1,
            filled_size=0.1,
            requested_price=53_000.0,
            average_fill_price=53_000.0,
            status=OrderStatus.FILLED,
            fills=[],
            timestamp=1_700_000_010.0,
            metadata={
                "close_reason": "tp",
                "position_entry_timestamp": second_ts,
            },
        )

        await fl._apply_fill(targeted_close)

        remaining = fl.positions.positions["BTCUSDT"]
        assert len(remaining) == 1
        assert remaining[0].entry_timestamp == pytest.approx(first_ts)


# ------------------------------------------------------------------
# Multi-TP fill tests
# ------------------------------------------------------------------


def _make_multi_tp_report(
    side: str = "buy",
    price: float = 50_000.0,
    size: float = 1.0,
    tp_levels: list | None = None,
    tp_portions: list | None = None,
    trail_to_breakeven: bool = False,
    close_reason: str = "",
) -> ExecutionReport:
    metadata = {
        "model_name": "test_model",
        "timeframe": "1h",
    }
    if tp_levels:
        metadata["tp_levels"] = tp_levels
        metadata["tp_portions"] = tp_portions or []
        metadata["trail_to_breakeven"] = trail_to_breakeven
    if close_reason:
        metadata["close_reason"] = close_reason

    return ExecutionReport(
        order_id="order-mt",
        idempotency_key="key-mt",
        asset="BTCUSDT",
        side=side,
        requested_size=size,
        filled_size=size,
        requested_price=price,
        average_fill_price=price,
        status=OrderStatus.FILLED,
        fills=[],
        stop_loss_price=49_000.0 if not close_reason else None,
        take_profit_price=None,
        timestamp=1_700_000_000.0,
        metadata=metadata,
    )


class TestFillListenerMultiTP:
    @pytest.mark.asyncio
    async def test_new_position_with_multi_tp(self) -> None:
        """Fill with multi-TP metadata opens position with tp fields."""
        fl = _make_listener()
        report = _make_multi_tp_report(
            tp_levels=[50_750.0, 51_500.0, 52_500.0],
            tp_portions=[0.4, 0.3, 0.3],
            trail_to_breakeven=True,
        )
        await fl._apply_fill(report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        pos = positions[0]
        assert pos.tp_levels == [50_750.0, 51_500.0, 52_500.0]
        assert pos.tp_portions == [0.4, 0.3, 0.3]
        assert pos.tp_levels_hit == [False, False, False]
        assert pos.trail_to_breakeven is True
        assert pos.original_size == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_close_fill_reduces_position(self) -> None:
        """Partial close fill from TP hit reduces existing position size."""
        fl = _make_listener()
        # Open a long with multi-TP
        open_report = _make_multi_tp_report(
            side="buy", price=100.0, size=1.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            trail_to_breakeven=True,
        )
        await fl._apply_fill(open_report)

        # Partial close: TP1 hit → sell 0.4
        close_report = _make_multi_tp_report(
            side="sell", price=101.5, size=0.4,
            close_reason="tp1",
        )
        close_report.metadata["position_entry_timestamp"] = open_report.timestamp
        await fl._apply_fill(close_report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        pos = positions[0]
        assert pos.size == pytest.approx(0.6)
        # Multi-TP fields preserved
        assert len(pos.tp_levels) == 3
        assert pos.tp_levels_hit == [True, False, False]
        assert pos.stop_loss_price == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_partial_close_no_reverse_position(self) -> None:
        """Partial close fill with close_reason should NOT open reverse position."""
        fl = _make_listener()

        # Partial close without any open position (edge case)
        close_report = _make_multi_tp_report(
            side="sell", price=101.5, size=0.4,
            close_reason="tp1",
        )
        await fl._apply_fill(close_report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        # Should NOT have opened a short position from unmatched qty
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_rejected_close_clears_pending_marker(self) -> None:
        fl = _make_listener()
        report = _make_multi_tp_report(
            tp_levels=[50_750.0, 51_500.0, 52_500.0],
            tp_portions=[0.4, 0.3, 0.3],
            trail_to_breakeven=True,
        )
        await fl._apply_fill(report)
        pos = fl.positions.positions["BTCUSDT"][0]
        pos.pending_close_reason = "tp1"

        rejected = ExecutionReport(
            order_id="rej-1",
            idempotency_key="rej-1",
            asset="BTCUSDT",
            side="sell",
            requested_size=0.4,
            filled_size=0.0,
            requested_price=101.5,
            average_fill_price=0.0,
            status=OrderStatus.REJECTED,
            fills=[],
            timestamp=1_700_000_010.0,
            error_message="Exchange down",
            metadata={
                "close_reason": "tp1",
                "position_entry_timestamp": pos.entry_timestamp,
            },
        )

        await fl._apply_fill(rejected)

        assert pos.pending_close_reason == ""

    @pytest.mark.asyncio
    async def test_no_multi_tp_backward_compat(self) -> None:
        """Fill without multi-TP metadata opens position with empty tp fields."""
        fl = _make_listener()
        report = _make_report(side="buy", price=50_000.0, size=0.1)
        await fl._apply_fill(report)

        positions = fl.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        pos = positions[0]
        assert pos.tp_levels == []
        assert pos.tp_portions == []
        assert pos.original_size == pytest.approx(0.1)
