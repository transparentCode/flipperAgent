"""Base contracts for trendline pivot extractors."""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, Type

import pandas as pd

from app.trendlines.contracts import PivotSet


class PivotExtractor(Protocol):
    """Protocol implemented by pivot extraction algorithms."""

    def extract(self, df: pd.DataFrame) -> PivotSet:
        """Extract structural highs and lows from an OHLC dataframe."""


EXTRACTOR_REGISTRY: Dict[str, Type[PivotExtractor]] = {}


def register_extractor(name: str, *, search_grid: List[Dict[str, Any]] | None = None):
    """Class decorator that registers a pivot extractor under *name*."""

    def decorator(cls: type) -> type:
        EXTRACTOR_REGISTRY[name] = cls
        if search_grid is not None:
            cls.SEARCH_GRID = search_grid  # type: ignore[attr-defined]
        return cls

    return decorator


__all__ = ["EXTRACTOR_REGISTRY", "PivotExtractor", "register_extractor"]
