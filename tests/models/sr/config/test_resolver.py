from __future__ import annotations

from dataclasses import MISSING, fields as dataclass_fields
import inspect

import pytest

from libs.models.sr import (
    AssociationConfig,
    ContractValidationError,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SRConfig,
    SRConfigResolver,
)


def _complete_defaults() -> dict:
    return {
        "detection": {
            "pivot_span_bars": 5,
            "zone_half_width_atr": 0.5,
        },
        "association": {
            "merge_distance_atr": 0.75,
        },
        "lifecycle": {
            "touch_tolerance_atr": 0.25,
            "break_buffer_atr": 0.1,
            "break_confirm_closes": 2,
            "max_age_bars": 50,
        },
        "runtime": {
            "max_active_zones": 8,
        },
    }


def _resolver() -> SRConfigResolver:
    return SRConfigResolver({"version": "1", "defaults": _complete_defaults()})


_CONFIG_TYPES = (
    ("detection", DetectionConfig),
    ("association", AssociationConfig),
    ("lifecycle", LifecycleConfig),
    ("runtime", RuntimeConfig),
)


def test_approved_parameter_surface_is_exactly_eight() -> None:
    paths = {
        f"{section}.{field.name}"
        for section, config_type in _CONFIG_TYPES
        for field in dataclass_fields(config_type)
    }
    assert paths == {
        "detection.pivot_span_bars",
        "detection.zone_half_width_atr",
        "association.merge_distance_atr",
        "lifecycle.touch_tolerance_atr",
        "lifecycle.break_buffer_atr",
        "lifecycle.break_confirm_closes",
        "lifecycle.max_age_bars",
        "runtime.max_active_zones",
    }
    assert len(paths) == 8


@pytest.mark.parametrize("config_type", [config_type for _, config_type in _CONFIG_TYPES])
def test_parameter_dataclass_fields_have_no_defaults(config_type: type) -> None:
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in dataclass_fields(config_type)
    )


def test_defaults_are_required() -> None:
    with pytest.raises(ContractValidationError):
        SRConfigResolver({"version": "1"})


def test_defaults_must_be_complete() -> None:
    incomplete = _complete_defaults()
    incomplete["detection"].pop("pivot_span_bars")
    with pytest.raises(ContractValidationError):
        SRConfigResolver({"version": "1", "defaults": incomplete})


def test_missing_global_default_cannot_fall_back_to_an_override() -> None:
    incomplete = _complete_defaults()
    incomplete["detection"].pop("zone_half_width_atr")
    raw = {
        "version": "1",
        "defaults": incomplete,
        "timeframes": {
            "1h": {"detection": {"zone_half_width_atr": 0.5}},
        },
    }
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_unknown_root_key_rejected() -> None:
    with pytest.raises(ContractValidationError):
        SRConfigResolver(
            {
                "version": "1",
                "defaults": _complete_defaults(),
                "unknown": {},
            }
        )


def test_unknown_section_rejected() -> None:
    raw = {"version": "1", "defaults": _complete_defaults()}
    raw["defaults"]["unknown"] = {}
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_unknown_field_rejected() -> None:
    raw = {"version": "1", "defaults": _complete_defaults()}
    raw["defaults"]["detection"]["unknown_field"] = 1
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("detection", "pivot_span_bars", True),
        ("detection", "zone_half_width_atr", float("inf")),
        ("association", "merge_distance_atr", float("nan")),
        ("lifecycle", "break_confirm_closes", False),
    ],
)
def test_non_finite_and_boolean_parameter_values_fail_closed(
    section: str, field: str, value: object
) -> None:
    defaults = _complete_defaults()
    defaults[section][field] = value
    with pytest.raises(ContractValidationError):
        SRConfigResolver({"version": "1", "defaults": defaults})


def test_empty_timeframe_override_rejected() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {"1h": {}},
    }
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_empty_asset_block_rejected() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "assets": {"BTCUSDT": {}},
    }
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_empty_asset_key_rejected() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "assets": {"": {"timeframes": {"1h": {"detection": {"pivot_span_bars": 10}}}}},
    }
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_empty_timeframe_key_rejected() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {"": {"detection": {"pivot_span_bars": 10}}},
    }
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_whitespace_identifiers_rejected() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {"   ": {"detection": {"pivot_span_bars": 10}}},
    }
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)

    with pytest.raises(ContractValidationError):
        SRConfigResolver({"version": "1", "defaults": _complete_defaults()}).resolve(
            asset="   ", timeframe="1h"
        )


def test_unsupported_config_version_rejected() -> None:
    with pytest.raises(ContractValidationError):
        SRConfigResolver({"version": "2", "defaults": _complete_defaults()})


