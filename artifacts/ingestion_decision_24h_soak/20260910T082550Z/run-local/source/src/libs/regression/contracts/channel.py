"""Immutable contract for structural residual channel geometry."""

from __future__ import annotations

from dataclasses import dataclass

from .structural import StructuralRegressionEstimate


@dataclass(frozen=True)
class StructuralChannelEstimate:
    """Descriptive residual-quantile geometry around one structural fit."""

    structural: StructuralRegressionEstimate
    channel_id: str
    channel_config_hash: str
    inner_coverage: float
    outer_coverage: float
    lower_inner_residual_log: float
    upper_inner_residual_log: float
    lower_outer_residual_log: float
    upper_outer_residual_log: float
    lower_inner_price: float
    upper_inner_price: float
    lower_outer_price: float
    upper_outer_price: float
    current_residual_log: float
