"""K2: Liquidity Sweep kernel — stop-hunt reversal detection."""

import math

from numba import njit

from libs.models.price_action.kernel_registry import KernelSpec, register_kernel

register_kernel(
    KernelSpec(
        name="sweep",
        weight_key="w_sweep",
        category="reversal",
        needs_swings=True,
        param_keys=("sweep_wick_scale",),
    )
)


@njit(cache=True)
def sweep_score(high, low, close, i, last_sh_price, last_sl_price, sweep_wick_scale):
    """Score liquidity sweep at bar *i*.

    Bullish sweep: wick below swing low then close above it.
    Bearish sweep: wick above swing high then close below it.

    Returns continuous score in [-1, +1].
    """
    bar_range = high[i] - low[i]
    if bar_range <= 0.0:
        return 0.0

    score = 0.0

    # Bullish sweep of swing low
    if last_sl_price == last_sl_price:  # not NaN
        if low[i] < last_sl_price and close[i] > last_sl_price:
            wick_ratio = (close[i] - low[i]) / bar_range
            score = min(1.0, wick_ratio * sweep_wick_scale)

    # Bearish sweep of swing high
    if last_sh_price == last_sh_price:  # not NaN
        if high[i] > last_sh_price and close[i] < last_sh_price:
            wick_ratio = (high[i] - close[i]) / bar_range
            s = -min(1.0, wick_ratio * sweep_wick_scale)
            # If both fire (rare), take the stronger signal
            if abs(s) > abs(score):
                score = s

    return score
