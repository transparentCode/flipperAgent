"""Tests for PaperExecutor — slippage, commission, fill correctness."""

from __future__ import annotations

import asyncio

import pytest

from libs.contracts.schemas import OrderExecutionRequest, OrderStatus
from libs.execution.paper_executor import PaperExecutor


def _make_order(**overrides) -> OrderExecutionRequest:
    defaults = {
        "asset": "BTCUSDT",
        "side": "buy",
        "size": 0.1,
        "order_type": "market",
        "timestamp": 1700000000.0,
        "requested_price": 50000.0,
        "idempotency_key": "test-key-1",
    }
    defaults.update(overrides)
    return OrderExecutionRequest(**defaults)


@pytest.fixture
def executor() -> PaperExecutor:
    return PaperExecutor(
        slippage_bps=5.0,
        slippage_jitter_bps=0.0,  # deterministic for testing
        commission_bps=4.0,
        fill_delay_ms=0,  # no delay in tests
    )


class TestPaperExecutorSlippage:
    @pytest.mark.asyncio
    async def test_buy_fills_above_requested_price(self, executor: PaperExecutor):
        order = _make_order(side="buy", requested_price=50000.0)
        report = await executor.execute_order(order)

        assert report.status == OrderStatus.FILLED
        assert report.average_fill_price > order.requested_price

    @pytest.mark.asyncio
    async def test_sell_fills_below_requested_price(self, executor: PaperExecutor):
        order = _make_order(side="sell", requested_price=50000.0)
        report = await executor.execute_order(order)

        assert report.status == OrderStatus.FILLED
        assert report.average_fill_price < order.requested_price

    @pytest.mark.asyncio
    async def test_slippage_bps_matches_expected(self, executor: PaperExecutor):
        order = _make_order(side="buy", requested_price=10000.0)
        report = await executor.execute_order(order)

        # With jitter=0, slippage should be exactly 5.0 bps
        expected_price = 10000.0 * (1 + 5.0 / 10_000)
        assert abs(report.average_fill_price - expected_price) < 0.01
        assert abs(report.slippage_bps - 5.0) < 0.1


class TestPaperExecutorCommission:
    @pytest.mark.asyncio
    async def test_commission_calculated(self, executor: PaperExecutor):
        order = _make_order(size=1.0, requested_price=10000.0)
        report = await executor.execute_order(order)

        assert len(report.fills) == 1
        fill = report.fills[0]
        expected_commission = 1.0 * fill.fill_price * (4.0 / 10_000)
        assert abs(fill.commission - expected_commission) < 0.01

    @pytest.mark.asyncio
    async def test_fill_fields_correct(self, executor: PaperExecutor):
        order = _make_order(asset="ETHUSDT", side="sell", size=2.5)
        report = await executor.execute_order(order)

        assert report.asset == "ETHUSDT"
        assert report.side == "sell"
        assert report.requested_size == 2.5
        assert report.filled_size == 2.5
        assert report.idempotency_key == "test-key-1"

        fill = report.fills[0]
        assert fill.asset == "ETHUSDT"
        assert fill.side == "sell"
        assert fill.size == 2.5
        assert fill.commission_asset == "USDT"


class TestPaperExecutorEdgeCases:
    @pytest.mark.asyncio
    async def test_zero_price_handling(self):
        executor = PaperExecutor(
            slippage_bps=5.0,
            slippage_jitter_bps=0.0,
            commission_bps=4.0,
            fill_delay_ms=0,
        )
        order = _make_order(requested_price=0.0)
        report = await executor.execute_order(order)

        assert report.status == OrderStatus.FILLED
        assert report.average_fill_price == 0.0
        assert report.fills[0].commission == 0.0

    @pytest.mark.asyncio
    async def test_stop_loss_take_profit_forwarded(self, executor: PaperExecutor):
        order = _make_order(stop_loss_price=48000.0, take_profit_price=55000.0)
        report = await executor.execute_order(order)

        assert report.stop_loss_price == 48000.0
        assert report.take_profit_price == 55000.0

    @pytest.mark.asyncio
    async def test_cancel_always_succeeds(self, executor: PaperExecutor):
        result = await executor.cancel_order("some-order-id", "BTCUSDT")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor: PaperExecutor):
        positions = await executor.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_balance(self, executor: PaperExecutor):
        balance = await executor.get_balance()
        assert "USDT" in balance
