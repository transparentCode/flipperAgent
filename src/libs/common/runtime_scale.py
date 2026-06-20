from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil
from typing import Any


@dataclass(frozen=True)
class StreamCaps:
    ohlcv_maxlen: int
    feature_stream_maxlen: int
    price_update_stream_maxlen: int
    signal_stream_maxlen: int
    order_stream_maxlen: int
    fill_stream_maxlen: int
    failure_stream_maxlen: int
    lifecycle_maxlen: int
    control_maxlen: int
    events_maxlen: int
    runtime_status_maxlen: int


@dataclass(frozen=True)
class RuntimeScaleInputs:
    asset_count: int
    runtime_timeframes_per_asset: float
    signal_pairs_per_asset: float
    strategy_pairs_per_asset: float
    stream_caps: StreamCaps


@dataclass(frozen=True)
class RuntimeScaleReport:
    asset_count: int
    runtime_timeframes_per_asset: float
    signal_pairs_per_asset: float
    strategy_pairs_per_asset: float
    ingestion_runtime_count: int
    signal_worker_count: int
    strategy_worker_count: int
    risk_worker_count: int
    execution_worker_count: int
    total_worker_count: int
    ohlcv_stream_count: int
    feature_stream_count: int
    price_update_stream_count: int
    signal_stream_count: int
    order_stream_count: int
    fill_stream_count: int
    failure_stream_count: int
    replay_entry_upper_bounds: dict[str, int]
    shared_stream_upper_bounds: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_runtime_scale(inputs: RuntimeScaleInputs) -> RuntimeScaleReport:
    asset_count = max(0, int(inputs.asset_count))
    runtime_timeframes = _scaled_count(asset_count, inputs.runtime_timeframes_per_asset)
    signal_pairs = _scaled_count(asset_count, inputs.signal_pairs_per_asset)
    strategy_pairs = _scaled_count(asset_count, inputs.strategy_pairs_per_asset)
    caps = inputs.stream_caps

    replay_entry_upper_bounds = {
        "ohlcv": runtime_timeframes * caps.ohlcv_maxlen,
        "features": signal_pairs * caps.feature_stream_maxlen,
        "price_update": signal_pairs * caps.price_update_stream_maxlen,
        "signals": strategy_pairs * caps.signal_stream_maxlen,
        "orders": asset_count * caps.order_stream_maxlen,
        "fills": asset_count * caps.fill_stream_maxlen,
        "failures": asset_count * caps.failure_stream_maxlen,
    }
    shared_stream_upper_bounds = {
        "lifecycle": caps.lifecycle_maxlen,
        "control": caps.control_maxlen,
        "events": caps.events_maxlen,
        "runtime_status": caps.runtime_status_maxlen,
    }

    return RuntimeScaleReport(
        asset_count=asset_count,
        runtime_timeframes_per_asset=inputs.runtime_timeframes_per_asset,
        signal_pairs_per_asset=inputs.signal_pairs_per_asset,
        strategy_pairs_per_asset=inputs.strategy_pairs_per_asset,
        ingestion_runtime_count=asset_count,
        signal_worker_count=signal_pairs,
        strategy_worker_count=strategy_pairs,
        risk_worker_count=asset_count,
        execution_worker_count=asset_count,
        total_worker_count=asset_count + signal_pairs + strategy_pairs + asset_count + asset_count,
        ohlcv_stream_count=runtime_timeframes,
        feature_stream_count=signal_pairs,
        price_update_stream_count=signal_pairs,
        signal_stream_count=strategy_pairs,
        order_stream_count=asset_count,
        fill_stream_count=asset_count,
        failure_stream_count=asset_count,
        replay_entry_upper_bounds=replay_entry_upper_bounds,
        shared_stream_upper_bounds=shared_stream_upper_bounds,
    )


def _scaled_count(asset_count: int, per_asset: float) -> int:
    if asset_count <= 0 or per_asset <= 0:
        return 0
    return ceil(asset_count * per_asset)

