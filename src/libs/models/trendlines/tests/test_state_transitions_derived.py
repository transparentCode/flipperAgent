"""Tests for derived state transition table."""

from __future__ import annotations

import pytest

from app.trendlines.config.state_transitions import (
    build_state_transition_table,
    _INTERACTION_DIRECTION,
    _STATE_PAIRS,
    _classify_transition,
    _compute_direction,
)


class TestBuildStateTransitionTable:
    def test_returns_14_entries(self):
        table = build_state_transition_table()
        assert len(table) == 14

    def test_keys_are_string_tuples(self):
        table = build_state_transition_table()
        for key in table:
            assert isinstance(key, tuple)
            assert len(key) == 2
            assert all(isinstance(s, str) for s in key)

    def test_values_are_direction_confidence(self):
        table = build_state_transition_table()
        for (from_s, to_s), (direction, confidence) in table.items():
            assert isinstance(direction, float), f"{from_s}->{to_s}: direction not float"
            assert isinstance(confidence, float), f"{from_s}->{to_s}: confidence not float"
            assert 0 < confidence <= 1.0, f"{from_s}->{to_s}: confidence {confidence} out of range"
            assert -1.0 <= direction <= 1.0, f"{from_s}->{to_s}: direction {direction} out of range"

    def test_all_state_pairs_covered(self):
        table = build_state_transition_table()
        for pair in _STATE_PAIRS:
            assert pair in table, f"Missing state pair: {pair}"

    def test_confidences_in_expected_bands(self):
        table = build_state_transition_table()
        confidences = sorted(set(c for _, c in table.values()))
        # 3 base archetypes + fade bumps for NONE→active transitions
        # At least 3 distinct values, all in (0, 1]
        assert len(confidences) >= 3
        assert all(0 < c <= 1.0 for c in confidences)

    def test_custom_confidence_levels(self):
        table = build_state_transition_table(
            conf_reversal=0.9, conf_continuation=0.7, conf_fade=0.3
        )
        confidences = sorted(set(c for _, c in table.values()))
        assert 0.9 in confidences
        assert 0.7 in confidences
        assert 0.3 in confidences


class TestDirectionSigns:
    """Verify directions match expected market physics."""

    def test_none_to_bounce_support_is_bullish(self):
        table = build_state_transition_table()
        d, _ = table[("NONE", "GEOMETRIC_BOUNCE_SUPPORT")]
        assert d > 0  # bounce off support → bullish

    def test_none_to_bounce_resistance_is_bearish(self):
        table = build_state_transition_table()
        d, _ = table[("NONE", "GEOMETRIC_BOUNCE_RESISTANCE")]
        assert d < 0  # bounce off resistance → bearish

    def test_none_to_breakout_is_bullish(self):
        table = build_state_transition_table()
        d, _ = table[("NONE", "STRUCTURAL_BREAKOUT")]
        assert d > 0

    def test_none_to_breakdown_is_bearish(self):
        table = build_state_transition_table()
        d, _ = table[("NONE", "STRUCTURAL_BREAKDOWN")]
        assert d < 0

    def test_reversal_bounce_to_opposing_breakout(self):
        table = build_state_transition_table()
        d, c = table[("GEOMETRIC_BOUNCE_SUPPORT", "STRUCTURAL_BREAKDOWN")]
        assert d < 0  # reversal: was bullish → now bearish
        assert c >= 0.8  # high confidence for reversal

    def test_fade_to_none_reverses(self):
        table = build_state_transition_table()
        d, _ = table[("GEOMETRIC_BOUNCE_SUPPORT", "NONE")]
        assert d < 0  # fading a bullish bounce → mild bearish

    def test_structural_fade_stronger_than_geometric(self):
        table = build_state_transition_table()
        _, c_geo = table[("GEOMETRIC_BOUNCE_SUPPORT", "NONE")]
        _, c_str = table[("STRUCTURAL_BREAKOUT", "NONE")]
        # Both are fade, same confidence level
        d_geo, _ = table[("GEOMETRIC_BOUNCE_SUPPORT", "NONE")]
        d_str, _ = table[("STRUCTURAL_BREAKOUT", "NONE")]
        assert abs(d_str) > abs(d_geo)  # structural fades are stronger signals


class TestClassifyTransition:
    def test_none_to_active_is_fade(self):
        assert _classify_transition("NONE", "GEOMETRIC_BOUNCE_SUPPORT") == "fade"

    def test_opposing_is_reversal(self):
        assert _classify_transition("GEOMETRIC_BOUNCE_SUPPORT", "STRUCTURAL_BREAKDOWN") == "reversal"

    def test_same_side_is_continuation(self):
        assert _classify_transition("STRUCTURAL_BREAKOUT", "GEOMETRIC_BOUNCE_SUPPORT") == "continuation"


class TestComputeDirection:
    def test_none_to_bullish(self):
        d = _compute_direction("NONE", "GEOMETRIC_BOUNCE_SUPPORT")
        assert d > 0

    def test_bullish_to_none(self):
        d = _compute_direction("GEOMETRIC_BOUNCE_SUPPORT", "NONE")
        assert d < 0  # reversal

    def test_bullish_to_bearish(self):
        d = _compute_direction("GEOMETRIC_BOUNCE_SUPPORT", "STRUCTURAL_BREAKDOWN")
        assert d < 0

    def test_direction_never_zero_for_active_pairs(self):
        for from_s, to_s in _STATE_PAIRS:
            d = _compute_direction(from_s, to_s)
            # NONE→active and active→NONE always have direction
            assert d != 0.0, f"Zero direction for {from_s} -> {to_s}"
