"""FillListener — consumes fills:{asset} and updates Risk Manager state."""

from __future__ import annotations

import asyncio
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import (
    ExecutionReport,
    OrderFill,
    OrderStatus,
    PositionState,
    valkey_decode,
)
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class FillListener(BaseStreamConsumer):
    """Consumes fills:{asset} and updates Risk Manager's PositionTracker + AccountState.

    NOTE: Both portfolio_app and risk_app consume the fills stream independently.
    Each uses its own consumer group to get an independent copy of all fill messages.
    Changes to fill processing here must be coordinated with portfolio_app.PortfolioWorker.
    """

    def __init__(
        self,
        asset: str,
        account: AccountState,
        positions: PositionTracker,
    ) -> None:
        super().__init__(
            stream_key=f"fills:{asset}",
            group_name="risk_app_fills_group",
            consumer_name=f"fill_listener_{asset}",
            batch_size=10,
            block_ms=1000,
        )
        self.asset = asset
        self.account = account
        self.positions = positions
        self.fill_stream_key = self.stream_key

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Main loop — consume fills, update positions and account state."""
        logger.info(f"Starting fill listener for {self.asset}")
        await self.run()

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Decode fill and apply to position/account state."""
        report = self._decode_execution_report(data)
        await self._apply_fill(report)

    # ------------------------------------------------------------------
    # Fill application
    # ------------------------------------------------------------------

    async def _apply_fill(self, report: ExecutionReport) -> None:
        """Update PositionTracker and AccountState based on the fill report.

        Handles partial fills: a single fill can close multiple positions
        in FIFO order and open a new position with any remaining quantity.
        """
        if report.status != OrderStatus.FILLED:
            logger.debug(
                f"Skipping non-FILLED report: status={report.status.value}",
            )
            return

        opposite_dir = -1 if report.side == "buy" else 1
        remaining = report.filled_size
        pos_list = self.positions.positions.get(report.asset, [])
        metadata = report.metadata or {}

        # FIFO match against opposite-side positions
        indices_to_remove: list[int] = []
        i = 0
        while i < len(pos_list) and remaining > 1e-12:
            pos = pos_list[i]
            if pos.direction != opposite_dir:
                i += 1
                continue

            match_qty = min(remaining, pos.size)
            pnl = pos.direction * (report.average_fill_price - pos.entry_price) * match_qty

            await self.account.record_trade_close(pnl, report.timestamp)
            logger.info(
                f"Closed {'short' if opposite_dir == -1 else 'long'} position "
                f"for {report.asset}: pnl={pnl:.4f}",
            )

            remaining -= match_qty

            if match_qty >= pos.size - 1e-12:
                # Fully closed — mark for removal
                indices_to_remove.append(i)
                i += 1
            else:
                # Partially closed — reduce position size
                pos.size -= match_qty
                pos.current_price = report.average_fill_price
                pos.unrealized_pnl = (
                    pos.direction
                    * (pos.current_price - pos.entry_price)
                    * pos.size
                )
                i += 1

        # Remove fully closed positions (reverse order to preserve indices)
        for idx in reversed(indices_to_remove):
            pos = pos_list[idx]
            pos.current_price = report.average_fill_price
            pos.unrealized_pnl = 0.0
            await self.positions.close_position(report.asset, idx)

        # Open new position for remaining unmatched fill quantity
        if remaining > 1e-12:
            new_dir = 1 if report.side == "buy" else -1
            pos = PositionState(
                asset=report.asset,
                direction=new_dir,
                entry_price=report.average_fill_price,
                current_price=report.average_fill_price,
                size=remaining,
                unrealized_pnl=0.0,
                entry_timestamp=report.timestamp,
                source_model=metadata.get("model_name", ""),
                source_timeframe=metadata.get("timeframe", ""),
                stop_loss_price=report.stop_loss_price,
                take_profit_price=report.take_profit_price,
            )
            await self.positions.open_position(pos)
            logger.info(
                f"Opened {'long' if new_dir == 1 else 'short'} position for {report.asset}: "
                f"size={remaining:.6f} @ {report.average_fill_price:.4f}",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_execution_report(payload: dict) -> ExecutionReport:
        """Decode a Valkey flat-map payload into an ExecutionReport."""
        return valkey_decode(payload, ExecutionReport)
