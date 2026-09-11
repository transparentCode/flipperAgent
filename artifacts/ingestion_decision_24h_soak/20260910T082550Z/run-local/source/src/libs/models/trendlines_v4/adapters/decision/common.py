"""State and context mechanics shared by the V1 and V2 Decision views."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from math import isfinite
from typing import Any

from apps.decision_app.storage.state_codec import (
    decode_state_payload,
    encode_state_payload,
)
from libs.contracts.decision import (
    DecisionContext,
    ModelRequestContext,
    require_utc,
)
from libs.models.trendlines_v4.engine.types import (
    HISTORY_CAPACITY_BARS,
    TrendlineBar,
    TrendlineGeometry,
)

TRENDLINES_STATE_SCHEMA_VERSION = "trendlines.state.v1"
_STATE_KEYS = frozenset(
    {"schema_version", "asset", "timeframe", "last_market_as_of", "bars"}
)


def _finite_positive_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    return result


def _validate_request_context(context: ModelRequestContext) -> None:
    if not isinstance(context, ModelRequestContext):
        raise TypeError("context must be a ModelRequestContext")
    if context.trigger_timeframe != context.decision_timeframe:
        raise ValueError("Trendlines requires matching trigger and decision timeframes")
    if context.trigger_mode != "on_bar_close":
        raise ValueError("Trendlines requires on_bar_close trigger mode")


def _validate_decision_context(context: DecisionContext) -> None:
    if not isinstance(context, DecisionContext):
        raise TypeError("context must be a DecisionContext")
    _validate_request_context(context)
    bar = context.decision_bar
    if bar is None:
        raise ValueError("Trendlines evaluation requires a decision bar")
    if not context.decision_bar_closed or not bar.closed:
        raise ValueError("Trendlines accepts closed decision bars only")
    if bar.timeframe != context.decision_timeframe:
        raise ValueError("decision bar timeframe must match decision timeframe")
    if bar.market_as_of != context.market_as_of:
        raise ValueError("decision bar cutoff must match context")
    if bar.bar_close_at != context.market_as_of:
        raise ValueError("closed decision bar must close at market_as_of")


def _decode_state(
    state_snapshot: object | None,
    context: ModelRequestContext,
) -> tuple[TrendlineBar, ...]:
    if state_snapshot is None:
        return ()
    if not isinstance(state_snapshot, str):
        raise TypeError("Trendlines state_snapshot must be an encoded state string")
    decoded = decode_state_payload(state_snapshot)
    if not isinstance(decoded, Mapping) or set(decoded) != _STATE_KEYS:
        raise ValueError("Trendlines state has an invalid schema")
    if decoded["schema_version"] != TRENDLINES_STATE_SCHEMA_VERSION:
        raise ValueError("Trendlines state schema_version is unsupported")
    if decoded["asset"] != context.asset:
        raise ValueError("Trendlines state asset does not match context")
    if decoded["timeframe"] != context.decision_timeframe:
        raise ValueError("Trendlines state timeframe does not match context")
    last_market_as_of = decoded["last_market_as_of"]
    if not isinstance(last_market_as_of, datetime):
        raise TypeError("Trendlines state last_market_as_of is invalid")
    require_utc(last_market_as_of, field_name="Trendlines state last_market_as_of")
    encoded_bars = decoded["bars"]
    if not isinstance(encoded_bars, tuple) or not encoded_bars:
        raise ValueError("Trendlines state bars must be a non-empty tuple")
    if len(encoded_bars) > HISTORY_CAPACITY_BARS:
        raise ValueError("Trendlines state exceeds the 300-bar capacity")
    bars: list[TrendlineBar] = []
    for index, encoded_bar in enumerate(encoded_bars):
        if not isinstance(encoded_bar, tuple) or len(encoded_bar) != 5:
            raise ValueError(f"Trendlines state bar {index} is invalid")
        closed_at, open_, high, low, close = encoded_bar
        if not isinstance(closed_at, datetime):
            raise TypeError(f"Trendlines state bar {index} timestamp is invalid")
        require_utc(closed_at, field_name=f"Trendlines state bar {index} timestamp")
        prices = (open_, high, low, close)
        if any(
            isinstance(value, bool)
            or not isinstance(value, float)
            or not isfinite(value)
            or value <= 0
            for value in prices
        ):
            raise ValueError(f"Trendlines state bar {index} prices are invalid")
        bar = TrendlineBar(closed_at, open_, high, low, close)
        if bars and bars[-1].closed_at >= bar.closed_at:
            raise ValueError("Trendlines state bars must be strictly increasing")
        bars.append(bar)
    if bars[-1].closed_at != last_market_as_of:
        raise ValueError("Trendlines state last cutoff must equal its final bar")
    return tuple(bars)


def _encode_state(context: DecisionContext, bars: Sequence[TrendlineBar]) -> str:
    return encode_state_payload(
        {
            "schema_version": TRENDLINES_STATE_SCHEMA_VERSION,
            "asset": context.asset,
            "timeframe": context.decision_timeframe,
            "last_market_as_of": context.market_as_of,
            "bars": tuple(
                (bar.closed_at, bar.open, bar.high, bar.low, bar.close) for bar in bars
            ),
        }
    )


def _line_value(line: TrendlineGeometry | None) -> Mapping[str, Any] | None:
    if line is None:
        return None
    return {
        "side": line.side,
        "start_anchor_at": line.start_anchor_at,
        "start_anchor_price": line.start_anchor_price,
        "end_anchor_at": line.end_anchor_at,
        "end_anchor_price": line.end_anchor_price,
        "slope_per_bar": line.slope_per_bar,
        "projected_price_at_market_as_of": line.projected_price_at_market_as_of,
        "post_anchor_body_crossed": line.post_anchor_body_crossed,
        "post_anchor_body_cross_count": line.post_anchor_body_cross_count,
        "projection_positive": line.projection_positive,
    }


def _to_trendline_bar(context: DecisionContext) -> TrendlineBar:
    bar = context.decision_bar
    if bar is None:
        raise ValueError("Trendlines evaluation requires a decision bar")
    return TrendlineBar(
        closed_at=context.market_as_of,
        open=_finite_positive_float(bar.open, field_name="open"),
        high=_finite_positive_float(bar.high, field_name="high"),
        low=_finite_positive_float(bar.low, field_name="low"),
        close=_finite_positive_float(bar.close, field_name="close"),
    )


__all__ = [
    "HISTORY_CAPACITY_BARS",
    "TRENDLINES_STATE_SCHEMA_VERSION",
    "_decode_state",
    "_encode_state",
    "_finite_positive_float",
    "_line_value",
    "_to_trendline_bar",
    "_validate_decision_context",
    "_validate_request_context",
]
