"""Tests for PositionTracker."""

import pytest

from libs.contracts.schemas import PositionState
from libs.risk.position_tracker import PositionTracker


def _make_position(**overrides) -> PositionState:
    defaults = dict(
        asset="BTCUSDT",
        direction=1,
        entry_price=50_000,
        current_price=50_000,
        size=0.1,
        unrealized_pnl=0.0,
        entry_timestamp=1_000_000,
        source_model="test_model",
        source_timeframe="1h",
        stop_loss_price=None,
        take_profit_price=None,
        trailing_stop_distance=None,
    )
    defaults.update(overrides)
    return PositionState(**defaults)


class TestOpenClose:
    @pytest.mark.asyncio
    async def test_open_position(self):
        tracker = PositionTracker()
        pos = _make_position()
        await tracker.open_position(pos)
        assert tracker.get_position_count() == 1

    @pytest.mark.asyncio
    async def test_close_position_returns_pnl(self):
        tracker = PositionTracker()
        pos = _make_position(unrealized_pnl=100)
        await tracker.open_position(pos)
        pnl = await tracker.close_position("BTCUSDT", 0)
        assert pnl == 100
        assert tracker.get_position_count() == 0

    @pytest.mark.asyncio
    async def test_close_invalid_index_raises(self):
        tracker = PositionTracker()
        with pytest.raises(IndexError):
            await tracker.close_position("BTCUSDT", 0)


class TestPriceUpdates:
    @pytest.mark.asyncio
    async def test_update_prices(self):
        tracker = PositionTracker()
        pos = _make_position(direction=1, entry_price=50_000, size=0.1)
        await tracker.open_position(pos)
        tracker.update_prices("BTCUSDT", 51_000)

        updated = tracker.positions["BTCUSDT"][0]
        assert updated.current_price == 51_000
        # unrealized = 1 * (51000 - 50000) * 0.1 = 100
        assert updated.unrealized_pnl == pytest.approx(100.0)


class TestTrailingStop:
    @pytest.mark.asyncio
    async def test_trailing_stop_moves_up_for_long(self):
        tracker = PositionTracker()
        pos = _make_position(
            direction=1,
            stop_loss_price=49_000,
            trailing_stop_distance=1_000,
        )
        await tracker.open_position(pos)

        # Price moves up: new SL = 52000 - 1000 = 51000 > 49000
        tracker.update_trailing_stops("BTCUSDT", 52_000)
        assert tracker.positions["BTCUSDT"][0].stop_loss_price == 51_000

    @pytest.mark.asyncio
    async def test_trailing_stop_does_not_move_down_for_long(self):
        tracker = PositionTracker()
        pos = _make_position(
            direction=1,
            stop_loss_price=49_000,
            trailing_stop_distance=1_000,
        )
        await tracker.open_position(pos)

        # Price moves down: new SL = 48000 - 1000 = 47000 < 49000 → no change
        tracker.update_trailing_stops("BTCUSDT", 48_000)
        assert tracker.positions["BTCUSDT"][0].stop_loss_price == 49_000

    @pytest.mark.asyncio
    async def test_trailing_stop_moves_down_for_short(self):
        tracker = PositionTracker()
        pos = _make_position(
            direction=-1,
            entry_price=50_000,
            stop_loss_price=51_000,
            trailing_stop_distance=1_000,
        )
        await tracker.open_position(pos)

        # Price moves down: new SL = 48000 + 1000 = 49000 < 51000
        tracker.update_trailing_stops("BTCUSDT", 48_000)
        assert tracker.positions["BTCUSDT"][0].stop_loss_price == 49_000


class TestSLTPCheck:
    @pytest.mark.asyncio
    async def test_sl_hit_long(self):
        tracker = PositionTracker()
        pos = _make_position(direction=1, stop_loss_price=49_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp("BTCUSDT", 48_500)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_tp_hit_long(self):
        tracker = PositionTracker()
        pos = _make_position(direction=1, take_profit_price=52_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp("BTCUSDT", 52_500)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_sl_hit_short(self):
        tracker = PositionTracker()
        pos = _make_position(direction=-1, stop_loss_price=51_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp("BTCUSDT", 51_500)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_tp_hit_short(self):
        tracker = PositionTracker()
        pos = _make_position(direction=-1, take_profit_price=48_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp("BTCUSDT", 47_500)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_no_hit(self):
        tracker = PositionTracker()
        pos = _make_position(
            direction=1, stop_loss_price=49_000, take_profit_price=52_000,
        )
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp("BTCUSDT", 50_500)
        assert len(hit) == 0


class TestExposure:
    @pytest.mark.asyncio
    async def test_total_exposure(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_position(size=0.1, current_price=50_000))
        await tracker.open_position(
            _make_position(asset="ETHUSDT", size=1, current_price=3_000),
        )
        # 0.1 * 50000 + 1 * 3000 = 8000
        assert tracker.get_total_exposure() == pytest.approx(8_000.0)

    @pytest.mark.asyncio
    async def test_asset_exposure(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_position(size=0.1, current_price=50_000))
        assert tracker.get_asset_exposure("BTCUSDT") == pytest.approx(5_000.0)

    @pytest.mark.asyncio
    async def test_all_positions(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_position())
        await tracker.open_position(_make_position(asset="ETHUSDT"))
        assert len(tracker.all_positions()) == 2
