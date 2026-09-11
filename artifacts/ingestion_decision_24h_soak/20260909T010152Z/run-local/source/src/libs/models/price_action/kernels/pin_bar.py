"""K3: Pin Bar / Rejection kernel — long-wick rejection candle."""

from numba import njit

from libs.models.price_action.kernel_registry import KernelSpec, register_kernel

register_kernel(
    KernelSpec(
        name="pin_bar",
        weight_key="w_pin",
        category="reversal",
        needs_swings=False,
        param_keys=(
            "pin_wick_body_ratio",
            "pin_wick_dominance",
            "pin_min_range_atr",
            "pin_strength_scale",
        ),
    )
)


@njit(cache=True)
def pin_bar_score(
    open_, high, low, close, atr, i,
    pin_wick_body_ratio,
    pin_wick_dominance,
    pin_min_range_atr,
    pin_strength_scale,
):
    """Score pin bar / rejection at bar *i*.

    Bullish pin: long lower wick, small body, small upper wick.
    Bearish pin: long upper wick, small body, small lower wick.

    Returns continuous score in [-1, +1].
    """
    range_ = high[i] - low[i]
    if range_ <= 0.0:
        return 0.0

    atr_val = atr[i]
    if atr_val <= 0.0:
        return 0.0

    # Noise filter: candle must be at least pin_min_range_atr of ATR
    if range_ < atr_val * pin_min_range_atr:
        return 0.0

    body = abs(close[i] - open_[i])
    o = open_[i]
    c = close[i]
    body_high = max(o, c)
    body_low = min(o, c)
    upper_wick = high[i] - body_high
    lower_wick = body_low - low[i]

    # Bullish pin bar: long lower wick
    if lower_wick > body * pin_wick_body_ratio and lower_wick > upper_wick * pin_wick_dominance:
        return min(1.0, (lower_wick / range_) * pin_strength_scale)

    # Bearish pin bar: long upper wick
    if upper_wick > body * pin_wick_body_ratio and upper_wick > lower_wick * pin_wick_dominance:
        return -min(1.0, (upper_wick / range_) * pin_strength_scale)

    return 0.0
