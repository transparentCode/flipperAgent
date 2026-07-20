from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.adaptive_context_calibration.config import (
    load_adaptive_context_calibration_config,
)


def test_exact_immutable_config(config) -> None:
    assert config.config_hash == "061ccbf306d2bc384340db70cbb9f6eb4181d931b3627015612b47a7c3270b50"
    assert config.assets == ("TAOUSDT", "ETHUSDT", "SOLUSDT")
    assert config.timeframes == ("1d", "12h")
    assert config.provider_12h.expected_rows == 1000
    assert config.provider_12h.max_calls_per_asset == 1
    assert tuple(fold.name for fold in config.folds) == (
        "2025_q1",
        "2025_q2",
        "2025_q3",
        "2025_q4",
    )


def test_recursive_duplicate_yaml_keys_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "version: '1'\nversion: '1'\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractValidationError, match="duplicate"):
        load_adaptive_context_calibration_config(str(path))
