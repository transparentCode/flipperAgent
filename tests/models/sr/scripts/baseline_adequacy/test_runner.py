from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.evidence.geometry_sensitivity.config import (
    GeometrySensitivityConfig,
)
from libs.models.sr.research.evidence.geometry_sensitivity.contracts import (
    GeometrySensitivityStudy,
)
from libs.models.sr.research.evidence.baseline_adequacy import runner as adequacy_runner
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
    assert type(frozen.v18_config) is GeometrySensitivityConfig
    assert type(frozen.v18_study) is GeometrySensitivityStudy


def test_frozen_inputs_reject_missing_v18_config(adequacy_config, repo_root):
    config = replace(adequacy_config, v18_config_path="definitely/missing/v18.yaml")

    with pytest.raises(ContractValidationError):
        load_frozen_inputs(config, repo_root=repo_root)


def test_frozen_inputs_reject_mutated_v18_config(
    adequacy_config,
    repo_root,
    tmp_path,
    monkeypatch,
):
    source = Path(repo_root) / adequacy_config.v18_config_path
    mutated = tmp_path / source.name
    mutated.write_text(
        source.read_text(encoding="utf-8").replace(
            "root: research/tmp_sr_v1_8",
            "root: research/mutated_v18",
        ),
        encoding="utf-8",
    )
    original_root_path = adequacy_runner._root_path

    def root_path(repo_root, relative, *, field_name):
        if field_name == "v18_config_path":
            return mutated
        return original_root_path(repo_root, relative, field_name=field_name)

    monkeypatch.setattr(adequacy_runner, "_root_path", root_path)

    with pytest.raises(ContractValidationError, match="loaded V1.8 config identity mismatch"):
        load_frozen_inputs(adequacy_config, repo_root=repo_root)
