from __future__ import annotations

from inspect import signature
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.candidate_reinforcement_audit.config import (
    DECISION_CATEGORIES,
    FOLD_NAMES,
    load_candidate_audit_config,
)
from libs.models.sr.scripts.candidate_reinforcement_audit.runner import compute_audit


def test_real_config_is_exact_and_immutable(candidate_config):
    assert candidate_config.replay.pivot_span_bars == 5
    assert candidate_config.replay.atr_period == 14
    assert candidate_config.replay.folds == tuple(candidate_config.replay.folds)
    assert candidate_config.decision_categories == DECISION_CATEGORIES
    assert tuple(fold.name for fold in candidate_config.replay.folds) == FOLD_NAMES
    with pytest.raises(AttributeError):
        candidate_config.asset = "BTCUSDT"


def test_config_hash_is_deterministic(candidate_config):
    other = load_candidate_audit_config("configs/sr_trials/sr_v1_12_taousdt_1d_candidate_reinforcement_audit.yaml")
    assert other.to_payload() == candidate_config.to_payload()
    assert other.config_hash == candidate_config.config_hash


@pytest.mark.parametrize(
    "mutation",
    (
        ("version: \"1\"", "version: \"2\""),
        ("\nartifact:\n", "\nartifact:\n  unknown: true\n"),
        ("\nartifact:\n", "\nartifact:\n"),
    ),
)
def test_config_mutations_fail_closed(tmp_path, mutation, candidate_config):
    original = Path("configs/sr_trials/sr_v1_12_taousdt_1d_candidate_reinforcement_audit.yaml").read_text(encoding="utf-8")
    if mutation[0] == "\nartifact:\n" and mutation[1] == "\nartifact:\n":
        original = original.replace("\nartifact:\n", "\n", 1)
    else:
        original = original.replace(*mutation, 1)
    path = tmp_path / "candidate.yaml"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_candidate_audit_config(path)


def test_recursive_duplicate_yaml_keys_fail_closed(tmp_path):
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "version: \"1\"\nversion: \"1\"\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractValidationError):
        load_candidate_audit_config(path)


def test_audit_has_no_call_time_parameter_override_layer():
    names = set(signature(compute_audit).parameters)
    assert names == {"config", "repo_root", "implementation_commit"}
