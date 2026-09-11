"""Explicit six-anchor Three Drives pattern measurements."""

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

ThreeDrivesOrientation = Literal["drives_up", "drives_down"]


def _derived_float(value: object, expected: float, *, field_name: str) -> float:
    normalized = _finite_real(value, field_name=field_name)
    if normalized != expected:
        raise ValueError(f"{field_name} is inconsistent with anchors")
    return normalized


def _validate_snapshot(
    anchors: tuple[SwingAnchor, ...],
    indices: tuple[object, ...],
    market_as_of: object,
    orientation: object,
) -> tuple[tuple[SwingAnchor, ...], tuple[int, ...], datetime, str]:
    market = _utc(market_as_of, field_name="market_as_of")
    if len(anchors) != 6:
        raise ValueError("Three Drives requires exactly six anchors")
    sequence = _validate_anchor_sequence(anchors, market)
    expected_orientation = (
        "drives_up" if sequence == "low_high_low_high_low_high" else None
    )
    if sequence == "high_low_high_low_high_low":
        expected_orientation = "drives_down"
    if expected_orientation is None or orientation != expected_orientation:
        raise ValueError("orientation is inconsistent with anchor topology")
    normalized_indices = _validate_bar_indices(indices)
    if len(normalized_indices) != 6:
        raise ValueError("Three Drives requires exactly six bar indices")
    return anchors, normalized_indices, market, expected_orientation


@dataclass(frozen=True, slots=True)
class ThreeDrivesPatternGeometryRequest:
    """One explicit six-anchor Three Drives candidate."""

    bars: tuple
    start: SwingAnchor
    drive1: SwingAnchor
    retrace_a: SwingAnchor
    drive2: SwingAnchor
    retrace_c: SwingAnchor
    drive3: SwingAnchor
    market_as_of: datetime

    def __post_init__(self) -> None:
        bars, market, _, _ = _validate_pattern_inputs(
            self.bars,
            (
                self.start,
                self.drive1,
                self.retrace_a,
                self.drive2,
                self.retrace_c,
                self.drive3,
            ),
            self.market_as_of,
        )
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "market_as_of", market)


