from __future__ import annotations

from copy import deepcopy

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.atr_calibration.config import (
    load_calibration_config,
    parse_calibration_config,
)


def test_real_calibration_yaml_is_exact_and_hashable(calibration_config):
    assert calibration_config.candidate_periods == (7, 10, 14, 20, 28)
    assert calibration_config.baseline_period == 14
    assert calibration_config.evaluation_reference_period == 14
    assert len(calibration_config.development_folds) == 6
    assert len(calibration_config.config_hash) == 64


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.__setitem__("unexpected", 1),
        lambda value: value["atr"].__setitem__("candidate_periods", [7, 14, 10, 20, 28]),
        lambda value: value["atr"].__setitem__("candidate_periods", [7, 10, 14, 20, 20]),
        lambda value: value["atr"].__setitem__("baseline_period", True),
        lambda value: value["holdout"].__setitem__("start", "2026-01-01T00:00:00+00:00"),
    ],
)
def test_invalid_typed_or_protocol_mutations_fail_closed(calibration_config, mutator):
    raw = deepcopy(calibration_config.to_payload())
    mutator(raw)
    with pytest.raises(ContractValidationError):
        parse_calibration_config(raw)


def test_duplicate_yaml_keys_fail_at_root_and_nested(tmp_path):
    config_path = tmp_path / "duplicate.yaml"
    config_path.write_text(
        "version: '1'\nversion: '1'\ncalibration: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractValidationError):
        load_calibration_config(config_path)

    config_path.write_text(
        "version: '1'\ncalibration:\n  trial_name: one\n  trial_name: two\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractValidationError):
        load_calibration_config(config_path)
