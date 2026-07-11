"""Asset/timeframe profile contracts and helpers for RegimeProbV1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from libs.models.regime_prob_v1.contracts import AssetTimeframeProfile

PROFILE_NAMES: tuple[str, ...] = (
    "balanced",
    "trend",
    "breakout",
    "mean_reversion",
    "risk_off",
)
PROFILE_TIERS: tuple[str, ...] = (
    "low",
    "medium",
    "high",
    "extreme",
    "unavailable",
)


@dataclass(frozen=True)
class AssetTimeframeProfileReport:
    """Derived profile plus the metrics used to assign its tiers."""

    profile: AssetTimeframeProfile
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "metrics": dict(self.metrics),
            "diagnostics": dict(self.diagnostics),
        }


def profile_to_dict(profile: AssetTimeframeProfile) -> dict[str, Any]:
    """Serialize one profile contract."""
    return asdict(profile)


__all__ = [
    "AssetTimeframeProfile",
    "AssetTimeframeProfileReport",
    "PROFILE_NAMES",
    "PROFILE_TIERS",
    "profile_to_dict",
]
