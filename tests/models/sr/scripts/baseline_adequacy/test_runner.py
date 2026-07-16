from __future__ import annotations

from pathlib import Path

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
