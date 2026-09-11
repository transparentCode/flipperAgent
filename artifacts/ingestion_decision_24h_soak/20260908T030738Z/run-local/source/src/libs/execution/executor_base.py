"""BaseExecutor — abstract interface for order execution adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.schemas import ExecutionReport, OrderExecutionRequest


class BaseExecutor(ABC):
    @abstractmethod
    async def execute_order(self, order: OrderExecutionRequest) -> ExecutionReport: ...

    @abstractmethod
    async def cancel_order(self, order_id: str, asset: str) -> bool: ...

    @abstractmethod
    async def get_positions(self, asset: str | None = None) -> list[dict]: ...

    @abstractmethod
    async def get_balance(self) -> dict[str, float]: ...
