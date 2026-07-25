from __future__ import annotations

import ast
from dataclasses import asdict
from pathlib import Path

import pytest

from libs.models.trendline.config import ResolvedTrendlineFamilyConfig as CompatResolvedConfig
from libs.models.trendline.config import TrendlineFamilyConfig as CompatTrendlineConfig
from libs.models.trendline.configuration import (
    UNSET,
    ResolvedTrendlineFamilyConfig,
    TrendlineConfigPatch,
    TrendlineConfigScope,
    TrendlineFamilyConfig,
    TrendlineFamilyConfigResolver,
    configuration_manifest,
    derive_configuration,
    legacy_v1_profile,
)
from libs.models.trendline.configuration.field_policy import FIELD_POLICIES, configuration_field_names
from libs.models.trendline.configuration.loader import load_trendline_family_config as canonical_loader
from libs.integrations.trendline_configuration.loader import load_trendline_family_config as integration_loader
from libs.models.trendline.configuration.contracts import CandidateConfig
from libs.models.trendline.configuration.resolver import TrendlineConfigPatch as CanonicalPatch
from libs.models.trendline_family.config import TrendlineFamilyConfig as FamilyCompatTrendlineConfig
from libs.models.trendline_family.config_resolver import TrendlineConfigPatch as FamilyCompatPatch
from libs.models.trendline_family.contracts import ContractValidationError
_TRENDLINE_ROOT = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline"
_FORBIDDEN_MODEL_IMPORTS = {
    "libs.models.regime",
    "libs.models.regime_v2",
    "libs.models.sr",
    "libs.models.market_context",
    "libs.models.signal",
}


def _resolver(raw: dict) -> TrendlineFamilyConfigResolver:
    return TrendlineFamilyConfigResolver(raw)


def _imports_under(root: Path) -> set[str]:
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        if path.relative_to(root).parts[:1] == ("optimization",) and path.name == "ablation.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_config_contract_identity_and_serialized_shape_are_preserved() -> None:
    assert CompatTrendlineConfig is TrendlineFamilyConfig
    assert FamilyCompatTrendlineConfig is TrendlineFamilyConfig
    assert CompatResolvedConfig is ResolvedTrendlineFamilyConfig
    assert FamilyCompatPatch is CanonicalPatch is TrendlineConfigPatch
    assert TrendlineFamilyConfig().to_dict() == {
        name: asdict(getattr(TrendlineFamilyConfig(), name))
        for name in (
            "model",
            "candidate",
            "matching",
            "lifecycle",
            "interaction",
            "events",
            "rails",
            "mtf",
            "ranking",
            "repository",
            "runtime",
        )
    }


def test_legacy_v1_profile_reproduces_implicit_defaults_without_id_drift() -> None:
    resolved = _resolver(legacy_v1_profile()).resolve(asset="BTCUSDT", timeframe="4h")
    implicit = TrendlineFamilyConfig()

    assert resolved.to_dict() == ResolvedTrendlineFamilyConfig.create(
        asset="BTCUSDT",
        timeframe="4h",
        config_version="1",
        config=implicit,
        field_provenance=resolved.field_provenance,
    ).to_dict()
    assert resolved.profile_id == "legacy_v1"
    assert resolved.profile_version == "1"
    assert resolved.candidate == implicit.candidate
    assert resolved.resolved_config_hash == ResolvedTrendlineFamilyConfig.create(
        asset="BTCUSDT",
        timeframe="4h",
        config_version="1",
        config=implicit,
        field_provenance=resolved.field_provenance,
    ).resolved_config_hash


