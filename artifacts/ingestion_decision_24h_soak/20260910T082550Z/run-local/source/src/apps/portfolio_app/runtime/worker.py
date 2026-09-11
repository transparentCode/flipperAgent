"""Thin runtime worker for portfolio_app fills ingestion."""

from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.position_matcher import PositionMatcher
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import ClosedTrade, EquityPoint, ExecutionReport, decode_execution_report
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.state import PortfolioState
from libs.portfolio.trade_journal import TradeJournal

from apps.portfolio_app.services.accounting import PositionAccountingService
from apps.portfolio_app.services.fill_processor import PortfolioFillProcessor

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class PortfolioWorker(BaseStreamConsumer):
    """Consumes fills:{asset} and maintains portfolio analytics tables."""

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
        self.accounting_service = PositionAccountingService()
        self.fill_processor = PortfolioFillProcessor(
            asset=asset,
            db_pool=db_pool,
            state=self.state,
            trade_journal=self.trade_journal,
            equity_builder=self.equity_builder,
            accounting_service=self.accounting_service,
        )

    async def start(self) -> None:
        """Main loop — consume fills, build trade records, snapshot equity."""
        logger.info("Starting portfolio worker for %s", self.asset)
        await self.run()

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Decode fill report and process it."""
        report = self._decode_report(data)
        await self._process_fill(report)

    async def _process_fill(self, report: ExecutionReport) -> None:
        """Process a single fill via the transactional fill processor."""
        await self.fill_processor.process_fill(report)

    def _apply_fill_to_state(
        self,
        report: ExecutionReport,
        matcher: PositionMatcher,
        watermarks: dict[tuple[str, float, float], dict[str, float]],
        marks: dict[tuple[str, float, float], float],
        starting_balance: float,
    ) -> tuple[list[ClosedTrade], float]:
        """Apply a fill using the extracted accounting service."""
        return self.accounting_service.apply_fill_to_state(
            report,
            matcher=matcher,
            watermarks=watermarks,
            marks=marks,
            starting_balance=starting_balance,
        )

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

    def _build_snapshot(
        self,
        matcher: PositionMatcher,
        marks: dict[tuple[str, float, float], float],
        balance: float,
        peak_equity: float,
        timestamp: float,
    ) -> tuple[EquityPoint, float, float, float]:
        """Compute a mark-to-market equity snapshot from shared portfolio state."""
        return self.accounting_service.build_snapshot(
            matcher=matcher,
            marks=marks,
            balance=balance,
            peak_equity=peak_equity,
            timestamp=timestamp,
        )

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
