from __future__ import annotations

from dataclasses import MISSING, fields

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.lifecycle_utility.config import (
    FROZEN_ATR_PERIOD,
    FROZEN_EVENT_CLASSES,
    FROZEN_FOLD_NAMES,
    FROZEN_OUTCOME_HORIZON,
    FROZEN_OUTCOME_OFFSET,
    LifecycleUtilityConfig,
    QualityGates,
    ReadinessGates,
    load_lifecycle_utility_config,
)

from conftest import CONFIG_PATH


def test_real_yaml_binds_exact_frozen_protocol(lifecycle_config):
    assert lifecycle_config.event_classes == FROZEN_EVENT_CLASSES
    assert lifecycle_config.atr_period == FROZEN_ATR_PERIOD
    assert lifecycle_config.outcome_start_offset_bars == FROZEN_OUTCOME_OFFSET
    assert lifecycle_config.outcome_horizon_bars == FROZEN_OUTCOME_HORIZON
    assert tuple(fold.name for fold in lifecycle_config.folds) == FROZEN_FOLD_NAMES
    assert lifecycle_config.source_row_count == 629
    assert lifecycle_config.source_bundle_id == "d210494937ebcd4347e026b8ac02bff3105065e5455752b8690d449def357925"


@pytest.mark.parametrize("model", (LifecycleUtilityConfig, ReadinessGates, QualityGates))
def test_protocol_dataclass_fields_have_no_defaults(model):
    tunable_fields = fields(model)
    assert all(item.default is MISSING and item.default_factory is MISSING for item in tunable_fields)


def test_config_hash_is_deterministic_and_no_python_fallback(lifecycle_config):
    reloaded = load_lifecycle_utility_config(CONFIG_PATH)
    assert reloaded.to_payload() == lifecycle_config.to_payload()
    assert reloaded.config_hash == lifecycle_config.config_hash
    assert "config_hash" not in lifecycle_config.to_payload()


@pytest.mark.parametrize(
    ("needle", "replacement"),
    (
        ("version: \"1\"", "version: \"2\""),
        ("source_row_count: 629", "source_row_count: 630"),
        ("  root: research/tmp_sr_v1_11/lifecycle_utility", "  root: research/tmp_sr_v1_11/lifecycle_utility\n  unexpected: 1"),
    ),
)
def test_protocol_mutations_fail_closed(tmp_path, needle, replacement):
    text = CONFIG_PATH.read_text(encoding="utf-8")
    assert needle in text
    path = tmp_path / "mutated.yaml"
    path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_lifecycle_utility_config(path)


@pytest.mark.parametrize(
    "duplicate",
    (
        "  readiness:\n  readiness:\n",
        "    minimum_completed_unique_resolutions: 16\n    minimum_completed_unique_resolutions: 16\n",
        "      start: \"2024-07-01T00:00:00Z\"\n      start: \"2024-07-01T00:00:00Z\"\n",
    ),
)
def test_recursive_duplicate_yaml_keys_fail_closed(tmp_path, duplicate):
    text = CONFIG_PATH.read_text(encoding="utf-8")
    if duplicate.startswith("  readiness"):
        needle = "  readiness:\n"
    elif duplicate.startswith("    minimum"):
        needle = "    minimum_completed_unique_resolutions: 16\n"
    else:
        needle = "      start: \"2024-07-01T00:00:00Z\"\n"
    path = tmp_path / "duplicate.yaml"
    path.write_text(text.replace(needle, duplicate + needle, 1), encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_lifecycle_utility_config(path)


def test_empty_and_non_mapping_yaml_fail_closed(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    non_mapping = tmp_path / "scalar.yaml"
    non_mapping.write_text("- one\n- two\n", encoding="utf-8")
    for path in (empty, non_mapping):
        with pytest.raises(ContractValidationError):
            load_lifecycle_utility_config(path)
