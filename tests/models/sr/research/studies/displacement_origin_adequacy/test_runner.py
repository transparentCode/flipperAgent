from __future__ import annotations

from pathlib import Path

from libs.models.sr.research.studies.displacement_origin_adequacy.config import (
    load_displacement_origin_adequacy_config,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.runner import (
    compute_displacement_origin_study,
    load_frozen_inputs,
)


_CONFIG = "configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml"


def test_runner_uses_only_the_verified_629_row_development_source() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)

    frozen = load_frozen_inputs(config, repo_root=Path("."))
    study = compute_displacement_origin_study(
        config,
        repo_root=Path("."),
        implementation_commit="a" * 40,
    )

    assert len(frozen.capsule.bars) == 629
    assert frozen.capsule.source_bundle_id == config.source.source_bundle_id
    assert len(frozen.model_bars) == 601
    assert study.source_bundle_id == config.source.bundle_id
    assert study.source_id == config.source.source_id
    assert len(study.cases) == 28
    assert len(study.completed_cases) == 23
    assert study.source_capsule_bundle_id == config.source.source_bundle_id
    assert len(study.controls) == 56
