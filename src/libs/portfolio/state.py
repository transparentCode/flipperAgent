"""Shared portfolio state across per-asset portfolio workers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.position_matcher import OpenPosition, PositionMatcher
from libs.contracts.schemas import EquityPoint
from libs.risk.position_tracker import PositionTracker

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


@dataclass
class PortfolioState:
    """Global mutable portfolio state shared by all portfolio workers."""

    balance: float
    peak_equity: float
    matcher: PositionMatcher = field(default_factory=PositionMatcher)
    position_watermarks: dict[tuple[str, float, float], dict[str, float]] = field(
        default_factory=dict,
    )
    position_marks: dict[tuple[str, float, float], float] = field(default_factory=dict)
    processed_fill_ids: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    async def load(cls, db_pool: Any, initial_balance: float) -> PortfolioState:
        """Restore portfolio balance, open positions, and processed fill IDs."""
        state = cls(balance=initial_balance, peak_equity=initial_balance)

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_processed_fills (
                    order_id TEXT PRIMARY KEY,
                    ts DOUBLE PRECISION NOT NULL
                )
                """,
            )

            latest_row = await conn.fetchrow(
                """
                SELECT balance, equity
                FROM portfolio_equity_curve
                ORDER BY timestamp DESC
                LIMIT 1
                """,
            )
            if latest_row:
                state.balance = float(latest_row["balance"])

            peak_row = await conn.fetchrow(
                "SELECT MAX(equity) AS peak_equity FROM portfolio_equity_curve",
            )
            if peak_row and peak_row["peak_equity"] is not None:
                state.peak_equity = max(
                    initial_balance,
                    float(peak_row["peak_equity"]),
                )

            processed_rows = await conn.fetch(
                "SELECT order_id FROM portfolio_processed_fills",
            )
            state.processed_fill_ids = {
                str(row["order_id"]) for row in processed_rows
            }

        tracker = await PositionTracker.load_positions(db_pool)
        for position in tracker.all_positions():
            side = "buy" if position.direction == 1 else "sell"
            metadata = {
                "model_name": position.source_model,
                "timeframe": position.source_timeframe,
            }
            state.matcher.open_positions.setdefault(position.asset, []).append(
                OpenPosition(
                    asset=position.asset,
                    side=side,
                    size=position.size,
                    entry_price=position.entry_price,
                    timestamp=position.entry_timestamp,
                    metadata=metadata,
                ),
            )
            key = cls.make_position_key(
                position.asset,
                position.entry_timestamp,
                position.entry_price,
            )
            state.position_marks[key] = position.current_price
            state.position_watermarks[key] = {
                "worst_price": position.current_price,
                "best_price": position.current_price,
            }

        logger.info(
            "Restored portfolio state: balance=%.4f peak=%.4f open_positions=%d processed_fills=%d",
            state.balance,
            state.peak_equity,
            sum(len(v) for v in state.matcher.open_positions.values()),
            len(state.processed_fill_ids),
        )
        return state

    @staticmethod
    def make_position_key(asset: str, entry_timestamp: float, entry_price: float) -> tuple[str, float, float]:
        return (asset, entry_timestamp, entry_price)

    async def sync_marks_from_risk_positions(self, db_pool: Any) -> None:
        """Refresh current prices from risk_positions without changing portfolio balance."""
        tracker = await PositionTracker.load_positions(db_pool)
        async with self.lock:
            for position in tracker.all_positions():
                key = self.make_position_key(
                    position.asset,
                    position.entry_timestamp,
                    position.entry_price,
                )
                self.position_marks[key] = position.current_price
                if key not in self.position_watermarks:
                    self.position_watermarks[key] = {
                        "worst_price": position.current_price,
                        "best_price": position.current_price,
                    }
                else:
                    marks = self.position_watermarks[key]
                    if position.direction == 1:
                        marks["worst_price"] = min(marks["worst_price"], position.current_price)
                        marks["best_price"] = max(marks["best_price"], position.current_price)
                    else:
                        marks["worst_price"] = max(marks["worst_price"], position.current_price)
                        marks["best_price"] = min(marks["best_price"], position.current_price)

    def build_equity_snapshot(
        self,
        timestamp: float | None = None,
    ) -> tuple[EquityPoint, float, float]:
        """Build a portfolio-wide mark-to-market equity snapshot."""
        ts = timestamp if timestamp is not None else time.time()
        long_notional = 0.0
        short_notional = 0.0
        unrealized_pnl = 0.0
        open_count = 0

        for asset_positions in self.matcher.open_positions.values():
            for position in asset_positions:
                open_count += 1
                key = self.make_position_key(
                    position.asset,
                    position.timestamp,
                    position.entry_price,
                )
                current_price = self.position_marks.get(key, position.entry_price)
                notional = current_price * position.size
                direction = 1 if position.side == "buy" else -1
                unrealized_pnl += direction * (current_price - position.entry_price) * position.size
                if position.side == "buy":
                    long_notional += notional
                else:
                    short_notional += notional

        equity = self.balance + unrealized_pnl
        if equity > self.peak_equity:
            self.peak_equity = equity
        drawdown_pct = (
            (self.peak_equity - equity) / self.peak_equity * 100
            if self.peak_equity > 0
            else 0.0
        )
        net_exposure_pct = ((long_notional - short_notional) / equity * 100) if equity > 0 else 0.0
        gross_exposure_pct = ((long_notional + short_notional) / equity * 100) if equity > 0 else 0.0

        point = EquityPoint(
            timestamp=ts,
            equity=equity,
            balance=self.balance,
            unrealized_pnl=unrealized_pnl,
            drawdown_pct=drawdown_pct,
            open_position_count=open_count,
        )
        return point, net_exposure_pct, gross_exposure_pct
