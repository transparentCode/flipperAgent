"""Deterministic registry for the bounded Phase-B candidate provider surface."""

from __future__ import annotations

from types import MappingProxyType

from ..contracts import ContractValidationError
from .fitting.pathfinding import FITTER_NAME, PathfindingLineFitter
from .pivots.fractal import PIVOT_PROVIDER_NAME, CausalFractalPivotExtractor
from .provider import LINE_PROVIDER_NAME, NativeDeterministicLineProvider


_PIVOT_PROVIDER_REGISTRY = MappingProxyType({PIVOT_PROVIDER_NAME: CausalFractalPivotExtractor})
_FITTER_REGISTRY = MappingProxyType({FITTER_NAME: PathfindingLineFitter})
_LINE_PROVIDER_REGISTRY = MappingProxyType({LINE_PROVIDER_NAME: NativeDeterministicLineProvider})


def pivot_provider_names() -> tuple[str, ...]:
    return tuple(sorted(_PIVOT_PROVIDER_REGISTRY))


def fitter_names() -> tuple[str, ...]:
    return tuple(sorted(_FITTER_REGISTRY))


def line_provider_names() -> tuple[str, ...]:
    return tuple(sorted(_LINE_PROVIDER_REGISTRY))


def get_line_provider(name: str) -> NativeDeterministicLineProvider:
    """Create a registered candidate provider without compatibility fallbacks."""

    provider_type = _LINE_PROVIDER_REGISTRY.get(name)
    if provider_type is None:
        raise ContractValidationError(f"unknown line candidate provider: {name}")
    return provider_type()
