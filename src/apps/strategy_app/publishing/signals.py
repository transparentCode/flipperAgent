from __future__ import annotations

import hashlib
from typing import Any

from libs.common.signal_authority import SignalAuthorityStore, signal_route_from_stream
from libs.contracts.schemas import FeatureVector, TradeSignal, valkey_encode


class StrategyAuthorityDenied(RuntimeError):
    """A managed legacy publication no longer has a valid authority fence."""


def make_signal_idempotency_key(
    model_name: str,
    asset: str,
    timeframe: str,
    timestamp: float,
) -> str:
    raw = f"{model_name}:{asset}:{timeframe}:{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class StrategySignalPublisher:
    def __init__(
        self,
        *,
        signal_stream_key: str,
        maxlen: int,
        approximate: bool,
        logger: Any,
        authority_store: SignalAuthorityStore | None = None,
    ) -> None:
        self.signal_stream_key = signal_stream_key
        self.maxlen = maxlen
        self.approximate = approximate
        self.logger = logger
        if authority_store is not None and not isinstance(
            authority_store, SignalAuthorityStore
        ):
            raise TypeError("authority_store must be SignalAuthorityStore or None")
        self.authority_store = authority_store

    async def publish_selected(
        self,
        *,
        redis_client: Any,
        feature_vec: FeatureVector,
        selected: list[Any],
        authority_epoch: int | None = None,
        authority_boundary_ms: int | None = None,
        effect_cutoff_ms: int | None = None,
    ) -> int:
        bar_close = feature_vec.bar_data.get("close")
        if not bar_close:
            self.logger.error(
                f"FeatureVector missing close price for {feature_vec.asset}/{feature_vec.timeframe} "
                f"at ts={feature_vec.timestamp} — skipping signal publication"
            )
            return 0

        published = 0
        for result in selected:
            candidate = result.candidate
            signal = TradeSignal(
                asset=candidate.asset,
                timeframe=candidate.timeframe,
                timestamp=candidate.timestamp,
                direction=candidate.direction,
                conviction=candidate.conviction,
                price=bar_close,
                idempotency_key=make_signal_idempotency_key(
                    candidate.model_name,
                    candidate.asset,
                    candidate.timeframe,
                    candidate.timestamp,
                ),
                model_name=candidate.model_name,
                metadata={
                    **candidate.metadata,
                    "selection_rank": result.rank,
                    "selection_score": result.selection_score,
                    "selection_penalties": result.penalties,
                    "bar_high": feature_vec.bar_data.get("high", 0.0),
                    "bar_low": feature_vec.bar_data.get("low", 0.0),
                },
            )

            if redis_client:
                fields = valkey_encode(signal)
                if self.authority_store is not None:
                    route = signal_route_from_stream(self.signal_stream_key)
                    guarded = await self.authority_store.guarded_xadd(
                        route=route,
                        expected_owner="strategy",
                        expected_epoch=authority_epoch,
                        expected_boundary_ms=authority_boundary_ms,
                        effect_cutoff_ms=effect_cutoff_ms,
                        stream_key=self.signal_stream_key,
                        fields=fields,
                        stream_id="*",
                        maxlen=self.maxlen,
                        approximate=self.approximate,
                    )
                    if not guarded.allowed:
                        raise StrategyAuthorityDenied(
                            f"signal authority denied legacy publication for {route}: "
                            f"{guarded.reason or 'unknown reason'}"
                        )
                        continue
                    if not guarded.managed:
                        await redis_client.xadd(
                            self.signal_stream_key,
                            fields,
                            maxlen=self.maxlen,
                            approximate=self.approximate,
                        )
                else:
                    await redis_client.xadd(
                        self.signal_stream_key,
                        fields,
                        maxlen=self.maxlen,
                        approximate=self.approximate,
                    )
                published += 1
                self.logger.debug(f"Published signal: {signal.idempotency_key}")
        return published
