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


def _before_bar_entry(position: PositionState, bar_close_seconds: float | None) -> bool:
    """Return whether a completed bar ended before this position existed."""

    return (
        bar_close_seconds is not None and position.entry_timestamp >= bar_close_seconds
    )


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

    def find_position_index(self, asset: str, entry_timestamp: float) -> int:
        """Find a position by entry timestamp, returning -1 when absent."""
        for idx, pos in enumerate(self.positions.get(asset, [])):
            if abs(pos.entry_timestamp - entry_timestamp) <= 1e-9:
                return idx
        return -1

    def mark_pending_close(
        self,
        asset: str,
        entry_timestamp: float,
        close_reason: str,
        requested_at: float,
    ) -> bool:
        """Mark a position as awaiting close execution."""
        idx = self.find_position_index(asset, entry_timestamp)
        if idx < 0:
            return False
        pos = self.positions[asset][idx]
        pos.pending_close_reason = close_reason
        pos.pending_close_requested_at = requested_at
        return True

    def clear_pending_close(self, asset: str, entry_timestamp: float) -> bool:
        """Clear pending-close markers when execution confirms or rejects an exit."""
        idx = self.find_position_index(asset, entry_timestamp)
        if idx < 0:
            return False
        pos = self.positions[asset][idx]
        pos.pending_close_reason = ""
        pos.pending_close_requested_at = 0.0
        return True

    # ------------------------------------------------------------------
    # Price updates
    # ------------------------------------------------------------------

    def update_prices(
        self,
        asset: str,
        current_price: float,
        *,
        bar_close_seconds: float | None = None,
    ) -> None:
        """Update current price and unrealized PnL for all positions of *asset*."""
        for pos in self.positions.get(asset, []):
            if _before_bar_entry(pos, bar_close_seconds):
                continue
            pos.current_price = current_price
            pos.unrealized_pnl = (
                pos.direction * (current_price - pos.entry_price) * pos.size
            )

    def update_trailing_stops(
        self,
        asset: str,
        current_price: float,
        *,
        bar_close_seconds: float | None = None,
    ) -> None:
        """Move trailing stop closer to price when price moves favorably."""
        for pos in self.positions.get(asset, []):
            if _before_bar_entry(pos, bar_close_seconds):
                continue
            if pos.trailing_stop_distance is None or pos.stop_loss_price is None:
                continue

            if pos.direction == 1:
                # Long: stop trails upward
                new_sl = current_price - pos.trailing_stop_distance
                pos.stop_loss_price = max(pos.stop_loss_price, new_sl)
            elif pos.direction == -1:
                # Short: stop trails downward
                new_sl = current_price + pos.trailing_stop_distance
                pos.stop_loss_price = min(pos.stop_loss_price, new_sl)

    # ------------------------------------------------------------------
    # SL / TP checks
    # ------------------------------------------------------------------

    def check_sl_tp(
        self,
        asset: str,
        current_price: float,
        *,
        bar_close_seconds: float | None = None,
    ) -> list[PositionState]:
        """Return positions that have hit their SL or TP at *current_price*.

        Skips multi-TP positions — those are handled by check_sl_tp_hlc_multi.
        """
        hit: list[PositionState] = []
        for pos in self.positions.get(asset, []):
            if _before_bar_entry(pos, bar_close_seconds):
                continue
            if pos.pending_close_reason:
                continue
            if pos.tp_levels:
                continue
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

    def check_sl_tp_hlc(
        self,
        asset: str,
        high: float,
        low: float,
        close: float,
        *,
        bar_close_seconds: float | None = None,
    ) -> list[PositionState]:
        """Return positions whose SL or TP was hit using intrabar high/low extremes.

        Uses *low* for long SL and short TP, *high* for long TP and short SL.
        When both SL and TP are hit on the same bar, TP takes priority.
        Skips multi-TP positions — those are handled by check_sl_tp_hlc_multi.
        """
        hit: list[PositionState] = []
        for pos in self.positions.get(asset, []):
            if _before_bar_entry(pos, bar_close_seconds):
                continue
            if pos.pending_close_reason:
                continue
            if pos.tp_levels:
                continue
            tp_hit = False
            sl_hit = False

            if pos.take_profit_price is not None and (
                (pos.direction == 1 and high >= pos.take_profit_price)
                or (pos.direction == -1 and low <= pos.take_profit_price)
            ):
                tp_hit = True

            if pos.stop_loss_price is not None and (
                (pos.direction == 1 and low <= pos.stop_loss_price)
                or (pos.direction == -1 and high >= pos.stop_loss_price)
            ):
                sl_hit = True

            if tp_hit or sl_hit:
                hit.append(pos)
        return hit

    def check_sl_tp_hlc_multi(
        self,
        asset: str,
        high: float,
        low: float,
        close: float,
        *,
        bar_close_seconds: float | None = None,
    ) -> list[tuple[PositionState, str, float]]:
        """Check multi-TP positions for partial exits using intrabar H/L.

        Returns list of (position, close_reason, close_size) tuples.
        Only one TP level fires per position per call (lowest unhit first).
        TP takes priority over SL when both hit on the same bar.
        Positions with empty tp_levels are skipped (handled by check_sl_tp_hlc).
        """
        results: list[tuple[PositionState, str, float]] = []
        for pos in self.positions.get(asset, []):
            if _before_bar_entry(pos, bar_close_seconds):
                continue
            if pos.pending_close_reason:
                continue
            if not pos.tp_levels:
                continue

            # Check each TP level (only the first unhit one fires)
            tp_fired = False
            for i, (tp_price, hit_already) in enumerate(
                zip(pos.tp_levels, pos.tp_levels_hit),
            ):
                if hit_already:
                    continue

                tp_hit = False
                if (pos.direction == 1 and high >= tp_price) or (
                    pos.direction == -1 and low <= tp_price
                ):
                    tp_hit = True

                if tp_hit:
                    close_size = pos.tp_portions[i] * pos.original_size
                    close_reason = f"tp{i + 1}"
                    results.append((pos, close_reason, close_size))
                    tp_fired = True
                    break  # one TP per bar

            # SL check only if no TP fired this bar
            if not tp_fired and pos.stop_loss_price is not None:
                sl_hit = False
                if (pos.direction == 1 and low <= pos.stop_loss_price) or (
                    pos.direction == -1 and high >= pos.stop_loss_price
                ):
                    sl_hit = True

                if sl_hit:
                    # SL closes the entire remaining position
                    results.append((pos, "sl", pos.size))

        return results

    def apply_partial_exit(
        self,
        asset: str,
        pos_index: int,
        close_size: float,
        tp_level_index: int,
    ) -> None:
        """Reduce position size after a partial TP hit.

        - Decrements pos.size by close_size
        - Marks tp_levels_hit[tp_level_index] = True
        - If tp_level_index == 0 and trail_to_breakeven:
            pos.stop_loss_price = pos.entry_price
        - Removes position entirely if size reaches ~0
        """
        pos_list = self.positions.get(asset, [])
        if pos_index < 0 or pos_index >= len(pos_list):
            raise IndexError(f"Invalid position index {pos_index} for {asset}")

        pos = pos_list[pos_index]
        pos.size = max(0.0, pos.size - close_size)
        pos.tp_levels_hit[tp_level_index] = True

        # Trail-to-breakeven after TP1
        if tp_level_index == 0 and pos.trail_to_breakeven:
            if pos.original_stop_loss is None:
                pos.original_stop_loss = pos.stop_loss_price
            pos.stop_loss_price = pos.entry_price
            logger.info(
                f"Trail-to-breakeven activated — asset={asset}, "
                f"SL moved to entry={pos.entry_price:.4f}",
            )

        logger.info(
            f"Partial exit — asset={asset}, tp{tp_level_index + 1} hit, "
            f"closed={close_size:.6f}, remaining={pos.size:.6f}",
        )

        # Remove position if fully closed
        if pos.size < 1e-12:
            pos_list.pop(pos_index)
            logger.info(f"Position fully closed via partial exits — asset={asset}")

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
                         trailing_stop_distance,
                         original_size, tp_levels, tp_portions, tp_levels_hit,
                         original_stop_loss, trail_to_breakeven)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                            $13,$14,$15,$16,$17,$18)
                    """,
                    pos.asset,
                    str(pos.direction),
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
                    pos.original_size,
                    json.dumps(pos.tp_levels),
                    json.dumps(pos.tp_portions),
                    json.dumps(pos.tp_levels_hit),
                    pos.original_stop_loss,
                    pos.trail_to_breakeven,
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
                original_size=row.get("original_size", 0.0) or 0.0,
                tp_levels=json.loads(row.get("tp_levels", "[]") or "[]"),
                tp_portions=json.loads(row.get("tp_portions", "[]") or "[]"),
                tp_levels_hit=json.loads(row.get("tp_levels_hit", "[]") or "[]"),
                original_stop_loss=row.get("original_stop_loss"),
                trail_to_breakeven=row.get("trail_to_breakeven", False) or False,
            )
            tracker.positions[pos.asset].append(pos)
        logger.info(f"Restored {tracker.get_position_count()} open positions from DB")
        return tracker
