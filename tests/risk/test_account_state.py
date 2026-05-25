"""Tests for AccountState."""

import pytest

from libs.contracts.schemas import PositionState
from libs.risk.account_state import AccountState


class TestAccountStateBasics:
    def test_initial_state(self):
        state = AccountState(10_000)
        assert state.equity == 10_000
        assert state.balance == 10_000
        assert state.current_drawdown_pct == 0.0
        assert state.daily_pnl == 0.0
        assert state.realized_pnl == 0.0

    def test_equity_with_realized_pnl(self):
        state = AccountState(10_000)
        state.realized_pnl = 500
        assert state.balance == 10_500
        assert state.equity == 10_500

    def test_equity_with_unrealized_pnl(self):
        state = AccountState(10_000)
        state.unrealized_pnl = 200
        assert state.balance == 10_000
        assert state.equity == 10_200


class TestRecordTradeClose:
    def test_records_pnl(self):
        state = AccountState(10_000)
        state.record_trade_close(500, 1_000_000)
        assert state.realized_pnl == 500
        assert state.daily_pnl == 500
        assert state.last_trade_pnl == 500
        assert state.last_trade_timestamp == 1_000_000

    def test_negative_pnl(self):
        state = AccountState(10_000)
        state.record_trade_close(-300, 1_000_000)
        assert state.realized_pnl == -300
        assert state.daily_pnl == -300
        assert state.last_trade_pnl == -300

    def test_peak_equity_updates_on_profit(self):
        state = AccountState(10_000)
        state.record_trade_close(500, 1_000_000)
        assert state.peak_equity == 10_500


class TestDrawdown:
    def test_drawdown_after_loss(self):
        state = AccountState(10_000)
        state.peak_equity = 10_000
        state.realized_pnl = -1_000
        # equity = 9000, peak = 10000, dd = 10%
        assert state.current_drawdown_pct == pytest.approx(10.0)

    def test_no_drawdown_at_peak(self):
        state = AccountState(10_000)
        assert state.current_drawdown_pct == 0.0


class TestDailyReset:
    def test_resets_on_new_day(self):
        state = AccountState(10_000)
        state.daily_pnl = -500
        state.daily_reset_timestamp = 86_400 * 100  # day 100

        # New day
        state.check_daily_reset(86_400 * 101)
        assert state.daily_pnl == 0.0

    def test_no_reset_same_day(self):
        state = AccountState(10_000)
        state.daily_pnl = -500
        state.daily_reset_timestamp = 86_400 * 100

        # Same day (a few hours later)
        state.check_daily_reset(86_400 * 100 + 3600)
        assert state.daily_pnl == -500


class TestUpdateUnrealized:
    def test_updates_from_positions(self):
        state = AccountState(10_000)
        positions = [
            PositionState(
                asset="BTCUSDT", direction=1, entry_price=50_000,
                current_price=51_000, size=1, unrealized_pnl=1_000,
                entry_timestamp=0, source_model="m", source_timeframe="1h",
            ),
            PositionState(
                asset="ETHUSDT", direction=-1, entry_price=3_000,
                current_price=2_900, size=1, unrealized_pnl=100,
                entry_timestamp=0, source_model="m", source_timeframe="1h",
            ),
        ]
        state.update_unrealized(positions)
        assert state.unrealized_pnl == 1_100
        assert state.equity == 11_100


class TestSnapshot:
    def test_snapshot_fields(self):
        state = AccountState(10_000)
        state.realized_pnl = 200
        state.daily_pnl = 50
        snap = state.snapshot()
        assert snap.balance == 10_200
        assert snap.equity == 10_200
        assert snap.daily_pnl == 50
        assert snap.drawdown_pct == 0.0
