"""FillTracker — slippage tracking and fill history."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ExecutionReport, OrderStatus

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


class FillTracker:
    def __init__(self) -> None:
        self._fills: list[ExecutionReport] = []
        self._slippage_by_asset: defaultdict[str, list[float]] = defaultdict(list)

    def record_fill(self, report: ExecutionReport) -> None:
        self._fills.append(report)
        if report.status == OrderStatus.FILLED:
            self._slippage_by_asset[report.asset].append(report.slippage_bps)

    def get_average_slippage_bps(self, asset: str | None = None) -> float:
        if asset:
            values = self._slippage_by_asset.get(asset, [])
        else:
            values = [s for vals in self._slippage_by_asset.values() for s in vals]
        if not values:
            return 0.0
        return sum(values) / len(values)

    def get_fill_history(
        self, asset: str | None = None, limit: int = 100
    ) -> list[ExecutionReport]:
        if asset:
            filtered = [f for f in self._fills if f.asset == asset]
        else:
            filtered = list(self._fills)
        return filtered[-limit:]

    async def save_report(self, db_pool: Any, report: ExecutionReport) -> None:
        if db_pool is None:
            logger.debug("No db_pool — skipping fill persistence")
            return
        async with db_pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS execution_fills "
                "(order_id TEXT PRIMARY KEY, data JSONB NOT NULL, ts DOUBLE PRECISION NOT NULL)"
            )
            await conn.execute(
                "INSERT INTO execution_fills (order_id, data, ts) "
                "VALUES ($1, $2, $3) ON CONFLICT (order_id) DO NOTHING",
                report.order_id,
                json.dumps(report.model_dump(), default=str),
                report.timestamp,
            )
