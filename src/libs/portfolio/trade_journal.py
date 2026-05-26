"""TradeJournal — query closed trades from DB with enrichment."""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ClosedTrade, TradeJournalEntry

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class TradeJournal:
    """Query closed trades from DB and enrich with equity context."""

    def __init__(self, db_pool: Any) -> None:
        self.db_pool = db_pool

    async def get_closed_trades(
        self,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ClosedTrade]:
        """Query portfolio_closed_trades with optional filters.

        Filters are ANDed. Results ordered by exit_timestamp DESC.
        """
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if asset is not None:
            conditions.append(f"asset = ${idx}")
            params.append(asset)
            idx += 1
        if model is not None:
            conditions.append(f"source_model = ${idx}")
            params.append(model)
            idx += 1
        if timeframe is not None:
            conditions.append(f"source_timeframe = ${idx}")
            params.append(timeframe)
            idx += 1
        if start_timestamp is not None:
            conditions.append(f"exit_timestamp >= ${idx}")
            params.append(start_timestamp)
            idx += 1
        if end_timestamp is not None:
            conditions.append(f"exit_timestamp <= ${idx}")
            params.append(end_timestamp)
            idx += 1

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT trade_id, asset, direction, entry_price, exit_price, size,
                   realized_pnl, realized_pnl_pct, commission_total, slippage_bps,
                   entry_timestamp, exit_timestamp, duration_seconds,
                   source_model, source_timeframe, entry_order_id, exit_order_id,
                   mae_pct, mfe_pct
            FROM portfolio_closed_trades
            {where_clause}
            ORDER BY exit_timestamp DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """
        params.extend([limit, offset])

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_closed_trade(r) for r in rows]

    async def get_journal_entries(
        self,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradeJournalEntry]:
        """Get closed trades enriched with equity context.

        For each trade, finds the nearest account snapshot at entry and exit
        time from risk_account_snapshots.
        """
        trades = await self.get_closed_trades(
            asset=asset,
            model=model,
            timeframe=timeframe,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            offset=offset,
        )
        if not trades:
            return []

        entries: list[TradeJournalEntry] = []
        for trade in trades:
            equity_at_entry = await self._lookup_equity_at(trade.entry_timestamp)
            equity_at_exit = await self._lookup_equity_at(trade.exit_timestamp)
            drawdown_at_entry = await self._lookup_drawdown_at(trade.entry_timestamp)

            risk_reward = self._compute_risk_reward(trade)

            entries.append(TradeJournalEntry(
                trade=trade,
                equity_at_entry=equity_at_entry,
                equity_at_exit=equity_at_exit,
                drawdown_at_entry_pct=drawdown_at_entry,
                risk_reward_achieved=risk_reward,
            ))

        return entries

    async def get_trade_count(
        self,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
    ) -> int:
        """Return count of closed trades matching filters."""
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if asset is not None:
            conditions.append(f"asset = ${idx}")
            params.append(asset)
            idx += 1
        if model is not None:
            conditions.append(f"source_model = ${idx}")
            params.append(model)
            idx += 1
        if timeframe is not None:
            conditions.append(f"source_timeframe = ${idx}")
            params.append(timeframe)
            idx += 1
        if start_timestamp is not None:
            conditions.append(f"exit_timestamp >= ${idx}")
            params.append(start_timestamp)
            idx += 1
        if end_timestamp is not None:
            conditions.append(f"exit_timestamp <= ${idx}")
            params.append(end_timestamp)
            idx += 1

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"SELECT COUNT(*) FROM portfolio_closed_trades {where_clause}"

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)

        return int(row[0]) if row else 0

    async def save_closed_trade(self, trade: ClosedTrade) -> None:
        """Persist a ClosedTrade to portfolio_closed_trades.

        Uses ON CONFLICT (trade_id) DO NOTHING for idempotency.
        """
        query = """
            INSERT INTO portfolio_closed_trades
                (trade_id, asset, direction, entry_price, exit_price, size,
                 realized_pnl, realized_pnl_pct, commission_total, slippage_bps,
                 entry_timestamp, exit_timestamp, duration_seconds,
                 source_model, source_timeframe, entry_order_id, exit_order_id,
                 mae_pct, mfe_pct)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18, $19)
            ON CONFLICT (trade_id) DO NOTHING
        """
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                query,
                trade.trade_id,
                trade.asset,
                trade.direction,
                trade.entry_price,
                trade.exit_price,
                trade.size,
                trade.realized_pnl,
                trade.realized_pnl_pct,
                trade.commission_total,
                trade.slippage_bps,
                trade.entry_timestamp,
                trade.exit_timestamp,
                trade.duration_seconds,
                trade.source_model,
                trade.source_timeframe,
                trade.entry_order_id,
                trade.exit_order_id,
                trade.mae_pct,
                trade.mfe_pct,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _lookup_equity_at(self, timestamp: float) -> float:
        """Find nearest account snapshot equity at or before timestamp."""
        query = """
            SELECT equity FROM risk_account_snapshots
            WHERE timestamp <= $1
            ORDER BY timestamp DESC
            LIMIT 1
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(query, timestamp)
        return float(row["equity"]) if row else 0.0

    async def _lookup_drawdown_at(self, timestamp: float) -> float:
        """Find nearest drawdown_pct at or before timestamp."""
        query = """
            SELECT drawdown_pct FROM risk_account_snapshots
            WHERE timestamp <= $1
            ORDER BY timestamp DESC
            LIMIT 1
        """
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(query, timestamp)
        return float(row["drawdown_pct"]) if row else 0.0

    @staticmethod
    def _compute_risk_reward(trade: ClosedTrade) -> float:
        """Compute achieved risk/reward ratio.

        risk_taken = |entry_price - stop_loss_price| * size if available,
        else entry notional * 0.02 as fallback.
        """
        entry_notional = trade.entry_price * trade.size
        if entry_notional == 0:
            return 0.0

        # Fallback: assume 2% risk if no stop loss data
        risk_taken = entry_notional * 0.02

        if risk_taken == 0:
            return 0.0

        return abs(trade.realized_pnl) / risk_taken

    @staticmethod
    def _row_to_closed_trade(row: Any) -> ClosedTrade:
        """Map a DB row to ClosedTrade schema."""
        return ClosedTrade(
            trade_id=str(row["trade_id"]),
            asset=row["asset"],
            direction=int(row["direction"]),
            entry_price=float(row["entry_price"]),
            exit_price=float(row["exit_price"]),
            size=float(row["size"]),
            realized_pnl=float(row["realized_pnl"]),
            realized_pnl_pct=float(row["realized_pnl_pct"]),
            commission_total=float(row["commission_total"]),
            slippage_bps=float(row["slippage_bps"]),
            entry_timestamp=float(row["entry_timestamp"]),
            exit_timestamp=float(row["exit_timestamp"]),
            duration_seconds=float(row["duration_seconds"]),
            source_model=row["source_model"] or "",
            source_timeframe=row["source_timeframe"] or "",
            entry_order_id=row["entry_order_id"] or "",
            exit_order_id=row["exit_order_id"] or "",
            mae_pct=float(row["mae_pct"]),
            mfe_pct=float(row["mfe_pct"]),
        )
