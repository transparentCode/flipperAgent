"""Tests for FillTracker — record fills, slippage, fill history."""

from __future__ import annotations

import pytest

from libs.contracts.schemas import ExecutionReport, OrderStatus
from libs.execution.fill_tracker import FillTracker


def _make_report(
    asset: str = "BTCUSDT",
    slippage_bps: float = 5.0,
    status: OrderStatus = OrderStatus.FILLED,
) -> ExecutionReport:
    return ExecutionReport(
        order_id=f"order-{asset}-{slippage_bps}",
        idempotency_key=f"key-{asset}-{slippage_bps}",
        asset=asset,
        side="buy",
        requested_size=1.0,
        filled_size=1.0,
        requested_price=50000.0,
        average_fill_price=50000.0 * (1 + slippage_bps / 10_000),
        status=status,
        slippage_bps=slippage_bps,
        timestamp=1700000000.0,
    )


class TestFillTrackerRecord:
    def test_record_fill(self):
        tracker = FillTracker()
        report = _make_report()
        tracker.record_fill(report)

        history = tracker.get_fill_history()
        assert len(history) == 1
        assert history[0].order_id == report.order_id

    def test_rejected_fill_not_in_slippage(self):
        tracker = FillTracker()
        report = _make_report(status=OrderStatus.REJECTED, slippage_bps=0.0)
        tracker.record_fill(report)

        assert tracker.get_average_slippage_bps() == 0.0


class TestFillTrackerSlippage:
    def test_average_slippage_single(self):
        tracker = FillTracker()
        tracker.record_fill(_make_report(slippage_bps=3.0))

        assert tracker.get_average_slippage_bps() == 3.0

    def test_average_slippage_multiple(self):
        tracker = FillTracker()
        tracker.record_fill(_make_report(slippage_bps=2.0))
        tracker.record_fill(_make_report(slippage_bps=4.0))

        assert tracker.get_average_slippage_bps() == pytest.approx(3.0)

    def test_average_slippage_by_asset(self):
        tracker = FillTracker()
        tracker.record_fill(_make_report(asset="BTCUSDT", slippage_bps=2.0))
        tracker.record_fill(_make_report(asset="ETHUSDT", slippage_bps=6.0))

        assert tracker.get_average_slippage_bps("BTCUSDT") == 2.0
        assert tracker.get_average_slippage_bps("ETHUSDT") == 6.0


class TestFillTrackerHistory:
    def test_fill_history_retrieval(self):
        tracker = FillTracker()
        for i in range(5):
            tracker.record_fill(_make_report(slippage_bps=float(i)))

        history = tracker.get_fill_history(limit=3)
        assert len(history) == 3

    def test_fill_history_by_asset(self):
        tracker = FillTracker()
        tracker.record_fill(_make_report(asset="BTCUSDT"))
        tracker.record_fill(_make_report(asset="ETHUSDT"))
        tracker.record_fill(_make_report(asset="BTCUSDT", slippage_bps=10.0))

        btc_history = tracker.get_fill_history(asset="BTCUSDT")
        assert len(btc_history) == 2

    def test_empty_history(self):
        tracker = FillTracker()

        assert tracker.get_fill_history() == []
        assert tracker.get_average_slippage_bps() == 0.0
