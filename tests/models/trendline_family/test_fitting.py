from __future__ import annotations

import pytest
import pandas as pd

from libs.models.trendline_family.fitting import PathfindingFitStatus, PathfindingLineFitter
from libs.models.trendline_family.pivots import (
    CausalFractalPivotExtractor,
    ConfirmedPivot,
    PivotExtractionResult,
    PivotExtractionStatus,
)

from .support import candidate_ohlcv, resolved_config


def test_pathfinding_emits_exact_support_and_resistance_geometry() -> None:
    frame = candidate_ohlcv()
    pivots = CausalFractalPivotExtractor(left_bars=1, right_bars=1).extract(
        frame,
        observed_at=frame.index[-1].to_pydatetime(),
    )
    result = PathfindingLineFitter().fit(frame, pivots, config=resolved_config())

    assert result.status is PathfindingFitStatus.VALID
    assert {line.role.value for line in result.lines} == {"SUPPORT", "RESISTANCE"}
    for line in result.lines:
        expected_kind = "low" if line.role.value == "SUPPORT" else "high"
        assert {pivot.kind for pivot in line.anchor_pivots} == {expected_kind}
        for pivot in line.anchor_pivots:
            assert line.geometry.value_at(pivot.timestamp) == pytest.approx(pivot.price, abs=1e-12)


def test_minimum_pivots_controls_pathfinding_admission() -> None:
    frame = candidate_ohlcv()
    pivots = CausalFractalPivotExtractor(left_bars=1, right_bars=1).extract(
        frame,
        observed_at=frame.index[-1].to_pydatetime(),
    )
    result = PathfindingLineFitter().fit(
        frame,
        pivots,
        config=resolved_config(min_pivots_per_side=4),
    )

    assert result.status is PathfindingFitStatus.INSUFFICIENT_PIVOTS
    assert result.lines == ()


def test_pathfinding_reports_no_valid_paths_when_all_segments_cross_candle_bodies() -> None:
    frame = candidate_ohlcv()
    frame.loc[:, "low"] = 0.0
    frame.loc[:, "open"] = 0.0
    frame.loc[:, "close"] = 1.0
    frame.loc[:, "high"] = 10.0
    frame.loc[frame.index[2], ["low", "open", "close"]] = (1.0, 1.0, 2.0)
    frame.loc[frame.index[15], ["low", "open", "close"]] = (2.0, 2.0, 3.0)
    first = ConfirmedPivot(
        pivot_id="first-low",
        index=2,
        timestamp=frame.index[2].to_pydatetime(),
        confirmation_index=3,
        confirmation_time=frame.index[3].to_pydatetime(),
        price=1.0,
        kind="low",
    )
    second = ConfirmedPivot(
        pivot_id="second-low",
        index=15,
        timestamp=frame.index[15].to_pydatetime(),
        confirmation_index=16,
        confirmation_time=frame.index[16].to_pydatetime(),
        price=2.0,
        kind="low",
    )
    pivots = PivotExtractionResult(
        status=PivotExtractionStatus.VALID,
        pivots=(first, second),
        input_bars=len(frame),
        confirmed_bars=len(frame),
    )

    result = PathfindingLineFitter().fit(frame, pivots, config=resolved_config())

    assert result.status is PathfindingFitStatus.NO_VALID_FITTED_PATHS
    assert result.lines == ()


@pytest.mark.parametrize("role", ["support", "resistance"])
def test_numeric_strings_preserve_support_and_resistance_body_validation(role: str) -> None:
    index = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    if role == "support":
        frame = pd.DataFrame(
            {
                "open": [10.0, 9.0, 10.0],
                "high": [11.0, 11.0, 11.0],
                "low": [10.0, 9.0, 10.0],
                "close": [10.0, 10.0, 10.0],
            },
            index=index,
        )
        kind, price = "low", 10.0
    else:
        frame = pd.DataFrame(
            {
                "open": [9.0, 9.0, 9.0],
                "high": [9.0, 10.0, 9.0],
                "low": [8.0, 8.0, 8.0],
                "close": [9.0, 10.0, 9.0],
            },
            index=index,
        )
        kind, price = "high", 9.0
    pivots = PivotExtractionResult(
        status="valid",
        pivots=(
            ConfirmedPivot(
                pivot_id=f"{role}-first",
                index=0,
                timestamp=index[0].to_pydatetime(),
                confirmation_index=0,
                confirmation_time=index[0].to_pydatetime(),
                price=price,
                kind=kind,
            ),
            ConfirmedPivot(
                pivot_id=f"{role}-second",
                index=2,
                timestamp=index[2].to_pydatetime(),
                confirmation_index=2,
                confirmation_time=index[2].to_pydatetime(),
                price=price,
                kind=kind,
            ),
        ),
        input_bars=len(frame),
        confirmed_bars=len(frame),
    )

    numeric_result = PathfindingLineFitter().fit(frame, pivots, config=resolved_config())
    string_result = PathfindingLineFitter().fit(frame.astype(str), pivots, config=resolved_config())

    assert numeric_result.status is PathfindingFitStatus.NO_VALID_FITTED_PATHS
    assert string_result.status is numeric_result.status
    assert string_result.lines == numeric_result.lines
