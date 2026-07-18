from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.evidence.baseline_adequacy.geometry import (
    load_frozen_geometry_study,
)
from libs.models.sr.scripts.baseline_adequacy.runner import load_frozen_inputs


def test_frozen_inputs_are_validated_without_provider_or_source_preparation(adequacy_config, repo_root, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("provider/source preparation path reached")

    import libs.models.sr.scripts.atr_calibration.source as atr_source
    import libs.models.sr.scripts.cohort_readiness.source as cohort_source

    monkeypatch.setattr(atr_source, "build_source_capsules", fail)
    monkeypatch.setattr(atr_source, "load_frozen_source", fail)
    monkeypatch.setattr(cohort_source, "build_source_bundle", fail)
    monkeypatch.setattr(cohort_source, "load_taousdt_source", fail)
    frozen = load_frozen_inputs(adequacy_config, repo_root=Path(repo_root))
    assert frozen.tao_source.row_count == 629


def test_geometry_frozen_evidence_boundary_rejects_member_byte_tampering(
    adequacy_config,
    repo_root,
    tmp_path,
):
    source = Path(repo_root) / adequacy_config.v18_study_bundle_path
    bundle = tmp_path / source.name
    bundle.mkdir()
    for name in ("manifest.json", "study.json"):
        (bundle / name).write_bytes((source / name).read_bytes())

    config, study = load_frozen_geometry_study(
        bundle,
        config_hash=adequacy_config.v18_config_hash,
        implementation_commit=adequacy_config.v18_implementation_commit,
        bundle_id=adequacy_config.v18_study_bundle_id,
    )
    assert config.config_hash == adequacy_config.v18_config_hash
    assert study.study_id == adequacy_config.v18_study_id

    (bundle / "study.json").write_bytes((bundle / "study.json").read_bytes() + b" ")
    with pytest.raises(ContractValidationError, match="V1.8 study member hash mismatch"):
        load_frozen_geometry_study(
            bundle,
            config_hash=adequacy_config.v18_config_hash,
            implementation_commit=adequacy_config.v18_implementation_commit,
            bundle_id=adequacy_config.v18_study_bundle_id,
        )
