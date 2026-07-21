"""Canonical discovered-line candidate contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .enums import FamilyRole, _role
from .geometry import AnchorRef, LineGeometry
from .validation import (
    ContractValidationError,
    _decode,
    _freeze_mapping,
    _integer,
    _number,
    _optional_integer,
    _optional_number,
    _primitive,
    _required,
    _string,
    parse_utc_isoformat,
    require_utc,
)

@dataclass(frozen=True)
class LineDiagnostics:
    raw_score: float
    normalized_quality: float
    touch_count: int
    effective_touch_count: int
    coverage: float
    r_squared: float | None = None
    inlier_ratio: float | None = None
    residual_scale_atr: float | None = None
    cut_fraction: float | None = None
    fitter_consensus: float | None = None
    anchor_stability: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_score", _number(self.raw_score, field_name="raw_score"))
        object.__setattr__(self, "normalized_quality", _number(self.normalized_quality, field_name="normalized_quality", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "touch_count", _integer(self.touch_count, field_name="touch_count"))
        object.__setattr__(self, "effective_touch_count", _integer(self.effective_touch_count, field_name="effective_touch_count"))
        if self.effective_touch_count > self.touch_count:
            raise ContractValidationError("effective_touch_count cannot exceed touch_count")
        object.__setattr__(self, "coverage", _number(self.coverage, field_name="coverage", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "r_squared", _optional_number(self.r_squared, field_name="r_squared", maximum=1.0))
        object.__setattr__(self, "inlier_ratio", _optional_number(self.inlier_ratio, field_name="inlier_ratio", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "residual_scale_atr", _optional_number(self.residual_scale_atr, field_name="residual_scale_atr", minimum=0.0))
        object.__setattr__(self, "cut_fraction", _optional_number(self.cut_fraction, field_name="cut_fraction", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "fitter_consensus", _optional_number(self.fitter_consensus, field_name="fitter_consensus", minimum=0.0, maximum=1.0))
        object.__setattr__(self, "anchor_stability", _optional_number(self.anchor_stability, field_name="anchor_stability", minimum=0.0, maximum=1.0))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineDiagnostics":
        return _decode("LineDiagnostics", value, lambda item: cls(
            raw_score=_required(item, "raw_score", owner="LineDiagnostics"),
            normalized_quality=_required(item, "normalized_quality", owner="LineDiagnostics"),
            touch_count=_required(item, "touch_count", owner="LineDiagnostics"),
            effective_touch_count=_required(item, "effective_touch_count", owner="LineDiagnostics"),
            coverage=_required(item, "coverage", owner="LineDiagnostics"),
            r_squared=item.get("r_squared"), inlier_ratio=item.get("inlier_ratio"),
            residual_scale_atr=item.get("residual_scale_atr"), cut_fraction=item.get("cut_fraction"),
            fitter_consensus=item.get("fitter_consensus"), anchor_stability=item.get("anchor_stability"),
        ))


@dataclass(frozen=True)
class LineCandidate:
    candidate_id: str
    asset: str
    timeframe: str
    observed_at: datetime
    geometry: LineGeometry
    anchors: tuple[AnchorRef, ...]
    role: FamilyRole | str
    method: str
    provider: str
    diagnostics: LineDiagnostics
    source_line_index: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("candidate_id", "asset", "timeframe", "method", "provider"):
            object.__setattr__(self, name, _string(getattr(self, name), field_name=name))
        object.__setattr__(self, "observed_at", require_utc(self.observed_at, field_name="observed_at"))
        if not isinstance(self.geometry, LineGeometry) or not isinstance(self.diagnostics, LineDiagnostics):
            raise ContractValidationError("candidate geometry and diagnostics must use canonical contracts")
        anchors = tuple(self.anchors)
        if len(anchors) < 2 or any(not isinstance(anchor, AnchorRef) for anchor in anchors):
            raise ContractValidationError("a line candidate requires at least two anchors")
        if len({anchor.anchor_id for anchor in anchors}) != len(anchors):
            raise ContractValidationError("line candidate anchor IDs must be unique")
        if any(anchor.confirmation_time > self.observed_at for anchor in anchors):
            raise ContractValidationError("line candidate contains an anchor confirmed after observed_at")
        object.__setattr__(self, "anchors", anchors)
        object.__setattr__(self, "role", _role(self.role))
        object.__setattr__(self, "source_line_index", _optional_integer(self.source_line_index, field_name="source_line_index"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, field_name="metadata"))

    def to_dict(self) -> dict[str, Any]:
        return _primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineCandidate":
        return _decode("LineCandidate", value, lambda item: cls(
            candidate_id=_required(item, "candidate_id", owner="LineCandidate"), asset=_required(item, "asset", owner="LineCandidate"),
            timeframe=_required(item, "timeframe", owner="LineCandidate"),
            observed_at=parse_utc_isoformat(_required(item, "observed_at", owner="LineCandidate"), field_name="observed_at"),
            geometry=LineGeometry.from_dict(_required(item, "geometry", owner="LineCandidate")),
            anchors=tuple(AnchorRef.from_dict(anchor) for anchor in _required(item, "anchors", owner="LineCandidate")),
            role=_required(item, "role", owner="LineCandidate"), method=_required(item, "method", owner="LineCandidate"),
            provider=_required(item, "provider", owner="LineCandidate"),
            diagnostics=LineDiagnostics.from_dict(_required(item, "diagnostics", owner="LineCandidate")),
            source_line_index=item.get("source_line_index"), metadata=item.get("metadata", {}),
        ))
