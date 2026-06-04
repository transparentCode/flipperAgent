"""
Configuration defaults for RegimeClassificationModel kernels.

Only 5 structural hyperparameters remain Optuna-worthy.
Everything else is either adaptive (computed from data) or fixed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BCPDConfig:
    """Bayesian Online Changepoint Detection config."""

    hazard_lambda: float = 150.0  # expected run length between changepoints
    hazard_shape: float = 1.0  # Weibull shape (1.0 = constant hazard)
    truncation: int = 500  # max run length tracked
    return_posterior: bool = True  # need posterior for entropy calc


@dataclass(frozen=True)
class HMMConfig:
    """HMM classifier config."""

    retrain_window: int = 500  # bars used for rolling fit
    min_train_bars: int = 200  # minimum bars before emitting signal
    log_vol_lookback: int = 24  # bars for within-feature vol estimate
    hurst_lookback: int = 100  # rolling R/S Hurst window
    use_hurst: bool = True
    use_volume: bool = True
    hmm_n_states: int = 0  # 0 = auto-select via BIC
    hmm_max_states: int = 4
    hmm_covariance_type: str = "full"
    hmm_robust_scoring: bool = True
    hmm_student_df: float = 5.0  # structural — Optuna-worthy
    hmm_crisis_vol_mult: float = 2.0


@dataclass(frozen=True)
class VolConfig:
    """Rolling volatility percentile config."""

    lookback: int = 168  # 1 week of 1h bars
    rank_window: int = 1000  # history for percentile ranking


@dataclass(frozen=True)
class HilbertConfig:
    """Hilbert cycle detector config."""

    min_period: int = 10  # structural — Optuna-worthy
    max_period: int = 40  # structural — Optuna-worthy
    stability_bars: int = 10


@dataclass(frozen=True)
class EWMAVolConfig:
    """EWMA forward volatility estimator config."""

    decay_factor: float = 0.94  # RiskMetrics standard
    min_periods: int = 20  # warm-up bars before emitting


@dataclass(frozen=True)
class TrendStrengthConfig:
    """Directional efficiency ratio config."""

    lookback: int = 20  # bars for efficiency ratio


@dataclass(frozen=True)
class RegimeClassificationConfig:
    """Top-level config for the RegimeClassificationModel."""

    bcpd: BCPDConfig = BCPDConfig()
    hmm: HMMConfig = HMMConfig()
    vol: VolConfig = VolConfig()
    hilbert: HilbertConfig = HilbertConfig()
    ewma_vol: EWMAVolConfig = EWMAVolConfig()
    trend: TrendStrengthConfig = TrendStrengthConfig()


# Bars-per-hour for each supported timeframe (1h = 1.0 baseline)
_BARS_PER_HOUR: dict[str, float] = {
    "1m": 60.0, "5m": 12.0, "15m": 4.0, "30m": 2.0,
    "1h": 1.0, "4h": 0.25, "1d": 1 / 24,
}


def timeframe_scaled_config(
    timeframe: str = "1h",
    frozen_overrides: dict[str, Any] | None = None,
) -> RegimeClassificationConfig:
    """Build a RegimeClassificationConfig with bar counts scaled to timeframe.

    All bar-denominated defaults are calibrated for 1h. This function scales
    them proportionally so they represent equivalent clock-time windows on
    other timeframes. Any key in frozen_overrides takes precedence over
    the scaled default.
    """
    ratio = _BARS_PER_HOUR.get(timeframe, 1.0)
    overrides = frozen_overrides or {}

    def _scaled(base_1h: int, key: str, floor: int = 20) -> int:
        if key in overrides:
            return int(overrides[key])
        return max(int(base_1h * ratio), floor)

    def _raw(default, key: str):
        return overrides.get(key, default)

    return RegimeClassificationConfig(
        bcpd=BCPDConfig(
            hazard_lambda=_raw(150.0, "bcpd_hazard_lambda"),
            hazard_shape=_raw(1.0, "bcpd_hazard_shape"),
            truncation=_scaled(500, "bcpd_truncation"),
        ),
        hmm=HMMConfig(
            retrain_window=_scaled(500, "hmm_retrain_window"),
            min_train_bars=_scaled(200, "hmm_min_train_bars", floor=30),
            log_vol_lookback=_scaled(24, "hmm_log_vol_lookback", floor=6),
            hurst_lookback=_raw(100, "hurst_lookback"),
            hmm_student_df=_raw(5.0, "hmm_student_df"),
            hmm_crisis_vol_mult=_raw(2.0, "hmm_crisis_vol_mult"),
        ),
        vol=VolConfig(
            lookback=_scaled(168, "vol_lookback"),
            rank_window=_scaled(1000, "vol_rank_window", floor=100),
        ),
        hilbert=HilbertConfig(
            min_period=_raw(10, "hilbert_min_period"),
            max_period=_raw(40, "hilbert_max_period"),
            stability_bars=_scaled(10, "hilbert_stability_bars", floor=3),
        ),
        ewma_vol=EWMAVolConfig(
            decay_factor=_raw(0.94, "ewma_decay_factor"),
            min_periods=_scaled(20, "ewma_min_periods", floor=5),
        ),
        trend=TrendStrengthConfig(
            lookback=_scaled(20, "trend_lookback", floor=5),
        ),
    )
