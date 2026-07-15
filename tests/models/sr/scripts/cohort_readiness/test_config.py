from __future__ import annotations

from copy import deepcopy

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.cohort_readiness.config import (
    load_cohort_config,
    parse_cohort_config,
)


def test_real_trial_yaml_is_locked_and_round_trips(cohort_config):
    assert cohort_config.assets == ("TAOUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert cohort_config.atr_period == 14
    assert cohort_config.common_start_period == 28
    assert cohort_config.outcome_start_offset_bars == 1
    assert cohort_config.outcome_horizon_bars == 10
    assert len(cohort_config.folds) == 6
    assert parse_cohort_config(cohort_config.to_payload()).config_hash == cohort_config.config_hash


@pytest.mark.parametrize(
    "mutator",
    [
        lambda raw: raw["trial"].__setitem__("assets", ["TAOUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]),
        lambda raw: raw["atr"].__setitem__("period", 7),
        lambda raw: raw["atr"].__setitem__("common_start_period", 29),
        lambda raw: raw["outcome"].__setitem__("horizon_bars", 11),
        lambda raw: raw["readiness"].__setitem__("minimum_eligible_development_folds", 5),
        lambda raw: raw["sources"]["window"].__setitem__("until", "2026-01-01T00:00:00Z"),
        lambda raw: raw["provider"].__setitem__("limit", 1500),
        lambda raw: raw.__setitem__("unexpected", True),
    ],
)
def test_protocol_mutations_fail_closed(cohort_config, mutator):
    raw = deepcopy(cohort_config.to_payload())
    mutator(raw)
    with pytest.raises(ContractValidationError):
        parse_cohort_config(raw)


def test_recursive_duplicate_yaml_keys_fail_closed(tmp_path, cohort_config):
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "version: '1'\nversion: '1'\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractValidationError):
        load_cohort_config(path)
    path.write_text(
        "version: '1'\ntrial:\n  trial_name: a\n  trial_name: b\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractValidationError):
        load_cohort_config(path)
