"""Canonical registry seam for trendline extractors and fitters."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from libs.models.trendlines.pivots.base import EXTRACTOR_REGISTRY, PivotExtractor
from libs.models.trendlines.fitting.base import FITTER_REGISTRY, TrendlineFitter

# Trigger decorator-based registration of all implementations.
import libs.models.trendlines.pivots  # noqa: F401
import libs.models.trendlines.fitting  # noqa: F401


logger = logging.getLogger(__name__)


DEPRECATED_EXTRACTOR_ALIASES = {
	"fractals": "fractal",
	"rdp-zigzag": "rdp_zigzag",
}


DEPRECATED_FITTER_ALIASES = {
	"ols": "least_squares",
	"least-squares": "least_squares",
}


def list_extractors() -> tuple[str, ...]:
	"""Return the stable, sorted set of registered extractor names."""

	return tuple(sorted(EXTRACTOR_REGISTRY))


def build_extractor(name: str, **kwargs: Any) -> PivotExtractor:
	"""Build a registered pivot extractor by name."""

	normalized = str(name).strip().lower()
	canonical = DEPRECATED_EXTRACTOR_ALIASES.get(normalized, normalized)
	if canonical != normalized:
		logger.warning(
			"Trendlines extractor alias '%s' is deprecated; use '%s' instead.",
			normalized,
			canonical,
		)
	extractor_cls = EXTRACTOR_REGISTRY.get(canonical)
	if extractor_cls is None:
		available = ", ".join(list_extractors()) or "<none>"
		raise ValueError(f"Unknown pivot extractor '{name}'. Available extractors: {available}")
	return extractor_cls(**kwargs)


def get_extractor_search_grid(name: str) -> List[Dict[str, Any]]:
	"""Return the search grid declared by extractor *name*, or an empty list."""

	normalized = str(name).strip().lower()
	canonical = DEPRECATED_EXTRACTOR_ALIASES.get(normalized, normalized)
	cls = EXTRACTOR_REGISTRY.get(canonical)
	if cls is None:
		return []
	return list(getattr(cls, "SEARCH_GRID", []))


def list_fitters() -> tuple[str, ...]:
	"""Return the stable, sorted set of registered fitter names."""

	return tuple(sorted(FITTER_REGISTRY))


def build_fitter(name: str, **kwargs: Any) -> TrendlineFitter:
	"""Build a registered trendline fitter by name."""

	normalized = str(name).strip().lower()
	canonical = DEPRECATED_FITTER_ALIASES.get(normalized, normalized)
	if canonical != normalized:
		logger.warning(
			"Trendlines fitter alias '%s' is deprecated; use '%s' instead.",
			normalized,
			canonical,
		)
	fitter_cls = FITTER_REGISTRY.get(canonical)
	if fitter_cls is None:
		available = ", ".join(list_fitters()) or "<none>"
		raise ValueError(f"Unknown trendline fitter '{name}'. Available fitters: {available}")
	return fitter_cls(**kwargs)


def get_fitter_search_grid() -> List[Dict[str, Any]]:
	"""Return combined search grids from all registered fitters."""

	grid: List[Dict[str, Any]] = []
	for cls in FITTER_REGISTRY.values():
		grid.extend(getattr(cls, "SEARCH_GRID", []))
	return grid


__all__ = [
	"EXTRACTOR_REGISTRY",
	"DEPRECATED_EXTRACTOR_ALIASES",
	"DEPRECATED_FITTER_ALIASES",
	"FITTER_REGISTRY",
	"build_extractor",
	"build_fitter",
	"get_extractor_search_grid",
	"get_fitter_search_grid",
	"list_extractors",
	"list_fitters",
]
