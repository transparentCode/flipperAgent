"""Helpers for deriving strategy-facing feature contracts from config."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_INDICATOR_FIELD_ALIASES: dict[str, set[str]] = {
    "MACD": {"MACD_macd", "MACD_line", "MACD_signal", "MACD_histogram"},
    "ADX": {"ADX_adx", "ADX_plus_di", "ADX_minus_di"},
    "BollingerBands": {
        "BollingerBands_middle",
        "BollingerBands_upper",
        "BollingerBands_lower",
    },
    "KeltnerChannel": {
        "KeltnerChannel_middle",
        "KeltnerChannel_upper",
        "KeltnerChannel_lower",
    },
    "KyleLambda": {"kyle_lambda", "kyle_z", "kyle_regime", "kyle_signed"},
    "TFI": {"tfi", "tfi_zscore"},
    "VPIN": {"vpin", "vpin_z", "net_taker_buy_ratio"},
}

_TRANSPORT_CONTEXT_FIELDS = {
    "ctx_transport",
    "ctx_transport.base_timeframe",
    "ctx_transport.bar_span_seconds",
    "ctx_transport.close_timestamp",
    "ctx_transport.ingestion_timestamp",
    "ctx_transport.publication_lag_ms",
    "ctx_transport.provider",
    "ctx_transport.origin",
    "ctx_transport.trigger_timeframe",
    "ctx_transport.decision_timeframe",
    "ctx_transport.trigger_mode",
    "ctx_transport.source_feature_timeframe",
    "ctx_transport.decision_bar_closed",
    "ctx_transport.projection_mode",
}


def build_available_feature_contract(
    features_node: Mapping[str, Any], engineered_node: Mapping[str, Any]
) -> set[str]:
    """Return indicator and flattened leaf fields implied by config."""
    available: set[str] = set()

    for config_key, cfg in features_node.items():
        available.add(config_key)

        indicator_type = None
        if isinstance(cfg, Mapping):
            indicator_type = cfg.get("type")
            if isinstance(indicator_type, str):
                available.add(indicator_type)

        canonical_name = indicator_type if isinstance(indicator_type, str) else config_key
        available.update(_INDICATOR_FIELD_ALIASES.get(canonical_name, set()))

    for key, cfg in engineered_node.items():
        if isinstance(cfg, Mapping) and cfg.get("enabled", True):
            available.add(f"eng_{key}")

    available.update(_TRANSPORT_CONTEXT_FIELDS)
    return available
