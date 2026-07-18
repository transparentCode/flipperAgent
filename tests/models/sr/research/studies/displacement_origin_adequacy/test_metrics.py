from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.domain import (
    CandidateLevel,
    ContractValidationError,
    SRStateKey,
    ZoneGeometry,
    ZoneSide,
)
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.evidence.baseline_adequacy.contracts import ControlOutcome
from libs.models.sr.research.metrics.first_touch import FirstTouchOutcome
from libs.models.sr.research.studies.displacement_origin_adequacy.config import (
    load_displacement_origin_adequacy_config,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.contracts import (
    CandidateCase,
    DisplacementOriginDisposition,
    MatchedControl,
    OutcomeStatus,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.metrics import (
    build_study,
)


_CONFIG = "configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml"
_T0 = datetime(2024, 7, 5, tzinfo=timezone.utc)


def _case(index: int, *, fold: str, quality: float) -> CandidateCase:
    timestamp = _T0 + timedelta(days=index)
    candidate = CandidateLevel(
        state_key=SRStateKey("binance_usdm", "TAOUSDT", "1d"),
        side=ZoneSide.SUPPORT if index % 2 == 0 else ZoneSide.RESISTANCE,
        geometry=ZoneGeometry(center=100.0 + index, half_width=1.0),
        source="displacement_origin_v2",
        formed_at=timestamp - timedelta(days=1),
        available_at=timestamp,
        atr_at_creation=1.0,
    )
    touch_at = timestamp + timedelta(days=1)
    outcome = FirstTouchOutcome(
        zone_id=candidate.candidate_id,
        side=candidate.side,
        first_touch_at=touch_at,
        touch_bar_id=f"touch-{index}",
        anchor_close=100.0,
        reference_atr_14=1.0,
        completed=True,
        right_censored=False,
        tenth_outcome_bar_closed_at=touch_at + timedelta(days=10),
        favorable_reference_atr=max(quality, 0.0),
        adverse_reference_atr=max(-quality, 0.0),
        quality_reference_atr=quality,
        invalidated=False,
    )
    return CandidateCase(
        candidate=candidate,
        confirmation_bar_id=f"confirmation-{index}",
        confirmation_index=index,
        base_distance_bars=1,
        fold=fold,
        status=OutcomeStatus.COMPLETED,
        outcome=outcome,
        zone_width_atr=2.0,
    )


def _controls(case: CandidateCase, *, config_hash: str) -> tuple[MatchedControl, ...]:
    assert case.outcome is not None
    result: list[MatchedControl] = []
    for side in (ZoneSide.SUPPORT, ZoneSide.RESISTANCE):
        result.append(
            MatchedControl(
                real_case_id=case.case_id,
                candidate_id=case.candidate.candidate_id,
                zone_width_atr=case.zone_width_atr,
                outcome=ControlOutcome(
                    anchor_id=deterministic_hash({"case": case.case_id, "side": side.value}),
                    asset="TAOUSDT",
                    timeframe="1d",
                    fold=case.fold or "missing",
                    bar_id=case.outcome.touch_bar_id,
                    anchor_at=case.outcome.first_touch_at,
                    side=side,
                    anchor_close=case.outcome.anchor_close,
                    reference_atr_14=case.outcome.reference_atr_14,
                    outcome_start_offset_bars=1,
                    outcome_horizon_bars=10,
                    tenth_outcome_bar_closed_at=case.outcome.tenth_outcome_bar_closed_at,
                    favorable_reference_atr=0.0,
                    adverse_reference_atr=0.0,
                    quality_reference_atr=0.0,
                    config_hash=config_hash,
                ),
            )
        )
    return tuple(result)


def _population(*, quality: float, fold_count: int) -> tuple[CandidateCase, ...]:
    folds = ("2024_q3", "2024_q4", "2025_q1", "2025_q2", "2025_q3", "2025_q4")
    return tuple(
        _case(index, fold=folds[index // 6], quality=quality)
        for index in range(fold_count * 6)
    )


@pytest.mark.parametrize(
    "quality, count, expected",
    [
        (1.0, 24, DisplacementOriginDisposition.BEATS_NAIVE_NULL),
        (0.0, 24, DisplacementOriginDisposition.NOT_BETTER_THAN_NAIVE_NULL),
        (1.0, 18, DisplacementOriginDisposition.INSUFFICIENT_EVIDENCE),
    ],
)
def test_gate_precedence_covers_all_v2_dispositions(
    quality: float,
    count: int,
    expected: DisplacementOriginDisposition,
) -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    cases = _population(quality=quality, fold_count=count // 6)
    controls = tuple(control for case in cases for control in _controls(case, config_hash=config.config_hash))

    study = build_study(
        cases,
        controls,
        config=config,
        implementation_commit="a" * 40,
    )

    assert study.decision.disposition is expected
    if expected is DisplacementOriginDisposition.INSUFFICIENT_EVIDENCE:
        assert not next(item for item in study.decision.gates if item.name == "readiness.completed_real_outcomes").passed


def test_study_rejects_malformed_implementation_identity() -> None:
    config = load_displacement_origin_adequacy_config(_CONFIG)
    cases = _population(quality=1.0, fold_count=4)
    controls = tuple(control for case in cases for control in _controls(case, config_hash=config.config_hash))

    with pytest.raises(ContractValidationError, match="implementation_commit"):
        build_study(cases, controls, config=config, implementation_commit="not-a-commit")
