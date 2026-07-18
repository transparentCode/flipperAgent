from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.displacement_origin_adequacy.config import (
    APPROVED_DETECTOR,
    APPROVED_GATES,
    load_displacement_origin_adequacy_config,
)


_CONFIG = "configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml"


def test_real_v2_configuration_loads_with_all_locked_protocol_values() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)

    assert config.detector.to_payload() == APPROVED_DETECTOR
    assert config.gates.to_payload() == APPROVED_GATES
    assert len(config.folds) == 6
    assert config.artifact.members == ("manifest.json", "study.json", "cases.json")


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ("  displacement_atr: 1.0\n", "", "missing"),
        ("  base_search_bars: 3\n", "  base_search_bars: 3\n  unknown: 1\n", "unknown"),
        ("  displacement_atr: 1.0\n", "  displacement_atr: 1.0\n  displacement_atr: 2.0\n", "invalid SR YAML"),
        ("  displacement_atr: 1.0\n", "  displacement_atr: false\n", "numeric"),
        ("  displacement_atr: 1.0\n", "  displacement_atr: 2.0\n", "approved"),
    ],
)
def test_v2_configuration_fails_closed_on_missing_unknown_duplicate_type_and_range(
    tmp_path: Path,
    old: str,
    new: str,
    expected: str,
) -> None:
    text = Path(_CONFIG).read_text(encoding="utf-8")
    mutated = text.replace(old, new, 1)
    path = tmp_path / "trial.yaml"
    path.write_text(mutated, encoding="utf-8")

    with pytest.raises(ContractValidationError, match=expected):
        load_displacement_origin_adequacy_config(str(path))
