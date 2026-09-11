"""ExecutionWorker — per-asset Valkey consumer for order streams."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from apps.execution_app.observability.runtime_state import ExecutionRuntimeStateStore
from apps.execution_app.observability.status import failure_stream_key
from apps.execution_app.state import ExecutionAsset, ExecutionAssetState, ExecutionFailureEvent
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.serialization import valkey_encode as serialize_valkey
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
        runtime_state_store: ExecutionRuntimeStateStore | None = None,
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
        self.runtime_state_store = runtime_state_store
        self.execution_asset = ExecutionAsset(asset=asset)
        self.execution_mode = str(exec_config.get("mode", "paper"))
        runtime_config = exec_config.get("runtime", {})

        self.order_stream_key = self.stream_key
        self.fill_stream_key = f"fills:{asset}"
        self.failure_stream_key = failure_stream_key(asset)
        self.fill_stream_maxlen = int(runtime_config.get("fill_stream_maxlen", 1000))
        self.fill_stream_approximate = bool(runtime_config.get("fill_stream_approximate", True))
        self.failure_stream_maxlen = int(runtime_config.get("failure_stream_maxlen", 1000))
        self.failure_stream_approximate = bool(
            runtime_config.get("failure_stream_approximate", True)
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Main loop — consume orders, execute, publish fills."""
        await self._update_runtime_status(
            state=ExecutionAssetState.WARMING,
            replace_last_error=False,
            detail={"phase": "starting", "mode": self.execution_mode},
        )
        logger.info(f"Starting execution worker for {self.asset}")
        try:
            await self.run()
        except asyncio.CancelledError:
            await self._update_runtime_status(
                state=ExecutionAssetState.STOPPED,
                detail={"phase": "cancelled", "mode": self.execution_mode},
            )
            raise
        await self._update_runtime_status(
            state=ExecutionAssetState.STOPPED,
            detail={"phase": "stopped", "mode": self.execution_mode},
        )

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Decode order, execute, publish fill report."""
        order = self._decode_order(data)
        await self._update_runtime_status(
            last_order_ts=order.timestamp,
            mode=self.execution_mode,
            detail={
                "last_order_stream": self.order_stream_key,
                "last_message_id": message_id,
                "last_idempotency_key": order.idempotency_key,
            },
        )
        try:
            report = await self.order_manager.process_order(order)
        except Exception as exc:
            await self._publish_failure_event(message_id, order, exc)
            await self._update_runtime_status(
                state=ExecutionAssetState.FAILED,
                last_failure_ts=time.time(),
                last_error=str(exc),
                replace_last_error=True,
                increment_failures=1,
                detail={"phase": "process_message", "last_failure_stream": self.failure_stream_key},
            )
            raise

        if report is not None:
            await self.redis_client.xadd(
                self.fill_stream_key,
                self._encode_report(report),
                maxlen=self.fill_stream_maxlen,
                approximate=self.fill_stream_approximate,
            )
            logger.info(
                f"Published fill for {self.asset}: "
                f"order_id={report.order_id}, "
                f"status={report.status.value}",
            )
            await self._update_runtime_status(
                state=ExecutionAssetState.LIVE,
                last_fill_ts=report.timestamp,
                last_error=None,
                replace_last_error=True,
                increment_processed=1,
                detail={
                    "last_fill_stream": self.fill_stream_key,
                    "last_order_id": report.order_id,
                    "last_fill_status": report.status.value,
                },
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

    async def _publish_failure_event(
        self,
        message_id: str,
        order: OrderExecutionRequest,
        exc: Exception,
    ) -> None:
        if self.redis_client is None:
            return
        event = ExecutionFailureEvent(
            asset=self.asset,
            stream=self.order_stream_key,
            consumer_group=self.group_name,
            consumer_name=self.consumer_name,
            message_id=message_id,
            idempotency_key=order.idempotency_key,
            timestamp=time.time(),
            error_type=type(exc).__name__,
            error_message=str(exc),
            order_side=order.side,
            order_size=order.size,
            requested_price=order.requested_price,
            order_type=order.order_type,
        )
        await self.redis_client.xadd(
            self.failure_stream_key,
            serialize_valkey(event, inject_trace=False),
            maxlen=self.failure_stream_maxlen,
            approximate=self.failure_stream_approximate,
        )

    async def _update_runtime_status(
        self,
        *,
        state: ExecutionAssetState | None = None,
        mode: str | None = None,
        last_order_ts: float | None = None,
        last_fill_ts: float | None = None,
        last_failure_ts: float | None = None,
        last_error: str | None = None,
        replace_last_error: bool = False,
        increment_processed: int = 0,
        increment_failures: int = 0,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if self.runtime_state_store is None:
            return
        await self.runtime_state_store.update(
            self.execution_asset,
            state=state,
            mode=mode,
            last_order_ts=last_order_ts,
            last_fill_ts=last_fill_ts,
            last_failure_ts=last_failure_ts,
            last_error=last_error,
            replace_last_error=replace_last_error,
            increment_processed=increment_processed,
            increment_failures=increment_failures,
            detail=detail,
        )
