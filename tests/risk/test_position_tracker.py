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

    @pytest.mark.asyncio
    async def test_pending_close_position_skipped(self):
        tracker = PositionTracker()
        pos = _make_position(direction=1, stop_loss_price=49_000, pending_close_reason="sl")
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp("BTCUSDT", 48_500)
        assert hit == []


class TestSLTPCheckHLC:
    """Tests for check_sl_tp_hlc — intrabar high/low SL/TP detection."""

    @pytest.mark.asyncio
    async def test_long_sl_hit_via_low(self):
        """Long SL hit when low <= SL but close > SL (wick stop)."""
        tracker = PositionTracker()
        pos = _make_position(direction=1, stop_loss_price=49_000)
        await tracker.open_position(pos)

        # Low pierces SL, close recovers above it
        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=50_500, low=48_800, close=50_000)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_long_tp_hit_via_high(self):
        """Long TP hit when high >= TP but close < TP."""
        tracker = PositionTracker()
        pos = _make_position(direction=1, take_profit_price=52_000)
        await tracker.open_position(pos)

        # High touches TP, close falls back
        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=52_100, low=50_500, close=51_500)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_short_sl_hit_via_high(self):
        """Short SL hit when high >= SL."""
        tracker = PositionTracker()
        pos = _make_position(direction=-1, entry_price=50_000, stop_loss_price=51_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=51_200, low=49_500, close=50_000)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_short_tp_hit_via_low(self):
        """Short TP hit when low <= TP."""
        tracker = PositionTracker()
        pos = _make_position(direction=-1, entry_price=50_000, take_profit_price=48_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=50_500, low=47_800, close=49_000)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_no_hit_within_bands(self):
        """No hit when high/low stay within SL/TP bands."""
        tracker = PositionTracker()
        pos = _make_position(
            direction=1, stop_loss_price=49_000, take_profit_price=52_000,
        )
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=51_500, low=49_500, close=50_500)
        assert len(hit) == 0

    @pytest.mark.asyncio
    async def test_both_sl_tp_hit_same_bar_tp_priority(self):
        """When both SL and TP are hit on same bar, position is still returned (TP priority)."""
        tracker = PositionTracker()
        pos = _make_position(
            direction=1, stop_loss_price=49_000, take_profit_price=52_000,
        )
        await tracker.open_position(pos)

        # Wide bar: low pierces SL, high pierces TP
        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=52_500, low=48_500, close=50_500)
        assert len(hit) == 1  # Position included — caller handles TP priority

    @pytest.mark.asyncio
    async def test_hlc_does_not_trigger_without_sl_tp(self):
        """Position with no SL/TP set is never hit."""
        tracker = PositionTracker()
        pos = _make_position(direction=1)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=99_000, low=1_000, close=50_000)
        assert len(hit) == 0

    @pytest.mark.asyncio
    async def test_exact_sl_boundary_long(self):
        """Long SL hit when low == SL exactly."""
        tracker = PositionTracker()
        pos = _make_position(direction=1, stop_loss_price=49_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=50_500, low=49_000, close=50_000)
        assert len(hit) == 1

    @pytest.mark.asyncio
    async def test_exact_tp_boundary_long(self):
        """Long TP hit when high == TP exactly."""
        tracker = PositionTracker()
        pos = _make_position(direction=1, take_profit_price=52_000)
        await tracker.open_position(pos)

        hit = tracker.check_sl_tp_hlc("BTCUSDT", high=52_000, low=50_000, close=51_000)
        assert len(hit) == 1


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


# ---------------------------------------------------------------
# Multi-TP partial exit tests
# ---------------------------------------------------------------


def _make_multi_tp_position(**overrides) -> PositionState:
    """Helper: creates a position with multi-TP fields populated."""
    defaults = dict(
        asset="BTCUSDT",
        direction=1,
        entry_price=100.0,
        current_price=100.0,
        size=1.0,
        original_size=1.0,
        unrealized_pnl=0.0,
        entry_timestamp=1_000_000,
        source_model="test",
        source_timeframe="1h",
        stop_loss_price=98.0,
        tp_levels=[101.5, 103.0, 105.0],
        tp_portions=[0.4, 0.3, 0.3],
        tp_levels_hit=[False, False, False],
        trail_to_breakeven=True,
    )
    defaults.update(overrides)
    return PositionState(**defaults)


