"""Deterministic values derived outside the semantic YAML surface."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ResolvedTrendlineFamilyConfig, canonical_timeframe_duration_seconds


@dataclass(frozen=True)
class DerivedTrendlineConfig:
    timeframe_duration_seconds: int
    minimum_warmup_bars: int
    maximum_historical_horizon_bars: int


def derive_configuration(config: ResolvedTrendlineFamilyConfig) -> DerivedTrendlineConfig:
    return DerivedTrendlineConfig(
        timeframe_duration_seconds=canonical_timeframe_duration_seconds(config.timeframe),
        minimum_warmup_bars=max(config.candidate.min_bars, config.matching.normalization_atr_window, config.interaction.atr_window),
        maximum_historical_horizon_bars=max(config.candidate.lookback_bars, config.lifecycle.expire_after_bars),
    )


__all__ = ["DerivedTrendlineConfig", "derive_configuration"]
