"""
Tier-aware search space builder for regression optimization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.regression.config.schema import OrchestratorConfig, OptimizationTier
from app.regression.optimization.constants import DEFAULT_PARAM_BOUNDS, DEFAULT_PARAM_TYPES
from app.regression.optimization.models import RegressionOptimizationConfig


@dataclass
class ParamSpec:
    """Specification for a single optimizable parameter."""
    name: str
    param_type: str  # "int" or "float"
    low: float
    high: float
    step: Optional[float] = None


class SearchSpaceBuilder:
    """Builds Optuna search spaces from config tier metadata."""

    _DEFAULT_BOUNDS: Dict[str, Tuple] = dict(DEFAULT_PARAM_BOUNDS)
    _DEFAULT_BOUNDS["ensemble.params"] = (0.0, 1.0)

    _DEFAULT_TYPES: Dict[str, str] = dict(DEFAULT_PARAM_TYPES)

    _TIER_LABEL_MAP = {
        OptimizationTier.GLOBAL: "global_tunable",
        OptimizationTier.PER_TF: "per_tf_tunable",
        OptimizationTier.PER_ASSET_CLASS: "per_asset_tunable",
        OptimizationTier.PER_ASSET: "per_asset_tunable",
    }

    def build(
        self,
        orch_config: OrchestratorConfig,
        tier: OptimizationTier,
        opt_config: Optional[RegressionOptimizationConfig] = None,
    ) -> List[ParamSpec]:
        label = self._TIER_LABEL_MAP.get(tier)
        if label is None:
            return []

        param_names: List[str] = orch_config.optimization.get(label, [])
        custom_bounds = opt_config.param_bounds if opt_config else {}
        custom_types = opt_config.param_types if opt_config else {}

        specs: List[ParamSpec] = []
        for name in param_names:
            bounds = custom_bounds.get(name) or self._DEFAULT_BOUNDS.get(name)
            if bounds is None:
                raise ValueError(f"No optimization bounds defined for {name}")
            param_type = custom_types.get(name) or self._DEFAULT_TYPES.get(name, "float")
            specs.append(ParamSpec(
                name=name,
                param_type=param_type,
                low=bounds[0],
                high=bounds[1],
                step=bounds[2] if len(bounds) > 2 else None,
            ))
        return specs

    def build_merged(
        self,
        orch_config: OrchestratorConfig,
        tiers: List[OptimizationTier],
        opt_config: Optional[RegressionOptimizationConfig] = None,
    ) -> List[ParamSpec]:
        """Build a deduplicated search space from multiple tiers merged together."""
        seen: set = set()
        specs: List[ParamSpec] = []
        for tier in tiers:
            for spec in self.build(orch_config, tier, opt_config):
                if spec.name not in seen:
                    seen.add(spec.name)
                    specs.append(spec)
        return specs

    @staticmethod
    def sample_params(
        trial: Any,
        specs: List[ParamSpec],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for spec in specs:
            if spec.param_type == "int":
                params[spec.name] = trial.suggest_int(
                    spec.name, int(spec.low), int(spec.high),
                    step=int(spec.step) if spec.step else 1,
                )
            else:
                params[spec.name] = trial.suggest_float(
                    spec.name, spec.low, spec.high,
                    step=spec.step,
                )
        return params
