"""Causal ATR and post-resolution outcome construction."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide
from libs.models.sr.scripts.baseline_trial.contracts import SourceBar

from .config import LifecycleUtilityConfig
from .contracts import NullCell, ResolutionEvent, ResolutionOutcome


def _finite(value: Any, *, path: str, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractValidationError(f"{path} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{path} must be finite")
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{path} must be >= {minimum}")
    return 0.0 if result == 0.0 else result


def compute_wilder_atr_by_bar(
    bars: tuple[SourceBar, ...],
    *,
    period: int,
) -> tuple[float | None, ...]:
    """Match the frozen true-range/SMA-seed/Wilder recursion contract."""
    if type(bars) is not tuple or any(type(bar) is not SourceBar for bar in bars):
        raise ContractValidationError("ATR bars must be a tuple of SourceBar values")
    if isinstance(period, bool) or type(period) is not int or period < 1:
        raise ContractValidationError("ATR period must be a positive integer")
    values: list[float | None] = [None] * len(bars)
    if len(bars) < period + 1:
        return tuple(values)
    true_ranges = [0.0] * len(bars)
    true_ranges[0] = _finite(bars[0].high - bars[0].low, path="atr.true_range[0]", minimum=0.0)
    for index in range(1, len(bars)):
        true_ranges[index] = _finite(
            max(
                bars[index].high - bars[index].low,
                abs(bars[index].high - bars[index - 1].close),
                abs(bars[index].low - bars[index - 1].close),
            ),
            path=f"atr.true_range[{index}]",
            minimum=0.0,
        )
    current = _finite(sum(true_ranges[1 : period + 1]) / period, path=f"atr[{period}]", minimum=0.0)
    if current <= 0:
        raise ContractValidationError("ATR must be positive at first valid bar")
    values[period] = current
    for index in range(period + 1, len(bars)):
        current = _finite((current * (period - 1) + true_ranges[index]) / period, path=f"atr[{index}]", minimum=0.0)
        if current <= 0:
            raise ContractValidationError(f"ATR must be positive at bar {index}")
        values[index] = current
    return tuple(values)


def _fold_end(event_fold: str, config: LifecycleUtilityConfig) -> datetime:
    for fold in config.folds:
        if fold.name == event_fold:
            return fold.end
    raise ContractValidationError(f"unknown event fold: {event_fold}")


def build_resolution_outcome(
    event: ResolutionEvent,
    bars: tuple[SourceBar, ...],
    *,
    config: LifecycleUtilityConfig,
    null_cell: NullCell | None,
    atr_values: tuple[float | None, ...] | None = None,
) -> ResolutionOutcome:
    """Build one causal ten-bar outcome anchored on a resolution bar close."""
    if type(event) is not ResolutionEvent:
        raise ContractValidationError("outcome construction requires ResolutionEvent")
    if type(bars) is not tuple or any(type(bar) is not SourceBar for bar in bars):
        raise ContractValidationError("outcome bars must be a tuple of SourceBar values")
    index_by_id = {bar.bar_id: index for index, bar in enumerate(bars)}
    if event.event_bar_id not in index_by_id:
        raise ContractValidationError("resolution event bar is not in the frozen source")
    event_index = index_by_id[event.event_bar_id]
    event_bar = bars[event_index]
    if event_bar.closed_at != event.event_at or event_bar.open_time >= event.event_at:
        raise ContractValidationError("resolution event is not aligned to its causal bar close")
    if abs(event.anchor_close - event_bar.close) > 1e-12:
        raise ContractValidationError("resolution anchor does not equal event bar close")
    atr_values = atr_values if atr_values is not None else compute_wilder_atr_by_bar(bars, period=config.atr_period)
    if type(atr_values) is not tuple or len(atr_values) != len(bars):
        raise ContractValidationError("ATR values do not match source bars")
    reference_atr = atr_values[event_index]
    if reference_atr is None or reference_atr <= 0:
        raise ContractValidationError("resolution event has no causal ATR(14)")
    start_index = event_index + config.outcome_start_offset_bars
    end_index = start_index + config.outcome_horizon_bars - 1
    if start_index >= len(bars):
        raise ContractValidationError("resolution has no next bar for outcome start")
    start_bar = bars[start_index]
    if start_bar.open_time != event_bar.closed_at:
        raise ContractValidationError("outcome must begin on the next aligned bar")
    fold_end = _fold_end(event.event_fold, config)
    if end_index >= len(bars):
        raise ContractValidationError("resolution horizon exceeds the frozen source")
    horizon_bar = bars[end_index]
    if horizon_bar.closed_at >= fold_end:
        return ResolutionOutcome(
            resolution_id=event.resolution_id,
            zone_id=event.zone_id,
            case_id=event.case_id,
            event_id=event.event_id,
            event_class=event.event_class,
            event_at=event.event_at,
            event_bar_id=event.event_bar_id,
            event_fold=event.event_fold,
            original_side=event.original_side,
            effective_side=event.effective_side,
            anchor_close=event.anchor_close,
            reference_atr_14=reference_atr,
            outcome_start_bar_id=start_bar.bar_id,
            outcome_end_at=None,
            completed=False,
            right_censored=True,
            favorable_excursion_atr=None,
            adverse_excursion_atr=None,
            directional_quality_atr=None,
            null_median_quality_atr=None,
            excess_quality_atr=None,
            null_control_count=0,
        )
    window = bars[start_index : end_index + 1]
    maximum = max(bar.high for bar in window)
    minimum = min(bar.low for bar in window)
    if event.effective_side is ZoneSide.SUPPORT:
        favorable = max(0.0, (maximum - event.anchor_close) / reference_atr)
        adverse = max(0.0, (event.anchor_close - minimum) / reference_atr)
    else:
        favorable = max(0.0, (event.anchor_close - minimum) / reference_atr)
        adverse = max(0.0, (maximum - event.anchor_close) / reference_atr)
    quality = favorable - adverse
    null_median = None if null_cell is None else null_cell.median_quality_atr
    null_count = 0 if null_cell is None else null_cell.control_count
    excess = None if null_median is None else quality - null_median
    return ResolutionOutcome(
        resolution_id=event.resolution_id,
        zone_id=event.zone_id,
        case_id=event.case_id,
        event_id=event.event_id,
        event_class=event.event_class,
        event_at=event.event_at,
        event_bar_id=event.event_bar_id,
        event_fold=event.event_fold,
        original_side=event.original_side,
        effective_side=event.effective_side,
        anchor_close=event.anchor_close,
        reference_atr_14=reference_atr,
        outcome_start_bar_id=start_bar.bar_id,
        outcome_end_at=horizon_bar.closed_at,
        completed=True,
        right_censored=False,
        favorable_excursion_atr=favorable,
        adverse_excursion_atr=adverse,
        directional_quality_atr=quality,
        null_median_quality_atr=null_median,
        excess_quality_atr=excess,
        null_control_count=null_count,
    )


__all__ = ["build_resolution_outcome", "compute_wilder_atr_by_bar"]
