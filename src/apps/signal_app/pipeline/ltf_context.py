"""Shared lower-timeframe context builders and Valkey persistence."""

from __future__ import annotations

from collections.abc import Sequence
import math
import re
from statistics import fmean, pstdev
from typing import Any

from libs.common.timeframes import timeframe_to_seconds

BarTuple = tuple[float, ...]

_PROFILE_WINDOW_RE = re.compile(r"_(\d+)([mhd])$")
_UNIT_TO_SECONDS = {
    "m": 60,
    "h": 3600,
    "d": 86_400,
}


def ltf_context_storage_key(asset: str, base_timeframe: str, profile: str) -> str:
    return f"signal:ltf_context:{asset.upper()}:{base_timeframe}:{profile}"


def required_history_bars(
    profiles: Sequence[str],
    *,
    base_timeframe: str = "1m",
) -> int:
    if not profiles:
        return 0
    base_seconds = max(timeframe_to_seconds(base_timeframe), 1)
    return max(
        max(math.ceil(profile_window_seconds(profile) / base_seconds), 1)
        for profile in profiles
    )


def compute_profile_snapshots(
    *,
    profiles: Sequence[str],
    bars: Sequence[BarTuple],
    base_timeframe: str = "1m",
) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    if not profiles or not bars:
        return snapshots

    base_seconds = max(timeframe_to_seconds(base_timeframe), 1)
    for profile in profiles:
        window_bars = max(math.ceil(profile_window_seconds(profile) / base_seconds), 1)
        if len(bars) < window_bars:
            continue
        window = list(bars[-window_bars:])
        snapshot = _compute_profile(profile, window=window, base_timeframe=base_timeframe)
        if snapshot:
            snapshots[profile] = snapshot
    return snapshots


def profile_window_seconds(profile: str) -> int:
    match = _PROFILE_WINDOW_RE.search(profile.strip())
    if match is None:
        raise ValueError(f"Unsupported context profile window: {profile}")
    quantity = int(match.group(1))
    unit = match.group(2)
    return quantity * _UNIT_TO_SECONDS[unit]


class ValkeyLtfContextStore:
    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = 21_600,
    ) -> None:
        self.redis_client = redis_client
        self.ttl_seconds = max(int(ttl_seconds), 0)

    async def publish_profiles(
        self,
        *,
        asset: str,
        base_timeframe: str,
        snapshots: dict[str, dict[str, Any]],
    ) -> None:
        if self.redis_client is None or not snapshots:
            return
        for profile, snapshot in snapshots.items():
            key = ltf_context_storage_key(asset, base_timeframe, profile)
            mapping = {
                key: _encode_value(value)
                for key, value in snapshot.items()
            }
            await self.redis_client.hset(key, mapping=mapping)
            if self.ttl_seconds > 0:
                await self.redis_client.expire(key, self.ttl_seconds)


def _compute_profile(
    profile: str,
    *,
    window: Sequence[BarTuple],
    base_timeframe: str,
) -> dict[str, Any]:
    if profile.startswith("volatility_"):
        return _volatility_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    if profile.startswith("breakout_pressure_"):
        return _breakout_pressure_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    if profile.startswith("return_dispersion_"):
        return _return_dispersion_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    if profile.startswith("volume_pressure_"):
        return _volume_pressure_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    if profile.startswith("regime_alignment_"):
        return _regime_alignment_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    raise ValueError(f"Unsupported lower-timeframe context profile: {profile}")


def _returns(window: Sequence[BarTuple]) -> list[float]:
    closes = [float(bar[3]) for bar in window]
    returns: list[float] = []
    for previous, current in zip(closes, closes[1:], strict=False):
        if previous == 0:
            returns.append(0.0)
            continue
        returns.append((current - previous) / previous)
    return returns


