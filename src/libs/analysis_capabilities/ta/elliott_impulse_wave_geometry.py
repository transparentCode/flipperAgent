"""Explicit six-anchor Elliott impulse-wave geometry."""

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

ElliottImpulseOrientation = Literal["up", "down"]


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
        raise ValueError("Elliott impulse requires exactly six anchors")
    sequence = _validate_anchor_sequence(anchors, market)
    if sequence == "low_high_low_high_low_high":
        expected_orientation = "up"
    elif sequence == "high_low_high_low_high_low":
        expected_orientation = "down"
    else:
        raise ValueError("anchors do not form an Elliott impulse topology")
    if orientation != expected_orientation:
        raise ValueError("orientation is inconsistent with anchor topology")
    normalized_indices = _validate_bar_indices(indices)
    if len(normalized_indices) != 6:
        raise ValueError("Elliott impulse requires exactly six bar indices")
    return anchors, normalized_indices, market, expected_orientation


@dataclass(frozen=True, slots=True)
class ElliottImpulseWaveGeometryRequest:
    """One explicit six-anchor Elliott impulse drawing."""

    bars: tuple
    start: SwingAnchor
    wave1: SwingAnchor
    wave2: SwingAnchor
    wave3: SwingAnchor
    wave4: SwingAnchor
    wave5: SwingAnchor
    market_as_of: datetime

    def __post_init__(self) -> None:
        bars, market, _, _ = _validate_pattern_inputs(
            self.bars,
            (
                self.start,
                self.wave1,
                self.wave2,
                self.wave3,
                self.wave4,
                self.wave5,
            ),
            self.market_as_of,
        )
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "market_as_of", market)


