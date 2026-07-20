"""The only YAML-reading boundary for trendline-family configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from libs.models.trendline.contracts import ContractValidationError


def load_trendline_family_config(path: str | Path) -> Mapping[str, Any]:
    """Load a YAML mapping without resolving asset/timeframe-specific values."""

    config_path = Path(path)
    try:
        with config_path.open("r", encoding="utf-8") as stream:
            payload = yaml.safe_load(stream)
    except OSError as exc:
        raise ContractValidationError(f"cannot read trendline-family config: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ContractValidationError(f"invalid trendline-family YAML: {config_path}") from exc
    if not isinstance(payload, dict):
        raise ContractValidationError("trendline-family config root must be a mapping")
    return payload
