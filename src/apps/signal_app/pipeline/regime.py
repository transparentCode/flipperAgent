from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
import math
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


class _UnavailableTrendlineFamilyShadowProducer:
    """Preserve enabled-shadow diagnostics when its optional module is unavailable."""

    min_bars = 0

    def __init__(self, *, error_type: str, error_reason: str) -> None:
        self.error_type = error_type
        self.error_reason = error_reason

    def analyze(self, ohlcv: pd.DataFrame, **_: Any) -> dict[str, Any]:
        del ohlcv
        return _minimal_shadow_failure_payload(
            error_type=self.error_type,
            error_reason=self.error_reason,
            state_advanced=False,
        )


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
        trendline_family_shadow: Any | None = None,
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
        self.trendline_family_shadow = trendline_family_shadow
        self.l2_reader = l2_reader or _load_latest_l2_features
        self._price_history: list[PriceBar] = []
        self._trendline_family_history: list[dict[str, float]] = []
        self._trendline_family_history_error: str | None = None
        self._trendline_family_history_revision = 0
        self._trendline_family_processed_revision = -1
        self._trendline_family_last_payload: dict[str, Any] | None = None
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
        price_history = [_bar_tuple_to_price_bar(bar) for bar in history]
        trendline_family_history: list[dict[str, float]] = []
        trendline_family_history_error: str | None = None
        if self.trendline_family_shadow is not None:
            for bar in history:
                try:
                    family_bar = _bar_tuple_to_trendline_family_bar(bar)
                except ValueError:
                    trendline_family_history_error = "invalid_shadow_timestamp"
                    break
                if (
                    trendline_family_history
                    and family_bar["timestamp"] <= trendline_family_history[-1]["timestamp"]
                ):
                    trendline_family_history_error = "non_monotonic_shadow_timestamp"
                trendline_family_history.append(family_bar)
        self._price_history = price_history
        self._trendline_family_history = trendline_family_history
        self._trendline_family_history_error = trendline_family_history_error
        if self.trendline_family_shadow is not None:
            self._trendline_family_history_revision += 1
            self._trendline_family_processed_revision = -1
            self._trendline_family_last_payload = None
        self._trim_history()
        self._classification_cache = None
        self._classification_cache_bar_count = 0

    def append_bar(self, bar_data: dict[str, float], *, timestamp: float | None = None) -> None:
        shadow_timestamp = None
        if self.trendline_family_shadow is not None:
            shadow_timestamp = _normalize_shadow_timestamp(timestamp)
        price_bar = _normalize_price_bar(bar_data)
        family_bar = None
        if shadow_timestamp is not None:
            family_bar = {**price_bar, "timestamp": shadow_timestamp}

        # Validate all inputs before either history advances.
        self._price_history.append(price_bar)
        if family_bar is not None:
            if (
                self._trendline_family_history
                and family_bar["timestamp"] <= self._trendline_family_history[-1]["timestamp"]
            ):
                self._trendline_family_history_error = "non_monotonic_shadow_timestamp"
            self._trendline_family_history.append(family_bar)
            self._trendline_family_history_revision += 1
        self._trim_history()

    async def enrich(self, features: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(features)
        # This namespace is producer-owned output and must never become RegimeV2 input.
        enriched.pop("trendline_family_shadow", None)
        self._attach_regime_snapshot(enriched)
        await self._attach_regime_classification(enriched)
        self._attach_regime_v2(enriched)
        self._attach_trendline_family_shadow(enriched)
        return enriched

    def refresh_trendline_family_shadow(self, features: dict[str, Any]) -> dict[str, Any]:
        """Attach one newly appended confirmed shadow bar after active evaluation."""

        self._attach_trendline_family_shadow(features)
        return features

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

    def _attach_trendline_family_shadow(self, features: dict[str, Any]) -> None:
        """Append shadow evidence after active RegimeV2 output is already fixed."""

        if self.trendline_family_shadow is None:
            return
        if self._trendline_family_history_error is not None:
            payload = _shadow_failure_payload(
                error_type="family_contract_error",
                error_reason=self._trendline_family_history_error,
                state_advanced=False,
            )
            self._cache_trendline_family_payload(payload)
            features["trendline_family_shadow"] = payload
            return
        if (
            self._trendline_family_processed_revision == self._trendline_family_history_revision
            and self._trendline_family_last_payload is not None
        ):
            features["trendline_family_shadow"] = _cached_shadow_payload(
                self._trendline_family_last_payload
            )
            return
        try:
            frame = _trendline_family_frame(self._trendline_family_history)
            observed_at = None if frame.empty else frame.index[-1].to_pydatetime()
            payload = self.trendline_family_shadow.analyze(
                frame,
                observed_at=observed_at,
            )
            self._cache_trendline_family_payload(payload)
            features["trendline_family_shadow"] = payload
        except Exception as exc:
            logger.warning(
                "Trendline-family shadow attachment failed for %s:%s",
                self.asset,
                self.timeframe,
                exc_info=True,
            )
            payload = _shadow_failure_payload(
                error_type="unexpected_error",
                error_reason=exc.__class__.__name__,
                state_advanced=False,
            )
            self._cache_trendline_family_payload(payload)
            features["trendline_family_shadow"] = payload

    def _cache_trendline_family_payload(self, payload: Mapping[str, Any]) -> None:
        self._trendline_family_last_payload = dict(payload)
        self._trendline_family_processed_revision = self._trendline_family_history_revision

    def _trim_history(self) -> None:
        if len(self._price_history) > self.max_history:
            self._price_history = self._price_history[-self.max_history :]
        if len(self._trendline_family_history) > self.max_history:
            self._trendline_family_history = self._trendline_family_history[-self.max_history :]


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
        from libs.models.regime_v2.adapters.feature_producer import RegimeV2FeatureProducer

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


def _create_trendline_family_shadow(
    asset: str,
    timeframe: str,
    *,
    config_resolver: FeatureProducerConfigResolver | None = None,
) -> Any | None:
    resolver = config_resolver or FeatureProducerConfigResolver()
    try:
        shadow_config = resolver.resolve(asset, timeframe, "TrendlineFamilyShadow")
    except Exception:
        logger.warning(
            "Trendline-family shadow config resolution failed for %s:%s",
            asset,
            timeframe,
            exc_info=True,
        )
        return _UnavailableTrendlineFamilyShadowProducer(
            error_type="config_resolution_error",
            error_reason="config_resolution_failure",
        )
    if _shadow_config_is_disabled(shadow_config):
        return None
    try:
        (
            FailedTrendlineFamilyShadowProducer,
            TrendlineFamilyFeatureProducer,
            TrendlineFamilyShadowConfig,
        ) = _load_trendline_family_shadow_adapter()
    except Exception:
        logger.warning(
            "Trendline-family shadow adapter import failed for %s:%s",
            asset,
            timeframe,
            exc_info=True,
        )
        return _UnavailableTrendlineFamilyShadowProducer(
            error_type="config_resolution_error",
            error_reason="shadow_adapter_import_failure",
        )
    try:
        typed_config = TrendlineFamilyShadowConfig.from_mapping(shadow_config)
    except ValueError:
        logger.warning(
            "Trendline-family shadow config is invalid for %s:%s",
            asset,
            timeframe,
            exc_info=True,
        )
        return FailedTrendlineFamilyShadowProducer(
            error_type="config_resolution_error",
            error_reason="invalid_shadow_config",
        )

    try:
        return TrendlineFamilyFeatureProducer(
            asset,
            timeframe,
            shadow_config=typed_config,
        )
    except Exception:
        logger.warning(
            "TrendlineFamilyFeatureProducer construction failed for %s:%s",
            asset,
            timeframe,
            exc_info=True,
        )
        return FailedTrendlineFamilyShadowProducer(
            error_type="config_resolution_error",
            error_reason="shadow_adapter_construction_failure",
        )


def _load_trendline_family_shadow_adapter() -> tuple[Any, Any, Any]:
    """Import the optional family adapter only after explicit enablement."""

    from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
        FailedTrendlineFamilyShadowProducer,
        TrendlineFamilyFeatureProducer,
        TrendlineFamilyShadowConfig,
    )

    return (
        FailedTrendlineFamilyShadowProducer,
        TrendlineFamilyFeatureProducer,
        TrendlineFamilyShadowConfig,
    )


