"""Explicit four-anchor triangle boundary geometry."""

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

TriangleApexRelation = Literal["future", "at_or_before_latest", "parallel"]


def _derived_float(value: object, expected: float, *, field_name: str) -> float:
    normalized = _finite_real(value, field_name=field_name)
    if normalized != expected:
        raise ValueError(f"{field_name} is inconsistent with anchors")
    return normalized


def _line_value(
    first: SwingAnchor,
    second: SwingAnchor,
    first_index: int,
    second_index: int,
    at_index: float,
) -> float:
    slope = (second.price - first.price) / (second_index - first_index)
    return first.price + slope * (at_index - first_index)


def _boundary_pairs(
    anchors: tuple[SwingAnchor, ...],
    indices: tuple[int, ...],
) -> tuple[
    tuple[SwingAnchor, SwingAnchor],
    tuple[int, int],
    tuple[SwingAnchor, SwingAnchor],
    tuple[int, int],
]:
    a, b, c, d = anchors
    a_index, b_index, c_index, d_index = indices
    if a.kind == "swing_high":
        return (
            (a, c),
            (a_index, c_index),
            (b, d),
            (b_index, d_index),
        )
    return (
        (b, d),
        (b_index, d_index),
        (a, c),
        (a_index, c_index),
    )


@dataclass(frozen=True, slots=True)
class TrianglePatternGeometryRequest:
    """One explicit four-anchor alternating triangle candidate."""

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
        if self.a.kind != self.c.kind or self.b.kind != self.d.kind:
            raise ValueError("triangle anchors must alternate same-side pairs")
        if self.a.kind == self.b.kind:
            raise ValueError("triangle boundaries must use opposite anchor kinds")
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "market_as_of", market)


