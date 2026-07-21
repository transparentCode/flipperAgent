"""ATR interaction seam."""

from .observations import INTERACTION_ATR_METHOD, InteractionAtr, calculate_interaction_atr
import numpy as np

from ..kernels.atr import true_range_mean


def numeric_true_range_mean(high: np.ndarray, low: np.ndarray, close: np.ndarray, *, window: int, compiled: bool = True) -> float:
    """Validate primitive inputs and dispatch one shared Python/Numba algorithm."""

    arrays = tuple(np.asarray(value, dtype=np.float64) for value in (high, low, close))
    if any(value.ndim != 1 for value in arrays) or len({value.size for value in arrays}) != 1:
        raise ValueError("ATR arrays must be one-dimensional and equal length")
    if isinstance(window, bool) or not isinstance(window, int) or window < 1 or window > arrays[0].size:
        raise ValueError("ATR window must fit the input arrays")
    if any(not np.isfinite(value).all() for value in arrays):
        raise ValueError("ATR arrays must contain only finite values")
    kernel = true_range_mean if compiled else true_range_mean.py_func
    return float(kernel(*arrays, window))

__all__ = ["INTERACTION_ATR_METHOD", "InteractionAtr", "calculate_interaction_atr", "numeric_true_range_mean"]
