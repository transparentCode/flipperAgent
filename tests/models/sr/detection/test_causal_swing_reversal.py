from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.detection.causal_swing_reversal import (
    CausalSwingReversalConfig,
    SwingMode,
    detect_causal_swing_reversal_bands,
    detect_causal_swing_reversals,
)
from libs.models.sr.domain import (
    ClosedBar,
    ContractValidationError,
    SRStateKey,
    ZoneSide,
)


def _bar(
    index: int,
    *,
    high: float,
    low: float,
    open_: float,
    close: float,
    atr: float,
) -> ClosedBar:
    return ClosedBar(
        SRStateKey("venue", "asset", "1d"),
        str(index),
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
        open_,
        high,
        low,
        close,
        atr,
    )


def _bars() -> tuple[ClosedBar, ...]:
    return (
        _bar(0, high=10.0, low=9.0, open_=9.5, close=10.0, atr=2.0),
        _bar(1, high=12.0, low=10.0, open_=10.0, close=11.0, atr=2.0),
        _bar(2, high=11.0, low=8.0, open_=10.0, close=9.0, atr=10.0),
        _bar(3, high=10.0, low=7.0, open_=9.0, close=8.0, atr=3.0),
        _bar(4, high=12.0, low=8.0, open_=8.0, close=11.5, atr=3.0),
    )


def test_frozen_extreme_atr_confirms_and_confirmation_atr_owns_candidate() -> None:
    swings = detect_causal_swing_reversals(_bars(), CausalSwingReversalConfig(1.5))
    assert [item.side for item in swings] == [ZoneSide.RESISTANCE, ZoneSide.SUPPORT]
    high, low = swings
    assert (high.extreme_index, high.confirmation_index, high.extreme_atr) == (
        1,
        2,
        2.0,
    )
    assert high.candidate is not None
    assert high.candidate.atr_at_creation == 10.0
    assert high.candidate.formed_at == _bars()[1].closed_at
    assert high.candidate.available_at == _bars()[2].closed_at
    assert (low.extreme_index, low.confirmation_index) == (3, 4)


def test_prefix_causality_ties_equality_and_zero_wick_transition() -> None:
    bars = _bars()
    config = CausalSwingReversalConfig(1.5)
    full = detect_causal_swing_reversals(bars, config)
    assert detect_causal_swing_reversals(bars[:2], config) == ()
    assert detect_causal_swing_reversals(bars[:3], config) == full[:1]
    assert detect_causal_swing_reversals(bars, config) == full
    assert detect_causal_swing_reversal_bands(bars[:3], config) == (full[0].candidate,)

    zero_wick = (
        bars[0],
        _bar(1, high=12.0, low=10.0, open_=10.0, close=12.0, atr=2.0),
        bars[2],
        bars[3],
        bars[4],
    )
    zero_swings = detect_causal_swing_reversals(zero_wick, config)
    assert zero_swings[0].candidate is None
    assert [item.side for item in zero_swings] == [
        ZoneSide.RESISTANCE,
        ZoneSide.SUPPORT,
    ]
    assert [
        item.side for item in detect_causal_swing_reversal_bands(zero_wick, config)
    ] == [ZoneSide.SUPPORT]


def test_unseeded_equal_prefix_new_extreme_and_invalid_inputs_fail_closed() -> None:
    equal = (
        _bar(0, high=10.0, low=9.0, open_=9.5, close=10.0, atr=2.0),
        _bar(1, high=11.0, low=9.0, open_=9.5, close=10.0, atr=2.0),
    )
    assert detect_causal_swing_reversals(equal, CausalSwingReversalConfig(1.5)) == ()
    assert SwingMode.UNSEEDED.value == "UNSEEDED"
    with pytest.raises(ContractValidationError, match="reversal_atr"):
        CausalSwingReversalConfig(True)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError, match="tuple"):
        detect_causal_swing_reversals(list(_bars()), CausalSwingReversalConfig(1.5))  # type: ignore[arg-type]
    duplicated = _bars()[:-1] + (_bars()[0],)
    with pytest.raises(ContractValidationError, match="duplicate"):
        detect_causal_swing_reversals(duplicated, CausalSwingReversalConfig(1.5))


def test_subthreshold_and_new_or_equal_extreme_do_not_confirm_early() -> None:
    config = CausalSwingReversalConfig(1.5)
    bars = (
        _bar(0, high=10.0, low=9.0, open_=9.5, close=10.0, atr=2.0),
        _bar(1, high=12.0, low=10.0, open_=10.0, close=11.0, atr=2.0),
        _bar(2, high=12.0, low=9.0, open_=10.0, close=9.1, atr=8.0),
        _bar(3, high=11.0, low=8.0, open_=10.0, close=9.0, atr=8.0),
    )
    tied = detect_causal_swing_reversals(bars, config)
    assert [(item.extreme_index, item.confirmation_index) for item in tied] == [(1, 3)]

    new_high = (
        _bar(0, high=10.0, low=9.0, open_=9.5, close=10.0, atr=2.0),
        _bar(1, high=12.0, low=10.0, open_=10.0, close=11.0, atr=2.0),
        _bar(2, high=13.0, low=9.0, open_=11.0, close=10.0, atr=2.0),
        _bar(3, high=12.0, low=8.0, open_=11.0, close=10.0, atr=2.0),
    )
    confirmed = detect_causal_swing_reversals(new_high, config)
    assert [(item.extreme_index, item.confirmation_index) for item in confirmed] == [
        (2, 3)
    ]
