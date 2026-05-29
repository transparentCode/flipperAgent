"""
Shared pipeline-factory builder for V2 optimization.

Builds the ``(params, asset, timeframe) -> (pipeline, config)`` callable
required by ``RegressionMOTPEOptimizer``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Callable, Dict, Tuple

from app.common.config.schema import PluginConfig
from app.regression.config.resolver import ConfigResolver
from app.regression.config.schema import ResolvedPipelineConfig
from app.regression.pipeline import RegressionPipeline
from app.regression.state import NullStateManager


def build_pipeline_factory(
    resolver: ConfigResolver,
) -> Callable[[Dict[str, Any], str, str], Tuple[RegressionPipeline, ResolvedPipelineConfig]]:
    """Build a pipeline_factory callable for RegressionMOTPEOptimizer.

    Returns a function ``(params, asset, timeframe) -> (pipeline, config)``.
    Applies param-overlay logic (methods, ensemble, uncertainty) onto the
    resolved base config, recomputes config_hash, and constructs a pipeline.
    """

    def factory(params: dict, asset: str, timeframe: str):
        base_config = resolver.resolve(asset, timeframe)

        overrides: Dict[str, Any] = {}
        methods_dict = dict(base_config.methods) if hasattr(base_config, "methods") else {}
        ensemble_cfg = getattr(base_config, "ensemble", None)
        uncertainty_cfg = getattr(base_config, "uncertainty", None)

        methods_modified = False
        ensemble_modified = False
        uncertainty_modified = False

        for name, value in params.items():
            if "." in name:
                parts = name.split(".")
                if parts[0] == "methods" and len(parts) >= 3:
                    plugin_name = parts[1]
                    param_key = parts[2]
                    if plugin_name in methods_dict:
                        existing = methods_dict[plugin_name]
                        if param_key == "weight":
                            methods_dict[plugin_name] = PluginConfig(
                                name=existing.name, enabled=existing.enabled,
                                weight=float(value), params=existing.params,
                            )
                        else:
                            new_params = dict(existing.params)
                            new_params[param_key] = value
                            methods_dict[plugin_name] = PluginConfig(
                                name=existing.name, enabled=existing.enabled,
                                weight=existing.weight, params=new_params,
                            )
                        methods_modified = True
                elif parts[0] == "ensemble" and len(parts) >= 2 and ensemble_cfg:
                    param_key = parts[1]
                    if param_key == "params" and len(parts) >= 3:
                        param_key = parts[2]
                    new_params = dict(ensemble_cfg.params)
                    new_params[param_key] = value
                    ensemble_cfg = PluginConfig(
                        name=ensemble_cfg.name, enabled=ensemble_cfg.enabled,
                        weight=ensemble_cfg.weight, params=new_params,
                    )
                    ensemble_modified = True
                elif parts[0] == "uncertainty" and len(parts) >= 2 and uncertainty_cfg:
                    param_key = parts[1]
                    if param_key == "params" and len(parts) >= 3:
                        param_key = parts[2]
                    new_params = dict(uncertainty_cfg.params)
                    new_params[param_key] = value
                    uncertainty_cfg = PluginConfig(
                        name=uncertainty_cfg.name, enabled=uncertainty_cfg.enabled,
                        weight=uncertainty_cfg.weight, params=new_params,
                    )
                    uncertainty_modified = True
            elif hasattr(base_config, name):
                overrides[name] = value

        if methods_modified:
            overrides["methods"] = tuple(sorted(methods_dict.items()))
        if ensemble_modified and ensemble_cfg:
            overrides["ensemble"] = ensemble_cfg
        if uncertainty_modified and uncertainty_cfg:
            overrides["uncertainty"] = uncertainty_cfg

        if overrides:
            hash_input = json.dumps(
                {**{k: getattr(base_config, k) for k in ResolvedPipelineConfig.__dataclass_fields__
                    if k not in ("config_hash",) and not k.startswith("_")
                    and isinstance(getattr(base_config, k), (int, float, str, bool))},
                 **overrides},
                sort_keys=True,
                default=str,
            )
            new_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
            overrides["config_hash"] = new_hash
            config = replace(base_config, **overrides)
        else:
            config = base_config

        pipeline = RegressionPipeline(config, NullStateManager())
        return pipeline, config

    return factory
