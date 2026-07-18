"""Viewer configuration shared by immutable research evidence consumers."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError


VIEWER_LIBRARY = "lightweight-charts"
VIEWER_LIBRARY_VERSION = "5.2.0"


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _boolean(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError(f"{field_name} must be a boolean")
    return value


def _number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        result = 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


def _integer(value: Any, *, field_name: str, minimum: int) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class ViewerConfig:
    library: str
    library_version: str
    attribution_logo: bool
    live_zone_extent: str
    show_terminal_by_default: bool
    show_events_by_default: bool
    background_color: str
    text_color: str
    grid_color: str
    support_border_color: str
    support_fill_color: str
    resistance_border_color: str
    resistance_fill_color: str
    pending_border_color: str
    terminal_opacity: float
    zone_line_width: int

    def __post_init__(self) -> None:
        if _string(self.library, field_name="viewer.library") != VIEWER_LIBRARY:
            raise ContractValidationError("viewer.library must be lightweight-charts")
        if _string(self.library_version, field_name="viewer.library_version") != VIEWER_LIBRARY_VERSION:
            raise ContractValidationError("unsupported Lightweight Charts version")
        if not _boolean(self.attribution_logo, field_name="viewer.attribution_logo"):
            raise ContractValidationError("viewer.attribution_logo must be true")
        if _string(self.live_zone_extent, field_name="viewer.live_zone_extent") != "viewport_right_edge":
            raise ContractValidationError(
                "viewer.live_zone_extent must be viewport_right_edge"
            )
        for field_name in ("show_terminal_by_default", "show_events_by_default"):
            object.__setattr__(
                self,
                field_name,
                _boolean(getattr(self, field_name), field_name=f"viewer.{field_name}"),
            )
        for field_name in (
            "background_color",
            "text_color",
            "grid_color",
            "support_border_color",
            "support_fill_color",
            "resistance_border_color",
            "resistance_fill_color",
            "pending_border_color",
        ):
            object.__setattr__(
                self,
                field_name,
                _string(getattr(self, field_name), field_name=f"viewer.{field_name}"),
            )
        object.__setattr__(
            self,
            "terminal_opacity",
            _number(
                self.terminal_opacity,
                field_name="viewer.terminal_opacity",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "zone_line_width",
            _integer(self.zone_line_width, field_name="viewer.zone_line_width", minimum=1),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "library_version": self.library_version,
            "attribution_logo": self.attribution_logo,
            "live_zone_extent": self.live_zone_extent,
            "show_terminal_by_default": self.show_terminal_by_default,
            "show_events_by_default": self.show_events_by_default,
            "background_color": self.background_color,
            "text_color": self.text_color,
            "grid_color": self.grid_color,
            "support_border_color": self.support_border_color,
            "support_fill_color": self.support_fill_color,
            "resistance_border_color": self.resistance_border_color,
            "resistance_fill_color": self.resistance_fill_color,
            "pending_border_color": self.pending_border_color,
            "terminal_opacity": self.terminal_opacity,
            "zone_line_width": self.zone_line_width,
        }
