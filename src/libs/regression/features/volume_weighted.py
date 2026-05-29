"""Volume-weighted feature extractor.

Ported from v1 ``app/regression/features/volume_weighted.py``.
Provides: volume_weights, volume_raw, volume_clipped.
Clip percentile and transform type read from config.
"""
from __future__ import annotations

import numpy as np

from ..config.schema import PluginConfig
from ..contracts.context import PipelineRequest
from ..contracts.result import FeatureSet
from .base import FeatureExtractor, FeatureRegistry

_VALID_WEIGHT_METHODS = ("sqrt", "log", "linear")


@FeatureRegistry.register("volume_weighted")
class VolumeWeightedFeatures(FeatureExtractor):
    requires = []
    provides = ["weights", "volume_raw", "volume_clipped"]
    min_warmup_bars = 0

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self.clip_pct: float = config.get("volume_clip_pct", 95.0)
        if self.clip_pct is not None and not (0 < self.clip_pct <= 100):
            raise ValueError(f"volume_clip_pct must be in (0, 100], got {self.clip_pct}")

        self.weight_method: str = config.get("weight_method", "sqrt")
        if self.weight_method not in _VALID_WEIGHT_METHODS:
            raise ValueError(
                f"Unknown weight_method: {self.weight_method!r}. "
                f"Expected one of {_VALID_WEIGHT_METHODS}"
            )

    def extract(self, request: PipelineRequest, features: FeatureSet) -> None:
        v_raw = features.volume_raw

        volume_valid = np.isfinite(v_raw) & (v_raw >= 0)
        features.valid_mask &= volume_valid
        combined_valid = features.valid_mask

        if features.volume_clipped is None or len(features.volume_clipped) != len(v_raw):
            features.volume_clipped = np.empty_like(v_raw)
        v_clipped = features.volume_clipped

        # Clip outliers
        v_valid_for_pct = v_raw[combined_valid]
        if len(v_valid_for_pct) > 0 and self.clip_pct is not None:
            clip_val = np.percentile(v_valid_for_pct, self.clip_pct)
            np.clip(v_raw, 0.0, clip_val, out=v_clipped)
        else:
            np.maximum(v_raw, 0.0, out=v_clipped)

        # Transform
        if self.weight_method == "sqrt":
            np.sqrt(v_clipped, out=features.weights)
        elif self.weight_method == "log":
            np.log1p(v_clipped, out=features.weights)
        else:
            features.weights[:] = v_clipped

        features.weights[~combined_valid] = 0.0

        # Normalize for numerical stability
        w_valid = features.weights[combined_valid]
        w_mean = float(np.mean(w_valid)) if len(w_valid) > 0 else 0.0

        if w_mean > 0:
            features.weights /= w_mean
        else:
            features.weights.fill(0.0)
            features.weights[combined_valid] = 1.0
