from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.detection.causal_swing_salience import (
    SwingSalienceState,
    detect_causal_swing_salience,
)
from libs.models.sr.domain import ClosedBar, ContractValidationError, SRStateKey, ZoneSide


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
        SRStateKey("venue", "asset", "12h"),
        str(index),
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=12 * index),
        open_,
        high,
        low,
        close,
        atr,
    )


def test_equal_prefix_stays_unseeded_and_prefix_replay_is_stable() -> None:
    bars = (
        _bar(0, high=10, low=9, open_=9.5, close=10, atr=2),
        _bar(1, high=11, low=9, open_=10, close=10, atr=2),
        _bar(2, high=12, low=9, open_=10, close=11, atr=2),
        _bar(3, high=11, low=8, open_=10, close=10, atr=3),
        _bar(4, high=10, low=7, open_=9, close=9, atr=4),
        _bar(5, high=10, low=8, open_=8.5, close=10, atr=5),
    )
    full = detect_causal_swing_salience(bars)
    assert detect_causal_swing_salience(bars[:3]) == ()
    assert detect_causal_swing_salience(bars[:4]) == full[:1]
    assert detect_causal_swing_salience(bars) == full
    assert full[0].state_before is SwingSalienceState.SEEK_HIGH
    assert full[0].state_after is SwingSalienceState.SEEK_LOW


def test_new_extreme_replaces_and_equal_extreme_keeps_earliest() -> None:
    bars = (
        _bar(0, high=10, low=8, open_=9, close=9, atr=2),
        _bar(1, high=12, low=9, open_=10, close=11, atr=2),
        _bar(2, high=13, low=9, open_=11, close=12, atr=3),
        _bar(3, high=13, low=8, open_=12, close=11, atr=4),
    )
    swing = detect_causal_swing_salience(bars)[0]
    assert (swing.extreme_index, swing.confirmation_index) == (2, 3)
    assert swing.raw_salience_atr == pytest.approx((13 - 11) / 3)


def test_zero_wick_confirms_and_transitions_without_candidate() -> None:
    bars = (
        _bar(0, high=10, low=9, open_=9.5, close=10, atr=2),
        _bar(1, high=12, low=10, open_=10, close=12, atr=2),
        _bar(2, high=11, low=9, open_=10, close=11, atr=3),
        _bar(3, high=10, low=8, open_=9, close=9, atr=4),
        _bar(4, high=10, low=8, open_=8, close=10, atr=5),
    )
    swings = detect_causal_swing_salience(bars)
    assert swings[0].side is ZoneSide.RESISTANCE
    assert swings[0].candidate is None
    assert swings[0].raw_salience_atr > 0
    assert swings[1].side is ZoneSide.SUPPORT
    assert swings[1].candidate is not None


def test_support_mirror_uses_extreme_atr_and_confirmation_atr() -> None:
    bars = (
        _bar(0, high=11, low=10, open_=10.5, close=10, atr=2),
        _bar(1, high=10, low=7, open_=9, close=8, atr=2),
        _bar(2, high=9, low=8, open_=8, close=9, atr=4),
    )
    swing = detect_causal_swing_salience(bars)[0]
    assert swing.side is ZoneSide.SUPPORT
    assert swing.extreme_atr == 2
    assert swing.raw_salience_atr == pytest.approx((9 - 7) / 2)
    assert swing.candidate is not None
    assert swing.candidate.atr_at_creation == 4


def test_invalid_bar_container_fails_closed() -> None:
    with pytest.raises(ContractValidationError, match="tuple"):
        detect_causal_swing_salience([])  # type: ignore[arg-type]
