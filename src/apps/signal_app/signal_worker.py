from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from apps.signal_app.feature_manager import FeatureManager
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_TRADINGVIEW, CONFIG_FILE_MODELS
from libs.common.logging.logger_utils import bind_logger
from libs.features.engineered.manager import EngineeredFeatureManager
from libs.common.enums import SystemComponent
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import FeatureVector, PriceUpdate, StreamOHLCVPayload, valkey_encode

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


def _parse_timeframe_seconds(timeframe: str) -> int:
    """Convert a timeframe string like '1m', '4h', '1d' to seconds."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if not timeframe:
        return 60
    suffix = timeframe[-1].lower()
    try:
        value = int(timeframe[:-1])
    except (ValueError, IndexError):
        return 60
    return value * units.get(suffix, 60)


_DEFAULT_TV_INDICES = ["CRYPTOCAP:BTC.D", "CRYPTOCAP:TOTAL2", "CRYPTOCAP:TOTAL3"]
_STARTUP_PRIMING_RETRY_DELAY_SEC = 1
_STARTUP_WARMING_RETRY_DELAY_SEC = 5

# Minimum bars required before regime analysis can run (HMM min_train_bars default)
_REGIME_MIN_BARS = 200
# Maximum price history buffer size
_REGIME_MAX_HISTORY = 2000
# Re-run full batch_evaluate every N new bars (avoid per-bar HMM refit)
_REGIME_REEVAL_INTERVAL = 10


def _import_regime_orchestrator():
    """Lazily import RegimeOrchestrator."""
    from libs.regime.orchestrator import RegimeOrchestrator
    return RegimeOrchestrator


def _resolve_tv_index_keys(config: ConfigManager) -> list[str]:
    """Resolve short index names from runtime TradingView config."""
    configured = config.get("tradingview.indices", _DEFAULT_TV_INDICES)
    if not isinstance(configured, list) or not configured:
        configured = _DEFAULT_TV_INDICES
    return [str(sym).split(":")[-1] for sym in configured]


def _regime_features_to_dict(rf) -> dict[str, Any]:
    """Serialize RegimeFeatures to a JSON-safe flat dict for Valkey transport."""
    return {
        "regime": rf.regime,
        "p_trending": rf.p_trending,
        "vol_percentile": rf.vol_percentile,
        "changepoint_prob": rf.changepoint_prob,
        "adaptive_period": rf.adaptive_period,
        "position_scale": rf.position_scale,
        "atr_multiplier": rf.atr_multiplier,
        "holding_period": rf.holding_period,
        "hilbert_period": rf.hilbert_period,
        "hilbert_confidence": rf.hilbert_confidence,
    }


class SignalWorker(BaseStreamConsumer):
    def __init__(self, asset: str, timeframe: str, db_fetcher=None):
        super().__init__(
            stream_key=f"stream:ohlcv:{asset.lower()}:{timeframe}",
            group_name="signal_app_group",
            consumer_name=f"signal_worker_{asset}_{timeframe}",
            batch_size=10,
            block_ms=1000,
        )
        self.asset = asset
        self.timeframe = timeframe
        self._config = ConfigManager()
        self._config.register_file(CONFIG_FILE_TRADINGVIEW)
        self._config.register_file(CONFIG_FILE_MODELS)
        self._tv_index_keys = _resolve_tv_index_keys(self._config)
        self.feature_manager = FeatureManager(asset, timeframe, db_fetcher=db_fetcher)
        self.engineered_manager = EngineeredFeatureManager(asset, timeframe)
        self._price_history: list[dict[str, float]] = []
        self._regime_orchestrator: Any = None
        self._regime_classifier: Any = None
        self._regime_cache: dict[str, Any] | None = None
        self._regime_cache_bar_count: int = 0
        self._last_processed_ts: float | None = None
        self._expected_interval_ms: float = _parse_timeframe_seconds(timeframe) * 1000

    @staticmethod
    def _normalize_timestamp_ms(timestamp: float) -> int:
        """Normalize timestamps to millisecond precision."""
        return int(timestamp * 1000) if timestamp < 1e12 else int(timestamp)

    async def _load_index_data(self) -> dict[str, dict[str, float]]:
        """Fetch latest TradingView index snapshots from Valkey."""
        index_data: dict[str, dict[str, float]] = {}
        if not self.redis_client:
            return index_data

        for idx_symbol in self._tv_index_keys:
            try:
                raw = await self.redis_client.hgetall(f"index:latest:{idx_symbol}")
                if raw:
                    index_data[idx_symbol] = {
                        k.decode() if isinstance(k, bytes) else k:
                        float(v.decode() if isinstance(v, bytes) else v)
                        for k, v in raw.items()
                    }
            except Exception:
                logger.warning(
                    f"Failed to fetch TV index data for {idx_symbol}",
                    exc_info=True,
                )
        return index_data

    async def _load_derivatives_data(self) -> dict[str, float]:
        """Fetch latest derivatives snapshots (OI, funding) from Valkey."""
        derivatives: dict[str, float] = {}
        if not self.redis_client:
            return derivatives

        # Derive asset list from config — same derivatives config used by tv_scraper
        derivatives_config: list[dict[str, Any]] = self._config.get(
            "tradingview.derivatives", []
        )
        assets = sorted({entry.get("asset", "") for entry in derivatives_config if entry.get("asset")})
        if not assets:
            return derivatives

        for asset in assets:
            for suffix, key_name in [("oi", "open_interest"), ("funding", "funding_rate")]:
                try:
                    raw = await self.redis_client.hgetall(f"derivatives:latest:{asset}:{suffix}")
                    if raw:
                        for k, v in raw.items():
                            field = k.decode() if isinstance(k, bytes) else k
                            val_str = v.decode() if isinstance(v, bytes) else v
                            if field == "value":
                                try:
                                    derivatives[f"{asset}_{key_name}"] = float(val_str)
                                except (ValueError, TypeError):
                                    pass
                except Exception:
                    logger.warning(f"Failed to fetch derivatives data for {asset}/{suffix}")

        return derivatives

    def _append_price_bar(
        self,
        *,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """Maintain the rolling price history buffer independently of any regime pipeline."""
        self._price_history.append(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
        if len(self._price_history) > _REGIME_MAX_HISTORY:
            self._price_history = self._price_history[-_REGIME_MAX_HISTORY:]

    def _maybe_attach_regime_snapshot(
        self,
        results: dict[str, Any],
    ) -> None:
        """Attach a regime snapshot when the optional regime pipeline is available."""
        if self._regime_orchestrator is None:
            return

        if len(self._price_history) < _REGIME_MIN_BARS:
            return

        try:
            df_hist = pd.DataFrame(self._price_history)
            regime_result = self._regime_orchestrator.analyze(df_hist)
            results["regime_snapshot"] = _regime_features_to_dict(regime_result)
        except Exception:
            logger.warning(
                "Regime analysis failed for current bar",
                exc_info=True,
            )

    def _resolve_feature_producer_config(self, producer_name: str) -> dict[str, Any] | None:
        """Resolve feature_producer config with deep-merged fallback chain."""
        fp_config = self._config.get("feature_producers", {})
        assets_config = fp_config.get("assets", {})

        asset_node = assets_config.get(self.asset, {})
        default_asset_node = assets_config.get("default", {})

        tf_node = asset_node.get("timeframes", {}).get(self.timeframe, {})
        asset_default_tf = asset_node.get("timeframes", {}).get("default", {})
        default_tf_node = default_asset_node.get("timeframes", {}).get(self.timeframe, {})
        default_default_tf = default_asset_node.get("timeframes", {}).get("default", {})

        def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
            merged = dict(base)
            for key, value in override.items():
                if (
                    key in merged
                    and isinstance(merged[key], dict)
                    and isinstance(value, dict)
                ):
                    merged[key] = _deep_merge(merged[key], value)
                else:
                    merged[key] = value
            return merged

        # Merge from lowest to highest priority:
        # default/default → default/tf → asset/default → asset/tf.
        merged: dict[str, Any] = {}
        found = False
        for node in (default_default_tf, default_tf_node, asset_default_tf, tf_node):
            if producer_name in node:
                merged = _deep_merge(merged, node[producer_name])
                found = True
        return merged if found else None

    async def _maybe_attach_regime_classification(
        self,
        results: dict[str, Any],
    ) -> None:
        """Attach regime_classification probability matrix features when model is available.

        Uses a cached result and only re-evaluates every _REGIME_REEVAL_INTERVAL
        new bars to avoid running full HMM/BCPD refit on every closed candle.
        """
        if self._regime_classifier is None:
            return

        if len(self._price_history) < _REGIME_MIN_BARS:
            return

        bars_since_cache = len(self._price_history) - self._regime_cache_bar_count
        need_reeval = (
            self._regime_cache is None
            or bars_since_cache >= _REGIME_REEVAL_INTERVAL
        )

        if need_reeval:
            try:
                df_hist = pd.DataFrame(self._price_history)
                regime_output = self._regime_classifier.batch_evaluate(df_hist)
                self._regime_cache = regime_output.iloc[-1]  # dict from RegimeFeatureOutput.to_dict()
                self._regime_cache_bar_count = len(self._price_history)
            except Exception:
                logger.warning(
                    "RegimeClassification batch_evaluate failed",
                    exc_info=True,
                )

        if self._regime_cache is None:
            return

        last_features = dict(self._regime_cache)
        last_features["_regime_staleness_bars"] = bars_since_cache

        # Fetch latest L2 features from TimescaleDB (if available)
        try:
            from libs.common.db.pool_manager import DBPoolManager
            from libs.common.db.timescale_reader import TimescaleReader
            reader = TimescaleReader(DBPoolManager.get_reader_pool())
            l2 = await reader.get_latest_l2_features(self.asset)
            if l2:
                last_features.update(l2)
        except Exception:
            logger.debug(
                "Optional L2 regime features unavailable for %s:%s",
                self.asset,
                self.timeframe,
                exc_info=True,
            )

        results["regime_classification"] = last_features

    async def _publish_bar_outputs(
        self,
        *,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        taker_buy_base: float,
        timestamp: int,
        raw_results: dict[str, Any],
        append_current_bar: bool,
    ) -> None:
        """Compute derived features and publish the signal/risk payloads for a bar."""
        results = dict(raw_results)
        index_data = await self._load_index_data()
        derivatives_data = await self._load_derivatives_data()

        engineered = self.engineered_manager.compute(
            results,
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "taker_buy_base": taker_buy_base,
            },
            index_data=index_data if index_data else None,
        )
        results.update(engineered)

        # Inject derivatives data into results for downstream consumers
        if derivatives_data:
            results.update(derivatives_data)

        # Maintain price history buffer independently of any regime pipeline
        if append_current_bar:
            self._append_price_bar(
                open_=open_, high=high, low=low, close=close, volume=volume,
            )

        self._maybe_attach_regime_snapshot(results)

        await self._maybe_attach_regime_classification(results)

        if self.redis_client and results:
            feature_stream = f"features:{self.asset}:{self.timeframe}"
            fv = FeatureVector(
                asset=self.asset,
                timeframe=self.timeframe,
                timestamp=timestamp,
                features=results,
                bar_data={
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "taker_buy_base": taker_buy_base,
                },
            )
            await self.redis_client.xadd(
                feature_stream,
                valkey_encode(fv),
                maxlen=10000,
                approximate=True,
            )

        if self.redis_client:
            price_stream = f"price_update:{self.asset}:{self.timeframe}"
            pu = PriceUpdate(
                asset=self.asset,
                timeframe=self.timeframe,
                timestamp=timestamp,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
            await self.redis_client.xadd(
                price_stream,
                valkey_encode(pu),
                maxlen=100,
                approximate=True,
            )

    async def _publish_bootstrap_snapshot(
        self,
        history: list[tuple[float, ...]],
    ) -> None:
        """Publish one immediate snapshot from primed history for higher-timeframe workers."""
        if not self.redis_client or not history:
            return

        raw_results = self.feature_manager.snapshot_features(history)
        if not raw_results:
            logger.warning(
                f"Skipping bootstrap snapshot for {self.asset}:{self.timeframe}: "
                "no primed indicators produced outputs yet."
            )
            return

        last_bar = history[-1]
        timestamp = self._normalize_timestamp_ms(last_bar[5])
        self._last_processed_ts = timestamp

        await self._publish_bar_outputs(
            open_=float(last_bar[0]),
            high=float(last_bar[1]),
            low=float(last_bar[2]),
            close=float(last_bar[3]),
            volume=float(last_bar[4]),
            taker_buy_base=float(last_bar[6]) if len(last_bar) > 6 else 0.0,
            timestamp=timestamp,
            raw_results=raw_results,
            append_current_bar=False,
        )
        logger.info(
            f"Published bootstrap snapshot for {self.asset}:{self.timeframe} "
            f"from historical bar @ {timestamp}"
        )

    async def _prime_startup_history(
        self,
        max_lookback: int,
    ) -> list[tuple[float, ...]] | None:
        """Prime indicators from DB history.

        Returns:
            Priming history when the worker is ready to process live bars.
            ``None`` when startup should remain in warming mode because not enough
            historical bars exist yet.

        Raises:
            RuntimeError when enough history exists but indicators still cannot
            be primed, which indicates a real contract/config bug.
        """
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                history = await self.feature_manager.fetch_historical_db_records(max_lookback)
                if not history:
                    logger.warning(
                        f"Priming deferred for {self.asset}:{self.timeframe}: "
                        "no history available yet. Waiting for more history."
                    )
                    return None

                self.feature_manager.prime(history)
                unprimed = self.feature_manager.get_unprimed_indicator_keys()
                if unprimed:
                    if len(history) < max_lookback:
                        logger.warning(
                            f"Starting {self.asset}:{self.timeframe} in degraded mode: "
                            f"have {len(history)} bars, need {max_lookback} for full prime. "
                            f"Waiting on indicators: {', '.join(unprimed)}"
                        )
                        return list(history)
                    raise RuntimeError(
                        f"Indicators failed to prime: {', '.join(unprimed)}"
                    )
                return list(history)
            except RuntimeError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    logger.warning(
                        f"Priming attempt {attempt + 1} failed for {self.asset}:{self.timeframe}, retrying..."
                    )
                    await asyncio.sleep(_STARTUP_PRIMING_RETRY_DELAY_SEC)
                else:
                    logger.warning(
                        f"Priming attempts exhausted for {self.asset}:{self.timeframe}; "
                        "remaining in warming mode until history becomes available.",
                        exc_info=True,
                    )

        if last_error is not None:
            return None
        return None

    async def start(self):
        logger.info(f"Starting signal worker for {self.asset} {self.timeframe}...")

        # 1. Boot up requirements state. Find max lookback for priming.
        # Include regime classification minimum so the classifier doesn't
        # start cold when indicator lookback is smaller than _REGIME_MIN_BARS.
        max_lookback = _REGIME_MIN_BARS
        for ind in self.feature_manager.indicators:
            max_lookback = max(max_lookback, ind.lookback_required)

        # 2. Fetch history and prime indicators.
        # If the stack is cold and history is not available yet, stay in warming
        # mode and keep retrying instead of crashing the entire worker process.
        history: list[tuple[float, ...]] = []
        while True:
            primed_history = await self._prime_startup_history(max_lookback)
            if primed_history is not None:
                history = primed_history
                break
            await asyncio.sleep(_STARTUP_WARMING_RETRY_DELAY_SEC)

        # 3. Prime price history buffer for regime pipelines (independent of orchestrator)
        if history:
            for bar in history:
                self._price_history.append({
                    "open": bar[0], "high": bar[1], "low": bar[2],
                    "close": bar[3], "volume": bar[4],
                })
            if len(self._price_history) > _REGIME_MAX_HISTORY:
                self._price_history = self._price_history[-_REGIME_MAX_HISTORY:]

        # 3a. Initialize regime orchestrator (optional — graceful if unavailable)
        try:
            RegimeOrchestrator = _import_regime_orchestrator()
            self._regime_orchestrator = RegimeOrchestrator.create(self.asset, self.timeframe)
            logger.info(f"Regime orchestrator initialized for {self.asset}:{self.timeframe} "
                        f"with {len(self._price_history)} primed bars")
        except Exception:
            logger.warning(f"Regime orchestrator unavailable for {self.asset}:{self.timeframe}, "
                           "regime features will not be published", exc_info=True)

        # 3b. Initialize regime classification model (new probability-matrix pipeline)
        # Config lives in models.yaml under feature_producers section.
        regime_cfg = self._resolve_feature_producer_config("RegimeClassification")
        if regime_cfg and regime_cfg.get("enabled", False):
            try:
                from libs.models.regime_classification.model import RegimeClassificationModel
                regime_params = regime_cfg.get("params") or {}
                frozen_overrides = regime_cfg.get("frozen_overrides") or {}
                self._regime_classifier = RegimeClassificationModel(
                    params=regime_params,
                    timeframe=self.timeframe,
                    frozen_overrides=frozen_overrides,
                )
                logger.info(f"RegimeClassificationModel initialized for {self.asset}:{self.timeframe}")
            except Exception:
                logger.warning(
                    f"RegimeClassificationModel unavailable for {self.asset}:{self.timeframe}, "
                    "regime_classification features will not be published",
                    exc_info=True,
                )
        else:
            logger.info(
                f"RegimeClassificationModel disabled for {self.asset}:{self.timeframe} "
                "(not enabled in feature_producers config)"
            )

        # 4. Emit one bootstrap snapshot so higher-timeframe workers do not wait
        # until the next candle close to seed downstream consumers.
        await self._publish_bootstrap_snapshot(history)

        # 5. Listen on stream via base class consumer loop
        await self.run()

    async def process_message(self, message_id: str, payload: dict) -> None:
        # Identify when incoming streamed events flag as `bar_closed: true`
        is_closed = payload.get("bar_closed") or payload.get("is_closed")

        if is_closed not in ("true", "True", "1", True):
            return

        try:
            ohlcv = StreamOHLCVPayload.model_validate(payload)
        except Exception as val_err:
            logger.warning(f"Invalid OHLCV payload, skipping: {val_err}")
            return

        try:
            open_ = ohlcv.open
            high = ohlcv.high
            low = ohlcv.low
            close = ohlcv.close
            volume = ohlcv.volume
            taker_buy_base = ohlcv.taker_buy_base
            timestamp = self._normalize_timestamp_ms(ohlcv.timestamp)

            # --- Gap detection: re-prime indicators if timestamp jump detected ---
            if self._last_processed_ts is not None:
                gap_ms = timestamp - self._last_processed_ts
                if gap_ms > 2 * self._expected_interval_ms:
                    logger.warning(
                        f"Gap detected for {self.asset}:{self.timeframe}: "
                        f"{gap_ms / 1000:.0f}s since last bar (expected ~{self._expected_interval_ms / 1000:.0f}s). "
                        f"Re-priming indicators from DB."
                    )
                    await self._reprime_after_gap()
            self._last_processed_ts = timestamp

            data_tuple = (open_, high, low, close, volume, timestamp, taker_buy_base)
            logger.debug(f"Dispatching tick {data_tuple} to FeatureManager")

            # Update features
            results = self.feature_manager.process_tick(data_tuple)
            logger.debug(f"Indicator results: {results}")

            await self._publish_bar_outputs(
                open_=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                taker_buy_base=taker_buy_base,
                timestamp=timestamp,
                raw_results=results,
                append_current_bar=True,
            )
        except Exception as e:
            logger.error(
                f"Failed to process payload {payload}: {e}",
                exc_info=True,
            )
            raise

    async def _reprime_after_gap(self) -> None:
        """Re-prime indicators by fetching fresh historical data from DB after a gap."""
        max_lookback = _REGIME_MIN_BARS
        for ind in self.feature_manager.indicators:
            max_lookback = max(max_lookback, ind.lookback_required)
        try:
            history = await self.feature_manager.fetch_historical_db_records(max_lookback)
            if not history:
                raise RuntimeError(
                    f"No history returned for re-priming {self.asset}:{self.timeframe}"
                )

            self.feature_manager.prime(history)
            unprimed = self.feature_manager.get_unprimed_indicator_keys()
            if unprimed:
                raise RuntimeError(
                    f"Indicators failed to re-prime after gap: {', '.join(unprimed)}"
                )

            # Rebuild regime price history (independent of orchestrator availability)
            self._price_history = [
                {
                    "open": bar[0],
                    "high": bar[1],
                    "low": bar[2],
                    "close": bar[3],
                    "volume": bar[4],
                }
                for bar in history
            ]
            logger.info(
                f"Re-primed {len(self.feature_manager.indicators)} indicators "
                f"with {len(history)} bars after gap for {self.asset}:{self.timeframe}"
            )
        except Exception:
            logger.error(
                f"Failed to re-prime indicators after gap for {self.asset}:{self.timeframe}",
                exc_info=True,
            )
            raise
