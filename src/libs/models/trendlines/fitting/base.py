"""Base contracts for trendline fitters."""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, Type

import pandas as pd

from libs.models.trendlines.contracts import PivotSet, TrendlineFitResult


class TrendlineFitter(Protocol):
    """Protocol implemented by trendline fitting algorithms."""

    def fit(self, df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult:
        """Fit trendlines from an OHLC dataframe."""


FITTER_REGISTRY: Dict[str, Type[TrendlineFitter]] = {}


def register_fitter(name: str, *, search_grid: List[Dict[str, Any]] | None = None):
    """Class decorator that registers a trendline fitter under *name*."""

    def decorator(cls: type) -> type:
        FITTER_REGISTRY[name] = cls
        if search_grid is not None:
            cls.SEARCH_GRID = search_grid  # type: ignore[attr-defined]
        return cls

    return decorator


__all__ = ["FITTER_REGISTRY", "TrendlineFitter", "register_fitter"]
