"""Explicit four-anchor Elliott correction-wave geometry."""

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

ElliottCorrectionOrientation = Literal["first_leg_up", "first_leg_down"]


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
    if len(anchors) != 4:
        raise ValueError("Elliott correction requires exactly four anchors")
    sequence = _validate_anchor_sequence(anchors, market)
    if sequence == "low_high_low_high":
        expected_orientation = "first_leg_up"
    elif sequence == "high_low_high_low":
        expected_orientation = "first_leg_down"
    else:
        raise ValueError("anchors do not form an Elliott correction topology")
    if orientation != expected_orientation:
        raise ValueError("orientation is inconsistent with anchor topology")
    normalized_indices = _validate_bar_indices(indices)
    if len(normalized_indices) != 4:
        raise ValueError("Elliott correction requires exactly four bar indices")
    return anchors, normalized_indices, market, expected_orientation


@dataclass(frozen=True, slots=True)
class ElliottCorrectionWaveGeometryRequest:
    """One explicit four-anchor Elliott A-B-C drawing."""

    bars: tuple
    start: SwingAnchor
    wave_a: SwingAnchor
    wave_b: SwingAnchor
    wave_c: SwingAnchor
    market_as_of: datetime

    def __post_init__(self) -> None:
        bars, market, _, _ = _validate_pattern_inputs(
            self.bars,
            (self.start, self.wave_a, self.wave_b, self.wave_c),
            self.market_as_of,
        )
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "market_as_of", market)


@dataclass(frozen=True, slots=True)
class ElliottCorrectionWaveGeometrySnapshot:
    """Immutable factual Elliott correction geometry at one cutoff."""

    market_as_of: datetime
    orientation: ElliottCorrectionOrientation
    start: SwingAnchor
    wave_a: SwingAnchor
    wave_b: SwingAnchor
    wave_c: SwingAnchor
    start_bar_index: int
    wave_a_bar_index: int
    wave_b_bar_index: int
    wave_c_bar_index: int
    a_price_magnitude: float
    b_price_magnitude: float
    c_price_magnitude: float
    a_bar_span: int
    b_bar_span: int
    c_bar_span: int
    b_over_a: float
    c_over_a: float
    c_over_b: float
    b_time_over_a: float
    c_time_over_a: float

    def __post_init__(self) -> None:
        anchors, indices, market, expected_orientation = _validate_snapshot(
            (self.start, self.wave_a, self.wave_b, self.wave_c),
            (
                self.start_bar_index,
                self.wave_a_bar_index,
                self.wave_b_bar_index,
                self.wave_c_bar_index,
            ),
            self.market_as_of,
            self.orientation,
        )
        start, wave_a, wave_b, wave_c = anchors
        start_index, wave_a_index, wave_b_index, wave_c_index = indices
        a_mag = abs(wave_a.price - start.price)
        b_mag = abs(wave_b.price - wave_a.price)
        c_mag = abs(wave_c.price - wave_b.price)
        spans = (
            ("a_bar_span", self.a_bar_span, wave_a_index - start_index),
            ("b_bar_span", self.b_bar_span, wave_b_index - wave_a_index),
            ("c_bar_span", self.c_bar_span, wave_c_index - wave_b_index),
        )
        for field_name, value, expected in spans:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value != expected:
                raise ValueError(f"{field_name} is inconsistent with anchors")
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in (
                (self.a_price_magnitude, a_mag, "a_price_magnitude"),
                (self.b_price_magnitude, b_mag, "b_price_magnitude"),
                (self.c_price_magnitude, c_mag, "c_price_magnitude"),
                (self.b_over_a, b_mag / a_mag, "b_over_a"),
                (self.c_over_a, c_mag / a_mag, "c_over_a"),
                (self.c_over_b, c_mag / b_mag, "c_over_b"),
                (
                    self.b_time_over_a,
                    (wave_b_index - wave_a_index) / (wave_a_index - start_index),
                    "b_time_over_a",
                ),
                (
                    self.c_time_over_a,
                    (wave_c_index - wave_b_index) / (wave_a_index - start_index),
                    "c_time_over_a",
                ),
            )
        )
        object.__setattr__(self, "market_as_of", market)
        object.__setattr__(self, "orientation", expected_orientation)
        for field_name, value in zip(
            (
                "a_price_magnitude",
                "b_price_magnitude",
                "c_price_magnitude",
                "b_over_a",
                "c_over_a",
                "c_over_b",
                "b_time_over_a",
                "c_time_over_a",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)


def compute_elliott_correction_wave_geometry(
    request: ElliottCorrectionWaveGeometryRequest,
) -> ElliottCorrectionWaveGeometrySnapshot:
    """Compute factual four-anchor Elliott correction geometry."""

    if not isinstance(request, ElliottCorrectionWaveGeometryRequest):
        raise TypeError("request must be ElliottCorrectionWaveGeometryRequest")
    _, _, indices, sequence = _validate_pattern_inputs(
        request.bars,
        (request.start, request.wave_a, request.wave_b, request.wave_c),
        request.market_as_of,
    )
    orientation = (
        "first_leg_up" if sequence == "low_high_low_high" else "first_leg_down"
    )
    start, wave_a, wave_b, wave_c = (
        request.start,
        request.wave_a,
        request.wave_b,
        request.wave_c,
    )
    start_index, wave_a_index, wave_b_index, wave_c_index = indices
    a_mag = abs(wave_a.price - start.price)
    b_mag = abs(wave_b.price - wave_a.price)
    c_mag = abs(wave_c.price - wave_b.price)
    a_span = wave_a_index - start_index
    b_span = wave_b_index - wave_a_index
    c_span = wave_c_index - wave_b_index
    return ElliottCorrectionWaveGeometrySnapshot(
        market_as_of=request.market_as_of,
        orientation=orientation,
        start=start,
        wave_a=wave_a,
        wave_b=wave_b,
        wave_c=wave_c,
        start_bar_index=start_index,
        wave_a_bar_index=wave_a_index,
        wave_b_bar_index=wave_b_index,
        wave_c_bar_index=wave_c_index,
        a_price_magnitude=a_mag,
        b_price_magnitude=b_mag,
        c_price_magnitude=c_mag,
        a_bar_span=a_span,
        b_bar_span=b_span,
        c_bar_span=c_span,
        b_over_a=b_mag / a_mag,
        c_over_a=c_mag / a_mag,
        c_over_b=c_mag / b_mag,
        b_time_over_a=b_span / a_span,
        c_time_over_a=c_span / a_span,
    )


__all__ = (
    "ElliottCorrectionOrientation",
    "ElliottCorrectionWaveGeometryRequest",
    "ElliottCorrectionWaveGeometrySnapshot",
    "compute_elliott_correction_wave_geometry",
)
