"""Publication intent contracts for ingestion."""

from typing import TYPE_CHECKING

from .outbox import (
    CANDLE_COMMITTED_EVENT_TYPE,
    CANDLE_COMMITTED_PRODUCER,
    CANDLE_COMMITTED_SCHEMA_VERSION,
    OutboxEvent,
    build_candle_committed_event,
)
from .stream_keys import canonical_lane_stream_key

if TYPE_CHECKING:
    from .publisher import OutboxPublisher


def __getattr__(name: str) -> object:
    if name == "OutboxPublisher":
        from .publisher import OutboxPublisher

        return OutboxPublisher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CANDLE_COMMITTED_EVENT_TYPE",
    "CANDLE_COMMITTED_PRODUCER",
    "CANDLE_COMMITTED_SCHEMA_VERSION",
    "OutboxEvent",
    "OutboxPublisher",
    "build_candle_committed_event",
    "canonical_lane_stream_key",
]
