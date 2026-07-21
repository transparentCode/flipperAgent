"""Fixed-fixture benchmark for actual public semantic ATR paths."""

from __future__ import annotations

from statistics import median
from time import perf_counter_ns
import tracemalloc

import numpy as np
import pandas as pd

from libs.models.trendline.interaction.atr import calculate_interaction_atr
from libs.models.trendline.tracking.matching import calculate_normalization_atr


def _p50(callable_, repeats: int = 500) -> float:
    samples = []
    for _ in range(repeats):
        start = perf_counter_ns()
        callable_()
        samples.append(perf_counter_ns() - start)
    return median(samples) / 1_000.0


def _peak_bytes(callable_) -> int:
    tracemalloc.start()
    callable_()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


def _report(name: str, compiled_call, python_call, *, cold_ms: float) -> None:
    compiled_result = compiled_call()
    python_result = python_call()
    assert compiled_result == python_result
    print(
        {
            "public_path": name,
            "fixture_shape": (4_096, 3),
            "window": 4_096,
            "warmup": "one compiled public-path call",
            "python_p50_us": _p50(python_call),
            "compiled_warm_p50_us": _p50(compiled_call),
            "compiled_first_call_ms": cold_ms,
            "python_peak_tracemalloc_bytes": _peak_bytes(python_call),
            "compiled_peak_tracemalloc_bytes": _peak_bytes(compiled_call),
            "parity": True,
        }
    )


def main() -> None:
    size = 4_096
    high = np.linspace(100.0, 500.0, size)
    frame = pd.DataFrame(
        {
            "high": high,
            "low": high - 2.0,
            "close": high - 1.0,
        }
    )
    def interaction_compiled():
        return calculate_interaction_atr(frame, window=size)

    def interaction_python():
        return calculate_interaction_atr(frame, window=size, compiled=False)
    start = perf_counter_ns()
    interaction_compiled()
    cold_ms = (perf_counter_ns() - start) / 1_000_000.0
    _report(
        "calculate_interaction_atr",
        interaction_compiled,
        interaction_python,
        cold_ms=cold_ms,
    )

    def normalization_compiled():
        return calculate_normalization_atr(frame, window=size)

    def normalization_python():
        return calculate_normalization_atr(frame, window=size, compiled=False)
    start = perf_counter_ns()
    normalization_compiled()
    first_ms = (perf_counter_ns() - start) / 1_000_000.0
    _report(
        "calculate_normalization_atr",
        normalization_compiled,
        normalization_python,
        cold_ms=first_ms,
    )


if __name__ == "__main__":
    main()
