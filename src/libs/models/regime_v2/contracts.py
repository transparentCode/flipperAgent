"""Contracts for RegimeV2.

These dataclasses are intentionally framework-light.  Runtime adapters can pack
or unpack them into existing Pydantic transport contracts when needed, but the
core regime engine stays independent and easy to test.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


Number = float | int


@dataclass(frozen=True)
class DataQualityReport:
    """Point-in-time data quality summary for a regime run."""

    usable: bool
    rows: int
    required_fields: tuple[str, ...]
    missing_required_fields: tuple[str, ...] = ()
    missing_ratio: float = 0.0
    duplicate_timestamps: int = 0
    monotonic_index: bool = True
    warmup_complete: bool = True
    anomaly_score: float = 0.0
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegimeEvidence:
    """Market-behavior evidence produced by RegimeV2.

    Values are normalized where practical.  Scores use the following convention:
    ``0.0`` = absent/low, ``1.0`` = strong/high.  Direction is separated from
    strength to avoid the old label → position-size coupling.
    """

    timestamp: Any
    asset: str
    timeframe: str

    trend_direction: str
    trend_strength: float
    trend_persistence: float
    trend_confidence: float

    volatility_percentile: float
    volatility_state: str
    compression_score: float
    shock_risk: float

    mean_reversion_score: float
    range_quality: float
    chop_risk: float

    structural_break_risk: float
    breakout_quality: float
    false_breakout_risk: float

    market_context_score: float
    breadth_confirmation: float
    liquidity_stress: float

    confidence: float
    uncertainty: float
    summary_label: str

    pre_breakout_setup_score: float = 0.0
    displacement_breakout_score: float = 0.0
    post_breakout_retest_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegimePolicy:
    """Policy derived from evidence.

    The policy decides which playbooks are allowed.  It does not directly emit a
    trade signal and does not override downstream risk sizing.
    """

    allow_trend_following: bool
    allow_breakout: bool
    allow_mean_reversion: bool
    allow_scalping: bool
    allow_countertrend: bool

    max_position_scale: float
    stop_multiplier: float
    target_multiplier: float
    holding_period_prior: int

    trend_score: float = 0.0
    breakout_score: float = 0.0
    mean_reversion_score: float = 0.0
    scalping_score: float = 0.0
    countertrend_score: float = 0.0
    breakout_setup_score: float = 0.0
    displacement_breakout_score: float = 0.0
    retest_breakout_score: float = 0.0

    no_trade_reason: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegimeV2Output:
    """Single-bar RegimeV2 output."""

    evidence: RegimeEvidence
    policy: RegimePolicy
    data_quality: DataQualityReport
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "policy": self.policy.to_dict(),
            "data_quality": self.data_quality.to_dict(),
            "diagnostics": dict(self.diagnostics),
        }


__all__ = [
    "DataQualityReport",
    "RegimeEvidence",
    "RegimePolicy",
    "RegimeV2Output",
]
