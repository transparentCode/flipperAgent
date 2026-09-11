"""PaperExecutor — simulated order execution with configurable slippage."""

from __future__ import annotations

import asyncio
import random
import time
import uuid

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    ExecutionReport,
    OrderExecutionRequest,
    OrderFill,
    OrderStatus,
)
from libs.execution.executor_base import BaseExecutor

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


class PaperExecutor(BaseExecutor):
    """Simulated executor that fills every order with configurable slippage."""

    def __init__(
        self,
        slippage_bps: float = 1.0,
        slippage_jitter_bps: float = 0.5,
        commission_bps: float = 4.0,
        fill_delay_ms: float = 50.0,
        seed: int = 42,
    ) -> None:
        self.slippage_bps = slippage_bps
        self.slippage_jitter_bps = slippage_jitter_bps
        self.commission_bps = commission_bps
        self.fill_delay_ms = fill_delay_ms
        self._rng = random.Random(seed)
        self._state_lock = asyncio.Lock()

        # Paper state
        self._positions: dict[str, dict] = {}
        self._balance: dict[str, float] = {"USDT": 10_000.0}

    @staticmethod
    def _weighted_avg_price(
        current_size: float,
        current_avg_price: float,
        added_size: float,
        added_price: float,
    ) -> float:
        total_size = current_size + added_size
        if total_size <= 0:
            return 0.0
        return (
            (current_size * current_avg_price) + (added_size * added_price)
        ) / total_size

    async def execute_order(self, order: OrderExecutionRequest) -> ExecutionReport:
        # Simulate network/exchange delay
        if self.fill_delay_ms > 0:
            await asyncio.sleep(self.fill_delay_ms / 1000.0)

        order_id = uuid.uuid4().hex[:12]
        fill_id = uuid.uuid4().hex[:12]
        now = time.time()

        # Direction-aware slippage: buy fills ABOVE, sell fills BELOW
        jitter = self._rng.uniform(0, self.slippage_jitter_bps)
        total_slippage_bps = self.slippage_bps + jitter

        if order.side == "buy":
            fill_price = order.requested_price * (1 + total_slippage_bps / 10_000)
        else:
            fill_price = order.requested_price * (1 - total_slippage_bps / 10_000)

        # Signed slippage: positive = worse for buyer
        if order.requested_price != 0:
            slippage_bps = (
                (fill_price - order.requested_price) / order.requested_price * 10_000
            )
        else:
            slippage_bps = 0.0

        commission = order.size * fill_price * (self.commission_bps / 10_000)

        fill = OrderFill(
            fill_id=fill_id,
            asset=order.asset,
            side=order.side,
            size=order.size,
            fill_price=fill_price,
            commission=commission,
            commission_asset="USDT",
            timestamp=now,
            is_maker=False,
        )

        report = ExecutionReport(
            order_id=order_id,
            idempotency_key=order.idempotency_key,
            asset=order.asset,
            side=order.side,
            requested_size=order.size,
            filled_size=order.size,
            requested_price=order.requested_price,
            average_fill_price=fill_price,
            status=OrderStatus.FILLED,
            fills=[fill],
            slippage_bps=slippage_bps,
            stop_loss_price=order.stop_loss_price,
            take_profit_price=order.take_profit_price,
            timestamp=now,
            metadata={
                "model_name": order.model_name,
                "timeframe": order.source_timeframe,
                "close_reason": order.close_reason,
                **order.metadata,
            },
        )

        # Keep shared paper account state consistent while still allowing
        # per-order delay/slippage simulation to happen outside the lock.
        notional = order.size * fill_price
        tolerance = 1e-12
        async with self._state_lock:
            self._balance["USDT"] += (
                -(notional + commission) if order.side == "buy" else (notional - commission)
            )

            pos = self._positions.get(order.asset)
            current_size = float(pos["size"]) if pos else 0.0
            current_avg_price = float(pos["avg_price"]) if pos else 0.0

            if order.side == "buy":
                if current_size >= 0:
                    new_size = current_size + order.size
                    new_avg_price = self._weighted_avg_price(
                        current_size, current_avg_price, order.size, fill_price,
                    )
                else:
                    short_size = abs(current_size)
                    if order.size < short_size - tolerance:
                        new_size = current_size + order.size
                        new_avg_price = current_avg_price
                    elif abs(order.size - short_size) <= tolerance:
                        new_size = 0.0
                        new_avg_price = 0.0
                    else:
                        residual_long = order.size - short_size
                        new_size = residual_long
                        new_avg_price = fill_price
            else:
                if current_size <= 0:
                    short_size = abs(current_size)
                    new_short_size = short_size + order.size
                    new_size = -new_short_size
                    new_avg_price = self._weighted_avg_price(
                        short_size, current_avg_price, order.size, fill_price,
                    )
                else:
                    if order.size < current_size - tolerance:
                        new_size = current_size - order.size
                        new_avg_price = current_avg_price
                    elif abs(order.size - current_size) <= tolerance:
                        new_size = 0.0
                        new_avg_price = 0.0
                    else:
                        residual_short = order.size - current_size
                        new_size = -residual_short
                        new_avg_price = fill_price

            if abs(new_size) <= tolerance:
                self._positions.pop(order.asset, None)
            else:
                self._positions[order.asset] = {
                    "asset": order.asset,
                    "size": new_size,
                    "avg_price": new_avg_price,
                }

        logger.info(
            f"Paper fill: {order.asset} {order.side} {order.size:.6f} "
            f"@ {fill_price:.4f} (slip={slippage_bps:.2f}bps)",
        )
        return report

    async def cancel_order(self, order_id: str, asset: str) -> bool:
        logger.info(f"Paper cancel (no-op): order_id={order_id} asset={asset}")
        return True

    async def get_positions(self, asset: str | None = None) -> list[dict]:
        if asset:
            pos = self._positions.get(asset)
            return [pos] if pos else []
        return list(self._positions.values())

    async def get_balance(self) -> dict[str, float]:
        return dict(self._balance)
