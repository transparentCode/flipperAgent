from __future__ import annotations

import pandas as pd
import pytest

from libs.models.trendline_family.pivots import CausalFractalPivotExtractor, PivotExtractionStatus

from .support import candidate_ohlcv


def test_pivot_is_unavailable_before_its_confirmation_bar() -> None:
    frame = candidate_ohlcv()
    extractor = CausalFractalPivotExtractor(left_bars=1, right_bars=1)

    before_confirmation = extractor.extract(frame, observed_at=frame.index[2].to_pydatetime())
    after_confirmation = extractor.extract(frame, observed_at=frame.index[3].to_pydatetime())

    assert before_confirmation.status is PivotExtractionStatus.NO_CONFIRMED_PIVOTS
    assert [(pivot.kind, pivot.index, pivot.confirmation_index) for pivot in after_confirmation.pivots] == [
        ("low", 2, 3)
    ]
    assert after_confirmation.pivots[0].timestamp == frame.index[2].to_pydatetime()
    assert after_confirmation.pivots[0].confirmation_time == frame.index[3].to_pydatetime()


def test_fractal_left_and_right_windows_control_their_owned_stage() -> None:
    frame = candidate_ohlcv()
    frame.loc[frame.index[1], "low"] = 6.0

    left_one = CausalFractalPivotExtractor(left_bars=1, right_bars=1).extract(
        frame,
        observed_at=frame.index[-1].to_pydatetime(),
    )
    left_two = CausalFractalPivotExtractor(left_bars=2, right_bars=1).extract(
        frame,
        observed_at=frame.index[-1].to_pydatetime(),
    )
    unmodified = candidate_ohlcv()
    right_two_early = CausalFractalPivotExtractor(left_bars=1, right_bars=2).extract(
        unmodified,
        observed_at=unmodified.index[3].to_pydatetime(),
    )

    assert len(left_one.pivots) != len(left_two.pivots)
    assert right_two_early.status is PivotExtractionStatus.NO_CONFIRMED_PIVOTS


@pytest.mark.parametrize(
    ("kind", "highs", "lows"),
    [
        ("high", [1.0, 2.0, 2.0, 2.0, 1.0], [0.0, 0.0, 0.0, 0.0, 0.0]),
        ("low", [5.0, 5.0, 5.0, 5.0, 5.0], [3.0, 2.0, 2.0, 2.0, 3.0]),
    ],
)
def test_confirmed_plateau_pivot_never_repaints_across_rolling_prefixes(
    kind: str,
    highs: list[float],
    lows: list[float],
) -> None:
    index = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    frame = pd.DataFrame({"high": highs, "low": lows}, index=index)
    extractor = CausalFractalPivotExtractor(left_bars=1, right_bars=1)

    first = extractor.extract(frame.iloc[:3], observed_at=index[2].to_pydatetime())
    first_from_full = extractor.extract(frame, observed_at=index[2].to_pydatetime())
    published = next(pivot for pivot in first.pivots if pivot.kind == kind)
    full_prefix_pivot = next(pivot for pivot in first_from_full.pivots if pivot.kind == kind)
    identity = (
        published.pivot_id,
        published.timestamp,
        published.price,
        published.confirmation_time,
    )

    assert identity == (
        full_prefix_pivot.pivot_id,
        full_prefix_pivot.timestamp,
        full_prefix_pivot.price,
        full_prefix_pivot.confirmation_time,
    )
    assert published.index == 1
    assert published.confirmation_index == 2
    for end in (4, 5):
        rolling = extractor.extract(frame.iloc[:end], observed_at=index[end - 1].to_pydatetime())
        preserved = next(pivot for pivot in rolling.pivots if pivot.pivot_id == published.pivot_id)
        assert identity == (
            preserved.pivot_id,
            preserved.timestamp,
            preserved.price,
            preserved.confirmation_time,
        )
