"""K1: Fair Value Gap kernel — 3-candle gap detection."""

from numba import njit

from libs.models.price_action.kernel_registry import KernelSpec, register_kernel

register_kernel(
    KernelSpec(
        name="fvg",
        weight_key="w_fvg",
        category="institutional",
        needs_swings=False,
        param_keys=("fvg_atr_scale",),
    )
)


@njit(cache=True)
def fvg_score(high, low, close, atr, i, fvg_atr_scale):  # noqa: ARG001 (close unused but kept for interface consistency)
    """Score Fair Value Gap at bar *i*.

    Bullish FVG: low[i] > high[i-2]  (gap up between C1.high and C3.low).
    Bearish FVG: high[i] < low[i-2]  (gap down between C1.low and C3.high).

    Returns continuous score in [-1, +1].
    """
    if i < 2:
        return 0.0

    atr_val = atr[i]
    if atr_val <= 0.0:
        return 0.0

    # Bullish FVG: gap_size = C3.low - C1.high
    bull_gap = low[i] - high[i - 2]
    if bull_gap > 0.0:
        return min(1.0, bull_gap / (atr_val * fvg_atr_scale))

    # Bearish FVG: gap_size = C1.low - C3.high
    bear_gap = low[i - 2] - high[i]
    if bear_gap > 0.0:
        return -min(1.0, bear_gap / (atr_val * fvg_atr_scale))

    return 0.0
