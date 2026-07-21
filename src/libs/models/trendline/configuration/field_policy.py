"""Machine-readable ownership and scope policy for every configuration field."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from ..domain.validation import ContractValidationError
from .contracts import TrendlineFamilyConfig


class ConfigClassification(str, Enum):
    INVARIANT = "invariant"
    GLOBAL = "global"
    TIMEFRAME = "timeframe"
    ASSET = "asset"
    ASSET_TIMEFRAME = "asset_timeframe"
    DERIVED = "derived"
    RUNTIME = "runtime_non_semantic"


class ConfigScope(str, Enum):
    GLOBAL = "global"
    TIMEFRAME = "timeframe"
    ASSET = "asset"
    ASSET_TIMEFRAME = "asset_timeframe"
    RESEARCH_OVERRIDE = "research_override"


@dataclass(frozen=True)
class ConfigFieldPolicy:
    field: str
    classification: ConfigClassification
    allowed_scopes: frozenset[ConfigScope]
    semantic: bool = True
    default_source: str = "configs/trendline_family.yaml"
    derivation_source: str | None = None
    hash_participation: str = "tracking"


_G = frozenset({ConfigScope.GLOBAL, ConfigScope.RESEARCH_OVERRIDE})
_T = frozenset({ConfigScope.GLOBAL, ConfigScope.TIMEFRAME, ConfigScope.ASSET_TIMEFRAME, ConfigScope.RESEARCH_OVERRIDE})
_A = frozenset({ConfigScope.GLOBAL, ConfigScope.ASSET, ConfigScope.ASSET_TIMEFRAME, ConfigScope.RESEARCH_OVERRIDE})
_AT = frozenset({ConfigScope.GLOBAL, ConfigScope.TIMEFRAME, ConfigScope.ASSET, ConfigScope.ASSET_TIMEFRAME, ConfigScope.RESEARCH_OVERRIDE})


def _policy(field: str, classification: ConfigClassification, scopes: frozenset[ConfigScope], *, hash_participation: str = "tracking") -> ConfigFieldPolicy:
    return ConfigFieldPolicy(field, classification, scopes, hash_participation=hash_participation)


FIELD_POLICIES = (
    _policy("model.enabled", ConfigClassification.GLOBAL, _G),
    _policy("model.model_version", ConfigClassification.GLOBAL, _G),
    _policy("candidate.pivot_provider", ConfigClassification.GLOBAL, _G),
    _policy("candidate.fitter", ConfigClassification.GLOBAL, _G),
    _policy("candidate.lookback_bars", ConfigClassification.TIMEFRAME, _AT),
    _policy("candidate.min_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("candidate.fractal_left_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("candidate.fractal_right_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("candidate.min_pivots_per_side", ConfigClassification.GLOBAL, _G),
    _policy("candidate.min_candidate_quality", ConfigClassification.GLOBAL, _AT),
    _policy("candidate.birth_quality_threshold", ConfigClassification.ASSET, _A),
    _policy("matching.normalization_atr_window", ConfigClassification.TIMEFRAME, _T),
    _policy("matching.max_distance_atr", ConfigClassification.ASSET_TIMEFRAME, _AT),
    _policy("matching.max_slope_delta_atr_per_hour", ConfigClassification.GLOBAL, _AT),
    _policy("matching.minimum_match_score", ConfigClassification.GLOBAL, _AT),
    _policy("matching.level_weight", ConfigClassification.GLOBAL, _G),
    _policy("matching.slope_weight", ConfigClassification.GLOBAL, _G),
    _policy("matching.anchor_weight", ConfigClassification.GLOBAL, _G),
    _policy("matching.role_weight", ConfigClassification.GLOBAL, _G),
    _policy("lifecycle.active_grace_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("lifecycle.dormant_after_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("lifecycle.expire_after_bars", ConfigClassification.TIMEFRAME, _AT),
    _policy("lifecycle.confidence_decay_per_unmatched_bar", ConfigClassification.GLOBAL, _G),
    _policy("lifecycle.reactivation_min_score", ConfigClassification.GLOBAL, _AT),
    _policy("lifecycle.max_active_families_per_role", ConfigClassification.GLOBAL, _T),
    _policy("interaction.atr_window", ConfigClassification.TIMEFRAME, _T),
    _policy("interaction.tolerance_atr", ConfigClassification.ASSET_TIMEFRAME, _AT),
    _policy("interaction.approaching_distance_atr", ConfigClassification.GLOBAL, _AT),
    _policy("interaction.minimum_zone_ticks", ConfigClassification.ASSET, _A),
    _policy("interaction.close_confirmation_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("events.pressure_min_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("events.rejection_recovery_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("events.retest_window_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("events.retest_confirmation_bars", ConfigClassification.TIMEFRAME, _T),
    _policy("rails.max_group_slope_delta_atr_per_hour", ConfigClassification.GLOBAL, _AT),
    _policy("rails.max_adjacent_gap_atr", ConfigClassification.GLOBAL, _AT),
    _policy("rails.max_corridor_width_atr", ConfigClassification.GLOBAL, _AT),
    _policy("rails.minimum_spacing_atr", ConfigClassification.GLOBAL, _AT),
    _policy("rails.representative_policy", ConfigClassification.GLOBAL, _G),
    _policy("mtf.enabled", ConfigClassification.GLOBAL, _G, hash_participation="mtf"),
    _policy("mtf.source_timeframes", ConfigClassification.GLOBAL, _T, hash_participation="mtf"),
    _policy("mtf.minimum_confluence_timeframes", ConfigClassification.GLOBAL, _G, hash_participation="mtf"),
    _policy("mtf.max_source_age_bars", ConfigClassification.TIMEFRAME, _T, hash_participation="mtf"),
    _policy("mtf.stale_include_age_bars", ConfigClassification.TIMEFRAME, _T, hash_participation="mtf"),
    _policy("mtf.max_level_distance_atr", ConfigClassification.GLOBAL, _AT, hash_participation="mtf"),
    _policy("mtf.max_corridor_separation_atr", ConfigClassification.GLOBAL, _AT, hash_participation="mtf"),
    _policy("mtf.max_slope_delta_atr_per_hour", ConfigClassification.GLOBAL, _AT, hash_participation="mtf"),
    _policy("mtf.intersection_horizon_bars", ConfigClassification.TIMEFRAME, _T, hash_participation="mtf"),
    _policy("mtf.normalization_policy", ConfigClassification.GLOBAL, _G, hash_participation="mtf"),
)

FIELD_POLICY_BY_NAME = {policy.field: policy for policy in FIELD_POLICIES}


def configuration_field_names() -> frozenset[str]:
    config = TrendlineFamilyConfig()
    return frozenset(
        f"{section.name}.{item.name}"
        for section in fields(config)
        for item in fields(getattr(config, section.name))
    )


def validate_field_policy_registry() -> None:
    names = tuple(policy.field for policy in FIELD_POLICIES)
    if len(names) != len(set(names)):
        raise ContractValidationError("configuration field policy contains duplicate ownership")
    missing = configuration_field_names() - set(names)
    unknown = set(names) - configuration_field_names()
    if missing or unknown:
        raise ContractValidationError(f"configuration field policy mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}")


def validate_field_scope(field: str, scope: ConfigScope) -> None:
    policy = FIELD_POLICY_BY_NAME.get(field)
    if policy is None:
        raise ContractValidationError(f"unknown configuration field policy: {field}")
    if scope not in policy.allowed_scopes:
        raise ContractValidationError(f"configuration field {field} is not allowed at {scope.value} scope")


validate_field_policy_registry()

__all__ = ["ConfigClassification", "ConfigFieldPolicy", "ConfigScope", "FIELD_POLICIES", "FIELD_POLICY_BY_NAME"]
