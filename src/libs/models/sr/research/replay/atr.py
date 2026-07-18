"""Causal ATR candidate construction and one-pass SR replay."""

from __future__ import annotations

import math
from importlib import import_module
from typing import Iterable

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain import create_initial_state
from libs.models.sr.domain import ClosedBar, ContractValidationError, SRStateKey
from libs.models.sr.evaluation.diagnostics import compute_diagnostics
from libs.models.sr.evaluation.trace_builder import build_evaluation_trace
from libs.models.sr.replay.runner import replay_bars

from libs.models.sr.research.replay.candidates import CandidateReplay
from libs.models.sr.research.source.capsules import SourceCapsule


def compute_atr_series(source: SourceCapsule | tuple, period: int) -> tuple[float | None, ...]:
    """Compute the existing ATR implementation without changing its contract."""
    if isinstance(source, SourceCapsule):
        bars = source.bars
    else:
        bars = source
    if type(period) is not int or isinstance(period, bool) or period < 1:
        raise ContractValidationError("ATR period must be a positive integer")
    if type(bars) not in (tuple, list) or not bars:
        raise ContractValidationError("ATR source bars must be non-empty")
    try:
        atr_class = import_module("libs.features.indicators.volatility.atr").ATR
        values = atr_class(period=period).batch(tuple((bar.high, bar.low, bar.close) for bar in bars))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractValidationError("ATR computation failed") from exc
    if len(values) != len(bars):
        raise ContractValidationError("ATR output length does not match source bars")
    for index, value in enumerate(values):
        if index < period:
            if value is not None:
                raise ContractValidationError("ATR warmup prefix is not causal")
        else:
            if value is None:
                raise ContractValidationError(f"ATR missing after warmup at index {index}")
            try:
                numeric = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ContractValidationError("ATR value is not finite") from exc
            if not math.isfinite(numeric) or numeric <= 0:
                raise ContractValidationError("ATR values must be finite and positive")
            values[index] = 0.0 if numeric == 0.0 else numeric
    return tuple(values)


def _aligned_replay(
    capsule: SourceCapsule,
    *,
    period: int,
    config: object,
    resolved_config: ResolvedSRConfig,
) -> CandidateReplay:
    candidate_atr = compute_atr_series(capsule, period)
    reference_atr = compute_atr_series(capsule, config.evaluation_reference_period)
    common_start_index = max(config.common_start_period, period, config.evaluation_reference_period)
    if common_start_index != config.common_start_period:
        raise ContractValidationError("candidate period bypassed the locked common start")
    if len(capsule.bars) <= common_start_index:
        raise ContractValidationError("source is too short for common ATR start")
    aligned_bars: list[ClosedBar] = []
    aligned_reference: list[float] = []
    state_key = SRStateKey(config.venue, config.symbol, config.timeframe)
    for index in range(common_start_index, len(capsule.bars)):
        candidate_value = candidate_atr[index]
        reference_value = reference_atr[index]
        if candidate_value is None or reference_value is None:
            raise ContractValidationError("common ATR alignment encountered an invalid value")
        source_bar = capsule.bars[index]
        aligned_bars.append(
            ClosedBar(
                state_key=state_key,
                bar_id=source_bar.bar_id,
                closed_at=source_bar.closed_at,
                open=source_bar.open,
                high=source_bar.high,
                low=source_bar.low,
                close=source_bar.close,
                atr_at_close=candidate_value,
            )
        )
        aligned_reference.append(reference_value)
    model_bars = tuple(aligned_bars)
    initial_state = create_initial_state(state_key, resolved_config)
    final_state, snapshots = replay_bars(initial_state, model_bars, resolved_config)
    trace = build_evaluation_trace(snapshots, resolved_config)
    diagnostics = compute_diagnostics(trace)
    return CandidateReplay(
        period=period,
        reference_period=config.evaluation_reference_period,
        common_start_index=common_start_index,
        model_bars=model_bars,
        reference_atr=tuple(aligned_reference),
        initial_state=initial_state,
        final_state=final_state,
        snapshots=snapshots,
        trace=trace,
        diagnostics=diagnostics,
    )


def replay_candidate(
    capsule: SourceCapsule,
    period: int,
    *,
    config: object,
    resolved_config: ResolvedSRConfig,
) -> CandidateReplay:
    """Replay one candidate once over the complete aligned capsule history."""
    if type(capsule) is not SourceCapsule:
        raise ContractValidationError("capsule must be exactly SourceCapsule")
    if period not in config.candidate_periods:
        raise ContractValidationError("period is not in the predeclared candidate set")
    if resolved_config.asset != config.symbol or resolved_config.timeframe != config.timeframe:
        raise ContractValidationError("resolved SR config does not match calibration")
    return _aligned_replay(capsule, period=period, config=config, resolved_config=resolved_config)


def replay_candidates(
    capsule: SourceCapsule,
    periods: Iterable[int],
    *,
    config: object,
    resolved_config: ResolvedSRConfig,
) -> tuple[CandidateReplay, ...]:
    """Replay candidates in canonical period order, independent of input order."""
    requested = tuple(periods)
    if len(set(requested)) != len(requested):
        raise ContractValidationError("candidate periods must be unique")
    if any(type(period) is not int or isinstance(period, bool) for period in requested):
        raise ContractValidationError("candidate periods must be integers")
    if not requested or any(period not in config.candidate_periods for period in requested):
        raise ContractValidationError("candidate periods must be predeclared")
    results = tuple(
        replay_candidate(capsule, period, config=config, resolved_config=resolved_config)
        for period in sorted(requested)
    )
    if not results:
        raise ContractValidationError("at least one candidate is required")
    reference_ids = tuple(bar.bar_id for bar in results[0].model_bars)
    reference_times = tuple(bar.closed_at for bar in results[0].model_bars)
    reference_ohlc = tuple((bar.open, bar.high, bar.low, bar.close) for bar in results[0].model_bars)
    reference_atr = results[0].reference_atr
    for result in results[1:]:
        if tuple(bar.bar_id for bar in result.model_bars) != reference_ids or tuple(bar.closed_at for bar in result.model_bars) != reference_times:
            raise ContractValidationError("candidate replay identities are not aligned")
        if tuple((bar.open, bar.high, bar.low, bar.close) for bar in result.model_bars) != reference_ohlc:
            raise ContractValidationError("candidate replay OHLC differs")
        if result.reference_atr != reference_atr:
            raise ContractValidationError("reference ATR differs across candidates")
    return results


__all__ = ["compute_atr_series", "replay_candidate", "replay_candidates"]
