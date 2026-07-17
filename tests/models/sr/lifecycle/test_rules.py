from __future__ import annotations

from datetime import datetime, timezone

import pytest

from libs.models.sr import (
    ClosedBar,
    ContractValidationError,
    LifecycleConfig,
    SRStateKey,
    ZoneDefinition,
    ZoneGeometry,
    ZoneSide,
)
from libs.models.sr.lifecycle.rules import breaches_zone, touches_zone


_CLOSED_AT = datetime(2026, 7, 14, 12, 1, tzinfo=timezone.utc)


def _key() -> SRStateKey:
    return SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")


def _config(
    *, touch_tolerance_atr: float = 0.5, break_buffer_atr: float = 0.5
) -> LifecycleConfig:
    return LifecycleConfig(
        touch_tolerance_atr=touch_tolerance_atr,
        break_buffer_atr=break_buffer_atr,
        break_confirm_closes=2,
        max_age_bars=50,
    )


def _definition(
    *,
    side: ZoneSide = ZoneSide.SUPPORT,
    center: float = 100.0,
    half_width: float = 5.0,
    atr_at_creation: float = 2.0,
) -> ZoneDefinition:
    return ZoneDefinition(
        state_key=_key(),
        side=side,
        geometry=ZoneGeometry(center=center, half_width=half_width),
        source="test",
        created_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        atr_at_creation=atr_at_creation,
        config_hash="a" * 64,
    )


def _bar(
    *, close: float, high: float, low: float, open: float = 100.0
) -> ClosedBar:
    return ClosedBar(
        state_key=_key(),
        bar_id="bar-1",
        closed_at=_CLOSED_AT,
        open=open,
        high=high,
        low=low,
        close=close,
        atr_at_close=1.0,
    )


def test_support_and_resistance_breach_directions_are_symmetric() -> None:
    config = _config()
    support = _definition(side=ZoneSide.SUPPORT)
    resistance = _definition(side=ZoneSide.RESISTANCE)

    assert not breaches_zone(support, _bar(close=94.0, high=100.0, low=94.0), config)
    assert breaches_zone(support, _bar(close=93.0, high=100.0, low=93.0), config)
    assert not breaches_zone(
        resistance, _bar(close=106.0, high=106.0, low=99.0), config
    )
    assert breaches_zone(
        resistance, _bar(close=107.0, high=107.0, low=99.0), config
    )


def test_touch_rejects_overflowed_atr_distance() -> None:
    definition = _definition()
    config = _config(touch_tolerance_atr=1e308)

    with pytest.raises(ContractValidationError, match="touch_distance"):
        touches_zone(
            definition,
            _bar(close=100.0, high=101.0, low=99.0),
            config,
        )


def test_touch_rejects_overflowed_expanded_bound() -> None:
    definition = _definition(center=1e308, half_width=0.0, atr_at_creation=1.0)
    config = _config(touch_tolerance_atr=1e308)

    with pytest.raises(ContractValidationError, match="expanded upper_bound"):
        touches_zone(
            definition,
            _bar(close=100.0, high=101.0, low=99.0),
            config,
        )


@pytest.mark.parametrize("side", [ZoneSide.SUPPORT, ZoneSide.RESISTANCE])
def test_breach_rejects_overflowed_atr_distance(side: ZoneSide) -> None:
    definition = _definition(side=side)
    config = _config(break_buffer_atr=1e308)

    with pytest.raises(ContractValidationError, match="break_distance"):
        breaches_zone(
            definition,
            _bar(close=100.0, high=101.0, low=99.0),
            config,
        )


def test_breach_rejects_overflowed_resistance_threshold() -> None:
    definition = _definition(
        side=ZoneSide.RESISTANCE,
        center=1e308,
        half_width=0.0,
        atr_at_creation=1.0,
    )
    config = _config(break_buffer_atr=1e308)

    with pytest.raises(
        ContractValidationError,
        match="resistance breach threshold",
    ):
        breaches_zone(
            definition,
            _bar(close=100.0, high=101.0, low=99.0),
            config,
        )


@pytest.mark.parametrize("side", [ZoneSide.SUPPORT, ZoneSide.RESISTANCE])
def test_break_threshold_equality_is_not_a_breach(side: ZoneSide) -> None:
    config = _config()
    definition = _definition(side=side)
    if side is ZoneSide.SUPPORT:
        bar = _bar(close=94.0, high=100.0, low=94.0)
    else:
        bar = _bar(close=106.0, high=106.0, low=99.0)
    assert not breaches_zone(definition, bar, config)


@pytest.mark.parametrize("side", [ZoneSide.SUPPORT, ZoneSide.RESISTANCE])
def test_touch_uses_atr_expanded_geometry(side: ZoneSide) -> None:
    config = _config()
    definition = _definition(side=side)
    assert touches_zone(
        definition, _bar(close=94.0, high=94.0, low=94.0, open=94.0), config
    )
    assert not touches_zone(
        definition,
        _bar(close=92.5, high=93.0, low=92.0, open=92.5),
        config,
    )


def test_line_geometry_uses_same_predicates() -> None:
    definition = _definition(half_width=0.0)
    config = _config(touch_tolerance_atr=0.0, break_buffer_atr=0.0)
    touch_bar = _bar(close=100.0, high=100.0, low=100.0)
    breach_bar = _bar(close=99.0, high=100.0, low=99.0)

    assert touches_zone(definition, touch_bar, config)
    assert breaches_zone(definition, breach_bar, config)


def test_predicates_do_not_mutate_inputs() -> None:
    definition = _definition()
    bar = _bar(close=93.0, high=100.0, low=93.0)
    config = _config()
    before = (definition, bar, config)

    breaches_zone(definition, bar, config)
    touches_zone(definition, bar, config)

    assert (definition, bar, config) == before