def test_existing_canonical_yaml_resolves_as_legacy_v1_without_profile_or_hash_drift() -> None:
    resolved = TrendlineFamilyConfigResolver.from_path(
        Path("configs/trendline_family.yaml")
    ).resolve(asset="BTCUSDT", timeframe="4h")

    assert resolved.profile_id == "legacy_v1"
    assert resolved.profile_version == "1"
    assert resolved.candidate.lookback_bars == 180
    assert resolved.candidate.birth_quality_threshold == 0.50
    assert resolved.matching.max_distance_atr == 0.65
    assert resolved.interaction.tolerance_atr == 0.22
    assert resolved.lifecycle.expire_after_bars == 60
    assert resolved.events.retest_window_bars == 6
    assert resolved.resolved_config_hash == "da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f"
    assert resolved.mtf_config_hash == "d9cae516fb96eb3449c8ad684453789e0fed825bda57d0913c111b0cd6b8aa7b"


def test_field_policy_is_complete_unique_and_enforced() -> None:
    policy_names = tuple(policy.field for policy in FIELD_POLICIES)
    assert len(policy_names) == len(set(policy_names))
    assert frozenset(policy_names) == configuration_field_names()
    with pytest.raises(ContractValidationError, match="not allowed at timeframe scope"):
        _resolver({"version": 1, "timeframes": {"4h": {"candidate": {"pivot_provider": "fractal"}}}})


def test_canonical_loader_identity_completion_and_derived_values() -> None:
    assert integration_loader is canonical_loader
    raw = canonical_loader("configs/trendline_family.yaml")
    TrendlineFamilyConfigResolver(raw, require_complete=True)
    incomplete = dict(raw)
    incomplete["defaults"] = dict(raw["defaults"])
    incomplete["defaults"]["candidate"] = dict(raw["defaults"]["candidate"])
    incomplete["defaults"]["candidate"].pop("lookback_bars")
    with pytest.raises(ContractValidationError, match="semantic profile is incomplete"):
        TrendlineFamilyConfigResolver(incomplete, require_complete=True)
    resolved = TrendlineFamilyConfigResolver(raw, require_complete=True).resolve(asset="BTCUSDT", timeframe="4h")
    derived = derive_configuration(resolved)
    assert derived.timeframe_duration_seconds == 14_400
    assert derived.minimum_warmup_bars == 40
    assert derived.maximum_historical_horizon_bars == 180


def test_scoped_resolution_merges_non_overlapping_equal_specificity_fields() -> None:
    resolved = _resolver(
        {
            "version": 1,
            "defaults": {"candidate": {"lookback_bars": 200}},
            "timeframes": {"4h": {"candidate": {"lookback_bars": 220}}},
            "assets": {"BTCUSDT": {"defaults": {"lifecycle": {"expire_after_bars": 60}}}},
        }
    ).resolve(asset="BTCUSDT", timeframe="4h")

    assert resolved.candidate.lookback_bars == 220
    assert resolved.lifecycle.expire_after_bars == 60
    assert resolved.field_provenance["candidate.lookback_bars"] == "timeframe:4h"
    assert resolved.field_provenance["lifecycle.expire_after_bars"] == "asset:BTCUSDT"


def test_equal_specificity_conflict_requires_exact_pair_resolution() -> None:
    raw = {
        "version": 1,
        "timeframes": {"4h": {"candidate": {"lookback_bars": 220}}},
        "assets": {"BTCUSDT": {"defaults": {"candidate": {"lookback_bars": 240}}}},
    }
    with pytest.raises(ContractValidationError, match="equal-specificity"):
        _resolver(raw).resolve(asset="BTCUSDT", timeframe="4h")

    raw["assets"]["BTCUSDT"]["timeframes"] = {"4h": {"candidate": {"lookback_bars": 260}}}
    resolved = _resolver(raw).resolve(asset="BTCUSDT", timeframe="4h")
    assert resolved.candidate.lookback_bars == 260
    assert resolved.field_provenance["candidate.lookback_bars"] == "asset_timeframe:BTCUSDT:4h"


