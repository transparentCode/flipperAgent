"""RiskWorker — per-asset Valkey consumer for signal streams."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import OrderExecutionRequest, TradeSignal
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.mtf.aggregator import SignalAggregator
from libs.risk.position_tracker import PositionTracker

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


class RiskWorker:
    """Per-asset Valkey consumer. Subscribes to signals:{asset}:{tf} for ALL timeframes."""

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
        self.asset = asset
        self.timeframes = timeframes
        self.risk_engine = risk_engine
        self.signal_aggregator = signal_aggregator
        self.account = account
        self.positions = positions
        self.risk_config = risk_config

        self.signal_stream_keys = [f"signals:{asset}:{tf}" for tf in timeframes]
        self.order_stream_key = f"orders:{asset}"
        self.group_name = "risk_app_group"
        self.consumer_name = f"risk_worker_{asset}"
        self.redis_client: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, redis_client: Any) -> None:
        self.redis_client = redis_client
        for key in self.signal_stream_keys:
            try:
                await self.redis_client.xgroup_create(
                    key, self.group_name, id="0", mkstream=True,
                )
            except Exception as e:
                if "BUSYGROUP" not in str(e):
                    logger.error(f"Failed to create group {self.group_name} on {key}: {e}")

    async def start(self) -> None:
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
                    count=10,
                    block=1000,
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
                        sname = stream_name.decode("utf-8") if isinstance(stream_name, bytes) else stream_name
                        ack_items.append((sname, message_id))

                if signals:
                    await self._process_signal_batch(signals)

                for sname, mid in ack_items:
                    await self.redis_client.xack(sname, self.group_name, mid)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in risk worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    async def _process_signal_batch(self, signals: list[TradeSignal]) -> None:
        """MTF aggregation -> RiskEngine.assess() -> publish or reject."""

        # Check daily reset
        if signals:
            self.account.check_daily_reset(signals[0].timestamp)

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
            )

            if self.redis_client:
                await self.redis_client.xadd(
                    self.order_stream_key,
                    order.model_dump(),
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
        """Decode bytes keys/values from Valkey and reconstruct TradeSignal."""
        decoded: dict[str, Any] = {}
        for k, v in payload.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else k
            val = v.decode("utf-8") if isinstance(v, bytes) else v
            decoded[key] = val

        # Parse nested JSON fields
        if isinstance(decoded.get("metadata"), str):
            decoded["metadata"] = json.loads(decoded["metadata"])

        return TradeSignal(
            asset=decoded["asset"],
            timeframe=decoded["timeframe"],
            timestamp=float(decoded["timestamp"]),
            direction=int(decoded["direction"]),
            conviction=float(decoded.get("conviction", 1.0)),
            price=float(decoded["price"]),
            idempotency_key=decoded["idempotency_key"],
            model_name=decoded.get("model_name", ""),
            metadata=decoded.get("metadata", {}),
        )
