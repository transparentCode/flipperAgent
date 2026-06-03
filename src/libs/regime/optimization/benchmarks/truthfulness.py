"""Supplemental truthfulness diagnostics for regime benchmarks.

These metrics are intentionally kept out of the optimization objective until
they are validated. They answer four narrow questions:

1. Does the current regime output beat a simple price-only baseline?
2. Does it beat other trivial alternatives such as persistence or shuffling?
3. Is ``p_trending`` calibrated against an explicit trend proxy?
4. Are the failures concentrated in one weak null model or across many?
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import predictive_power, strategy_utility

_BASELINE_WEIGHT_MAP = {
    "CLEAN_TREND_BULL": 1.0,
    "CLEAN_TREND_BEAR": -1.0,
    "CLEAN_TREND_FLAT": 0.0,
    "VOLATILE_TREND_BULL": 0.6,
    "VOLATILE_TREND_BEAR": -0.6,
    "VOLATILE_TREND_FLAT": 0.0,
    "QUIET_MR_RANGE": 0.3,
    "QUIET_MR_SQUEEZE": 0.0,
    "CHOPPY": 0.0,
}


def compute(
    features_df: pd.DataFrame,
    returns: np.ndarray,
    *,
    price_df: pd.DataFrame | None = None,
    primary_horizon: int = 4,
    calibration_bins: int = 10,
    random_seed: int = 42,
) -> dict:
    """Compute supplemental truthfulness diagnostics.

    Returns:
    - ``baseline_*``: simple return/vol grid baseline lift
    - per-baseline lifts for persistence, vol-only, ADX, and shuffled labels
    - ``proxy_trend_*``: calibration diagnostics
    - ``passed_baseline_gate``: legacy simple-baseline gate
    - ``passed_strict_baseline_gate``: all available baselines cleared
    """
    required = {"regime", "p_trending"}
    if not required.issubset(features_df.columns) or len(returns) < 20:
        return _empty()

    n = min(len(features_df), len(returns))
    actual = features_df.iloc[-n:].copy()
    ret = np.asarray(returns[-n:], dtype=float)

    actual_t1 = strategy_utility.compute(actual, ret)
    actual_t2 = predictive_power.compute(actual, ret, primary_horizon=primary_horizon)

    baseline_metrics = {
        "simple": _baseline_lift(
            actual_t1,
            actual_t2,
            _simple_baseline_features(ret, actual.index),
            ret,
            primary_horizon=primary_horizon,
        ),
        "persistence": _baseline_lift(
            actual_t1,
            actual_t2,
            _persistence_baseline_features(actual),
            ret,
            primary_horizon=primary_horizon,
        ),
        "vol_only": _baseline_lift(
            actual_t1,
            actual_t2,
            _vol_percentile_baseline_features(ret, actual.index),
            ret,
            primary_horizon=primary_horizon,
        ),
        "shuffled": _baseline_lift(
            actual_t1,
            actual_t2,
            _shuffled_baseline_features(actual, seed=random_seed),
            ret,
            primary_horizon=primary_horizon,
        ),
    }
    if price_df is not None and {"high", "low", "close"}.issubset(price_df.columns):
        price = price_df.iloc[-n:].copy()
        baseline_metrics["adx"] = _baseline_lift(
            actual_t1,
            actual_t2,
            _adx_baseline_features(price, actual.index),
            ret,
            primary_horizon=primary_horizon,
        )
    else:
        baseline_metrics["adx"] = {"sharpe_lift": 0.0, "ic_lift": 0.0, "available": False}

    simple_metrics = baseline_metrics["simple"]
    baseline_sharpe_lift = simple_metrics["sharpe_lift"]
    baseline_ic_lift = simple_metrics["ic_lift"]

    proxy_labels = _trend_proxy_labels(ret, horizon=primary_horizon)
    p_trending = np.clip(actual["p_trending"].to_numpy(dtype=float), 0.0, 1.0)
    valid = np.isfinite(proxy_labels) & np.isfinite(p_trending)
    if valid.sum() < max(10, calibration_bins):
        brier_score = 1.0
        ece = 1.0
    else:
        y = proxy_labels[valid].astype(float)
        p = p_trending[valid]
        brier_score = float(np.mean((p - y) ** 2))
        ece = _expected_calibration_error(y, p, calibration_bins)

    strict_checks = [
        baseline_metrics["simple"],
        baseline_metrics["persistence"],
        baseline_metrics["vol_only"],
        baseline_metrics["shuffled"],
    ]
    if baseline_metrics["adx"]["available"]:
        strict_checks.append(baseline_metrics["adx"])
    strict_failures = sum(
        1
        for metric in strict_checks
        if metric["sharpe_lift"] < 0.0 or metric["ic_lift"] < 0.0
    )

    return {
        "baseline_sharpe_lift": float(baseline_sharpe_lift),
        "baseline_ic_lift": float(baseline_ic_lift),
        "persistence_sharpe_lift": float(baseline_metrics["persistence"]["sharpe_lift"]),
        "persistence_ic_lift": float(baseline_metrics["persistence"]["ic_lift"]),
        "vol_baseline_sharpe_lift": float(baseline_metrics["vol_only"]["sharpe_lift"]),
        "vol_baseline_ic_lift": float(baseline_metrics["vol_only"]["ic_lift"]),
        "adx_baseline_sharpe_lift": float(baseline_metrics["adx"]["sharpe_lift"]),
        "adx_baseline_ic_lift": float(baseline_metrics["adx"]["ic_lift"]),
        "shuffled_sharpe_lift": float(baseline_metrics["shuffled"]["sharpe_lift"]),
        "shuffled_ic_lift": float(baseline_metrics["shuffled"]["ic_lift"]),
        "proxy_trend_brier_score": float(brier_score),
        "proxy_trend_ece": float(ece),
        "passed_baseline_gate": bool(
            baseline_sharpe_lift >= 0.0 and baseline_ic_lift >= 0.0
        ),
        "passed_strict_baseline_gate": bool(strict_failures == 0),
        "strict_baseline_failure_count": int(strict_failures),
    }


def _baseline_lift(
    actual_t1: dict,
    actual_t2: dict,
    baseline_features: pd.DataFrame,
    returns: np.ndarray,
    *,
    primary_horizon: int,
) -> dict:
    baseline_t1 = strategy_utility.compute(baseline_features, returns)
    baseline_t2 = predictive_power.compute(
        baseline_features,
        returns,
        primary_horizon=primary_horizon,
    )
    return {
        "sharpe_lift": float(
            actual_t1["sharpe_improvement"] - baseline_t1["sharpe_improvement"]
        ),
        "ic_lift": float(
            actual_t2["forward_return_ic"] - baseline_t2["forward_return_ic"]
        ),
        "available": True,
    }


def _simple_baseline_features(
    returns: np.ndarray,
    index: pd.Index,
    *,
    trend_window: int = 20,
    vol_window: int = 24,
    trend_z_threshold: float = 0.75,
    squeeze_percentile: float = 35.0,
) -> pd.DataFrame:
    """Build a simple price-only baseline regime series."""
    ret_s = pd.Series(returns, index=index, dtype=float)

    trend_mean = ret_s.rolling(trend_window, min_periods=5).mean()
    trend_std = ret_s.rolling(trend_window, min_periods=5).std().replace(0.0, np.nan)
    trend_z = (trend_mean / (trend_std + 1e-10)).fillna(0.0)

    realized_vol = ret_s.rolling(vol_window, min_periods=5).std().fillna(0.0)
    vol_rank = realized_vol.rolling(vol_window, min_periods=5).apply(
        lambda x: float(np.mean(x <= x[-1]) * 100.0),
        raw=True,
    ).fillna(50.0)

    regimes: list[str] = []
    p_trending: list[float] = []
    position_scale: list[float] = []

    for z, vol_pct in zip(trend_z.to_numpy(), vol_rank.to_numpy()):
        if z >= trend_z_threshold:
            regime = "CLEAN_TREND_BULL" if vol_pct < 70.0 else "VOLATILE_TREND_BULL"
        elif z <= -trend_z_threshold:
            regime = "CLEAN_TREND_BEAR" if vol_pct < 70.0 else "VOLATILE_TREND_BEAR"
        elif vol_pct <= squeeze_percentile:
            regime = "QUIET_MR_SQUEEZE"
        elif vol_pct <= 50.0:
            regime = "QUIET_MR_RANGE"
        else:
            regime = "CHOPPY"

        regimes.append(regime)
        p = min(1.0, abs(float(z)) / (trend_z_threshold * 2.0))
        p_trending.append(p)
        position_scale.append(_BASELINE_WEIGHT_MAP[regime])

    return pd.DataFrame(
        {
            "regime": regimes,
            "p_trending": p_trending,
            "position_scale": position_scale,
        },
        index=index,
    )


def _persistence_baseline_features(actual: pd.DataFrame) -> pd.DataFrame:
    """Lag the actual regime outputs by one bar."""
    baseline = actual.copy()
    baseline["regime"] = actual["regime"].shift(1).fillna(actual["regime"].iloc[0])
    baseline["p_trending"] = (
        actual["p_trending"].shift(1).fillna(actual["p_trending"].iloc[0]).clip(0.0, 1.0)
    )
    if "position_scale" in actual.columns:
        baseline["position_scale"] = (
            actual["position_scale"].shift(1).fillna(actual["position_scale"].iloc[0])
        )
    else:
        baseline["position_scale"] = [
            _BASELINE_WEIGHT_MAP.get(regime, 0.0) for regime in baseline["regime"]
        ]
    return baseline[["regime", "p_trending", "position_scale"]]


def _vol_percentile_baseline_features(
    returns: np.ndarray,
    index: pd.Index,
    *,
    vol_window: int = 24,
    squeeze_percentile: float = 30.0,
) -> pd.DataFrame:
    """Volatility-only null model with no directional intelligence."""
    ret_s = pd.Series(returns, index=index, dtype=float)
    realized_vol = ret_s.rolling(vol_window, min_periods=5).std().fillna(0.0)
    vol_rank = realized_vol.rolling(vol_window, min_periods=5).apply(
        lambda x: float(np.mean(x <= x[-1]) * 100.0),
        raw=True,
    ).fillna(50.0)

    regimes = np.where(
        vol_rank >= 70.0,
        "CHOPPY",
        np.where(vol_rank <= squeeze_percentile, "QUIET_MR_SQUEEZE", "QUIET_MR_RANGE"),
    )
    position_scale = np.where(vol_rank >= 70.0, 0.0, 0.2)
    p_trending = np.where(vol_rank >= 70.0, 0.15, 0.25)

    return pd.DataFrame(
        {
            "regime": regimes,
            "p_trending": p_trending,
            "position_scale": position_scale,
        },
        index=index,
    )


def _adx_baseline_features(
    price_df: pd.DataFrame,
    index: pd.Index,
    *,
    adx_window: int = 14,
    adx_threshold: float = 22.0,
) -> pd.DataFrame:
    """Simple directional baseline from ADX and DI spread."""
    high = price_df["high"].astype(float)
    low = price_df["low"].astype(float)
    close = price_df["close"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat(
        [
            (high - low),
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(adx_window, min_periods=adx_window).mean()

    plus_di = 100.0 * pd.Series(plus_dm, index=index).rolling(
        adx_window, min_periods=adx_window
    ).mean() / (atr + 1e-10)
    minus_di = 100.0 * pd.Series(minus_dm, index=index).rolling(
        adx_window, min_periods=adx_window
    ).mean() / (atr + 1e-10)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(adx_window, min_periods=adx_window).mean().fillna(0.0)

    direction = np.where(plus_di > minus_di, "BULL", "BEAR")
    trending = adx >= adx_threshold
    regimes = np.where(
        trending & (direction == "BULL"),
        "CLEAN_TREND_BULL",
        np.where(
            trending & (direction == "BEAR"),
            "CLEAN_TREND_BEAR",
            "QUIET_MR_RANGE",
        ),
    )
    position_scale = np.where(
        trending & (direction == "BULL"),
        0.8,
        np.where(trending & (direction == "BEAR"), -0.8, 0.2),
    )
    p_trending = np.clip(adx / 50.0, 0.0, 1.0)

    return pd.DataFrame(
        {
            "regime": regimes,
            "p_trending": p_trending,
            "position_scale": position_scale,
        },
        index=index,
    )


def _shuffled_baseline_features(actual: pd.DataFrame, *, seed: int) -> pd.DataFrame:
    """Shuffle coherent regime rows as a null model."""
    rng = np.random.default_rng(seed)
    order = np.arange(len(actual))
    rng.shuffle(order)
    shuffled = actual.iloc[order][["regime", "p_trending", "position_scale"]].copy()
    shuffled.index = actual.index
    return shuffled


def _trend_proxy_labels(
    returns: np.ndarray,
    *,
    horizon: int = 4,
    efficiency_threshold: float = 0.6,
) -> np.ndarray:
    """Binary proxy: 1 when forward move is directionally efficient."""
    n = len(returns)
    labels = np.full(n, np.nan)
    for i in range(n - horizon):
        window = returns[i + 1 : i + horizon + 1]
        path = np.abs(window).sum()
        if path <= 1e-10:
            labels[i] = 0.0
            continue
        efficiency = abs(window.sum()) / path
        labels[i] = 1.0 if efficiency >= efficiency_threshold else 0.0
    return labels


def _expected_calibration_error(
    labels: np.ndarray,
    probs: np.ndarray,
    n_bins: int,
) -> float:
    """Simple equal-width ECE on [0, 1]."""
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = len(labels)
    error = 0.0
    for left, right in zip(bin_edges[:-1], bin_edges[1:]):
        if right == 1.0:
            mask = (probs >= left) & (probs <= right)
        else:
            mask = (probs >= left) & (probs < right)
        if not np.any(mask):
            continue
        acc = labels[mask].mean()
        conf = probs[mask].mean()
        error += abs(acc - conf) * (mask.sum() / total)
    return float(error)


def _empty() -> dict:
    return {
        "baseline_sharpe_lift": 0.0,
        "baseline_ic_lift": 0.0,
        "persistence_sharpe_lift": 0.0,
        "persistence_ic_lift": 0.0,
        "vol_baseline_sharpe_lift": 0.0,
        "vol_baseline_ic_lift": 0.0,
        "adx_baseline_sharpe_lift": 0.0,
        "adx_baseline_ic_lift": 0.0,
        "shuffled_sharpe_lift": 0.0,
        "shuffled_ic_lift": 0.0,
        "proxy_trend_brier_score": 1.0,
        "proxy_trend_ece": 1.0,
        "passed_baseline_gate": False,
        "passed_strict_baseline_gate": False,
        "strict_baseline_failure_count": 0,
    }
