"""The only YAML read boundary for Trendline V2 configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..domain.validation import ContractValidationError
from .contracts import ResolvedTrendlineV2Config
from .resolver import resolve_trendline_v2_config


def load_trendline_v2_config(path: str | Path) -> ResolvedTrendlineV2Config:
    try:
        config_path = Path(path)
    except TypeError as exc:
        raise ContractValidationError("configuration path must be path-like") from exc
    if not config_path.is_file():
        raise ContractValidationError(f"configuration file does not exist: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw: Any = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ContractValidationError("unable to read Trendline V2 configuration") from exc
    return resolve_trendline_v2_config(raw)


__all__ = ["load_trendline_v2_config"]
