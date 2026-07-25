"""Config apply and YAML snippet builders for trendlines pipeline workflows."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def build_yaml_snippet(results: Dict[str, Dict[str, Any]], asset: str) -> Dict[str, Any]:
    """Convert promoted trendlines results into a trendlines_pipeline universe block."""

    asset_block: Dict[str, Any] = {"timeframes": {}}

    for timeframe, result in results.items():
        best_params = dict(result.get("best_params", {}))
        if not best_params:
            if "lookback_bars" in result:
                best_params["lookback_bars"] = result["lookback_bars"]
            if "extractor" in result:
                best_params["extractor"] = result["extractor"]
            if "fitter" in result:
                best_params["fitter"] = result["fitter"]
        timeframe_entry: Dict[str, Any] = {}
        if "lookback_bars" in best_params:
            timeframe_entry["lookback_bars"] = best_params["lookback_bars"]
        if "extractor" in best_params:
            timeframe_entry["extractor"] = best_params["extractor"]
        if "fitter" in best_params:
            timeframe_entry["fitter"] = best_params["fitter"]
        asset_block["timeframes"][timeframe] = timeframe_entry

    return {asset: asset_block}


def apply_pipeline_optimization_to_config(
    asset: str,
    results: Dict[str, Dict[str, Any]],
    yaml_path: str,
) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("PyYAML required: pip install pyyaml") from exc

    for timeframe, result in results.items():
        if str(result.get("engine", "trendlines")).strip().lower() != "trendlines":
            raise ValueError(
                f"Trendlines config apply supports only trendlines engine results; got {result.get('engine')} for {asset} {timeframe}"
            )
        promotion = dict(result.get("promotion_result", {}))
        if not bool(promotion.get("should_promote", False)):
            raise ValueError(
                f"Trendlines pipeline result for {asset} {timeframe} is not approved for config apply"
            )

    path = Path(yaml_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw = raw or {}

    if "trendlines_pipeline" in raw:
        pipe = raw["trendlines_pipeline"]
    elif "universe" in raw:
        pipe = raw
    else:
        pipe = raw.setdefault("trendlines_pipeline", {})

    pipe.setdefault("universe", {})
    universe = pipe["universe"]
    asset_block = universe.setdefault(asset, {})

    snippet = build_yaml_snippet(results, asset)[asset]
    timeframes_block = asset_block.setdefault("timeframes", {})
    for timeframe, timeframe_payload in snippet.get("timeframes", {}).items():
        target = timeframes_block.setdefault(timeframe, {})
        _deep_merge(target, timeframe_payload)

    path.write_text(
        yaml.dump(raw, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


__all__ = [
    "apply_pipeline_optimization_to_config",
    "build_yaml_snippet",
]
