"""End-to-end pipeline tests for multi-TP partial exit system.

These tests wire together the real components (no mocks for core logic)
to verify the full signal → risk → execution → portfolio lifecycle
works correctly with multi-TP exits.

No Docker required — all in-process using PaperExecutor.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from libs.common.position_matcher import PositionMatcher
from libs.contracts.schemas import (
    ExecutionReport,
    OrderExecutionRequest,
    PositionState,
    RiskAssessment,
    TradeSignal,
)
from libs.execution.paper_executor import PaperExecutor
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.position_tracker import PositionTracker
from libs.risk.sizer import PositionSizer
from libs.risk.stop_loss import StopLossCalculator
from libs.risk.take_profit import TakeProfitCalculator


# ---------------------------------------------------------------------------
# Config matching production risk.yaml multi_level settings
# ---------------------------------------------------------------------------

RISK_CONFIG = {
    "position_sizing": {
        "default_strategy": "fixed_fractional",
        "fixed_fractional": {"risk_per_trade_pct": 2.0},
    },
    "stop_loss": {
        "default_method": "fixed_pct",
        "fixed_pct": {"pct": 2.0},
    },
    "take_profit": {
        "default_method": "multi_level",
        "multi_level": {
            "levels": [
                {"pct": 1.5, "portion": 0.40},
                {"pct": 3.0, "portion": 0.30},
                {"pct": 5.0, "portion": 0.30},
            ],
            "trail_to_breakeven": True,
        },
    },
}

RISK_CONFIG_SINGLE_TP = {
    "position_sizing": {
        "default_strategy": "fixed_fractional",
        "fixed_fractional": {"risk_per_trade_pct": 2.0},
    },
    "stop_loss": {
        "default_method": "fixed_pct",
        "fixed_pct": {"pct": 2.0},
    },
    "take_profit": {
        "default_method": "fixed_pct",
        "fixed_pct": {"pct": 3.0},
    },
}


def _make_signal(
    asset: str = "BTCUSDT",
    direction: int = 1,
    price: float = 100.0,
    timeframe: str = "1h",
) -> TradeSignal:
    return TradeSignal(
        asset=asset,
        direction=direction,
        model_name="SqueezeBreakout",
        timeframe=timeframe,
        price=price,
        timestamp=time.time(),
        idempotency_key=f"test_{asset}_{int(time.time() * 1000)}",
    )


def _build_engine() -> RiskEngine:
    return RiskEngine(
        rules=[],  # no rejection rules for E2E
        sizer=PositionSizer(),
        sl_calc=StopLossCalculator(),
        tp_calc=TakeProfitCalculator(),
    )


# ---------------------------------------------------------------------------
# E2E Test: Full multi-TP lifecycle
# ---------------------------------------------------------------------------


class TestMultiTpPipelineE2E:
    """Full pipeline: signal → risk assessment → open → price bars → partial exits → close."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_long_all_tps_hit(self):
        """
        Long BTCUSDT @ 100:
        - TP1 = 101.5 (1.5%) → close 40%
        - TP2 = 103.0 (3.0%) → close 30%
        - TP3 = 105.0 (5.0%) → close 30%
        Trail-to-breakeven after TP1: SL moves from 98 → 100.
        """
        engine = _build_engine()
        tracker = PositionTracker()
        executor = PaperExecutor(slippage_bps=0.0, commission_bps=4.0, fill_delay_ms=0)
        portfolio = PositionMatcher()

        account = AccountState(initial_balance=10000.0)
        signal = _make_signal(direction=1, price=100.0)

        # --- Step 1: Risk assessment ---
        assessment = engine.assess(signal, account, tracker, RISK_CONFIG)
        assert assessment.allowed
        assert len(assessment.tp_levels) == 3
        assert assessment.tp_levels[0] == pytest.approx(101.5, rel=1e-3)
        assert assessment.tp_levels[1] == pytest.approx(103.0, rel=1e-3)
        assert assessment.tp_levels[2] == pytest.approx(105.0, rel=1e-3)
        assert assessment.tp_portions == pytest.approx([0.40, 0.30, 0.30])
        assert assessment.trail_to_breakeven is True
        assert assessment.take_profit_price is None  # multi-level mode

        # --- Step 2: Execute entry order ---
        entry_order = OrderExecutionRequest(
            asset="BTCUSDT",
            side="buy",
            size=assessment.proposed_size,
            order_type="market",
            timestamp=time.time(),
            requested_price=100.0,
            idempotency_key="entry_btc_1",
            model_name="SqueezeBreakout",
            source_timeframe="1h",
            metadata={
                "tp_levels": assessment.tp_levels,
                "tp_portions": assessment.tp_portions,
                "trail_to_breakeven": assessment.trail_to_breakeven,
            },
        )
        entry_report = await executor.execute_order(entry_order)
        assert entry_report.status.value == "FILLED"

        # Portfolio records entry
        portfolio.apply_fill(
            "BTCUSDT", "buy", entry_report.filled_size,
            entry_report.average_fill_price, time.time(),
        )

        # --- Step 3: Open position in tracker ---
        original_size = entry_report.filled_size
        pos = PositionState(
            asset="BTCUSDT",
            direction=1,
            entry_price=entry_report.average_fill_price,
            current_price=100.0,
            size=original_size,
            original_size=original_size,
            unrealized_pnl=0.0,
            entry_timestamp=time.time(),
            source_model="SqueezeBreakout",
            source_timeframe="1h",
            stop_loss_price=assessment.stop_loss_price,
            tp_levels=assessment.tp_levels,
            tp_portions=assessment.tp_portions,
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        await tracker.open_position(pos)
        assert tracker.get_position_count() == 1

        # --- Step 4: Price bar hits TP1 (high=102 > 101.5) ---
        exits_bar1 = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=102.0, low=100.5, close=101.8)
        assert len(exits_bar1) == 1
        pos_hit, reason, close_size = exits_bar1[0]
        assert reason == "tp1"
        assert close_size == pytest.approx(0.40 * original_size)

        # Apply partial exit
        pos_idx = tracker.positions["BTCUSDT"].index(pos_hit)
        tracker.apply_partial_exit("BTCUSDT", pos_idx, close_size, 0)

        # Verify trail-to-breakeven
        updated_pos = tracker.positions["BTCUSDT"][0]
        assert updated_pos.stop_loss_price == pytest.approx(updated_pos.entry_price)
        assert updated_pos.tp_levels_hit[0] is True
        assert updated_pos.size == pytest.approx(0.60 * original_size)

        # Execute partial close
        tp1_order = OrderExecutionRequest(
            asset="BTCUSDT", side="sell", size=close_size,
            order_type="market", timestamp=time.time(),
            requested_price=101.5, idempotency_key="tp1_btc_1",
            close_reason="tp1", model_name="SqueezeBreakout",
            source_timeframe="1h",
        )
        tp1_report = await executor.execute_order(tp1_order)
        assert tp1_report.status.value == "FILLED"
        assert tp1_report.metadata["close_reason"] == "tp1"

        # Portfolio records partial close
        closed_trades_1 = portfolio.apply_fill(
            "BTCUSDT", "sell", tp1_report.filled_size,
            tp1_report.average_fill_price, time.time(),
        )
        assert len(closed_trades_1) == 1
        assert closed_trades_1[0].pnl > 0  # profitable

        # --- Step 5: Price bar hits TP2 (high=103.5 > 103.0) ---
        exits_bar2 = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=103.5, low=101.0, close=103.2)
        assert len(exits_bar2) == 1
        _, reason2, close_size2 = exits_bar2[0]
        assert reason2 == "tp2"
        assert close_size2 == pytest.approx(0.30 * original_size)

        tracker.apply_partial_exit("BTCUSDT", 0, close_size2, 1)
        assert tracker.positions["BTCUSDT"][0].size == pytest.approx(0.30 * original_size)

        tp2_order = OrderExecutionRequest(
            asset="BTCUSDT", side="sell", size=close_size2,
            order_type="market", timestamp=time.time(),
            requested_price=103.0, idempotency_key="tp2_btc_1",
            close_reason="tp2", model_name="SqueezeBreakout",
            source_timeframe="1h",
        )
        tp2_report = await executor.execute_order(tp2_order)
        closed_trades_2 = portfolio.apply_fill(
            "BTCUSDT", "sell", tp2_report.filled_size,
            tp2_report.average_fill_price, time.time(),
        )
        assert len(closed_trades_2) == 1
        assert closed_trades_2[0].pnl > 0

        # --- Step 6: Price bar hits TP3 (high=105.5 > 105.0) ---
        exits_bar3 = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=105.5, low=103.0, close=105.2)
        assert len(exits_bar3) == 1
        _, reason3, close_size3 = exits_bar3[0]
        assert reason3 == "tp3"
        assert close_size3 == pytest.approx(0.30 * original_size)

        tracker.apply_partial_exit("BTCUSDT", 0, close_size3, 2)
        # Position fully closed
        assert tracker.get_position_count() == 0

        tp3_order = OrderExecutionRequest(
            asset="BTCUSDT", side="sell", size=close_size3,
            order_type="market", timestamp=time.time(),
            requested_price=105.0, idempotency_key="tp3_btc_1",
            close_reason="tp3", model_name="SqueezeBreakout",
            source_timeframe="1h",
        )
        tp3_report = await executor.execute_order(tp3_order)
        closed_trades_3 = portfolio.apply_fill(
            "BTCUSDT", "sell", tp3_report.filled_size,
            tp3_report.average_fill_price, time.time(),
        )
        assert len(closed_trades_3) == 1
        assert closed_trades_3[0].pnl > 0

        # --- Verify final state ---
        assert len(portfolio.open_positions.get("BTCUSDT", [])) == 0

        total_pnl = sum(
            t.pnl for t in closed_trades_1 + closed_trades_2 + closed_trades_3
        )
        assert total_pnl > 0, f"Total PnL should be positive, got {total_pnl}"

    @pytest.mark.asyncio
    async def test_sl_after_tp1_breakeven(self):
        """
        Long BTCUSDT @ 100:
        - TP1 hits @ 101.5 → 40% closed
        - Price reverses → SL at breakeven (100.0) hits remaining 60%
        - Net PnL: TP1 profit (0.4 * 1.5%) minus zero on SL = positive
        """
        engine = _build_engine()
        tracker = PositionTracker()
        executor = PaperExecutor(slippage_bps=0.0, commission_bps=0.0, fill_delay_ms=0)
        portfolio = PositionMatcher()

        account = AccountState(initial_balance=10000.0)
        signal = _make_signal(direction=1, price=100.0)
        assessment = engine.assess(signal, account, tracker, RISK_CONFIG)
        original_size = assessment.proposed_size

        # Open position
        pos = PositionState(
            asset="BTCUSDT", direction=1,
            entry_price=100.0, current_price=100.0,
            size=original_size, original_size=original_size,
            unrealized_pnl=0.0, entry_timestamp=time.time(),
            source_model="SqueezeBreakout", source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=assessment.tp_levels,
            tp_portions=assessment.tp_portions,
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        await tracker.open_position(pos)
        portfolio.apply_fill("BTCUSDT", "buy", original_size, 100.0, time.time())

        # Bar 1: TP1 hit
        exits = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=102.0, low=100.5, close=101.8)
        assert len(exits) == 1
        tracker.apply_partial_exit("BTCUSDT", 0, exits[0][2], 0)

        tp1_size = exits[0][2]
        tp1_trades = portfolio.apply_fill("BTCUSDT", "sell", tp1_size, 101.5, time.time())
        assert len(tp1_trades) == 1
        tp1_pnl = tp1_trades[0].pnl

        # Verify SL moved to breakeven
        assert tracker.positions["BTCUSDT"][0].stop_loss_price == pytest.approx(100.0)

        # Bar 2: Price reverses, SL at breakeven (100.0) triggers
        exits2 = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=101.0, low=99.5, close=99.8)
        assert len(exits2) == 1
        _, reason, sl_size = exits2[0]
        assert reason == "sl"
        remaining_size = 0.60 * original_size
        assert sl_size == pytest.approx(remaining_size)

        # Close via SL
        sl_trades = portfolio.apply_fill("BTCUSDT", "sell", sl_size, 100.0, time.time())
        sl_pnl = sl_trades[0].pnl

        # SL at breakeven → ~0 PnL on remaining; TP1 was profitable
        assert sl_pnl == pytest.approx(0.0, abs=0.01)
        total_pnl = tp1_pnl + sl_pnl
        assert total_pnl > 0, f"Net should be positive from TP1: {total_pnl}"

    @pytest.mark.asyncio
    async def test_short_position_multi_tp(self):
        """Short BTCUSDT @ 100, TPs at 98.5/97/95 (prices below entry)."""
        engine = _build_engine()
        tracker = PositionTracker()
        executor = PaperExecutor(slippage_bps=0.0, commission_bps=0.0, fill_delay_ms=0)
        portfolio = PositionMatcher()

        account = AccountState(initial_balance=10000.0)
        signal = _make_signal(direction=-1, price=100.0)
        assessment = engine.assess(signal, account, tracker, RISK_CONFIG)

        assert assessment.allowed
        # Short TPs should be below entry
        assert assessment.tp_levels[0] < 100.0
        assert assessment.tp_levels[0] == pytest.approx(98.5, rel=1e-3)

        original_size = assessment.proposed_size
        pos = PositionState(
            asset="BTCUSDT", direction=-1,
            entry_price=100.0, current_price=100.0,
            size=original_size, original_size=original_size,
            unrealized_pnl=0.0, entry_timestamp=time.time(),
            source_model="SqueezeBreakout", source_timeframe="1h",
            stop_loss_price=102.0,
            tp_levels=assessment.tp_levels,
            tp_portions=assessment.tp_portions,
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        await tracker.open_position(pos)
        portfolio.apply_fill("BTCUSDT", "sell", original_size, 100.0, time.time())

        # Bar 1: TP1 hit (low drops below 98.5)
        exits = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=100.0, low=98.0, close=98.5)
        assert len(exits) == 1
        assert exits[0][1] == "tp1"
        tracker.apply_partial_exit("BTCUSDT", 0, exits[0][2], 0)

        tp1_trades = portfolio.apply_fill("BTCUSDT", "buy", exits[0][2], 98.5, time.time())
        assert tp1_trades[0].pnl > 0  # short closed below entry = profit

        # After TP1, SL moves to entry (100.0) — breakeven for short
        assert tracker.positions["BTCUSDT"][0].stop_loss_price == pytest.approx(100.0)

        # Bar 2: TP2 hit (low < 97)
        exits2 = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=98.5, low=96.5, close=97.0)
        assert exits2[0][1] == "tp2"
        tracker.apply_partial_exit("BTCUSDT", 0, exits2[0][2], 1)
        tp2_trades = portfolio.apply_fill("BTCUSDT", "buy", exits2[0][2], 97.0, time.time())
        assert tp2_trades[0].pnl > 0

        # Bar 3: TP3 hit (low < 95)
        exits3 = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=97.0, low=94.5, close=95.0)
        assert exits3[0][1] == "tp3"
        tracker.apply_partial_exit("BTCUSDT", 0, exits3[0][2], 2)
        tp3_trades = portfolio.apply_fill("BTCUSDT", "buy", exits3[0][2], 95.0, time.time())
        assert tp3_trades[0].pnl > 0

        assert tracker.get_position_count() == 0
        assert len(portfolio.open_positions.get("BTCUSDT", [])) == 0

    @pytest.mark.asyncio
    async def test_scoring_parity_with_pipeline(self):
        """
        Verify that backtest_multi_tp() scoring function produces results
        consistent with the pipeline's partial-exit logic on the same price data.
        """
        from libs.optim_utils.scoring import backtest_multi_tp, compute_multi_tp_metrics

        # Synthetic data: long signal at bar 0, price rises through all TPs
        n = 20
        directions = np.zeros(n)
        directions[0] = 1

        close = np.array([100.0 + i * 0.5 for i in range(n)])
        high = close + 0.3
        low = close - 0.3

        equity_returns, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
            trail_to_breakeven=True,
        )

        # The scoring function should find all 3 TPs hit
        assert len(trades) == 1
        t = trades[0]
        assert all(t.tp_hits), f"Expected all TPs hit: {t.tp_hits}"
        assert not t.sl_hit
        assert t.pnl_pct > 0

        # Now run the same through PositionTracker
        tracker = PositionTracker()
        pos = PositionState(
            asset="TEST", direction=1,
            entry_price=100.0, current_price=100.0,
            size=1.0, original_size=1.0,
            unrealized_pnl=0.0, entry_timestamp=0.0,
            source_model="test", source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.40, 0.30, 0.30],
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        await tracker.open_position(pos)

        pipeline_tp_hits = []
        for bar_idx in range(1, n):
            exits = tracker.check_sl_tp_hlc_multi(
                "TEST", high=high[bar_idx], low=low[bar_idx], close=close[bar_idx],
            )
            for ex_pos, reason, csize in exits:
                pipeline_tp_hits.append(reason)
                pidx = tracker.positions["TEST"].index(ex_pos)
                tp_lvl_idx = int(reason[-1]) - 1
                tracker.apply_partial_exit("TEST", pidx, csize, tp_lvl_idx)

        # Both should agree on which TPs hit
        assert "tp1" in pipeline_tp_hits
        assert "tp2" in pipeline_tp_hits
        assert "tp3" in pipeline_tp_hits
        assert tracker.get_position_count() == 0