def _shadow_config_is_disabled(shadow_config: Any) -> bool:
    if shadow_config is None:
        return True
    if not isinstance(shadow_config, Mapping):
        return False
    if "enabled" not in shadow_config:
        return True
    return shadow_config["enabled"] is False

async def _load_latest_l2_features(asset: str) -> dict[str, Any] | None:
    reader = TimescaleReader(DBPoolManager.get_reader_pool())
    return await reader.get_latest_l2_features(asset)


def _bar_tuple_to_price_bar(bar: BarTuple) -> PriceBar:
    return _normalize_price_bar(
        {
            "open": bar[0],
            "high": bar[1],
            "low": bar[2],
            "close": bar[3],
            "volume": bar[4],
        }
    )


def _bar_tuple_to_trendline_family_bar(bar: BarTuple) -> dict[str, float]:
    return {
        **_bar_tuple_to_price_bar(bar),
        "timestamp": _normalize_shadow_timestamp(bar[5]),
    }


def _trendline_family_frame(history: Sequence[Mapping[str, float]]) -> pd.DataFrame:
    """Build a UTC confirmed-bar frame only for the independent shadow model."""

    frame = pd.DataFrame(list(history))
    if frame.empty or "timestamp" not in frame.columns:
        return frame
    timestamps = pd.to_numeric(frame.pop("timestamp"), errors="coerce")
    if timestamps.isna().any() or not timestamps.map(math.isfinite).all():
        return pd.DataFrame()
    seconds = timestamps.where(timestamps.abs() < 1e12, timestamps / 1000.0)
    frame.index = pd.to_datetime(seconds, unit="s", utc=True)
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        return pd.DataFrame()
    return frame


