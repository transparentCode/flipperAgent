"""Public Phase-C update API for deterministic single-timeframe family snapshots."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .configuration.contracts import ResolvedTrendlineFamilyConfig
from .configuration.resolver import TrendlineFamilyConfigResolver
from .contracts import ContractValidationError, TrendlineFamilyOutput, TrendlineFamilySnapshot
from .provider import LineCandidateProvider
from .registry import get_line_provider
from .repository import TrendlineFamilyRepository
from .tracker import TrendlineFamilyTracker
from .mtf import MTFGeometrySnapshot, MTFNormalizationContext, compose_mtf_snapshot


def update_trendline_families(
    ohlcv: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    repository: TrendlineFamilyRepository,
    config: ResolvedTrendlineFamilyConfig | None = None,
    config_path: str | Path = "configs/trendline_family.yaml",
    runtime_override: Mapping[str, Any] | None = None,
    provider: LineCandidateProvider | None = None,
    observed_at: datetime | None = None,
    tick_size: float | None = None,
) -> TrendlineFamilyOutput:
    """Run one confirmed-bar family update and persist its immutable snapshot."""

    _validate_request_identity(asset=asset, timeframe=timeframe)
    if config is not None:
        if not isinstance(config, ResolvedTrendlineFamilyConfig):
            raise ContractValidationError("config must be ResolvedTrendlineFamilyConfig")
        if config.asset != asset or config.timeframe != timeframe:
            raise ContractValidationError("resolved config identity does not match API request")
        if runtime_override is not None:
            raise ContractValidationError("runtime_override requires API config resolution")
        resolved = config
    else:
        resolved = TrendlineFamilyConfigResolver.from_path(config_path).resolve(
            asset=asset,
            timeframe=timeframe,
            runtime_override=runtime_override,
        )
    selected_provider = provider or get_line_provider("native_deterministic")
    return TrendlineFamilyTracker(
        repository=repository,
        provider=selected_provider,
        config=resolved,
    ).update(ohlcv, observed_at=observed_at, tick_size=tick_size)


def _validate_request_identity(*, asset: str, timeframe: str) -> None:
    if not isinstance(asset, str) or not asset:
        raise ContractValidationError("asset must be a non-empty string")
    if not isinstance(timeframe, str) or not timeframe:
        raise ContractValidationError("timeframe must be a non-empty string")


def compose_trendline_family_mtf(
    *,
    source_snapshots: Mapping[str, TrendlineFamilySnapshot],
    decision_timestamp: datetime,
    normalization_context: MTFNormalizationContext,
    config: ResolvedTrendlineFamilyConfig,
) -> MTFGeometrySnapshot:
    """Public pure Phase-H composition boundary over confirmed source snapshots."""

    return compose_mtf_snapshot(
        source_snapshots=source_snapshots,
        decision_timestamp=decision_timestamp,
        normalization_context=normalization_context,
        config=config,
    )
