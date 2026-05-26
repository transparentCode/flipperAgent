"""ExecutionWorker — per-asset Valkey consumer for order streams."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ExecutionReport, OrderExecutionRequest
from libs.execution.order_manager import OrderManager

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


class ExecutionWorker:
    """Per-asset Valkey consumer. Consumes orders:{asset}, publishes fills:{asset}."""

    def __init__(
        self,
        asset: str,
        order_manager: OrderManager,
        exec_config: dict[str, Any],
    ) -> None:
        self.asset = asset
        self.order_manager = order_manager
        self.exec_config = exec_config

        self.order_stream_key = f"orders:{asset}"
        self.fill_stream_key = f"fills:{asset}"
        self.group_name = "execution_app_group"
        self.consumer_name = f"execution_worker_{asset}"
        self.redis_client: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, redis_client: Any) -> None:
        """Store client and create consumer group."""
        self.redis_client = redis_client
        try:
            await self.redis_client.xgroup_create(
                self.order_stream_key, self.group_name, id="0", mkstream=True,
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(
                    f"Failed to create group {self.group_name} "
                    f"on {self.order_stream_key}: {e}",
                )

    async def start(self) -> None:
        """Main loop — consume orders, execute, publish fills."""
        logger.info(f"Starting execution worker for {self.asset}")

        if not self.redis_client:
            logger.warning("No redis client. Running in mock mode.")
            return

        streams = {self.order_stream_key: ">"}

        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    streams,
                    count=10,
                    block=1000,
                )
                if not response:
                    continue

                for stream_name, messages in response:
                    for message_id, payload in messages:
                        try:
                            order = self._decode_order(payload)
                            report = await self.order_manager.process_order(order)

                            if report is not None:
                                await self.redis_client.xadd(
                                    self.fill_stream_key,
                                    self._encode_report(report),
                                )
                                logger.info(
                                    f"Published fill for {self.asset}: "
                                    f"order_id={report.order_id}, "
                                    f"status={report.status.value}",
                                )
                        except Exception as e:
                            logger.error(f"Failed to process order: {e}", exc_info=True)

                        sname = (
                            stream_name.decode("utf-8")
                            if isinstance(stream_name, bytes)
                            else stream_name
                        )
                        await self.redis_client.xack(
                            sname, self.group_name, message_id,
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in execution worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_order(payload: dict) -> OrderExecutionRequest:
        """Decode bytes keys/values from Valkey and reconstruct OrderExecutionRequest."""
        decoded: dict[str, Any] = {}
        for k, v in payload.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else k
            val = v.decode("utf-8") if isinstance(v, bytes) else v
            decoded[key] = val

        # Parse optional float fields
        stop_loss = decoded.get("stop_loss_price")
        take_profit = decoded.get("take_profit_price")

        return OrderExecutionRequest(
            asset=decoded["asset"],
            side=decoded["side"],
            size=float(decoded["size"]),
            order_type=decoded.get("order_type", "market"),
            timestamp=float(decoded["timestamp"]),
            requested_price=float(decoded["requested_price"]),
            idempotency_key=decoded["idempotency_key"],
            stop_loss_price=float(stop_loss) if stop_loss and stop_loss != "None" else None,
            take_profit_price=float(take_profit) if take_profit and take_profit != "None" else None,
            model_name=decoded.get("model_name", ""),
            source_timeframe=decoded.get("source_timeframe", ""),
        )

    @staticmethod
    def _encode_report(report: ExecutionReport) -> dict[str, str]:
        """Encode ExecutionReport for Valkey xadd (all values must be strings)."""
        data = report.model_dump()
        result: dict[str, str] = {}
        for k, v in data.items():
            if isinstance(v, (list, dict)):
                result[k] = json.dumps(v, default=str)
            elif v is None:
                result[k] = "None"
            else:
                result[k] = str(v)
        return result
