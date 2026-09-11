"""Timing helpers for research-lab orchestration."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar


T = TypeVar("T")


def timed_call(function: Callable[..., T], *args: Any, **kwargs: Any) -> tuple[T, float]:
    """Call one operation and return result plus elapsed milliseconds."""

    started = perf_counter()
    result = function(*args, **kwargs)
    return result, (perf_counter() - started) * 1000.0


def elapsed_ms(started: float) -> float:
    """Convert a perf-counter start value into elapsed milliseconds."""

    return (perf_counter() - started) * 1000.0


__all__ = ["elapsed_ms", "timed_call"]
