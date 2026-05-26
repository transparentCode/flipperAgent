"""BinanceExecutor — stub implementation for Binance USD-M Futures."""

from __future__ import annotations

from libs.contracts.schemas import ExecutionReport, OrderExecutionRequest
from libs.execution.executor_base import BaseExecutor


class BinanceExecutor(BaseExecutor):
    """Placeholder for live Binance execution. All methods raise NotImplementedError."""

    async def execute_order(self, order: OrderExecutionRequest) -> ExecutionReport:
        raise NotImplementedError("BinanceExecutor not yet implemented")

    async def cancel_order(self, order_id: str, asset: str) -> bool:
        raise NotImplementedError("BinanceExecutor not yet implemented")

    async def get_positions(self, asset: str | None = None) -> list[dict]:
        raise NotImplementedError("BinanceExecutor not yet implemented")

    async def get_balance(self) -> dict[str, float]:
        raise NotImplementedError("BinanceExecutor not yet implemented")
