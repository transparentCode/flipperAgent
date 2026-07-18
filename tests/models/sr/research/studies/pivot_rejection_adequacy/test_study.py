from dataclasses import replace
from pathlib import Path

import pytest

from libs.models.sr.domain import CandidateLevel, ContractValidationError, ZoneGeometry
from libs.models.sr.research.studies.pivot_rejection_adequacy.config import (
    load_pivot_rejection_adequacy_config,
)
from libs.models.sr.research.studies.pivot_rejection_adequacy.metrics import build_study
from libs.models.sr.research.studies.pivot_rejection_adequacy.outcomes import (
    build_naive_controls,
    evaluate_candidates,
)
from libs.models.sr.research.studies.pivot_rejection_adequacy.runner import (
    compute_pivot_rejection_study,
    load_frozen_inputs,
)


_ROOT = Path(__file__).resolve().parents[6]
_CONFIG = _ROOT / "configs/sr_trials/sr_v2_1_taousdt_1d_pivot_rejection_adequacy.yaml"


def _inputs():
    config = load_pivot_rejection_adequacy_config(str(_CONFIG))
    frozen = load_frozen_inputs(config, repo_root=_ROOT)
    cases = evaluate_candidates(frozen.model_bars, config=config)
    return (
        config,
        frozen,
        cases,
        build_naive_controls(cases, frozen.model_bars, config=config),
    )


def test_frozen_study_is_network_free_and_controls_are_independent() -> None:
    config, frozen, cases, controls = _inputs()
    study = compute_pivot_rejection_study(
        config, repo_root=_ROOT, implementation_commit="a" * 40
    )
    assert len(cases) == 65 and len(controls) == 120 and len(study.pairs) == 38
    assert {control.candidate.source for control in controls} == {
        "prior_close_naive_v2_1"
    }
    assert all(
        control.candidate.geometry.center == control.prior_close for control in controls
    )
    assert any(
        control.outcome is not None
        and case.outcome is not None
        and control.outcome.touch_bar_id != case.outcome.touch_bar_id
        for control in controls
        for case in cases
        if control.real_case_id == case.case_id
    )


def test_control_topology_and_causal_identity_fail_closed() -> None:
    config, _, cases, controls = _inputs()
    with pytest.raises(ContractValidationError, match="topology"):
        build_study(cases, controls[1:], config=config, implementation_commit="a" * 40)
    control = controls[0]
    wrong = CandidateLevel(
        control.candidate.state_key,
        control.candidate.side,
        ZoneGeometry(control.prior_close + 1.0, control.candidate.geometry.half_width),
        control.candidate.source,
        control.candidate.formed_at,
        control.candidate.available_at,
        control.candidate.atr_at_creation,
    )
    with pytest.raises(ContractValidationError, match="prior close"):
        replace(control, candidate=wrong)
    real = next(case for case in cases if case.fold is not None)
    assert (
        replace(real, status=real.status, outcome=real.outcome).case_id == real.case_id
    )
