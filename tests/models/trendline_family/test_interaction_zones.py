from __future__ import annotations

import pytest
import pandas as pd

from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.interactions import InteractionAtr, build_interaction_zone, calculate_interaction_atr

from .tracker_support import interaction_family, timestamp, tracker_config


def test_interaction_zone_preserves_exact_line_center_and_uses_atr_width_without_tick_size() -> None:
    config = tracker_config(interaction={"tolerance_atr": 0.10})
    observed = timestamp()
    family = interaction_family(config, observed, reference_price=100.0)
    build = build_interaction_zone(
        family,
        timestamp=observed,
        interaction_atr=InteractionAtr(value=10.0, method="simple_true_range_mean_v1", sample_count=3),
        config=config,
        tick_size=None,
    )

    assert build.zone.center_price == family.representative.value_at(observed)
    assert build.zone.lower_price == pytest.approx(99.0)
    assert build.zone.upper_price == pytest.approx(101.0)
    assert build.zone.width_atr == pytest.approx(0.10)
    assert build.tick_half_width is None
    assert not build.tick_floor_applied


def test_tick_size_floor_selects_the_larger_half_width_and_is_auditable() -> None:
    config = tracker_config(interaction={"tolerance_atr": 0.10, "minimum_zone_ticks": 2})
    build = build_interaction_zone(
        interaction_family(config, timestamp()),
        timestamp=timestamp(),
        interaction_atr=InteractionAtr(value=10.0, method="simple_true_range_mean_v1", sample_count=3),
        config=config,
        tick_size=0.75,
    )

    assert build.atr_half_width == pytest.approx(1.0)
    assert build.tick_half_width == pytest.approx(1.5)
    assert build.tick_floor_applied
    assert build.zone.lower_price == pytest.approx(98.5)
    assert build.zone.upper_price == pytest.approx(101.5)


def test_zero_true_range_cannot_produce_interaction_atr() -> None:
    observed = timestamp()
    frame = pd.DataFrame(
        {"high": [100.0, 100.0], "low": [100.0, 100.0], "close": [100.0, 100.0]},
        index=pd.date_range(end=observed, periods=2, freq="h", tz="UTC"),
    )

    with pytest.raises(ContractValidationError, match="positive"):
        calculate_interaction_atr(frame, window=2)
