"""Explicit five-anchor Cypher pattern measurements."""

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

CypherSequenceKind = Literal["low_high_low_high_low", "high_low_high_low_high"]


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
    if len(anchors) != 5:
        raise ValueError("Cypher requires exactly five anchors")
    sequence = _validate_anchor_sequence(anchors, market)
    if sequence_kind != sequence:
        raise ValueError("sequence_kind is inconsistent with anchors")
    normalized_indices = _validate_bar_indices(indices)
    if len(normalized_indices) != 5:
        raise ValueError("Cypher requires exactly five bar indices")
    return anchors, normalized_indices, market, sequence


@dataclass(frozen=True, slots=True)
class CypherPatternGeometryRequest:
    """One explicit five-anchor Cypher candidate."""

    bars: tuple
    x: SwingAnchor
    a: SwingAnchor
    b: SwingAnchor
    c: SwingAnchor
    d: SwingAnchor
    market_as_of: datetime

    def __post_init__(self) -> None:
        bars, market, _, _ = _validate_pattern_inputs(
            self.bars,
            (self.x, self.a, self.b, self.c, self.d),
            self.market_as_of,
        )
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "market_as_of", market)


@dataclass(frozen=True, slots=True)
class CypherPatternGeometrySnapshot:
    """Immutable factual Cypher measurements at one exact cutoff."""

    market_as_of: datetime
    x: SwingAnchor
    a: SwingAnchor
    b: SwingAnchor
    c: SwingAnchor
    d: SwingAnchor
    x_bar_index: int
    a_bar_index: int
    b_bar_index: int
    c_bar_index: int
    d_bar_index: int
    sequence_kind: CypherSequenceKind
    xa_price_magnitude: float
    ab_price_magnitude: float
    bc_price_magnitude: float
    cd_price_magnitude: float
    xc_price_magnitude: float
    xa_bar_span: int
    ab_bar_span: int
    bc_bar_span: int
    cd_bar_span: int
    ab_over_xa: float
    xc_over_xa: float
    cd_over_xc: float

    def __post_init__(self) -> None:
        anchors, indices, market, _ = _validate_snapshot(
            (self.x, self.a, self.b, self.c, self.d),
            (
                self.x_bar_index,
                self.a_bar_index,
                self.b_bar_index,
                self.c_bar_index,
                self.d_bar_index,
            ),
            self.market_as_of,
            self.sequence_kind,
        )
        x, a, b, c, d = anchors
        x_index, a_index, b_index, c_index, d_index = indices
        xa = abs(a.price - x.price)
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        cd = abs(d.price - c.price)
        xc = abs(c.price - x.price)
        if xc == 0.0:
            raise ValueError("X and C prices must differ for CD/XC")
        spans = (
            ("xa_bar_span", self.xa_bar_span, a_index - x_index),
            ("ab_bar_span", self.ab_bar_span, b_index - a_index),
            ("bc_bar_span", self.bc_bar_span, c_index - b_index),
            ("cd_bar_span", self.cd_bar_span, d_index - c_index),
        )
        for field_name, value, expected in spans:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value != expected:
                raise ValueError(f"{field_name} is inconsistent with anchors")
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in (
                (self.xa_price_magnitude, xa, "xa_price_magnitude"),
                (self.ab_price_magnitude, ab, "ab_price_magnitude"),
                (self.bc_price_magnitude, bc, "bc_price_magnitude"),
                (self.cd_price_magnitude, cd, "cd_price_magnitude"),
                (self.xc_price_magnitude, xc, "xc_price_magnitude"),
                (self.ab_over_xa, ab / xa, "ab_over_xa"),
                (self.xc_over_xa, xc / xa, "xc_over_xa"),
                (self.cd_over_xc, cd / xc, "cd_over_xc"),
            )
        )
        object.__setattr__(self, "market_as_of", market)
        for field_name, value in zip(
            (
                "xa_price_magnitude",
                "ab_price_magnitude",
                "bc_price_magnitude",
                "cd_price_magnitude",
                "xc_price_magnitude",
                "ab_over_xa",
                "xc_over_xa",
                "cd_over_xc",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)


def compute_cypher_pattern_geometry(
    request: CypherPatternGeometryRequest,
) -> CypherPatternGeometrySnapshot:
    """Compute factual five-anchor Cypher geometry."""

    if not isinstance(request, CypherPatternGeometryRequest):
        raise TypeError("request must be CypherPatternGeometryRequest")
    _, _, indices, sequence = _validate_pattern_inputs(
        request.bars,
        (request.x, request.a, request.b, request.c, request.d),
        request.market_as_of,
    )
    x, a, b, c, d = request.x, request.a, request.b, request.c, request.d
    x_index, a_index, b_index, c_index, d_index = indices
    xa = abs(a.price - x.price)
    ab = abs(b.price - a.price)
    bc = abs(c.price - b.price)
    cd = abs(d.price - c.price)
    xc = abs(c.price - x.price)
    if xc == 0.0:
        raise ValueError("X and C prices must differ for CD/XC")
    return CypherPatternGeometrySnapshot(
        market_as_of=request.market_as_of,
        x=x,
        a=a,
        b=b,
        c=c,
        d=d,
        x_bar_index=x_index,
        a_bar_index=a_index,
        b_bar_index=b_index,
        c_bar_index=c_index,
        d_bar_index=d_index,
        sequence_kind=sequence,
        xa_price_magnitude=xa,
        ab_price_magnitude=ab,
        bc_price_magnitude=bc,
        cd_price_magnitude=cd,
        xc_price_magnitude=xc,
        xa_bar_span=a_index - x_index,
        ab_bar_span=b_index - a_index,
        bc_bar_span=c_index - b_index,
        cd_bar_span=d_index - c_index,
        ab_over_xa=ab / xa,
        xc_over_xa=xc / xa,
        cd_over_xc=cd / xc,
    )


__all__ = (
    "CypherPatternGeometryRequest",
    "CypherPatternGeometrySnapshot",
    "CypherSequenceKind",
    "compute_cypher_pattern_geometry",
)
