"""Tests for multi-TP schema additions to contracts."""

from __future__ import annotations

import json

import pytest

from libs.contracts.execution import OrderExecutionRequest
from libs.contracts.risk import PositionState, RiskAssessment


class TestPositionStateMultiTp:
    """Verify multi-TP fields on PositionState."""

    def test_default_empty_tp_fields(self):
        """Multi-TP fields default to empty — backward compat."""
        pos = PositionState(
            asset="BTCUSDT", direction=1, entry_price=100.0,
            current_price=101.0, size=1.0, unrealized_pnl=1.0,
            entry_timestamp=1000.0, source_model="test", source_timeframe="1h",
        )
        assert pos.tp_levels == []
        assert pos.tp_portions == []
        assert pos.tp_levels_hit == []
        assert pos.original_size == 0.0
        assert pos.original_stop_loss is None
        assert pos.trail_to_breakeven is False

    def test_multi_tp_fields_populated(self):
        """Multi-TP fields can be populated."""
        pos = PositionState(
            asset="BTCUSDT", direction=1, entry_price=100.0,
            current_price=101.0, size=1.0, original_size=1.0,
            unrealized_pnl=1.0, entry_timestamp=1000.0,
            source_model="test", source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            tp_levels_hit=[True, False, False],
            original_stop_loss=98.0,
            trail_to_breakeven=True,
        )
        assert pos.tp_levels == [101.5, 103.0, 105.0]
        assert pos.tp_portions == [0.4, 0.3, 0.3]
        assert pos.tp_levels_hit == [True, False, False]
        assert pos.original_size == 1.0
        assert pos.trail_to_breakeven is True

    def test_serialization_roundtrip(self):
        """Multi-TP fields survive JSON serialization."""
        pos = PositionState(
            asset="BTCUSDT", direction=1, entry_price=100.0,
            current_price=101.0, size=0.6, original_size=1.0,
            unrealized_pnl=0.6, entry_timestamp=1000.0,
            source_model="SB", source_timeframe="1h",
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            tp_levels_hit=[True, False, False],
            trail_to_breakeven=True,
        )
        data = json.loads(pos.model_dump_json())
        restored = PositionState(**data)
        assert restored.tp_levels == pos.tp_levels
        assert restored.tp_portions == pos.tp_portions
        assert restored.tp_levels_hit == pos.tp_levels_hit
        assert restored.original_size == 1.0
        assert restored.trail_to_breakeven is True

    def test_backward_compat_single_tp(self):
        """Old-style single TP still works when multi-TP fields are empty."""
        pos = PositionState(
            asset="BTCUSDT", direction=1, entry_price=100.0,
            current_price=101.0, size=1.0, unrealized_pnl=1.0,
            entry_timestamp=1000.0, source_model="test", source_timeframe="1h",
            take_profit_price=105.0, stop_loss_price=98.0,
        )
        assert pos.take_profit_price == 105.0
        assert len(pos.tp_levels) == 0


class TestRiskAssessmentMultiTp:
    """Verify multi-TP fields on RiskAssessment."""

    def test_default_empty(self):
        """Multi-TP fields default to empty."""
        from libs.contracts.signal import TradeSignal
        sig = TradeSignal(
            asset="BTCUSDT", direction=1, conviction=0.8,
            source_model="test", source_timeframe="1h", timestamp=1000.0,
            timeframe="1h", price=100.0, idempotency_key="test_1",
        )
        ra = RiskAssessment(allowed=True, signal=sig, proposed_size=1.0)
        assert ra.tp_levels == []
        assert ra.tp_portions == []
        assert ra.trail_to_breakeven is False

    def test_multi_tp_populated(self):
        """Multi-TP assessment with levels."""
        from libs.contracts.signal import TradeSignal
        sig = TradeSignal(
            asset="BTCUSDT", direction=1, conviction=0.8,
            source_model="test", source_timeframe="1h", timestamp=1000.0,
            timeframe="1h", price=100.0, idempotency_key="test_2",
        )
        ra = RiskAssessment(
            allowed=True, signal=sig, proposed_size=1.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.4, 0.3, 0.3],
            trail_to_breakeven=True,
        )
        assert len(ra.tp_levels) == 3
        assert sum(ra.tp_portions) == pytest.approx(1.0)


class TestOrderExecutionRequestCloseReason:
    """Verify close_reason field on OrderExecutionRequest."""

    def test_default_empty(self):
        """close_reason defaults to empty string."""
        order = OrderExecutionRequest(
            asset="BTCUSDT", side="sell", size=0.4,
            timestamp=1000.0, requested_price=101.5,
            idempotency_key="tp1_BTCUSDT_1000",
        )
        assert order.close_reason == ""

    def test_close_reason_set(self):
        """close_reason can be set to tp1/tp2/tp3/sl."""
        order = OrderExecutionRequest(
            asset="BTCUSDT", side="sell", size=0.4,
            timestamp=1000.0, requested_price=101.5,
            idempotency_key="tp1_BTCUSDT_1000",
            close_reason="tp1",
        )
        assert order.close_reason == "tp1"
