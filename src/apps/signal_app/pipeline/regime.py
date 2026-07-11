from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pandas as pd

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

from apps.signal_app.pipeline.raw_indicators import BarTuple
from apps.signal_app.settings import SignalWorkerSettings

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)

REGIME_MIN_BARS = 200
REGIME_MAX_HISTORY = 2000
REGIME_REEVAL_INTERVAL = 10

PriceBar = dict[str, float]
L2FeatureReader = Callable[[str], Awaitable[dict[str, Any] | None]]


class FeatureProducerConfigResolver:
    """Resolve feature producer config using the current models.yaml fallback chain."""

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.config_manager.register_file(CONFIG_FILE_MODELS)

    def resolve(self, asset: str, timeframe: str, producer_name: str) -> dict[str, Any] | None:
        fp_config = self.config_manager.get("feature_producers", {})
        assets_config = fp_config.get("assets", {})

        asset_node = assets_config.get(asset.upper(), {})
        default_asset_node = assets_config.get("default", {})

        tf_node = asset_node.get("timeframes", {}).get(timeframe, {})
        asset_default_tf = asset_node.get("timeframes", {}).get("default", {})
        default_tf_node = default_asset_node.get("timeframes", {}).get(timeframe, {})
        default_default_tf = default_asset_node.get("timeframes", {}).get("default", {})

        merged: dict[str, Any] = {}
        found = False
        for node in (default_default_tf, default_tf_node, asset_default_tf, tf_node):
            if producer_name in node:
                merged = _deep_merge(merged, node[producer_name])
                found = True
        return merged if found else None


