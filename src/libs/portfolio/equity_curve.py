"""EquityCurveBuilder — build and query equity curve time-series."""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import EquityPoint

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class EquityCurveBuilder:
    """Build and query equity curve time-series."""

    def __init__(self, db_pool: Any) -> None:
        self.db_pool = db_pool

    async def get_equity_curve(
        self,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        max_points: int = 10000,
    ) -> list[EquityPoint]:
        """Query portfolio_equity_curve table for equity time-series.

        If the number of rows exceeds max_points, downsample using
        ROW_NUMBER striding. Results ordered by timestamp ASC.
        """
        # First, get total count to decide on striding
        count_conditions: list[str] = []
        count_params: list[Any] = []
        idx = 1

        if start_timestamp is not None:
            count_conditions.append(f"timestamp >= ${idx}")
            count_params.append(start_timestamp)
            idx += 1
        if end_timestamp is not None:
            count_conditions.append(f"timestamp <= ${idx}")
            count_params.append(end_timestamp)
            idx += 1

        where_clause = ""
        if count_conditions:
            where_clause = "WHERE " + " AND ".join(count_conditions)

        count_query = f"SELECT COUNT(*) FROM portfolio_equity_curve {where_clause}"

        async with self.db_pool.acquire() as conn:
            count_row = await conn.fetchrow(count_query, *count_params)

        total = int(count_row[0]) if count_row else 0
        if total == 0:
            return []

        # Build main query with optional striding
        params: list[Any] = list(count_params)
        pidx = idx

        if total > max_points and max_points > 0:
            stride = total // max_points
            query = f"""
                SELECT timestamp, equity, balance, unrealized_pnl,
                       drawdown_pct, open_position_count
                FROM (
                    SELECT *, ROW_NUMBER() OVER (ORDER BY timestamp ASC) AS rn
                    FROM portfolio_equity_curve
                    {where_clause}
                ) sub
                WHERE (sub.rn - 1) % ${pidx} = 0
                ORDER BY timestamp ASC
            """
            params.append(stride)
        else:
            query = f"""
                SELECT timestamp, equity, balance, unrealized_pnl,
                       drawdown_pct, open_position_count
                FROM portfolio_equity_curve
                {where_clause}
                ORDER BY timestamp ASC
            """

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_equity_point(r) for r in rows]

    async def save_equity_point(
        self,
        point: EquityPoint,
        net_exposure_pct: float = 0.0,
        gross_exposure_pct: float = 0.0,
        conn: Any | None = None,
    ) -> None:
        """Persist a single equity point with optional exposure data.

        Uses ON CONFLICT (timestamp) DO UPDATE to overwrite stale snapshots.
        """
        query = """
            INSERT INTO portfolio_equity_curve
                (timestamp, equity, balance, unrealized_pnl,
                 drawdown_pct, open_position_count,
                 net_exposure_pct, gross_exposure_pct)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (timestamp) DO UPDATE SET
                equity = EXCLUDED.equity,
                balance = EXCLUDED.balance,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                drawdown_pct = EXCLUDED.drawdown_pct,
                open_position_count = EXCLUDED.open_position_count,
                net_exposure_pct = EXCLUDED.net_exposure_pct,
                gross_exposure_pct = EXCLUDED.gross_exposure_pct
        """
        async def _execute(target_conn: Any) -> None:
            await target_conn.execute(
                query,
                point.timestamp,
                point.equity,
                point.balance,
                point.unrealized_pnl,
                point.drawdown_pct,
                point.open_position_count,
                net_exposure_pct,
                gross_exposure_pct,
            )

        if conn is not None:
            await _execute(conn)
            return

        async with self.db_pool.acquire() as pooled_conn:
            await _execute(pooled_conn)

    async def build_from_account_snapshots(
        self,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
    ) -> list[EquityPoint]:
        """Build equity curve from existing risk_account_snapshots table.

        This is the offline/backtest path — reads from risk_account_snapshots
        (already populated by AccountState.save_snapshot) and converts to
        EquityPoint objects. Does NOT write to portfolio_equity_curve.
        """
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if start_timestamp is not None:
            conditions.append(f"timestamp >= ${idx}")
            params.append(start_timestamp)
            idx += 1
        if end_timestamp is not None:
            conditions.append(f"timestamp <= ${idx}")
            params.append(end_timestamp)
            idx += 1

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT timestamp, equity, balance, unrealized_pnl,
                   drawdown_pct, open_position_count
            FROM risk_account_snapshots
            {where_clause}
            ORDER BY timestamp ASC
        """

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_equity_point(r) for r in rows]

    @staticmethod
    def _row_to_equity_point(row: Any) -> EquityPoint:
        """Map a DB row to EquityPoint schema."""
        return EquityPoint(
            timestamp=float(row["timestamp"]),
            equity=float(row["equity"]),
            balance=float(row["balance"]),
            unrealized_pnl=float(row["unrealized_pnl"]),
            drawdown_pct=float(row["drawdown_pct"]),
            open_position_count=int(row["open_position_count"]),
        )
