"""Portfolio observability router."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from libs.common.db.pool_manager import DBPoolManager

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", summary="Portfolio equity and recent trade stats")
async def portfolio_summary() -> dict[str, Any]:
    """Return the latest equity snapshot and recent-trade statistics.

    Queries two DB tables written by portfolio_app:
    - ``portfolio_equity_curve`` — latest equity point (balance, drawdown, exposure)
    - ``portfolio_closed_trades`` — last 200 trades for win rate, avg PnL, total PnL

    Response shape::

        {
          "equity": {
            "timestamp": 1717000000.0,
            "lag_ms": 4200,
            "equity": 10842.50,
            "balance": 10842.50,
            "unrealized_pnl": 0.0,
            "drawdown_pct": 1.23,
            "open_position_count": 2,
            "net_exposure_pct": 12.4,
            "gross_exposure_pct": 15.1,
            "status": "ok"
          },
          "trades": {
            "sample_size": 47,
            "total_pnl": 842.50,
            "win_rate_pct": 57.4,
            "avg_pnl": 17.93,
            "avg_win": 62.10,
            "avg_loss": -38.44,
            "avg_duration_seconds": 7320.0,
            "avg_slippage_bps": 5.2,
            "status": "ok"
          }
        }

    ``status`` values: ``ok``, ``no_data``, ``error``.
    """
    now_ms = int(time.time() * 1000)

    equity_result: dict[str, Any] = {"status": "no_data"}
    trades_result: dict[str, Any] = {"status": "no_data"}

    try:
        reader_pool = DBPoolManager.get_reader_pool()
    except RuntimeError as e:
        error_msg = str(e)
        return {
            "equity": {"status": "error", "error": error_msg},
            "trades": {"status": "error", "error": error_msg},
        }

    # --- Latest equity point ---
    try:
        async with reader_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT timestamp, equity, balance, unrealized_pnl,
                       drawdown_pct, open_position_count,
                       net_exposure_pct, gross_exposure_pct
                FROM portfolio_equity_curve
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
        if row:
            ts = float(row["timestamp"])
            ts_ms = ts * 1000 if ts < 1e12 else ts
            equity_result = {
                "timestamp": ts,
                "lag_ms": now_ms - int(ts_ms),
                "equity": float(row["equity"]),
                "balance": float(row["balance"]),
                "unrealized_pnl": float(row["unrealized_pnl"]),
                "drawdown_pct": float(row["drawdown_pct"]),
                "open_position_count": int(row["open_position_count"]),
                "net_exposure_pct": float(row["net_exposure_pct"]),
                "gross_exposure_pct": float(row["gross_exposure_pct"]),
                "status": "ok",
            }
    except Exception as e:
        equity_result = {"status": "error", "error": str(e)}

    # --- Recent trade statistics (last 200 closed trades) ---
    try:
        async with reader_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT realized_pnl, commission_total, duration_seconds, slippage_bps
                FROM portfolio_closed_trades
                ORDER BY exit_timestamp DESC
                LIMIT 200
                """
            )
        if rows:
            pnls = [
                float(r["realized_pnl"]) - float(r["commission_total"])
                for r in rows
            ]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            trades_result = {
                "sample_size": len(pnls),
                "total_pnl": round(sum(pnls), 6),
                "win_rate_pct": round(len(wins) / len(pnls) * 100, 2),
                "avg_pnl": round(sum(pnls) / len(pnls), 6),
                "avg_win": round(sum(wins) / len(wins), 6) if wins else 0.0,
                "avg_loss": round(sum(losses) / len(losses), 6) if losses else 0.0,
                "avg_duration_seconds": round(
                    sum(float(r["duration_seconds"]) for r in rows) / len(rows), 2
                ),
                "avg_slippage_bps": round(
                    sum(float(r["slippage_bps"]) for r in rows) / len(rows), 4
                ),
                "status": "ok",
            }
    except Exception as e:
        trades_result = {"status": "error", "error": str(e)}

    return {"equity": equity_result, "trades": trades_result}
