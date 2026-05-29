"""Log-price feature extractor.

Ported from v1 ``app/regression/features/log_price.py`` with identical math.
Provides: log_prices, close_raw, valid_mask, timestamps.
"""
from __future__ import annotations

import numpy as np

from ..config.schema import PluginConfig
from ..contracts.context import PipelineRequest
from ..contracts.result import FeatureSet
from .base import FeatureExtractor, FeatureRegistry


@FeatureRegistry.register("log_price")
class LogPriceFeatures(FeatureExtractor):
    requires = []
    provides = ["log_prices", "close_raw", "valid_mask", "timestamps"]
    min_warmup_bars = 0

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)

    def extract(self, request: PipelineRequest, features: FeatureSet) -> None:
        y_raw = features.close_raw

        valid = np.isfinite(y_raw) & (y_raw > 0)
        features.valid_mask &= valid

        features.log_prices.fill(np.nan)
        features.log_prices[valid] = np.log(y_raw[valid])
