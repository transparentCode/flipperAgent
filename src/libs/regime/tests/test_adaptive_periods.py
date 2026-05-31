"""
Tests for FeatureAggregator._compute_adaptive_period()

Validates the 2-tier adaptive period logic:
  Level 1 (hilbert_confidence >= 0.70): scale = hilbert_period / bb_base
  Level 2 (hilbert_confidence < 0.70):  scale = regime fallback scale
  Period clamped: scale in [0.5, 2.0], period = max(5, round(bb_base * scale))
"""

import pytest
from app.regime.aggregation.rule_based import FeatureAggregator, AggregatorConfig

BB_BASE = 20   # default bb_base
THRESHOLD = 0.70  # default hilbert_high_threshold


@pytest.fixture
def agg():
    return FeatureAggregator(AggregatorConfig())


# ---------------------------------------------------------------------------
# Level 1: High confidence → direct Hilbert scale
# ---------------------------------------------------------------------------

def test_high_confidence_uses_hilbert_scale(agg):
    """hilbert_confidence >= 0.70 → scale = hilbert_period / bb_base."""
    period = agg._compute_adaptive_period(
        hilbert_period=30.0, hilbert_confidence=0.85, regime="CLEAN_TREND_BULL"
    )
    # scale = 30 / 20 = 1.5 → period = round(20 * 1.5) = 30
    assert period == 30


def test_high_confidence_exactly_at_threshold(agg):
    """Exactly at threshold (0.70) should use Hilbert scale."""
    period = agg._compute_adaptive_period(
        hilbert_period=20.0, hilbert_confidence=0.70, regime="QUIET_MR_RANGE"
    )
    # scale = 20/20 = 1.0 → period = 20
    assert period == 20


def test_high_confidence_hilbert_drives_period_regardless_of_regime(agg):
    """With high confidence, regime label doesn't affect period."""
    p_clean = agg._compute_adaptive_period(30.0, 0.90, "CLEAN_TREND_BULL")
    p_choppy = agg._compute_adaptive_period(30.0, 0.90, "CHOPPY")
    p_quiet = agg._compute_adaptive_period(30.0, 0.90, "QUIET_MR_RANGE")
    assert p_clean == p_choppy == p_quiet  # same Hilbert input → same period


# ---------------------------------------------------------------------------
# Level 2: Low confidence → regime fallback scale
# ---------------------------------------------------------------------------

def test_low_confidence_uses_regime_fallback_clean_trend(agg):
    """CLEAN_TREND_BULL fallback scale = 1.0 → period = bb_base."""
    period = agg._compute_adaptive_period(
        hilbert_period=40.0, hilbert_confidence=0.40, regime="CLEAN_TREND_BULL"
    )
    # Hilbert ignored; scale = 1.0 → period = 20
    assert period == 20


def test_low_confidence_uses_regime_fallback_volatile_trend(agg):
    """VOLATILE_TREND_BULL fallback scale = 0.75 → period = round(20 * 0.75) = 15."""
    period = agg._compute_adaptive_period(
        hilbert_period=40.0, hilbert_confidence=0.40, regime="VOLATILE_TREND_BULL"
    )
    assert period == 15


def test_low_confidence_uses_regime_fallback_quiet_mr(agg):
    """QUIET_MR_RANGE fallback scale = 1.25 → period = round(20 * 1.25) = 25."""
    period = agg._compute_adaptive_period(
        hilbert_period=40.0, hilbert_confidence=0.40, regime="QUIET_MR_RANGE"
    )
    assert period == 25


def test_low_confidence_uses_regime_fallback_choppy(agg):
    """CHOPPY fallback scale = 0.5 → period = round(20 * 0.5) = 10."""
    period = agg._compute_adaptive_period(
        hilbert_period=40.0, hilbert_confidence=0.40, regime="CHOPPY"
    )
    assert period == 10


# ---------------------------------------------------------------------------
# Clamping: scale clamped to [0.5, 2.0]
# ---------------------------------------------------------------------------

def test_hilbert_period_too_low_clamped_to_min(agg):
    """Hilbert period=5, bb_base=20 → scale=0.25 → clamped to 0.5 → period=10."""
    period = agg._compute_adaptive_period(
        hilbert_period=5.0, hilbert_confidence=0.95, regime="CLEAN_TREND_BULL"
    )
    assert period == 10  # max(5, round(20 * 0.5))


def test_hilbert_period_too_high_clamped_to_max(agg):
    """Hilbert period=60, bb_base=20 → scale=3.0 → clamped to 2.0 → period=40."""
    period = agg._compute_adaptive_period(
        hilbert_period=60.0, hilbert_confidence=0.95, regime="CLEAN_TREND_BULL"
    )
    assert period == 40  # max(5, round(20 * 2.0))


def test_period_never_below_5(agg):
    """Period floor is 5 regardless of clamping."""
    period = agg._compute_adaptive_period(
        hilbert_period=1.0, hilbert_confidence=0.95, regime="CLEAN_TREND_BULL"
    )
    assert period >= 5


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

def test_returns_int(agg):
    period = agg._compute_adaptive_period(25.0, 0.80, "CLEAN_TREND_BULL")
    assert isinstance(period, int)
