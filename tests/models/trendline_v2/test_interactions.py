from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendline_v2.api import (
    build_trendline_interaction_bar,
    observe_trendline_family_interactions,
)
from libs.models.trendline_v2.domain import LineRole
from libs.models.trendline_v2.domain.identity import deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame
from libs.models.trendline_v2.interaction import (
    CandleDirection,
    ConfirmedInteractionBar,
    ExactLineObservationPolicy,
    LinePriceRelation,
    observe_exact_line_interactions,
)
from libs.models.trendline_v2.selection import SelectionStatus
from libs.models.trendline_v2.tracking import (
    ExactSelectedStructureTrackingPolicy,
    TrackingStatus,
    track_selected_trendlines,
)

from test_tracking_contracts import (
    BASE,
    _candidate,
    _initial_snapshot,
    _selection,
    _unavailable,
)


POLICY = ExactLineObservationPolicy()
TRACKING_POLICY = ExactSelectedStructureTrackingPolicy()
BAR_INPUT_ID = deterministic_hash("test_interaction_bar_input", {"value": 1})
NEXT_BAR_INPUT_ID = deterministic_hash("test_interaction_bar_input", {"value": 2})


def _bar(
    *,
    timestamp=None,
    available_at=None,
    source_input_identity: str = BAR_INPUT_ID,
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    open: float = 101.0,
    high: float = 105.0,
    low: float = 99.0,
    close: float = 103.0,
) -> ConfirmedInteractionBar:
    return ConfirmedInteractionBar.create(
        asset=asset,
        timeframe=timeframe,
        timestamp=timestamp or BASE + timedelta(hours=4),
        available_at=available_at or BASE + timedelta(hours=8),
        source_input_identity=source_input_identity,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=1.0,
    )


def _frame(*, include_future: bool = False, open_value: float = 101.0) -> ConfirmedOHLCVFrame:
    timestamps = [BASE, BASE + timedelta(hours=4)]
    if include_future:
        timestamps.append(BASE + timedelta(hours=8))
    data = pd.DataFrame(
        {
            "open": (100.0, open_value, 102.0)[: len(timestamps)],
            "high": (101.0, 105.0, 106.0)[: len(timestamps)],
            "low": (99.0, 99.0, 101.0)[: len(timestamps)],
            "close": (100.5, 103.0, 103.0)[: len(timestamps)],
            "volume": (1.0, 1.0, 1.0)[: len(timestamps)],
        },
        index=pd.DatetimeIndex(timestamps),
    )
    return ConfirmedOHLCVFrame.from_frame(
        data,
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=BASE + timedelta(hours=8),
        confirmed_through=BASE + timedelta(hours=4),
    )


def test_exact_timestamp_frame_extraction_and_copy_boundary() -> None:
    frame = _frame()
    bar = build_trendline_interaction_bar(
        frame, timestamp=BASE + timedelta(hours=4)
    )
    assert bar.timestamp == BASE + timedelta(hours=4)
    assert bar.available_at == frame.observed_at
    assert bar.source_input_identity == frame.input_identity
    assert bar.open == 101.0

    with pytest.raises(ContractValidationError):
        build_trendline_interaction_bar(frame, timestamp=BASE + timedelta(hours=2))

    original = frame.frame
    original.loc[BASE + timedelta(hours=4), "open"] = 999.0
    assert bar.open == 101.0


def test_same_prefix_future_rows_do_not_change_bar_identity() -> None:
    early = build_trendline_interaction_bar(
        _frame(), timestamp=BASE + timedelta(hours=4)
    )
    extended = build_trendline_interaction_bar(
        _frame(include_future=True), timestamp=BASE + timedelta(hours=4)
    )
    assert extended == early
    assert extended.bar_id == early.bar_id


@pytest.mark.parametrize(
    "bar",
    [
        _bar(asset="ETHUSDT"),
        _bar(timeframe="1h"),
        _bar(timestamp=BASE + timedelta(hours=3)),
        _bar(timestamp=BASE, available_at=BASE + timedelta(hours=4)),
        _bar(source_input_identity=_initial_snapshot().input_identity),
    ],
)
def test_observer_rejects_market_and_causal_mismatches(bar: ConfirmedInteractionBar) -> None:
    tracking = _initial_snapshot()
    with pytest.raises(ContractValidationError):
        observe_exact_line_interactions(tracking, bar, policy=POLICY)


def test_equal_tracking_timestamp_with_later_availability_is_accepted() -> None:
    tracking = _initial_snapshot()
    bar = _bar(
        timestamp=tracking.observed_at,
        available_at=tracking.observed_at + timedelta(hours=4),
    )
    snapshot = observe_exact_line_interactions(tracking, bar, policy=POLICY)
    assert snapshot.observed_at == bar.available_at


def test_one_observation_per_active_family_and_deterministic_ordering() -> None:
    selection = _selection((_candidate(), _candidate(role=LineRole.RESISTANCE)))
    tracking = track_selected_trendlines(
        selection, previous=None, policy=TRACKING_POLICY
    )
    snapshot = observe_trendline_family_interactions(
        tracking, _bar(), policy=POLICY
    )
    assert len(snapshot.observations) == len(tracking.active_families) == 2
    assert tuple(item.family_id for item in snapshot.observations) == tuple(
        sorted(family.family_id for family in tracking.active_families)
    )
    assert snapshot.diagnostics.support_observation_count == 1
    assert snapshot.diagnostics.resistance_observation_count == 1