@dataclass(frozen=True, slots=True)
class TrianglePatternGeometrySnapshot:
    """Immutable factual triangle boundary geometry at one cutoff."""

    market_as_of: datetime
    a: SwingAnchor
    b: SwingAnchor
    c: SwingAnchor
    d: SwingAnchor
    a_bar_index: int
    b_bar_index: int
    c_bar_index: int
    d_bar_index: int
    upper_first_anchor: SwingAnchor
    upper_second_anchor: SwingAnchor
    lower_first_anchor: SwingAnchor
    lower_second_anchor: SwingAnchor
    upper_slope_per_bar: float
    lower_slope_per_bar: float
    upper_price_at_d: float
    lower_price_at_d: float
    boundary_gap_at_d: float
    apex_bar_position: float | None
    apex_price: float | None
    apex_relation: TriangleApexRelation

    def __post_init__(self) -> None:
        market = _utc(self.market_as_of, field_name="market_as_of")
        anchors = (self.a, self.b, self.c, self.d)
        sequence = _validate_anchor_sequence(anchors, market)
        if sequence not in ("high_low_high_low", "low_high_low_high"):
            raise ValueError("triangle anchors must alternate high and low")
        indices = _validate_bar_indices(
            (self.a_bar_index, self.b_bar_index, self.c_bar_index, self.d_bar_index)
        )
        if len(indices) != 4:
            raise ValueError("triangle requires exactly four bar indices")
        upper, upper_indices, lower, lower_indices = _boundary_pairs(anchors, indices)
        if (
            self.upper_first_anchor,
            self.upper_second_anchor,
            self.lower_first_anchor,
            self.lower_second_anchor,
        ) != (upper[0], upper[1], lower[0], lower[1]):
            raise ValueError("triangle boundary anchors are inconsistent")
        if self.upper_first_anchor.kind != "swing_high":
            raise ValueError("upper boundary must use swing highs")
        if self.lower_first_anchor.kind != "swing_low":
            raise ValueError("lower boundary must use swing lows")
        upper_first_index, upper_second_index = upper_indices
        lower_first_index, lower_second_index = lower_indices
        d_index = indices[-1]
        upper_slope = _finite_real(
            (upper[1].price - upper[0].price)
            / (upper_second_index - upper_first_index),
            field_name="upper_slope_per_bar",
        )
        lower_slope = _finite_real(
            (lower[1].price - lower[0].price)
            / (lower_second_index - lower_first_index),
            field_name="lower_slope_per_bar",
        )
        upper_at_d = _finite_real(
            _line_value(
                upper[0],
                upper[1],
                upper_first_index,
                upper_second_index,
                d_index,
            ),
            field_name="upper_price_at_d",
        )
        lower_at_d = _finite_real(
            _line_value(
                lower[0],
                lower[1],
                lower_first_index,
                lower_second_index,
                d_index,
            ),
            field_name="lower_price_at_d",
        )
        if upper_at_d <= lower_at_d:
            raise ValueError("triangle boundaries must remain ordered at d")
        gap = upper_at_d - lower_at_d
        if upper_slope == lower_slope:
            expected_relation = "parallel"
            if self.apex_bar_position is not None or self.apex_price is not None:
                raise ValueError("parallel triangle boundaries have no apex")
        else:
            apex_bar = (
                lower[0].price
                - upper[0].price
                + upper_slope * upper_first_index
                - lower_slope * lower_first_index
            ) / (upper_slope - lower_slope)
            apex_price = upper[0].price + upper_slope * (apex_bar - upper_first_index)
            apex_bar = _finite_real(apex_bar, field_name="apex_bar_position")
            apex_price = _finite_real(apex_price, field_name="apex_price")
            expected_relation = (
                "future" if apex_bar > d_index else "at_or_before_latest"
            )
            if self.apex_bar_position is None or self.apex_price is None:
                raise ValueError("non-parallel triangle boundaries require an apex")
            _derived_float(
                self.apex_bar_position,
                apex_bar,
                field_name="apex_bar_position",
            )
            _derived_float(self.apex_price, apex_price, field_name="apex_price")
        if self.apex_relation != expected_relation:
            raise ValueError("apex_relation is inconsistent with boundary slopes")
        values = (
            (self.upper_slope_per_bar, upper_slope, "upper_slope_per_bar"),
            (self.lower_slope_per_bar, lower_slope, "lower_slope_per_bar"),
            (self.upper_price_at_d, upper_at_d, "upper_price_at_d"),
            (self.lower_price_at_d, lower_at_d, "lower_price_at_d"),
            (self.boundary_gap_at_d, gap, "boundary_gap_at_d"),
        )
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in values
        )
        object.__setattr__(self, "market_as_of", market)
        for field_name, value in zip(
            (
                "upper_slope_per_bar",
                "lower_slope_per_bar",
                "upper_price_at_d",
                "lower_price_at_d",
                "boundary_gap_at_d",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)
        if self.apex_bar_position is not None:
            object.__setattr__(
                self,
                "apex_bar_position",
                _finite_real(
                    self.apex_bar_position,
                    field_name="apex_bar_position",
                ),
            )
        if self.apex_price is not None:
            object.__setattr__(
                self,
                "apex_price",
                _finite_real(self.apex_price, field_name="apex_price"),
            )


def compute_triangle_pattern_geometry(
    request: TrianglePatternGeometryRequest,
) -> TrianglePatternGeometrySnapshot:
    """Compute factual triangle boundaries using bar ordinals."""

    if not isinstance(request, TrianglePatternGeometryRequest):
        raise TypeError("request must be TrianglePatternGeometryRequest")
    _, _, indices, _ = _validate_pattern_inputs(
        request.bars,
        (request.a, request.b, request.c, request.d),
        request.market_as_of,
    )
    anchors = (request.a, request.b, request.c, request.d)
    upper, upper_indices, lower, lower_indices = _boundary_pairs(anchors, indices)
    upper_slope = (upper[1].price - upper[0].price) / (
        upper_indices[1] - upper_indices[0]
    )
    lower_slope = (lower[1].price - lower[0].price) / (
        lower_indices[1] - lower_indices[0]
    )
    d_index = indices[-1]
    upper_at_d = _line_value(
        upper[0],
        upper[1],
        upper_indices[0],
        upper_indices[1],
        d_index,
    )
    lower_at_d = _line_value(
        lower[0],
        lower[1],
        lower_indices[0],
        lower_indices[1],
        d_index,
    )
    if upper_slope == lower_slope:
        apex_bar = None
        apex_price = None
        relation = "parallel"
    else:
        apex_bar = (
            lower[0].price
            - upper[0].price
            + upper_slope * upper_indices[0]
            - lower_slope * lower_indices[0]
        ) / (upper_slope - lower_slope)
        apex_price = upper[0].price + upper_slope * (apex_bar - upper_indices[0])
        relation = "future" if apex_bar > d_index else "at_or_before_latest"
    return TrianglePatternGeometrySnapshot(
        market_as_of=request.market_as_of,
        a=request.a,
        b=request.b,
        c=request.c,
        d=request.d,
        a_bar_index=indices[0],
        b_bar_index=indices[1],
        c_bar_index=indices[2],
        d_bar_index=indices[3],
        upper_first_anchor=upper[0],
        upper_second_anchor=upper[1],
        lower_first_anchor=lower[0],
        lower_second_anchor=lower[1],
        upper_slope_per_bar=upper_slope,
        lower_slope_per_bar=lower_slope,
        upper_price_at_d=upper_at_d,
        lower_price_at_d=lower_at_d,
        boundary_gap_at_d=upper_at_d - lower_at_d,
        apex_bar_position=apex_bar,
        apex_price=apex_price,
        apex_relation=relation,
    )


__all__ = (
    "TriangleApexRelation",
    "TrianglePatternGeometryRequest",
    "TrianglePatternGeometrySnapshot",
    "compute_triangle_pattern_geometry",
)
