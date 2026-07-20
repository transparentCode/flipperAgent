from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.relative_salience_rank_utility.config import (
    COHORTS,
    load_relative_salience_rank_config,
)


def test_frozen_configuration_is_exact_and_has_six_cohorts() -> None:
    config = load_relative_salience_rank_config("configs/sr_trials/sr_v2_4_relative_salience_rank_utility.yaml")
    assert len(COHORTS) == 6
    assert config.payload["provider"]["max_calls"] == 6
    assert config.payload["bootstrap"]["seed"] == 2404


@pytest.mark.parametrize(
    "text",
    (
        "version: '1'\nversion: '1'\n",
        "version: '1'\nunknown: true\n",
    ),
)
def test_configuration_rejects_duplicate_and_unknown_fields(tmp_path: Path, text: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_relative_salience_rank_config(str(path))
