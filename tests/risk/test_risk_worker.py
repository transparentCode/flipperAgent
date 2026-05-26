"""Tests for RiskWorker."""

from __future__ import annotations

import asyncio
import json
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
        timestamp=1_700_000_000.0,
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
        worker.risk_engine.assess.return_value = assessment

        await worker._process_signal_batch([signal])

        worker.redis_client.xadd.assert_called_once()
        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "orders:BTCUSDT"

    @pytest.mark.asyncio
    async def test_sl_tp_triggers_order(self) -> None:
        """Position with stop_loss hit at current price → xadd called for SL/TP."""
        from libs.contracts.schemas import PositionState

        worker = _make_worker()
        worker.redis_client = AsyncMock()

        signal = _make_signal(price=48_000.0)  # price below stop
        worker.signal_aggregator.aggregate.return_value = None  # no aggregated signal

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

        await worker._process_signal_batch([signal])

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
