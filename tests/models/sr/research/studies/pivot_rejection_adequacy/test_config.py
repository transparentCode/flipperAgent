from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.research.studies.pivot_rejection_adequacy.config import (
    load_pivot_rejection_adequacy_config,
)


_ROOT = Path(__file__).resolve().parents[6]
_CONFIG = _ROOT / "configs/sr_trials/sr_v2_1_taousdt_1d_pivot_rejection_adequacy.yaml"


def test_approved_v21_configuration_is_strict_and_deterministic() -> None:
    config = load_pivot_rejection_adequacy_config(str(_CONFIG))
    assert config.detector.pivot_span_bars == 5
    assert config.controls_per_real_candidate == 2
    assert config.control_side_order[0].value == "SUPPORT"
    assert (
        config.config_hash
        == load_pivot_rejection_adequacy_config(str(_CONFIG)).config_hash
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("pivot_span_bars: 5", "pivot_span_bars: 4"),
        ("minimum_completed_pairs: 24", "minimum_completed_pairs: 23"),
        ("source_kind", "source_kind"),
    ],
)
def test_out_of_contract_configuration_is_rejected(
    tmp_path: Path, old: str, new: str
) -> None:
    content = _CONFIG.read_text()
    if old == "source_kind":
        content = content.replace(
            "  grid_policy:", "  source_kind: forbidden\n  grid_policy:"
        )
    else:
        content = content.replace(old, new)
    path = tmp_path / "invalid.yaml"
    path.write_text(content)
    with pytest.raises(ContractValidationError):
        load_pivot_rejection_adequacy_config(str(path))
