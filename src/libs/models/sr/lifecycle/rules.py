"""Pure, side-aware SR lifecycle predicates."""

from __future__ import annotations

from libs.models.sr.config.models import LifecycleConfig
from libs.models.sr.domain.contracts import ClosedBar, ZoneDefinition, ZoneSide


def touches_zone(
    definition: ZoneDefinition,
    bar: ClosedBar,
    config: LifecycleConfig,
) -> bool:
    """Return whether a closed bar overlaps the ATR-expanded zone."""

    touch_distance = (
        config.touch_tolerance_atr * definition.atr_at_creation
    )
    lower = definition.geometry.lower_bound
    upper = definition.geometry.upper_bound
    return (
        bar.high >= lower - touch_distance
        and bar.low <= upper + touch_distance
    )


def breaches_zone(
    definition: ZoneDefinition,
    bar: ClosedBar,
    config: LifecycleConfig,
) -> bool:
    """Return whether a closed bar strictly breaches a side threshold."""

    break_distance = (
        config.break_buffer_atr * definition.atr_at_creation
    )
    if definition.side is ZoneSide.SUPPORT:
        return bar.close < definition.geometry.lower_bound - break_distance
    return bar.close > definition.geometry.upper_bound + break_distance


__all__ = ["breaches_zone", "touches_zone"]
