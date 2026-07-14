"""Pure causal pivot detection for SR-V1.2."""

from __future__ import annotations

import math

from libs.models.sr.config.models import DetectionConfig
from libs.models.sr.domain.contracts import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    ZoneGeometry,
    ZoneSide,
)


def _finite(value: float, *, field_name: str) -> float:
    if not math.isfinite(value):
        raise ContractValidationError(f"{field_name} must be finite")
    return value


def _validate_window(window: tuple[ClosedBar, ...]) -> None:
    if not window:
        return
    for idx, bar in enumerate(window):
        if type(bar) is not ClosedBar:
            raise ContractValidationError(
                f"bars[{idx}] must be exactly ClosedBar"
            )
    state_key = window[0].state_key
    seen_bar_ids: set[str] = set()
    previous_timestamp = None
    for idx, bar in enumerate(window):
        if bar.state_key != state_key:
            raise ContractValidationError(
                f"bars[{idx}].state_key must match pivot window state_key"
            )
        if bar.bar_id in seen_bar_ids:
            raise ContractValidationError(
                f"duplicate bar_id in pivot window: {bar.bar_id}"
            )
        seen_bar_ids.add(bar.bar_id)
        if (
            previous_timestamp is not None
            and bar.closed_at <= previous_timestamp
        ):
            raise ContractValidationError(
                "pivot window timestamps must be strictly increasing"
            )
        previous_timestamp = bar.closed_at


def _candidate(
    *,
    center_bar: ClosedBar,
    confirmation_bar: ClosedBar,
    side: ZoneSide,
    center: float,
    config: DetectionConfig,
) -> CandidateLevel:
    atr_at_creation = _finite(
        confirmation_bar.atr_at_close,
        field_name="atr_at_creation",
    )
    half_width = _finite(
        config.zone_half_width_atr * atr_at_creation,
        field_name="zone half_width",
    )
    center = _finite(center, field_name="candidate center")
    lower_bound = _finite(
        center - half_width,
        field_name="candidate lower_bound",
    )
    upper_bound = _finite(
        center + half_width,
        field_name="candidate upper_bound",
    )
    # Keep final geometry validation in the domain contract as well.
    geometry = ZoneGeometry(center=center, half_width=half_width)
    if not math.isfinite(geometry.lower_bound) or not math.isfinite(
        geometry.upper_bound
    ):
        raise ContractValidationError("candidate geometry bounds must be finite")
    if geometry.lower_bound != lower_bound or geometry.upper_bound != upper_bound:
        raise ContractValidationError("candidate geometry bounds are inconsistent")
    return CandidateLevel(
        state_key=center_bar.state_key,
        side=side,
        geometry=geometry,
        source="pivot_v1",
        formed_at=center_bar.closed_at,
        available_at=confirmation_bar.closed_at,
        atr_at_creation=atr_at_creation,
    )


def detect_confirmed_pivots(
    bars: tuple[ClosedBar, ...],
    config: DetectionConfig,
) -> tuple[CandidateLevel, ...]:
    """Return strict pivots confirmed by final bar in ``bars``."""
    if type(bars) is not tuple:
        raise ContractValidationError("bars must be exactly a tuple")
    if type(config) is not DetectionConfig:
        raise ContractValidationError("config must be exactly DetectionConfig")

    window_size = 2 * config.pivot_span_bars + 1
    window = bars[-window_size:]
    _validate_window(window)
    if len(window) < window_size:
        return ()

    span = config.pivot_span_bars
    center_bar = window[span]
    confirmation_bar = window[-1]
    other_bars = window[:span] + window[span + 1 :]
    candidates: list[CandidateLevel] = []
    if all(center_bar.high > bar.high for bar in other_bars):
        candidates.append(
            _candidate(
                center_bar=center_bar,
                confirmation_bar=confirmation_bar,
                side=ZoneSide.RESISTANCE,
                center=center_bar.high,
                config=config,
            )
        )
    if all(center_bar.low < bar.low for bar in other_bars):
        candidates.append(
            _candidate(
                center_bar=center_bar,
                confirmation_bar=confirmation_bar,
                side=ZoneSide.SUPPORT,
                center=center_bar.low,
                config=config,
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.formed_at,
                candidate.available_at,
                candidate.candidate_id,
            ),
        )
    )


__all__ = ["detect_confirmed_pivots"]
