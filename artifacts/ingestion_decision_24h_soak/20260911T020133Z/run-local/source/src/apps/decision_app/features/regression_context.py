"""App-owned Decision projection of the approved regression context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

import pandas as pd

from apps.decision_app.domain.identity import sha256_fingerprint
from apps.decision_app.features.engine import SharedFeatureContext
from apps.decision_app.features.planning import (
    FeatureHistoryRequirement,
    SharedFeatureDefinition,
)
from libs.contracts.decision import CausalBarView
from libs.regression import api as regression_api
from libs.regression.channel import STRUCTURAL_CHANNEL_ID, channel_config_fingerprint
from libs.regression.config.resolver import ConfigResolver
from libs.regression.context_snapshot import REGRESSION_CONTEXT_ID
from libs.regression.contracts.context_snapshot import RegressionContextSnapshot
from libs.regression.structural import STRUCTURAL_ESTIMATOR_ID

REGRESSION_CONTEXT_FEATURE_NAME = "REGRESSION_CONTEXT"
REGRESSION_CONTEXT_FEATURE_VERSION = "1"


def _resolve_history(
    resolver: ConfigResolver,
    lane: Any,
) -> tuple[FeatureHistoryRequirement, ...]:
    resolved = resolver.resolve(lane.asset, lane.decision_timeframe)
    return (
        FeatureHistoryRequirement(
            source="decision",
            bars=int(resolved.window_size) + 1,
        ),
    )


def _resolve_config_fingerprint(
    resolver: ConfigResolver,
    lane: Any,
) -> str:
    resolved = resolver.resolve(lane.asset, lane.decision_timeframe)
    return sha256_fingerprint(
        {
            "feature_name": REGRESSION_CONTEXT_FEATURE_NAME,
            "feature_version": REGRESSION_CONTEXT_FEATURE_VERSION,
            "context_id": REGRESSION_CONTEXT_ID,
            "structural_estimator_id": STRUCTURAL_ESTIMATOR_ID,
            "channel_id": STRUCTURAL_CHANNEL_ID,
            "source_config_hash": resolved.config_hash,
            "channel_config_hash": channel_config_fingerprint(
                resolver.structural_channel_config
            ),
        }
    )


def _float_value(value: object, *, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError(f"{field_name} must be convertible to float") from exc
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _history_to_dataframe(
    bars: Sequence[CausalBarView],
) -> pd.DataFrame:
    if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
        raise TypeError("regression history must be a bar sequence")
    if any(not isinstance(bar, CausalBarView) for bar in bars):
        raise TypeError("regression history must contain CausalBarView values")

    index = pd.DatetimeIndex([bar.bar_open_at for bar in bars])
    if index.tz is None:
        raise ValueError("regression history index must be UTC")
    return pd.DataFrame(
        {
            "open": [_float_value(bar.open, field_name="open") for bar in bars],
            "high": [_float_value(bar.high, field_name="high") for bar in bars],
            "low": [_float_value(bar.low, field_name="low") for bar in bars],
            "close": [_float_value(bar.close, field_name="close") for bar in bars],
            "volume": [_float_value(bar.volume, field_name="volume") for bar in bars],
        },
        index=index,
    )


def _require_structural_identity(
    snapshot: RegressionContextSnapshot,
    context: SharedFeatureContext,
) -> None:
    structural = snapshot.channel.structural
    if structural.asset != context.asset:
        raise ValueError("regression structural asset does not match Decision context")
    if structural.timeframe != context.decision_timeframe:
        raise ValueError(
            "regression structural timeframe does not match Decision context"
        )
    if structural.timestamp != context.decision_bar.bar_open_at:
        raise ValueError(
            "regression structural timestamp does not match Decision bar open"
        )
    if structural.observed_through != context.decision_bar.bar_close_at:
        raise ValueError(
            "regression structural cutoff does not match Decision bar close"
        )
    if structural.observed_through != context.market_as_of:
        raise ValueError(
            "regression structural cutoff does not match Decision market_as_of"
        )


def _region_value(value: object) -> str | None:
    if value is None:
        return None
    region_value = getattr(value, "value", None)
    if not isinstance(region_value, str) or not region_value:
        raise TypeError("regression region must be a non-empty enum value")
    return region_value


def _project_snapshot(snapshot: RegressionContextSnapshot) -> Mapping[str, Any]:
    structural = snapshot.channel.structural
    channel = snapshot.channel
    return {
        "context_id": snapshot.context_id,
        "source_config_hash": structural.source_config_hash,
        "channel_config_hash": channel.channel_config_hash,
        "structural": {
            "estimator_id": structural.estimator_id,
            "window_size": structural.window_size,
            "window_started_at": structural.window_started_at,
            "bar_open_at": structural.timestamp,
            "observed_through": structural.observed_through,
            "slope_log_per_hour": structural.slope_log_per_hour,
            "center_price": structural.center_price,
            "residual_mad_log": structural.residual_mad_log,
            "fit_quality": structural.fit_quality,
        },
        "channel": {
            "channel_id": channel.channel_id,
            "inner_coverage": channel.inner_coverage,
            "outer_coverage": channel.outer_coverage,
            "lower_inner_residual_log": channel.lower_inner_residual_log,
            "upper_inner_residual_log": channel.upper_inner_residual_log,
            "lower_outer_residual_log": channel.lower_outer_residual_log,
            "upper_outer_residual_log": channel.upper_outer_residual_log,
            "lower_inner_price": channel.lower_inner_price,
            "upper_inner_price": channel.upper_inner_price,
            "lower_outer_price": channel.lower_outer_price,
            "upper_outer_price": channel.upper_outer_price,
            "current_residual_log": channel.current_residual_log,
        },
        "location": {
            "region": _region_value(snapshot.region),
            "outer_channel_position": snapshot.outer_channel_position,
            "inner_width_log": snapshot.inner_width_log,
            "outer_width_log": snapshot.outer_width_log,
            "inner_width_fraction": snapshot.inner_width_fraction,
            "outer_width_fraction": snapshot.outer_width_fraction,
            "upper_outer_breach": snapshot.upper_outer_breach,
            "lower_outer_breach": snapshot.lower_outer_breach,
            "previous_region": _region_value(snapshot.previous_region),
            "reentered_from_upper_outer": snapshot.reentered_from_upper_outer,
            "reentered_from_lower_outer": snapshot.reentered_from_lower_outer,
        },
    }


def _calculator(
    resolver: ConfigResolver,
    context: Any,
) -> Mapping[str, Any]:
    if not isinstance(context, SharedFeatureContext):
        raise TypeError("regression context calculator requires SharedFeatureContext")
    if context.decision_bar_closed is not True:
        raise ValueError(
            "REGRESSION_CONTEXT requires a closed Decision bar; "
            "projected/open bars fail closed"
        )

    resolved = resolver.resolve(context.asset, context.decision_timeframe)
    required_bars = int(resolved.window_size) + 1
    bars = context.histories.get(context.decision_timeframe)
    if bars is None:
        raise ValueError("regression Decision history is unavailable")
    if len(bars) != required_bars:
        raise ValueError(
            "REGRESSION_CONTEXT requires exactly "
            f"{required_bars} Decision bars; received {len(bars)}"
        )
    if bars[-1] != context.decision_bar:
        raise ValueError("regression history does not end at the Decision bar")

    frame = _history_to_dataframe(bars)
    snapshot = regression_api.compute_regression_context(
        frame,
        context.asset,
        context.decision_timeframe,
        resolved,
        resolver.structural_channel_config,
    )
    if not isinstance(snapshot, RegressionContextSnapshot):
        raise TypeError("regression API returned an unsupported context snapshot")
    _require_structural_identity(snapshot, context)
    if snapshot.context_id != REGRESSION_CONTEXT_ID:
        raise ValueError("regression context ID does not match the approved contract")
    return _project_snapshot(snapshot)


def build_regression_context_feature_definition(
    resolver: ConfigResolver,
) -> SharedFeatureDefinition:
    """Build the local Decision feature definition around one loaded resolver."""

    if not isinstance(resolver, ConfigResolver):
        raise TypeError("resolver must be a ConfigResolver")

    return SharedFeatureDefinition(
        name=REGRESSION_CONTEXT_FEATURE_NAME,
        version=REGRESSION_CONTEXT_FEATURE_VERSION,
        calculator=lambda context: _calculator(resolver, context),
        history_requirement_resolver=lambda lane: _resolve_history(resolver, lane),
        config_fingerprint_resolver=lambda lane: _resolve_config_fingerprint(
            resolver, lane
        ),
    )


__all__ = [
    "REGRESSION_CONTEXT_FEATURE_NAME",
    "REGRESSION_CONTEXT_FEATURE_VERSION",
    "build_regression_context_feature_definition",
]