def _normalize_price_bar(bar_data: Mapping[str, Any]) -> PriceBar:
    """Validate all numeric OHLCV fields before mutating pipeline histories."""

    try:
        values = {
            field: float(bar_data[field])
            for field in ("open", "high", "low", "close", "volume")
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("bar_data must contain numeric OHLCV values") from exc
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("bar_data OHLCV values must be finite")
    return values


def _normalize_shadow_timestamp(timestamp: Any) -> float:
    if timestamp is None:
        raise ValueError("timestamp is required while trendline-family shadow is enabled")
    if isinstance(timestamp, bool):
        raise ValueError("trendline-family shadow timestamp must be numeric")
    try:
        value = float(timestamp)
    except (TypeError, ValueError) as exc:
        raise ValueError("trendline-family shadow timestamp must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError("trendline-family shadow timestamp must be finite")
    return value


def _shadow_failure_payload(
    *,
    error_type: str,
    error_reason: str,
    state_advanced: bool | None,
) -> dict[str, Any]:
    """Use the optional adapter's canonical failure schema when it is available."""

    try:
        from libs.models.regime_v2.adapters.trendline_family_feature_producer import (
            build_trendline_family_shadow_failure_payload,
        )
    except Exception:
        return _minimal_shadow_failure_payload(
            error_type=error_type,
            error_reason=error_reason,
            state_advanced=state_advanced,
        )
    return build_trendline_family_shadow_failure_payload(
        error_type=error_type,
        error_reason=error_reason,
        state_advanced=state_advanced,
    )


def _minimal_shadow_failure_payload(
    *,
    error_type: str,
    error_reason: str,
    state_advanced: bool | None,
) -> dict[str, Any]:
    """Last-resort payload for an unavailable optional module; no family work occurs."""

    return {
        "trendline_family_shadow_enabled": True,
        "trendline_family_valid": False,
        "trendline_family_error": error_reason,
        "trendline_family_error_type": error_type,
        "trendline_family_error_reason": error_reason,
        "trendline_family_latency_ms": 0.0,
        "trendline_family_failure_count": 1,
        "trendline_family_success_count": 0,
        "trendline_family_coverage": 0.0,
        "trendline_family_state_advanced": state_advanced,
        "trendline_family_repository_head_before": None,
        "trendline_family_repository_head_after": None,
    }


def _cached_shadow_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the latest confirmed snapshot without claiming a second update."""

    cached = dict(payload)
    if cached.get("trendline_family_valid") is True:
        cached.update(
            {
                "trendline_family_latency_ms": 0.0,
                "trendline_family_success_count": 0,
                "trendline_family_failure_count": 0,
                "trendline_family_state_advanced": False,
            }
        )
    return cached


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
