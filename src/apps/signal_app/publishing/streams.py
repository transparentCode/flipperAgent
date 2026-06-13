from __future__ import annotations

from typing import Any

from libs.contracts.signal import FeatureVector, PriceUpdate
from libs.contracts.serialization import valkey_encode


class SignalStreamPublisher:
    def __init__(self, redis_client: Any) -> None:
        self.redis_client = redis_client

    async def publish_feature_vector(
        self,
        feature_vector: FeatureVector,
        *,
        maxlen: int = 10_000,
    ) -> str | None:
        if self.redis_client is None:
            return None
        stream = feature_stream_key(feature_vector.asset, feature_vector.timeframe)
        return await self.redis_client.xadd(
            stream,
            valkey_encode(feature_vector),
            maxlen=maxlen,
            approximate=True,
        )

    async def publish_price_update(
        self,
        price_update: PriceUpdate,
        *,
        maxlen: int = 100,
    ) -> str | None:
        if self.redis_client is None:
            return None
        stream = price_update_stream_key(price_update.asset, price_update.timeframe)
        return await self.redis_client.xadd(
            stream,
            valkey_encode(price_update),
            maxlen=maxlen,
            approximate=True,
        )


def feature_stream_key(asset: str, timeframe: str) -> str:
    return f"features:{asset.upper()}:{timeframe}"


def price_update_stream_key(asset: str, timeframe: str) -> str:
    return f"price_update:{asset.upper()}:{timeframe}"

