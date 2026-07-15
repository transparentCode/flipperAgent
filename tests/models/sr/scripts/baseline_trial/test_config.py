from __future__ import annotations

from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from libs.models.sr import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    RuntimeConfig,
)
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.baseline_trial.config import (
    load_and_resolve_input_config,
    load_resolved_sr_config,
    load_trial_config,
    parse_trial_config,
    resolve_input_config,
)
from libs.models.sr.scripts.baseline_trial.contracts import (
    ATRProvenance,
    BundleMember,
    EvidenceManifest,
    ResolvedInputConfig,
    SourceBar,
    TrialResult,
    TrialSpec,
    ValidatedDataset,
    ViewerConfig,
)
from libs.models.sr.adapters.yaml_config import load_sr_config


_ROOT = Path(__file__).parents[5]
_INPUT_PATH = _ROOT / "configs" / "sr_inputs.yaml"
_TRIAL_PATH = _ROOT / "configs" / "sr_trials" / "taousdt_1d_baseline.yaml"


def test_real_input_and_trial_yaml_load_with_frozen_baseline_values() -> None:
    trial = load_trial_config(_TRIAL_PATH)
    resolved = load_and_resolve_input_config(
        _INPUT_PATH,
        asset=trial.symbol,
        timeframe=trial.timeframe,
    )

    assert trial.symbol == "TAOUSDT"
    assert trial.timeframe == "1d"
    assert trial.adapter_limit == 1500
    assert resolved.atr_method == "wilder_rma"
    assert resolved.atr_period == 14
    assert resolved.atr_seed == "sma"
    assert resolved.field_provenance == (
        ("atr.method", "defaults"),
        ("atr.period", "defaults"),
        ("atr.seed", "defaults"),
    )


def test_input_resolution_uses_only_three_precedence_layers() -> None:
    raw = {
        "version": "1",
        "defaults": {"atr": {"method": "wilder_rma", "period": 14, "seed": "sma"}},
        "timeframes": {"1d": {"atr": {"period": 20}}},
        "assets": {
            "TAOUSDT": {
                "timeframes": {
                    "1d": {"atr": {"method": "wilder_rma", "period": 30}},
                },
            },
        },
    }

    resolved = resolve_input_config(raw, asset="TAOUSDT", timeframe="1d")

    assert (resolved.atr_method, resolved.atr_period, resolved.atr_seed) == (
        "wilder_rma",
        30,
        "sma",
    )
    assert resolved.field_provenance == (
        ("atr.method", "asset_timeframe:TAOUSDT:1d"),
        ("atr.period", "asset_timeframe:TAOUSDT:1d"),
        ("atr.seed", "defaults"),
    )


def test_input_resolution_rejects_asset_wide_and_call_time_overrides() -> None:
    asset_wide = {
        "version": "1",
        "defaults": {"atr": {"method": "wilder_rma", "period": 14, "seed": "sma"}},
        "timeframes": {},
        "assets": {"TAOUSDT": {"atr": {"period": 20}}},
    }
    with pytest.raises(ContractValidationError):
        resolve_input_config(asset_wide, asset="TAOUSDT", timeframe="1d")

    with pytest.raises(TypeError):
        resolve_input_config({}, asset="TAOUSDT", timeframe="1d", runtime_override={})


def test_missing_input_values_do_not_fall_back_to_python_defaults() -> None:
    raw = {
        "version": "1",
        "defaults": {"atr": {"method": "wilder_rma", "seed": "sma"}},
        "timeframes": {},
        "assets": {},
    }
    with pytest.raises(ContractValidationError, match="period"):
        resolve_input_config(raw, asset="TAOUSDT", timeframe="1d")


@pytest.mark.parametrize(
    "yaml_text",
    (
        "version: '1'\ndefaults:\n  atr: {method: wilder_rma, period: 14, seed: sma}\ntimeframes: {}\nassets: {}\n",
        "version: '1'\ndefaults:\n  atr:\n    method: wilder_rma\n    method: wilder_rma\n    period: 14\n    seed: sma\ntimeframes: {}\nassets: {}\n",
        "version: '1'\ndefaults:\n  atr: {method: wilder_rma, period: 14, seed: sma}\ntimeframes:\n  1d: {atr: {period: 20}}\n  1d: {atr: {period: 21}}\nassets: {}\n",
    ),
)
def test_input_yaml_duplicate_keys_fail_closed(tmp_path: Path, yaml_text: str) -> None:
    path = tmp_path / "inputs.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    if "method: wilder_rma\n    method" in yaml_text or "  1d:" in yaml_text and yaml_text.count("  1d:") > 1:
        with pytest.raises(ContractValidationError):
            load_sr_config(path)
    else:
        assert load_sr_config(path)


@pytest.mark.parametrize(
    "yaml_text",
    (
        "version: '1'\ntrial: {}\ntrial: {}\nviewer: {}\n",
        "version: '1'\ntrial:\n  trial_name: one\n  trial_name: two\nviewer: {}\n",
    ),
)
def test_trial_yaml_duplicate_keys_fail_closed(tmp_path: Path, yaml_text: str) -> None:
    path = tmp_path / "trial.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_sr_config(path)


def test_trial_yaml_rejects_unknown_and_non_utc_values() -> None:
    raw = load_sr_config(_TRIAL_PATH)
    raw = dict(raw)
    raw["viewer"] = dict(raw["viewer"])
    raw["viewer"]["unexpected"] = True
    with pytest.raises(ContractValidationError):
        parse_trial_config(raw)

    raw = load_sr_config(_TRIAL_PATH)
    raw = dict(raw)
    raw["trial"] = dict(raw["trial"])
    raw["trial"]["requested_since"] = "2024-01-01T00:00:00+05:30"
    with pytest.raises(ContractValidationError, match="UTC"):
        parse_trial_config(raw)


def test_existing_sr_config_still_exposes_exact_eight_paths() -> None:
    resolved = load_resolved_sr_config(
        _ROOT / "configs" / "sr.yaml",
        asset="TAOUSDT",
        timeframe="1d",
    )
    assert len(resolved.field_provenance) == 8
    assert resolved.resolved_config_hash


@pytest.mark.parametrize(
    "contract_type",
    (
        DetectionConfig,
        AssociationConfig,
        LifecycleConfig,
        RuntimeConfig,
        ResolvedInputConfig,
        ViewerConfig,
        TrialSpec,
        SourceBar,
        ValidatedDataset,
        ATRProvenance,
        BundleMember,
        EvidenceManifest,
        TrialResult,
    ),
)
def test_contract_fields_have_no_python_defaults(contract_type: type) -> None:
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(contract_type)
    )
