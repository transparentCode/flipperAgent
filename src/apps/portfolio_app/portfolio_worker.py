"""PortfolioWorker — consumes fills:{asset} and builds portfolio analytics."""

from __future__ import annotations

import asyncio
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
    valkey_decode,
)
from libs.portfolio.equity_curve import EquityCurveBuilder
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

        # FIFO position matching engine
        self._matcher = PositionMatcher()
        # MAE/MFE watermarks keyed by (asset, entry_timestamp, entry_price)
        self._position_watermarks: dict[tuple, dict[str, float]] = {}
        # Local balance tracking for equity snapshots
        self._balance: float = portfolio_cfg.get("initial_balance", 10_000.0)
        self._peak_equity: float = self._balance

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

        metadata = report.metadata or {}
        closed_trades = self._matcher.apply_fill(
            asset=report.asset,
            side=report.side,
            size=report.filled_size,
            price=report.average_fill_price,
            timestamp=report.timestamp,
            metadata=metadata,
        )

        # Process closed trades
        for ct in closed_trades:
            wm_key = (ct.asset, ct.entry_time, ct.entry_price)
            watermarks = self._position_watermarks.get(wm_key, {})

            direction = 1 if ct.side == "buy" else -1
            notional = ct.entry_price * ct.size
            pnl_pct = (ct.pnl / notional) * 100 if notional > 0 else 0.0

            # Compute MAE/MFE from watermarks
            if notional > 0 and watermarks:
                worst = watermarks.get("worst_price", ct.entry_price)
                best = watermarks.get("best_price", ct.entry_price)
                mae_pct = abs(min(0.0, direction * (worst - ct.entry_price) / ct.entry_price)) * 100
                mfe_pct = abs(max(0.0, direction * (best - ct.entry_price) / ct.entry_price)) * 100
            else:
                mae_pct = 0.0
                mfe_pct = 0.0

            closed = ClosedTrade(
                trade_id=uuid.uuid4().hex,
                asset=report.asset,
                direction=direction,
                entry_price=ct.entry_price,
                exit_price=ct.exit_price,
                size=ct.size,
                realized_pnl=ct.pnl,
                realized_pnl_pct=pnl_pct,
                commission_total=sum(f.commission for f in report.fills),
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
            await self.trade_journal.save_closed_trade(closed)
            self._balance += ct.pnl
            logger.info(f"Recorded closed trade — {report.asset} pnl={ct.pnl:.4f}")

        # Determine which positions are still active
        active_keys = {
            (pos.asset, pos.timestamp, pos.entry_price)
            for pos in self._matcher.open_positions.get(report.asset, [])
        }

        # Initialize watermarks for any new positions
        for pos in self._matcher.open_positions.get(report.asset, []):
            wm_key = (pos.asset, pos.timestamp, pos.entry_price)
            if wm_key not in self._position_watermarks:
                self._position_watermarks[wm_key] = {
                    "worst_price": pos.entry_price,
                    "best_price": pos.entry_price,
                }

        # Update MAE/MFE watermarks for all remaining open positions
        for pos in self._matcher.open_positions.get(report.asset, []):
            wm_key = (pos.asset, pos.timestamp, pos.entry_price)
            wm = self._position_watermarks.get(wm_key)
            if wm:
                if pos.side == "buy":  # long
                    wm["worst_price"] = min(wm["worst_price"], report.average_fill_price)
                    wm["best_price"] = max(wm["best_price"], report.average_fill_price)
                else:  # short
                    wm["worst_price"] = max(wm["worst_price"], report.average_fill_price)
                    wm["best_price"] = min(wm["best_price"], report.average_fill_price)

        # Clean up watermarks for fully closed positions
        for ct in closed_trades:
            wm_key = (ct.asset, ct.entry_time, ct.entry_price)
            if wm_key not in active_keys:
                self._position_watermarks.pop(wm_key, None)

        # Snapshot equity after every fill
        await self._snapshot_equity(report.timestamp)

    async def _snapshot_equity(self, timestamp: float) -> None:
        """Compute equity from local state and write an EquityPoint with exposure."""
        # Compute exposure from open positions
        long_notional = 0.0
        short_notional = 0.0
        open_count = 0

        for asset_positions in self._matcher.open_positions.values():
            for pos in asset_positions:
                open_count += 1
                notional = pos.entry_price * pos.size
                if pos.side == "buy":
                    long_notional += notional
                else:
                    short_notional += notional

        equity = self._balance
        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown_pct = (
            (self._peak_equity - equity) / self._peak_equity * 100
            if self._peak_equity > 0
            else 0.0
        )

        net_exposure_pct = ((long_notional - short_notional) / equity * 100) if equity > 0 else 0.0
        gross_exposure_pct = ((long_notional + short_notional) / equity * 100) if equity > 0 else 0.0

        point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            balance=self._balance,
            unrealized_pnl=0.0,
            drawdown_pct=drawdown_pct,
            open_position_count=open_count,
        )
        await self.equity_builder.save_equity_point(point, net_exposure_pct, gross_exposure_pct)

    @staticmethod
    def _decode_report(payload: dict) -> ExecutionReport:
        """Decode a Valkey flat-map payload into an ExecutionReport."""
        return valkey_decode(payload, ExecutionReport)
