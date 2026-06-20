"""Tests for RiskWorker."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.risk_app.risk_worker import RiskWorker
from libs.contracts.schemas import (
    RiskAssessment,
    TradeSignal,
)
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.mtf.aggregator import SignalAggregator
from libs.risk.position_tracker import PositionTracker


def _make_signal(**overrides) -> TradeSignal:
    defaults = dict(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=time.time(),
        direction=1,
        conviction=0.8,
        price=50_000.0,
        idempotency_key="test_key",
        model_name="test_model",
        metadata={"ATR": 500.0},
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


def _make_worker(risk_config: dict | None = None) -> RiskWorker:
    engine = MagicMock(spec=RiskEngine)
    aggregator = MagicMock(spec=SignalAggregator)
    account = AccountState(initial_balance=10_000.0)
    positions = PositionTracker()
    return RiskWorker(
        asset="BTCUSDT",
        timeframes=["1h"],
        risk_engine=engine,
        signal_aggregator=aggregator,
        account=account,
        positions=positions,
        risk_config=risk_config or {},
    )


# ------------------------------------------------------------------
# _decode_signal
# ------------------------------------------------------------------


class TestDecodeSignal:
    def test_string_payload(self) -> None:
        payload = {
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "timestamp": "1700000000.0",
            "direction": "1",
            "conviction": "0.8",
            "price": "50000.0",
            "idempotency_key": "key-1",
            "model_name": "test_model",
            "metadata": "{}",
        }
        sig = RiskWorker._decode_signal(payload)
        assert isinstance(sig, TradeSignal)
        assert sig.asset == "BTCUSDT"
        assert sig.direction == 1
        assert sig.price == 50_000.0

    def test_bytes_payload(self) -> None:
        payload = {
            b"asset": b"ETHUSDT",
            b"timeframe": b"15m",
            b"timestamp": b"1700000001.0",
            b"direction": b"-1",
            b"conviction": b"0.5",
            b"price": b"2000.0",
            b"idempotency_key": b"key-2",
            b"model_name": b"eth_model",
            b"metadata": b'{"ATR": 100}',
        }
        sig = RiskWorker._decode_signal(payload)
        assert isinstance(sig, TradeSignal)
        assert sig.asset == "ETHUSDT"
        assert sig.direction == -1
        assert sig.metadata == {"ATR": 100}

    def test_model_name_and_metadata(self) -> None:
        payload = {
            "asset": "BTCUSDT",
            "timeframe": "4h",
            "timestamp": "1700000002.0",
            "direction": "1",
            "price": "51000.0",
            "idempotency_key": "key-3",
            "model_name": "my_model",
            "metadata": json.dumps({"score": 0.9}),
        }
        sig = RiskWorker._decode_signal(payload)
        assert sig.model_name == "my_model"
        assert sig.metadata == {"score": 0.9}


# ------------------------------------------------------------------
# _process_signal_batch
# ------------------------------------------------------------------


class TestProcessSignalBatch:
    @pytest.mark.asyncio
    async def test_rejected_signal_no_order(self) -> None:
        worker = _make_worker()
        worker.redis_client = AsyncMock()

        signal = _make_signal()
        worker.signal_aggregator.aggregate.return_value = signal

        assessment = MagicMock(spec=RiskAssessment)
        assessment.allowed = False
        assessment.rejection_reason = "max_drawdown"
        worker.risk_engine.assess.return_value = assessment

        await worker._process_signal_batch([signal])

        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_signal_publishes_order(self) -> None:
        worker = _make_worker()
        worker.redis_client = AsyncMock()

        signal = _make_signal()
        worker.signal_aggregator.aggregate.return_value = signal

        assessment = MagicMock(spec=RiskAssessment)
        assessment.allowed = True
        assessment.proposed_size = 0.01
        assessment.stop_loss_price = 49_000.0
        assessment.take_profit_price = 52_000.0
        assessment.tp_levels = []
        assessment.tp_portions = []
        assessment.trail_to_breakeven = False
        worker.risk_engine.assess.return_value = assessment

        await worker._process_signal_batch([signal])

        worker.redis_client.xadd.assert_called_once()
        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "orders:BTCUSDT"
        assert call_args.kwargs["maxlen"] == 1000
        assert call_args.kwargs["approximate"] is True

    @pytest.mark.asyncio
    async def test_allowed_signal_honors_order_stream_runtime_cap(self) -> None:
        worker = _make_worker(
            risk_config={
                "runtime": {
                    "order_stream_maxlen": 600,
                    "order_stream_approximate": False,
                }
            }
        )
        worker.redis_client = AsyncMock()

        signal = _make_signal()
        worker.signal_aggregator.aggregate.return_value = signal

        assessment = MagicMock(spec=RiskAssessment)
        assessment.allowed = True
        assessment.proposed_size = 0.01
        assessment.stop_loss_price = 49_000.0
        assessment.take_profit_price = 52_000.0
        assessment.tp_levels = []
        assessment.tp_portions = []
        assessment.trail_to_breakeven = False
        worker.risk_engine.assess.return_value = assessment

        await worker._process_signal_batch([signal])

        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "orders:BTCUSDT"
        assert call_args.kwargs["maxlen"] == 600
        assert call_args.kwargs["approximate"] is False

    @pytest.mark.asyncio
    async def test_model_profile_override_is_passed_to_risk_engine(self) -> None:
        worker = _make_worker(
            risk_config={
                "position_sizing": {
                    "default_strategy": "fixed_fractional",
                    "fixed_fractional": {"risk_per_trade_pct": 2.0},
                    "volatility_scaled": {"target_risk_pct": 1.0, "atr_multiplier": 2.0},
                },
                "stop_loss": {"default_method": "fixed_pct", "fixed_pct": {"pct": 2.0}},
                "take_profit": {"default_method": "risk_reward", "risk_reward": {"ratio": 2.0}},
                "mtf": {"default_conflict_resolution": "conviction_weighted"},
                "model_profiles": {
                    "test_model": {
                        "position_sizing": {"strategy": "volatility_scaled"},
                    }
                },
            },
        )
        worker.redis_client = AsyncMock()

        signal = _make_signal(model_name="test_model")
        worker.signal_aggregator.aggregate.return_value = signal

        assessment = MagicMock(spec=RiskAssessment)
        assessment.allowed = True
        assessment.proposed_size = 0.01
        assessment.stop_loss_price = 49_000.0
        assessment.take_profit_price = 52_000.0
        assessment.tp_levels = []
        assessment.tp_portions = []
        assessment.trail_to_breakeven = False
        worker.risk_engine.assess.return_value = assessment

        await worker._process_signal_batch([signal])

        assess_call = worker.risk_engine.assess.call_args
        effective_config = assess_call.args[3]
        assert effective_config["position_sizing"]["default_strategy"] == "volatility_scaled"

    @pytest.mark.asyncio
    async def test_asset_model_override_is_passed_to_risk_engine(self) -> None:
        worker = _make_worker(
            risk_config={
                "position_sizing": {
                    "default_strategy": "fixed_fractional",
                    "fixed_fractional": {"risk_per_trade_pct": 2.0},
                    "kelly": {"fraction": 0.5},
                },
                "take_profit": {
                    "default_method": "risk_reward",
                    "risk_reward": {"ratio": 2.0},
                    "multi_level": {"levels": [{"pct": 1.5, "portion": 1.0}]},
                },
                "assets": {
                    "BTCUSDT": {
                        "model_profiles": {
                            "test_model": {
                                "position_sizing": {"strategy": "kelly"},
                                "take_profit": {"method": "multi_level"},
                            }
                        }
                    }
                },
            },
        )
        worker.redis_client = AsyncMock()

        signal = _make_signal(asset="BTCUSDT", model_name="test_model")
        worker.signal_aggregator.aggregate.return_value = signal

        assessment = MagicMock(spec=RiskAssessment)
        assessment.allowed = True
        assessment.proposed_size = 0.01
        assessment.stop_loss_price = 49_000.0
        assessment.take_profit_price = None
        assessment.tp_levels = [51_000.0]
        assessment.tp_portions = [1.0]
        assessment.trail_to_breakeven = False
        worker.risk_engine.assess.return_value = assessment

        await worker._process_signal_batch([signal])

        assess_call = worker.risk_engine.assess.call_args
        effective_config = assess_call.args[3]
        assert effective_config["position_sizing"]["default_strategy"] == "kelly"
        assert effective_config["take_profit"]["default_method"] == "multi_level"

    @pytest.mark.asyncio
    async def test_batch_profile_can_override_mtf_strategy_when_model_is_uniform(self) -> None:
        worker = _make_worker(
            risk_config={
                "mtf": {
                    "default_conflict_resolution": "conviction_weighted",
                    "timeframe_weights": {"1h": 1.0},
                },
                "model_profiles": {
                    "test_model": {
                        "mtf": {"conflict_resolution": "higher_tf_priority"},
                    }
                },
            },
        )
        worker.redis_client = AsyncMock()
        worker.risk_engine.assess.return_value = MagicMock(
            allowed=False,
            rejection_reason="rejected",
            tp_levels=[],
            tp_portions=[],
            trail_to_breakeven=False,
        )

        signal = _make_signal(model_name="test_model")
        worker.signal_aggregator.aggregate.return_value = None

        await worker._process_signal_batch([signal])

        aggregate_call = worker.signal_aggregator.aggregate.call_args
        assert aggregate_call.args[1] == "higher_tf_priority"

    @pytest.mark.asyncio
    async def test_sl_tp_triggers_order(self) -> None:
        """Position with stop_loss hit at current price → xadd called for SL/TP.

        SL/TP monitoring lives in _process_price_update (fired on every bar),
        NOT in _process_signal_batch.
        """
        from libs.contracts.schemas import PositionState, PriceUpdate, valkey_encode

        worker = _make_worker()
        worker.redis_client = AsyncMock()

        # Pre-populate a long position with a stop-loss that will be hit
        pos = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=50_000.0,
            current_price=50_000.0,
            size=0.1,
            unrealized_pnl=0.0,
            entry_timestamp=1_699_999_000.0,
            source_model="test_model",
            source_timeframe="1h",
            stop_loss_price=49_000.0,
            take_profit_price=55_000.0,
        )
        worker.positions.positions["BTCUSDT"].append(pos)

        # Send a price update where low breaches stop_loss
        price_payload = valkey_encode(PriceUpdate(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=time.time(),
            open=49_500.0,
            high=49_800.0,
            low=48_000.0,
            close=48_500.0,
            volume=100.0,
        ))

        await worker._process_price_update(price_payload)

        # SL/TP triggered → should have published an order
        worker.redis_client.xadd.assert_called_once()
        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "orders:BTCUSDT"
        assert call_args.kwargs["maxlen"] == 1000
        assert call_args.kwargs["approximate"] is True

    @pytest.mark.asyncio
    async def test_daily_reset_called(self) -> None:
        """Verify account.check_daily_reset is called during batch processing."""
        worker = _make_worker()
        worker.redis_client = AsyncMock()
        worker.account.check_daily_reset = AsyncMock()

        signal = _make_signal()
        worker.signal_aggregator.aggregate.return_value = None

        await worker._process_signal_batch([signal])

        worker.account.check_daily_reset.assert_called_once_with(signal.timestamp)


class TestRunLoop:
    @pytest.mark.asyncio
    async def test_price_stream_poll_is_non_blocking(self) -> None:
        worker = _make_worker()
        worker.redis_client = AsyncMock()
        worker._drain_signal_pel = AsyncMock()
        worker.redis_client.xreadgroup = AsyncMock(
            side_effect=[[], asyncio.CancelledError()],
        )

        await worker.run()

        assert worker.redis_client.xreadgroup.await_count == 2
        signal_call = worker.redis_client.xreadgroup.await_args_list[0]
        price_call = worker.redis_client.xreadgroup.await_args_list[1]

        assert signal_call.kwargs["block"] == worker.block_ms
        assert price_call.kwargs["block"] is None


# ------------------------------------------------------------------
# Multi-TP price update tests
# ------------------------------------------------------------------


class TestProcessPriceUpdateMultiTP:
    """Tests for _process_price_update with multi-TP positions."""

    @pytest.mark.asyncio
    async def test_tp1_partial_order_emitted(self) -> None:
        """Multi-TP position with TP1 hit queues a close order without mutating size yet."""
        from libs.contracts.schemas import PositionState, PriceUpdate, valkey_encode

        worker = _make_worker()
        worker.redis_client = AsyncMock()

        pos = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=100.0,
            current_price=100.0,
            size=1.0,
            original_size=1.0,
            unrealized_pnl=0.0,
            entry_timestamp=1_000_000.0,
            source_model="test",
            source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        worker.positions.positions["BTCUSDT"].append(pos)

        price_payload = valkey_encode(PriceUpdate(
            asset="BTCUSDT", timeframe="1h", timestamp=time.time(),
            open=100.5, high=102.0, low=100.0, close=101.5, volume=100.0,
        ))

        await worker._process_price_update(price_payload)

        # Should have published a partial close order
        assert worker.redis_client.xadd.call_count >= 1
        # Position is left unchanged until the fill listener confirms execution
        assert pos.tp_levels_hit == [False, False, False]
        assert pos.size == pytest.approx(1.0)
        assert pos.stop_loss_price == pytest.approx(98.0)
        assert pos.pending_close_reason == "tp1"
        call_args = worker.redis_client.xadd.call_args
        payload = call_args[0][1]
        assert payload["close_reason"] == "tp1"

    @pytest.mark.asyncio
    async def test_sl_closes_remaining_multi_tp(self) -> None:
        """Multi-TP SL queues a close order and leaves state unchanged until fill."""
        from libs.contracts.schemas import PositionState, PriceUpdate, valkey_encode

        worker = _make_worker()
        worker.redis_client = AsyncMock()

        pos = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=100.0,
            current_price=100.0,
            size=1.0,
            original_size=1.0,
            unrealized_pnl=0.0,
            entry_timestamp=1_000_000.0,
            source_model="test",
            source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        worker.positions.positions["BTCUSDT"].append(pos)

        price_payload = valkey_encode(PriceUpdate(
            asset="BTCUSDT", timeframe="1h", timestamp=time.time(),
            open=99.0, high=99.5, low=97.0, close=97.5, volume=100.0,
        ))

        await worker._process_price_update(price_payload)

        positions = worker.positions.positions.get("BTCUSDT", [])
        assert len(positions) == 1
        assert positions[0].pending_close_reason == "sl"
        assert worker.redis_client.xadd.call_count >= 1

    @pytest.mark.asyncio
    async def test_no_double_order_single_tp_and_multi_tp(self) -> None:
        """Multi-TP position should only be handled by multi-TP path, not legacy."""
        from libs.contracts.schemas import PositionState, PriceUpdate, valkey_encode

        worker = _make_worker()
        worker.redis_client = AsyncMock()

        pos = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=100.0,
            current_price=100.0,
            size=1.0,
            original_size=1.0,
            unrealized_pnl=0.0,
            entry_timestamp=1_000_000.0,
            source_model="test",
            source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        worker.positions.positions["BTCUSDT"].append(pos)

        # Price doesn't hit any TP or SL
        price_payload = valkey_encode(PriceUpdate(
            asset="BTCUSDT", timeframe="1h", timestamp=time.time(),
            open=100.0, high=101.0, low=99.0, close=100.5, volume=100.0,
        ))

        await worker._process_price_update(price_payload)

        # No orders should be published
        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_multi_tp_position_does_not_requeue(self) -> None:
        from libs.contracts.schemas import PositionState, PriceUpdate, valkey_encode

        worker = _make_worker()
        worker.redis_client = AsyncMock()

        pos = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=100.0,
            current_price=100.0,
            size=1.0,
            original_size=1.0,
            unrealized_pnl=0.0,
            entry_timestamp=1_000_000.0,
            source_model="test",
            source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
            pending_close_reason="tp1",
        )
        worker.positions.positions["BTCUSDT"].append(pos)

        price_payload = valkey_encode(PriceUpdate(
            asset="BTCUSDT", timeframe="1h", timestamp=time.time(),
            open=100.5, high=102.0, low=100.0, close=101.5, volume=100.0,
        ))

        await worker._process_price_update(price_payload)

        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_signal_dropped_against_wall_clock(self) -> None:
        worker = _make_worker({"mtf": {"signal_timeout_seconds": 300}})
        worker.redis_client = AsyncMock()
        worker.account.check_daily_reset = AsyncMock()

        stale_signal = _make_signal(timestamp=time.time() - 3600)
        worker.signal_aggregator.aggregate.return_value = stale_signal

        await worker._process_signal_batch([stale_signal])

        worker.signal_aggregator.aggregate.assert_not_called()
        worker.redis_client.xadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_price_update_refreshes_account_unrealized(self) -> None:
        from libs.contracts.schemas import PositionState, PriceUpdate, valkey_encode

        worker = _make_worker()
        worker.redis_client = AsyncMock()

        pos = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=100.0,
            current_price=100.0,
            size=2.0,
            unrealized_pnl=0.0,
            entry_timestamp=1_000_000.0,
            source_model="test",
            source_timeframe="1h",
        )
        worker.positions.positions["BTCUSDT"].append(pos)

        price_payload = valkey_encode(PriceUpdate(
            asset="BTCUSDT", timeframe="1h", timestamp=time.time(),
            open=100.0, high=101.0, low=99.5, close=103.0, volume=100.0,
        ))

        await worker._process_price_update(price_payload)

        assert worker.account.unrealized_pnl == pytest.approx(6.0)

    @pytest.mark.asyncio
    async def test_multi_tp_order_metadata(self) -> None:
        """Multi-TP signal batch should include tp_levels in order metadata."""
        worker = _make_worker()
        worker.redis_client = AsyncMock()
        worker.account.check_daily_reset = AsyncMock()

        signal = _make_signal(timestamp=time.time())
        worker.signal_aggregator.aggregate.return_value = signal

        assessment = MagicMock(spec=RiskAssessment)
        assessment.allowed = True
        assessment.proposed_size = 0.01
        assessment.stop_loss_price = 49_000.0
        assessment.take_profit_price = None
        assessment.tp_levels = [50_750.0, 51_500.0, 52_500.0]
        assessment.tp_portions = [0.4, 0.3, 0.3]
        assessment.trail_to_breakeven = True
        worker.risk_engine.assess.return_value = assessment

        await worker._process_signal_batch([signal])

        assert worker.redis_client.xadd.call_count >= 1
        # Verify the order was published with multi-TP metadata
        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "orders:BTCUSDT"