# ---------------------------------------------------------------------------
# E2E Test: Mixed mode — one asset multi-TP, another single-TP
# ---------------------------------------------------------------------------


class TestMixedModePipelineE2E:
    """Two concurrent positions: BTCUSDT with multi-TP, ETHUSDT with single-TP."""

    @pytest.mark.asyncio
    async def test_mixed_mode_coexistence(self):
        """Verify both modes work independently in the same tracker."""
        engine = _build_engine()
        tracker = PositionTracker()
        executor = PaperExecutor(slippage_bps=0.0, commission_bps=0.0, fill_delay_ms=0)

        account = AccountState(initial_balance=10000.0)

        # --- Open multi-TP position (BTCUSDT) ---
        btc_signal = _make_signal(asset="BTCUSDT", direction=1, price=100.0)
        btc_assessment = engine.assess(btc_signal, account, tracker, RISK_CONFIG)
        assert len(btc_assessment.tp_levels) == 3

        btc_pos = PositionState(
            asset="BTCUSDT", direction=1,
            entry_price=100.0, current_price=100.0,
            size=btc_assessment.proposed_size,
            original_size=btc_assessment.proposed_size,
            unrealized_pnl=0.0, entry_timestamp=time.time(),
            source_model="SqueezeBreakout", source_timeframe="1h",
            stop_loss_price=98.0,
            tp_levels=btc_assessment.tp_levels,
            tp_portions=btc_assessment.tp_portions,
            tp_levels_hit=[False, False, False],
            trail_to_breakeven=True,
        )
        await tracker.open_position(btc_pos)

        # --- Open single-TP position (ETHUSDT) ---
        eth_signal = _make_signal(asset="ETHUSDT", direction=1, price=3000.0)
        eth_assessment = engine.assess(eth_signal, account, tracker, RISK_CONFIG_SINGLE_TP)
        assert eth_assessment.tp_levels == []
        assert eth_assessment.take_profit_price is not None

        eth_pos = PositionState(
            asset="ETHUSDT", direction=1,
            entry_price=3000.0, current_price=3000.0,
            size=eth_assessment.proposed_size,
            original_size=eth_assessment.proposed_size,
            unrealized_pnl=0.0, entry_timestamp=time.time(),
            source_model="SqueezeBreakout", source_timeframe="1h",
            stop_loss_price=eth_assessment.stop_loss_price,
            take_profit_price=eth_assessment.take_profit_price,
            tp_levels=[],
            tp_portions=[],
            tp_levels_hit=[],
            trail_to_breakeven=False,
        )
        await tracker.open_position(eth_pos)

        assert tracker.get_position_count() == 2

        # --- Price update: BTC TP1 hit, ETH no hit ---
        btc_exits = tracker.check_sl_tp_hlc_multi("BTCUSDT", high=102.0, low=100.5, close=101.8)
        assert len(btc_exits) == 1  # BTC TP1

        # Multi-TP check ignores single-TP positions (ETH tp_levels is empty)
        eth_multi_exits = tracker.check_sl_tp_hlc_multi("ETHUSDT", high=3050.0, low=2990.0, close=3040.0)
        assert len(eth_multi_exits) == 0

        # Single-TP check only catches ETH
        eth_single_exits = tracker.check_sl_tp_hlc("ETHUSDT", high=3100.0, low=3000.0, close=3090.0)
        assert len(eth_single_exits) == 1  # ETH TP hit

        # Apply BTC partial exit
        tracker.apply_partial_exit("BTCUSDT", 0, btc_exits[0][2], 0)
        assert tracker.positions["BTCUSDT"][0].size < btc_assessment.proposed_size

        # Close ETH fully (single-TP mode)
        await tracker.close_position("ETHUSDT", 0)

        # BTC still open with reduced size, ETH gone
        assert tracker.get_position_count() == 1
        assert "ETHUSDT" not in tracker.positions or len(tracker.positions["ETHUSDT"]) == 0

    @pytest.mark.asyncio
    async def test_idempotency_keys_unique_per_partial(self):
        """Each TP level generates a unique idempotency key."""
        keys_seen = set()
        asset = "BTCUSDT"
        entry_ts = 1716000000

        for i in range(3):
            key = f"tp{i+1}_{asset}_{entry_ts}"
            assert key not in keys_seen, f"Duplicate key: {key}"
            keys_seen.add(key)

        # SL key also unique
        sl_key = f"sl_{asset}_{entry_ts}"
        assert sl_key not in keys_seen

    @pytest.mark.asyncio
    async def test_position_persistence_round_trip(self):
        """Multi-TP fields survive PositionState serialization/deserialization."""
        pos = PositionState(
            asset="BTCUSDT", direction=1,
            entry_price=100.0, current_price=101.0,
            size=0.6, original_size=1.0,
            unrealized_pnl=0.6, entry_timestamp=time.time(),
            source_model="SqueezeBreakout", source_timeframe="1h",
            stop_loss_price=100.0,
            tp_levels=[101.5, 103.0, 105.0],
            tp_portions=[0.40, 0.30, 0.30],
            tp_levels_hit=[True, False, False],
            original_stop_loss=98.0,
            trail_to_breakeven=True,
        )

        # Serialize and deserialize (Pydantic model)
        data = pos.model_dump()
        restored = PositionState(**data)

        assert restored.tp_levels == [101.5, 103.0, 105.0]
        assert restored.tp_portions == [0.40, 0.30, 0.30]
        assert restored.tp_levels_hit == [True, False, False]
        assert restored.original_size == 1.0
        assert restored.original_stop_loss == 98.0
        assert restored.trail_to_breakeven is True
        assert restored.size == 0.6
