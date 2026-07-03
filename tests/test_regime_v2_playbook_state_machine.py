"""Tests for Phase 7B deterministic playbook state machine."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.policy.playbook_state_machine import (
    STATE_BREAKOUT_CONFIRMATION,
    STATE_BREAKOUT_SETUP,
    STATE_NO_TRADE_RISK,
    STATE_SCALP_ONLY,
    STATE_TREND_CONTINUATION,
    STATE_WAIT_COMPRESSION,
    build_playbook_state_frame,
    build_playbook_state_report,
    context_row_to_state,
    render_playbook_state_report_markdown,
)


def _row(**overrides) -> dict:
    base = {
        "playbook_context_market_phase": "neutral_context",
        "playbook_context_risk_state": "ok",
        "playbook_context_risk_score": 0.25,
        "playbook_context_dominant_playbook": "none",
        "playbook_context_horizon_bias": "mid",
        "playbook_context_next_step": "observe_or_shadow_only",
        "playbook_context_conflict_tags": "",
        "playbook_context_conflict_count": 0,
        "playbook_context_is_active": False,
    }
    base.update(overrides)
    return base


def test_state_machine_blocks_risk_first():
    state = context_row_to_state(
        _row(
            playbook_context_market_phase="uncertain_no_trade",
            playbook_context_risk_state="blocked",
            playbook_context_dominant_playbook="scalping",
            playbook_context_is_active=True,
        )
    )

    assert state["playbook_state"] == STATE_NO_TRADE_RISK
    assert state["state_reason"] == "risk_blocked"
    assert state["is_risk_state"] is True
    assert state["is_executable_state"] is False


def test_state_machine_separates_wait_and_setup_states():
    compression = context_row_to_state(
        _row(
            playbook_context_market_phase="compressed_wait",
            playbook_context_horizon_bias="wait_for_expansion",
            playbook_context_next_step="watch_for_breakout_expansion",
        )
    )
    setup = context_row_to_state(_row(playbook_context_market_phase="breakout_setup"))

    assert compression["playbook_state"] == STATE_WAIT_COMPRESSION
    assert compression["is_wait_state"] is True
    assert setup["playbook_state"] == STATE_BREAKOUT_SETUP
    assert setup["is_wait_state"] is True


def test_state_machine_confirms_breakout_only_without_conflict():
    confirmed = context_row_to_state(
        _row(
            playbook_context_market_phase="displacement_breakout",
            playbook_context_dominant_playbook="breakout",
            playbook_context_horizon_bias="mid_to_long",
            playbook_context_is_active=True,
        )
    )
    conflicted = context_row_to_state(
        _row(
            playbook_context_market_phase="displacement_breakout",
            playbook_context_dominant_playbook="breakout",
            playbook_context_conflict_tags="breakout_false_break_risk",
            playbook_context_is_active=True,
        )
    )

    assert confirmed["playbook_state"] == STATE_BREAKOUT_CONFIRMATION
    assert confirmed["is_executable_state"] is True
    assert conflicted["playbook_state"] == STATE_BREAKOUT_SETUP
    assert conflicted["state_reason"] == "breakout_needs_confirmation"


def test_state_machine_trend_and_scalp_paths():
    trend = context_row_to_state(
        _row(
            playbook_context_market_phase="bull_trend",
            playbook_context_dominant_playbook="trend",
            playbook_context_horizon_bias="long",
            playbook_context_is_active=True,
        )
    )
    scalp = context_row_to_state(
        _row(
            playbook_context_dominant_playbook="scalping",
            playbook_context_is_active=True,
        )
    )

    assert trend["playbook_state"] == STATE_TREND_CONTINUATION
    assert trend["state_reason"] == "trend_context"
    assert scalp["playbook_state"] == STATE_SCALP_ONLY
    assert scalp["state_reason"] == "scalp_only_context"


def test_state_frame_report_and_markdown():
    context = pd.DataFrame(
        [
            _row(playbook_context_market_phase="uncertain_no_trade", playbook_context_risk_state="blocked"),
            _row(playbook_context_market_phase="compressed_wait", playbook_context_horizon_bias="wait_for_expansion"),
            _row(playbook_context_market_phase="bull_trend", playbook_context_dominant_playbook="trend", playbook_context_horizon_bias="long", playbook_context_is_active=True),
        ],
        index=[1, 2, 3],
    )

    state_df = build_playbook_state_frame(context)
    report = build_playbook_state_report(state_df, asset="BNBUSDT", timeframe="1h", source="unit")
    md = render_playbook_state_report_markdown(report)

    assert state_df.loc[1, "playbook_state"] == STATE_NO_TRADE_RISK
    assert state_df.loc[2, "playbook_state"] == STATE_WAIT_COMPRESSION
    assert state_df.loc[3, "playbook_state"] == STATE_TREND_CONTINUATION
    assert report["summary"]["row_count"] == 3
    assert report["summary"]["executable_count"] == 1
    assert report["summary"]["wait_count"] == 1
    assert report["summary"]["risk_count"] == 1
    assert "# RegimeV2 Phase 7B Playbook State Machine Report" in md
