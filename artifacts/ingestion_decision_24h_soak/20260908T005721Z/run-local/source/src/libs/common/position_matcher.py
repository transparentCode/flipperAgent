"""Shared FIFO position matching for fills against open positions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OpenPosition:
    """Tracks an open position entry."""

    asset: str
    side: str  # "buy" or "sell"
    size: float
    entry_price: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClosedTrade:
    """Result of matching a fill against an open position."""

    asset: str
    side: str  # side of the ORIGINAL position that was closed
    size: float
    entry_price: float
    exit_price: float
    entry_time: float
    exit_time: float
    pnl: float
    metadata: dict[str, Any] = field(default_factory=dict)


class PositionMatcher:
    """FIFO position matcher that correctly handles partial fills."""

    def __init__(self) -> None:
        self.open_positions: dict[str, list[OpenPosition]] = {}

    def apply_fill(
        self,
        asset: str,
        side: str,
        size: float,
        price: float,
        timestamp: float,
        metadata: dict[str, Any] | None = None,
    ) -> list[ClosedTrade]:
        """Apply a fill and return any closed trades.

        If the fill is on the opposite side of existing positions,
        positions are closed in FIFO order (handling partial fills).
        If same side or no opposing positions, a new position is opened.
        """
        if asset not in self.open_positions:
            self.open_positions[asset] = []

        positions = self.open_positions[asset]
        opposite_side = "sell" if side == "buy" else "buy"
        remaining = size
        closed_trades: list[ClosedTrade] = []

        i = 0
        while i < len(positions) and remaining > 1e-12:
            pos = positions[i]
            if pos.side != opposite_side:
                i += 1
                continue

            match_qty = min(remaining, pos.size)

            # PnL: long -> (exit - entry) * qty; short -> (entry - exit) * qty
            if pos.side == "buy":
                pnl = (price - pos.entry_price) * match_qty
            else:
                pnl = (pos.entry_price - price) * match_qty

            closed_trades.append(
                ClosedTrade(
                    asset=asset,
                    side=pos.side,
                    size=match_qty,
                    entry_price=pos.entry_price,
                    exit_price=price,
                    entry_time=pos.timestamp,
                    exit_time=timestamp,
                    pnl=pnl,
                    metadata=dict(pos.metadata),
                )
            )

            remaining -= match_qty

            if match_qty >= pos.size - 1e-12:
                # Fully closed
                positions.pop(i)
            else:
                # Partially closed — reduce position size
                pos.size -= match_qty
                i += 1

        # Open new position for remaining unmatched fill quantity
        if remaining > 1e-12:
            positions.append(
                OpenPosition(
                    asset=asset,
                    side=side,
                    size=remaining,
                    entry_price=price,
                    timestamp=timestamp,
                    metadata=metadata or {},
                )
            )

        return closed_trades
