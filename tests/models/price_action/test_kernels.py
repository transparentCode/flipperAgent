"""Kernel-level unit tests for PriceAction model."""

from __future__ import annotations

import numpy as np
import pytest

from libs.models.price_action.kernels.bos import bos_score
from libs.models.price_action.kernels.engulfing import engulfing_score
from libs.models.price_action.kernels.fvg import fvg_score
from libs.models.price_action.kernels.inside_bar import inside_bar_score
from libs.models.price_action.kernels.pin_bar import pin_bar_score
from libs.models.price_action.kernels.sweep import sweep_score


# ── Helpers ─────────────────────────────────────────────────────────────

def _arr(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float64)


# ── K1: FVG ─────────────────────────────────────────────────────────────

class TestFVG:
    def test_fvg_bullish(self):
        # Candle 0: high=100, Candle 1 (gap), Candle 2: low=102 → gap = 2
        high = _arr(100.0, 103.0, 105.0)
        low = _arr(98.0, 101.0, 102.0)
        close = _arr(99.0, 102.0, 104.0)
        atr = _arr(2.0, 2.0, 2.0)
        score = fvg_score(high, low, close, atr, 2, 1.0)
        assert score > 0.0, f"Expected positive FVG score, got {score}"
        assert score == pytest.approx(1.0, abs=0.01)  # gap=2, atr=2, scale=1 → 1.0

    def test_fvg_bearish(self):
        # Candle 0: low=105, Candle 2: high=103 → bear_gap = 105-103 = 2
        high = _arr(107.0, 104.0, 103.0)
        low = _arr(105.0, 102.0, 101.0)
        close = _arr(106.0, 103.0, 102.0)
        atr = _arr(2.0, 2.0, 2.0)
        score = fvg_score(high, low, close, atr, 2, 1.0)
        assert score < 0.0, f"Expected negative FVG score, got {score}"
        assert score == pytest.approx(-1.0, abs=0.01)

    def test_fvg_no_gap(self):
        # Overlapping candles — no gap
        high = _arr(102.0, 104.0, 106.0)
        low = _arr(98.0, 100.0, 101.0)
        close = _arr(101.0, 103.0, 105.0)
        atr = _arr(2.0, 2.0, 2.0)
        score = fvg_score(high, low, close, atr, 2, 1.0)
        assert score == 0.0


# ── K2: Sweep ───────────────────────────────────────────────────────────

class TestSweep:
    def test_sweep_bullish(self):
        # Wick below swing low (95), close above it (97)
        high = _arr(100.0, 100.0, 100.0)
        low = _arr(97.0, 97.0, 93.0)  # sweeps below 95
        close = _arr(99.0, 99.0, 97.0)  # closes above 95
        score = sweep_score(high, low, close, 2, float("nan"), 95.0, 1.5)
        assert score > 0.0, f"Expected positive sweep score, got {score}"

    def test_sweep_no_rejection(self):
        # Wick below swing low but close also below — no rejection
        high = _arr(100.0, 100.0, 98.0)
        low = _arr(97.0, 97.0, 93.0)
        close = _arr(99.0, 99.0, 94.0)  # close below swing low
        score = sweep_score(high, low, close, 2, float("nan"), 95.0, 1.5)
        assert score == 0.0


# ── K3: Pin Bar ─────────────────────────────────────────────────────────

class TestPinBar:
    def test_pin_bar_bullish(self):
        # Long lower wick, small body, small upper wick
        open_ = _arr(100.0)
        high = _arr(101.0)
        low = _arr(95.0)
        close = _arr(100.5)
        atr = _arr(6.0)
        score = pin_bar_score(open_, high, low, close, atr, 0, 2.0, 1.5, 0.3, 1.5)
        assert score > 0.0, f"Expected positive pin bar score, got {score}"

    def test_pin_bar_too_small(self):
        # Candle range < min ATR threshold
        open_ = _arr(100.0)
        high = _arr(100.1)
        low = _arr(99.95)
        close = _arr(100.05)
        atr = _arr(6.0)  # range=0.15, atr*0.3=1.8 → too small
        score = pin_bar_score(open_, high, low, close, atr, 0, 2.0, 1.5, 0.3, 1.5)
        assert score == 0.0


# ── K4: Engulfing ───────────────────────────────────────────────────────

class TestEngulfing:
    def test_engulfing_bullish(self):
        # Bar 1 body fully engulfs bar 0 body, bullish close
        open_ = _arr(101.0, 99.0)
        high = _arr(102.0, 104.0)
        low = _arr(100.0, 98.0)
        close = _arr(100.5, 103.0)  # prev body: 100.5–101 (0.5); curr body: 99–103 (4.0)
        atr = _arr(3.0, 3.0)
        score = engulfing_score(open_, high, low, close, atr, 1, 0.5, 0.5)
        assert score > 0.0, f"Expected positive engulfing score, got {score}"

    def test_engulfing_small_body(self):
        # Body too small relative to ATR
        open_ = _arr(100.0, 99.9)
        high = _arr(101.0, 101.0)
        low = _arr(99.0, 99.0)
        close = _arr(100.1, 100.2)  # tiny bodies
        atr = _arr(10.0, 10.0)  # body=0.3 < 10*0.5=5
        score = engulfing_score(open_, high, low, close, atr, 1, 0.5, 0.5)
        assert score == 0.0


# ── K5: BOS ─────────────────────────────────────────────────────────────

class TestBOS:
    def test_bos_bullish_break(self):
        # Close breaks above swing high (was below on prior bar)
        close = _arr(99.0, 101.5)
        atr = _arr(2.0, 2.0)
        score = bos_score(close, atr, 1, 100.0, 90.0, 1.0)
        assert score > 0.0, f"Expected positive BOS score, got {score}"

    def test_bos_no_break(self):
        # Close below swing high
        close = _arr(99.0, 99.5)
        atr = _arr(2.0, 2.0)
        score = bos_score(close, atr, 1, 100.0, 90.0, 1.0)
        assert score == 0.0


# ── K6: Inside Bar ──────────────────────────────────────────────────────

class TestInsideBar:
    def test_inside_bar_breakout_up(self):
        # Bar i-2: wide range; Bar i-1: inside bar; Bar i: breakout up
        high = _arr(110.0, 108.0, 112.0)
        low = _arr(100.0, 102.0, 107.0)
        close = _arr(105.0, 106.0, 111.0)
        atr = _arr(5.0, 5.0, 5.0)
        score = inside_bar_score(high, low, close, atr, 2, 0.5)
        assert score > 0.0, f"Expected positive inside bar score, got {score}"

    def test_inside_bar_no_breakout(self):
        # Inside bar but close stays within i-1 range
        high = _arr(110.0, 108.0, 107.0)
        low = _arr(100.0, 102.0, 103.0)
        close = _arr(105.0, 106.0, 105.0)
        atr = _arr(5.0, 5.0, 5.0)
        score = inside_bar_score(high, low, close, atr, 2, 0.5)
        assert score == 0.0
