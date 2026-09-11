"""Research feature/candidate tables sourced from core SR v2 functions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def feature_table(trace: Any) -> tuple[Mapping[str, Any], ...]:
    return tuple(trace.feature_rows)


def candidate_table(trace: Any) -> tuple[Mapping[str, Any], ...]:
    return tuple(trace.candidate_rows)


__all__ = ["candidate_table", "feature_table"]
