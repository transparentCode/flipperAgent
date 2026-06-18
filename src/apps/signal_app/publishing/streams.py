from __future__ import annotations

from typing import Any

from libs.common.stream_keys import feature_stream_key, price_update_stream_key
from libs.contracts.signal import FeatureVector, PriceUpdate
from libs.contracts.serialization import valkey_encode
from apps.signal_app.settings import SignalWorkerSettings


class SignalStreamPublisher:
    def __init__(
        self,
        redis_client: Any,
        *,
        settings: SignalWorkerSettings | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.settings = settings or SignalWorkerSettings()

    async def publish_feature_vector(
        self,
        feature_vector: FeatureVector,
        *,
        trigger_timeframe: str | None = None,
        maxlen: int | None = None,
        approximate: bool | None = None,
    ) -> str | None:
        if self.redis_client is None:
            return None
        effective_maxlen = self.settings.feature_stream_maxlen if maxlen is None else maxlen
        effective_approximate = (
            self.settings.feature_stream_approximate if approximate is None else approximate
        )
        stream = feature_stream_key(
            feature_vector.asset,
            feature_vector.timeframe,
            trigger_timeframe=trigger_timeframe,
        )
        return await self.redis_client.xadd(
            stream,
            valkey_encode(feature_vector),
            maxlen=effective_maxlen,
            approximate=effective_approximate,
        )

    async def publish_price_update(
        self,
        price_update: PriceUpdate,
        *,
        maxlen: int | None = None,
        approximate: bool | None = None,
    ) -> str | None:
        if self.redis_client is None:
            return None
        effective_maxlen = self.settings.price_update_stream_maxlen if maxlen is None else maxlen
        effective_approximate = (
            self.settings.price_update_stream_approximate if approximate is None else approximate
        )
        stream = price_update_stream_key(price_update.asset, price_update.timeframe)
        return await self.redis_client.xadd(
            stream,
            valkey_encode(price_update),
            maxlen=effective_maxlen,
            approximate=effective_approximate,
        )
