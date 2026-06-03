"""Tests for OrderManager — dedup, validation, execution, error handling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from libs.contracts.schemas import (
    ExecutionReport,
    OrderExecutionRequest,
    OrderFill,
    OrderStatus,
)
from libs.execution.fill_tracker import FillTracker
from libs.execution.idempotency import IdempotencyStore
from libs.execution.order_manager import OrderManager


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


def _make_report(order: OrderExecutionRequest) -> ExecutionReport:
    return ExecutionReport(
        order_id="test-order-123",
        idempotency_key=order.idempotency_key,
        asset=order.asset,
        side=order.side,
        requested_size=order.size,
        filled_size=order.size,
        requested_price=order.requested_price,
        average_fill_price=order.requested_price * 1.0005,
        status=OrderStatus.FILLED,
        fills=[],
        slippage_bps=5.0,
        stop_loss_price=order.stop_loss_price,
        take_profit_price=order.take_profit_price,
        timestamp=order.timestamp,
    )


@pytest.fixture
def manager():
    executor = AsyncMock()
    idempotency_store = IdempotencyStore(max_size=100)
    fill_tracker = FillTracker()
    return OrderManager(
        executor=executor,
        idempotency_store=idempotency_store,
        fill_tracker=fill_tracker,
    )


class TestOrderManagerDedup:
    @pytest.mark.asyncio
    async def test_duplicate_returns_none(self, manager: OrderManager):
        order = _make_order()
        report = _make_report(order)
        manager.executor.execute_order.return_value = report

        # First call should succeed
        result1 = await manager.process_order(order)
        assert result1 is not None
        assert result1.status == OrderStatus.FILLED

        # Second call with same key should be deduplicated
        result2 = await manager.process_order(order)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_different_keys_not_deduplicated(self, manager: OrderManager):
        order1 = _make_order(idempotency_key="key-1")
        order2 = _make_order(idempotency_key="key-2")
        report1 = _make_report(order1)
        report2 = _make_report(order2)
        manager.executor.execute_order.side_effect = [report1, report2]

        result1 = await manager.process_order(order1)
        result2 = await manager.process_order(order2)
        assert result1 is not None
        assert result2 is not None


class TestOrderManagerValidation:
    @pytest.mark.asyncio
    async def test_zero_size_rejected(self, manager: OrderManager):
        order = _make_order(size=0.0)
        result = await manager.process_order(order)

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "Invalid order size" in result.error_message

    @pytest.mark.asyncio
    async def test_negative_size_rejected(self, manager: OrderManager):
        order = _make_order(size=-1.0)
        result = await manager.process_order(order)

        assert result is not None
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_bad_side_rejected(self, manager: OrderManager):
        order = _make_order(side="hold")
        result = await manager.process_order(order)

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "Invalid order side" in result.error_message

    @pytest.mark.asyncio
    async def test_unsupported_order_type_rejected(self, manager: OrderManager):
        order = _make_order(order_type="limit")
        result = await manager.process_order(order)

        assert result is not None
        assert result.status == OrderStatus.REJECTED
        assert "Unsupported order type" in result.error_message


class TestOrderManagerExecution:
    @pytest.mark.asyncio
    async def test_successful_execution(self, manager: OrderManager):
        order = _make_order()
        report = _make_report(order)
        manager.executor.execute_order.return_value = report

        result = await manager.process_order(order)

        assert result is not None
        assert result.status == OrderStatus.FILLED
        assert result.order_id == "test-order-123"
        manager.executor.execute_order.assert_awaited_once_with(order)

    @pytest.mark.asyncio
    async def test_executor_exception_bubbles_for_retry(self, manager: OrderManager):
        order = _make_order()
        manager.executor.execute_order.side_effect = RuntimeError("Exchange down")

        with pytest.raises(RuntimeError, match="Exchange down"):
            await manager.process_order(order)

        assert manager.fill_tracker.get_fill_history() == []
        assert manager.idempotency_store.is_duplicate(order.idempotency_key) is False

    @pytest.mark.asyncio
    async def test_fill_tracker_records_result(self, manager: OrderManager):
        order = _make_order()
        report = _make_report(order)
        manager.executor.execute_order.return_value = report

        await manager.process_order(order)

        history = manager.fill_tracker.get_fill_history()
        assert len(history) == 1
        assert history[0].order_id == "test-order-123"

    @pytest.mark.asyncio
    async def test_persists_fill_and_idempotency_immediately(self):
        class _Conn:
            def __init__(self) -> None:
                self.execute = AsyncMock()
                self.fetchrow = AsyncMock(return_value=None)

        class _Acquire:
            def __init__(self, conn):
                self.conn = conn

            async def __aenter__(self):
                return self.conn

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Pool:
            def __init__(self, conn) -> None:
                self.conn = conn

            def acquire(self):
                return _Acquire(self.conn)

        executor = AsyncMock()
        idempotency_store = IdempotencyStore(max_size=100)
        fill_tracker = FillTracker()
        conn = _Conn()
        order = _make_order()
        report = _make_report(order)
        executor.execute_order.return_value = report

        manager = OrderManager(
            executor=executor,
            idempotency_store=idempotency_store,
            fill_tracker=fill_tracker,
            db_pool=_Pool(conn),
        )

        await manager.process_order(order)

        executed_queries = " ".join(call.args[0] for call in conn.execute.await_args_list)
        assert "execution_fills" in executed_queries
        assert "execution_idempotency_keys" in executed_queries

    @pytest.mark.asyncio
    async def test_duplicate_inflight_order_returns_none(self, manager: OrderManager):
        order = _make_order()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_execute(_order):
            started.set()
            await release.wait()
            return _make_report(_order)

        manager.executor.execute_order.side_effect = _slow_execute

        first_task = asyncio.create_task(manager.process_order(order))
        await started.wait()
        second_result = await manager.process_order(order)
        release.set()
        first_result = await first_task

        assert first_result is not None
        assert second_result is None

    @pytest.mark.asyncio
    async def test_duplicate_found_in_db_returns_none(self):
        class _Conn:
            def __init__(self) -> None:
                self.fetchrow = AsyncMock(return_value={"ts": 1700000000.0})
                self.execute = AsyncMock()

        class _Acquire:
            def __init__(self, conn):
                self.conn = conn

            async def __aenter__(self):
                return self.conn

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class _Pool:
            def __init__(self, conn) -> None:
                self.conn = conn

            def acquire(self):
                return _Acquire(self.conn)

        executor = AsyncMock()
        idempotency_store = IdempotencyStore(max_size=100)
        fill_tracker = FillTracker()
        conn = _Conn()
        manager = OrderManager(
            executor=executor,
            idempotency_store=idempotency_store,
            fill_tracker=fill_tracker,
            db_pool=_Pool(conn),
        )
        order = _make_order(idempotency_key="persisted-key")

        result = await manager.process_order(order)

        assert result is None
        executor.execute_order.assert_not_called()
        assert idempotency_store.is_duplicate("persisted-key") is True

    @pytest.mark.asyncio
    async def test_different_orders_can_execute_concurrently(self, manager: OrderManager):
        active = 0
        max_active = 0
        gate = asyncio.Event()

        async def _blocking_execute(order):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            if max_active >= 2:
                gate.set()
            await gate.wait()
            active -= 1
            return _make_report(order)

        manager.executor.execute_order.side_effect = _blocking_execute
        order1 = _make_order(idempotency_key="key-1", asset="BTCUSDT")
        order2 = _make_order(idempotency_key="key-2", asset="ETHUSDT")

        results = await asyncio.wait_for(
            asyncio.gather(
                manager.process_order(order1),
                manager.process_order(order2),
            ),
            timeout=1.0,
        )

        assert all(result is not None for result in results)
        assert max_active == 2
