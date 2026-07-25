"""Typed execution and finality contracts for pivot extractors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from libs.models.trendlines.contracts.identity import (
    PivotFinality,
    TrendlineExecutionMode,
)


@dataclass(frozen=True)
class ExtractorCapabilities:
    """Immutable execution-mode and finality declaration for an extractor."""

    supported_modes: frozenset[TrendlineExecutionMode]
    finality: PivotFinality

    def __post_init__(self) -> None:
        modes = frozenset(self.supported_modes)
        if not modes:
            raise ValueError("Extractor capabilities require at least one execution mode")
        if not all(isinstance(mode, TrendlineExecutionMode) for mode in modes):
            raise TypeError("supported_modes must contain TrendlineExecutionMode values")
        if not isinstance(self.finality, PivotFinality):
            raise TypeError("finality must be a PivotFinality value")
        object.__setattr__(self, "supported_modes", modes)


class ExtractorExecutionPolicyError(ValueError):
    """Raised when an extractor lacks or violates its execution policy."""


def normalize_execution_mode(
    mode: TrendlineExecutionMode | str,
) -> TrendlineExecutionMode:
    """Normalize a typed or serialized execution mode."""

    if isinstance(mode, TrendlineExecutionMode):
        return mode
    try:
        return TrendlineExecutionMode(str(mode).strip().lower())
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in TrendlineExecutionMode)
        raise ExtractorExecutionPolicyError(
            f"Unknown trendline execution mode {mode!r}; expected one of: {allowed}"
        ) from exc


def get_extractor_capabilities(extractor: Any) -> ExtractorCapabilities:
    """Return typed capabilities declared by an extractor class."""

    owner = extractor if isinstance(extractor, type) else type(extractor)
    capabilities = getattr(owner, "CAPABILITIES", None)
    if not isinstance(capabilities, ExtractorCapabilities):
        name = getattr(owner, "__name__", repr(owner))
        raise ExtractorExecutionPolicyError(
            f"Extractor '{name}' has no typed capability declaration"
        )
    return capabilities


def validate_extractor_capabilities(
    extractor: Any,
    execution_mode: TrendlineExecutionMode | str,
    *,
    extractor_name: str | None = None,
) -> ExtractorCapabilities:
    """Fail closed when extractor capabilities do not support requested mode."""

    mode = normalize_execution_mode(execution_mode)
    capabilities = get_extractor_capabilities(extractor)
    if mode not in capabilities.supported_modes:
        owner = extractor if isinstance(extractor, type) else type(extractor)
        label = extractor_name or getattr(owner, "__name__", repr(owner))
        supported = ", ".join(sorted(item.value for item in capabilities.supported_modes))
        raise ExtractorExecutionPolicyError(
            f"Extractor '{label}' is not supported in execution mode '{mode.value}'; "
            f"supported modes: [{supported}]; "
            f"pivot finality: '{capabilities.finality.value}'"
        )
    return capabilities


def capabilities_to_metadata(capabilities: ExtractorCapabilities) -> dict[str, Any]:
    """Serialize typed capabilities into JSON-compatible pipeline metadata."""

    return {
        "extractor_finality": capabilities.finality.value,
        "extractor_supported_modes": sorted(
            mode.value for mode in capabilities.supported_modes
        ),
    }


__all__ = [
    "ExtractorCapabilities",
    "ExtractorExecutionPolicyError",
    "PivotFinality",
    "TrendlineExecutionMode",
    "capabilities_to_metadata",
    "get_extractor_capabilities",
    "normalize_execution_mode",
    "validate_extractor_capabilities",
]
