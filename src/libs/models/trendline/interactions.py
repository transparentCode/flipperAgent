"""Phase-D causal interaction zones and single-confirmed-bar evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

import pandas as pd

from .configuration.contracts import ResolvedTrendlineFamilyConfig
from .contracts import (
    CandleDirection,
    ContractValidationError,
    FamilyInteractionObservation,
    FamilyRole,
    InteractionObservationState,
    InteractionZone,
    TrendlineFamilyState,
    deterministic_id,
    require_utc,
)


INTERACTION_ATR_METHOD = "simple_true_range_mean_v1"
INTERACTION_ZONE_POLICY = "atr_tick_floor_v1"
_CONTACT_STATES = frozenset(
    {
        InteractionObservationState.IN_ZONE,
        InteractionObservationState.WICK_BREACH,
        InteractionObservationState.BODY_BREACH,
        InteractionObservationState.CLOSE_BEYOND,
    }
)


@dataclass(frozen=True)
class InteractionAtr:
    value: float
    method: str
    sample_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise ContractValidationError("interaction ATR value must be numeric")
        value = float(self.value)
        if not math.isfinite(value) or value <= 0.0:
            raise ContractValidationError("interaction ATR must be finite and positive")
        if not isinstance(self.method, str) or not self.method:
            raise ContractValidationError("interaction ATR method must be non-empty")
        if isinstance(self.sample_count, bool) or not isinstance(self.sample_count, int) or self.sample_count < 1:
            raise ContractValidationError("interaction ATR sample_count must be a positive integer")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class InteractionEvaluation:
    observation: FamilyInteractionObservation
    bars_since_touch: int
    breach_increment: int

    def __post_init__(self) -> None:
        if not isinstance(self.observation, FamilyInteractionObservation):
            raise ContractValidationError("interaction evaluation requires a canonical observation")
        if isinstance(self.bars_since_touch, bool) or not isinstance(self.bars_since_touch, int) or self.bars_since_touch < 0:
            raise ContractValidationError("bars_since_touch must be a non-negative integer")
        if self.breach_increment not in {0, 1}:
            raise ContractValidationError("breach_increment must be zero or one")


@dataclass(frozen=True)
class _ZoneBuild:
    zone: InteractionZone
    atr_half_width: float
    tick_half_width: float | None
    tick_floor_applied: bool


def calculate_interaction_atr(ohlcv: pd.DataFrame, *, window: int) -> InteractionAtr:
    """Compute the interaction-owned causal simple true-range mean."""

    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ContractValidationError("interaction ATR window must be an integer >= 1")
    if not isinstance(ohlcv, pd.DataFrame) or len(ohlcv) < 2:
        raise ContractValidationError("at least two confirmed bars are required for interaction ATR")
    required = {"high", "low", "close"}
    if required.difference(ohlcv.columns):
        raise ContractValidationError("interaction ATR requires high, low, and close columns")
    try:
        high = ohlcv["high"].astype(float).to_list()
        low = ohlcv["low"].astype(float).to_list()
        close = ohlcv["close"].astype(float).to_list()
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("interaction ATR inputs must be numeric") from exc
    if any(not math.isfinite(value) for value in high + low + close):
        raise ContractValidationError("interaction ATR inputs must be finite")
    true_ranges = [high[0] - low[0]]
    for index in range(1, len(ohlcv)):
        true_ranges.append(
            max(
                high[index] - low[index],
                abs(high[index] - close[index - 1]),
                abs(low[index] - close[index - 1]),
            )
        )
    samples = true_ranges[-window:]
    return InteractionAtr(
        value=sum(samples) / len(samples),
        method=INTERACTION_ATR_METHOD,
        sample_count=len(samples),
    )


def build_interaction_zone(
    family: TrendlineFamilyState,
    *,
    timestamp: datetime,
    interaction_atr: InteractionAtr,
    config: ResolvedTrendlineFamilyConfig,
    tick_size: float | None,
) -> _ZoneBuild:
    """Build a symmetric zone around the unchanged representative geometry."""

    if not isinstance(family, TrendlineFamilyState):
        raise ContractValidationError("interaction zone requires TrendlineFamilyState")
    if not isinstance(interaction_atr, InteractionAtr):
        raise ContractValidationError("interaction zone requires InteractionAtr")
    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("interaction zone requires ResolvedTrendlineFamilyConfig")
    observed = require_utc(timestamp, field_name="interaction timestamp")
    if family.asset != config.asset or family.timeframe != config.timeframe:
        raise ContractValidationError("interaction family/config identity mismatch")
    normalized_tick_size = validate_tick_size(tick_size)
    atr_half_width = interaction_atr.value * config.interaction.tolerance_atr
    tick_half_width = (
        None
        if normalized_tick_size is None
        else normalized_tick_size * config.interaction.minimum_zone_ticks
    )
    half_width = max(atr_half_width, tick_half_width or 0.0)
    center = family.representative.value_at(observed)
    return _ZoneBuild(
        zone=InteractionZone(
            line_id=family.family_id,
            timestamp=observed,
            center_price=center,
            lower_price=center - half_width,
            upper_price=center + half_width,
            width_atr=half_width / interaction_atr.value,
            policy_name=INTERACTION_ZONE_POLICY,
        ),
        atr_half_width=atr_half_width,
        tick_half_width=tick_half_width,
        tick_floor_applied=tick_half_width is not None and tick_half_width >= atr_half_width,
    )


def evaluate_family_interaction(
    family: TrendlineFamilyState,
    *,
    timestamp: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    interaction_atr: InteractionAtr,
    config: ResolvedTrendlineFamilyConfig,
    tick_size: float | None,
) -> InteractionEvaluation:
    """Classify one confirmed candle with explicit role-symmetric precedence."""

    if family.current_role not in {FamilyRole.SUPPORT, FamilyRole.RESISTANCE}:
        raise ContractValidationError("interaction evidence requires SUPPORT or RESISTANCE family")
    open_, high, low, close = _candle_values(
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
    )
    zone_build = build_interaction_zone(
        family,
        timestamp=timestamp,
        interaction_atr=interaction_atr,
        config=config,
        tick_size=tick_size,
    )
    zone = zone_build.zone
    state, wick, body, close_penetration = _classify_state(
        role=family.current_role,
        open_price=open_,
        high_price=high,
        low_price=low,
        close_price=close,
        zone=zone,
        atr=interaction_atr.value,
        approaching_distance_atr=config.interaction.approaching_distance_atr,
    )
    close_location = 0.5 if high == low else (close - low) / (high - low)
    payload: dict[str, Any] = {
        "family_id": family.family_id,
        "role": family.current_role,
        "timestamp": zone.timestamp,
        "state": state,
        "exact_line_price": zone.center_price,
        "zone": zone,
        "interaction_atr": interaction_atr.value,
        "interaction_atr_method": interaction_atr.method,
        "interaction_atr_sample_count": interaction_atr.sample_count,
        "distance_to_line_atr": abs(close - zone.center_price) / interaction_atr.value,
        "distance_to_zone_atr": max(abs(close - zone.center_price) - (zone.upper_price - zone.center_price), 0.0)
        / interaction_atr.value,
        "wick_penetration_atr": wick,
        "body_penetration_atr": body,
        "close_penetration_atr": close_penetration,
        "candle_direction": _candle_direction(open_, close),
        "close_location": close_location,
        "tick_size": validate_tick_size(tick_size),
        "minimum_zone_ticks": config.interaction.minimum_zone_ticks,
        "atr_half_width": zone_build.atr_half_width,
        "tick_half_width": zone_build.tick_half_width,
        "tick_floor_applied": zone_build.tick_floor_applied,
        "close_price": close,
    }
    observation = FamilyInteractionObservation(
        observation_id=deterministic_id("family-interaction-observation", payload),
        **payload,
    )
    contact = observation.state in _CONTACT_STATES
    return InteractionEvaluation(
        observation=observation,
        bars_since_touch=0 if contact else family.bars_since_touch + 1,
        breach_increment=int(
            observation.state
            in {InteractionObservationState.BODY_BREACH, InteractionObservationState.CLOSE_BEYOND}
        ),
    )


def _classify_state(
    *,
    role: FamilyRole,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    zone: InteractionZone,
    atr: float,
    approaching_distance_atr: float,
) -> tuple[InteractionObservationState, float, float, float]:
    if role is FamilyRole.SUPPORT:
        boundary = zone.lower_price
        wick = max(boundary - low_price, 0.0) / atr
        body = max(boundary - min(open_price, close_price), 0.0) / atr
        close = max(boundary - close_price, 0.0) / atr
        close_beyond = close_price < boundary
        body_breach = min(open_price, close_price) < boundary
        wick_breach = low_price < boundary
    else:
        boundary = zone.upper_price
        wick = max(high_price - boundary, 0.0) / atr
        body = max(max(open_price, close_price) - boundary, 0.0) / atr
        close = max(close_price - boundary, 0.0) / atr
        close_beyond = close_price > boundary
        body_breach = max(open_price, close_price) > boundary
        wick_breach = high_price > boundary
    if close_beyond:
        return InteractionObservationState.CLOSE_BEYOND, wick, body, close
    if body_breach:
        return InteractionObservationState.BODY_BREACH, wick, body, close
    if wick_breach:
        return InteractionObservationState.WICK_BREACH, wick, body, close
    if low_price <= zone.upper_price and high_price >= zone.lower_price:
        return InteractionObservationState.IN_ZONE, 0.0, 0.0, 0.0
    range_distance = _range_distance_to_zone(low_price, high_price, zone)
    if range_distance <= approaching_distance_atr * atr:
        return InteractionObservationState.APPROACHING, 0.0, 0.0, 0.0
    return InteractionObservationState.FAR, 0.0, 0.0, 0.0


def _range_distance_to_zone(low_price: float, high_price: float, zone: InteractionZone) -> float:
    if high_price < zone.lower_price:
        return zone.lower_price - high_price
    if low_price > zone.upper_price:
        return low_price - zone.upper_price
    return 0.0


def _candle_values(
    *,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> tuple[float, float, float, float]:
    values = {
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
    }
    normalized: dict[str, float] = {}
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractValidationError(f"interaction candle {name} must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ContractValidationError(f"interaction candle {name} must be finite")
        normalized[name] = number
    if normalized["high"] < normalized["low"]:
        raise ContractValidationError("interaction candle high cannot be below low")
    if normalized["high"] < normalized["open"] or normalized["high"] < normalized["close"]:
        raise ContractValidationError("interaction candle high cannot be below open or close")
    if normalized["low"] > normalized["open"] or normalized["low"] > normalized["close"]:
        raise ContractValidationError("interaction candle low cannot be above open or close")
    return normalized["open"], normalized["high"], normalized["low"], normalized["close"]


def _candle_direction(open_price: float, close_price: float) -> CandleDirection:
    if close_price > open_price:
        return CandleDirection.BULLISH
    if close_price < open_price:
        return CandleDirection.BEARISH
    return CandleDirection.NEUTRAL


def validate_tick_size(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError("tick_size must be numeric when supplied")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ContractValidationError("tick_size must be finite and positive when supplied")
    return normalized
