"""Validated semantic ATR adapter shared by interaction and matching."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from ..domain.validation import ContractValidationError
from ..kernels.atr import true_range_mean


INTERACTION_ATR_METHOD = "simple_true_range_mean_v1"


@dataclass(frozen=True)
class InteractionAtr:
    value: float
    method: str
    sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise ContractValidationError("interaction ATR value must be numeric")
        value = float(self.value)
        if not math.isfinite(value) or value <= 0.0:
            raise ContractValidationError("interaction ATR must be finite and positive")
        if not isinstance(self.method, str) or not self.method:
            raise ContractValidationError("interaction ATR method must be non-empty")
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 1
        ):
            raise ContractValidationError(
                "interaction ATR sample_count must be a positive integer"
            )
        object.__setattr__(self, "value", value)


def numeric_true_range_mean(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    window: int,
    compiled: bool = True,
) -> float:
    """Validate primitive inputs and dispatch one shared Python/Numba algorithm."""

    arrays = tuple(np.asarray(value, dtype=np.float64) for value in (high, low, close))
    if any(value.ndim != 1 for value in arrays) or len(
        {value.size for value in arrays}
    ) != 1:
        raise ValueError("ATR arrays must be one-dimensional and equal length")
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("ATR window must be an integer >= 1")
    if arrays[0].size < 1:
        raise ValueError("ATR window must fit the input arrays")
    if any(not np.isfinite(value).all() for value in arrays):
        raise ValueError("ATR arrays must contain only finite values")
    effective_window = min(window, arrays[0].size)
    kernel = true_range_mean if compiled else true_range_mean.py_func
    return float(kernel(*arrays, effective_window))


def _atr_arrays(ohlcv: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return tuple(
        ohlcv[column].to_numpy(dtype=np.float64, copy=False)
        for column in ("high", "low", "close")
    )


def calculate_interaction_atr(
    ohlcv: pd.DataFrame,
    *,
    window: int,
    compiled: bool = True,
) -> InteractionAtr:
    """Compute interaction-owned causal simple true-range mean."""

    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ContractValidationError("interaction ATR window must be an integer >= 1")
    if not isinstance(ohlcv, pd.DataFrame) or len(ohlcv) < 2:
        raise ContractValidationError(
            "at least two confirmed bars are required for interaction ATR"
        )
    required = {"high", "low", "close"}
    if required.difference(ohlcv.columns):
        raise ContractValidationError(
            "interaction ATR requires high, low, and close columns"
        )
    try:
        arrays = _atr_arrays(ohlcv)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            "interaction ATR inputs must be numeric"
        ) from exc
    if any(not np.isfinite(value).all() for value in arrays):
        raise ContractValidationError("interaction ATR inputs must be finite")
    effective_window = min(window, len(ohlcv))
    return InteractionAtr(
        value=numeric_true_range_mean(
            *arrays,
            window=effective_window,
            compiled=compiled,
        ),
        method=INTERACTION_ATR_METHOD,
        sample_count=effective_window,
    )


__all__ = [
    "INTERACTION_ATR_METHOD",
    "InteractionAtr",
    "calculate_interaction_atr",
    "numeric_true_range_mean",
]
