"""AccountState — balance, equity, PnL, drawdown tracking with DB persistence."""

from __future__ import annotations

import time
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import AccountSnapshot, PositionState

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)

_SECONDS_PER_DAY = 86_400


class AccountState:
    """In-memory account state for paper-trading risk management."""

    def __init__(self, initial_balance: float) -> None:
        self.initial_balance = initial_balance
        self.realized_pnl: float = 0.0
        self.unrealized_pnl: float = 0.0
        self.peak_equity: float = initial_balance
        self.daily_pnl: float = 0.0
        self.daily_reset_timestamp: float = 0.0
        self.last_trade_pnl: float = 0.0
        self.last_trade_timestamp: float = 0.0

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def equity(self) -> float:
        return self.initial_balance + self.realized_pnl + self.unrealized_pnl

    @property
    def balance(self) -> float:
        return self.initial_balance + self.realized_pnl

    @property
    def current_drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100)

    # ------------------------------------------------------------------
    # State mutations
    # ------------------------------------------------------------------

    def record_trade_close(self, pnl: float, timestamp: float) -> None:
        """Record PnL from a closed position."""
        self.realized_pnl += pnl
        self.daily_pnl += pnl
        self.last_trade_pnl = pnl
        self.last_trade_timestamp = timestamp

        # Update peak equity after realized PnL change
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

        logger.debug(
            f"Trade closed — pnl={pnl:.4f}, realized_total={self.realized_pnl:.4f}, "
            f"equity={self.equity:.4f}",
        )

    def update_unrealized(self, positions: list[PositionState]) -> None:
        """Recompute unrealized PnL from current open positions."""
        self.unrealized_pnl = sum(p.unrealized_pnl for p in positions)

        # Update peak equity when unrealized moves favorably
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

    def check_daily_reset(self, current_timestamp: float) -> None:
        """Reset daily PnL if a new UTC day has started."""
        current_day = int(current_timestamp // _SECONDS_PER_DAY)
        last_day = int(self.daily_reset_timestamp // _SECONDS_PER_DAY)

        if current_day > last_day:
            logger.info(f"Daily PnL reset — previous daily_pnl={self.daily_pnl:.4f}")
            self.daily_pnl = 0.0
            self.daily_reset_timestamp = current_timestamp

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            timestamp=time.time(),
            balance=self.balance,
            equity=self.equity,
            unrealized_pnl=self.unrealized_pnl,
            realized_pnl=self.realized_pnl,
            drawdown_pct=self.current_drawdown_pct,
            peak_equity=self.peak_equity,
            open_position_count=0,  # caller should override if needed
            daily_pnl=self.daily_pnl,
        )

    # ------------------------------------------------------------------
    # DB persistence (TimescaleDB)
    # ------------------------------------------------------------------

    async def save_snapshot(self, db_pool: Any) -> None:
        """Persist current account snapshot to TimescaleDB."""
        snap = self.snapshot()
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk_account_snapshots
                    (timestamp, balance, equity, unrealized_pnl, realized_pnl,
                     drawdown_pct, peak_equity, open_position_count, daily_pnl)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                int(snap.timestamp),
                snap.balance,
                snap.equity,
                snap.unrealized_pnl,
                snap.realized_pnl,
                snap.drawdown_pct,
                snap.peak_equity,
                snap.open_position_count,
                snap.daily_pnl,
            )

    @classmethod
    async def load_latest(cls, db_pool: Any, initial_balance: float) -> AccountState:
        """Restore account state from the most recent DB snapshot."""
        state = cls(initial_balance)
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM risk_account_snapshots ORDER BY timestamp DESC LIMIT 1",
            )
        if row:
            state.realized_pnl = row["realized_pnl"]
            state.unrealized_pnl = row["unrealized_pnl"]
            state.peak_equity = row["peak_equity"]
            state.daily_pnl = row["daily_pnl"]
            logger.info(
                f"Restored account state — balance={state.balance:.4f}, "
                f"equity={state.equity:.4f}",
            )
        else:
            logger.info(
                f"No prior snapshot found — starting with initial_balance={initial_balance}",
            )
        return state
