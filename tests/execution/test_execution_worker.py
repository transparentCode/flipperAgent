"""Tests for ExecutionWorker — decode_order helper."""

from __future__ import annotations

import pytest

from apps.execution_app.execution_worker import ExecutionWorker
from libs.contracts.schemas import OrderExecutionRequest


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