@dataclass(frozen=True, slots=True)
class ElliottImpulseWaveGeometrySnapshot:
    """Immutable factual Elliott impulse geometry at one cutoff."""

    market_as_of: datetime
    orientation: ElliottImpulseOrientation
    start: SwingAnchor
    wave1: SwingAnchor
    wave2: SwingAnchor
    wave3: SwingAnchor
    wave4: SwingAnchor
    wave5: SwingAnchor
    start_bar_index: int
    wave1_bar_index: int
    wave2_bar_index: int
    wave3_bar_index: int
    wave4_bar_index: int
    wave5_bar_index: int
    wave1_price_magnitude: float
    wave2_price_magnitude: float
    wave3_price_magnitude: float
    wave4_price_magnitude: float
    wave5_price_magnitude: float
    wave1_bar_span: int
    wave2_bar_span: int
    wave3_bar_span: int
    wave4_bar_span: int
    wave5_bar_span: int
    wave2_over_wave1: float
    wave3_over_wave1: float
    wave4_over_wave3: float
    wave5_over_wave1: float
    wave3_time_over_wave1: float
    wave5_time_over_wave1: float

    def __post_init__(self) -> None:
        anchors, indices, market, expected_orientation = _validate_snapshot(
            (
                self.start,
                self.wave1,
                self.wave2,
                self.wave3,
                self.wave4,
                self.wave5,
            ),
            (
                self.start_bar_index,
                self.wave1_bar_index,
                self.wave2_bar_index,
                self.wave3_bar_index,
                self.wave4_bar_index,
                self.wave5_bar_index,
            ),
            self.market_as_of,
            self.orientation,
        )
        start, wave1, wave2, wave3, wave4, wave5 = anchors
        (
            start_index,
            wave1_index,
            wave2_index,
            wave3_index,
            wave4_index,
            wave5_index,
        ) = indices
        magnitudes = (
            abs(wave1.price - start.price),
            abs(wave2.price - wave1.price),
            abs(wave3.price - wave2.price),
            abs(wave4.price - wave3.price),
            abs(wave5.price - wave4.price),
        )
        spans = (
            wave1_index - start_index,
            wave2_index - wave1_index,
            wave3_index - wave2_index,
            wave4_index - wave3_index,
            wave5_index - wave4_index,
        )
        for field_name, value, expected in zip(
            (
                "wave1_bar_span",
                "wave2_bar_span",
                "wave3_bar_span",
                "wave4_bar_span",
                "wave5_bar_span",
            ),
            (
                self.wave1_bar_span,
                self.wave2_bar_span,
                self.wave3_bar_span,
                self.wave4_bar_span,
                self.wave5_bar_span,
            ),
            spans,
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value != expected:
                raise ValueError(f"{field_name} is inconsistent with anchors")
        w1, w2, w3, w4, w5 = magnitudes
        s1, _, s3, _, s5 = spans
        normalized = tuple(
            _derived_float(value, expected, field_name=field_name)
            for value, expected, field_name in (
                (self.wave1_price_magnitude, w1, "wave1_price_magnitude"),
                (self.wave2_price_magnitude, w2, "wave2_price_magnitude"),
                (self.wave3_price_magnitude, w3, "wave3_price_magnitude"),
                (self.wave4_price_magnitude, w4, "wave4_price_magnitude"),
                (self.wave5_price_magnitude, w5, "wave5_price_magnitude"),
                (self.wave2_over_wave1, w2 / w1, "wave2_over_wave1"),
                (self.wave3_over_wave1, w3 / w1, "wave3_over_wave1"),
                (self.wave4_over_wave3, w4 / w3, "wave4_over_wave3"),
                (self.wave5_over_wave1, w5 / w1, "wave5_over_wave1"),
                (self.wave3_time_over_wave1, s3 / s1, "wave3_time_over_wave1"),
                (self.wave5_time_over_wave1, s5 / s1, "wave5_time_over_wave1"),
            )
        )
        object.__setattr__(self, "market_as_of", market)
        object.__setattr__(self, "orientation", expected_orientation)
        for field_name, value in zip(
            (
                "wave1_price_magnitude",
                "wave2_price_magnitude",
                "wave3_price_magnitude",
                "wave4_price_magnitude",
                "wave5_price_magnitude",
                "wave2_over_wave1",
                "wave3_over_wave1",
                "wave4_over_wave3",
                "wave5_over_wave1",
                "wave3_time_over_wave1",
                "wave5_time_over_wave1",
            ),
            normalized,
        ):
            object.__setattr__(self, field_name, value)


def compute_elliott_impulse_wave_geometry(
    request: ElliottImpulseWaveGeometryRequest,
) -> ElliottImpulseWaveGeometrySnapshot:
    """Compute factual six-anchor Elliott impulse geometry."""

    if not isinstance(request, ElliottImpulseWaveGeometryRequest):
        raise TypeError("request must be ElliottImpulseWaveGeometryRequest")
    _, _, indices, sequence = _validate_pattern_inputs(
        request.bars,
        (
            request.start,
            request.wave1,
            request.wave2,
            request.wave3,
            request.wave4,
            request.wave5,
        ),
        request.market_as_of,
    )
    orientation = "up" if sequence == "low_high_low_high_low_high" else "down"
    start, wave1, wave2, wave3, wave4, wave5 = (
        request.start,
        request.wave1,
        request.wave2,
        request.wave3,
        request.wave4,
        request.wave5,
    )
    (
        start_index,
        wave1_index,
        wave2_index,
        wave3_index,
        wave4_index,
        wave5_index,
    ) = indices
    magnitudes = (
        abs(wave1.price - start.price),
        abs(wave2.price - wave1.price),
        abs(wave3.price - wave2.price),
        abs(wave4.price - wave3.price),
        abs(wave5.price - wave4.price),
    )
    spans = (
        wave1_index - start_index,
        wave2_index - wave1_index,
        wave3_index - wave2_index,
        wave4_index - wave3_index,
        wave5_index - wave4_index,
    )
    w1, w2, w3, w4, w5 = magnitudes
    s1, _, s3, _, s5 = spans
    return ElliottImpulseWaveGeometrySnapshot(
        market_as_of=request.market_as_of,
        orientation=orientation,
        start=start,
        wave1=wave1,
        wave2=wave2,
        wave3=wave3,
        wave4=wave4,
        wave5=wave5,
        start_bar_index=start_index,
        wave1_bar_index=wave1_index,
        wave2_bar_index=wave2_index,
        wave3_bar_index=wave3_index,
        wave4_bar_index=wave4_index,
        wave5_bar_index=wave5_index,
        wave1_price_magnitude=w1,
        wave2_price_magnitude=w2,
        wave3_price_magnitude=w3,
        wave4_price_magnitude=w4,
        wave5_price_magnitude=w5,
        wave1_bar_span=spans[0],
        wave2_bar_span=spans[1],
        wave3_bar_span=spans[2],
        wave4_bar_span=spans[3],
        wave5_bar_span=spans[4],
        wave2_over_wave1=w2 / w1,
        wave3_over_wave1=w3 / w1,
        wave4_over_wave3=w4 / w3,
        wave5_over_wave1=w5 / w1,
        wave3_time_over_wave1=s3 / s1,
        wave5_time_over_wave1=s5 / s1,
    )


__all__ = (
    "ElliottImpulseOrientation",
    "ElliottImpulseWaveGeometryRequest",
    "ElliottImpulseWaveGeometrySnapshot",
    "compute_elliott_impulse_wave_geometry",
)
