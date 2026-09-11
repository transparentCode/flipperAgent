"""Explicit five-anchor XABCD pattern geometry."""

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

XABCDSequenceKind = Literal["low_high_low_high_low", "high_low_high_low_high"]


def _derived_float(value: object, expected: float, *, field_name: str) -> float:
    normalized = _finite_real(value, field_name=field_name)
    if normalized != expected:
        raise ValueError(f"{field_name} is inconsistent with anchors")
    return normalized


@dataclass(frozen=True, slots=True)
class XABCDPatternGeometryRequest:
    """One explicit five-anchor XABCD candidate."""

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
class XABCDPatternGeometrySnapshot:
    """Immutable factual XABCD geometry at one exact cutoff."""

    market_as_of: datetime
    x: object
    a: object
    b: object
    c: object
    d: object
    x_bar_index: int
    a_bar_index: int
    b_bar_index: int
    c_bar_index: int
    d_bar_index: int
    sequence_kind: XABCDSequenceKind
    xa_price_magnitude: float
    ab_price_magnitude: float
    bc_price_magnitude: float
    cd_price_magnitude: float
    ad_price_magnitude: float
    xa_bar_span: int
    ab_bar_span: int
    bc_bar_span: int
    cd_bar_span: int
    ab_over_xa: float
    bc_over_ab: float
    cd_over_bc: float
    ad_over_xa: float
    bcd_time_over_xab_time: float

    def __post_init__(self) -> None:
        market = _utc(self.market_as_of, field_name="market_as_of")
        anchors = (self.x, self.a, self.b, self.c, self.d)
        if len(anchors) != 5:
            raise ValueError("XABCD requires exactly five anchors")
        sequence = _validate_anchor_sequence(anchors, market)
        if self.sequence_kind != sequence:
            raise ValueError("sequence_kind is inconsistent with anchors")
        indices = _validate_bar_indices(
            (
                self.x_bar_index,
                self.a_bar_index,
                self.b_bar_index,
                self.c_bar_index,
                self.d_bar_index,
            )
        )
        x_index, a_index, b_index, c_index, d_index = indices
        xa = abs(self.a.price - self.x.price)
        ab = abs(self.b.price - self.a.price)
        bc = abs(self.c.price - self.b.price)
        cd = abs(self.d.price - self.c.price)
        ad = abs(self.d.price - self.a.price)
        xa_span = a_index - x_index
        ab_span = b_index - a_index
        bc_span = c_index - b_index
        cd_span = d_index - c_index
        values = (
            (self.xa_price_magnitude, xa, "xa_price_magnitude"),
            (self.ab_price_magnitude, ab, "ab_price_magnitude"),
            (self.bc_price_magnitude, bc, "bc_price_magnitude"),
            (self.cd_price_magnitude, cd, "cd_price_magnitude"),
            (self.ad_price_magnitude, ad, "ad_price_magnitude"),
            (self.ab_over_xa, ab / xa, "ab_over_xa"),
            (self.bc_over_ab, bc / ab, "bc_over_ab"),
            (self.cd_over_bc, cd / bc, "cd_over_bc"),
            (self.ad_over_xa, ad / xa, "ad_over_xa"),
            (
                self.bcd_time_over_xab_time,
                (d_index - b_index) / (b_index - x_index),
                "bcd_time_over_xab_time",
            ),
        )
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in values
        )
        for field_name, value, expected in (
            ("xa_bar_span", self.xa_bar_span, xa_span),
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
                "xa_price_magnitude",
                "ab_price_magnitude",
                "bc_price_magnitude",
                "cd_price_magnitude",
                "ad_price_magnitude",
                "ab_over_xa",
                "bc_over_ab",
                "cd_over_bc",
                "ad_over_xa",
                "bcd_time_over_xab_time",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)


def compute_xabcd_pattern_geometry(
    request: XABCDPatternGeometryRequest,
) -> XABCDPatternGeometrySnapshot:
    """Compute factual five-anchor XABCD geometry."""

    if not isinstance(request, XABCDPatternGeometryRequest):
        raise TypeError("request must be XABCDPatternGeometryRequest")
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
    ad = abs(d.price - a.price)
    return XABCDPatternGeometrySnapshot(
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
        ad_price_magnitude=ad,
        xa_bar_span=a_index - x_index,
        ab_bar_span=b_index - a_index,
        bc_bar_span=c_index - b_index,
        cd_bar_span=d_index - c_index,
        ab_over_xa=ab / xa,
        bc_over_ab=bc / ab,
        cd_over_bc=cd / bc,
        ad_over_xa=ad / xa,
        bcd_time_over_xab_time=(d_index - b_index) / (b_index - x_index),
    )


__all__ = (
    "XABCDPatternGeometryRequest",
    "XABCDPatternGeometrySnapshot",
    "XABCDSequenceKind",
    "compute_xabcd_pattern_geometry",
)