@pytest.mark.parametrize(
    "malformed",
    [
        {"timeframes": []},
        {"assets": []},
        {"timeframes": {"1h": []}},
        {"assets": {"BTCUSDT": {"timeframes": []}}},
        {"assets": {"BTCUSDT": {"timeframes": None}}},
    ],
)
def test_malformed_override_containers_raise_contract_error(malformed: dict) -> None:
    raw = {"version": "1", "defaults": _complete_defaults()}
    raw.update(malformed)
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_override_values_are_validated_at_their_source_path() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {"1h": {"detection": {"pivot_span_bars": 0}}},
    }
    with pytest.raises(ContractValidationError, match=r"timeframes\.1h"):
        SRConfigResolver(raw)


def test_resolution_precedence() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {
            "1h": {
                "detection": {"pivot_span_bars": 10},
            }
        },
        "assets": {
            "BTCUSDT": {
                "timeframes": {
                    "1h": {
                        "lifecycle": {"max_age_bars": 100},
                    }
                },
            }
        },
    }
    resolver = SRConfigResolver(raw)
    resolved = resolver.resolve(asset="BTCUSDT", timeframe="1h")

    assert resolved.detection.pivot_span_bars == 10
    assert resolved.lifecycle.max_age_bars == 100
    assert resolved.runtime.max_active_zones == 8
    assert not hasattr(resolved.lifecycle, "max_active_zones")

    provenance = dict(resolved.field_provenance)
    assert provenance["detection.pivot_span_bars"] == "timeframe:1h"
    assert provenance["lifecycle.max_age_bars"] == "asset_timeframe:BTCUSDT:1h"
    assert provenance["association.merge_distance_atr"] == "defaults"


def test_four_layer_resolution_precedence_and_provenance() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {
            "1h": {
                "detection": {"pivot_span_bars": 10},
                "lifecycle": {"max_age_bars": 80},
            }
        },
        "assets": {
            "BTCUSDT": {
                "defaults": {
                    "association": {"merge_distance_atr": 0.4},
                    "lifecycle": {"max_age_bars": 90},
                },
                "timeframes": {
                    "1h": {
                        "detection": {"pivot_span_bars": 7},
                    }
                },
            }
        },
    }
    resolved = SRConfigResolver(raw).resolve(asset="BTCUSDT", timeframe="1h")

    assert resolved.detection.pivot_span_bars == 7
    assert resolved.lifecycle.max_age_bars == 90
    assert resolved.association.merge_distance_atr == 0.4
    provenance = dict(resolved.field_provenance)
    assert provenance["detection.pivot_span_bars"] == "asset_timeframe:BTCUSDT:1h"
    assert provenance["lifecycle.max_age_bars"] == "asset:BTCUSDT"
    assert provenance["association.merge_distance_atr"] == "asset:BTCUSDT"


def test_asset_wide_defaults_apply_without_an_exact_asset_timeframe_override() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "assets": {
            "BTCUSDT": {
                "defaults": {
                    "runtime": {"max_active_zones": 12},
                },
            }
        },
    }
    resolver = SRConfigResolver(raw)

    resolved = resolver.resolve(asset="BTCUSDT", timeframe="4h")
    unrelated = resolver.resolve(asset="ETHUSDT", timeframe="4h")

    assert resolved.runtime.max_active_zones == 12
    assert dict(resolved.field_provenance)["runtime.max_active_zones"] == "asset:BTCUSDT"
    assert unrelated.runtime.max_active_zones == 8
    assert dict(unrelated.field_provenance)["runtime.max_active_zones"] == "defaults"


@pytest.mark.parametrize(
    "asset_defaults",
    [
        {},
        {"unknown": {}},
        {"detection": {}},
        {"detection": {"pivot_span_bars": 0}},
    ],
)
def test_asset_wide_defaults_are_strictly_validated(asset_defaults: dict) -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "assets": {"BTCUSDT": {"defaults": asset_defaults}},
    }
    with pytest.raises(ContractValidationError):
        SRConfigResolver(raw)


def test_runtime_timeframe_override_precedence_and_provenance() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {
            "1h": {"runtime": {"max_active_zones": 12}},
        },
    }
    resolver = SRConfigResolver(raw)

    timeframe_resolved = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    default_resolved = resolver.resolve(asset="BTCUSDT", timeframe="4h")

    assert timeframe_resolved.runtime.max_active_zones == 12
    assert (
        dict(timeframe_resolved.field_provenance)["runtime.max_active_zones"]
        == "timeframe:1h"
    )
    assert default_resolved.runtime.max_active_zones == 8
    assert (
        dict(default_resolved.field_provenance)["runtime.max_active_zones"]
        == "defaults"
    )


