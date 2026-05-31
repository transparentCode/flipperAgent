"""K6: Inside Bar Breakout kernel — compression then expansion."""

from numba import njit

from libs.models.price_action.kernel_registry import KernelSpec, register_kernel

register_kernel(
    KernelSpec(
        name="inside_bar",
        weight_key="w_inside",
        category="continuation",
        needs_swings=False,
        param_keys=("ib_breakout_scale",),
    )
)


@njit(cache=True)
def inside_bar_score(high, low, close, atr, i, ib_breakout_scale):
    """Score inside bar breakout at bar *i*.

    An inside bar at i-1 (range contained within i-2) followed by
    a breakout close at bar i.

    Returns continuous score in [-1, +1].
    """
    if i < 2:
        return 0.0

    atr_val = atr[i]
    if atr_val <= 0.0:
        return 0.0

    # Check if bar i-1 was an inside bar relative to bar i-2
    is_inside = high[i - 1] <= high[i - 2] and low[i - 1] >= low[i - 2]
    if not is_inside:
        return 0.0

    # Breakout detection on bar i
    if close[i] > high[i - 1]:
        return min(1.0, (close[i] - high[i - 1]) / (atr_val * ib_breakout_scale + 1e-10))
    elif close[i] < low[i - 1]:
        return -min(1.0, (low[i - 1] - close[i]) / (atr_val * ib_breakout_scale + 1e-10))

    return 0.0