class RegimeFeaturePipeline:
    """Optional regime context producer for the v2 feature assembly path."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        min_bars: int | None = None,
        max_history: int | None = None,
        reeval_interval: int | None = None,
        settings: SignalWorkerSettings | None = None,
        orchestrator: Any | None = None,
        classifier: Any | None = None,
        regime_v2: Any | None = None,
        l2_reader: L2FeatureReader | None = None,
    ) -> None:
        settings = settings or SignalWorkerSettings()
        self.asset = asset.upper()
        self.timeframe = timeframe
        base_min_bars = settings.regime_min_bars if min_bars is None else min_bars
        self.orchestrator_min_bars = _component_min_bars(orchestrator, fallback=base_min_bars)
        self.classifier_min_bars = _component_min_bars(classifier, fallback=base_min_bars)
        self.regime_v2_min_bars = _component_min_bars(regime_v2, fallback=base_min_bars)
        self.min_bars = max(
            self.orchestrator_min_bars,
            self.classifier_min_bars,
            self.regime_v2_min_bars,
        )
        self.max_history = (
            settings.regime_max_history if max_history is None else max_history
        )
        self.reeval_interval = (
            settings.regime_reeval_interval if reeval_interval is None else reeval_interval
        )
        self.orchestrator = orchestrator
        self.classifier = classifier
        self.regime_v2 = regime_v2
        self.l2_reader = l2_reader or _load_latest_l2_features
        self._price_history: list[PriceBar] = []
        self._classification_cache: dict[str, Any] | None = None
        self._classification_cache_bar_count = 0

    @classmethod
    def create_optional(
        cls,
        asset: str,
        timeframe: str,
        *,
        config_resolver: FeatureProducerConfigResolver | None = None,
        settings: SignalWorkerSettings | None = None,
    ) -> "RegimeFeaturePipeline":
        settings = settings or SignalWorkerSettings()
        resolver = config_resolver or FeatureProducerConfigResolver()
        orchestrator = _create_regime_orchestrator(asset, timeframe)
        classifier = _create_regime_classifier(
            asset,
            timeframe,
            config_resolver=resolver,
        )
        regime_v2 = _create_regime_v2(
            asset,
            timeframe,
            config_resolver=resolver,
        )
        return cls(
            asset,
            timeframe,
            settings=settings,
            orchestrator=orchestrator,
            classifier=classifier,
            regime_v2=regime_v2,
        )

    @property
    def price_history(self) -> list[PriceBar]:
        return list(self._price_history)

    def prime(self, history: Sequence[BarTuple]) -> None:
        self._price_history = [_bar_tuple_to_price_bar(bar) for bar in history]
        self._trim_history()
        self._classification_cache = None
        self._classification_cache_bar_count = 0

    def append_bar(self, bar_data: dict[str, float]) -> None:
        self._price_history.append(
            {
                "open": float(bar_data["open"]),
                "high": float(bar_data["high"]),
                "low": float(bar_data["low"]),
                "close": float(bar_data["close"]),
                "volume": float(bar_data["volume"]),
            }
        )
        self._trim_history()

    async def enrich(self, features: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(features)
        self._attach_regime_snapshot(enriched)
        await self._attach_regime_classification(enriched)
        self._attach_regime_v2(enriched)
        return enriched

    def _attach_regime_snapshot(self, features: dict[str, Any]) -> None:
        if self.orchestrator is None or len(self._price_history) < self.orchestrator_min_bars:
            return

        try:
            regime_result = self.orchestrator.analyze(pd.DataFrame(self._price_history))
            features["regime_snapshot"] = regime_features_to_dict(regime_result)
        except Exception:
            logger.warning("Regime analysis failed for current bar", exc_info=True)

    async def _attach_regime_classification(self, features: dict[str, Any]) -> None:
        if self.classifier is None or len(self._price_history) < self.classifier_min_bars:
            return

        bars_since_cache = len(self._price_history) - self._classification_cache_bar_count
        need_reeval = (
            self._classification_cache is None
            or bars_since_cache >= self.reeval_interval
        )

        if need_reeval:
            try:
                regime_output = self.classifier.batch_evaluate(pd.DataFrame(self._price_history))
                self._classification_cache = dict(regime_output.iloc[-1])
                self._classification_cache_bar_count = len(self._price_history)
            except Exception:
                logger.warning("RegimeClassification batch_evaluate failed", exc_info=True)

        if self._classification_cache is None:
            return

        last_features = dict(self._classification_cache)
        last_features["_regime_staleness_bars"] = bars_since_cache
        try:
            l2_features = await self.l2_reader(self.asset)
            if l2_features:
                last_features.update(l2_features)
        except Exception:
            logger.debug(
                "Optional L2 regime features unavailable for %s:%s",
                self.asset,
                self.timeframe,
                exc_info=True,
            )

        features["regime_classification"] = last_features

    def _attach_regime_v2(self, features: dict[str, Any]) -> None:
        if self.regime_v2 is None or len(self._price_history) < self.regime_v2_min_bars:
            return

        try:
            features["regime_v2"] = self.regime_v2.analyze(
                self._price_history,
                latest_features=features,
            )
        except Exception:
            logger.warning("RegimeV2 analysis failed for current bar", exc_info=True)

    def _trim_history(self) -> None:
        if len(self._price_history) > self.max_history:
            self._price_history = self._price_history[-self.max_history :]


def regime_features_to_dict(regime_features: Any) -> dict[str, Any]:
    return {
        "regime": regime_features.regime,
        "p_trending": regime_features.p_trending,
        "vol_percentile": regime_features.vol_percentile,
        "changepoint_prob": regime_features.changepoint_prob,
        "adaptive_period": regime_features.adaptive_period,
        "position_scale": regime_features.position_scale,
        "atr_multiplier": regime_features.atr_multiplier,
        "holding_period": regime_features.holding_period,
        "hilbert_period": regime_features.hilbert_period,
        "hilbert_confidence": regime_features.hilbert_confidence,
    }


def _create_regime_orchestrator(asset: str, timeframe: str) -> Any | None:
    try:
        from libs.regime.orchestrator import RegimeOrchestrator

        return RegimeOrchestrator.create(asset.upper(), timeframe)
    except Exception:
        logger.warning(
            "Regime orchestrator unavailable for %s:%s",
            asset,
            timeframe,
            exc_info=True,
        )
        return None


def _create_regime_classifier(
    asset: str,
    timeframe: str,
    *,
    config_resolver: FeatureProducerConfigResolver | None = None,
) -> Any | None:
    resolver = config_resolver or FeatureProducerConfigResolver()
    regime_config = resolver.resolve(asset, timeframe, "RegimeClassification")
    if not regime_config or not regime_config.get("enabled", False):
        return None

    try:
        from libs.models.regime_classification.model import RegimeClassificationModel

        return RegimeClassificationModel(
            params=regime_config.get("params") or {},
            timeframe=timeframe,
            frozen_overrides=regime_config.get("frozen_overrides") or {},
        )
    except Exception:
        logger.warning(
            "RegimeClassificationModel unavailable for %s:%s",
            asset,
            timeframe,
            exc_info=True,
        )
        return None


def _create_regime_v2(
    asset: str,
    timeframe: str,
    *,
    config_resolver: FeatureProducerConfigResolver | None = None,
) -> Any | None:
    resolver = config_resolver or FeatureProducerConfigResolver()
    regime_config = resolver.resolve(asset, timeframe, "RegimeV2")
    if not regime_config or not regime_config.get("enabled", False):
        return None

    try:
        from libs.models.regime_v2.adapters import RegimeV2FeatureProducer

        return RegimeV2FeatureProducer(
            asset,
            timeframe,
            params=regime_config.get("params") or {},
        )
    except Exception:
        logger.warning(
            "RegimeV2FeatureProducer unavailable for %s:%s",
            asset,
            timeframe,
            exc_info=True,
        )
        return None


async def _load_latest_l2_features(asset: str) -> dict[str, Any] | None:
    reader = TimescaleReader(DBPoolManager.get_reader_pool())
    return await reader.get_latest_l2_features(asset)


def _bar_tuple_to_price_bar(bar: BarTuple) -> PriceBar:
    return {
        "open": float(bar[0]),
        "high": float(bar[1]),
        "low": float(bar[2]),
        "close": float(bar[3]),
        "volume": float(bar[4]),
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _component_min_bars(component: Any | None, *, fallback: int) -> int:
    if component is None:
        return 0

    direct = getattr(component, "min_bars", None)
    if isinstance(direct, int | float) and direct > 0:
        return int(direct)

    meta = getattr(component, "meta", None)
    meta_min_bars = getattr(meta, "min_history_bars", None)
    if isinstance(meta_min_bars, int | float) and meta_min_bars > 0:
        return int(meta_min_bars)

    return max(int(fallback), 0)
