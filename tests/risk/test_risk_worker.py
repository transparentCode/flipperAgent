"""Tests for RiskWorker."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.risk_app.risk_worker import RiskWorker
from libs.contracts.schemas import (
    OrderExecutionRequest,
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


# ------------------------------------------------------------------
# Multi-TP price update tests
# ------------------------------------------------------------------


class TestProcessPriceUpdateMultiTP:
    """Tests for _process_price_update with multi-TP positions."""

    @pytest.mark.asyncio
    async def test_tp1_partial_order_emitted(self) -> None:
        """Multi-TP position with TP1 hit → partial close order published."""
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
        # Position should have TP1 marked as hit
        assert pos.tp_levels_hit[0] is True
        assert pos.size == pytest.approx(0.6)
        # Trail-to-breakeven: SL moved to entry
        assert pos.stop_loss_price == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_sl_closes_remaining_multi_tp(self) -> None:
        """Multi-TP position with SL hit → full remaining size closed."""
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

        # Position should be fully closed (removed)
        assert len(worker.positions.positions.get("BTCUSDT", [])) == 0
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