def test_invocation_patch_is_highest_precedence_and_immutable() -> None:
    patch_values = {"candidate": {"lookback_bars": 280}}
    patch = TrendlineConfigPatch(patch_values)
    patch_values["candidate"]["lookback_bars"] = 999
    resolved = _resolver(
        {"version": 1, "timeframes": {"4h": {"candidate": {"lookback_bars": 220}}}}
    ).resolve(asset="BTCUSDT", timeframe="4h", invocation_override=patch)

    assert resolved.candidate.lookback_bars == 280
    assert resolved.field_provenance["candidate.lookback_bars"] == "invocation_override"
    assert patch.values["candidate"]["lookback_bars"] == 280
    with pytest.raises(TypeError):
        patch.values["candidate"]["lookback_bars"] = 1  # type: ignore[index]
    with pytest.raises(ContractValidationError, match="cannot both"):
        _resolver({"version": 1}).resolve(
            asset="BTCUSDT",
            timeframe="4h",
            runtime_override={"candidate": {"lookback_bars": 220}},
            invocation_override=patch,
        )
    assert repr(UNSET) == "UNSET"


def test_scope_validation_unknown_scope_fallback_and_complete_provenance() -> None:
    assert TrendlineConfigScope() == TrendlineConfigScope(asset=None, timeframe=None)
    with pytest.raises(ContractValidationError, match="scope asset"):
        TrendlineConfigScope(asset="")
    resolved = _resolver({"version": 1, "defaults": {"candidate": {"lookback_bars": 200}}}).resolve(
        asset="UNKNOWNUSDT", timeframe="17m"
    )
    assert resolved.candidate.lookback_bars == 200
    assert resolved.field_provenance["candidate.lookback_bars"] == "yaml_defaults"
    with pytest.raises(ContractValidationError, match="unknown config"):
        _resolver({"version": 1, "unknown": {}})


def test_provenance_fingerprint_is_deterministic_and_separate_from_domain_identity() -> None:
    first = _resolver({"profile_id": "legacy_v1", "profile_version": "1", "version": 1}).resolve(
        asset="BTCUSDT", timeframe="4h"
    )
    second = _resolver({"version": 1, "profile_version": "1", "profile_id": "legacy_v1"}).resolve(
        asset="BTCUSDT", timeframe="4h"
    )
    alternate = ResolvedTrendlineFamilyConfig.create(
        asset="BTCUSDT",
        timeframe="4h",
        config_version="1",
        config=TrendlineFamilyConfig(),
        field_provenance=first.field_provenance,
        profile_id="alternate",
        profile_version="1",
    )

    assert first.configuration_fingerprint == second.configuration_fingerprint
    assert first.resolved_config_hash == alternate.resolved_config_hash
    assert first.configuration_fingerprint != alternate.configuration_fingerprint
    manifest = configuration_manifest(first)
    assert manifest["configuration_fingerprint"] == first.configuration_fingerprint
    assert manifest["resolved_values"] == first.to_dict()
    assert "regime" not in manifest


def test_core_model_has_no_direct_other_model_imports_or_cross_model_contract_fields() -> None:
    imports = _imports_under(_TRENDLINE_ROOT)
    assert not {value for value in imports if value.startswith(tuple(_FORBIDDEN_MODEL_IMPORTS))}
    for contract in (TrendlineFamilyConfig, ResolvedTrendlineFamilyConfig):
        fields = set(contract.__dataclass_fields__)
        assert not {field for field in fields if field.startswith(("regime", "sr_", "market_context"))}


def test_config_validation_remains_strict_after_profile_resolution() -> None:
    with pytest.raises(ContractValidationError, match="integer"):
        _resolver({"version": 1, "defaults": {"candidate": {"lookback_bars": True}}}).resolve(
            asset="BTCUSDT", timeframe="4h"
        )
    with pytest.raises(ContractValidationError, match="explicit"):
        TrendlineConfigPatch({"candidate": {"lookback_bars": None}})
    with pytest.raises(ContractValidationError, match="numeric"):
        CandidateConfig(min_candidate_quality="0.2")
