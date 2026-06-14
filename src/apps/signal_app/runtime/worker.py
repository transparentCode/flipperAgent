from __future__ import annotations

import asyncio
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.signal import StreamOHLCVPayload

from apps.signal_app.enrichment.valkey import ValkeySignalEnrichmentReader
from apps.signal_app.models import SignalPair, SignalPairState
from apps.signal_app.observability.runtime_state import SignalRuntimeStateStore
from apps.signal_app.pipeline import EngineeredFeaturePipeline, FeaturePipeline, RawIndicatorPipeline
from apps.signal_app.pipeline.priming import StartupPrimer, TimescaleStartupHistoryFetcher
from apps.signal_app.pipeline.regime import RegimeFeaturePipeline
from apps.signal_app.publishing import SignalStreamPublisher
from apps.signal_app.settings import SignalWorkerSettings

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)

DEFAULT_SIGNAL_WORKER_SETTINGS = SignalWorkerSettings()


class SignalRuntimeWorker(BaseStreamConsumer):
    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        pipeline: FeaturePipeline | None = None,
        publisher: SignalStreamPublisher | None = None,
        primer: StartupPrimer | None = None,
        startup_retry_delay_sec: float | None = None,
        settings: SignalWorkerSettings | None = None,
    ) -> None:
        settings = settings or DEFAULT_SIGNAL_WORKER_SETTINGS
        super().__init__(
            stream_key=f"stream:ohlcv:{asset.lower()}:{timeframe}",
            group_name=settings.consumer_group,
            consumer_name=f"{settings.consumer_name_prefix}_{asset}_{timeframe}",
            batch_size=settings.batch_size,
            block_ms=settings.block_ms,
        )
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.settings = settings
        self.raw_indicators = RawIndicatorPipeline(self.asset, self.timeframe)
        self.pipeline = pipeline or FeaturePipeline(
            raw_indicators=self.raw_indicators,
            engineered_features=EngineeredFeaturePipeline(self.asset, self.timeframe),
            regime_features=RegimeFeaturePipeline.create_optional(
                self.asset,
                self.timeframe,
                settings=self.settings,
            ),
        )
        if getattr(self.pipeline, "raw_indicators", None) is not None:
            self.raw_indicators = self.pipeline.raw_indicators
        self.publisher = publisher
        self.primer = primer or StartupPrimer(TimescaleStartupHistoryFetcher())
        self.state_store: SignalRuntimeStateStore | None = None
        self.startup_retry_delay_sec = (
            startup_retry_delay_sec
            if startup_retry_delay_sec is not None
            else settings.warming_retry_delay_sec
        )
        self._last_processed_ts: int | None = None
        self._expected_interval_ms = parse_timeframe_seconds(timeframe) * 1000

    async def connect(self, redis_client: Any) -> None:
        await super().connect(redis_client)
        self.state_store = SignalRuntimeStateStore(redis_client)
        if self.publisher is None:
            self.publisher = SignalStreamPublisher(redis_client)
        if self.pipeline.enrichment_reader is None:
            self.pipeline.enrichment_reader = ValkeySignalEnrichmentReader(
                redis_client,
                settings=self.settings,
            )

    async def start(self) -> None:
        logger.info("Starting signal worker for %s %s", self.asset, self.timeframe)
        await self._update_runtime_state(
            state=SignalPairState.WARMING,
            detail={"phase": "startup"},
        )
        history: list[tuple[float, ...]] = []
        while True:
            primed_history = await self.prime_startup_history(self.max_lookback)
            if primed_history is not None:
                history = primed_history
                break
            await asyncio.sleep(self.startup_retry_delay_sec)

        if self.pipeline.regime_features is not None:
            self.pipeline.regime_features.prime(history)

        await self.publish_bootstrap_snapshot(history)
        await self.run()

    @property
    def max_lookback(self) -> int:
        lookback = 0
        if self.pipeline.regime_features is not None:
            lookback = max(lookback, int(self.pipeline.regime_features.min_bars))
        for indicator in self.raw_indicators.indicators:
            lookback = max(lookback, int(indicator.lookback_required))
        return lookback

    async def prime_startup_history(
        self,
        max_lookback: int,
    ) -> list[tuple[float, ...]] | None:
        for attempt in range(3):
            try:
                history = await self.primer.fetch_history(
                    self.asset,
                    self.timeframe,
                    max_lookback,
                )
                if not history:
                    logger.warning(
                        "Priming deferred for %s:%s: no history available yet.",
                        self.asset,
                        self.timeframe,
                    )
                    await self._update_runtime_state(
                        state=SignalPairState.WARMING,
                        detail={"phase": "startup", "reason": "no_history"},
                    )
                    return None

                self.raw_indicators.prime(history)
                unprimed = self.raw_indicators.get_unprimed_indicator_keys()
                if unprimed:
                    if len(history) < max_lookback:
                        logger.warning(
                            "Starting %s:%s in degraded mode: have %s bars, need %s.",
                            self.asset,
                            self.timeframe,
                            len(history),
                            max_lookback,
                        )
                        await self._update_runtime_state(
                            state=SignalPairState.DEGRADED,
                            detail={
                                "phase": "startup",
                                "reason": "partial_history",
                                "history_bars": len(history),
                                "required_bars": max_lookback,
                                "unprimed_indicators": unprimed,
                            },
                        )
                        return history
                    raise RuntimeError(
                        f"Indicators failed to prime: {', '.join(unprimed)}"
                    )
                return history
            except RuntimeError:
                raise
            except Exception:
                if attempt < 2:
                    logger.warning(
                        "Priming attempt %s failed for %s:%s, retrying...",
                        attempt + 1,
                        self.asset,
                        self.timeframe,
                        exc_info=True,
                    )
                    await self._update_runtime_state(
                        state=SignalPairState.WARMING,
                        last_error="priming_attempt_failed",
                        detail={"phase": "startup", "attempt": attempt + 1},
                    )
                    await asyncio.sleep(self.settings.priming_retry_delay_sec)
                else:
                    logger.warning(
                        "Priming attempts exhausted for %s:%s; remaining in warming mode.",
                        self.asset,
                        self.timeframe,
                        exc_info=True,
                    )
                    await self._update_runtime_state(
                        state=SignalPairState.WARMING,
                        last_error="priming_attempts_exhausted",
                        detail={"phase": "startup", "attempts_exhausted": True},
                    )
        return None

    async def publish_bootstrap_snapshot(self, history: list[tuple[float, ...]]) -> None:
        if not history:
            return
        publisher = self._ensure_publisher()
        raw_features = self.raw_indicators.snapshot_features(history)
        if not raw_features:
            logger.warning(
                "Skipping bootstrap snapshot for %s:%s: no primed indicator outputs.",
                self.asset,
                self.timeframe,
            )
            await self._update_runtime_state(
                state=SignalPairState.DEGRADED,
                detail={"phase": "bootstrap", "reason": "no_raw_features"},
            )
            return

        candle = _bar_tuple_to_candle(self.asset, self.timeframe, history[-1])
        index_data: dict[str, dict[str, float]] = {}
        derivatives_data: dict[str, float] = {}
        if self.pipeline.enrichment_reader is not None:
            index_data = await self.pipeline.enrichment_reader.load_index_data()
            derivatives_data = await self.pipeline.enrichment_reader.load_derivatives_data()

        features = self.pipeline.build_features(
            candle=candle,
            raw_features=raw_features,
            index_data=index_data,
            derivatives_data=derivatives_data,
            append_current_bar=False,
        )
        if self.pipeline.regime_features is not None:
            features = await self.pipeline.regime_features.enrich(features)
        feature_vector, price_update = self.pipeline.build_payloads(
            asset=self.asset,
            timeframe=self.timeframe,
            candle=candle,
            features=features,
        )
        self._last_processed_ts = int(feature_vector.timestamp)
        await publisher.publish_feature_vector(feature_vector)
        await publisher.publish_price_update(price_update)
        await self._update_runtime_state(
            state=self._current_runtime_state(history),
            last_input_ts=float(candle.timestamp),
            last_feature_ts=float(feature_vector.timestamp),
            last_error=None,
            detail={"phase": "bootstrap"},
        )

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        payload = _decode_payload(data)
        if not _is_closed_bar(payload):
            return

        try:
            candle = StreamOHLCVPayload.model_validate(payload)
        except Exception as exc:
            logger.warning("Invalid OHLCV payload %s, skipping: %s", message_id, exc)
            return

        timestamp = normalize_timestamp_ms(candle.timestamp)
        try:
            if self._last_processed_ts is not None:
                gap_ms = timestamp - self._last_processed_ts
                if gap_ms > 2 * self._expected_interval_ms:
                    logger.warning(
                        "Gap detected for %s:%s: %.0fs since last bar; re-priming.",
                        self.asset,
                        self.timeframe,
                        gap_ms / 1000,
                    )
                    if not await self.reprime_after_gap():
                        return
            self._last_processed_ts = timestamp

            publisher = self._ensure_publisher()
            feature_vector, price_update = await self.pipeline.process_closed_candle_enriched(
                asset=self.asset,
                timeframe=self.timeframe,
                candle=candle,
            )
            await publisher.publish_feature_vector(feature_vector)
            await publisher.publish_price_update(price_update)
            await self._update_runtime_state(
                state=self._current_runtime_state_after_processing(),
                last_input_ts=float(candle.timestamp),
                last_feature_ts=float(feature_vector.timestamp),
                last_error=None,
                detail={"phase": "live"},
            )
        except Exception as exc:
            await self._update_runtime_state(
                state=SignalPairState.FAILED,
                last_input_ts=float(candle.timestamp),
                last_error=str(exc),
                detail={"phase": "live", "message_id": message_id},
            )
            raise

    async def reprime_after_gap(self) -> bool:
        history = await self.primer.fetch_history(self.asset, self.timeframe, self.max_lookback)
        if not history:
            logger.warning(
                "Gap re-priming deferred for %s:%s: no history returned yet.",
                self.asset,
                self.timeframe,
            )
            await self._update_runtime_state(
                state=SignalPairState.DEGRADED,
                last_error="reprime_no_history",
                detail={"phase": "reprime", "reason": "no_history"},
            )
            return False

        self.raw_indicators.prime(history)
        unprimed = self.raw_indicators.get_unprimed_indicator_keys()
        if unprimed:
            if len(history) < self.max_lookback:
                logger.warning(
                    "Gap re-priming left %s:%s degraded: have %s bars, need %s.",
                    self.asset,
                    self.timeframe,
                    len(history),
                    self.max_lookback,
                )
                if self.pipeline.regime_features is not None:
                    self.pipeline.regime_features.prime(history)
                await self._update_runtime_state(
                    state=SignalPairState.DEGRADED,
                    last_error=None,
                    detail={
                        "phase": "reprime",
                        "reason": "partial_history",
                        "history_bars": len(history),
                        "required_bars": self.max_lookback,
                        "unprimed_indicators": unprimed,
                    },
                )
                return True
            raise RuntimeError(
                f"Indicators failed to re-prime after gap: {', '.join(unprimed)}"
            )
        if self.pipeline.regime_features is not None:
            self.pipeline.regime_features.prime(history)
        await self._update_runtime_state(
            state=SignalPairState.LIVE,
            last_error=None,
            detail={"phase": "reprime", "history_bars": len(history)},
        )
        return True

    def _ensure_publisher(self) -> SignalStreamPublisher:
        if self.publisher is None:
            if self.redis_client is None:
                raise RuntimeError("SignalRuntimeWorker requires a publisher or redis client.")
            self.publisher = SignalStreamPublisher(self.redis_client)
        return self.publisher

    def _pair(self) -> SignalPair:
        return SignalPair(asset=self.asset, timeframe=self.timeframe)

    def _current_runtime_state(self, history: list[tuple[float, ...]]) -> SignalPairState:
        if self.raw_indicators.get_unprimed_indicator_keys() or len(history) < self.max_lookback:
            return SignalPairState.DEGRADED
        return SignalPairState.LIVE

    def _current_runtime_state_after_processing(self) -> SignalPairState:
        if self.raw_indicators.get_unprimed_indicator_keys():
            return SignalPairState.DEGRADED
        return SignalPairState.LIVE

    async def _update_runtime_state(
        self,
        *,
        state: SignalPairState,
        last_input_ts: float | None = None,
        last_feature_ts: float | None = None,
        last_error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if self.state_store is None:
            return
        await self.state_store.update(
            self._pair(),
            state=state,
            last_input_ts=last_input_ts,
            last_feature_ts=last_feature_ts,
            last_error=last_error,
            replace_last_error=last_error is None,
            detail=detail,
        )


def _is_closed_bar(payload: dict[str, Any]) -> bool:
    return payload.get("bar_closed") in ("true", "True", "1", True) or payload.get("is_closed") in (
        "true",
        "True",
        "1",
        True,
    )


def _decode_payload(data: dict[Any, Any]) -> dict[str, Any]:
    return {
        key.decode() if isinstance(key, bytes) else str(key):
        value.decode() if isinstance(value, bytes) else value
        for key, value in data.items()
    }


def parse_timeframe_seconds(timeframe: str) -> int:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if not timeframe:
        return 60
    try:
        value = int(timeframe[:-1])
    except (ValueError, IndexError):
        return 60
    return value * units.get(timeframe[-1].lower(), 60)


def normalize_timestamp_ms(timestamp: float) -> int:
    return int(timestamp * 1000) if timestamp < 1e12 else int(timestamp)


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
