"""Atomic write of optimized params to configs/optimized_params.yaml.

Reads current params from configs/models.yaml (the source of truth for
live model params). Writes optimized params to a separate file
(configs/optimized_params.yaml) so they can be reviewed before promotion.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import yaml

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

_OPTIMIZED_PARAMS_FILE = "optimized_params.yaml"
_MODELS_FILE = "models.yaml"


def _config_dir() -> Path:
    """Return the config directory from ConfigManager."""
    cm = ConfigManager()
    return cm._config_dir


def read_current_params(
    model_name: str,
    asset: str,
    timeframe: str,
) -> dict[str, Any] | None:
    """Read current params for a model/asset/timeframe from configs/models.yaml.

    Returns None if the model or asset/timeframe combination is not found.
    """
    models_path = _config_dir() / _MODELS_FILE
    if not models_path.exists():
        return None

    with open(models_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Try: models.<model_name>.assets.<asset>.timeframes.<timeframe>.params
    model_cfg = data.get("models", {}).get(model_name, {})
    asset_cfg = model_cfg.get("assets", {}).get(asset, {})
    tf_cfg = asset_cfg.get("timeframes", {}).get(timeframe, {})
    params = tf_cfg.get("params")
    if params:
        return params

    # Fallback: models.<model_name>.params (global defaults)
    return model_cfg.get("params")


def write_best_params(
    model_name: str,
    asset: str,
    timeframe: str,
    params: dict[str, Any],
) -> Path:
    """Atomically write optimized params to configs/optimized_params.yaml.

    Uses write-to-temp-then-rename for atomicity. Merges into existing
    file content if it already exists.

    Returns the path to the written file.
    """
    out_path = _config_dir() / _OPTIMIZED_PARAMS_FILE

    # Load existing content
    existing: dict[str, Any] = {}
    if out_path.exists():
        with open(out_path, "r", encoding="utf-8") as f:
            existing = yaml.safe_load(f) or {}

    # Merge: optimized_params.<model_name>.<asset>.<timeframe> = params
    if model_name not in existing:
        existing[model_name] = {}
    if asset not in existing[model_name]:
        existing[model_name][asset] = {}
    existing[model_name][asset][timeframe] = params

    # Atomic write via temp file + rename
    parent = out_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        dir=str(parent),
        delete=False,
        encoding="utf-8",
    ) as tmp:
        yaml.dump(existing, tmp, default_flow_style=False, sort_keys=False)
        tmp_path = Path(tmp.name)

    tmp_path.rename(out_path)
    logger.info(f"Wrote optimized params for {model_name}/{asset}/{timeframe} to {out_path}")
    return out_path
