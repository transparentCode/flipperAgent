"""Explicit ownership and scope classification for foundation fields."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..domain.validation import ContractValidationError, require_string


class FieldClassification(str, Enum):
    INVARIANT = "invariant"
    DERIVED = "derived"
    GLOBAL = "global"
    TIMEFRAME = "timeframe"
    ASSET = "asset"
    ASSET_TIMEFRAME = "asset_timeframe"
    RUNTIME_NON_SEMANTIC = "runtime_non_semantic"
    RESEARCH_OVERRIDE = "research_override"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class FieldPolicy:
    name: str
    owner: str
    value_type: str
    classification: FieldClassification | str
    allowed_scopes: tuple[str, ...]
    semantic: bool
    required: bool
    yaml_participation: bool
    hash_participation: bool
    derivation_source: str | None
    evidence_status: str

    def __post_init__(self) -> None:
        name = require_string(self.name, field_name="field policy.name")
        owner = require_string(self.owner, field_name="field policy.owner")
        value_type = require_string(self.value_type, field_name="field policy.value_type")
        try:
            classification = FieldClassification(self.classification)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid field policy classification") from exc
        scopes = tuple(self.allowed_scopes)
        if not scopes or any(not isinstance(scope, str) or not scope for scope in scopes):
            raise ContractValidationError("field policy scopes must be non-empty strings")
        if self.hash_participation and not self.semantic:
            raise ContractValidationError("non-semantic field cannot participate in hash")
        if self.derivation_source is not None:
            require_string(self.derivation_source, field_name="field policy.derivation_source")
        require_string(self.evidence_status, field_name="field policy.evidence_status")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "owner", owner)
        object.__setattr__(self, "value_type", value_type)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(self, "allowed_scopes", scopes)


_POLICIES = (
    FieldPolicy("model.name", "configuration", "str", FieldClassification.INVARIANT, ("global",), True, True, True, True, None, "foundation_protocol"),
    FieldPolicy("model.version", "configuration", "str", FieldClassification.INVARIANT, ("global",), True, True, True, True, None, "foundation_protocol"),
    FieldPolicy("model.schema_version", "configuration", "int", FieldClassification.INVARIANT, ("global",), True, True, True, True, None, "foundation_protocol"),
)


_PROVIDER_POLICIES = (
    FieldPolicy(
        "provider.name",
        "confirmed_extrema_pair",
        "str",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "approved_provider_identity",
    ),
    FieldPolicy(
        "provider.version",
        "confirmed_extrema_pair",
        "str",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "approved_provider_identity",
    ),
    FieldPolicy(
        "provider.plateau_policy",
        "confirmed_extrema_pair",
        "enum",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "approved_causal_policy",
    ),
    FieldPolicy(
        "provider.history_horizon",
        "confirmed_extrema_pair",
        "enum",
        FieldClassification.UNRESOLVED,
        ("global", "timeframe", "asset", "asset_timeframe"),
        True,
        True,
        False,
        True,
        "phase_6a_scope_study",
        "fixture_only_unresolved_scope",
    ),
    FieldPolicy(
        "provider.lookback_duration_seconds",
        "confirmed_extrema_pair",
        "float_seconds",
        FieldClassification.UNRESOLVED,
        ("global", "timeframe", "asset", "asset_timeframe"),
        True,
        True,
        False,
        True,
        "phase_6a_scope_study",
        "fixture_only_unresolved_scope",
    ),
    FieldPolicy(
        "provider.left_confirmation_bars",
        "confirmed_extrema_pair",
        "int_bars",
        FieldClassification.UNRESOLVED,
        ("global", "timeframe", "asset", "asset_timeframe"),
        True,
        True,
        False,
        True,
        "phase_6a_scope_study",
        "fixture_only_unresolved_scope",
    ),
    FieldPolicy(
        "provider.right_confirmation_bars",
        "confirmed_extrema_pair",
        "int_bars",
        FieldClassification.UNRESOLVED,
        ("global", "timeframe", "asset", "asset_timeframe"),
        True,
        True,
        False,
        True,
        "phase_6a_scope_study",
        "fixture_only_unresolved_scope",
    ),
    FieldPolicy(
        "provider.min_extrema_per_role",
        "confirmed_extrema_pair",
        "int_count",
        FieldClassification.UNRESOLVED,
        ("global", "timeframe", "asset", "asset_timeframe"),
        True,
        True,
        False,
        True,
        "phase_6a_scope_study",
        "fixture_only_unresolved_scope",
    ),
    FieldPolicy(
        "provider.body_validation_policy",
        "confirmed_extrema_pair",
        "enum",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "exact_side_v1",
    ),
    FieldPolicy(
        "provider.pair_enumeration_order",
        "confirmed_extrema_pair",
        "enum",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "canonical_chronological_order",
    ),
    FieldPolicy(
        "provider.candidate_order_version",
        "confirmed_extrema_pair",
        "str",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "canonical_order_identity",
    ),
    FieldPolicy(
        "provider.structural_validation_version",
        "confirmed_extrema_pair",
        "str",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "exact_side_identity",
    ),
    FieldPolicy(
        "provider.max_hypotheses",
        "confirmed_extrema_pair",
        "int_count",
        FieldClassification.UNRESOLVED,
        ("global", "timeframe", "asset", "asset_timeframe"),
        True,
        True,
        False,
        True,
        "phase_6a_scope_study",
        "semantic_workload_fixture_only",
    ),
    FieldPolicy(
        "provider.max_output_candidates",
        "confirmed_extrema_pair",
        "int_count",
        FieldClassification.UNRESOLVED,
        ("global", "timeframe", "asset", "asset_timeframe"),
        True,
        True,
        False,
        True,
        "phase_6a_scope_study",
        "semantic_workload_fixture_only",
    ),
    FieldPolicy(
        "provider.provider_evidence_schema_version",
        "confirmed_extrema_pair",
        "str",
        FieldClassification.INVARIANT,
        ("global",),
        True,
        True,
        False,
        True,
        "phase_6a_provider_contract",
        "typed_evidence_schema_v1",
    ),
)


def field_policies() -> tuple[FieldPolicy, ...]:
    return _POLICIES


def provider_field_policies() -> tuple[FieldPolicy, ...]:
    """Return provider fields kept outside canonical YAML resolution."""

    return _PROVIDER_POLICIES


def all_field_policies() -> tuple[FieldPolicy, ...]:
    return (*_POLICIES, *_PROVIDER_POLICIES)


__all__ = [
    "FieldClassification",
    "FieldPolicy",
    "all_field_policies",
    "field_policies",
    "provider_field_policies",
]
