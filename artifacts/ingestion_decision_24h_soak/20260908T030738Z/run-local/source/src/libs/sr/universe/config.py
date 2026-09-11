"""
Universe-level config for S/R pipeline.
========================================
Holds universe-wide settings: asset list, parallelism, per-asset
overrides, and cross-asset configuration.

Supports the 3-tier cascade:
  * Global defaults (universe-level)
  * Per-timeframe overrides
  * Per-asset overrides
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AssetSRConfig:
    """Per-asset S/R config overrides."""
    symbol: str
    timeframes: Optional[List[str]] = None
    enabled_kernels: Optional[List[str]] = None  # None = all
    disabled_kernels: Optional[List[str]] = None
    config_overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UniverseSRConfig:
    """Universe-level configuration for batch S/R processing."""

    # Asset list
    assets: List[AssetSRConfig] = field(default_factory=list)

    # Parallelism
    max_workers: int = 4
    timeout_per_asset_s: float = 30.0

    # Global defaults
    default_timeframes: List[str] = field(default_factory=lambda: ["1h"])
    default_enabled_kernels: Optional[List[str]] = None

    # Global config (base layer of cascade)
    global_config: Dict[str, Any] = field(default_factory=dict)

    # Per-timeframe overrides (middle layer)
    timeframe_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Cross-asset settings (Phase 4)
    cross_asset_enabled: bool = False
    correlation_threshold: float = 0.6
    min_universe_agreement: int = 2

    # Sidecar profiling / hot-reload settings
    sidecar_enabled: bool = False
    sidecar_queue_backend: str = "sqlite"
    sidecar_queue_path: Optional[str] = None
    sidecar_config_path: Optional[str] = None
    sidecar_watch_config: bool = False
    sidecar_stale_after_days: int = 7

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UniverseSRConfig":
        """Build config from raw dict (e.g., parsed YAML)."""
        assets = [
            AssetSRConfig(**a) if isinstance(a, dict) else a
            for a in d.get("assets", [])
        ]
        return cls(
            assets=assets,
            max_workers=d.get("max_workers", 4),
            timeout_per_asset_s=d.get("timeout_per_asset_s", 30.0),
            default_timeframes=d.get("default_timeframes", ["1h"]),
            default_enabled_kernels=d.get("default_enabled_kernels"),
            global_config=d.get("global_config", {}),
            timeframe_overrides=d.get("timeframe_overrides", {}),
            cross_asset_enabled=d.get("cross_asset_enabled", False),
            correlation_threshold=d.get("correlation_threshold", 0.6),
            min_universe_agreement=d.get("min_universe_agreement", 2),
            sidecar_enabled=d.get("sidecar_enabled", False),
            sidecar_queue_backend=d.get("sidecar_queue_backend", "sqlite"),
            sidecar_queue_path=d.get("sidecar_queue_path"),
            sidecar_config_path=d.get("sidecar_config_path"),
            sidecar_watch_config=d.get("sidecar_watch_config", False),
            sidecar_stale_after_days=d.get("sidecar_stale_after_days", 7),
        )
