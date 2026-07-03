"""Feature-producer adapter for RegimeV2.

This adapter is intentionally thin: it converts the signal app's rolling
``PriceBar`` history plus the latest engineered features into a dataframe that
``RegimeV2Orchestrator`` can analyze, then serializes the rich output into a
plain dict suitable for ``FeatureVector.features``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from libs.models.regime_v2.contracts import RegimeV2Output
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator

_CONTEXT_PREFIXES = ("eng_",)
_CONTEXT_KEYS = {
    "spread_bps",
    "bid_ask_imbalance",
    "depth_ratio",
}


class RegimeV2FeatureProducer:
    """Optional RegimeV2 producer for live feature enrichment."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        orchestrator: RegimeV2Orchestrator | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.orchestrator = orchestrator or RegimeV2Orchestrator.create(
            self.asset,
            self.timeframe,
            **(params or {}),
        )

    def analyze(
        self,
        price_history: Sequence[dict[str, float]],
        latest_features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        df = pd.DataFrame(list(price_history))
        if latest_features and not df.empty:
            last_idx = df.index[-1]
            for key, value in latest_features.items():
                if _is_context_key(key):
                    df.loc[last_idx, key] = value
        return regime_v2_output_to_dict(self.orchestrator.analyze(df))


def regime_v2_output_to_dict(output: RegimeV2Output) -> dict[str, Any]:
    """Serialize RegimeV2Output for ``FeatureVector.features``."""
    payload = output.to_dict()
    # Convenience top-level fields for dashboards/rules that should not need to
    # inspect nested dicts.
    payload["summary_label"] = output.evidence.summary_label
    payload["confidence"] = output.evidence.confidence
    payload["uncertainty"] = output.evidence.uncertainty
    payload["no_trade_reason"] = output.policy.no_trade_reason
    payload["max_position_scale"] = output.policy.max_position_scale
    return payload


def _is_context_key(key: str) -> bool:
    return key.startswith(_CONTEXT_PREFIXES) or key in _CONTEXT_KEYS


__all__ = ["RegimeV2FeatureProducer", "regime_v2_output_to_dict"]
