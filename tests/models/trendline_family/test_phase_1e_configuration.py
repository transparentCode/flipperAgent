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
    legacy_v1_profile,
)
from libs.models.trendline.configuration.contracts import CandidateConfig
from libs.models.trendline.configuration.resolver import TrendlineConfigPatch as CanonicalPatch
from libs.models.trendline_family.config import TrendlineFamilyConfig as FamilyCompatTrendlineConfig
from libs.models.trendline_family.config_resolver import TrendlineConfigPatch as FamilyCompatPatch
from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
    TrendlineFamilyFeatureProducer as CompatShadowProducer,
)
from libs.integrations.trendline_regime_v2.shadow import (
    TrendlineFamilyFeatureProducer as NeutralShadowProducer,
)


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


def test_cross_model_shadow_adapter_is_neutral_implementation_with_compatibility_identity() -> None:
    assert CompatShadowProducer is NeutralShadowProducer
    source = (Path(__file__).parents[3] / "src" / "libs" / "models" / "regime_v2" / "adapters" / "trendline_family_feature_producer.py").read_text(
        encoding="utf-8"
    )
    assert "libs.models.trendline" not in source
    assert "libs.integrations.trendline_regime_v2.shadow" in source


def test_config_validation_remains_strict_after_profile_resolution() -> None:
    with pytest.raises(ContractValidationError, match="integer"):
        _resolver({"version": 1, "defaults": {"candidate": {"lookback_bars": True}}}).resolve(
            asset="BTCUSDT", timeframe="4h"
        )
    with pytest.raises(ContractValidationError, match="explicit"):
        TrendlineConfigPatch({"candidate": {"lookback_bars": None}})
    with pytest.raises(ContractValidationError, match="numeric"):
        CandidateConfig(min_candidate_quality="0.2")
