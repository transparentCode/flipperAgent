"""Typed contracts for the package-local mature-trendlines viewer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VIEWER_PAYLOAD_SCHEMA_VERSION = "trendlines_research_viewer_payload_v1"
VIEWER_BUNDLE_SCHEMA_VERSION = "trendlines_research_viewer_bundle_v1"
VIEWER_DISPLAY_WINDOW_SEMANTICS_VERSION = (
    "trendlines.research-viewer-display-window.v1"
)
VIEWER_PAYLOAD_SEMANTICS_VERSION = "trendlines.research-viewer-payload.v1"
VIEWER_BUNDLE_SEMANTICS_VERSION = "trendlines.research-viewer-bundle.v1"


class TrendlineViewerContractError(ValueError):
    """Raised when viewer input, payload, or bundle contracts are invalid."""


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def require_sha256(value: Any, field_name: str) -> None:
    if not is_sha256(value):
        raise TrendlineViewerContractError(
            f"{field_name} must be a lowercase SHA-256 identity"
        )


def exact_keys(value: Any, expected: set[str], field_name: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise TrendlineViewerContractError(
            f"{field_name} keys mismatch: expected {sorted(expected)}, got {actual}"
        )


def finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrendlineViewerContractError(f"{field_name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise TrendlineViewerContractError(f"{field_name} must be finite")
    return result


def integer_seconds(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrendlineViewerContractError(
            f"{field_name} must be an integer UNIX timestamp"
        )
    return value


@dataclass(frozen=True)
class TrendlineViewerSpec:
    """One recorded replay position and bounded chart display window."""

    timeframe: str
    position: int
    display_lookback_bars: int

    def __post_init__(self) -> None:
        timeframe = str(self.timeframe).strip()
        if not timeframe:
            raise TrendlineViewerContractError("viewer timeframe is required")
        if isinstance(self.position, bool) or not isinstance(self.position, int):
            raise TrendlineViewerContractError("viewer position must be an integer")
        if self.position < 0:
            raise TrendlineViewerContractError("viewer position must be >= 0")
        if (
            isinstance(self.display_lookback_bars, bool)
            or not isinstance(self.display_lookback_bars, int)
            or self.display_lookback_bars < 1
        ):
            raise TrendlineViewerContractError(
                "display_lookback_bars must be a positive integer"
            )
        object.__setattr__(self, "timeframe", timeframe)


__all__ = [
    "VIEWER_BUNDLE_SCHEMA_VERSION",
    "VIEWER_BUNDLE_SEMANTICS_VERSION",
    "VIEWER_DISPLAY_WINDOW_SEMANTICS_VERSION",
    "VIEWER_PAYLOAD_SCHEMA_VERSION",
    "VIEWER_PAYLOAD_SEMANTICS_VERSION",
    "TrendlineViewerContractError",
    "TrendlineViewerSpec",
    "exact_keys",
    "finite_number",
    "integer_seconds",
    "is_sha256",
    "require_sha256",
]
