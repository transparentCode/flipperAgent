"""FillListener — consumes fills:{asset} and updates Risk Manager state."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    ExecutionReport,
    OrderFill,
    OrderStatus,
    PositionState,
)
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class FillListener:
    """Consumes fills:{asset} and updates Risk Manager's PositionTracker + AccountState."""

    def __init__(
        self,
        asset: str,
        account: AccountState,
        positions: PositionTracker,
    ) -> None:
        self.asset = asset
        self.account = account
        self.positions = positions

        self.fill_stream_key = f"fills:{asset}"
        self.group_name = "risk_app_fills_group"
        self.consumer_name = f"fill_listener_{asset}"
        self.redis_client: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, redis_client: Any) -> None:
        """Store client and create consumer group."""
        self.redis_client = redis_client
        try:
            await self.redis_client.xgroup_create(
                self.fill_stream_key, self.group_name, id="0", mkstream=True,
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(
                    f"Failed to create group {self.group_name} "
                    f"on {self.fill_stream_key}: {e}",
                )

    async def start(self) -> None:
        """Main loop — consume fills, update positions and account state."""
        logger.info(f"Starting fill listener for {self.asset}")

        if not self.redis_client:
            logger.warning("No redis client. Running in mock mode.")
            return

        streams = {self.fill_stream_key: ">"}

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
                            report = self._decode_execution_report(payload)
                            self._apply_fill(report)
                        except Exception as e:
                            logger.error(
                                f"Failed to process fill: {e}", exc_info=True,
                            )

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
                logger.error(f"Error in fill listener loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Fill application
    # ------------------------------------------------------------------

    def _apply_fill(self, report: ExecutionReport) -> None:
        """Update PositionTracker and AccountState based on the fill report."""
        if report.status != OrderStatus.FILLED:
            logger.debug(
                f"Skipping non-FILLED report: status={report.status.value}",
            )
            return

        if report.side == "buy":
            # FIFO: try to close first open short (direction=-1)
            pos_list = self.positions.positions.get(report.asset, [])
            matched_idx: int | None = None
            for i, pos in enumerate(pos_list):
                if pos.direction == -1:
                    matched_idx = i
                    break

            if matched_idx is not None:
                pos = pos_list[matched_idx]
                pos.current_price = report.average_fill_price
                pos.unrealized_pnl = (
                    pos.direction
                    * (pos.current_price - pos.entry_price)
                    * pos.size
                )
                pnl = self.positions.close_position(report.asset, matched_idx)
                self.account.record_trade_close(pnl, report.timestamp)
                logger.info(
                    f"Closed short position for {report.asset}: pnl={pnl:.4f}",
                )
            else:
                # No matching short — open a long position
                pos = PositionState(
                    asset=report.asset,
                    direction=1,
                    entry_price=report.average_fill_price,
                    current_price=report.average_fill_price,
                    size=report.filled_size,
                    unrealized_pnl=0.0,
                    entry_timestamp=report.timestamp,
                    source_model="",
                    source_timeframe="",
                    stop_loss_price=report.stop_loss_price,
                    take_profit_price=report.take_profit_price,
                )
                self.positions.open_position(pos)
                logger.info(
                    f"Opened long position for {report.asset}: "
                    f"size={report.filled_size:.6f} @ {report.average_fill_price:.4f}",
                )

        elif report.side == "sell":
            # FIFO: find first open position with direction=1 (closing a long)
            pos_list = self.positions.positions.get(report.asset, [])
            matched_idx: int | None = None
            for i, pos in enumerate(pos_list):
                if pos.direction == 1:
                    matched_idx = i
                    break

            if matched_idx is not None:
                pos = pos_list[matched_idx]
                pos.current_price = report.average_fill_price
                pos.unrealized_pnl = (
                    pos.direction
                    * (pos.current_price - pos.entry_price)
                    * pos.size
                )
                pnl = self.positions.close_position(report.asset, matched_idx)
                self.account.record_trade_close(pnl, report.timestamp)
                logger.info(
                    f"Closed long position for {report.asset}: pnl={pnl:.4f}",
                )
            else:
                # No matching long — open a short position
                pos = PositionState(
                    asset=report.asset,
                    direction=-1,
                    entry_price=report.average_fill_price,
                    current_price=report.average_fill_price,
                    size=report.filled_size,
                    unrealized_pnl=0.0,
                    entry_timestamp=report.timestamp,
                    source_model="",
                    source_timeframe="",
                    stop_loss_price=report.stop_loss_price,
                    take_profit_price=report.take_profit_price,
                )
                self.positions.open_position(pos)
                logger.info(
                    f"Opened short position for {report.asset}: "
                    f"size={report.filled_size:.6f} @ {report.average_fill_price:.4f}",
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_execution_report(payload: dict) -> ExecutionReport:
        """Decode bytes keys/values from Valkey and reconstruct ExecutionReport."""
        decoded: dict[str, Any] = {}
        for k, v in payload.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else k
            val = v.decode("utf-8") if isinstance(v, bytes) else v
            decoded[key] = val

        # Parse JSON-encoded list/dict fields
        fills_raw = decoded.get("fills", "[]")
        if isinstance(fills_raw, str):
            fills_raw = json.loads(fills_raw)

        metadata_raw = decoded.get("metadata", "{}")
        if isinstance(metadata_raw, str):
            metadata_raw = json.loads(metadata_raw)

        # Parse optional float fields
        stop_loss = decoded.get("stop_loss_price")
        take_profit = decoded.get("take_profit_price")

        return ExecutionReport(
            order_id=decoded["order_id"],
            idempotency_key=decoded["idempotency_key"],
            asset=decoded["asset"],
            side=decoded["side"],
            requested_size=float(decoded["requested_size"]),
            filled_size=float(decoded["filled_size"]),
            requested_price=float(decoded["requested_price"]),
            average_fill_price=float(decoded["average_fill_price"]),
            status=OrderStatus(decoded["status"]),
            fills=[OrderFill(**f) for f in fills_raw],
            slippage_bps=float(decoded.get("slippage_bps", 0.0)),
            stop_loss_price=float(stop_loss) if stop_loss and stop_loss != "None" else None,
            take_profit_price=float(take_profit) if take_profit and take_profit != "None" else None,
            timestamp=float(decoded["timestamp"]),
            error_message=decoded.get("error_message", ""),
            metadata=metadata_raw,
        )
