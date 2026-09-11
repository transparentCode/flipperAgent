"""Explicit five-extrema Head & Shoulders geometry."""

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

HeadShouldersOrientation = Literal["top", "bottom"]


def _derived_float(value: object, expected: float, *, field_name: str) -> float:
    normalized = _finite_real(value, field_name=field_name)
    if normalized != expected:
        raise ValueError(f"{field_name} is inconsistent with anchors")
    return normalized


def _line_value(
    left: SwingAnchor,
    right: SwingAnchor,
    left_index: int,
    right_index: int,
    at_index: int,
) -> float:
    slope = (right.price - left.price) / (right_index - left_index)
    return left.price + slope * (at_index - left_index)


def _validate_head_shoulders(
    anchors: tuple[SwingAnchor, ...],
    market_as_of: object,
    orientation: object,
    indices: tuple[object, ...],
) -> tuple[datetime, tuple[int, ...], HeadShouldersOrientation]:
    market = _utc(market_as_of, field_name="market_as_of")
    if len(anchors) != 5:
        raise ValueError("Head & Shoulders requires exactly five anchors")
    sequence = _validate_anchor_sequence(anchors, market)
    expected_orientation = "top" if anchors[0].kind == "swing_high" else "bottom"
    expected_sequence = (
        "high_low_high_low_high"
        if expected_orientation == "top"
        else "low_high_low_high_low"
    )
    if sequence != expected_sequence or orientation != expected_orientation:
        raise ValueError("orientation is inconsistent with anchor topology")
    if expected_orientation == "top":
        if not (
            anchors[2].price > anchors[0].price and anchors[2].price > anchors[4].price
        ):
            raise ValueError("head must exceed both shoulders")
    elif not (
        anchors[2].price < anchors[0].price and anchors[2].price < anchors[4].price
    ):
        raise ValueError("head must be below both shoulders")
    normalized_indices = _validate_bar_indices(indices)
    if len(normalized_indices) != 5:
        raise ValueError("Head & Shoulders requires exactly five bar indices")
    return market, normalized_indices, expected_orientation  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class HeadShouldersPatternGeometryRequest:
    """One explicit regular or inverse Head & Shoulders candidate."""

    bars: tuple
    left_shoulder: SwingAnchor
    neck_left: SwingAnchor
    head: SwingAnchor
    neck_right: SwingAnchor
    right_shoulder: SwingAnchor
    market_as_of: datetime

    def __post_init__(self) -> None:
        bars, market, _, _ = _validate_pattern_inputs(
            self.bars,
            (
                self.left_shoulder,
                self.neck_left,
                self.head,
                self.neck_right,
                self.right_shoulder,
            ),
            self.market_as_of,
        )
        if self.left_shoulder.kind != self.head.kind:
            raise ValueError("shoulders and head must share an extremum kind")
        if self.neck_left.kind != self.neck_right.kind:
            raise ValueError("neckline anchors must share an extremum kind")
        if self.left_shoulder.kind == self.neck_left.kind:
            raise ValueError("neckline anchors must oppose shoulder anchors")
        if self.left_shoulder.kind == "swing_high":
            if not (
                self.head.price > self.left_shoulder.price
                and self.head.price > self.right_shoulder.price
            ):
                raise ValueError("head must exceed both shoulders")
        elif not (
            self.head.price < self.left_shoulder.price
            and self.head.price < self.right_shoulder.price
        ):
            raise ValueError("head must be below both shoulders")
        left_index, neck_left_index, head_index, neck_right_index, right_index = (
            _validate_pattern_inputs(
                bars,
                (
                    self.left_shoulder,
                    self.neck_left,
                    self.head,
                    self.neck_right,
                    self.right_shoulder,
                ),
                market,
            )[2]
        )
        if self.left_shoulder.kind == "swing_high":
            neckline = lambda index: _line_value(
                self.neck_left,
                self.neck_right,
                neck_left_index,
                neck_right_index,
                index,
            )
            if any(
                neckline(index) >= anchor.price
                for index, anchor in (
                    (left_index, self.left_shoulder),
                    (head_index, self.head),
                    (right_index, self.right_shoulder),
                )
            ):
                raise ValueError("all top prominences must be positive")
        else:
            neckline = lambda index: _line_value(
                self.neck_left,
                self.neck_right,
                neck_left_index,
                neck_right_index,
                index,
            )
            if any(
                neckline(index) <= anchor.price
                for index, anchor in (
                    (left_index, self.left_shoulder),
                    (head_index, self.head),
                    (right_index, self.right_shoulder),
                )
            ):
                raise ValueError("all bottom prominences must be positive")
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "market_as_of", market)


