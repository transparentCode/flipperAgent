from __future__ import annotations

from copy import deepcopy

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.baseline_adequacy.config import load_baseline_adequacy_config, parse_baseline_adequacy_config


def test_real_config_is_exact_and_immutable(adequacy_config):
    assert adequacy_config.asset == "TAOUSDT"
    assert adequacy_config.timeframe == "1d"
    assert adequacy_config.controls_per_anchor == 2
    assert tuple(side.value for side in adequacy_config.control_side_order) == ("SUPPORT", "RESISTANCE")
    assert adequacy_config.config_hash == "ae8b290674f8c9feb3ce630910753f44dcff87a64795428f614735b0cc2dc9a9"


@pytest.mark.parametrize("field", [
    "minimum_completed_real_outcomes",
    "minimum_comparable_folds",
    "minimum_real_outcomes_per_comparable_fold",
    "minimum_controls_per_side_per_comparable_fold",
    "minimum_pooled_median_excess_quality_atr",
    "minimum_positive_comparable_fold_fraction",
    "minimum_worst_comparable_fold_excess_atr",
])
def test_gate_mutation_fails_closed(adequacy_config, field):
    payload = deepcopy(adequacy_config.to_payload())
    current = payload["gates"][field]
    payload["gates"][field] = current + 1
    with pytest.raises(ContractValidationError):
        parse_baseline_adequacy_config(payload)


def test_missing_and_unknown_config_keys_fail_closed(adequacy_config):
    payload = deepcopy(adequacy_config.to_payload())
    del payload["controls"]["controls_per_anchor"]
    with pytest.raises(ContractValidationError):
        parse_baseline_adequacy_config(payload)
    payload = deepcopy(adequacy_config.to_payload())
    payload["controls"]["unexpected"] = 1
    with pytest.raises(ContractValidationError):
        parse_baseline_adequacy_config(payload)


def test_duplicate_and_alias_yaml_fail_closed(tmp_path, adequacy_config):
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("version: '1'\nversion: '1'\n", encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_baseline_adequacy_config(duplicate)
    alias = tmp_path / "alias.yaml"
    alias.write_text("base: &base 1\ncopy: *base\n", encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_baseline_adequacy_config(alias)
