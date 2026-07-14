from __future__ import annotations

import pytest

from libs.models.trendline_family.contracts import FamilyRole, InteractionObservationState
from libs.models.trendline_family.interactions import InteractionAtr, evaluate_family_interaction

from .tracker_support import interaction_family, timestamp, tracker_config


_ATR = InteractionAtr(value=10.0, method="simple_true_range_mean_v1", sample_count=3)


@pytest.mark.parametrize(
    ("role", "candle", "expected"),
    (
        (FamilyRole.SUPPORT, (100.0, 100.0, 97.0, 98.0), InteractionObservationState.CLOSE_BEYOND),
        (FamilyRole.SUPPORT, (98.5, 100.0, 98.0, 100.0), InteractionObservationState.BODY_BREACH),
        (FamilyRole.SUPPORT, (100.0, 100.0, 98.5, 100.0), InteractionObservationState.WICK_BREACH),
        (FamilyRole.SUPPORT, (102.0, 103.0, 100.5, 102.0), InteractionObservationState.IN_ZONE),
        (FamilyRole.SUPPORT, (102.5, 103.0, 102.0, 102.5), InteractionObservationState.APPROACHING),
        (FamilyRole.SUPPORT, (103.5, 104.0, 103.1, 103.5), InteractionObservationState.FAR),
        (FamilyRole.RESISTANCE, (100.0, 103.0, 100.0, 102.0), InteractionObservationState.CLOSE_BEYOND),
        (FamilyRole.RESISTANCE, (101.5, 102.0, 100.0, 100.0), InteractionObservationState.BODY_BREACH),
        (FamilyRole.RESISTANCE, (100.0, 101.5, 100.0, 100.0), InteractionObservationState.WICK_BREACH),
        (FamilyRole.RESISTANCE, (98.0, 99.5, 97.0, 98.0), InteractionObservationState.IN_ZONE),
        (FamilyRole.RESISTANCE, (97.5, 98.0, 97.0, 97.5), InteractionObservationState.APPROACHING),
        (FamilyRole.RESISTANCE, (96.5, 96.9, 96.0, 96.5), InteractionObservationState.FAR),
    ),
)
def test_role_symmetric_interaction_classifies_all_phase_d_states(
    role: FamilyRole,
    candle: tuple[float, float, float, float],
    expected: InteractionObservationState,
) -> None:
    config = tracker_config(interaction={"tolerance_atr": 0.10, "approaching_distance_atr": 0.20})
    evaluation = evaluate_family_interaction(
        interaction_family(config, timestamp(), role=role),
        timestamp=timestamp(),
        open_price=candle[0],
        high_price=candle[1],
        low_price=candle[2],
        close_price=candle[3],
        interaction_atr=_ATR,
        config=config,
        tick_size=None,
    )

    assert evaluation.observation.state is expected


@pytest.mark.parametrize("role", (FamilyRole.SUPPORT, FamilyRole.RESISTANCE))
def test_zone_boundary_equality_is_in_zone_not_a_breach(role: FamilyRole) -> None:
    config = tracker_config(interaction={"tolerance_atr": 0.10})
    candle = (100.0, 100.0, 99.0, 99.0) if role is FamilyRole.SUPPORT else (100.0, 101.0, 100.0, 101.0)
    observation = evaluate_family_interaction(
        interaction_family(config, timestamp(), role=role),
        timestamp=timestamp(),
        open_price=candle[0],
        high_price=candle[1],
        low_price=candle[2],
        close_price=candle[3],
        interaction_atr=_ATR,
        config=config,
        tick_size=None,
    ).observation

    assert observation.state is InteractionObservationState.IN_ZONE
    assert observation.wick_penetration_atr == 0.0
    assert observation.body_penetration_atr == 0.0
    assert observation.close_penetration_atr == 0.0
