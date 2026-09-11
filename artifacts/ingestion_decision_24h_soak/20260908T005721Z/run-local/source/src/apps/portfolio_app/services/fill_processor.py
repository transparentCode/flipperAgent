"""Transactional fill processing for portfolio workers."""

from __future__ import annotations

import copy
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.position_matcher import PositionMatcher
from libs.contracts.schemas import ExecutionReport, OrderStatus
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.state import PortfolioState
from libs.portfolio.trade_journal import TradeJournal

from apps.portfolio_app.services.accounting import PositionAccountingService

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class PortfolioFillProcessor:
    """Applies fill reports into shared portfolio state transactionally."""

    def __init__(
        self,
        *,
        asset: str,
        db_pool: Any,
        state: PortfolioState,
        trade_journal: TradeJournal,
        equity_builder: EquityCurveBuilder,
        accounting_service: PositionAccountingService | None = None,
    ) -> None:
        self.asset = asset
        self.db_pool = db_pool
        self.state = state
        self.trade_journal = trade_journal
        self.equity_builder = equity_builder
        self.accounting_service = accounting_service or PositionAccountingService()

    async def process_fill(self, report: ExecutionReport) -> None:
        """Process a single fill and commit state only after DB success."""
        if report.status != OrderStatus.FILLED:
            return

        async with self.state.lock:
            if report.order_id in self.state.processed_fill_ids:
                logger.info("Skipping already-processed fill: %s", report.order_id)
                return

            temp_matcher = PositionMatcher()
            temp_matcher.open_positions = copy.deepcopy(self.state.matcher.open_positions)
            temp_watermarks = copy.deepcopy(self.state.position_watermarks)
            temp_marks = copy.deepcopy(self.state.position_marks)
            temp_balance = self.state.balance

            planned_trades, temp_balance = self.accounting_service.apply_fill_to_state(
                report,
                matcher=temp_matcher,
                watermarks=temp_watermarks,
                marks=temp_marks,
                starting_balance=temp_balance,
            )
            point, net_exposure_pct, gross_exposure_pct, peak_equity = (
                self.accounting_service.build_snapshot(
                    matcher=temp_matcher,
                    marks=temp_marks,
                    balance=temp_balance,
                    peak_equity=self.state.peak_equity,
                    timestamp=report.timestamp,
                )
            )

            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    if await self.trade_journal.is_fill_processed(report.order_id, conn=conn):
                        self.state.processed_fill_ids.add(report.order_id)
                        return

                    for planned_trade in planned_trades:
                        await self.trade_journal._save_closed_trade(planned_trade, conn=conn)
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

            self.state.matcher.open_positions.clear()
            self.state.matcher.open_positions.update(temp_matcher.open_positions)
            self.state.position_watermarks.clear()
            self.state.position_watermarks.update(temp_watermarks)
            self.state.position_marks.clear()
            self.state.position_marks.update(temp_marks)
            self.state.balance = temp_balance
            self.state.peak_equity = peak_equity
            self.state.processed_fill_ids.add(report.order_id)
