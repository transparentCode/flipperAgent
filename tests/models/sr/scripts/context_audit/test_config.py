from __future__ import annotations

from copy import deepcopy
from dataclasses import fields

import pytest

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.context_audit.config import (
    ContextAuditConfig,
    load_context_audit_config,
    parse_context_audit_config,
)


def test_real_config_is_frozen_and_complete(context_config):
    assert context_config.config_hash == "1ae6cdf31951e20540a9625a85e593e9bfbb9520364b68d6e783f05ab477207f"
    assert context_config.source_row_count == 629
    assert context_config.outcome_start_offset_bars == 1
    assert context_config.outcome_horizon_bars == 10
    assert tuple(fold.name for fold in context_config.folds) == (
        "2024_q3", "2024_q4", "2025_q1", "2025_q2", "2025_q3", "2025_q4"
    )


def test_trial_fields_have_no_hidden_python_defaults():
    defaulted = {
        item.name
        for item in fields(ContextAuditConfig)
        if item.default is not item.default_factory
    }
    assert defaulted == {"audit_status"}


@pytest.mark.parametrize(
    "mutation",
    (
        lambda raw: raw["trial"].__setitem__("asset", "BTCUSDT"),
        lambda raw: raw["protocol"]["model"].__setitem__("atr_period", 7),
        lambda raw: raw["protocol"]["outcome"].__setitem__("horizon_bars", 11),
        lambda raw: raw["protocol"]["folds"].pop(),
        lambda raw: raw["viewer"].__setitem__("attribution_logo", False),
        lambda raw: raw["protocol"]["model"].__setitem__("zone_half_width_atr", float("nan")),
    ),
)
def test_frozen_protocol_mutations_fail(mutation, repo_root):
    path = repo_root / "configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml"
    raw = deepcopy(load_sr_config(path))
    mutation(raw)
    with pytest.raises(ContractValidationError):
        parse_context_audit_config(raw)


def test_unknown_and_missing_keys_fail(repo_root):
    path = repo_root / "configs/sr_trials/sr_v1_10_taousdt_1d_context_audit.yaml"
    raw = deepcopy(load_sr_config(path))
    raw["unexpected"] = True
    with pytest.raises(ContractValidationError):
        parse_context_audit_config(raw)
    raw = deepcopy(load_sr_config(path))
    del raw["inputs"]["v19"]["study_id"]
    with pytest.raises(ContractValidationError):
        parse_context_audit_config(raw)


def test_duplicate_yaml_keys_fail_closed(tmp_path):
    path = tmp_path / "duplicate.yaml"
    path.write_text('version: "1"\nversion: "1"\n', encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_context_audit_config(path)
