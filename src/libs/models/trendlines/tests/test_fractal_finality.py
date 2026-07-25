import numpy as np
import pandas as pd

from libs.models.trendlines.pivots import FractalPivotExtractor


def _make_frame(
    *,
    high_plateau: tuple[int, int] | None = None,
    low_plateau: tuple[int, int] | None = None,
    higher_high: int | None = None,
    lower_high: int | None = None,
    size: int = 80,
) -> pd.DataFrame:
    high = np.full(size, 101.0)
    low = np.full(size, 99.0)
    close = np.full(size, 100.0)
    if high_plateau is not None:
        start, stop = high_plateau
        high[start:stop] = 110.0
    if low_plateau is not None:
        start, stop = low_plateau
        low[start:stop] = 90.0
    if higher_high is not None:
        high[higher_high] = 115.0
    if lower_high is not None:
        high[lower_high] = 108.0
    return pd.DataFrame(
        {
            "open": close.copy(),
            "high": high,
            "low": low,
            "close": close,
        },
        index=pd.RangeIndex(size),
    )


def _pivot_tuples(pivots) -> set[tuple[str, int, float]]:
    return {
        *(
            ("high", int(index), float(value))
            for index, value in zip(pivots.high_indices, pivots.high_values)
        ),
        *(
            ("low", int(index), float(value))
            for index, value in zip(pivots.low_indices, pivots.low_values)
        ),
    }


def test_open_equal_high_plateau_is_suppressed() -> None:
    frame = _make_frame(high_plateau=(20, 28), size=28)
    pivots = FractalPivotExtractor(window_left=3, window_right=3).extract(frame)

    assert not any(20 <= int(index) <= 24 for index in pivots.high_indices)


def test_completed_equal_high_plateau_emits_midpoint_once() -> None:
    frame = _make_frame(high_plateau=(20, 28), size=80)
    extractor = FractalPivotExtractor(window_left=3, window_right=3)

    for end in range(31, len(frame) + 1):
        pivots = extractor.extract(frame.iloc[:end])
        assert 24 in {int(index) for index in pivots.high_indices}
        assert 20 not in {int(index) for index in pivots.high_indices}
        assert 27 not in {int(index) for index in pivots.high_indices}


def test_open_equal_low_plateau_is_suppressed() -> None:
    frame = _make_frame(low_plateau=(20, 28), size=28)
    pivots = FractalPivotExtractor(window_left=3, window_right=3).extract(frame)

    assert not any(20 <= int(index) <= 24 for index in pivots.low_indices)


def test_completed_equal_low_plateau_emits_midpoint_once() -> None:
    frame = _make_frame(low_plateau=(20, 28), size=80)
    extractor = FractalPivotExtractor(window_left=3, window_right=3)

    for end in range(31, len(frame) + 1):
        pivots = extractor.extract(frame.iloc[:end])
        assert 24 in {int(index) for index in pivots.low_indices}
        assert 20 not in {int(index) for index in pivots.low_indices}
        assert 27 not in {int(index) for index in pivots.low_indices}


def test_isolated_pivot_retains_right_window_delay() -> None:
    frame = _make_frame(high_plateau=(20, 21), size=40)
    extractor = FractalPivotExtractor(window_left=3, window_right=3)

    before_confirmation = extractor.extract(frame.iloc[:23])
    after_confirmation = extractor.extract(frame.iloc[:24])

    assert 20 not in {int(index) for index in before_confirmation.high_indices}
    assert 20 in {int(index) for index in after_confirmation.high_indices}


def test_higher_and_lower_follow_ons_do_not_rewrite_final_plateau() -> None:
    frame = _make_frame(
        high_plateau=(20, 28),
        higher_high=40,
        lower_high=60,
        size=80,
    )
    extractor = FractalPivotExtractor(window_left=3, window_right=3)

    for end in range(31, len(frame) + 1):
        pivots = extractor.extract(frame.iloc[:end])
        assert ("high", 24, 110.0) in _pivot_tuples(pivots)


def test_zero_right_window_waits_for_terminal_plateau_closure() -> None:
    frame = _make_frame(high_plateau=(20, 22), size=30)
    extractor = FractalPivotExtractor(window_left=3, window_right=0)

    terminal = extractor.extract(frame.iloc[:21])
    extending = extractor.extract(frame.iloc[:22])
    closed = extractor.extract(frame.iloc[:23])

    assert 20 not in {int(index) for index in terminal.high_indices}
    assert 20 not in {int(index) for index in extending.high_indices}
    assert 21 in {int(index) for index in closed.high_indices}


def test_fractal_prefix_outputs_are_append_only() -> None:
    frame = _make_frame(
        high_plateau=(20, 28),
        low_plateau=(40, 48),
        higher_high=60,
        lower_high=70,
        size=80,
    )
    extractor = FractalPivotExtractor(window_left=3, window_right=3)
    previous: set[tuple[str, int, float]] = set()

    for end in range(7, len(frame) + 1):
        current = _pivot_tuples(extractor.extract(frame.iloc[:end]))
        assert previous <= current
        previous = current
