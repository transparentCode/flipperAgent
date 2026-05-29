from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

import pandas as pd

from ..config.schema import ResolvedPipelineConfig, VolumeProfile


@dataclass
class AssetMeta:
    """Static metadata about an asset, resolved from config at startup."""

    asset_class: str  # "crypto" | "stock" | "fx"
    volume_profile: VolumeProfile  # from asset_class config tier
    session_gap_handling: bool = False
    low_liquidity_window_handling: bool = False
    exchange: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RegimeSnapshot:
    """Typed regime signal consumed read-only by pipeline.

    Mirrors v1 contract but more explicit about fields.
    """

    label: str  # CLEAN_TREND | VOLATILE_TREND | QUIET_MR | CHOPPY
    confidence: float  # 0.0–1.0
    transition_prob: float  # 0.0–1.0
    suggested_window: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CascadeContext:
    """Result from a higher timeframe, propagated down during MTF cascade."""

    source_tf: str
    slope: float
    direction: str
    confidence: float
    band_width: float
    dominant_method: str


@dataclass
class PipelineRequest:
    """Complete input to a single pipeline execution.

    Config is already resolved — pipeline does not do config resolution.
    """

    df: pd.DataFrame
    asset: str
    timeframe: str
    mode: Literal["fit_last", "fit_series"]
    config: ResolvedPipelineConfig

    # Optional context
    regime: Optional[RegimeSnapshot] = None
    cascade: Optional[CascadeContext] = None
    asset_meta: Optional[AssetMeta] = None

    # Runtime override: effective window after regime adjustment
    effective_window: Optional[int] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def resolve_window(self) -> int:
        """Compute effective window: regime override if allowed, else config default."""
        if self.effective_window is not None:
            return self.effective_window

        base = self.config.window_size

        if (
            self.config.regime_window_override
            and self.regime is not None
            and self.regime.suggested_window is not None
        ):
            clamped = max(
                self.config.min_window,
                min(self.config.max_window, self.regime.suggested_window),
            )
            return clamped

        return base
