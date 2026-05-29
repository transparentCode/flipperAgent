"""OrderManager — order lifecycle: dedup, validate, execute, track."""

from __future__ import annotations

import asyncio
import time
import uuid

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    ExecutionReport,
    OrderExecutionRequest,
    OrderStatus,
)
from libs.execution.executor_base import BaseExecutor
from libs.execution.fill_tracker import FillTracker
from libs.execution.idempotency import IdempotencyStore

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


class OrderManager:
    def __init__(
        self,
        executor: BaseExecutor,
        idempotency_store: IdempotencyStore,
        fill_tracker: FillTracker,
    ) -> None:
        self.executor = executor
        self.idempotency_store = idempotency_store
        self.fill_tracker = fill_tracker
        self._lock = asyncio.Lock()

    async def process_order(
        self, order: OrderExecutionRequest
    ) -> ExecutionReport | None:
        async with self._lock:
            # 1. Idempotency check
            if self.idempotency_store.is_duplicate(order.idempotency_key):
                logger.info(f"Duplicate order skipped: {order.idempotency_key}")
                return None

            # 2. Validate
            error = self._validate(order)
            if error:
                report = self._rejection_report(order, error)
                self.fill_tracker.record_fill(report)
                self.idempotency_store.mark_processed(
                    order.idempotency_key, report.timestamp
                )
                return report

            # 3. Execute
            try:
                report = await self.executor.execute_order(order)
            except Exception as exc:
                logger.error(f"Executor error for {order.idempotency_key}: {exc}")
                report = self._rejection_report(order, str(exc))
                self.fill_tracker.record_fill(report)
                self.idempotency_store.mark_processed(
                    order.idempotency_key, report.timestamp
                )
                return report

            # 4. Record fill
            self.fill_tracker.record_fill(report)

            # 5. Mark idempotency key
            self.idempotency_store.mark_processed(
                order.idempotency_key, report.timestamp
            )

            # 6. Return
            return report

    # ------------------------------------------------------------------

    @staticmethod
    def _validate(order: OrderExecutionRequest) -> str:
        if order.size <= 0:
            return f"Invalid order size: {order.size}"
        if order.side not in {"buy", "sell"}:
            return f"Invalid order side: {order.side}"
        if order.requested_price <= 0:
            return f"Invalid order price: {order.requested_price}"
        return ""

    @staticmethod
    def _rejection_report(order: OrderExecutionRequest, error: str) -> ExecutionReport:
        return ExecutionReport(
            order_id=uuid.uuid4().hex[:12],
            idempotency_key=order.idempotency_key,
            asset=order.asset,
            side=order.side,
            requested_size=order.size,
            filled_size=0.0,
            requested_price=order.requested_price,
            average_fill_price=0.0,
            status=OrderStatus.REJECTED,
            slippage_bps=0.0,
            stop_loss_price=order.stop_loss_price,
            take_profit_price=order.take_profit_price,
            timestamp=time.time(),
            error_message=error,
            metadata={
                "model_name": order.model_name,
                "timeframe": order.source_timeframe,
            },
        )
