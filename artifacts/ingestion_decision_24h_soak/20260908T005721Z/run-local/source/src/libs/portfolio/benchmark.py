"""BenchmarkAnalyzer — alpha, beta, information ratio vs benchmark."""

from __future__ import annotations

import math

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import BenchmarkComparison

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def compute_benchmark_comparison(
    strategy_returns: list[float],
    benchmark_returns: list[float],
    periods_per_year: int = 8760,
    risk_free_rate: float = 0.0,
    start_timestamp: float = 0.0,
    end_timestamp: float = 0.0,
    benchmark_name: str = "BTC_BUY_HOLD",
) -> BenchmarkComparison:
    """Compare strategy returns vs benchmark returns.

    Both return series must be aligned (same length, same time grid).
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return BenchmarkComparison(
            benchmark_name=benchmark_name,
            strategy_return_pct=0.0,
            benchmark_return_pct=0.0,
            alpha=0.0,
            beta=0.0,
            correlation=0.0,
            information_ratio=0.0,
            tracking_error=0.0,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )

    s = strategy_returns[:n]
    b = benchmark_returns[:n]

    # Means
    mean_s = sum(s) / n
    mean_b = sum(b) / n

    # Variance and covariance (sample)
    cov_sb = sum((s[i] - mean_s) * (b[i] - mean_b) for i in range(n)) / (n - 1)
    var_b = sum((b[i] - mean_b) ** 2 for i in range(n)) / (n - 1)
    var_s = sum((s[i] - mean_s) ** 2 for i in range(n)) / (n - 1)

    # Beta
    beta = cov_sb / var_b if var_b > 0 else 0.0

    # Alpha (Jensen's) — annualized
    rf_per_period = risk_free_rate / periods_per_year
    alpha = (mean_s - rf_per_period) - beta * (mean_b - rf_per_period)
    alpha_annual = alpha * periods_per_year

    # Correlation
    std_s = math.sqrt(var_s) if var_s > 0 else 0.0
    std_b = math.sqrt(var_b) if var_b > 0 else 0.0
    correlation = cov_sb / (std_s * std_b) if (std_s > 0 and std_b > 0) else 0.0

    # Active returns
    active = [s[i] - b[i] for i in range(n)]
    mean_active = sum(active) / n
    var_active = sum((a - mean_active) ** 2 for a in active) / (n - 1) if n > 1 else 0.0
    std_active = math.sqrt(var_active) if var_active > 0 else 0.0

    # Tracking error (annualized)
    tracking_error = std_active * math.sqrt(periods_per_year)

    # Information ratio (annualized)
    information_ratio = (
        (mean_active / std_active) * math.sqrt(periods_per_year)
        if std_active > 0
        else 0.0
    )

    # Total returns (simple compounding)
    strategy_total = _compound_returns(s)
    benchmark_total = _compound_returns(b)

    return BenchmarkComparison(
        benchmark_name=benchmark_name,
        strategy_return_pct=strategy_total * 100,
        benchmark_return_pct=benchmark_total * 100,
        alpha=alpha_annual,
        beta=beta,
        correlation=correlation,
        information_ratio=information_ratio,
        tracking_error=tracking_error,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
    )


def build_benchmark_returns(
    benchmark_prices: list[tuple[float, float]],
    interval_seconds: int = 3600,
) -> list[float]:
    """Build benchmark return series from price data.

    Args:
        benchmark_prices: List of (timestamp, price) tuples, sorted ASC.
        interval_seconds: Same interval as strategy returns.

    Resamples to grid, computes log returns.
    """
    if len(benchmark_prices) < 2 or interval_seconds <= 0:
        return []

    sorted_prices = sorted(benchmark_prices, key=lambda x: x[0])
    start_ts = sorted_prices[0][0]
    end_ts = sorted_prices[-1][0]

    if end_ts <= start_ts:
        return []

    # Resample prices to grid via forward-fill
    grid_prices: list[float] = []
    ptr = 0
    current_ts = start_ts

    while current_ts <= end_ts:
        while ptr + 1 < len(sorted_prices) and sorted_prices[ptr + 1][0] <= current_ts:
            ptr += 1
        grid_prices.append(sorted_prices[ptr][1])
        current_ts += interval_seconds

    # Compute log returns
    returns: list[float] = []
    for i in range(1, len(grid_prices)):
        if grid_prices[i - 1] > 0:
            returns.append(math.log(grid_prices[i] / grid_prices[i - 1]))
        else:
            returns.append(0.0)

    return returns


def _compound_returns(log_returns: list[float]) -> float:
    """Compound log returns to get total return."""
    if not log_returns:
        return 0.0
    total_log = sum(log_returns)
    return math.exp(total_log) - 1
