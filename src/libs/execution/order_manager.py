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
        db_pool=None,
    ) -> None:
        self.executor = executor
        self.idempotency_store = idempotency_store
        self.fill_tracker = fill_tracker
        self.db_pool = db_pool
        self._claim_lock = asyncio.Lock()
        self._inflight_keys: set[str] = set()

    async def process_order(
        self, order: OrderExecutionRequest
    ) -> ExecutionReport | None:
        claimed = False
        try:
            # 1. Idempotency / in-flight check
            async with self._claim_lock:
                if order.idempotency_key in self._inflight_keys:
                    logger.info(f"Duplicate in-flight order skipped: {order.idempotency_key}")
                    return None
                self._inflight_keys.add(order.idempotency_key)
                claimed = True

            if await self.idempotency_store.check_duplicate(
                order.idempotency_key, self.db_pool,
            ):
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
                await self._persist_report(report)
                return report

            # 3. Execute
            try:
                report = await self.executor.execute_order(order)
            except Exception as exc:
                logger.error(f"Executor error for {order.idempotency_key}: {exc}")
                raise

            # 4. Record fill
            self.fill_tracker.record_fill(report)

            # 5. Mark idempotency key
            self.idempotency_store.mark_processed(
                order.idempotency_key, report.timestamp
            )
            await self._persist_report(report)

            # 6. Return
            return report
        finally:
            if claimed:
                async with self._claim_lock:
                    self._inflight_keys.discard(order.idempotency_key)

    # ------------------------------------------------------------------

    async def _persist_report(self, report: ExecutionReport) -> None:
        """Best-effort durable persistence for fills and dedup keys."""
        if self.db_pool is None:
            return
        await self.fill_tracker.save_report(self.db_pool, report)
        await self.idempotency_store.upsert_key(
            self.db_pool, report.idempotency_key, report.timestamp,
        )

    @staticmethod
    def _validate(order: OrderExecutionRequest) -> str:
        if order.size <= 0:
            return f"Invalid order size: {order.size}"
        if order.side not in {"buy", "sell"}:
            return f"Invalid order side: {order.side}"
        if order.order_type != "market":
            return f"Unsupported order type: {order.order_type}"
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
                "close_reason": order.close_reason,
                **order.metadata,
            },
        )
