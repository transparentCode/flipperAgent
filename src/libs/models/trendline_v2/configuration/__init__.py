"""Strict Trendline V2 configuration boundary."""

from .contracts import ResolvedTrendlineV2Config
from .field_policy import (
    FieldClassification,
    FieldPolicy,
    all_field_policies,
    field_policies,
    provider_field_policies,
)
from .loader import load_trendline_v2_config
from .provider import (
    BodyValidationPolicy,
    ConfirmedExtremaPairConfig,
    HistoryHorizon,
    PairEnumerationOrder,
    PlateauPolicy,
    ProviderConfig,
)
from .resolver import resolve_trendline_v2_config

__all__ = [
    "FieldClassification",
    "FieldPolicy",
    "BodyValidationPolicy",
    "ConfirmedExtremaPairConfig",
    "HistoryHorizon",
    "PairEnumerationOrder",
    "PlateauPolicy",
    "ProviderConfig",
    "ResolvedTrendlineV2Config",
    "all_field_policies",
    "field_policies",
    "load_trendline_v2_config",
    "provider_field_policies",
    "resolve_trendline_v2_config",
]
