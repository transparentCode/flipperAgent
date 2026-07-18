from dataclasses import replace
from pathlib import Path

from libs.models.sr.research.studies.pivot_rejection_adequacy.artifacts import (
    publish_study_bundle,
    validate_study_bundle,
)
from libs.models.sr.research.studies.pivot_rejection_adequacy.config import (
    ArtifactProtocol,
    load_pivot_rejection_adequacy_config,
)
from libs.models.sr.research.studies.pivot_rejection_adequacy.runner import (
    compute_pivot_rejection_study,
)


_ROOT = Path(__file__).resolve().parents[6]
_CONFIG = _ROOT / "configs/sr_trials/sr_v2_1_taousdt_1d_pivot_rejection_adequacy.yaml"


def test_bundle_recomputes_semantics(tmp_path: Path) -> None:
    config = load_pivot_rejection_adequacy_config(str(_CONFIG))
    config = replace(
        config,
        artifact=ArtifactProtocol(
            "unused", config.artifact.stage, config.artifact.members
        ),
    )
    study = compute_pivot_rejection_study(
        config, repo_root=_ROOT, implementation_commit="b" * 40
    )
    bundle_id, path = publish_study_bundle(study, config=config, output_root=tmp_path)
    assert (
        validate_study_bundle(
            path, config=config, repo_root=_ROOT, expected_bundle_id=bundle_id
        ).study_id
        == study.study_id
    )
