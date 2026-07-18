from __future__ import annotations

from dataclasses import MISSING
from datetime import datetime, timedelta, timezone
import math

import pytest

from libs.models.sr import ClosedBar, ContractValidationError, SRStateKey, ZoneSide
from libs.models.sr.detection import (
    DisplacementOriginConfig,
    detect_displacement_origins,
)


_T0 = datetime(2024, 7, 1, tzinfo=timezone.utc)


def _key(symbol: str = "TAOUSDT") -> SRStateKey:
    return SRStateKey(venue="binance_usdm", symbol=symbol, timeframe="1d")


def _config(**overrides: object) -> DisplacementOriginConfig:
    values: dict[str, object] = {
        "displacement_atr": 1.0,
        "minimum_body_fraction": 0.60,
        "structure_lookback_bars": 5,
        "base_search_bars": 3,
    }
    values.update(overrides)
    return DisplacementOriginConfig(**values)  # type: ignore[arg-type]


def _bar(
    index: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    atr: float = 1.0,
    state_key: SRStateKey | None = None,
    bar_id: str | None = None,
    closed_at: datetime | None = None,
) -> ClosedBar:
    return ClosedBar(
        state_key=state_key or _key(),
        bar_id=bar_id or f"bar-{index}",
        closed_at=closed_at or _T0 + timedelta(days=index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        atr_at_close=atr,
    )


def _bullish_bars() -> tuple[ClosedBar, ...]:
    return (
        _bar(0, open_price=100, high=103, low=99, close=101),
        _bar(1, open_price=102, high=104, low=100, close=101),
        _bar(2, open_price=100, high=102, low=98, close=99),
        _bar(3, open_price=99, high=101, low=97, close=100),
        _bar(4, open_price=101, high=102, low=98, close=100),
        _bar(5, open_price=100, high=107, low=99, close=106),
    )


def _bearish_bars() -> tuple[ClosedBar, ...]:
    return (
        _bar(0, open_price=100, high=103, low=99, close=101),
        _bar(1, open_price=101, high=104, low=100, close=103),
        _bar(2, open_price=102, high=105, low=101, close=104),
        _bar(3, open_price=103, high=106, low=102, close=104),
        _bar(4, open_price=104, high=107, low=103, close=105),
        _bar(5, open_price=106, high=107, low=97, close=98),
    )


def test_bullish_displacement_creates_support_from_nearest_bearish_base() -> None:
    bars = _bullish_bars()

    candidates = detect_displacement_origins(bars, _config())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.side is ZoneSide.SUPPORT
    assert candidate.geometry.lower_bound == 98.0
    assert candidate.geometry.upper_bound == 102.0
    assert candidate.formed_at == bars[4].closed_at
    assert candidate.available_at == bars[5].closed_at
    assert candidate.atr_at_creation == bars[4].atr_at_close
    assert candidate.source == "displacement_origin_v2"


def test_bearish_displacement_creates_resistance_from_nearest_bullish_base() -> None:
    bars = _bearish_bars()

    candidates = detect_displacement_origins(bars, _config())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.side is ZoneSide.RESISTANCE
    assert candidate.geometry.lower_bound == 103.0
    assert candidate.geometry.upper_bound == 107.0
    assert candidate.formed_at == bars[4].closed_at
    assert candidate.available_at == bars[5].closed_at


@pytest.mark.parametrize(
    "mutator",
    [
        lambda bars: bars[:5]
        + (_bar(5, open_price=100, high=107, low=99, close=100),),
        lambda bars: bars[:5]
        + (_bar(5, open_price=100, high=107, low=99, close=100.9),),
        lambda bars: bars[:5]
        + (_bar(5, open_price=100, high=107, low=99, close=103),),
        lambda bars: bars[:5]
        + (_bar(5, open_price=100, high=107, low=99, close=102),),
    ],
)
def test_each_displacement_condition_failure_emits_nothing(
    mutator: object,
) -> None:
    bars = _bullish_bars()

    assert detect_displacement_origins(mutator(bars), _config()) == ()  # type: ignore[operator]


@pytest.mark.parametrize(
    "distance, base_index",
    [(1, 4), (2, 3), (3, 2)],
)
def test_nearest_opposing_base_is_selected_at_each_allowed_distance(
    distance: int, base_index: int
) -> None:
    bars = list(_bullish_bars())
    for index in range(2, 5):
        bars[index] = _bar(
            index,
            open_price=100,
            high=102,
            low=98,
            close=101,
        )
    bars[base_index] = _bar(
        base_index,
        open_price=101,
        high=102 + distance,
        low=98 - distance,
        close=100,
    )

    candidates = detect_displacement_origins(tuple(bars), _config())

    assert len(candidates) == 1
    assert candidates[0].formed_at == bars[base_index].closed_at


def test_doji_and_missing_opposing_base_emit_nothing() -> None:
    bars = list(_bullish_bars())
    for index in range(2, 5):
        bars[index] = _bar(
            index,
            open_price=100,
            high=102,
            low=98,
            close=100,
        )

    assert detect_displacement_origins(tuple(bars), _config()) == ()


def test_zero_width_confirmation_or_base_emits_nothing() -> None:
    base_zero = list(_bullish_bars())
    object.__setattr__(base_zero[4], "high", 100.0)
    object.__setattr__(base_zero[4], "low", 100.0)
    confirmation_zero = list(_bullish_bars())
    confirmation_zero[5] = _bar(5, open_price=100, high=100, low=100, close=100)

    assert detect_displacement_origins(tuple(base_zero), _config()) == ()
    assert detect_displacement_origins(tuple(confirmation_zero), _config()) == ()


def test_prefix_causality_and_full_replay_parity() -> None:
    prefix = _bullish_bars()
    suffix = (
        _bar(6, open_price=106, high=108, low=104, close=107),
        _bar(7, open_price=107, high=109, low=105, close=108),
    )

    prefix_candidates = detect_displacement_origins(prefix, _config())
    full_candidates = detect_displacement_origins(prefix + suffix, _config())

    assert full_candidates[: len(prefix_candidates)] == prefix_candidates


def test_exact_thresholds_pass_and_structural_ties_reject() -> None:
    exact = list(_bullish_bars())
    exact[5] = _bar(5, open_price=103, high=105, low=103, close=105)
    tied = list(exact)
    tied[5] = _bar(5, open_price=102, high=104, low=102, close=104)

    config = _config(displacement_atr=2.0)
    assert len(detect_displacement_origins(tuple(exact), config)) == 1
    assert detect_displacement_origins(tuple(tied), config) == ()


@pytest.mark.parametrize(
    "bars, expected",
    [
        ((object(),), "exactly ClosedBar"),
        (
            (_bullish_bars()[0], _bullish_bars()[1], _bullish_bars()[2], _bullish_bars()[3], _bullish_bars()[4], _bullish_bars()[5].__class__),
            "exactly ClosedBar",
        ),
        (
            _bullish_bars()[:5]
            + (_bar(5, open_price=100, high=107, low=99, close=106, state_key=_key("BTCUSDT")),),
            "state_key",
        ),
        (
            _bullish_bars()[:5]
            + (_bar(5, open_price=100, high=107, low=99, close=106, bar_id="bar-4"),),
            "duplicate bar_id",
        ),
        (
            _bullish_bars()[:5]
            + (_bar(5, open_price=100, high=107, low=99, close=106, closed_at=_T0 + timedelta(days=4)),),
            "strictly increasing",
        ),
    ],
)
def test_invalid_input_metadata_fails_closed(bars: tuple[object, ...], expected: str) -> None:
    with pytest.raises(ContractValidationError, match=expected):
        detect_displacement_origins(bars, _config())  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [math.inf, math.nan])
def test_nonfinite_prior_atr_fails_closed(value: float) -> None:
    bars = list(_bullish_bars())
    object.__setattr__(bars[4], "atr_at_close", value)

    with pytest.raises(ContractValidationError, match="atr_at_close must be finite"):
        detect_displacement_origins(tuple(bars), _config())


def test_config_is_strict_and_has_no_numeric_defaults() -> None:
    assert (
        DisplacementOriginConfig.__dataclass_fields__["displacement_atr"].default
        is MISSING
    )
    with pytest.raises(ContractValidationError, match="minimum_body_fraction"):
        _config(minimum_body_fraction=1.1)
    with pytest.raises(ContractValidationError, match="structure_lookback_bars"):
        _config(structure_lookback_bars=True)
    with pytest.raises(ContractValidationError, match="config must be exactly"):
        detect_displacement_origins(_bullish_bars(), object())  # type: ignore[arg-type]
