"""Pure, side-aware SR lifecycle predicates."""

from __future__ import annotations

import math

from libs.models.sr.config.models import LifecycleConfig
from libs.models.sr.domain.bars import ClosedBar
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.zones import ZoneDefinition, ZoneSide


def _finite(value: float, *, field_name: str) -> float:
    if not math.isfinite(value):
        raise ContractValidationError(
            f"{field_name} must be finite after ATR scaling"
        )
    return value


def touches_zone(
    definition: ZoneDefinition,
    bar: ClosedBar,
    config: LifecycleConfig,
) -> bool:
    """Return whether a closed bar overlaps the ATR-expanded zone."""

    touch_distance = _finite(
        config.touch_tolerance_atr * definition.atr_at_creation,
        field_name="touch_distance",
    )
    lower = _finite(definition.geometry.lower_bound, field_name="lower_bound")
    upper = _finite(definition.geometry.upper_bound, field_name="upper_bound")
    expanded_lower = _finite(
        lower - touch_distance,
        field_name="expanded lower_bound",
    )
    expanded_upper = _finite(
        upper + touch_distance,
        field_name="expanded upper_bound",
    )
    return (
        bar.high >= expanded_lower
        and bar.low <= expanded_upper
    )


def breaches_zone(
    definition: ZoneDefinition,
    bar: ClosedBar,
    config: LifecycleConfig,
) -> bool:
    """Return whether a closed bar strictly breaches a side threshold."""

    break_distance = _finite(
        config.break_buffer_atr * definition.atr_at_creation,
        field_name="break_distance",
    )
    lower = _finite(definition.geometry.lower_bound, field_name="lower_bound")
    upper = _finite(definition.geometry.upper_bound, field_name="upper_bound")
    if definition.side is ZoneSide.SUPPORT:
        threshold = _finite(
            lower - break_distance,
            field_name="support breach threshold",
        )
        return bar.close < threshold
    threshold = _finite(
        upper + break_distance,
        field_name="resistance breach threshold",
    )
    return bar.close > threshold


__all__ = ["breaches_zone", "touches_zone"]
