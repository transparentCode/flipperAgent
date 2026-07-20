from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from libs.models.sr.detection.causal_swing_reversal import detect_causal_swing_reversals
from libs.models.sr.domain import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    SRStateKey,
    ZoneGeometry,
    ZoneSide,
)
from libs.models.sr.research.metrics.first_revisit import first_revisit_outcome
from libs.models.sr.research.studies.swing_reversal_adequacy.config import (
    load_swing_reversal_adequacy_config,
)
from libs.models.sr.research.studies.swing_reversal_adequacy.contracts import (
    Decision,
    GateResult,
    SwingReversalDisposition,
)
from libs.models.sr.research.studies.swing_reversal_adequacy.metrics import build_study
from libs.models.sr.research.studies.swing_reversal_adequacy.outcomes import (
    build_naive_controls,
    evaluate_candidates,
)
from libs.models.sr.research.studies.swing_reversal_adequacy.runner import (
    compute_swing_reversal_study,
    load_frozen_inputs,
)


_ROOT = Path(__file__).resolve().parents[6]
_CONFIG = _ROOT / "configs/sr_trials/sr_v2_2_taousdt_1d_swing_reversal_adequacy.yaml"


def _inputs():
    config = load_swing_reversal_adequacy_config(str(_CONFIG))
    frozen = load_frozen_inputs(config, repo_root=_ROOT)
    swings, cases = evaluate_candidates(frozen.model_bars, config=config)
    return (
        config,
        frozen,
        swings,
        cases,
        build_naive_controls(cases, frozen.model_bars, config=config),
    )


def test_frozen_study_binds_swing_provenance_and_independent_controls() -> None:
    config, frozen, swings, cases, controls = _inputs()
    study = compute_swing_reversal_study(
        config, repo_root=_ROOT, implementation_commit="a" * 40
    )
    assert study.swings == swings
    assert len(cases) == len([item for item in swings if item.candidate_id is not None])
    assert len(controls) == 2 * len([item for item in cases if item.fold is not None])
    cases_by_id = {case.case_id: case for case in cases}
    assert all(
        control.candidate.geometry.center
        == control.prior_close
        == cases_by_id[control.real_case_id].prior_close
        == frozen.model_bars[control.confirmation_index - 1].close
        for control in controls
    )
    assert all(
        frozen.model_bars[case.extreme_index].bar_id == case.extreme_bar_id
        and frozen.model_bars[case.extreme_index].atr_at_close == case.extreme_atr
        and frozen.model_bars[case.confirmation_index].atr_at_close
        == case.candidate.atr_at_creation
        for case in cases
    )
    assert any(
        control.outcome is not None
        and case.outcome is not None
        and control.outcome.touch_bar_id != case.outcome.touch_bar_id
        for control in controls
        for case in cases
        if control.real_case_id == case.case_id
    )


def test_full_prefix_replay_and_future_outcomes_preserve_causal_ids() -> None:
    config, frozen, _, cases, controls = _inputs()
    full = detect_causal_swing_reversals(frozen.model_bars, config.detector)
    for end in range(1, len(frozen.model_bars) + 1):
        assert detect_causal_swing_reversals(
            frozen.model_bars[:end], config.detector
        ) == tuple(item for item in full if item.confirmation_index < end)
    case = next(
        item for item in cases if item.outcome is not None and item.outcome.completed
    )
    control = next(
        item
        for item in controls
        if item.real_case_id == case.case_id
        and item.outcome is not None
        and item.outcome.completed
    )
    assert case.outcome is not None and control.outcome is not None
    changed_case = replace(
        case.outcome,
        favorable_reference_atr=case.outcome.favorable_reference_atr + 1.0,
        quality_reference_atr=case.outcome.quality_reference_atr + 1.0,
    )
    changed_control = replace(
        control.outcome,
        favorable_reference_atr=control.outcome.favorable_reference_atr + 1.0,
        quality_reference_atr=control.outcome.quality_reference_atr + 1.0,
    )
    assert replace(case, outcome=changed_case).case_id == case.case_id
    assert replace(control, outcome=changed_control).control_id == control.control_id


def _outcome_bar(index: int, *, high: float = 110.0, low: float = 109.0) -> ClosedBar:
    close = min(max(100.5, low), high)
    return ClosedBar(
        SRStateKey("venue", "asset", "1d"),
        str(index),
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
        close,
        high,
        low,
        close,
        1.0,
    )


def _outcome_candidate(bar: ClosedBar) -> CandidateLevel:
    return CandidateLevel(
        bar.state_key,
        ZoneSide.SUPPORT,
        ZoneGeometry(100.0, 1.0),
        "fixture",
        bar.closed_at,
        bar.closed_at,
        1.0,
    )


def test_touch_search_and_fold_horizon_boundaries() -> None:
    bars = tuple(
        _outcome_bar(index, high=101.0, low=100.0)
        if index == 50
        else _outcome_bar(index)
        for index in range(62)
    )
    complete = first_revisit_outcome(
        _outcome_candidate(bars[0]),
        confirmation_index=0,
        fold_end=bars[-1].closed_at,
        bars=bars,
        first_touch_offset_bars=1,
        touch_search_bars=50,
        horizon_bars=1,
    )
    assert complete is not None and complete.completed and complete.touch_bar_id == "50"
    late = tuple(
        _outcome_bar(index, high=101.0, low=100.0)
        if index == 51
        else _outcome_bar(index)
        for index in range(62)
    )
    assert (
        first_revisit_outcome(
            _outcome_candidate(late[0]),
            confirmation_index=0,
            fold_end=late[-1].closed_at,
            bars=late,
            first_touch_offset_bars=1,
            touch_search_bars=50,
            horizon_bars=1,
        )
        is None
    )
    censored = first_revisit_outcome(
        _outcome_candidate(bars[0]),
        confirmation_index=0,
        fold_end=bars[51].closed_at,
        bars=bars,
        first_touch_offset_bars=1,
        touch_search_bars=50,
        horizon_bars=1,
    )
    assert censored is not None and censored.right_censored


def test_controls_gates_and_dispositions_fail_closed() -> None:
    config, _, swings, cases, controls = _inputs()
    study = compute_swing_reversal_study(
        config, repo_root=_ROOT, implementation_commit="a" * 40
    )
    gates = study.decision.gates
    assert Decision(
        SwingReversalDisposition.NOT_BETTER_THAN_NAIVE_NULL,
        gates,
        "one or more utility gates failed after readiness",
    )
    failed_readiness = replace(gates[0], value=0, passed=False)
    assert Decision(
        SwingReversalDisposition.INSUFFICIENT_EVIDENCE,
        (failed_readiness,) + gates[1:],
        "readiness gates failed",
    )
    passed = tuple(replace(gate, value=gate.threshold, passed=True) for gate in gates)
    assert Decision(
        SwingReversalDisposition.BEATS_NAIVE_NULL,
        passed,
        "all utility gates passed after readiness",
    )
    with pytest.raises(ContractValidationError, match="topology"):
        Decision(SwingReversalDisposition.NOT_BETTER_THAN_NAIVE_NULL, gates[:-1], "x")
    with pytest.raises(ContractValidationError, match="unsupported"):
        GateResult("unknown", "readiness", 1, 1, ">=", True)
    with pytest.raises(ContractValidationError, match="topology"):
        build_study(
            swings, cases, controls[1:], config=config, implementation_commit="a" * 40
        )
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
