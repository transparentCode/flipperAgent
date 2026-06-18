from __future__ import annotations

from typing import Any

from libs.contracts.signal import FeatureVector, PriceUpdate, StreamOHLCVPayload

from apps.signal_app.enrichment.valkey import ValkeySignalEnrichmentReader
from apps.signal_app.pipeline.context_namespaces import (
    TRANSPORT_CONTEXT_KEY,
    build_transport_context,
    merge_ltf_context,
)
from apps.signal_app.pipeline.engineered import EngineeredFeaturePipeline
from apps.signal_app.pipeline.raw_indicators import BarTuple, RawIndicatorPipeline
from apps.signal_app.pipeline.regime import RegimeFeaturePipeline


class FeaturePipeline:
    """Target wrapper for live and on-demand feature assembly.

    Owns the v2 bar-close feature assembly path while reusing shared feature
    libraries through narrow, injectable seams.
    """

    def __init__(
        self,
        raw_indicators: RawIndicatorPipeline | None = None,
        *,
        engineered_features: EngineeredFeaturePipeline | None = None,
        enrichment_reader: ValkeySignalEnrichmentReader | None = None,
        regime_features: RegimeFeaturePipeline | None = None,
    ) -> None:
        self.raw_indicators = raw_indicators
        self.engineered_features = engineered_features
        self.enrichment_reader = enrichment_reader
        self.regime_features = regime_features

    def process_closed_candle(
        self,
        *,
        asset: str,
        timeframe: str,
        candle: StreamOHLCVPayload,
        index_data: dict[str, dict[str, float]] | None = None,
        derivatives_data: dict[str, float] | None = None,
        ltf_context_profiles: dict[str, dict[str, Any]] | None = None,
        append_current_bar: bool = True,
    ) -> tuple[FeatureVector, PriceUpdate]:
        if self.raw_indicators is None:
            raise RuntimeError("RawIndicatorPipeline is required to process closed candles.")

        raw_features = self.raw_indicators.process_tick(_candle_to_tuple(candle))
        features = self.build_features(
            candle=candle,
            raw_features=raw_features,
            index_data=index_data,
            derivatives_data=derivatives_data,
            ltf_context_profiles=ltf_context_profiles,
            append_current_bar=append_current_bar,
        )
        return self.build_payloads(
            asset=asset,
            timeframe=timeframe,
            candle=candle,
            features=features,
        )

    async def process_closed_candle_enriched(
        self,
        *,
        asset: str,
        timeframe: str,
        candle: StreamOHLCVPayload,
        append_current_bar: bool = True,
        ltf_context_profiles: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[FeatureVector, PriceUpdate]:
        index_data: dict[str, dict[str, float]] = {}
        derivatives_data: dict[str, float] = {}
        if self.enrichment_reader is not None:
            index_data = await self.enrichment_reader.load_index_data()
            derivatives_data = await self.enrichment_reader.load_derivatives_data()

        feature_vector, price_update = self.process_closed_candle(
            asset=asset,
            timeframe=timeframe,
            candle=candle,
            index_data=index_data,
            derivatives_data=derivatives_data,
            ltf_context_profiles=ltf_context_profiles,
            append_current_bar=append_current_bar,
        )
        if self.regime_features is not None:
            feature_vector.features = await self.regime_features.enrich(feature_vector.features)
        return feature_vector, price_update

    def build_features(
        self,
        *,
        candle: StreamOHLCVPayload,
        raw_features: dict[str, Any],
        index_data: dict[str, dict[str, float]] | None = None,
        derivatives_data: dict[str, float] | None = None,
        ltf_context_profiles: dict[str, dict[str, Any]] | None = None,
        append_current_bar: bool = True,
    ) -> dict[str, Any]:
        features = merge_ltf_context(raw_features, profiles=ltf_context_profiles)
        features[TRANSPORT_CONTEXT_KEY] = build_transport_context(candle)
        bar_data = candle_bar_data(candle)
        if self.engineered_features is not None:
            features.update(
                self.engineered_features.compute(
                    features,
                    bar_data,
                    index_data=index_data,
                )
            )
        if derivatives_data:
            features.update(derivatives_data)
        if self.regime_features is not None and append_current_bar:
            self.regime_features.append_bar(bar_data)
        return features

    def build_payloads(
        self,
        *,
        asset: str,
        timeframe: str,
        candle: StreamOHLCVPayload,
        features: dict[str, Any],
    ) -> tuple[FeatureVector, PriceUpdate]:
        timestamp = normalize_timestamp_ms(candle.timestamp)
        bar_data = candle_bar_data(candle)
        feature_vector = FeatureVector(
            asset=asset,
            timeframe=timeframe,
            timestamp=timestamp,
            features=features,
            bar_data=bar_data,
        )
        price_update = PriceUpdate(
            asset=asset,
            timeframe=timeframe,
            timestamp=timestamp,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        )
        return feature_vector, price_update


def candle_bar_data(candle: StreamOHLCVPayload) -> dict[str, float]:
    return {
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "taker_buy_base": candle.taker_buy_base,
    }


def _candle_to_tuple(candle: StreamOHLCVPayload) -> BarTuple:
    return (
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
        normalize_timestamp_ms(candle.timestamp),
        candle.taker_buy_base,
    )


def normalize_timestamp_ms(timestamp: float) -> int:
    return int(timestamp * 1000) if timestamp < 1e12 else int(timestamp)
