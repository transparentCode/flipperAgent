"""
Configuration defaults for RegimeClassificationModel kernels.

Only 5 structural hyperparameters remain Optuna-worthy.
Everything else is either adaptive (computed from data) or fixed.
"""

from __future__ import annotations

from dataclasses import dataclass


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
