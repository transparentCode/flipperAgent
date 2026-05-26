"""PositionTracker — in-memory position state with DB persistence."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import PositionState

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class PositionTracker:
    """Manages open positions per asset with SL/TP checking and trailing stop updates."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.positions: dict[str, list[PositionState]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Position lifecycle
    # ------------------------------------------------------------------

    async def open_position(self, state: PositionState) -> None:
        async with self._lock:
            self.positions[state.asset].append(state)
            logger.info(
                f"Opened position — asset={state.asset}, direction={state.direction}, "
                f"size={state.size:.6f}, entry={state.entry_price:.4f}",
            )

    async def close_position(self, asset: str, index: int) -> float:
        """Close position at *index* for *asset*. Returns realized PnL."""
        async with self._lock:
            pos_list = self.positions.get(asset, [])
            if index < 0 or index >= len(pos_list):
                raise IndexError(f"Invalid position index {index} for {asset}")

            pos = pos_list.pop(index)
            pnl = pos.unrealized_pnl
            logger.info(
                f"Closed position — asset={asset}, direction={pos.direction}, "
                f"pnl={pnl:.4f}, entry={pos.entry_price:.4f}, "
                f"exit={pos.current_price:.4f}",
            )
            return pnl

    # ------------------------------------------------------------------
    # Price updates
    # ------------------------------------------------------------------

    def update_prices(self, asset: str, current_price: float) -> None:
        """Update current price and unrealized PnL for all positions of *asset*."""
        for pos in self.positions.get(asset, []):
            pos.current_price = current_price
            pos.unrealized_pnl = pos.direction * (current_price - pos.entry_price) * pos.size

    def update_trailing_stops(self, asset: str, current_price: float) -> None:
        """Move trailing stop closer to price when price moves favorably."""
        for pos in self.positions.get(asset, []):
            if pos.trailing_stop_distance is None or pos.stop_loss_price is None:
                continue

            if pos.direction == 1:
                # Long: stop trails upward
                new_sl = current_price - pos.trailing_stop_distance
                if new_sl > pos.stop_loss_price:
                    pos.stop_loss_price = new_sl
            elif pos.direction == -1:
                # Short: stop trails downward
                new_sl = current_price + pos.trailing_stop_distance
                if new_sl < pos.stop_loss_price:
                    pos.stop_loss_price = new_sl

    # ------------------------------------------------------------------
    # SL / TP checks
    # ------------------------------------------------------------------

    def check_sl_tp(self, asset: str, current_price: float) -> list[PositionState]:
        """Return positions that have hit their SL or TP at *current_price*."""
        hit: list[PositionState] = []
        for pos in self.positions.get(asset, []):
            if pos.stop_loss_price is not None:
                if pos.direction == 1 and current_price <= pos.stop_loss_price:
                    hit.append(pos)
                    continue
                if pos.direction == -1 and current_price >= pos.stop_loss_price:
                    hit.append(pos)
                    continue

            if pos.take_profit_price is not None:
                if pos.direction == 1 and current_price >= pos.take_profit_price:
                    hit.append(pos)
                    continue
                if pos.direction == -1 and current_price <= pos.take_profit_price:
                    hit.append(pos)
                    continue
        return hit

    # ------------------------------------------------------------------
    # Exposure queries
    # ------------------------------------------------------------------

    def get_total_exposure(self) -> float:
        """Total notional exposure across all assets."""
        total = 0.0
        for pos_list in self.positions.values():
            for pos in pos_list:
                total += abs(pos.size * pos.current_price)
        return total

    def get_position_count(self) -> int:
        return sum(len(v) for v in self.positions.values())

    def get_asset_exposure(self, asset: str) -> float:
        return sum(abs(p.size * p.current_price) for p in self.positions.get(asset, []))

    def all_positions(self) -> list[PositionState]:
        """Flat list of all open positions."""
        result: list[PositionState] = []
        for pos_list in self.positions.values():
            result.extend(pos_list)
        return result

    # ------------------------------------------------------------------
    # DB persistence (TimescaleDB)
    # ------------------------------------------------------------------

    async def save_positions(self, db_pool: Any) -> None:
        """Persist all open positions to TimescaleDB (replace strategy)."""
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM risk_positions")
            for pos in self.all_positions():
                await conn.execute(
                    """
                    INSERT INTO risk_positions
                        (asset, direction, entry_price, current_price, size,
                         unrealized_pnl, entry_timestamp, source_model,
                         source_timeframe, stop_loss_price, take_profit_price,
                         trailing_stop_distance)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    """,
                    pos.asset,
                    pos.direction,
                    pos.entry_price,
                    pos.current_price,
                    pos.size,
                    pos.unrealized_pnl,
                    pos.entry_timestamp,
                    pos.source_model,
                    pos.source_timeframe,
                    pos.stop_loss_price,
                    pos.take_profit_price,
                    pos.trailing_stop_distance,
                )

    @classmethod
    async def load_positions(cls, db_pool: Any) -> PositionTracker:
        """Restore open positions from TimescaleDB."""
        tracker = cls()
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM risk_positions")
        for row in rows:
            pos = PositionState(
                asset=row["asset"],
                direction=row["direction"],
                entry_price=row["entry_price"],
                current_price=row["current_price"],
                size=row["size"],
                unrealized_pnl=row["unrealized_pnl"],
                entry_timestamp=row["entry_timestamp"],
                source_model=row["source_model"],
                source_timeframe=row["source_timeframe"],
                stop_loss_price=row["stop_loss_price"],
                take_profit_price=row["take_profit_price"],
                trailing_stop_distance=row["trailing_stop_distance"],
            )
            tracker.positions[pos.asset].append(pos)
        logger.info(f"Restored {tracker.get_position_count()} open positions from DB")
        return tracker
