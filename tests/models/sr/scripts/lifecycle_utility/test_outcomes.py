from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide
from libs.models.sr.scripts.lifecycle_utility.outcomes import (
    build_resolution_outcome,
    compute_wilder_atr_by_bar,
)


def test_atr_and_outcome_start_are_causal(make_bars, make_event, lifecycle_config):
    bars = make_bars(40, datetime(2024, 6, 15, tzinfo=timezone.utc))
    event = make_event(
        seed="causal",
        event_at=bars[16].closed_at,
        event_bar_id=bars[16].bar_id,
        anchor_close=bars[16].close,
    )
    atr_values = compute_wilder_atr_by_bar(bars, period=14)
    outcome = build_resolution_outcome(event, bars, config=lifecycle_config, null_cell=None, atr_values=atr_values)
    assert atr_values[16] is not None
    assert outcome.reference_atr_14 == atr_values[16]
    assert outcome.anchor_close == bars[16].close
    assert outcome.outcome_start_bar_id == bars[17].bar_id
    assert outcome.outcome_end_at == bars[26].closed_at
    assert outcome.event_at == bars[16].closed_at


def test_outcome_excursions_flip_with_effective_side(make_bars, make_event, lifecycle_config):
    bars = make_bars(40, datetime(2024, 6, 15, tzinfo=timezone.utc))
    support_event = make_event(
        seed="support",
        event_class="FALSE_BREAKOUT",
        side=ZoneSide.SUPPORT,
        event_at=bars[16].closed_at,
        event_bar_id=bars[16].bar_id,
        anchor_close=bars[16].close,
    )
    resistance_event = make_event(
        seed="resistance",
        event_class="BREAK_CONFIRMED",
        side=ZoneSide.SUPPORT,
        event_at=bars[16].closed_at,
        event_bar_id=bars[16].bar_id,
        anchor_close=bars[16].close,
    )
    atr_values = compute_wilder_atr_by_bar(bars, period=14)
    support = build_resolution_outcome(support_event, bars, config=lifecycle_config, null_cell=None, atr_values=atr_values)
    resistance = build_resolution_outcome(resistance_event, bars, config=lifecycle_config, null_cell=None, atr_values=atr_values)
    window = bars[17:27]
    maximum = max(bar.high for bar in window)
    minimum = min(bar.low for bar in window)
    atr = atr_values[16]
    assert atr is not None
    assert support.favorable_excursion_atr == max(0.0, (maximum - support.anchor_close) / atr)
    assert resistance.favorable_excursion_atr == max(0.0, (resistance.anchor_close - minimum) / atr)
    assert support.effective_side is ZoneSide.SUPPORT
    assert resistance.effective_side is ZoneSide.RESISTANCE


def test_horizon_crossing_event_fold_is_right_censored(make_bars, make_event, lifecycle_config):
    bars = make_bars(50, datetime(2024, 9, 1, tzinfo=timezone.utc))
    event = make_event(
        seed="fold-boundary",
        event_at=bars[28].closed_at,
        event_bar_id=bars[28].bar_id,
        anchor_close=bars[28].close,
    )
    outcome = build_resolution_outcome(event, bars, config=lifecycle_config, null_cell=None)
    assert outcome.right_censored is True
    assert outcome.completed is False
    assert outcome.outcome_end_at is None
    assert outcome.directional_quality_atr is None
    assert outcome.null_control_count == 0


def test_horizon_ending_exactly_at_fold_end_is_right_censored(make_bars, make_event, lifecycle_config):
    bars = make_bars(40, datetime(2024, 9, 1, tzinfo=timezone.utc))
    event = make_event(
        seed="exact-fold-end",
        event_at=bars[19].closed_at,
        event_bar_id=bars[19].bar_id,
        anchor_close=bars[19].close,
    )
    assert bars[29].closed_at == datetime(2024, 10, 1, tzinfo=timezone.utc)
    outcome = build_resolution_outcome(event, bars, config=lifecycle_config, null_cell=None)
    assert outcome.right_censored is True
    assert outcome.completed is False


def test_anchor_and_bar_misalignment_fail_closed(make_bars, make_event, lifecycle_config):
    bars = make_bars(40, datetime(2024, 6, 15, tzinfo=timezone.utc))
    event = make_event(
        seed="bad-anchor",
        event_at=bars[16].closed_at,
        event_bar_id=bars[16].bar_id,
        anchor_close=bars[16].close,
    )
    with pytest.raises(ContractValidationError):
        build_resolution_outcome(replace(event, anchor_close=event.anchor_close + 1.0), bars, config=lifecycle_config, null_cell=None)
    with pytest.raises(ContractValidationError):
        build_resolution_outcome(replace(event, event_at=event.event_at + timedelta(hours=1)), bars, config=lifecycle_config, null_cell=None)
