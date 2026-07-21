from __future__ import annotations

import numpy as np
import pytest

from libs.models.trendline.interaction.atr import numeric_true_range_mean
from libs.models.trendline.kernels.atr import true_range_mean


def test_atr_kernel_compiled_python_parity_and_repeat_determinism() -> None:
    high = np.array([10.0, 12.0, 11.0, 14.0, 13.0])
    low = np.array([8.0, 9.0, 9.5, 10.0, 11.0])
    close = np.array([9.0, 11.0, 10.0, 13.0, 12.0])
    compiled = numeric_true_range_mean(high, low, close, window=4)
    python = numeric_true_range_mean(high, low, close, window=4, compiled=False)
    assert compiled == python == true_range_mean(high, low, close, 4)
    assert compiled == numeric_true_range_mean(high, low, close, window=4)


def test_atr_kernel_minimum_irregular_values_and_wrapper_rejections() -> None:
    assert numeric_true_range_mean(np.array([2.0]), np.array([1.0]), np.array([1.5]), window=1) == 1.0
    with pytest.raises(ValueError, match="fit"):
        numeric_true_range_mean(np.array([]), np.array([]), np.array([]), window=1)
    with pytest.raises(ValueError, match="finite"):
        numeric_true_range_mean(np.array([np.nan]), np.array([1.0]), np.array([1.0]), window=1)
    with pytest.raises(ValueError, match="equal length"):
        numeric_true_range_mean(np.array([2.0]), np.array([1.0, 2.0]), np.array([1.0]), window=1)


def test_atr_kernel_causal_prefix_and_stable_operation_order() -> None:
    high = np.linspace(100.0, 130.0, 64)
    low = high - 2.0
    close = high - 1.0
    low[48:] = high[48:] - np.linspace(2.5, 6.0, 16)
    prefix = numeric_true_range_mean(high[:48], low[:48], close[:48], window=14)
    assert prefix == numeric_true_range_mean(high[:48], low[:48], close[:48], window=14, compiled=False)
    assert prefix != numeric_true_range_mean(high, low, close, window=14)
