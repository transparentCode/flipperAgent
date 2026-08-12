"""Minimal canonical candle commit service."""

from __future__ import annotations

from time import perf_counter

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.publication.outbox import build_candle_committed_event
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)


def canonicalize_observation(observation: CandleObservation) -> CanonicalCandle:
    """Convert provider metadata into the canonical provider provenance contract."""
    return CanonicalCandle(
        lane=observation.lane,
        open_time=observation.open_time,
        close_time=observation.close_time,
        open=observation.open,
        high=observation.high,
        low=observation.low,
        close=observation.close,
        volume=observation.volume,
        taker_buy_base=observation.taker_buy_base,
        source_type="provider",
        source_provider=observation.provider_id,
        source_timeframe=None,
    )


class CandleIngestionService:
    """Construct publication intent and delegate atomic persistence."""

    def __init__(
        self,
        repository: CandleRepository,
        observability: IngestionObservability | None = None,
    ) -> None:
        self.repository = repository
        self.observability = observability or IngestionObservability()

    async def commit_candle(self, candle: CanonicalCandle) -> CandleCommitStatus:
        event = build_candle_committed_event(candle)
        started = perf_counter()
        status = await self.repository.commit_candle(candle, event)
        self.observability.record_candle_commit(
            timeframe=candle.lane.timeframe,
            source_type=candle.source_type,
            outcome=status,
            duration_ms=(perf_counter() - started) * 1000,
        )
        if status is CandleCommitStatus.INSERTED:
            self.observability.record_outbox_insert(event.occurred_at)
        return status

    async def commit_observation(
        self,
        observation: CandleObservation,
    ) -> CandleCommitStatus:
        return await self.commit_candle(canonicalize_observation(observation))


__all__ = ["CandleIngestionService", "canonicalize_observation"]
