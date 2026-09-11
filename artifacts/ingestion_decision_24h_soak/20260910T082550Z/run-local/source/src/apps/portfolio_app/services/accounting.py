"""Portfolio accounting services for fill application and equity snapshots."""

from __future__ import annotations

import uuid

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.position_matcher import PositionMatcher
from libs.contracts.schemas import ClosedTrade, EquityPoint, ExecutionReport

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class PositionAccountingService:
    """Encapsulates fill accounting and portfolio snapshot calculations."""

    def apply_fill_to_state(
        self,
        report: ExecutionReport,
        matcher: PositionMatcher,
        watermarks: dict[tuple[str, float, float], dict[str, float]],
        marks: dict[tuple[str, float, float], float],
        starting_balance: float,
    ) -> tuple[list[ClosedTrade], float]:
        """Apply a fill to copied state and return closed trades plus new balance."""
        metadata = report.metadata or {}
        closed_trades = matcher.apply_fill(
            asset=report.asset,
            side=report.side,
            size=report.filled_size,
            price=report.average_fill_price,
            timestamp=report.timestamp,
            metadata=metadata,
        )

        total_commission = sum(fill.commission for fill in report.fills)
        closed_qty = sum(closed_trade.size for closed_trade in closed_trades)
        opening_qty = max(0.0, report.filled_size - closed_qty)

        close_reason = metadata.get("close_reason", "")
        if close_reason and opening_qty > 1e-12:
            positions = matcher.open_positions.get(report.asset, [])
            if positions:
                last_position = positions[-1]
                if (
                    last_position.side == report.side
                    and abs(last_position.size - opening_qty) <= 1e-12
                    and abs(last_position.entry_price - report.average_fill_price) <= 1e-12
                    and abs(last_position.timestamp - report.timestamp) <= 1e-9
                ):
                    positions.pop()
                    opening_qty = 0.0
                    logger.warning(
                        "Ignoring unmatched close fill for %s (order_id=%s, close_reason=%s)",
                        report.asset,
                        report.order_id,
                        close_reason,
                    )

        planned_trades: list[ClosedTrade] = []
        balance = starting_balance
        for closed_trade in closed_trades:
            watermark_key = (closed_trade.asset, closed_trade.entry_time, closed_trade.entry_price)
            position_watermarks = watermarks.get(watermark_key, {})

            direction = 1 if closed_trade.side == "buy" else -1
            notional = closed_trade.entry_price * closed_trade.size
            pnl_pct = (closed_trade.pnl / notional) * 100 if notional > 0 else 0.0

            if notional > 0 and position_watermarks:
                worst = position_watermarks.get("worst_price", closed_trade.entry_price)
                best = position_watermarks.get("best_price", closed_trade.entry_price)
                mae_pct = abs(
                    min(0.0, direction * (worst - closed_trade.entry_price) / closed_trade.entry_price)
                ) * 100
                mfe_pct = abs(
                    max(0.0, direction * (best - closed_trade.entry_price) / closed_trade.entry_price)
                ) * 100
            else:
                mae_pct = 0.0
                mfe_pct = 0.0

            commission_share = (
                closed_trade.size / report.filled_size * total_commission
                if report.filled_size > 0
                else 0.0
            )

            planned_trade = ClosedTrade(
                trade_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        (
                            f"{report.order_id}:{closed_trade.asset}:"
                            f"{closed_trade.entry_time}:{closed_trade.entry_price}:{closed_trade.size}"
                        ),
                    ),
                ),
                asset=report.asset,
                direction=direction,
                entry_price=closed_trade.entry_price,
                exit_price=closed_trade.exit_price,
                size=closed_trade.size,
                realized_pnl=closed_trade.pnl,
                realized_pnl_pct=pnl_pct,
                commission_total=commission_share,
                slippage_bps=report.slippage_bps,
                entry_timestamp=closed_trade.entry_time,
                exit_timestamp=closed_trade.exit_time,
                duration_seconds=closed_trade.exit_time - closed_trade.entry_time,
                source_model=closed_trade.metadata.get("model_name", ""),
                source_timeframe=closed_trade.metadata.get("timeframe", ""),
                entry_order_id="",
                exit_order_id=report.order_id,
                mae_pct=mae_pct,
                mfe_pct=mfe_pct,
            )
            planned_trades.append(planned_trade)
            balance += closed_trade.pnl - commission_share
            logger.info("Recorded closed trade — %s pnl=%.4f", report.asset, closed_trade.pnl)

        if opening_qty > 1e-12 and report.filled_size > 0:
            opening_commission_share = opening_qty / report.filled_size * total_commission
            balance -= opening_commission_share

        active_keys = {
            (position.asset, position.timestamp, position.entry_price)
            for position in matcher.open_positions.get(report.asset, [])
        }

        for position in matcher.open_positions.get(report.asset, []):
            watermark_key = (position.asset, position.timestamp, position.entry_price)
            if watermark_key not in watermarks:
                watermarks[watermark_key] = {
                    "worst_price": position.entry_price,
                    "best_price": position.entry_price,
                }
            marks.setdefault(watermark_key, position.entry_price)

        for position in matcher.open_positions.get(report.asset, []):
            watermark_key = (position.asset, position.timestamp, position.entry_price)
            watermark = watermarks.get(watermark_key)
            if watermark:
                if position.side == "buy":
                    watermark["worst_price"] = min(watermark["worst_price"], report.average_fill_price)
                    watermark["best_price"] = max(watermark["best_price"], report.average_fill_price)
                else:
                    watermark["worst_price"] = max(watermark["worst_price"], report.average_fill_price)
                    watermark["best_price"] = min(watermark["best_price"], report.average_fill_price)
            marks[watermark_key] = report.average_fill_price

        for closed_trade in closed_trades:
            watermark_key = (closed_trade.asset, closed_trade.entry_time, closed_trade.entry_price)
            if watermark_key not in active_keys:
                watermarks.pop(watermark_key, None)
                marks.pop(watermark_key, None)

        return planned_trades, balance

    def build_snapshot(
        self,
        matcher: PositionMatcher,
        marks: dict[tuple[str, float, float], float],
        balance: float,
        peak_equity: float,
        timestamp: float,
    ) -> tuple[EquityPoint, float, float, float]:
        """Compute a mark-to-market equity snapshot from shared portfolio state."""
        long_notional = 0.0
        short_notional = 0.0
        open_count = 0
        unrealized_pnl = 0.0

        for asset_positions in matcher.open_positions.values():
            for position in asset_positions:
                open_count += 1
                position_key = (position.asset, position.timestamp, position.entry_price)
                current_price = marks.get(position_key, position.entry_price)
                notional = current_price * position.size
                direction = 1 if position.side == "buy" else -1
                unrealized_pnl += direction * (current_price - position.entry_price) * position.size
                if position.side == "buy":
                    long_notional += notional
                else:
                    short_notional += notional

        equity = balance + unrealized_pnl
        next_peak = max(peak_equity, equity)
        drawdown_pct = ((next_peak - equity) / next_peak * 100) if next_peak > 0 else 0.0
        net_exposure_pct = ((long_notional - short_notional) / equity * 100) if equity > 0 else 0.0
        gross_exposure_pct = ((long_notional + short_notional) / equity * 100) if equity > 0 else 0.0

        point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            balance=balance,
            unrealized_pnl=unrealized_pnl,
            drawdown_pct=drawdown_pct,
            open_position_count=open_count,
        )
        return point, net_exposure_pct, gross_exposure_pct, next_peak
