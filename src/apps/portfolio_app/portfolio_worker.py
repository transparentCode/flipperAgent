"""PortfolioWorker — consumes fills:{asset} and builds portfolio analytics."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.position_matcher import PositionMatcher
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import (
    ClosedTrade,
    EquityPoint,
    ExecutionReport,
    OrderStatus,
    decode_execution_report,
)
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.state import PortfolioState
from libs.portfolio.trade_journal import TradeJournal

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class PortfolioWorker(BaseStreamConsumer):
    """Consumes fills:{asset} and maintains portfolio analytics tables.

    NOTE: Both portfolio_app and risk_app consume the fills stream independently.
    Each uses its own consumer group to get an independent copy of all fill messages.
    Changes to fill processing here must be coordinated with risk_app.FillListener.
    """

    def __init__(
        self,
        asset: str,
        db_pool: Any,
        config_mgr: ConfigManager,
        shared_state: PortfolioState | None = None,
    ) -> None:
        portfolio_cfg = config_mgr.get("portfolio", {})
        consumer_cfg = portfolio_cfg.get("consumer", {})

        super().__init__(
            stream_key=f"fills:{asset}",
            group_name=consumer_cfg.get("group_name", "portfolio_app_fills_group"),
            consumer_name=f"portfolio_worker_{asset}",
            batch_size=consumer_cfg.get("batch_size", 10),
            block_ms=consumer_cfg.get("block_ms", 2000),
        )
        self.asset = asset
        self.db_pool = db_pool
        self.config_mgr = config_mgr
        self.fill_stream_key = self.stream_key

        self.trade_journal = TradeJournal(db_pool)
        self.equity_builder = EquityCurveBuilder(db_pool)
        initial_balance = portfolio_cfg.get("initial_balance", 10_000.0)
        self.state = shared_state or PortfolioState(
            balance=initial_balance,
            peak_equity=initial_balance,
        )

    async def start(self) -> None:
        """Main loop — consume fills, build trade records, snapshot equity."""
        logger.info(f"Starting portfolio worker for {self.asset}")
        await self.run()

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Decode fill report and process it."""
        report = self._decode_report(data)
        await self._process_fill(report)

    async def _process_fill(self, report: ExecutionReport) -> None:
        """Process a single fill — use PositionMatcher for FIFO matching, write to DB."""
        if report.status != OrderStatus.FILLED:
            return

        async with self.state.lock:
            if report.order_id in self.state.processed_fill_ids:
                logger.info(f"Skipping already-processed fill: {report.order_id}")
                return

            temp_matcher = PositionMatcher()
            temp_matcher.open_positions = copy.deepcopy(self._matcher.open_positions)
            temp_watermarks = copy.deepcopy(self._position_watermarks)
            temp_marks = copy.deepcopy(self._position_marks)
            temp_balance = self._balance

            planned_trades, temp_balance = self._apply_fill_to_state(
                report,
                matcher=temp_matcher,
                watermarks=temp_watermarks,
                marks=temp_marks,
                starting_balance=temp_balance,
            )
            point, net_exposure_pct, gross_exposure_pct, peak_equity = self._build_snapshot(
                matcher=temp_matcher,
                marks=temp_marks,
                balance=temp_balance,
                peak_equity=self._peak_equity,
                timestamp=report.timestamp,
            )

            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    if await self.trade_journal.is_fill_processed(report.order_id, conn=conn):
                        self.state.processed_fill_ids.add(report.order_id)
                        return

                    for closed in planned_trades:
                        await self.trade_journal._save_closed_trade(closed, conn=conn)
                    await self.equity_builder.save_equity_point(
                        point,
                        net_exposure_pct,
                        gross_exposure_pct,
                        conn=conn,
                    )
                    await self.trade_journal.mark_fill_processed(
                        report.order_id,
                        report.timestamp,
                        conn=conn,
                    )

            self._matcher.open_positions.clear()
            self._matcher.open_positions.update(temp_matcher.open_positions)
            self._position_watermarks.clear()
            self._position_watermarks.update(temp_watermarks)
            self._position_marks.clear()
            self._position_marks.update(temp_marks)
            self._balance = temp_balance
            self._peak_equity = peak_equity
            self.state.processed_fill_ids.add(report.order_id)

    def _apply_fill_to_state(
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

        total_commission = sum(f.commission for f in report.fills)
        closed_qty = sum(ct.size for ct in closed_trades)
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
        for ct in closed_trades:
            wm_key = (ct.asset, ct.entry_time, ct.entry_price)
            position_watermarks = watermarks.get(wm_key, {})

            direction = 1 if ct.side == "buy" else -1
            notional = ct.entry_price * ct.size
            pnl_pct = (ct.pnl / notional) * 100 if notional > 0 else 0.0

            # Compute MAE/MFE from watermarks
            if notional > 0 and position_watermarks:
                worst = position_watermarks.get("worst_price", ct.entry_price)
                best = position_watermarks.get("best_price", ct.entry_price)
                mae_pct = abs(min(0.0, direction * (worst - ct.entry_price) / ct.entry_price)) * 100
                mfe_pct = abs(max(0.0, direction * (best - ct.entry_price) / ct.entry_price)) * 100
            else:
                mae_pct = 0.0
                mfe_pct = 0.0

            # Proportional commission: this closed trade's share of the fill's total commission.
            # When one fill closes multiple FIFO entries, each entry should only bear its
            # fraction of the commission; assigning the full commission to every entry would
            # inflate commission_total by len(closed_trades)×.
            commission_share = (
                ct.size / report.filled_size * total_commission
                if report.filled_size > 0
                else 0.0
            )

            closed = ClosedTrade(
                trade_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{report.order_id}:{ct.asset}:{ct.entry_time}:{ct.entry_price}:{ct.size}",
                    ),
                ),
                asset=report.asset,
                direction=direction,
                entry_price=ct.entry_price,
                exit_price=ct.exit_price,
                size=ct.size,
                realized_pnl=ct.pnl,
                realized_pnl_pct=pnl_pct,
                commission_total=commission_share,
                slippage_bps=report.slippage_bps,
                entry_timestamp=ct.entry_time,
                exit_timestamp=ct.exit_time,
                duration_seconds=ct.exit_time - ct.entry_time,
                source_model=ct.metadata.get("model_name", ""),
                source_timeframe=ct.metadata.get("timeframe", ""),
                entry_order_id="",
                exit_order_id=report.order_id,
                mae_pct=mae_pct,
                mfe_pct=mfe_pct,
            )
            planned_trades.append(closed)
            # Net PnL: gross position PnL minus proportional commission paid on the exit.
            # Without this deduction, _balance drifts above the true net-of-commission equity.
            balance += ct.pnl - commission_share
            logger.info(f"Recorded closed trade — {report.asset} pnl={ct.pnl:.4f}")

        if opening_qty > 1e-12 and report.filled_size > 0:
            opening_commission_share = opening_qty / report.filled_size * total_commission
            balance -= opening_commission_share

        # Determine which positions are still active
        active_keys = {
            (pos.asset, pos.timestamp, pos.entry_price)
            for pos in matcher.open_positions.get(report.asset, [])
        }

        # Initialize watermarks for any new positions
        for pos in matcher.open_positions.get(report.asset, []):
            wm_key = (pos.asset, pos.timestamp, pos.entry_price)
            if wm_key not in watermarks:
                watermarks[wm_key] = {
                    "worst_price": pos.entry_price,
                    "best_price": pos.entry_price,
                }
            marks.setdefault(wm_key, pos.entry_price)

        # Update MAE/MFE watermarks for all remaining open positions
        for pos in matcher.open_positions.get(report.asset, []):
            wm_key = (pos.asset, pos.timestamp, pos.entry_price)
            wm = watermarks.get(wm_key)
            if wm:
                if pos.side == "buy":  # long
                    wm["worst_price"] = min(wm["worst_price"], report.average_fill_price)
                    wm["best_price"] = max(wm["best_price"], report.average_fill_price)
                else:  # short
                    wm["worst_price"] = max(wm["worst_price"], report.average_fill_price)
                    wm["best_price"] = min(wm["best_price"], report.average_fill_price)
            marks[wm_key] = report.average_fill_price

        # Clean up watermarks for fully closed positions
        for ct in closed_trades:
            wm_key = (ct.asset, ct.entry_time, ct.entry_price)
            if wm_key not in active_keys:
                watermarks.pop(wm_key, None)
                marks.pop(wm_key, None)

        return planned_trades, balance

    async def _snapshot_equity(self, timestamp: float) -> None:
        """Compute equity from local state and write an EquityPoint with exposure."""
        async with self.state.lock:
            point, net_exposure_pct, gross_exposure_pct, peak_equity = self._build_snapshot(
                matcher=self._matcher,
                marks=self._position_marks,
                balance=self._balance,
                peak_equity=self._peak_equity,
                timestamp=timestamp,
            )
            self._peak_equity = peak_equity
        await self.equity_builder.save_equity_point(point, net_exposure_pct, gross_exposure_pct)

    @staticmethod
    def _build_snapshot(
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
            for pos in asset_positions:
                open_count += 1
                key = (pos.asset, pos.timestamp, pos.entry_price)
                current_price = marks.get(key, pos.entry_price)
                notional = current_price * pos.size
                direction = 1 if pos.side == "buy" else -1
                unrealized_pnl += direction * (current_price - pos.entry_price) * pos.size
                if pos.side == "buy":
                    long_notional += notional
                else:
                    short_notional += notional

        equity = balance + unrealized_pnl
        next_peak = max(peak_equity, equity)
        drawdown_pct = (
            (next_peak - equity) / next_peak * 100
            if next_peak > 0
            else 0.0
        )

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

    @staticmethod
    def _decode_report(payload: dict) -> ExecutionReport:
        """Decode a Valkey flat-map payload into an ExecutionReport."""
        return decode_execution_report(payload)

    @property
    def _matcher(self) -> PositionMatcher:
        return self.state.matcher

    @property
    def _position_watermarks(self) -> dict[tuple[str, float, float], dict[str, float]]:
        return self.state.position_watermarks

    @property
    def _position_marks(self) -> dict[tuple[str, float, float], float]:
        return self.state.position_marks

    @property
    def _balance(self) -> float:
        return self.state.balance

    @_balance.setter
    def _balance(self, value: float) -> None:
        self.state.balance = value

    @property
    def _peak_equity(self) -> float:
        return self.state.peak_equity

    @_peak_equity.setter
    def _peak_equity(self, value: float) -> None:
        self.state.peak_equity = value
