from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.domain import CandidateLevel, ContractValidationError, SRStateKey, ZoneGeometry, ZoneSide
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.studies.displacement_origin_adequacy.config import load_displacement_origin_adequacy_config
from libs.models.sr.research.studies.displacement_origin_adequacy.contracts import CandidateCase, DisplacementOriginDisposition, NaiveControl, OutcomeStatus
from libs.models.sr.research.studies.displacement_origin_adequacy.metrics import build_study


_CONFIG = "configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml"
_T0 = datetime(2024, 7, 5, tzinfo=timezone.utc)


def _outcome(candidate: CandidateLevel, quality: float, index: int) -> FirstTouchOutcome:
    touch_at = candidate.available_at + timedelta(days=1)
    return FirstTouchOutcome(zone_id=candidate.candidate_id, side=candidate.side, first_touch_at=touch_at, touch_bar_id=f"touch-{index}", anchor_close=100.0, reference_atr_14=1.0, completed=True, right_censored=False, tenth_outcome_bar_closed_at=touch_at + timedelta(days=10), favorable_reference_atr=max(quality, 0.0), adverse_reference_atr=max(-quality, 0.0), quality_reference_atr=quality, invalidated=False)


def _case(index: int, fold: str, quality: float) -> CandidateCase:
    timestamp = _T0 + timedelta(days=index)
    candidate = CandidateLevel(state_key=SRStateKey("binance_usdm", "TAOUSDT", "1d"), side=ZoneSide.SUPPORT if index % 2 == 0 else ZoneSide.RESISTANCE, geometry=ZoneGeometry(center=100.0 + index, half_width=1.0), source="displacement_origin_v2", formed_at=timestamp - timedelta(days=1), available_at=timestamp, atr_at_creation=1.0)
    return CandidateCase(candidate=candidate, confirmation_bar_id=f"confirmation-{index}", confirmation_index=index + 1, base_distance_bars=1, fold=fold, status=OutcomeStatus.COMPLETED, outcome=_outcome(candidate, quality, index), zone_width_atr=2.0)


def _controls(case: CandidateCase, quality: float) -> tuple[NaiveControl, ...]:
    result: list[NaiveControl] = []
    for side in (ZoneSide.SUPPORT, ZoneSide.RESISTANCE):
        candidate = CandidateLevel(state_key=case.candidate.state_key, side=side, geometry=ZoneGeometry(center=case.candidate.geometry.center + 10.0, half_width=case.candidate.geometry.half_width), source="prior_close_naive_v2", formed_at=case.candidate.formed_at, available_at=case.candidate.available_at, atr_at_creation=case.candidate.atr_at_creation)
        result.append(NaiveControl(real_confirmation_id=case.confirmation_id, candidate=candidate, confirmation_bar_id=case.confirmation_bar_id, confirmation_index=case.confirmation_index, fold=case.fold or "missing", status=OutcomeStatus.COMPLETED, outcome=_outcome(candidate, quality, case.confirmation_index), zone_width_atr=case.zone_width_atr))
    return tuple(result)


def _population(real_quality: float, naive_quality: float, count: int) -> tuple[tuple[CandidateCase, ...], tuple[NaiveControl, ...]]:
    folds = ("2024_q3", "2024_q4", "2025_q1", "2025_q2")
    cases = tuple(_case(index, folds[index // 6], real_quality) for index in range(count))
    return cases, tuple(control for case in cases for control in _controls(case, naive_quality))


@pytest.mark.parametrize(
    "real_quality, naive_quality, count, expected",
    [(1.0, 0.0, 24, DisplacementOriginDisposition.BEATS_NAIVE_NULL), (0.0, 0.0, 24, DisplacementOriginDisposition.NOT_BETTER_THAN_NAIVE_NULL), (1.0, 0.0, 18, DisplacementOriginDisposition.INSUFFICIENT_EVIDENCE)],
)
def test_paired_gate_precedence_covers_all_v2_dispositions(real_quality: float, naive_quality: float, count: int, expected: DisplacementOriginDisposition) -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    cases, controls = _population(real_quality, naive_quality, count)
    study = build_study(cases, controls, config=config, implementation_commit="a" * 40)
    assert study.decision.disposition is expected
    assert all(pair.paired_excess_quality_atr == real_quality - naive_quality for pair in study.pairs)


def test_pairing_rejects_control_geometry_or_width_mismatch() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    cases, controls = _population(1.0, 0.0, 24)
    bad = list(controls)
    object.__setattr__(bad[0], "zone_width_atr", 3.0)
    with pytest.raises(ContractValidationError, match="matching contract"):
        build_study(cases, tuple(bad), config=config, implementation_commit="a" * 40)


def test_study_rejects_missing_extra_or_duplicate_side_controls_per_case() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    cases, controls = _population(1.0, 0.0, 24)
    # Keep total 48: first candidate has four controls; second has none.
    malformed = controls[:2] + controls[:2] + controls[4:]

    with pytest.raises(ContractValidationError, match="ordered SUPPORT/RESISTANCE topology"):
        build_study(cases, malformed, config=config, implementation_commit="a" * 40)


def test_study_rejects_malformed_implementation_identity() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    cases, controls = _population(1.0, 0.0, 24)
    with pytest.raises(ContractValidationError, match="implementation_commit"):
        build_study(cases, controls, config=config, implementation_commit="not-a-commit")
