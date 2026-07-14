from __future__ import annotations

import pytest

from libs.models.trendline_family.contracts import FamilyRole
from libs.models.trendline_family.interactions import InteractionAtr, evaluate_family_interaction

from .tracker_support import interaction_family, timestamp, tracker_config


def test_support_and_resistance_mirror_breaches_have_symmetric_penetration_metrics() -> None:
    config = tracker_config(interaction={"tolerance_atr": 0.10})
    atr = InteractionAtr(value=10.0, method="simple_true_range_mean_v1", sample_count=3)
    support = evaluate_family_interaction(
        interaction_family(config, timestamp(), role=FamilyRole.SUPPORT),
        timestamp=timestamp(),
        open_price=100.0,
        high_price=100.0,
        low_price=97.0,
        close_price=98.0,
        interaction_atr=atr,
        config=config,
        tick_size=None,
    ).observation
    resistance = evaluate_family_interaction(
        interaction_family(config, timestamp(), role=FamilyRole.RESISTANCE),
        timestamp=timestamp(),
        open_price=100.0,
        high_price=103.0,
        low_price=100.0,
        close_price=102.0,
        interaction_atr=atr,
        config=config,
        tick_size=None,
    ).observation

    assert support.wick_penetration_atr == pytest.approx(resistance.wick_penetration_atr)
    assert support.body_penetration_atr == pytest.approx(resistance.body_penetration_atr)
    assert support.close_penetration_atr == pytest.approx(resistance.close_penetration_atr)