class TestCheckSlTpHlcMulti:
    """Tests for check_sl_tp_hlc_multi()."""

    @pytest.mark.asyncio
    async def test_no_tp_levels_skipped(self):
        """Positions without tp_levels are ignored by multi check."""
        tracker = PositionTracker()
        await tracker.open_position(_make_position(
            stop_loss_price=49_000, take_profit_price=52_000,
        ))
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 53_000, 49_500, 52_500)
        assert results == []

    @pytest.mark.asyncio
    async def test_tp1_hit_long(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_multi_tp_position())
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 102.0, 99.5, 101.5)
        assert len(results) == 1
        pos, reason, size = results[0]
        assert reason == "tp1"
        assert size == pytest.approx(0.4)

    @pytest.mark.asyncio
    async def test_tp2_hit_after_tp1_already_hit(self):
        tracker = PositionTracker()
        pos = _make_multi_tp_position(
            tp_levels_hit=[True, False, False],
            size=0.6,
        )
        await tracker.open_position(pos)
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 103.5, 100.0, 103.0)
        assert len(results) == 1
        _, reason, size = results[0]
        assert reason == "tp2"
        assert size == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_tp3_hit_long(self):
        tracker = PositionTracker()
        pos = _make_multi_tp_position(
            tp_levels_hit=[True, True, False],
            size=0.3,
        )
        await tracker.open_position(pos)
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 106.0, 100.0, 105.0)
        assert len(results) == 1
        _, reason, size = results[0]
        assert reason == "tp3"
        assert size == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_only_one_tp_per_bar(self):
        """Even if bar high exceeds TP2, only TP1 fires if unhit."""
        tracker = PositionTracker()
        await tracker.open_position(_make_multi_tp_position())
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 110.0, 99.0, 105.0)
        assert len(results) == 1
        _, reason, _ = results[0]
        assert reason == "tp1"

    @pytest.mark.asyncio
    async def test_sl_hit_when_no_tp_fires(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_multi_tp_position())
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 100.5, 97.5, 98.0)
        assert len(results) == 1
        _, reason, size = results[0]
        assert reason == "sl"
        assert size == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_tp_priority_over_sl(self):
        """When bar covers both TP1 and SL, TP fires (SL suppressed)."""
        tracker = PositionTracker()
        await tracker.open_position(_make_multi_tp_position())
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 102.0, 97.5, 100.0)
        assert len(results) == 1
        _, reason, _ = results[0]
        assert reason == "tp1"

    @pytest.mark.asyncio
    async def test_sl_after_breakeven_trail(self):
        """SL at entry after trail-to-breakeven — only triggers if low <= entry."""
        tracker = PositionTracker()
        pos = _make_multi_tp_position(
            tp_levels_hit=[True, False, False],
            size=0.6,
            stop_loss_price=100.0,  # trailed to entry
        )
        await tracker.open_position(pos)
        # Low touches entry exactly
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 101.0, 100.0, 100.5)
        assert len(results) == 1
        _, reason, size = results[0]
        assert reason == "sl"
        assert size == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_short_tp_hit(self):
        tracker = PositionTracker()
        pos = _make_multi_tp_position(
            direction=-1,
            entry_price=100.0,
            stop_loss_price=102.0,
            tp_levels=[98.5, 97.0, 95.0],
        )
        await tracker.open_position(pos)
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 100.0, 98.0, 98.5)
        assert len(results) == 1
        _, reason, _ = results[0]
        assert reason == "tp1"

    @pytest.mark.asyncio
    async def test_no_hit(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_multi_tp_position())
        results = tracker.check_sl_tp_hlc_multi("BTCUSDT", 101.0, 99.0, 100.5)
        assert results == []


class TestApplyPartialExit:
    """Tests for apply_partial_exit()."""

    @pytest.mark.asyncio
    async def test_basic_partial_exit(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_multi_tp_position())
        tracker.apply_partial_exit("BTCUSDT", 0, 0.4, 0)
        pos = tracker.positions["BTCUSDT"][0]
        assert pos.size == pytest.approx(0.6)
        assert pos.tp_levels_hit[0] is True
        assert pos.tp_levels_hit[1] is False

    @pytest.mark.asyncio
    async def test_trail_to_breakeven_on_tp1(self):
        tracker = PositionTracker()
        pos = _make_multi_tp_position(stop_loss_price=98.0)
        await tracker.open_position(pos)
        tracker.apply_partial_exit("BTCUSDT", 0, 0.4, 0)
        pos = tracker.positions["BTCUSDT"][0]
        assert pos.stop_loss_price == pytest.approx(100.0)  # entry
        assert pos.original_stop_loss == pytest.approx(98.0)

    @pytest.mark.asyncio
    async def test_no_trail_on_tp2(self):
        tracker = PositionTracker()
        pos = _make_multi_tp_position(
            tp_levels_hit=[True, False, False],
            size=0.6,
            stop_loss_price=100.0,  # already at entry
        )
        await tracker.open_position(pos)
        tracker.apply_partial_exit("BTCUSDT", 0, 0.3, 1)
        pos = tracker.positions["BTCUSDT"][0]
        assert pos.stop_loss_price == pytest.approx(100.0)  # unchanged
        assert pos.size == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_no_trail_when_disabled(self):
        tracker = PositionTracker()
        pos = _make_multi_tp_position(trail_to_breakeven=False, stop_loss_price=98.0)
        await tracker.open_position(pos)
        tracker.apply_partial_exit("BTCUSDT", 0, 0.4, 0)
        pos = tracker.positions["BTCUSDT"][0]
        assert pos.stop_loss_price == pytest.approx(98.0)  # unchanged

    @pytest.mark.asyncio
    async def test_full_close_removes_position(self):
        tracker = PositionTracker()
        pos = _make_multi_tp_position(
            tp_levels_hit=[True, True, False],
            size=0.3,
        )
        await tracker.open_position(pos)
        tracker.apply_partial_exit("BTCUSDT", 0, 0.3, 2)
        assert len(tracker.positions["BTCUSDT"]) == 0

    @pytest.mark.asyncio
    async def test_invalid_index_raises(self):
        tracker = PositionTracker()
        await tracker.open_position(_make_multi_tp_position())
        with pytest.raises(IndexError):
            tracker.apply_partial_exit("BTCUSDT", 5, 0.4, 0)
