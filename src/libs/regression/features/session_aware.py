"""Session-aware feature extractor.

Emits a ``session_mask`` for assets whose trading session is discontinuous or whose
volume is only a liquidity proxy. ``RegressionPipeline`` applies that mask after
feature extraction by ANDing it into ``FeatureSet.valid_mask`` and zeroing masked
weights so downstream methods exclude those bars consistently.

For stocks: detects session gaps and marks the first post-gap bar invalid.
For fx: marks low-liquidity windows invalid.
For crypto: no-op pass-through (continuous market).
"""
from __future__ import annotations

import numpy as np

from ..config.schema import PluginConfig, VolumeProfile
from ..contracts.context import PipelineRequest
from ..contracts.result import FeatureSet
from .base import FeatureExtractor, FeatureRegistry


@FeatureRegistry.register("session_aware")
class SessionAwareFeatures(FeatureExtractor):
    requires = []
    provides = ["session_mask"]
    min_warmup_bars = 0

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self.gap_threshold_seconds: int = config.get("gap_threshold_seconds", 7200)
        self.low_liquidity_volume_pct: float = config.get("low_liquidity_volume_pct", 10.0)

    def extract(self, request: PipelineRequest, features: FeatureSet) -> None:
        n = len(features.valid_mask)
        session_mask = np.ones(n, dtype=bool)

        meta = request.asset_meta
        if meta is None:
            features.session_mask = session_mask
            return

        if meta.volume_profile == VolumeProfile.CONTINUOUS:
            # Crypto — all bars are valid session bars.
            features.session_mask = session_mask
            return

        if meta.volume_profile == VolumeProfile.SESSION:
            # Stock — emit a session mask; pipeline applies it as the runtime gate.
            if meta.session_gap_handling:
                session_mask = self._detect_session_gaps(features)
            features.session_mask = session_mask
            return

        if meta.volume_profile == VolumeProfile.PROXY:
            # FX — emit a liquidity mask; pipeline applies it as the runtime gate.
            if meta.low_liquidity_window_handling:
                session_mask = self._detect_low_liquidity(features)
            features.session_mask = session_mask
            return

        features.session_mask = session_mask

    def _detect_session_gaps(self, features: FeatureSet) -> np.ndarray:
        """Mark bars immediately after a gap > threshold as gap bars."""
        n = len(features.timestamps)
        mask = np.ones(n, dtype=bool)

        ts = features.timestamps
        if n < 2:
            return mask

        try:
            ts_numeric = ts.astype("datetime64[s]").astype(np.int64)
        except (ValueError, TypeError):
            return mask

        diffs = np.diff(ts_numeric)
        gap_indices = np.where(diffs > self.gap_threshold_seconds)[0]
        # First bar after each gap is unreliable
        post_gap = gap_indices + 1
        post_gap = post_gap[post_gap < n]
        mask[post_gap] = False

        return mask

    def _detect_low_liquidity(self, features: FeatureSet) -> np.ndarray:
        """Mark bars with volume below pct threshold of median as low-liquidity."""
        n = len(features.volume_raw)
        mask = np.ones(n, dtype=bool)

        v = features.volume_raw
        valid = np.isfinite(v) & (v > 0)
        if np.sum(valid) < 3:
            return mask

        median_vol = float(np.median(v[valid]))
        if median_vol <= 0:
            return mask

        threshold = median_vol * (self.low_liquidity_volume_pct / 100.0)
        mask = v >= threshold
        mask[~valid] = False

        return mask
