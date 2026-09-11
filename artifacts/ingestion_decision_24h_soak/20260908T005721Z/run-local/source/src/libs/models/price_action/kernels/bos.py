"""K5: Break of Structure (BOS) kernel — swing-level break continuation."""

from numba import njit

from libs.models.price_action.kernel_registry import KernelSpec, register_kernel

register_kernel(
    KernelSpec(
        name="bos",
        weight_key="w_bos",
        category="continuation",
        needs_swings=True,
        param_keys=("bos_displacement_scale",),
    )
)


@njit(cache=True)
def bos_score(close, atr, i, last_sh_price, last_sl_price, bos_displacement_scale):
    """Score Break of Structure at bar *i*.

    Bullish BOS: close breaks above last swing high (was below on prior bar).
    Bearish BOS: close breaks below last swing low (was above on prior bar).

    Returns continuous score in [-1, +1].
    """
    if i < 1:
        return 0.0

    atr_val = atr[i]
    if atr_val <= 0.0:
        return 0.0

    score = 0.0

    # Bullish BOS  (NaN check via self-comparison)
    if last_sh_price == last_sh_price:
        if close[i] > last_sh_price and close[i - 1] <= last_sh_price:
            displacement = (close[i] - last_sh_price) / (atr_val + 1e-10)
            score = min(1.0, displacement * bos_displacement_scale)

    # Bearish BOS
    if last_sl_price == last_sl_price:
        if close[i] < last_sl_price and close[i - 1] >= last_sl_price:
            displacement = (last_sl_price - close[i]) / (atr_val + 1e-10)
            s = -min(1.0, displacement * bos_displacement_scale)
            if abs(s) > abs(score):
                score = s

    return score