def _base_snapshot(window: Sequence[BarTuple], *, base_timeframe: str, profile: str) -> dict[str, Any]:
    opens = [float(bar[0]) for bar in window]
    highs = [float(bar[1]) for bar in window]
    lows = [float(bar[2]) for bar in window]
    closes = [float(bar[3]) for bar in window]
    volumes = [float(bar[4]) for bar in window]
    taker_buy_bases = [float(bar[6]) if len(bar) > 6 else 0.0 for bar in window]
    start_close = closes[0]
    end_close = closes[-1]
    return_pct = ((end_close - start_close) / start_close) if start_close else 0.0
    high_max = max(highs)
    low_min = min(lows)
    range_pct = ((high_max - low_min) / start_close) if start_close else 0.0
    return {
        "profile": profile,
        "base_timeframe": base_timeframe,
        "window_bars": len(window),
        "window_seconds": len(window) * timeframe_to_seconds(base_timeframe),
        "as_of_timestamp": float(window[-1][5]),
        "open": opens[0],
        "high": high_max,
        "low": low_min,
        "close": end_close,
        "return_pct": return_pct,
        "range_pct": range_pct,
        "volume": sum(volumes),
        "taker_buy_base": sum(taker_buy_bases),
    }


def _volatility_snapshot(
    window: Sequence[BarTuple],
    *,
    base_timeframe: str,
    profile: str,
) -> dict[str, Any]:
    snapshot = _base_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    returns = _returns(window)
    snapshot["value"] = pstdev(returns) if len(returns) >= 2 else 0.0
    snapshot["mean_return"] = fmean(returns) if returns else 0.0
    return snapshot


def _breakout_pressure_snapshot(
    window: Sequence[BarTuple],
    *,
    base_timeframe: str,
    profile: str,
) -> dict[str, Any]:
    snapshot = _base_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    window_high = snapshot["high"]
    window_low = snapshot["low"]
    close = snapshot["close"]
    price_range = window_high - window_low
    if price_range <= 0:
        snapshot["value"] = 0.0
    else:
        snapshot["value"] = ((close - window_low) / price_range) * 2.0 - 1.0
    snapshot["breakout_distance_pct"] = ((window_high - close) / close) if close else 0.0
    return snapshot


def _return_dispersion_snapshot(
    window: Sequence[BarTuple],
    *,
    base_timeframe: str,
    profile: str,
) -> dict[str, Any]:
    snapshot = _base_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    returns = _returns(window)
    snapshot["value"] = pstdev(returns) if len(returns) >= 2 else 0.0
    snapshot["abs_mean_return"] = fmean(abs(value) for value in returns) if returns else 0.0
    return snapshot


def _volume_pressure_snapshot(
    window: Sequence[BarTuple],
    *,
    base_timeframe: str,
    profile: str,
) -> dict[str, Any]:
    snapshot = _base_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    volume = float(snapshot["volume"])
    taker_buy_base = float(snapshot["taker_buy_base"])
    if volume <= 0:
        snapshot["buy_ratio"] = 0.0
        snapshot["value"] = 0.0
        return snapshot
    buy_ratio = taker_buy_base / volume
    snapshot["buy_ratio"] = buy_ratio
    snapshot["value"] = (buy_ratio * 2.0) - 1.0
    return snapshot


def _regime_alignment_snapshot(
    window: Sequence[BarTuple],
    *,
    base_timeframe: str,
    profile: str,
) -> dict[str, Any]:
    snapshot = _base_snapshot(window, base_timeframe=base_timeframe, profile=profile)
    closes = [float(bar[3]) for bar in window]
    if len(closes) < 4:
        snapshot["value"] = 0.0
        snapshot["short_return_pct"] = 0.0
        snapshot["long_return_pct"] = snapshot["return_pct"]
        return snapshot
    midpoint = max(len(closes) // 4, 1)
    short_start = closes[-(midpoint + 1)]
    short_end = closes[-1]
    short_return = ((short_end - short_start) / short_start) if short_start else 0.0
    long_return = float(snapshot["return_pct"])
    if short_return == 0.0 or long_return == 0.0:
        alignment = 0.0
    elif math.copysign(1.0, short_return) == math.copysign(1.0, long_return):
        alignment = 1.0
    else:
        alignment = -1.0
    snapshot["value"] = alignment
    snapshot["short_return_pct"] = short_return
    snapshot["long_return_pct"] = long_return
    return snapshot


def _encode_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


__all__ = [
    "BarTuple",
    "ValkeyLtfContextStore",
    "compute_profile_snapshots",
    "ltf_context_storage_key",
    "profile_window_seconds",
    "required_history_bars",
]
