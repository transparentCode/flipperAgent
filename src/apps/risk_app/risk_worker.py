"""RiskWorker — per-asset Valkey consumer for signal streams."""

from __future__ import annotations

import asyncio
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer, ensure_consumer_group
from libs.contracts.schemas import OrderExecutionRequest, TradeSignal, PriceUpdate, valkey_encode, valkey_decode
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.mtf.aggregator import SignalAggregator
from libs.risk.position_tracker import PositionTracker

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)

# --- OTel setup (graceful if not available) ---
_tracer = None
_extract_trace_context = None
try:
    from opentelemetry import trace as _trace
    from libs.common.telemetry.propagation import extract_trace_context as _etc
    _tracer = _trace.get_tracer(__name__)
    _extract_trace_context = _etc
except ImportError:
    pass


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
        self.price_stream_keys = [f"price_update:{asset}:{tf}" for tf in timeframes]
        self.order_stream_key = f"orders:{asset}"
        self.price_group_name = "risk_app_price_group"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, redis_client: Any) -> None:
        """Store client and create consumer groups for all signal and price streams."""
        self.redis_client = redis_client
        for key in self.signal_stream_keys:
            await ensure_consumer_group(redis_client, key, self.group_name)
        for key in self.price_stream_keys:
            await ensure_consumer_group(redis_client, key, self.price_group_name)

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

        await self._drain_signal_pel()

        signal_streams = {key: ">" for key in self.signal_stream_keys}
        price_streams = {key: ">" for key in self.price_stream_keys}
        price_stream_set = set(self.price_stream_keys)
        consecutive_failures = 0
        circuit_breaker_threshold = self.risk_config.get("circuit_breaker_threshold", 50)

        while True:
            try:
                # Read signal streams
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    signal_streams,
                    count=self.batch_size,
                    block=self.block_ms,
                )

                # Read price update streams (non-blocking)
                price_response = await self.redis_client.xreadgroup(
                    self.price_group_name,
                    self.consumer_name,
                    price_streams,
                    count=self.batch_size,
                    block=0,
                )

                # Process price updates first (SL/TP on every bar)
                if price_response:
                    for stream_name, messages in price_response:
                        for message_id, payload in messages:
                            try:
                                if _tracer and _extract_trace_context:
                                    parent_ctx = _extract_trace_context(payload)
                                    with _tracer.start_as_current_span(
                                        "risk.process_price_update",
                                        context=parent_ctx,
                                        attributes={
                                            "messaging.system": "valkey",
                                            "messaging.destination": stream_name
                                            if isinstance(stream_name, str)
                                            else stream_name.decode("utf-8", errors="replace"),
                                            "risk.asset": self.asset,
                                        },
                                    ):
                                        await self._process_price_update(payload)
                                else:
                                    await self._process_price_update(payload)
                                await self.redis_client.xack(
                                    stream_name, self.price_group_name, message_id,
                                )
                            except Exception as e:
                                logger.error(f"Failed to process price update: {e}", exc_info=True)

                if not response:
                    continue

                signals: list[TradeSignal] = []
                ack_items: list[tuple[str, str]] = []
                first_parent_ctx = None

                for stream_name, messages in response:
                    for message_id, payload in messages:
                        try:
                            if _extract_trace_context and first_parent_ctx is None:
                                first_parent_ctx = _extract_trace_context(payload)
                            sig = self._decode_signal(payload)
                            signals.append(sig)
                        except Exception as e:
                            logger.error(f"Failed to decode signal: {e}")
                        ack_items.append((stream_name, message_id))

                if signals:
                    if _tracer:
                        span_kwargs: dict = {
                            "attributes": {
                                "risk.asset": self.asset,
                                "risk.batch_size": len(signals),
                            },
                        }
                        if first_parent_ctx is not None:
                            span_kwargs["context"] = first_parent_ctx
                        with _tracer.start_as_current_span(
                            "risk.process_signal_batch",
                            **span_kwargs,
                        ):
                            await self._process_signal_batch(signals)
                    else:
                        await self._process_signal_batch(signals)

                for sname, mid in ack_items:
                    await self.redis_client.xack(sname, self.group_name, mid)

                # Successful iteration — reset circuit breaker
                consecutive_failures = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"Error in risk worker loop: {e} (consecutive failures: {consecutive_failures})", exc_info=True)
                if consecutive_failures >= circuit_breaker_threshold:
                    logger.critical(
                        f"Circuit breaker tripped for risk worker {self.asset}: "
                        f"{consecutive_failures} consecutive failures. Breaking consumer loop."
                    )
                    break
                await asyncio.sleep(1)

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Not used — RiskWorker overrides run() for batch processing."""
        raise NotImplementedError("RiskWorker uses batch processing via run()")

    async def _drain_signal_pel(self) -> None:
        """Re-claim and reprocess any signal messages left in the PEL from a previous crash.

        Price-update streams are not drained — price heartbeats are ephemeral and
        replaying them after a crash offers no value.
        """
        for stream_key in self.signal_stream_keys:
            try:
                next_id = "0-0"
                while True:
                    result = await self.redis_client.xautoclaim(
                        stream_key,
                        self.group_name,
                        self.consumer_name,
                        min_idle_time=0,
                        start_id=next_id,
                        count=self.batch_size,
                    )
                    next_id, pending_messages, _ = result
                    if not pending_messages:
                        break

                    signals: list[TradeSignal] = []
                    ack_ids: list[str] = []
                    for message_id, data in pending_messages:
                        try:
                            signals.append(self._decode_signal(data))
                        except Exception as e:
                            logger.error(f"Failed to decode PEL signal {message_id}: {e}")
                        ack_ids.append(message_id)

                    if signals:
                        await self._process_signal_batch(signals)
                    for mid in ack_ids:
                        await self.redis_client.xack(stream_key, self.group_name, mid)

                    if next_id == "0-0":
                        break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    f"PEL drain failed for {stream_key} — skipping, proceeding to live stream",
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    async def _process_signal_batch(self, signals: list[TradeSignal]) -> None:
        """MTF aggregation -> RiskEngine.assess() -> publish or reject.

        SL/TP monitoring is handled exclusively by _process_price_update() via the
        price_update stream, which fires on every bar. Do NOT duplicate that check
        here — it would cause double close-orders for the same bar.
        """

        # Check daily reset
        if signals:
            await self.account.check_daily_reset(signals[0].timestamp)

        # Drop signals older than signal_timeout_seconds
        timeout_secs = self.risk_config.get("mtf", {}).get("signal_timeout_seconds", 300)
        if timeout_secs > 0:
            now = max(s.timestamp for s in signals)
            fresh = [s for s in signals if now - s.timestamp <= timeout_secs]
            if len(fresh) < len(signals):
                logger.warning(
                    f"Dropped {len(signals) - len(fresh)} stale signal(s) for {self.asset} "
                    f"(timeout={timeout_secs}s)",
                )
            signals = fresh
        if not signals:
            return

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
            order_metadata: dict[str, Any] = {}
            if assessment.tp_levels:
                order_metadata["tp_levels"] = assessment.tp_levels
                order_metadata["tp_portions"] = assessment.tp_portions
                order_metadata["trail_to_breakeven"] = assessment.trail_to_breakeven

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
                metadata=order_metadata,
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
    # Price update processing
    # ------------------------------------------------------------------

    async def _process_price_update(self, payload: dict) -> None:
        """Handle a price heartbeat — check SL/TP on every bar regardless of signals."""
        price_update = valkey_decode(payload, PriceUpdate)
        close = price_update.close
        high = price_update.high
        low = price_update.low

        self.positions.update_prices(self.asset, close)
        self.positions.update_trailing_stops(self.asset, close)

        # Multi-TP: check for partial exits first
        partial_exits = self.positions.check_sl_tp_hlc_multi(
            self.asset, high, low, close,
        )
        for pos, close_reason, close_size in partial_exits:
            close_side = "sell" if pos.direction == 1 else "buy"
            order = OrderExecutionRequest(
                asset=self.asset,
                side=close_side,
                size=close_size,
                order_type="market",
                timestamp=price_update.timestamp,
                requested_price=close,
                idempotency_key=f"{close_reason}_{self.asset}_{int(pos.entry_timestamp)}",
                close_reason=close_reason,
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

            # Apply partial exit to position state immediately
            pos_list = self.positions.positions.get(self.asset, [])
            try:
                pos_index = pos_list.index(pos)
            except ValueError:
                pos_index = -1

            if close_reason == "sl":
                # SL closes full remaining position — remove it
                if pos_index >= 0:
                    await self.positions.close_position(self.asset, pos_index)
                logger.info(
                    f"Multi-TP SL triggered for {self.asset}: "
                    f"closing remaining size={close_size:.6f} @ close={close:.4f}",
                )
            elif pos_index >= 0:
                # Extract tp_level_index from close_reason (e.g. "tp1" -> 0)
                tp_level_index = int(close_reason[2:]) - 1
                self.positions.apply_partial_exit(
                    self.asset, pos_index, close_size, tp_level_index,
                )
                logger.info(
                    f"Multi-TP {close_reason} triggered for {self.asset}: "
                    f"partial close size={close_size:.6f} @ close={close:.4f}",
                )

        # Legacy single-TP path (positions where tp_levels is empty)
        hit_positions = self.positions.check_sl_tp_hlc(self.asset, high, low, close)
        for pos in hit_positions:
            close_side = "sell" if pos.direction == 1 else "buy"
            order = OrderExecutionRequest(
                asset=self.asset,
                side=close_side,
                size=pos.size,
                order_type="market",
                timestamp=price_update.timestamp,
                requested_price=close,
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
                    f"Price heartbeat SL/TP triggered for {self.asset}: "
                    f"closing {'long' if pos.direction == 1 else 'short'} "
                    f"position @ close={close:.4f} (H={high:.4f} L={low:.4f})",
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_signal(payload: dict) -> TradeSignal:
        """Decode a Valkey flat-map payload into a TradeSignal."""
        return valkey_decode(payload, TradeSignal)
