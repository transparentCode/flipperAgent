"""
Optimization Staleness Checker
===============================
Determines whether per-asset optimization results are stale and
need re-running.

Staleness criteria (all configurable via ``sr.optimization.staleness``):
  1. **Age** — optimization older than ``max_age_days``
  2. **Drift** — current asset characteristics have drifted beyond
     ``wick_drift_threshold`` or ``atr_drift_threshold`` from the
     snapshot taken at optimization time
  3. **Never optimized** — no ``_optimization_meta`` present
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class StalenessResult:
    """Result of a staleness check for one (asset, timeframe)."""
    stale: bool
    reason: str = ""            # "never_optimized" | "age" | "drift" | "fresh"
    age_days: float = 0.0
    wick_drift: float = 0.0
    atr_drift: float = 0.0

    @property
    def fresh(self) -> bool:
        return not self.stale


@dataclass(frozen=True)
class StalenessConfig:
    """Configurable thresholds for staleness detection."""
    max_age_days: int = 7
    wick_drift_threshold: float = 0.3    # absolute wick_body_ratio drift
    atr_drift_threshold: float = 0.5     # fractional atr_pct drift (50%)
    hurst_drift_threshold: float = 0.15  # absolute hurst drift


class StalenessChecker:
    """Check optimization freshness for a specific (asset, timeframe) pair."""

    def __init__(self, config: Optional[StalenessConfig] = None):
        self._config = config or StalenessConfig()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StalenessChecker":
        """Build from yaml dict (``sr.optimization.staleness``)."""
        return cls(config=StalenessConfig(
            max_age_days=int(d.get("max_age_days", 7)),
            wick_drift_threshold=float(d.get("wick_drift_threshold", 0.3)),
            atr_drift_threshold=float(d.get("atr_drift_threshold", 0.5)),
            hurst_drift_threshold=float(d.get("hurst_drift_threshold", 0.15)),
        ))

    def check(
        self,
        optimization_meta: Optional[Dict[str, Any]],
        current_wick_body_ratio: float = 1.0,
        current_atr_pct: float = 0.01,
        current_hurst: float = 0.5,
    ) -> StalenessResult:
        """
        Check staleness of optimization results.

        Parameters
        ----------
        optimization_meta
            The ``_optimization_meta`` dict from the asset's yaml section.
            Contains ``last_optimized``, ``characteristics_snapshot``, etc.
        current_wick_body_ratio
            Current data-derived wick_body_ratio.
        current_atr_pct
            Current data-derived ATR as percentage of price.
        current_hurst
            Current data-derived Hurst exponent.

        Returns
        -------
        StalenessResult
        """
        if optimization_meta is None:
            return StalenessResult(stale=True, reason="never_optimized")

        # Age check
        last_opt_str = optimization_meta.get("last_optimized")
        if last_opt_str is None:
            return StalenessResult(stale=True, reason="never_optimized")

        try:
            last_opt = datetime.fromisoformat(last_opt_str)
            if last_opt.tzinfo is None:
                last_opt = last_opt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_days = (now - last_opt).total_seconds() / 86400.0
        except (ValueError, TypeError):
            return StalenessResult(stale=True, reason="never_optimized")

        if age_days > self._config.max_age_days:
            return StalenessResult(stale=True, reason="age", age_days=age_days)

        # Drift check
        snapshot = optimization_meta.get("characteristics_snapshot", {})
        snap_wick = snapshot.get("wick_body_ratio", 1.0)
        snap_atr_pct = snapshot.get("atr_pct", 0.01)
        snap_hurst = snapshot.get("hurst", 0.5)

        wick_drift = abs(current_wick_body_ratio - snap_wick)
        atr_base = max(snap_atr_pct, 1e-6)
        atr_drift = abs(current_atr_pct - snap_atr_pct) / atr_base
        hurst_drift = abs(current_hurst - snap_hurst)

        if wick_drift > self._config.wick_drift_threshold:
            return StalenessResult(
                stale=True, reason="drift",
                age_days=age_days, wick_drift=wick_drift, atr_drift=atr_drift,
            )
        if atr_drift > self._config.atr_drift_threshold:
            return StalenessResult(
                stale=True, reason="drift",
                age_days=age_days, wick_drift=wick_drift, atr_drift=atr_drift,
            )
        if hurst_drift > self._config.hurst_drift_threshold:
            return StalenessResult(
                stale=True, reason="drift",
                age_days=age_days, wick_drift=wick_drift, atr_drift=atr_drift,
            )

        return StalenessResult(
            stale=False, reason="fresh",
            age_days=age_days, wick_drift=wick_drift, atr_drift=atr_drift,
        )
