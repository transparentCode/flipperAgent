from __future__ import annotations

from typing import Any

from libs.contracts.signal import FeatureVector, StreamOHLCVPayload

from apps.signal_app.pipeline.engineered import EngineeredFeaturePipeline
from apps.signal_app.pipeline.features import FeaturePipeline
from apps.signal_app.pipeline.priming import HistoricalFetcher, StartupPrimer, TimescaleStartupHistoryFetcher
from apps.signal_app.pipeline.raw_indicators import RawIndicatorPipeline


class FeatureSnapshotService:
    """Compute on-demand feature snapshots without publishing to streams."""

    def __init__(self, fetcher: HistoricalFetcher | None = None) -> None:
        self.primer = StartupPrimer(fetcher or TimescaleStartupHistoryFetcher())

    async def compute(
        self,
        *,
        asset: str,
        timeframe: str,
        lookback: int,
        bars: list[dict[str, float]] | None = None,
    ) -> FeatureVector:
        asset = asset.upper()
        history = bars_to_history(bars) if bars else await self.primer.fetch_history(
            asset,
            timeframe,
            lookback,
        )
        if not history:
            raise ValueError(f"No history available for {asset}:{timeframe}")

        raw_indicators = RawIndicatorPipeline(asset, timeframe)
        raw_indicators.prime(history)
        unprimed = raw_indicators.get_unprimed_indicator_keys()
        if unprimed and len(history) >= lookback:
            raise RuntimeError(f"Indicators failed to prime: {', '.join(unprimed)}")

        raw_features = raw_indicators.snapshot_features(history)
        if not raw_features:
            raise RuntimeError(f"No snapshot features produced for {asset}:{timeframe}")

        candle = _bar_tuple_to_candle(asset, timeframe, history[-1])
        pipeline = FeaturePipeline(
            raw_indicators=raw_indicators,
            engineered_features=EngineeredFeaturePipeline(asset, timeframe),
        )
        features = pipeline.build_features(
            candle=candle,
            raw_features=raw_features,
            append_current_bar=False,
        )
        feature_vector, _ = pipeline.build_payloads(
            asset=asset,
            timeframe=timeframe,
            candle=candle,
            features=features,
        )
        return feature_vector


def bars_to_history(bars: list[dict[str, float]] | None) -> list[tuple[float, ...]]:
    if not bars:
        return []

    history: list[tuple[float, ...]] = []
    for bar in bars:
        history.append(
            (
                float(bar["open"]),
                float(bar["high"]),
                float(bar["low"]),
                float(bar["close"]),
                float(bar["volume"]),
                _require_timestamp(bar),
                float(bar.get("taker_buy_base", 0.0)),
            )
        )
    return history


def _require_timestamp(bar: dict[str, Any]) -> float:
    if "timestamp" not in bar:
        raise ValueError("Snapshot bars require a timestamp field.")
    timestamp = float(bar["timestamp"])
    return timestamp / 1000.0 if timestamp > 1e12 else timestamp


def _bar_tuple_to_candle(
    asset: str,
    timeframe: str,
    bar: tuple[float, ...],
) -> StreamOHLCVPayload:
    return StreamOHLCVPayload(
        symbol=asset,
        timeframe=timeframe,
        timestamp=float(bar[5]),
        open=float(bar[0]),
        high=float(bar[1]),
        low=float(bar[2]),
        close=float(bar[3]),
        volume=float(bar[4]),
        taker_buy_base=float(bar[6]) if len(bar) > 6 else 0.0,
        bar_closed=True,
    )
