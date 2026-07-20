from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.swing_reversal_adequacy.config import (
    APPROVED_DETECTOR,
    load_swing_reversal_adequacy_config,
)


_CONFIG = "configs/sr_trials/sr_v2_2_taousdt_1d_swing_reversal_adequacy.yaml"


def test_v22_configuration_is_strict_and_deterministic() -> None:
    config = load_swing_reversal_adequacy_config(_CONFIG)
    assert config.detector.to_payload() == APPROVED_DETECTOR == {"reversal_atr": 1.5}
    assert config.to_payload()["detector"] == {"reversal_atr": 1.5}
    assert (
        config.config_hash == load_swing_reversal_adequacy_config(_CONFIG).config_hash
    )


@pytest.mark.parametrize(
    "payload",
    [
        "version: '1'\n",
        "version: '1'\ntrial: {}\n",
        "version: '1'\ndetector:\n  reversal_atr: true\n",
        "version: '1'\ndetector:\n  reversal_atr: 1.5\n  reversal_atr: 2.0\n",
    ],
)
def test_v22_configuration_rejects_incomplete_typed_and_duplicate_yaml(
    tmp_path: Path, payload: str
) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ContractValidationError):
        load_swing_reversal_adequacy_config(str(path))
