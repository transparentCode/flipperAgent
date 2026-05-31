"""Numba-accelerated batch orchestrator for PriceAction ensemble scoring."""

from __future__ import annotations

import math

import numpy as np
from numba import njit


@njit(cache=True)
def _batch_price_action(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
    # Swing detection
    swing_lookback: int,
    # K1: FVG
    fvg_atr_scale: float,
    # K2: Sweep
    sweep_wick_scale: float,
    # K3: Pin Bar
    pin_wick_body_ratio: float,
    pin_wick_dominance: float,
    pin_min_range_atr: float,
    pin_strength_scale: float,
    # K4: Engulfing
    engulf_min_body_atr: float,
    engulf_ratio_scale: float,
    # K5: BOS
    bos_displacement_scale: float,
    # K6: Inside Bar
    ib_breakout_scale: float,
    # Weights
    w_fvg: float,
    w_sweep: float,
    w_pin: float,
    w_engulf: float,
    w_bos: float,
    w_inside: float,
    # Ensemble
    confluence_scale: float,
    confluence_min: int,
    # Context
    context_proximity_boost: float,
    context_alignment_boost: float,
    # Decay
    pattern_decay_rate: float,
) -> np.ndarray:
    """Process the full OHLCV+ATR series and return per-bar edge scores.

    Fully deterministic, no Python objects, no dynamic allocation.
    """
    n = len(close)
    edge = np.empty(n, dtype=np.float64)

    # Rolling swing state
    last_sh_price = math.nan
    last_sl_price = math.nan

    # Decay accumulators (EMA per kernel)
    dk1_prev = 0.0
    dk2_prev = 0.0
    dk3_prev = 0.0
    dk4_prev = 0.0
    dk5_prev = 0.0
    dk6_prev = 0.0

    for i in range(n):
        # ── 1. Update confirmed swing points ────────────────────────
        if i >= 2 * swing_lookback:
            check_idx = i - swing_lookback
            is_sh = True
            is_sl = True
            for j in range(check_idx - swing_lookback, check_idx + swing_lookback + 1):
                if j != check_idx and 0 <= j < n:
                    if high[j] >= high[check_idx]:
                        is_sh = False
                    if low[j] <= low[check_idx]:
                        is_sl = False
            if is_sh:
                last_sh_price = high[check_idx]
            if is_sl:
                last_sl_price = low[check_idx]

        # ── 2. Compute raw kernel scores ────────────────────────────

        # K1: FVG
        k1 = 0.0
        if i >= 2:
            atr_val = atr[i]
            if atr_val > 0.0:
                bull_gap = low[i] - high[i - 2]
                if bull_gap > 0.0:
                    k1 = min(1.0, bull_gap / (atr_val * fvg_atr_scale))
                else:
                    bear_gap = low[i - 2] - high[i]
                    if bear_gap > 0.0:
                        k1 = -min(1.0, bear_gap / (atr_val * fvg_atr_scale))

        # K2: Sweep
        k2 = 0.0
        bar_range = high[i] - low[i]
        if bar_range > 0.0:
            if not math.isnan(last_sl_price):
                if low[i] < last_sl_price and close[i] > last_sl_price:
                    wick_ratio = (close[i] - low[i]) / bar_range
                    k2 = min(1.0, wick_ratio * sweep_wick_scale)
            if not math.isnan(last_sh_price):
                if high[i] > last_sh_price and close[i] < last_sh_price:
                    wick_ratio = (high[i] - close[i]) / bar_range
                    s = -min(1.0, wick_ratio * sweep_wick_scale)
                    if abs(s) > abs(k2):
                        k2 = s

        # K3: Pin Bar
        k3 = 0.0
        if bar_range > 0.0 and atr[i] > 0.0:
            if bar_range >= atr[i] * pin_min_range_atr:
                body = abs(close[i] - open_[i])
                body_high = max(open_[i], close[i])
                body_low = min(open_[i], close[i])
                upper_wick = high[i] - body_high
                lower_wick = body_low - low[i]
                if lower_wick > body * pin_wick_body_ratio and lower_wick > upper_wick * pin_wick_dominance:
                    k3 = min(1.0, (lower_wick / bar_range) * pin_strength_scale)
                elif upper_wick > body * pin_wick_body_ratio and upper_wick > lower_wick * pin_wick_dominance:
                    k3 = -min(1.0, (upper_wick / bar_range) * pin_strength_scale)

        # K4: Engulfing
        k4 = 0.0
        if i >= 1 and atr[i] > 0.0:
            prev_body_high = max(open_[i - 1], close[i - 1])
            prev_body_low = min(open_[i - 1], close[i - 1])
            curr_body_high = max(open_[i], close[i])
            curr_body_low = min(open_[i], close[i])
            prev_body_size = prev_body_high - prev_body_low
            curr_body_size = curr_body_high - curr_body_low
            if curr_body_low < prev_body_low and curr_body_high > prev_body_high:
                if curr_body_size >= atr[i] * engulf_min_body_atr:
                    ratio = curr_body_size / (prev_body_size + 1e-10)
                    if close[i] > open_[i]:
                        k4 = min(1.0, ratio * engulf_ratio_scale)
                    elif close[i] < open_[i]:
                        k4 = -min(1.0, ratio * engulf_ratio_scale)

        # K5: BOS
        k5 = 0.0
        if i >= 1 and atr[i] > 0.0:
            if not math.isnan(last_sh_price):
                if close[i] > last_sh_price and close[i - 1] <= last_sh_price:
                    displacement = (close[i] - last_sh_price) / (atr[i] + 1e-10)
                    k5 = min(1.0, displacement * bos_displacement_scale)
            if not math.isnan(last_sl_price):
                if close[i] < last_sl_price and close[i - 1] >= last_sl_price:
                    displacement = (last_sl_price - close[i]) / (atr[i] + 1e-10)
                    s = -min(1.0, displacement * bos_displacement_scale)
                    if abs(s) > abs(k5):
                        k5 = s

        # K6: Inside Bar Breakout
        k6 = 0.0
        if i >= 2 and atr[i] > 0.0:
            is_inside = high[i - 1] <= high[i - 2] and low[i - 1] >= low[i - 2]
            if is_inside:
                if close[i] > high[i - 1]:
                    k6 = min(1.0, (close[i] - high[i - 1]) / (atr[i] * ib_breakout_scale + 1e-10))
                elif close[i] < low[i - 1]:
                    k6 = -min(1.0, (low[i - 1] - close[i]) / (atr[i] * ib_breakout_scale + 1e-10))

        # ── 3. Pattern decay (EMA accumulator per kernel) ───────────
        dk1 = k1 + pattern_decay_rate * dk1_prev
        dk2 = k2 + pattern_decay_rate * dk2_prev
        dk3 = k3 + pattern_decay_rate * dk3_prev
        dk4 = k4 + pattern_decay_rate * dk4_prev
        dk5 = k5 + pattern_decay_rate * dk5_prev
        dk6 = k6 + pattern_decay_rate * dk6_prev
        dk1_prev = dk1
        dk2_prev = dk2
        dk3_prev = dk3
        dk4_prev = dk4
        dk5_prev = dk5
        dk6_prev = dk6

        # ── 4. Context multipliers ──────────────────────────────────
        # Proximity boost for reversal kernels near swing levels
        dist_sh = abs(close[i] - last_sh_price) / (atr[i] + 1e-10) if not math.isnan(last_sh_price) else 999.0
        dist_sl = abs(close[i] - last_sl_price) / (atr[i] + 1e-10) if not math.isnan(last_sl_price) else 999.0
        min_dist = min(dist_sh, dist_sl)
        if min_dist < 1.5:
            prox = 1.0 + context_proximity_boost * (1.0 - min_dist / 1.5)
            dk2 *= prox
            dk3 *= prox
            dk4 *= prox

        # Alignment boost: FVG concurrent with BOS
        if dk1 != 0.0 and dk5 != 0.0:
            dk1 *= (1.0 + context_alignment_boost)

        # Alignment boost: sweep/pin aligns directionally with FVG
        if dk1 != 0.0:
            if dk2 != 0.0 and (dk2 > 0) == (dk1 > 0):
                dk2 *= (1.0 + context_alignment_boost * 0.5)
            if dk3 != 0.0 and (dk3 > 0) == (dk1 > 0):
                dk3 *= (1.0 + context_alignment_boost * 0.5)

        # ── 5. Weighted sum ─────────────────────────────────────────
        raw = (w_fvg * dk1 + w_sweep * dk2 + w_pin * dk3
               + w_engulf * dk4 + w_bos * dk5 + w_inside * dk6)

        # ── 6. Confluence bonus ─────────────────────────────────────
        sign_raw = 1.0 if raw > 0 else (-1.0 if raw < 0 else 0.0)
        n_agree = 0
        if dk1 * sign_raw > 0:
            n_agree += 1
        if dk2 * sign_raw > 0:
            n_agree += 1
        if dk3 * sign_raw > 0:
            n_agree += 1
        if dk4 * sign_raw > 0:
            n_agree += 1
        if dk5 * sign_raw > 0:
            n_agree += 1
        if dk6 * sign_raw > 0:
            n_agree += 1

        bonus_count = n_agree - confluence_min
        if bonus_count < 0:
            bonus_count = 0
        bonus = 1.0 + confluence_scale * bonus_count

        edge[i] = raw * bonus

    return edge
