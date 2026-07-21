"""Fixed-fixture cold/warm benchmark for the deterministic ATR kernel."""

from __future__ import annotations

from statistics import median
from time import perf_counter_ns

import numpy as np

from libs.models.trendline.kernels.atr import true_range_mean


def _p50(callable_, repeats: int = 2_000) -> float:
    samples = []
    for _ in range(repeats):
        start = perf_counter_ns()
        callable_()
        samples.append(perf_counter_ns() - start)
    return median(samples) / 1_000.0


def main() -> None:
    size = 4_096
    high = np.linspace(100.0, 500.0, size)
    low = high - 2.0
    close = high - 1.0
    start = perf_counter_ns()
    compiled = true_range_mean(high, low, close, size)
    cold_ms = (perf_counter_ns() - start) / 1_000_000.0
    python = true_range_mean.py_func(high, low, close, size)
    assert compiled == python
    print({"fixture_shape": size, "warmup": "one compiled call", "python_p50_us": _p50(lambda: true_range_mean.py_func(high, low, close, size)), "compiled_warm_p50_us": _p50(lambda: true_range_mean(high, low, close, size)), "cold_start_ms": cold_ms, "parity": True})


if __name__ == "__main__":
    main()