def test_runtime_asset_timeframe_override_precedence_and_provenance() -> None:
    raw = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {
            "1h": {"runtime": {"max_active_zones": 12}},
        },
        "assets": {
            "BTCUSDT": {
                "timeframes": {
                    "1h": {"runtime": {"max_active_zones": 16}},
                },
            }
        },
    }
    resolver = SRConfigResolver(raw)

    exact_resolved = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    timeframe_resolved = resolver.resolve(asset="ETHUSDT", timeframe="1h")

    assert exact_resolved.runtime.max_active_zones == 16
    assert (
        dict(exact_resolved.field_provenance)["runtime.max_active_zones"]
        == "asset_timeframe:BTCUSDT:1h"
    )
    assert timeframe_resolved.runtime.max_active_zones == 12
    assert (
        dict(timeframe_resolved.field_provenance)["runtime.max_active_zones"]
        == "timeframe:1h"
    )


def test_resolve_has_no_call_time_runtime_override_parameter() -> None:
    parameters = inspect.signature(SRConfigResolver.resolve).parameters
    assert "runtime_override" not in parameters


def test_unrelated_asset_timeframe_uses_defaults() -> None:
    resolver = _resolver()
    resolved = resolver.resolve(asset="ETHUSDT", timeframe="4h")
    assert resolved.detection.pivot_span_bars == 5
    assert dict(resolved.field_provenance)["detection.pivot_span_bars"] == "defaults"


def test_resolved_config_hash_is_sha256() -> None:
    resolver = _resolver()
    resolved = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    assert len(resolved.resolved_config_hash) == 64
    assert int(resolved.resolved_config_hash, 16) >= 0


def test_hash_changes_with_override() -> None:
    base = {"version": "1", "defaults": _complete_defaults()}
    overridden = {
        "version": "1",
        "defaults": _complete_defaults(),
        "timeframes": {
            "1h": {"detection": {"pivot_span_bars": 99}}
        },
    }
    r_base = SRConfigResolver(base).resolve(asset="BTCUSDT", timeframe="1h")
    r_over = SRConfigResolver(overridden).resolve(asset="BTCUSDT", timeframe="1h")
    assert r_base.resolved_config_hash != r_over.resolved_config_hash


def test_config_hash_and_provenance_are_independent_of_mapping_insertion_order() -> None:
    defaults = _complete_defaults()
    ordered = {
        "version": "1",
        "defaults": defaults,
        "timeframes": {"1h": {"detection": {"pivot_span_bars": 7}}},
        "assets": {
            "BTCUSDT": {
                "defaults": {"association": {"merge_distance_atr": 0.4}},
                "timeframes": {"1h": {"runtime": {"max_active_zones": 10}}},
            }
        },
    }
    reordered = {
        "assets": {
            "BTCUSDT": {
                "timeframes": {"1h": {"runtime": {"max_active_zones": 10}}},
                "defaults": {"association": {"merge_distance_atr": 0.4}},
            }
        },
        "timeframes": {"1h": {"detection": {"pivot_span_bars": 7}}},
        "defaults": {
            "runtime": defaults["runtime"],
            "lifecycle": defaults["lifecycle"],
            "association": defaults["association"],
            "detection": defaults["detection"],
        },
        "version": "1",
    }

    first = SRConfigResolver(ordered).resolve(asset="BTCUSDT", timeframe="1h")
    second = SRConfigResolver(reordered).resolve(asset="BTCUSDT", timeframe="1h")

    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("detection", "zone_half_width_atr"),
        ("association", "merge_distance_atr"),
        ("lifecycle", "touch_tolerance_atr"),
        ("lifecycle", "break_buffer_atr"),
    ],
)
def test_signed_zero_config_values_have_one_hash(section: str, field: str) -> None:
    positive_defaults = _complete_defaults()
    negative_defaults = _complete_defaults()
    positive_defaults[section][field] = 0.0
    negative_defaults[section][field] = -0.0

    positive = SRConfigResolver(
        {"version": "1", "defaults": positive_defaults}
    ).resolve(asset="BTCUSDT", timeframe="1h")
    negative = SRConfigResolver(
        {"version": "1", "defaults": negative_defaults}
    ).resolve(asset="BTCUSDT", timeframe="1h")

    assert getattr(getattr(negative, section), field) == 0.0
    assert positive.resolved_config_hash == negative.resolved_config_hash