def test_removed_families_receive_no_observation() -> None:
    first = track_selected_trendlines(
        _selection((_candidate(), _candidate(role=LineRole.RESISTANCE))),
        previous=None,
        policy=TRACKING_POLICY,
    )
    later_candidate = _candidate(observed_at=BASE + timedelta(hours=8))
    later = track_selected_trendlines(
        _selection(
            (later_candidate,),
            observed_at=later_candidate.observed_at,
            input_identity=NEXT_BAR_INPUT_ID,
        ),
        previous=first,
        policy=TRACKING_POLICY,
    )
    snapshot = observe_exact_line_interactions(
        later,
        _bar(
            timestamp=BASE + timedelta(hours=8),
            available_at=BASE + timedelta(hours=12),
            source_input_identity=BAR_INPUT_ID,
        ),
        policy=POLICY,
    )
    assert tuple(item.family_id for item in snapshot.observations) == tuple(
        family.family_id for family in later.active_families
    )
    first_ids = {family.family_id for family in first.active_families}
    later_ids = {family.family_id for family in later.active_families}
    assert first_ids - later_ids == set(later.removed_family_ids)


@pytest.mark.parametrize(
    "status",
    [SelectionStatus.SOURCE_ABSTAINED, SelectionStatus.SOURCE_FAILED],
)
def test_source_unavailable_carried_families_are_observed(status: SelectionStatus) -> None:
    first = _initial_snapshot()
    carried = track_selected_trendlines(
        _unavailable(
            status=status,
            observed_at=BASE + timedelta(hours=8),
            input_identity=NEXT_BAR_INPUT_ID,
        ),
        previous=first,
        policy=TRACKING_POLICY,
    )
    assert carried.status is TrackingStatus.SOURCE_UNAVAILABLE
    snapshot = observe_exact_line_interactions(
        carried,
        _bar(
            timestamp=BASE + timedelta(hours=8),
            available_at=BASE + timedelta(hours=12),
            source_input_identity=BAR_INPUT_ID,
        ),
        policy=POLICY,
    )
    assert len(snapshot.observations) == len(first.active_families)
    assert snapshot.source_active_family_ids == tuple(
        family.family_id for family in first.active_families
    )


def test_zero_active_family_snapshot_is_valid() -> None:
    selection = _unavailable(
        status=SelectionStatus.SOURCE_ABSTAINED,
        observed_at=BASE + timedelta(hours=4),
        input_identity=NEXT_BAR_INPUT_ID,
    )
    tracking = track_selected_trendlines(
        selection, previous=None, policy=TRACKING_POLICY
    )
    snapshot = observe_exact_line_interactions(tracking, _bar(), policy=POLICY)
    assert snapshot.source_active_family_ids == ()
    assert snapshot.observations == ()
    assert snapshot.diagnostics.observation_count == 0


def test_projection_and_raw_distance_formula_are_exact_for_both_roles() -> None:
    selection = _selection((_candidate(), _candidate(role=LineRole.RESISTANCE)))
    tracking = track_selected_trendlines(
        selection, previous=None, policy=TRACKING_POLICY
    )
    bar = _bar()
    snapshot = observe_exact_line_interactions(tracking, bar, policy=POLICY)
    for observation in snapshot.observations:
        line = tracking.active_families[
            tuple(family.family_id for family in tracking.active_families).index(
                observation.family_id
            )
        ].current_candidate.geometry.value_at(bar.timestamp)
        assert observation.exact_line_price == line
        assert observation.open_minus_line == bar.open - line
        assert observation.high_minus_line == bar.high - line
        assert observation.low_minus_line == bar.low - line
        assert observation.close_minus_line == bar.close - line


def test_intersection_boundaries_close_relation_and_flat_direction() -> None:
    tracking = _initial_snapshot()
    line = tracking.active_families[0].current_candidate.geometry.value_at(
        BASE + timedelta(hours=4)
    )
    bar = _bar(open=line, high=line, low=line, close=line)
    observation = observe_exact_line_interactions(
        tracking, bar, policy=POLICY
    ).observations[0]
    assert observation.wick_intersects_line is True
    assert observation.body_intersects_line is True
    assert observation.close_relation is LinePriceRelation.ON
    assert observation.candle_direction is CandleDirection.FLAT


def test_dependency_boundary_has_no_provider_or_legacy_interaction_imports() -> None:
    root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2" / "interaction"
    source = "\n".join(path.read_text() for path in root.glob("*.py"))
    for forbidden in (
        "trendline_family",
        "trendlines_old",
        "trendline_v2.discovery",
        "trendline_v2.selection",
        "yaml",
        "network",
        "viewer",
        "storage",
    ):
        assert forbidden not in source


def test_observer_has_no_provider_execution_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import libs.models.trendline_v2.api as api

    monkeypatch.setattr(
        api,
        "discover_trendlines",
        lambda *args, **kwargs: pytest.fail("interaction observer executed provider"),
    )
    snapshot = observe_exact_line_interactions(
        _initial_snapshot(), _bar(), policy=POLICY
    )
    assert snapshot.observations
