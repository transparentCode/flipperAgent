"""Live mark-to-market worker for portfolio_app price updates."""

from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import PriceUpdate, valkey_decode
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.state import PortfolioState

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class PortfolioMarkWorker(BaseStreamConsumer):
    """Consumes `price_update:{asset}:{timeframe}` and refreshes portfolio MTM state."""

    def __init__(
        self,
        *,
        asset: str,
        timeframe: str,
        db_pool: Any,
        config_mgr: ConfigManager,
        shared_state: PortfolioState,
    ) -> None:
        portfolio_cfg = config_mgr.get("portfolio", {})
        consumer_cfg = portfolio_cfg.get("consumer", {})

        super().__init__(
            stream_key=f"price_update:{asset}:{timeframe}",
            group_name=consumer_cfg.get("price_group_name", "portfolio_app_prices_group"),
            consumer_name=f"portfolio_mark_worker_{asset}_{timeframe}",
            batch_size=consumer_cfg.get("price_batch_size", 10),
            block_ms=consumer_cfg.get("price_block_ms", 2000),
        )
        self.asset = asset
        self.timeframe = timeframe
        self.db_pool = db_pool
        self.config_mgr = config_mgr
        self.state = shared_state
        self.equity_builder = EquityCurveBuilder(db_pool)

    async def start(self) -> None:
        logger.info("Starting portfolio mark worker for %s:%s", self.asset, self.timeframe)
        await self.run()

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        price_update = valkey_decode(data, PriceUpdate)
        async with self.state.lock:
            self.state.apply_price_update(
                price_update.asset,
                high=price_update.high,
                low=price_update.low,
                close=price_update.close,
            )
            point, net_exposure_pct, gross_exposure_pct = self.state.build_equity_snapshot(
                timestamp=price_update.timestamp,
            )
        await self.equity_builder.save_equity_point(point, net_exposure_pct, gross_exposure_pct)
