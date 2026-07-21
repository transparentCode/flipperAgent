from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.input import ConfirmedOHLCVFrame


UTC = timezone.utc


def _frame(*, strings: bool = False) -> pd.DataFrame:
    index = pd.to_datetime(
        [
            "2024-01-01T00:00:00Z",
            "2024-01-01T01:00:00Z",
            "2024-01-01T03:00:00Z",
            "2024-01-01T04:00:00Z",
        ]
    )
    values = {
        "open": [9, 10, 10, 11],
        "high": [10, 11, 11, 12],
        "low": [8, 9, 9, 10],
        "close": [9.5, 10.5, 10.5, 11.5],
        "volume": [10, 11, 12, 13],
    }
    frame = pd.DataFrame(values, index=index)
    if strings:
        frame = frame.astype(str)
    return frame


def _build(frame: pd.DataFrame) -> ConfirmedOHLCVFrame:
    return ConfirmedOHLCVFrame.from_frame(
        frame,
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=datetime(2024, 1, 1, 5, tzinfo=UTC),
        confirmed_through=datetime(2024, 1, 1, 3, tzinfo=UTC),
    )


def _future_frame(**values: object) -> pd.DataFrame:
    defaults = {"open": [12], "high": [13], "low": [11], "close": [12.5], "volume": [14]}
    defaults.update({key: [value] for key, value in values.items()})
    return pd.DataFrame(
        defaults,
        index=pd.to_datetime(["2024-01-01T05:00:00Z"]),
    )


def test_confirmed_boundary_excludes_future_rows_and_preserves_irregular_timestamps() -> None:
    result = _build(_frame())
    assert result.row_count == 3
    assert list(result.frame.index.hour) == [0, 1, 3]
    assert result.frame.dtypes.tolist() == [np.dtype("float64")] * 5


def test_future_rows_do_not_change_fixed_prefix_identity_or_arrays() -> None:
    base = _build(_frame())
    extended = _build(pd.concat([_frame(), _future_frame()]))

    assert extended.input_identity == base.input_identity
    assert np.array_equal(extended.arrays().close, base.arrays().close)


@pytest.mark.parametrize(
    "future, label",
    [
        (_future_frame(close=np.nan), "NaN"),
        (_future_frame(high=np.inf), "infinity"),
        (_future_frame(high=10), "OHLC"),
        (_future_frame(volume=-1), "volume"),
    ],
)
def test_malformed_future_values_cannot_change_fixed_prefix(
    future: pd.DataFrame, label: str
) -> None:
    base = _build(_frame())
    result = _build(pd.concat([_frame(), future]))
    assert result.input_identity == base.input_identity, label


def test_duplicate_future_timestamps_are_outside_the_validation_boundary() -> None:
    future = pd.concat([_future_frame(), _future_frame()])
    result = _build(pd.concat([_frame(), future]))
    assert result.input_identity == _build(_frame()).input_identity


def test_out_of_order_future_timestamps_are_outside_the_validation_boundary() -> None:
    first = _future_frame()
    second = first.copy(deep=True)
    second.index = pd.to_datetime(["2024-01-01T06:00:00Z"])
    out_of_order = pd.concat([_frame(), second, first])
    result = _build(out_of_order)
    assert result.input_identity == _build(_frame()).input_identity


def test_numeric_strings_normalize_to_same_identity_and_float64_values() -> None:
    numeric = _build(_frame())
    strings = _build(_frame(strings=True))

    assert strings.input_identity == numeric.input_identity
    assert all(dtype == np.dtype("float64") for dtype in strings.frame.dtypes)
    assert np.array_equal(strings.arrays().high, numeric.arrays().high)


def test_arrays_are_read_only() -> None:
    arrays = _build(_frame()).arrays()
    assert not arrays.close.flags.writeable
    with pytest.raises(ValueError):
        arrays.close[0] = 999.0


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda frame: frame.set_axis(frame.index.tz_localize(None)), "timezone"),
        (lambda frame: frame.iloc[[1, 0, 2, 3]], "increasing"),
        (lambda frame: frame.rename(index={frame.index[1]: frame.index[0]}), "duplicates"),
        (lambda frame: frame.assign(high=[7, 11, 11, 12]), "high bounds"),
        (lambda frame: frame.assign(low=[9.5, 9, 9, 10]), "low bounds"),
        (lambda frame: frame.assign(close=["bad", 10.5, 10.5, 11.5]), "non-numeric"),
        (lambda frame: frame.assign(volume=[10, 11, np.inf, 13]), "non-finite"),
    ],
)
def test_invalid_causal_input_fails_closed(mutator, message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        _build(mutator(_frame()))


def test_non_empty_asset_timeframe_and_explicit_confirmation_are_required() -> None:
    with pytest.raises(ContractValidationError):
        ConfirmedOHLCVFrame.from_frame(
            _frame(),
            asset="",
            timeframe="4h",
            observed_at=datetime(2024, 1, 1, 5, tzinfo=UTC),
            confirmed_through=datetime(2024, 1, 1, 3, tzinfo=UTC),
        )
    with pytest.raises(ContractValidationError, match="after observed_at"):
        ConfirmedOHLCVFrame.from_frame(
            _frame(),
            asset="BTCUSDT",
            timeframe="4h",
            observed_at=datetime(2024, 1, 1, 3, tzinfo=UTC),
            confirmed_through=datetime(2024, 1, 1, 4, tzinfo=UTC),
        )
