"""Canonical registry seam for trendline extractors and fitters."""

from libs.models.trendlines.registry.registry import (
    DEPRECATED_EXTRACTOR_ALIASES,
    DEPRECATED_FITTER_ALIASES,
    EXTRACTOR_REGISTRY,
    FITTER_REGISTRY,
    build_extractor,
    build_fitter,
    canonical_extractor_name,
    get_registered_extractor_capabilities,
    get_extractor_search_grid,
    get_fitter_search_grid,
    list_extractors,
    list_extractors_for_mode,
    list_fitters,
)

__all__ = [
    "DEPRECATED_EXTRACTOR_ALIASES",
    "DEPRECATED_FITTER_ALIASES",
    "EXTRACTOR_REGISTRY",
    "FITTER_REGISTRY",
    "build_extractor",
    "build_fitter",
    "canonical_extractor_name",
    "get_registered_extractor_capabilities",
    "get_extractor_search_grid",
    "get_fitter_search_grid",
    "list_extractors",
    "list_extractors_for_mode",
    "list_fitters",
]
