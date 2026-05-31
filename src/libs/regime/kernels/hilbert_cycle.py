"""
Hilbert Transform — Dominant Cycle Detector (Causal).

Implements Ehlers' Homodyne Discriminator from "Cybernetic Analysis for
Stocks and Futures" (2004). Uses a short FIR Hilbert approximation that
is strictly causal — every computation uses only current and past bars.

Replaces the previous scipy.signal.hilbert implementation which was
FFT-based (non-causal, leaked future data via bidirectional transform
and global mean centering).
"""

from __future__ import annotations

import numpy as np

_MIN_PERIOD = 10   # bars — lower bound on cycle period (default for crypto)
_MAX_PERIOD = 40   # bars — upper bound on cycle period (default for crypto)
_STABILITY_BARS = 10  # trailing bars used for dominant_period estimate


class HilbertCycle:
    """
    Ehlers Homodyne Discriminator — causal dominant cycle estimator.

    Uses a 7-tap FIR Hilbert transform (causal, no future data) to extract
    in-phase and quadrature components, then derives instantaneous period
    via homodyne discrimination.

    Parameters
    ----------
    min_period : int — lower clamp for cycle period (default 10, use 20+ for FX/stocks)
    max_period : int — upper clamp for cycle period (default 40, use 100+ for FX/stocks)
    stability_bars : int — trailing bars for rolling median/confidence
    """

    def __init__(
        self,
        min_period: int = _MIN_PERIOD,
        max_period: int = _MAX_PERIOD,
        stability_bars: int = _STABILITY_BARS,
    ):
        self.min_period = min_period
        self.max_period = max_period
        self.stability_bars = stability_bars

    def calculate(self, prices: np.ndarray) -> tuple[float, float]:
        """
        Compute dominant cycle period and confidence for the last bar.

        Parameters
        ----------
        prices : 1-D array of close prices (minimum ~20 bars recommended)

        Returns
        -------
        dominant_period : float  — estimated bars per cycle, clamped [min, max]
        confidence      : float  — 0.0 (noisy) – 1.0 (stable period)
        """
        if len(prices) < 2:
            return float(self.max_period), 0.0

        period_series = self._period_series(prices)
        tail = period_series[-self.stability_bars:]
        dominant_period = float(np.median(tail))
        confidence = self._confidence(tail)
        return dominant_period, confidence

    def calculate_series(
        self, prices: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute dominant_period and confidence at every bar (causal).

        All computations use only data up to the current bar — no lookahead.

        Parameters
        ----------
        prices : 1-D array of close prices

        Returns
        -------
        periods     : shape (T,)
        confidences : shape (T,)
        """
        T = len(prices)
        if T < 2:
            return np.full(T, float(self.max_period)), np.zeros(T)

        period_full = self._period_series(prices)

        # Causal rolling median for dominant period
        periods = np.full(T, float(self.max_period))
        confidences = np.zeros(T)

        for t in range(self.stability_bars, T):
            window = period_full[max(0, t - self.stability_bars + 1) : t + 1]
            periods[t] = float(np.median(window))
            mean = window.mean()
            if mean > 0:
                cv = window.std() / mean
                confidences[t] = float(np.clip(1.0 - cv, 0.0, 1.0))

        # Fill early bars with first valid value
        if T > self.stability_bars:
            periods[:self.stability_bars] = periods[self.stability_bars]

        return periods, confidences

    # ------------------------------------------------------------------
    # Internal helpers — Ehlers Homodyne Discriminator
    # ------------------------------------------------------------------

    def _period_series(self, prices: np.ndarray) -> np.ndarray:
        """
        Causal instantaneous period at each bar via Ehlers' Homodyne
        Discriminator. Uses a 7-tap FIR Hilbert approximation — strictly
        causal, no FFT, no future data.

        Returns array of the same length as prices.
        """
        T = len(prices)
        result = np.full(T, float(self.max_period))

        if T < 7:
            return result

        # Ehlers' 4-bar WMA smoothing
        smooth = np.zeros(T)
        for i in range(3, T):
            smooth[i] = (
                4.0 * prices[i]
                + 3.0 * prices[i - 1]
                + 2.0 * prices[i - 2]
                + prices[i - 3]
            ) / 10.0

        # State arrays for the homodyne discriminator
        detrender = np.zeros(T)
        I1 = np.zeros(T)
        Q1 = np.zeros(T)
        jI = np.zeros(T)
        jQ = np.zeros(T)
        I2 = np.zeros(T)
        Q2 = np.zeros(T)
        Re = np.zeros(T)
        Im = np.zeros(T)
        period = np.full(T, float(self.max_period))
        smooth_period = np.full(T, float(self.max_period))

        # Ehlers FIR coefficients
        a1, a2 = 0.0962, 0.5769

        for i in range(6, T):
            # Adaptive FIR adjustment factor
            adj = 0.075 * period[i - 1] + 0.54

            # Detrender: Hilbert FIR on smoothed price
            detrender[i] = (
                a1 * smooth[i]
                + a2 * smooth[i - 2]
                - a2 * smooth[i - 4]
                - a1 * smooth[i - 6]
            ) * adj

            # In-phase = detrended delayed 3 bars
            I1[i] = detrender[i - 3]

            # Quadrature: Hilbert FIR on detrended signal
            Q1[i] = (
                a1 * detrender[i]
                + a2 * detrender[i - 2]
                - a2 * detrender[i - 4]
                - a1 * detrender[i - 6]
            ) * adj

            # Advance phase of I1 and Q1 by 90 degrees
            jI[i] = (
                a1 * I1[i]
                + a2 * I1[i - 2]
                - a2 * I1[i - 4]
                - a1 * I1[i - 6]
            ) * adj

            jQ[i] = (
                a1 * Q1[i]
                + a2 * Q1[i - 2]
                - a2 * Q1[i - 4]
                - a1 * Q1[i - 6]
            ) * adj

            # Phasor addition for 3-bar averaging
            I2[i] = I1[i] - jQ[i]
            Q2[i] = Q1[i] + jI[i]

            # Smooth I and Q components (EMA α=0.2)
            I2[i] = 0.2 * I2[i] + 0.8 * I2[i - 1]
            Q2[i] = 0.2 * Q2[i] + 0.8 * Q2[i - 1]

            # Homodyne discriminator
            Re[i] = I2[i] * I2[i - 1] + Q2[i] * Q2[i - 1]
            Im[i] = I2[i] * Q2[i - 1] - Q2[i] * I2[i - 1]

            # Smooth Re and Im (EMA α=0.2)
            Re[i] = 0.2 * Re[i] + 0.8 * Re[i - 1]
            Im[i] = 0.2 * Im[i] + 0.8 * Im[i - 1]

            # Compute period from phase angle
            if abs(Im[i]) > 1e-10 and abs(Re[i]) > 1e-10:
                period[i] = 2.0 * np.pi / abs(np.arctan2(Im[i], Re[i]))
            else:
                period[i] = period[i - 1]

            # Constrain period rate of change (max ±50% per bar)
            if period[i] > 1.5 * period[i - 1]:
                period[i] = 1.5 * period[i - 1]
            if period[i] < 0.67 * period[i - 1]:
                period[i] = 0.67 * period[i - 1]

            # Clamp to bounds
            period[i] = np.clip(period[i], self.min_period, self.max_period)

            # Smooth period (EMA α=0.2)
            period[i] = 0.2 * period[i] + 0.8 * period[i - 1]

            # Double-smooth for stability
            smooth_period[i] = 0.33 * period[i] + 0.67 * smooth_period[i - 1]

        # Clamp final output
        result = np.clip(smooth_period, self.min_period, self.max_period)
        return result

    def _confidence(self, period_window: np.ndarray) -> float:
        """
        Period stability → confidence.  CV = std/mean; confidence = 1 - CV.
        """
        mean = period_window.mean()
        if mean == 0:
            return 0.0
        cv = period_window.std() / mean
        return float(np.clip(1.0 - cv, 0.0, 1.0))