@dataclass(frozen=True, slots=True)
class HeadShouldersPatternGeometrySnapshot:
    """Immutable factual Head & Shoulders geometry at one cutoff."""

    market_as_of: datetime
    orientation: HeadShouldersOrientation
    left_shoulder: SwingAnchor
    neck_left: SwingAnchor
    head: SwingAnchor
    neck_right: SwingAnchor
    right_shoulder: SwingAnchor
    left_shoulder_bar_index: int
    neck_left_bar_index: int
    head_bar_index: int
    neck_right_bar_index: int
    right_shoulder_bar_index: int
    neckline_slope_per_bar: float
    neckline_at_left_shoulder: float
    neckline_at_head: float
    neckline_at_right_shoulder: float
    left_shoulder_prominence: float
    head_prominence: float
    right_shoulder_prominence: float
    shoulder_price_difference: float

    def __post_init__(self) -> None:
        anchors = (
            self.left_shoulder,
            self.neck_left,
            self.head,
            self.neck_right,
            self.right_shoulder,
        )
        market, indices, orientation = _validate_head_shoulders(
            anchors,
            self.market_as_of,
            self.orientation,
            (
                self.left_shoulder_bar_index,
                self.neck_left_bar_index,
                self.head_bar_index,
                self.neck_right_bar_index,
                self.right_shoulder_bar_index,
            ),
        )
        (
            left_index,
            neck_left_index,
            head_index,
            neck_right_index,
            right_index,
        ) = indices
        slope = _finite_real(
            (self.neck_right.price - self.neck_left.price)
            / (neck_right_index - neck_left_index),
            field_name="neckline_slope_per_bar",
        )
        neckline_at_left = _line_value(
            self.neck_left,
            self.neck_right,
            neck_left_index,
            neck_right_index,
            left_index,
        )
        neckline_at_head = _line_value(
            self.neck_left,
            self.neck_right,
            neck_left_index,
            neck_right_index,
            head_index,
        )
        neckline_at_right = _line_value(
            self.neck_left,
            self.neck_right,
            neck_left_index,
            neck_right_index,
            right_index,
        )
        if orientation == "top":
            prominences = (
                self.left_shoulder.price - neckline_at_left,
                self.head.price - neckline_at_head,
                self.right_shoulder.price - neckline_at_right,
            )
        else:
            prominences = (
                neckline_at_left - self.left_shoulder.price,
                neckline_at_head - self.head.price,
                neckline_at_right - self.right_shoulder.price,
            )
        if not all(value > 0.0 for value in prominences):
            raise ValueError("all prominences must be positive")
        values = (
            (self.neckline_slope_per_bar, slope, "neckline_slope_per_bar"),
            (
                self.neckline_at_left_shoulder,
                neckline_at_left,
                "neckline_at_left_shoulder",
            ),
            (self.neckline_at_head, neckline_at_head, "neckline_at_head"),
            (
                self.neckline_at_right_shoulder,
                neckline_at_right,
                "neckline_at_right_shoulder",
            ),
            (
                self.left_shoulder_prominence,
                prominences[0],
                "left_shoulder_prominence",
            ),
            (self.head_prominence, prominences[1], "head_prominence"),
            (
                self.right_shoulder_prominence,
                prominences[2],
                "right_shoulder_prominence",
            ),
            (
                self.shoulder_price_difference,
                abs(self.right_shoulder.price - self.left_shoulder.price),
                "shoulder_price_difference",
            ),
        )
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in values
        )
        object.__setattr__(self, "market_as_of", market)
        for field_name, value in zip(
            (
                "neckline_slope_per_bar",
                "neckline_at_left_shoulder",
                "neckline_at_head",
                "neckline_at_right_shoulder",
                "left_shoulder_prominence",
                "head_prominence",
                "right_shoulder_prominence",
                "shoulder_price_difference",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)


def compute_head_shoulders_pattern_geometry(
    request: HeadShouldersPatternGeometryRequest,
) -> HeadShouldersPatternGeometrySnapshot:
    """Compute factual regular or inverse Head & Shoulders geometry."""

    if not isinstance(request, HeadShouldersPatternGeometryRequest):
        raise TypeError("request must be HeadShouldersPatternGeometryRequest")
    _, _, indices, _ = _validate_pattern_inputs(
        request.bars,
        (
            request.left_shoulder,
            request.neck_left,
            request.head,
            request.neck_right,
            request.right_shoulder,
        ),
        request.market_as_of,
    )
    (
        left_index,
        neck_left_index,
        head_index,
        neck_right_index,
        right_index,
    ) = indices
    neckline_at = lambda index: _line_value(
        request.neck_left,
        request.neck_right,
        neck_left_index,
        neck_right_index,
        index,
    )
    neckline_values = (
        neckline_at(left_index),
        neckline_at(head_index),
        neckline_at(right_index),
    )
    if request.left_shoulder.kind == "swing_high":
        prominences = tuple(
            anchor.price - neckline
            for anchor, neckline in zip(
                (request.left_shoulder, request.head, request.right_shoulder),
                neckline_values,
            )
        )
        orientation = "top"
    else:
        prominences = tuple(
            neckline - anchor.price
            for anchor, neckline in zip(
                (request.left_shoulder, request.head, request.right_shoulder),
                neckline_values,
            )
        )
        orientation = "bottom"
    return HeadShouldersPatternGeometrySnapshot(
        market_as_of=request.market_as_of,
        orientation=orientation,
        left_shoulder=request.left_shoulder,
        neck_left=request.neck_left,
        head=request.head,
        neck_right=request.neck_right,
        right_shoulder=request.right_shoulder,
        left_shoulder_bar_index=left_index,
        neck_left_bar_index=neck_left_index,
        head_bar_index=head_index,
        neck_right_bar_index=neck_right_index,
        right_shoulder_bar_index=right_index,
        neckline_slope_per_bar=(request.neck_right.price - request.neck_left.price)
        / (neck_right_index - neck_left_index),
        neckline_at_left_shoulder=neckline_values[0],
        neckline_at_head=neckline_values[1],
        neckline_at_right_shoulder=neckline_values[2],
        left_shoulder_prominence=prominences[0],
        head_prominence=prominences[1],
        right_shoulder_prominence=prominences[2],
        shoulder_price_difference=abs(
            request.right_shoulder.price - request.left_shoulder.price
        ),
    )


__all__ = (
    "HeadShouldersOrientation",
    "HeadShouldersPatternGeometryRequest",
    "HeadShouldersPatternGeometrySnapshot",
    "compute_head_shoulders_pattern_geometry",
)
