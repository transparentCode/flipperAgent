"""Auto-import all kernel modules to trigger register_kernel() calls."""

from libs.models.price_action.kernels import (  # noqa: F401
    bos,
    engulfing,
    fvg,
    inside_bar,
    pin_bar,
    sweep,
)
