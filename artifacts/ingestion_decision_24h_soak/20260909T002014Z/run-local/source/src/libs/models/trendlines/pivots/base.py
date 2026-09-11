"""Base contracts for trendline pivot extractors."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Protocol, Type

import pandas as pd

from libs.models.trendlines.contracts import PivotSet
from libs.models.trendlines.pivots.capabilities import ExtractorCapabilities


class PivotExtractor(Protocol):
    """Protocol implemented by pivot extraction algorithms."""

    CAPABILITIES: ClassVar[ExtractorCapabilities]

    def extract(self, df: pd.DataFrame) -> PivotSet:
        """Extract structural highs and lows from an OHLC dataframe."""


EXTRACTOR_REGISTRY: Dict[str, Type[PivotExtractor]] = {}
EXTRACTOR_CAPABILITIES: Dict[str, ExtractorCapabilities] = {}


def register_extractor(
    name: str,
    *,
    capabilities: ExtractorCapabilities,
    search_grid: List[Dict[str, Any]] | None = None,
):
    """Class decorator that registers a pivot extractor under *name*."""

    if not isinstance(capabilities, ExtractorCapabilities):
        raise TypeError("registered extractors require typed capabilities")

    def decorator(cls: type) -> type:
        EXTRACTOR_REGISTRY[name] = cls
        EXTRACTOR_CAPABILITIES[name] = capabilities
        cls.CAPABILITIES = capabilities  # type: ignore[attr-defined]
        if search_grid is not None:
            cls.SEARCH_GRID = search_grid  # type: ignore[attr-defined]
        return cls

    return decorator


__all__ = [
    "EXTRACTOR_CAPABILITIES",
    "EXTRACTOR_REGISTRY",
    "PivotExtractor",
    "register_extractor",
]
