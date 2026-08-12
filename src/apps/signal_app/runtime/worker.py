from __future__ import annotations

import asyncio
import inspect
import math
from collections import deque
from typing import Any

from apps.signal_app.enrichment.valkey import ValkeySignalEnrichmentReader
from apps.signal_app.models import SignalPair, SignalPairState
from apps.signal_app.observability.runtime_state import SignalRuntimeStateStore
from apps.signal_app.ohlcv_source import (
    IngestionHistoryFetcher,
    decode_ingestion_event,
    stream_key_for_binding,
)
from apps.signal_app.pipeline import (
    EngineeredFeaturePipeline,
    FeaturePipeline,
    RawIndicatorPipeline,
)
from apps.signal_app.pipeline.ltf_context import (
    ValkeyLtfContextStore,
    compute_profile_snapshots,
    required_history_bars,
)
from apps.signal_app.pipeline.priming import (
    StartupPrimer,
)
from apps.signal_app.pipeline.projection import (
    ProjectedBar,
    project_current_decision_bar,
)
from apps.signal_app.pipeline.regime import RegimeFeaturePipeline
from apps.signal_app.publishing import SignalStreamPublisher
from apps.signal_app.settings import SignalWorkerSettings
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer, ensure_consumer_group
from libs.common.timeframes import timeframe_to_seconds
from libs.contracts.signal import StreamOHLCVPayload

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
        base_timeframe: str = "1m",
        trigger_timeframe: str | None = None,
        trigger_mode: str = "on_bar_close",
        required_context_profiles: list[str] | None = None,
    ) -> None:
        settings = settings or DEFAULT_SIGNAL_WORKER_SETTINGS
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.base_timeframe = str(base_timeframe).strip() or "1m"
        self.trigger_timeframe = (
            str(trigger_timeframe or timeframe).strip() or timeframe
        )
        self.trigger_mode = str(trigger_mode).strip() or "on_bar_close"
        self.source_binding = settings.source_binding(self.asset)
        super().__init__(
            stream_key=stream_key_for_binding(
                self.source_binding,
                self.trigger_timeframe,
            ),
            group_name=settings.consumer_group,
            consumer_name=_consumer_name(
                settings.consumer_name_prefix,
                self.asset,
                decision_timeframe=self.timeframe,
                trigger_timeframe=self.trigger_timeframe,
            ),
            batch_size=settings.batch_size,
            block_ms=settings.block_ms,
        )
        self.required_context_profiles = list(required_context_profiles or [])
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
        if primer is not None:
            self.primer = primer
        else:
            self.primer = StartupPrimer(IngestionHistoryFetcher(self.source_binding))
        self.state_store: SignalRuntimeStateStore | None = None
        self.context_store: ValkeyLtfContextStore | None = None
        self.startup_retry_delay_sec = (
            startup_retry_delay_sec
            if startup_retry_delay_sec is not None
            else settings.warming_retry_delay_sec
        )
        self._last_processed_ts: int | None = None
        self._expected_interval_ms = timeframe_to_seconds(self.trigger_timeframe) * 1000
        self._ltf_history_bars = required_history_bars(
            self.required_context_profiles,
            base_timeframe=self.base_timeframe,
        )
        self._ltf_history: deque[tuple[float, ...]] = deque(
            maxlen=max(self._ltf_history_bars, 1)
        )
        self._projection_history: deque[tuple[float, ...]] = deque(
            maxlen=max(self.max_lookback, 1)
        )
        self._source_window_bars = max(
            self._ltf_history_bars,
            math.ceil(
                max(timeframe_to_seconds(self.timeframe), 1)
                / max(timeframe_to_seconds(self.trigger_timeframe), 1)
            ),
            1,
        )
        self._source_history: deque[tuple[float, ...]] = deque(
            maxlen=self._source_window_bars
        )

    async def connect(self, redis_client: Any) -> None:
        await ensure_consumer_group(
            redis_client,
            self.stream_key,
            self.group_name,
            start_id="$",
        )
        await super().connect(redis_client)
        self.state_store = SignalRuntimeStateStore(redis_client)
        self.context_store = ValkeyLtfContextStore(
            redis_client,
            ttl_seconds=self.settings.ltf_context_ttl_seconds,
        )
        if self.publisher is None:
            self.publisher = SignalStreamPublisher(redis_client, settings=self.settings)
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
        regime_features = getattr(self.pipeline, "regime_features", None)
        if regime_features is not None:
            lookback = max(lookback, int(regime_features.min_bars))
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

                await asyncio.to_thread(self.raw_indicators.prime, history)
                self._prime_projection_history(history)
                if self._is_projected_lane():
                    source_history = await self.primer.fetch_history(
                        self.asset,
                        self.trigger_timeframe,
                        self._source_window_bars,
                    )
                    self._prime_source_history(source_history)
                    self._prime_ltf_history(source_history)
                else:
                    self._prime_ltf_history(history)
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

    async def publish_bootstrap_snapshot(
        self, history: list[tuple[float, ...]]
    ) -> None:
        if not history:
            return
        publisher = self._ensure_publisher()
        projected = self._current_projected_bar()
        bootstrap_history = (
            self._projection_history_for_snapshot(projected)
            if projected is not None
            else history
        )
        raw_features = await asyncio.to_thread(
            self.raw_indicators.snapshot_features,
            bootstrap_history,
        )
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

        if projected is not None:
            candle = self._projected_candle_from_projection(
                projected,
                origin="decision_projection_bootstrap",
            )
        else:
            candle = _bar_tuple_to_candle(self.asset, self.timeframe, history[-1])
        index_data: dict[str, dict[str, float]] = {}
        derivatives_data: dict[str, float] = {}
        ltf_context_profiles = await self._resolve_ltf_context_profiles(
            candle=candle,
            history=list(self._source_history)
            if self._is_projected_lane()
            else history,
        )
        if self.pipeline.enrichment_reader is not None:
            index_data = await self.pipeline.enrichment_reader.load_index_data()
            derivatives_data = (
                await self.pipeline.enrichment_reader.load_derivatives_data()
            )

        features = await asyncio.to_thread(
            self.pipeline.build_features,
            candle=candle,
            raw_features=raw_features,
            index_data=index_data,
            derivatives_data=derivatives_data,
            ltf_context_profiles=ltf_context_profiles,
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
        feature_vector = self._apply_projection_transport_metadata(
            feature_vector,
            source_feature_timeframe=self.trigger_timeframe,
            decision_bar_closed=projected.closed if projected is not None else True,
        )
        self._last_processed_ts = self._bootstrap_last_processed_ts(
            candle, feature_vector
        )
        await publisher.publish_feature_vector(
            feature_vector,
            trigger_timeframe=self.trigger_timeframe
            if self._is_projected_lane()
            else None,
        )
        if not self._is_projected_lane():
            await publisher.publish_price_update(price_update)
        await self._update_runtime_state(
            state=self._current_runtime_state(history),
            last_input_ts=float(candle.timestamp),
            last_feature_ts=float(feature_vector.timestamp),
            last_error=None,
            detail={"phase": "bootstrap"},
        )

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        candle = decode_ingestion_event(
            data,
            self.source_binding,
            self.trigger_timeframe,
        )

        timestamp = normalize_timestamp_ms(candle.timestamp)
        try:
            if self._last_processed_ts is not None:
                if timestamp <= self._last_processed_ts:
                    return
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
            self._source_history.append(
                (
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    float(candle.timestamp),
                    candle.taker_buy_base,
                )
            )
            self._last_processed_ts = timestamp

            publisher = self._ensure_publisher()
            ltf_context_profiles = await self._resolve_ltf_context_profiles(
                candle=candle
            )
            (
                feature_vector,
                price_update,
            ) = await self._process_closed_candle_with_optional_context(
                candle=candle,
                ltf_context_profiles=ltf_context_profiles,
            )
            await publisher.publish_feature_vector(
                feature_vector,
                trigger_timeframe=self.trigger_timeframe
                if self._is_projected_lane()
                else None,
            )
            if not self._is_projected_lane():
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
        history = await self.primer.fetch_history(
            self.asset, self.timeframe, self.max_lookback
        )
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

        await asyncio.to_thread(self.raw_indicators.prime, history)
        self._prime_projection_history(history)
        if self._is_projected_lane():
            source_history = await self.primer.fetch_history(
                self.asset,
                self.trigger_timeframe,
                self._source_window_bars,
            )
            self._prime_source_history(source_history)
            self._prime_ltf_history(source_history)
        else:
            self._prime_ltf_history(history)
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

    async def _process_closed_candle_with_optional_context(
        self,
        *,
        candle: StreamOHLCVPayload,
        ltf_context_profiles: dict[str, dict[str, Any]] | None,
    ) -> tuple[Any, Any]:
        if self._is_projected_lane():
            return await self._process_projected_candle(
                candle=candle,
                ltf_context_profiles=ltf_context_profiles,
            )
        parameters = inspect.signature(
            self.pipeline.process_closed_candle_enriched
        ).parameters
        kwargs: dict[str, Any] = {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "candle": candle,
        }
        if "ltf_context_profiles" in parameters and ltf_context_profiles:
            kwargs["ltf_context_profiles"] = ltf_context_profiles
        return await self.pipeline.process_closed_candle_enriched(**kwargs)

    async def _process_projected_candle(
        self,
        *,
        candle: StreamOHLCVPayload,
        ltf_context_profiles: dict[str, dict[str, Any]] | None,
    ) -> tuple[Any, Any]:
        projected = self._current_projected_bar()
        if projected is None:
            raise RuntimeError("Projected decision view requires source history.")

        projected_candle = self._projected_candle_from_projection(projected)
        history_for_snapshot = self._projection_history_for_snapshot(projected)
        raw_features = await asyncio.to_thread(
            self.raw_indicators.snapshot_features,
            history_for_snapshot,
        )
        index_data: dict[str, dict[str, float]] = {}
        derivatives_data: dict[str, float] = {}
        if self.pipeline.enrichment_reader is not None:
            index_data = await self.pipeline.enrichment_reader.load_index_data()
            derivatives_data = (
                await self.pipeline.enrichment_reader.load_derivatives_data()
            )

        features = await asyncio.to_thread(
            self.pipeline.build_features,
            candle=projected_candle,
            raw_features=raw_features,
            index_data=index_data,
            derivatives_data=derivatives_data,
            ltf_context_profiles=ltf_context_profiles,
            append_current_bar=False,
        )
        if self.pipeline.regime_features is not None:
            features = await self.pipeline.regime_features.enrich(features)
            if projected.closed:
                # Active RegimeV2 is already evaluated for this vector. Advance the
                # confirmed regime history now so subsequent projected decisions see this close.
                self.pipeline.regime_features.append_bar(
                    {
                        "open": projected_candle.open,
                        "high": projected_candle.high,
                        "low": projected_candle.low,
                        "close": projected_candle.close,
                        "volume": projected_candle.volume,
                        "taker_buy_base": projected_candle.taker_buy_base,
                    }
                )
        feature_vector, price_update = self.pipeline.build_payloads(
            asset=self.asset,
            timeframe=self.timeframe,
            candle=projected_candle,
            features=features,
        )
        feature_vector = self._apply_projection_transport_metadata(
            feature_vector,
            source_feature_timeframe=self.trigger_timeframe,
            decision_bar_closed=projected.closed,
        )
        if projected.closed:
            await self._commit_projected_bar(projected)
        return feature_vector, price_update

    def _prime_ltf_history(self, history: list[tuple[float, ...]]) -> None:
        if not self._should_publish_ltf_context() or not history:
            return
        self._ltf_history.clear()
        for row in history[-self._ltf_history.maxlen :]:
            self._ltf_history.append(row)

    def _prime_projection_history(self, history: list[tuple[float, ...]]) -> None:
        self._projection_history.clear()
        for row in history[-self._projection_history.maxlen :]:
            self._projection_history.append(row)

    def _prime_source_history(self, history: list[tuple[float, ...]]) -> None:
        self._source_history.clear()
        for row in history[-self._source_history.maxlen :]:
            self._source_history.append(row)

    async def _resolve_ltf_context_profiles(
        self,
        *,
        candle: StreamOHLCVPayload,
        history: list[tuple[float, ...]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        if not self.required_context_profiles:
            return {}
        if self._should_publish_ltf_context():
            if history is None:
                self._ltf_history.append(
                    (
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume,
                        float(candle.timestamp),
                        candle.taker_buy_base,
                    )
                )
            snapshots = compute_profile_snapshots(
                profiles=self.required_context_profiles,
                bars=list(self._ltf_history),
                base_timeframe=self.base_timeframe,
            )
            if self.context_store is not None and snapshots:
                await self.context_store.publish_profiles(
                    asset=self.asset,
                    base_timeframe=self.base_timeframe,
                    snapshots=snapshots,
                )
            return snapshots

        if self.pipeline.enrichment_reader is None:
            return {}
        return await self.pipeline.enrichment_reader.load_ltf_context_profiles(
            asset=self.asset,
            base_timeframe=self.base_timeframe,
            profiles=self.required_context_profiles,
        )

    def _should_publish_ltf_context(self) -> bool:
        return self.trigger_timeframe == self.base_timeframe and bool(
            self.required_context_profiles
        )

    def _is_projected_lane(self) -> bool:
        return self.trigger_timeframe != self.timeframe

    def _ensure_publisher(self) -> SignalStreamPublisher:
        if self.publisher is None:
            if self.redis_client is None:
                raise RuntimeError(
                    "SignalRuntimeWorker requires a publisher or redis client."
                )
            self.publisher = SignalStreamPublisher(
                self.redis_client, settings=self.settings
            )
        return self.publisher

    def _pair(self) -> SignalPair:
        return SignalPair(
            asset=self.asset,
            timeframe=self.timeframe,
            trigger_timeframe=None
            if not self._is_projected_lane()
            else self.trigger_timeframe,
            trigger_mode=self.trigger_mode,
            base_timeframe=self.base_timeframe,
            required_context_profiles=list(self.required_context_profiles),
        )

    def _current_projected_bar(self) -> ProjectedBar | None:
        return project_current_decision_bar(
            list(self._source_history),
            decision_timeframe=self.timeframe,
            source_timeframe=self.trigger_timeframe,
        )

    def _projection_history_for_snapshot(
        self, projected: ProjectedBar
    ) -> list[tuple[float, ...]]:
        history = list(self._projection_history)
        if history and int(float(history[-1][5])) == int(projected.bucket_start):
            history[-1] = projected.bar
            return history
        history.append(projected.bar)
        return history

    def _projected_candle_from_projection(
        self,
        projected: ProjectedBar,
        *,
        origin: str = "decision_projection_live",
    ) -> StreamOHLCVPayload:
        provider = (
            "timescale" if origin == "decision_projection_bootstrap" else "projected"
        )
        return projected.to_candle(
            asset=self.asset,
            base_timeframe=self.base_timeframe,
            provider=provider,
            origin=origin,
        )

    def _apply_projection_transport_metadata(
        self,
        feature_vector: Any,
        *,
        source_feature_timeframe: str,
        decision_bar_closed: bool,
    ) -> Any:
        features = dict(feature_vector.features)
        transport = dict(features.get("ctx_transport", {}))
        transport["trigger_timeframe"] = self.trigger_timeframe
        transport["decision_timeframe"] = self.timeframe
        transport["trigger_mode"] = self.trigger_mode
        transport["source_feature_timeframe"] = source_feature_timeframe
        transport["decision_bar_closed"] = decision_bar_closed
        transport["projection_mode"] = (
            "decision_view" if self._is_projected_lane() else "direct"
        )
        features["ctx_transport"] = transport
        return feature_vector.model_copy(update={"features": features})

    async def _commit_projected_bar(self, projected: ProjectedBar) -> None:
        if self._projection_history and int(
            float(self._projection_history[-1][5])
        ) == int(projected.bucket_start):
            self._projection_history[-1] = projected.bar
        else:
            self._projection_history.append(projected.bar)
        await asyncio.to_thread(
            self.raw_indicators.prime,
            list(self._projection_history),
        )

    def _bootstrap_last_processed_ts(
        self, candle: StreamOHLCVPayload, feature_vector: Any
    ) -> int:
        if self._source_history:
            return normalize_timestamp_ms(float(self._source_history[-1][5]))
        return int(
            feature_vector.timestamp
            if feature_vector.timestamp
            else normalize_timestamp_ms(candle.timestamp)
        )

    def _current_runtime_state(
        self, history: list[tuple[float, ...]]
    ) -> SignalPairState:
        if (
            self.raw_indicators.get_unprimed_indicator_keys()
            or len(history) < self.max_lookback
        ):
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


def normalize_timestamp_ms(timestamp: float) -> int:
    return int(timestamp * 1000) if timestamp < 1e12 else int(timestamp)


def _consumer_name(
    prefix: str,
    asset: str,
    *,
    decision_timeframe: str,
    trigger_timeframe: str,
) -> str:
    if decision_timeframe == trigger_timeframe:
        return f"{prefix}_{asset}_{decision_timeframe}"
    return f"{prefix}_{asset}_{decision_timeframe}__{trigger_timeframe}"


def _bar_tuple_to_candle(
    asset: str,
    timeframe: str,
    bar: tuple[float, ...],
) -> StreamOHLCVPayload:
    bar_span_seconds = timeframe_to_seconds(timeframe)
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
        base_timeframe="1m",
        bar_span_seconds=bar_span_seconds,
        close_timestamp=float(bar[5]) + bar_span_seconds,
        provider="timescale",
        origin="bootstrap_snapshot",
    )