def test_forged_resolved_config_hash_detected() -> None:
    resolver = _resolver()
    resolved = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    with pytest.raises(ContractValidationError):
        ResolvedSRConfig(
            version=resolved.version,
            asset=resolved.asset,
            timeframe=resolved.timeframe,
            detection=resolved.detection,
            association=resolved.association,
            lifecycle=resolved.lifecycle,
            runtime=resolved.runtime,
            field_provenance=resolved.field_provenance,
            resolved_config_hash="0" * 64,
        )


def test_resolved_config_requires_complete_provenance() -> None:
    resolved = _resolver().resolve(asset="BTCUSDT", timeframe="1h")
    with pytest.raises(ContractValidationError):
        ResolvedSRConfig.create(
            version=resolved.version,
            asset=resolved.asset,
            timeframe=resolved.timeframe,
            detection=resolved.detection,
            association=resolved.association,
            lifecycle=resolved.lifecycle,
            runtime=resolved.runtime,
            field_provenance={},
        )

    incomplete = dict(resolved.field_provenance)
    incomplete.pop("runtime.max_active_zones")
    with pytest.raises(ContractValidationError):
        ResolvedSRConfig.create(
            version=resolved.version,
            asset=resolved.asset,
            timeframe=resolved.timeframe,
            detection=resolved.detection,
            association=resolved.association,
            lifecycle=resolved.lifecycle,
            runtime=resolved.runtime,
            field_provenance=incomplete,
        )


def test_resolved_config_create_validates_typed_groups() -> None:
    resolved = _resolver().resolve(asset="BTCUSDT", timeframe="1h")
    with pytest.raises(ContractValidationError):
        ResolvedSRConfig.create(
            version=resolved.version,
            asset=resolved.asset,
            timeframe=resolved.timeframe,
            detection=object(),  # type: ignore[arg-type]
            association=resolved.association,
            lifecycle=resolved.lifecycle,
            runtime=resolved.runtime,
            field_provenance=dict(resolved.field_provenance),
        )


def test_sr_config_wrapper_validates() -> None:
    with pytest.raises(ContractValidationError):
        SRConfig(version="1", defaults={"detection": {}})


def test_resolved_config_to_dict_roundtrip_shape() -> None:
    resolver = _resolver()
    resolved = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    d = resolved.to_dict()
    assert d["version"] == "1"
    assert d["asset"] == "BTCUSDT"
    assert d["timeframe"] == "1h"
    assert "detection" in d
    assert "lifecycle" in d
    assert d["runtime"]["max_active_zones"] == 8
    assert len(d["field_provenance"]) == 8
    assert d["resolved_config_hash"] == resolved.resolved_config_hash


def test_deep_freeze_prevents_source_mutation() -> None:
    raw = {"version": "1", "defaults": _complete_defaults()}
    resolver = SRConfigResolver(raw)
    # The resolver stores a deep-frozen copy; mutating the original input must
    # not affect the resolver's internal state.
    raw["defaults"]["detection"]["pivot_span_bars"] = 999
    resolved = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    assert resolved.detection.pivot_span_bars == 5


def test_raw_config_is_recursively_immutable() -> None:
    resolver = _resolver()
    before = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    with pytest.raises(TypeError):
        resolver.raw_config["defaults"] = {}
    with pytest.raises(TypeError):
        resolver.raw_config["defaults"]["detection"]["pivot_span_bars"] = 99
    after = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    assert after.detection.pivot_span_bars == 5
    assert after.resolved_config_hash == before.resolved_config_hash


def test_from_sr_config_preserves_immutable_source() -> None:
    config = SRConfig(version="1", defaults=_complete_defaults())
    resolver = SRConfigResolver.from_sr_config(config)
    with pytest.raises(TypeError):
        resolver.raw_config["defaults"]["runtime"]["max_active_zones"] = 99
    assert resolver.resolve(asset="BTCUSDT", timeframe="1h").runtime == RuntimeConfig(
        max_active_zones=8
    )


def test_legacy_models_imports_are_canonical_reexports() -> None:
    from libs.models.sr.config.models import (  # noqa: PLC0415
        DetectionConfig as LegacyDetectionConfig,
    )
    from libs.models.sr.config.resolved import (  # noqa: PLC0415
        ResolvedSRConfig as CanonicalResolvedSRConfig,
    )
    from libs.models.sr.config.schema import SRConfig as CanonicalSRConfig  # noqa: PLC0415
    from libs.models.sr.config.sections import (  # noqa: PLC0415
        DetectionConfig as CanonicalDetectionConfig,
    )

    assert LegacyDetectionConfig is CanonicalDetectionConfig
    assert ResolvedSRConfig is CanonicalResolvedSRConfig
    assert SRConfig is CanonicalSRConfig
