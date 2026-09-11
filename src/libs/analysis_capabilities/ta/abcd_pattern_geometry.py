"""Explicit four-anchor ABCD pattern geometry."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ._pattern_common import (
    _finite_real,
    _utc,
    _validate_anchor_sequence,
    _validate_bar_indices,
    _validate_pattern_inputs,
)
from .swing_anchors import SwingAnchor

ABCDSequenceKind = Literal["low_high_low_high", "high_low_high_low"]


def _derived_float(value: object, expected: float, *, field_name: str) -> float:
    normalized = _finite_real(value, field_name=field_name)
    if normalized != expected:
        raise ValueError(f"{field_name} is inconsistent with anchors")
    return normalized


def _validate_snapshot(
    anchors: tuple[SwingAnchor, ...],
    indices: tuple[object, ...],
    market_as_of: object,
    sequence_kind: object,
) -> tuple[tuple[SwingAnchor, ...], tuple[int, ...], datetime, str]:
    market = _utc(market_as_of, field_name="market_as_of")
    if len(anchors) != 4:
        raise ValueError("ABCD requires exactly four anchors")
    normalized_anchors = anchors
    derived_sequence = _validate_anchor_sequence(normalized_anchors, market)
    if sequence_kind != derived_sequence:
        raise ValueError("sequence_kind is inconsistent with anchors")
    normalized_indices = _validate_bar_indices(indices)
    if len(normalized_indices) != 4:
        raise ValueError("ABCD requires exactly four bar indices")
    return normalized_anchors, normalized_indices, market, derived_sequence


@dataclass(frozen=True, slots=True)
class ABCDPatternGeometryRequest:
    """One explicit four-anchor ABCD candidate."""

    bars: tuple
    a: SwingAnchor
    b: SwingAnchor
    c: SwingAnchor
    d: SwingAnchor
    market_as_of: datetime

    def __post_init__(self) -> None:
        bars, market, _, _ = _validate_pattern_inputs(
            self.bars,
            (self.a, self.b, self.c, self.d),
            self.market_as_of,
        )
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "market_as_of", market)


@dataclass(frozen=True, slots=True)
class ABCDPatternGeometrySnapshot:
    """Immutable factual ABCD geometry at one exact cutoff."""

    market_as_of: datetime
    a: object
    b: object
    c: object
    d: object
    a_bar_index: int
    b_bar_index: int
    c_bar_index: int
    d_bar_index: int
    sequence_kind: ABCDSequenceKind
    ab_price_magnitude: float
    bc_price_magnitude: float
    cd_price_magnitude: float
    ab_bar_span: int
    bc_bar_span: int
    cd_bar_span: int
    bc_over_ab: float
    cd_over_bc: float
    cd_over_ab: float
    cd_time_over_ab: float

    def __post_init__(self) -> None:
        anchors, indices, market, _sequence = _validate_snapshot(
            (self.a, self.b, self.c, self.d),
            (self.a_bar_index, self.b_bar_index, self.c_bar_index, self.d_bar_index),
            self.market_as_of,
            self.sequence_kind,
        )
        a, b, c, d = anchors
        a_index, b_index, c_index, d_index = indices
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        cd = abs(d.price - c.price)
        ab_span = b_index - a_index
        bc_span = c_index - b_index
        cd_span = d_index - c_index
        values = (
            (self.ab_price_magnitude, ab, "ab_price_magnitude"),
            (self.bc_price_magnitude, bc, "bc_price_magnitude"),
            (self.cd_price_magnitude, cd, "cd_price_magnitude"),
            (self.bc_over_ab, bc / ab, "bc_over_ab"),
            (self.cd_over_bc, cd / bc, "cd_over_bc"),
            (self.cd_over_ab, cd / ab, "cd_over_ab"),
            (self.cd_time_over_ab, cd_span / ab_span, "cd_time_over_ab"),
        )
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in values
        )
        for field_name, value, expected in (
            ("ab_bar_span", self.ab_bar_span, ab_span),
            ("bc_bar_span", self.bc_bar_span, bc_span),
            ("cd_bar_span", self.cd_bar_span, cd_span),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value != expected:
                raise ValueError(f"{field_name} is inconsistent with anchors")
        object.__setattr__(self, "market_as_of", market)
        for field_name, value in zip(
            (
                "ab_price_magnitude",
                "bc_price_magnitude",
                "cd_price_magnitude",
                "bc_over_ab",
                "cd_over_bc",
                "cd_over_ab",
                "cd_time_over_ab",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)


def compute_abcd_pattern_geometry(
    request: ABCDPatternGeometryRequest,
) -> ABCDPatternGeometrySnapshot:
    """Compute factual four-anchor ABCD geometry."""

    if not isinstance(request, ABCDPatternGeometryRequest):
        raise TypeError("request must be ABCDPatternGeometryRequest")
    _, _, indices, sequence = _validate_pattern_inputs(
        request.bars,
        (request.a, request.b, request.c, request.d),
        request.market_as_of,
    )
    a, b, c, d = request.a, request.b, request.c, request.d
    ab = abs(b.price - a.price)
    bc = abs(c.price - b.price)
    cd = abs(d.price - c.price)
    a_index, b_index, c_index, d_index = indices
    ab_span = b_index - a_index
    bc_span = c_index - b_index
    cd_span = d_index - c_index
    return ABCDPatternGeometrySnapshot(
        market_as_of=request.market_as_of,
        a=a,
        b=b,
        c=c,
        d=d,
        a_bar_index=a_index,
        b_bar_index=b_index,
        c_bar_index=c_index,
        d_bar_index=d_index,
        sequence_kind=sequence,
        ab_price_magnitude=ab,
        bc_price_magnitude=bc,
        cd_price_magnitude=cd,
        ab_bar_span=ab_span,
        bc_bar_span=bc_span,
        cd_bar_span=cd_span,
        bc_over_ab=bc / ab,
        cd_over_bc=cd / bc,
        cd_over_ab=cd / ab,
        cd_time_over_ab=cd_span / ab_span,
    )


__all__ = (
    "ABCDPatternGeometryRequest",
    "ABCDPatternGeometrySnapshot",
    "ABCDSequenceKind",
    "compute_abcd_pattern_geometry",
)
