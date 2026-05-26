"""RiskWorker — per-asset Valkey consumer for signal streams."""

from __future__ import annotations

import asyncio
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer, ensure_consumer_group
from libs.contracts.schemas import OrderExecutionRequest, TradeSignal, valkey_encode, valkey_decode
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.mtf.aggregator import SignalAggregator
from libs.risk.position_tracker import PositionTracker

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class RiskWorker(BaseStreamConsumer):
    """Per-asset Valkey consumer. Subscribes to signals:{asset}:{tf} for ALL timeframes.

    Overrides ``run()`` because it reads from multiple streams and batches signals.
    """

    def __init__(
        self,
        asset: str,
        timeframes: list[str],
        risk_engine: RiskEngine,
        signal_aggregator: SignalAggregator,
        account: AccountState,
        positions: PositionTracker,
        risk_config: dict[str, Any],
    ) -> None:
        # Use first signal stream as primary stream_key for base class
        super().__init__(
            stream_key=f"signals:{asset}:{timeframes[0]}" if timeframes else f"signals:{asset}",
            group_name="risk_app_group",
            consumer_name=f"risk_worker_{asset}",
            batch_size=10,
            block_ms=1000,
        )
        self.asset = asset
        self.timeframes = timeframes
        self.risk_engine = risk_engine
        self.signal_aggregator = signal_aggregator
        self.account = account
        self.positions = positions
        self.risk_config = risk_config

        self.signal_stream_keys = [f"signals:{asset}:{tf}" for tf in timeframes]
        self.order_stream_key = f"orders:{asset}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, redis_client: Any) -> None:
        """Store client and create consumer groups for all signal streams."""
        self.redis_client = redis_client
        for key in self.signal_stream_keys:
            await ensure_consumer_group(redis_client, key, self.group_name)

    async def start(self) -> None:
        """Alias for run() — keeps existing call-sites working."""
        await self.run()

    async def run(self) -> None:
        """Multi-stream batch consumer loop."""
        logger.info(
            f"Starting risk worker for {self.asset} "
            f"(timeframes={self.timeframes})",
        )

        if not self.redis_client:
            logger.warning("No redis client. Running in mock mode.")
            return

        streams = {key: ">" for key in self.signal_stream_keys}

        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    streams,
                    count=self.batch_size,
                    block=self.block_ms,
                )
                if not response:
                    continue

                signals: list[TradeSignal] = []
                ack_items: list[tuple[str, str]] = []

                for stream_name, messages in response:
                    for message_id, payload in messages:
                        try:
                            sig = self._decode_signal(payload)
                            signals.append(sig)
                        except Exception as e:
                            logger.error(f"Failed to decode signal: {e}")
                        ack_items.append((stream_name, message_id))

                if signals:
                    await self._process_signal_batch(signals)

                for sname, mid in ack_items:
                    await self.redis_client.xack(sname, self.group_name, mid)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in risk worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Not used — RiskWorker overrides run() for batch processing."""
        raise NotImplementedError("RiskWorker uses batch processing via run()")

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    async def _process_signal_batch(self, signals: list[TradeSignal]) -> None:
        """MTF aggregation -> RiskEngine.assess() -> publish or reject."""

        # Check daily reset
        if signals:
            await self.account.check_daily_reset(signals[0].timestamp)

        # --- SL/TP monitoring ---
        if signals:
            price = signals[0].price
            self.positions.update_prices(self.asset, price)
            self.positions.update_trailing_stops(self.asset, price)

            hit_positions = self.positions.check_sl_tp(self.asset, price)
            for pos in hit_positions:
                close_side = "sell" if pos.direction == 1 else "buy"
                order = OrderExecutionRequest(
                    asset=self.asset,
                    side=close_side,
                    size=pos.size,
                    order_type="market",
                    timestamp=signals[0].timestamp,
                    requested_price=price,
                    idempotency_key=f"sl_tp_{self.asset}_{int(pos.entry_timestamp)}",
                    stop_loss_price=None,
                    take_profit_price=None,
                    model_name=pos.source_model,
                    source_timeframe=pos.source_timeframe,
                )
                if self.redis_client:
                    await self.redis_client.xadd(
                        self.order_stream_key,
                        valkey_encode(order),
                        maxlen=5000,
                        approximate=True,
                    )
                    logger.info(
                        f"SL/TP triggered for {self.asset}: "
                        f"closing {'long' if pos.direction == 1 else 'short'} "
                        f"position @ {price:.4f}",
                    )

        # Determine conflict resolution strategy from config
        mtf_config = self.risk_config.get("mtf", {})
        strategy = mtf_config.get(
            "default_conflict_resolution", "conviction_weighted",
        )
        tf_weights = mtf_config.get("timeframe_weights", {})

        # Aggregate signals
        result = self.signal_aggregator.aggregate(signals, strategy, tf_weights)

        if result is None:
            logger.debug(f"MTF aggregation cancelled signals for {self.asset}")
            return

        # Normalize to list
        to_assess = result if isinstance(result, list) else [result]

        for signal in to_assess:
            assessment = self.risk_engine.assess(
                signal, self.account, self.positions, self.risk_config,
            )

            if not assessment.allowed:
                logger.info(
                    f"Signal REJECTED for {self.asset}: "
                    f"{assessment.rejection_reason}",
                )
                continue

            # Build and publish OrderExecutionRequest
            order = OrderExecutionRequest(
                asset=signal.asset,
                side="buy" if signal.direction == 1 else "sell",
                size=assessment.proposed_size,
                order_type="market",
                timestamp=signal.timestamp,
                requested_price=signal.price,
                idempotency_key=signal.idempotency_key,
                stop_loss_price=assessment.stop_loss_price,
                take_profit_price=assessment.take_profit_price,
                model_name=signal.model_name,
                source_timeframe=signal.timeframe,
            )

            if self.redis_client:
                await self.redis_client.xadd(
                    self.order_stream_key,
                    valkey_encode(order),
                    maxlen=5000,
                    approximate=True,
                )
                logger.info(
                    f"Published order for {self.asset}: "
                    f"side={order.side}, size={order.size:.6f}",
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_signal(payload: dict) -> TradeSignal:
        """Decode a Valkey flat-map payload into a TradeSignal."""
        return valkey_decode(payload, TradeSignal)
