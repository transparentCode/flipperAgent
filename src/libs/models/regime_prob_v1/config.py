"""Configuration objects for RegimeProbV1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RuntimeMode = Literal[
    "disabled",
    "shadow",
    "paper_filter_only",
    "paper_sizing",
    "live_filter_only",
    "live_sizing",
]


@dataclass(frozen=True)
class RegimeProbFeatureFrameConfig:
    """Controls which point-in-time features are included in the frame.

    `include_hilbert`, `include_regime_classification`, `include_trendlines`, and
    `include_mtf` are reserved placeholders in the current scaffold. They are
    accepted for forward compatibility but are runtime no-ops until the
    corresponding feature adapters are wired.
    """

    include_regime_v2_evidence: bool = True
    include_policy_scores: bool = True
    include_raw_break_features: bool = True
    include_bcpd: bool = True
    include_hurst: bool = True
    include_hilbert: bool = False
    include_regime_classification: bool = False
    include_trendlines: bool = False
    include_external_context: bool = False
    include_mtf: bool = False


@dataclass(frozen=True)
class RegimeProbLabelConfig:
    """Offline-only label generation settings."""

    horizons: tuple[int, ...] = (3, 6, 12, 24)
    fee_bps: float = 5.0
    purge_bars: int = 24
    min_support_count: int = 20
    require_directional_breakout: bool = True


@dataclass(frozen=True)
class RegimeProbRuntimeConfig:
    """Lightweight runtime safety contract for RegimeProbV1.

    This is intentionally a shadow-first contract. While state probabilities are
    sourced from `deterministic_proxy`, RegimeProbV1 must not claim true HMM
    posterior behavior or force trades independently of RegimeV2.
    """

    mode: RuntimeMode = "shadow"
    can_force_trade: bool = False
    fallback_to_regime_v2: bool = True


__all__ = [
    "RegimeProbFeatureFrameConfig",
    "RegimeProbLabelConfig",
    "RegimeProbRuntimeConfig",
    "RuntimeMode",
]
