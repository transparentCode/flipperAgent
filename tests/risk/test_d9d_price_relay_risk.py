"""D9D risk-side price continuity and replay safety regressions."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.risk_app.risk_worker import RiskWorker
from libs.contracts.schemas import (
    OrderExecutionRequest,
    PositionState,
    PriceUpdate,
    valkey_decode,
    valkey_encode,
)
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.mtf.aggregator import SignalAggregator
from libs.risk.position_tracker import PositionTracker

BAR_OPEN_SECONDS = 1_700_000_000.0
BAR_OPEN_MS = int(BAR_OPEN_SECONDS * 1000)
BAR_CLOSE_SECONDS = BAR_OPEN_SECONDS + 3_600


def _worker() -> RiskWorker:
    return RiskWorker(
        asset="BTCUSDT",
        timeframes=["1h"],
        risk_engine=MagicMock(spec=RiskEngine),
        signal_aggregator=MagicMock(spec=SignalAggregator),
        account=AccountState(initial_balance=10_000.0),
        positions=PositionTracker(),
        risk_config={},
    )


def _payload(*, timeframe: str = "1h", high: float = 101.0, low: float = 90.0) -> dict:
    return valkey_encode(
        PriceUpdate(
            asset="BTCUSDT",
            timeframe=timeframe,
            timestamp=BAR_OPEN_MS,
            open=100.0,
            high=high,
            low=low,
            close=92.0,
            volume=10.0,
        )
    )


def _position(*, entry_timestamp: float) -> PositionState:
    return PositionState(
        asset="BTCUSDT",
        direction=1,
        entry_price=100.0,
        current_price=100.0,
        size=1.0,
        unrealized_pnl=0.0,
        entry_timestamp=entry_timestamp,
        source_model="test",
        source_timeframe="1h",
        stop_loss_price=95.0,
        take_profit_price=110.0,
    )


@pytest.mark.asyncio
async def test_price_exit_uses_bar_close_seconds_and_bar_open_ms_identity() -> None:
    worker = _worker()
    worker.redis_client = AsyncMock()
    position = _position(entry_timestamp=BAR_OPEN_SECONDS - 10)
    worker.positions.positions["BTCUSDT"].append(position)

    await worker._process_price_update(_payload())

    order_payload = worker.redis_client.xadd.call_args.args[1]
    order = valkey_decode(order_payload, OrderExecutionRequest)
    assert order.timestamp == BAR_CLOSE_SECONDS
    assert position.pending_close_requested_at == BAR_CLOSE_SECONDS
    assert str(BAR_OPEN_MS) in order.idempotency_key


@pytest.mark.asyncio
async def test_pre_entry_closed_bar_does_not_update_or_exit_position() -> None:
    worker = _worker()
    worker.redis_client = AsyncMock()
    position = _position(entry_timestamp=BAR_CLOSE_SECONDS)
    worker.positions.positions["BTCUSDT"].append(position)

    await worker._process_price_update(_payload())

    assert worker.redis_client.xadd.await_count == 0
    assert position.current_price == 100.0
    assert position.unrealized_pnl == 0.0


@pytest.mark.asyncio
async def test_entry_inside_bar_retains_existing_hl_exit_semantics() -> None:
    worker = _worker()
    worker.redis_client = AsyncMock()
    position = _position(entry_timestamp=BAR_OPEN_SECONDS + 1_800)
    worker.positions.positions["BTCUSDT"].append(position)

    await worker._process_price_update(_payload())

    assert worker.redis_client.xadd.await_count == 1
    assert position.pending_close_reason == "sl"


@pytest.mark.asyncio
async def test_invalid_price_timeframe_fails_closed() -> None:
    worker = _worker()
    worker.redis_client = AsyncMock()

    with pytest.raises(ValueError, match="invalid price-update timeframe"):
        await worker._process_price_update(_payload(timeframe="not-a-timeframe"))


@pytest.mark.asyncio
async def test_price_pel_reclaim_processes_then_acknowledges_successfully() -> None:
    worker = _worker()
    worker.redis_client = AsyncMock()
    message = ("1700003600000-0", _payload())
    worker.redis_client.xautoclaim = AsyncMock(
        side_effect=[("0-0", [message], []), ("0-0", [], [])]
    )
    worker._process_price_update = AsyncMock()

    await worker._drain_price_pel()

    worker._process_price_update.assert_awaited_once_with(message[1])
    worker.redis_client.xack.assert_awaited_once_with(
        "price_update:BTCUSDT:1h",
        "risk_app_price_group",
        message[0],
    )


@pytest.mark.asyncio
async def test_price_pel_processing_failure_leaves_message_pending() -> None:
    worker = _worker()
    worker.redis_client = AsyncMock()
    message = ("1700003600000-0", _payload())
    worker.redis_client.xautoclaim = AsyncMock(
        side_effect=[("0-0", [message], []), ("0-0", [], [])]
    )
    worker._process_price_update = AsyncMock(side_effect=RuntimeError("retry"))

    await worker._drain_price_pel()

    worker.redis_client.xack.assert_not_awaited()


@pytest.mark.asyncio
async def test_risk_startup_drains_signal_then_price_pel_before_live_reads() -> None:
    worker = _worker()
    worker.redis_client = AsyncMock()
    order: list[str] = []
    worker._drain_signal_pel = AsyncMock(side_effect=lambda: order.append("signal"))
    worker._drain_price_pel = AsyncMock(side_effect=lambda: order.append("price"))
    worker.redis_client.xreadgroup = AsyncMock(side_effect=asyncio.CancelledError)

    await worker.run()

    assert order == ["signal", "price"]
    worker.redis_client.xreadgroup.assert_awaited_once()


@pytest.mark.asyncio
async def test_reclaimed_sl_price_emits_one_close_and_pending_close_blocks_retry() -> (
    None
):
    worker = _worker()
    worker.redis_client = AsyncMock()
    position = _position(entry_timestamp=BAR_OPEN_SECONDS - 10)
    worker.positions.positions["BTCUSDT"].append(position)
    message = ("1700003600000-0", _payload())
    worker.redis_client.xautoclaim = AsyncMock(
        side_effect=[
            ("0-0", [message], []),
            ("0-0", [message], []),
        ]
    )

    await worker._drain_price_pel()
    await worker._drain_price_pel()

    assert worker.redis_client.xadd.await_count == 1
    assert worker.redis_client.xack.await_count == 2
    assert position.pending_close_reason == "sl"
