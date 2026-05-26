"""ExecutionWorker — per-asset Valkey consumer for order streams."""

from __future__ import annotations

import asyncio
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import ExecutionReport, OrderExecutionRequest, valkey_encode, valkey_decode
from libs.execution.order_manager import OrderManager

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


class ExecutionWorker(BaseStreamConsumer):
    """Per-asset Valkey consumer. Consumes orders:{asset}, publishes fills:{asset}."""

    def __init__(
        self,
        asset: str,
        order_manager: OrderManager,
        exec_config: dict[str, Any],
    ) -> None:
        super().__init__(
            stream_key=f"orders:{asset}",
            group_name="execution_app_group",
            consumer_name=f"execution_worker_{asset}",
            batch_size=10,
            block_ms=1000,
        )
        self.asset = asset
        self.order_manager = order_manager
        self.exec_config = exec_config

        self.order_stream_key = self.stream_key
        self.fill_stream_key = f"fills:{asset}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Main loop — consume orders, execute, publish fills."""
        logger.info(f"Starting execution worker for {self.asset}")
        await self.run()

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Decode order, execute, publish fill report."""
        order = self._decode_order(data)
        report = await self.order_manager.process_order(order)

        if report is not None:
            await self.redis_client.xadd(
                self.fill_stream_key,
                self._encode_report(report),
                maxlen=5000,
                approximate=True,
            )
            logger.info(
                f"Published fill for {self.asset}: "
                f"order_id={report.order_id}, "
                f"status={report.status.value}",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_order(payload: dict) -> OrderExecutionRequest:
        """Decode a Valkey flat-map payload into an OrderExecutionRequest."""
        return valkey_decode(payload, OrderExecutionRequest)

    @staticmethod
    def _encode_report(report: ExecutionReport) -> dict[str, str]:
        """Encode ExecutionReport for Valkey XADD."""
        return valkey_encode(report)
