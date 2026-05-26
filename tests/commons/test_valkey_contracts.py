"""Round-trip tests for valkey_encode → valkey_decode across all major contracts."""

from __future__ import annotations

import pytest

from libs.contracts.schemas import (
    ClosedTrade,
    EquityPoint,
    ExecutionReport,
    FeatureVector,
    ModelOutput,
    OrderExecutionRequest,
    OrderFill,
    OrderStatus,
    PositionState,
    TradeSignal,
    valkey_decode,
    valkey_encode,
)


# ---------------------------------------------------------------------------
# Round-trip helpers
# ---------------------------------------------------------------------------


def _assert_roundtrip(model_instance, model_class):
    """Encode → assert all values are str → decode → assert equality."""
    encoded = valkey_encode(model_instance)
    assert all(isinstance(v, str) for v in encoded.values()), (
        f"All encoded values must be str, got: "
        f"{[(k, type(v)) for k, v in encoded.items() if not isinstance(v, str)]}"
    )
    decoded = valkey_decode(encoded, model_class)
    assert decoded == model_instance


# ---------------------------------------------------------------------------
# TradeSignal
# ---------------------------------------------------------------------------


class TestTradeSignalRoundtrip:
    def test_basic_roundtrip(self) -> None:
        original = TradeSignal(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1_700_000_000.0,
            direction=1,
            conviction=0.85,
            price=50_000.0,
            idempotency_key="abc123",
            model_name="dual_ema",
            metadata={"ATR": 500.0, "score": 0.9},
        )
        _assert_roundtrip(original, TradeSignal)

    def test_empty_metadata(self) -> None:
        original = TradeSignal(
            asset="ETHUSDT",
            timeframe="1h",
            timestamp=1_700_000_001.0,
            direction=-1,
            conviction=1.0,
            price=2_000.0,
            idempotency_key="def456",
            metadata={},
        )
        _assert_roundtrip(original, TradeSignal)


# ---------------------------------------------------------------------------
# OrderExecutionRequest
# ---------------------------------------------------------------------------


class TestOrderExecutionRequestRoundtrip:
    def test_with_optional_prices(self) -> None:
        original = OrderExecutionRequest(
            asset="BTCUSDT",
            side="buy",
            size=0.05,
            order_type="market",
            timestamp=1_700_000_000.0,
            requested_price=50_000.0,
            idempotency_key="order-key-1",
            stop_loss_price=48_000.0,
            take_profit_price=55_000.0,
            model_name="trend_model",
            source_timeframe="4h",
        )
        _assert_roundtrip(original, OrderExecutionRequest)

    def test_none_optional_prices(self) -> None:
        original = OrderExecutionRequest(
            asset="ETHUSDT",
            side="sell",
            size=2.5,
            timestamp=1_700_000_002.0,
            requested_price=3_000.0,
            idempotency_key="order-key-2",
            stop_loss_price=None,
            take_profit_price=None,
        )
        _assert_roundtrip(original, OrderExecutionRequest)


# ---------------------------------------------------------------------------
# FeatureVector
# ---------------------------------------------------------------------------


class TestFeatureVectorRoundtrip:
    def test_with_nested_dicts(self) -> None:
        original = FeatureVector(
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1_700_000_000.0,
            features={"RSI": {"value": 45.0}, "ATR": {"value": 500.0}},
            bar_data={"open": 49_000.0, "high": 51_000.0, "low": 48_500.0, "close": 50_000.0, "volume": 100.0},
        )
        _assert_roundtrip(original, FeatureVector)

    def test_empty_features(self) -> None:
        original = FeatureVector(
            asset="ETHUSDT",
            timeframe="1h",
            timestamp=1_700_000_001.0,
            features={},
            bar_data={},
        )
        _assert_roundtrip(original, FeatureVector)


# ---------------------------------------------------------------------------
# ExecutionReport
# ---------------------------------------------------------------------------


class TestExecutionReportRoundtrip:
    def test_full_report(self) -> None:
        original = ExecutionReport(
            order_id="ord-abc",
            idempotency_key="idem-abc",
            asset="BTCUSDT",
            side="buy",
            requested_size=0.1,
            filled_size=0.1,
            requested_price=50_000.0,
            average_fill_price=50_010.0,
            status=OrderStatus.FILLED,
            fills=[
                OrderFill(
                    fill_id="fill-1",
                    asset="BTCUSDT",
                    side="buy",
                    size=0.1,
                    fill_price=50_010.0,
                    commission=0.5,
                    timestamp=1_700_000_000.0,
                ),
            ],
            slippage_bps=2.0,
            stop_loss_price=48_000.0,
            take_profit_price=55_000.0,
            timestamp=1_700_000_000.0,
            error_message="",
            metadata={"source": "paper"},
        )
        _assert_roundtrip(original, ExecutionReport)

    def test_empty_fills_and_metadata(self) -> None:
        original = ExecutionReport(
            order_id="ord-def",
            idempotency_key="idem-def",
            asset="ETHUSDT",
            side="sell",
            requested_size=1.0,
            filled_size=1.0,
            requested_price=2_000.0,
            average_fill_price=2_000.0,
            status=OrderStatus.CANCELLED,
            fills=[],
            timestamp=1_700_000_001.0,
            metadata={},
        )
        _assert_roundtrip(original, ExecutionReport)

    def test_none_optional_fields(self) -> None:
        original = ExecutionReport(
            order_id="ord-ghi",
            idempotency_key="idem-ghi",
            asset="SOLUSDT",
            side="buy",
            requested_size=10.0,
            filled_size=10.0,
            requested_price=100.0,
            average_fill_price=100.0,
            status=OrderStatus.FILLED,
            fills=[],
            stop_loss_price=None,
            take_profit_price=None,
            timestamp=1_700_000_002.0,
        )
        _assert_roundtrip(original, ExecutionReport)


