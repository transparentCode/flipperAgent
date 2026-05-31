"""K4: Engulfing kernel — current body fully engulfs prior body."""

from numba import njit

from libs.models.price_action.kernel_registry import KernelSpec, register_kernel

register_kernel(
    KernelSpec(
        name="engulfing",
        weight_key="w_engulf",
        category="reversal",
        needs_swings=False,
        param_keys=("engulf_min_body_atr", "engulf_ratio_scale"),
    )
)


@njit(cache=True)
def engulfing_score(open_, high, low, close, atr, i, engulf_min_body_atr, engulf_ratio_scale):  # noqa: ARG001
    """Score engulfing pattern at bar *i*.

    Bullish engulf: current body wraps prior body, close > open.
    Bearish engulf: current body wraps prior body, close < open.

    Returns continuous score in [-1, +1].
    """
    if i < 1:
        return 0.0

    atr_val = atr[i]
    if atr_val <= 0.0:
        return 0.0

    prev_body_high = max(open_[i - 1], close[i - 1])
    prev_body_low = min(open_[i - 1], close[i - 1])
    curr_body_high = max(open_[i], close[i])
    curr_body_low = min(open_[i], close[i])

    prev_body_size = prev_body_high - prev_body_low
    curr_body_size = curr_body_high - curr_body_low

    engulfs = curr_body_low < prev_body_low and curr_body_high > prev_body_high

    if not engulfs:
        return 0.0

    if curr_body_size < atr_val * engulf_min_body_atr:
        return 0.0

    ratio = curr_body_size / (prev_body_size + 1e-10)

    if close[i] > open_[i]:
        return min(1.0, ratio * engulf_ratio_scale)
    elif close[i] < open_[i]:
        return -min(1.0, ratio * engulf_ratio_scale)

    return 0.0
