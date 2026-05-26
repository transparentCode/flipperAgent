"""Tests for ExecutionWorker — decode_order helper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.execution_app.execution_worker import ExecutionWorker
from libs.contracts.schemas import (
    ExecutionReport,
    OrderExecutionRequest,
    OrderFill,
    OrderStatus,
    valkey_decode,
    valkey_encode,
)


class TestDecodeOrder:
    def test_decode_string_payload(self):
        payload = {
            "asset": "BTCUSDT",
            "side": "buy",
            "size": "0.1",
            "order_type": "market",
            "timestamp": "1700000000.0",
            "requested_price": "50000.0",
            "idempotency_key": "test-key-1",
            "stop_loss_price": "48000.0",
            "take_profit_price": "55000.0",
        }

        order = ExecutionWorker._decode_order(payload)

        assert isinstance(order, OrderExecutionRequest)
        assert order.asset == "BTCUSDT"
        assert order.side == "buy"
        assert order.size == 0.1
        assert order.requested_price == 50000.0
        assert order.stop_loss_price == 48000.0
        assert order.take_profit_price == 55000.0

    def test_decode_bytes_payload(self):
        payload = {
            b"asset": b"ETHUSDT",
            b"side": b"sell",
            b"size": b"2.5",
            b"order_type": b"market",
            b"timestamp": b"1700000000.0",
            b"requested_price": b"3000.0",
            b"idempotency_key": b"test-key-2",
            b"stop_loss_price": b"None",
            b"take_profit_price": b"None",
        }

        order = ExecutionWorker._decode_order(payload)

        assert order.asset == "ETHUSDT"
        assert order.side == "sell"
        assert order.size == 2.5
        assert order.stop_loss_price is None
        assert order.take_profit_price is None

    def test_decode_missing_optional_fields(self):
        payload = {
            "asset": "SOLUSDT",
            "side": "buy",
            "size": "10.0",
            "timestamp": "1700000000.0",
            "requested_price": "100.0",
            "idempotency_key": "test-key-3",
        }

        order = ExecutionWorker._decode_order(payload)

        assert order.asset == "SOLUSDT"
        assert order.order_type == "market"
        assert order.stop_loss_price is None
        assert order.take_profit_price is None


# ------------------------------------------------------------------
# Encode / decode round-trip
# ------------------------------------------------------------------


class TestEncodeDecodeRoundtrip:
    def test_encode_decode_roundtrip(self) -> None:
        """ExecutionReport survives _encode_report → _decode_order cycle for key fields."""
        report = ExecutionReport(
            order_id="ord-rt",
            idempotency_key="idem-rt",
            asset="BTCUSDT",
            side="buy",
            requested_size=0.1,
            filled_size=0.1,
            requested_price=50_000.0,
            average_fill_price=50_010.0,
            status=OrderStatus.FILLED,
            fills=[
                OrderFill(
                    fill_id="f1",
                    asset="BTCUSDT",
                    side="buy",
                    size=0.1,
                    fill_price=50_010.0,
                    timestamp=1_700_000_000.0,
                ),
            ],
            slippage_bps=2.0,
            stop_loss_price=48_000.0,
            take_profit_price=55_000.0,
            timestamp=1_700_000_000.0,
            metadata={"source": "paper"},
        )
        encoded = ExecutionWorker._encode_report(report)
        assert all(isinstance(v, str) for v in encoded.values())

        decoded = valkey_decode(encoded, ExecutionReport)
        assert decoded.order_id == report.order_id
        assert decoded.asset == report.asset
        assert decoded.status == report.status
        assert decoded.average_fill_price == pytest.approx(report.average_fill_price)
        assert decoded.stop_loss_price == pytest.approx(report.stop_loss_price)
        assert decoded.metadata == report.metadata


# ------------------------------------------------------------------
# process_message publishes fill
# ------------------------------------------------------------------


class TestProcessMessagePublishesFill:
    @pytest.mark.asyncio
    async def test_process_message_publishes_fill(self) -> None:
        """process_message should call xadd on fills:{asset} stream."""
        report = ExecutionReport(
            order_id="ord-pm",
            idempotency_key="idem-pm",
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

        mock_order_manager = AsyncMock()
        mock_order_manager.process_order.return_value = report

        worker = ExecutionWorker(
            asset="BTCUSDT",
            order_manager=mock_order_manager,
            exec_config={},
        )
        worker.redis_client = AsyncMock()

        payload = valkey_encode(
            OrderExecutionRequest(
                asset="BTCUSDT",
                side="buy",
                size=0.1,
                timestamp=1_700_000_000.0,
                requested_price=50_000.0,
                idempotency_key="test-key",
            )
        )

        await worker.process_message("msg-1", payload)

        mock_order_manager.process_order.assert_called_once()
        worker.redis_client.xadd.assert_called_once()
        call_args = worker.redis_client.xadd.call_args
        assert call_args[0][0] == "fills:BTCUSDT"