@dataclass(frozen=True, slots=True)
class ThreeDrivesPatternGeometrySnapshot:
    """Immutable factual Three Drives measurements at one cutoff."""

    market_as_of: datetime
    orientation: ThreeDrivesOrientation
    start: SwingAnchor
    drive1: SwingAnchor
    retrace_a: SwingAnchor
    drive2: SwingAnchor
    retrace_c: SwingAnchor
    drive3: SwingAnchor
    start_bar_index: int
    drive1_bar_index: int
    retrace_a_bar_index: int
    drive2_bar_index: int
    retrace_c_bar_index: int
    drive3_bar_index: int
    drive1_mag: float
    a_retrace_mag: float
    drive2_mag: float
    c_retrace_mag: float
    drive3_mag: float
    drive1_bar_span: int
    a_retrace_bar_span: int
    drive2_bar_span: int
    c_retrace_bar_span: int
    drive3_bar_span: int
    a_retrace_over_drive1: float
    drive2_over_a_retrace: float
    c_retrace_over_drive2: float
    drive3_over_c_retrace: float
    c_retrace_over_a_retrace: float
    drive3_over_drive2: float
    c_retrace_time_over_a_retrace_time: float
    drive3_time_over_drive2_time: float

    def __post_init__(self) -> None:
        anchors, indices, market, expected_orientation = _validate_snapshot(
            (
                self.start,
                self.drive1,
                self.retrace_a,
                self.drive2,
                self.retrace_c,
                self.drive3,
            ),
            (
                self.start_bar_index,
                self.drive1_bar_index,
                self.retrace_a_bar_index,
                self.drive2_bar_index,
                self.retrace_c_bar_index,
                self.drive3_bar_index,
            ),
            self.market_as_of,
            self.orientation,
        )
        start, drive1, retrace_a, drive2, retrace_c, drive3 = anchors
        (
            start_index,
            drive1_index,
            retrace_a_index,
            drive2_index,
            retrace_c_index,
            drive3_index,
        ) = indices
        drive1_mag = abs(drive1.price - start.price)
        a_retrace_mag = abs(retrace_a.price - drive1.price)
        drive2_mag = abs(drive2.price - retrace_a.price)
        c_retrace_mag = abs(retrace_c.price - drive2.price)
        drive3_mag = abs(drive3.price - retrace_c.price)
        spans = (
            ("drive1_bar_span", self.drive1_bar_span, drive1_index - start_index),
            (
                "a_retrace_bar_span",
                self.a_retrace_bar_span,
                retrace_a_index - drive1_index,
            ),
            (
                "drive2_bar_span",
                self.drive2_bar_span,
                drive2_index - retrace_a_index,
            ),
            (
                "c_retrace_bar_span",
                self.c_retrace_bar_span,
                retrace_c_index - drive2_index,
            ),
            (
                "drive3_bar_span",
                self.drive3_bar_span,
                drive3_index - retrace_c_index,
            ),
        )
        for field_name, value, expected in spans:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value != expected:
                raise ValueError(f"{field_name} is inconsistent with anchors")
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in (
                (self.drive1_mag, drive1_mag, "drive1_mag"),
                (self.a_retrace_mag, a_retrace_mag, "a_retrace_mag"),
                (self.drive2_mag, drive2_mag, "drive2_mag"),
                (self.c_retrace_mag, c_retrace_mag, "c_retrace_mag"),
                (self.drive3_mag, drive3_mag, "drive3_mag"),
                (
                    self.a_retrace_over_drive1,
                    a_retrace_mag / drive1_mag,
                    "a_retrace_over_drive1",
                ),
                (
                    self.drive2_over_a_retrace,
                    drive2_mag / a_retrace_mag,
                    "drive2_over_a_retrace",
                ),
                (
                    self.c_retrace_over_drive2,
                    c_retrace_mag / drive2_mag,
                    "c_retrace_over_drive2",
                ),
                (
                    self.drive3_over_c_retrace,
                    drive3_mag / c_retrace_mag,
                    "drive3_over_c_retrace",
                ),
                (
                    self.c_retrace_over_a_retrace,
                    c_retrace_mag / a_retrace_mag,
                    "c_retrace_over_a_retrace",
                ),
                (
                    self.drive3_over_drive2,
                    drive3_mag / drive2_mag,
                    "drive3_over_drive2",
                ),
                (
                    self.c_retrace_time_over_a_retrace_time,
                    (retrace_c_index - drive2_index) / (retrace_a_index - drive1_index),
                    "c_retrace_time_over_a_retrace_time",
                ),
                (
                    self.drive3_time_over_drive2_time,
                    (drive3_index - retrace_c_index) / (drive2_index - retrace_a_index),
                    "drive3_time_over_drive2_time",
                ),
            )
        )
        object.__setattr__(self, "market_as_of", market)
        object.__setattr__(self, "orientation", expected_orientation)
        for field_name, value in zip(
            (
                "drive1_mag",
                "a_retrace_mag",
                "drive2_mag",
                "c_retrace_mag",
                "drive3_mag",
                "a_retrace_over_drive1",
                "drive2_over_a_retrace",
                "c_retrace_over_drive2",
                "drive3_over_c_retrace",
                "c_retrace_over_a_retrace",
                "drive3_over_drive2",
                "c_retrace_time_over_a_retrace_time",
                "drive3_time_over_drive2_time",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)


def compute_three_drives_pattern_geometry(
    request: ThreeDrivesPatternGeometryRequest,
) -> ThreeDrivesPatternGeometrySnapshot:
    """Compute factual six-anchor Three Drives geometry."""

    if not isinstance(request, ThreeDrivesPatternGeometryRequest):
        raise TypeError("request must be ThreeDrivesPatternGeometryRequest")
    _, _, indices, sequence = _validate_pattern_inputs(
        request.bars,
        (
            request.start,
            request.drive1,
            request.retrace_a,
            request.drive2,
            request.retrace_c,
            request.drive3,
        ),
        request.market_as_of,
    )
    orientation = (
        "drives_up" if sequence == "low_high_low_high_low_high" else "drives_down"
    )
    start, drive1, retrace_a, drive2, retrace_c, drive3 = (
        request.start,
        request.drive1,
        request.retrace_a,
        request.drive2,
        request.retrace_c,
        request.drive3,
    )
    (
        start_index,
        drive1_index,
        retrace_a_index,
        drive2_index,
        retrace_c_index,
        drive3_index,
    ) = indices
    drive1_mag = abs(drive1.price - start.price)
    a_retrace_mag = abs(retrace_a.price - drive1.price)
    drive2_mag = abs(drive2.price - retrace_a.price)
    c_retrace_mag = abs(retrace_c.price - drive2.price)
    drive3_mag = abs(drive3.price - retrace_c.price)
    drive1_span = drive1_index - start_index
    a_retrace_span = retrace_a_index - drive1_index
    drive2_span = drive2_index - retrace_a_index
    c_retrace_span = retrace_c_index - drive2_index
    drive3_span = drive3_index - retrace_c_index
    return ThreeDrivesPatternGeometrySnapshot(
        market_as_of=request.market_as_of,
        orientation=orientation,
        start=start,
        drive1=drive1,
        retrace_a=retrace_a,
        drive2=drive2,
        retrace_c=retrace_c,
        drive3=drive3,
        start_bar_index=start_index,
        drive1_bar_index=drive1_index,
        retrace_a_bar_index=retrace_a_index,
        drive2_bar_index=drive2_index,
        retrace_c_bar_index=retrace_c_index,
        drive3_bar_index=drive3_index,
        drive1_mag=drive1_mag,
        a_retrace_mag=a_retrace_mag,
        drive2_mag=drive2_mag,
        c_retrace_mag=c_retrace_mag,
        drive3_mag=drive3_mag,
        drive1_bar_span=drive1_span,
        a_retrace_bar_span=a_retrace_span,
        drive2_bar_span=drive2_span,
        c_retrace_bar_span=c_retrace_span,
        drive3_bar_span=drive3_span,
        a_retrace_over_drive1=a_retrace_mag / drive1_mag,
        drive2_over_a_retrace=drive2_mag / a_retrace_mag,
        c_retrace_over_drive2=c_retrace_mag / drive2_mag,
        drive3_over_c_retrace=drive3_mag / c_retrace_mag,
        c_retrace_over_a_retrace=c_retrace_mag / a_retrace_mag,
        drive3_over_drive2=drive3_mag / drive2_mag,
        c_retrace_time_over_a_retrace_time=c_retrace_span / a_retrace_span,
        drive3_time_over_drive2_time=drive3_span / drive2_span,
    )


__all__ = (
    "ThreeDrivesOrientation",
    "ThreeDrivesPatternGeometryRequest",
    "ThreeDrivesPatternGeometrySnapshot",
    "compute_three_drives_pattern_geometry",
)
