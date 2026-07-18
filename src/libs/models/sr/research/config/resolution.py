"""Resolved production-SR configuration loading shared by SR research."""

from __future__ import annotations

from pathlib import Path

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.config.resolver import SRConfigResolver


def load_resolved_sr_config(
    path: str | Path,
    *,
    asset: str,
    timeframe: str,
) -> ResolvedSRConfig:
    """Load and resolve one immutable production SR configuration."""

    return SRConfigResolver(load_sr_config(path)).resolve(
        asset=asset,
        timeframe=timeframe,
    )


__all__ = ["load_resolved_sr_config"]