# ---------------------------------------------------------------------------
# PositionState
# ---------------------------------------------------------------------------


class TestPositionStateRoundtrip:
    def test_with_trailing_stop(self) -> None:
        original = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=50_000.0,
            current_price=51_000.0,
            size=0.1,
            unrealized_pnl=100.0,
            entry_timestamp=1_700_000_000.0,
            source_model="trend_model",
            source_timeframe="4h",
            stop_loss_price=49_000.0,
            take_profit_price=55_000.0,
            trailing_stop_distance=500.0,
        )
        _assert_roundtrip(original, PositionState)

    def test_none_trailing_fields(self) -> None:
        original = PositionState(
            asset="ETHUSDT",
            direction=-1,
            entry_price=2_000.0,
            current_price=1_950.0,
            size=2.0,
            unrealized_pnl=100.0,
            entry_timestamp=1_700_000_001.0,
            source_model="",
            source_timeframe="",
            stop_loss_price=None,
            take_profit_price=None,
            trailing_stop_distance=None,
        )
        _assert_roundtrip(original, PositionState)


# ---------------------------------------------------------------------------
# ClosedTrade
# ---------------------------------------------------------------------------


class TestClosedTradeRoundtrip:
    def test_roundtrip(self) -> None:
        original = ClosedTrade(
            trade_id="trade-abc",
            asset="BTCUSDT",
            direction=1,
            entry_price=50_000.0,
            exit_price=51_000.0,
            size=0.1,
            realized_pnl=100.0,
            realized_pnl_pct=2.0,
            commission_total=0.5,
            slippage_bps=1.0,
            entry_timestamp=1_700_000_000.0,
            exit_timestamp=1_700_001_000.0,
            duration_seconds=1_000.0,
            source_model="dual_ema",
            source_timeframe="4h",
            entry_order_id="entry-ord",
            exit_order_id="exit-ord",
            mae_pct=0.5,
            mfe_pct=3.0,
        )
        _assert_roundtrip(original, ClosedTrade)


# ---------------------------------------------------------------------------
# EquityPoint
# ---------------------------------------------------------------------------


class TestEquityPointRoundtrip:
    def test_roundtrip(self) -> None:
        original = EquityPoint(
            timestamp=1_700_000_000.0,
            equity=10_500.0,
            balance=10_000.0,
            unrealized_pnl=500.0,
            drawdown_pct=1.5,
            open_position_count=2,
        )
        _assert_roundtrip(original, EquityPoint)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_sentinel_roundtrip(self) -> None:
        """None fields should become __NONE__ sentinel and decode back to None."""
        original = OrderExecutionRequest(
            asset="BTCUSDT",
            side="buy",
            size=0.1,
            timestamp=1_700_000_000.0,
            requested_price=50_000.0,
            idempotency_key="test-none",
            stop_loss_price=None,
            take_profit_price=None,
        )
        encoded = valkey_encode(original)
        assert encoded["stop_loss_price"] == "__NONE__"
        assert encoded["take_profit_price"] == "__NONE__"
        decoded = valkey_decode(encoded, OrderExecutionRequest)
        assert decoded.stop_loss_price is None
        assert decoded.take_profit_price is None

    def test_empty_dict_metadata_roundtrip(self) -> None:
        """Empty dict metadata={} should become '{}' string and decode back."""
        original = TradeSignal(
            asset="BTCUSDT",
            timeframe="1h",
            timestamp=1_700_000_000.0,
            direction=1,
            conviction=0.5,
            price=50_000.0,
            idempotency_key="test-empty-dict",
            metadata={},
        )
        encoded = valkey_encode(original)
        assert encoded["metadata"] == "{}"
        decoded = valkey_decode(encoded, TradeSignal)
        assert decoded.metadata == {}

    def test_empty_list_fills_roundtrip(self) -> None:
        """Empty list fills=[] should become '[]' string and decode back."""
        original = ExecutionReport(
            order_id="ord-empty",
            idempotency_key="idem-empty",
            asset="BTCUSDT",
            side="buy",
            requested_size=0.1,
            filled_size=0.1,
            requested_price=50_000.0,
            average_fill_price=50_000.0,
            status=OrderStatus.FILLED,
            fills=[],
            timestamp=1_700_000_000.0,
        )
        encoded = valkey_encode(original)
        assert encoded["fills"] == "[]"
        decoded = valkey_decode(encoded, ExecutionReport)
        assert decoded.fills == []
