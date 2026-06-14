"""Reusable Valkey stream consumer base class."""

from __future__ import annotations

import abc
import asyncio
import time as _time
from typing import Any

from valkey.exceptions import ResponseError
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__)

_DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 50
_DEFAULT_PEL_RECLAIM_IDLE_MS = 30_000


async def ensure_consumer_group(
    client: Any,
    stream_key: str,
    group_name: str,
    start_id: str = "0",
) -> None:
    """Create a consumer group, ignoring BUSYGROUP if it already exists."""
    try:
        await client.xgroup_create(stream_key, group_name, id=start_id, mkstream=True)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            raise


class BaseStreamConsumer(abc.ABC):
    """ABC for Valkey XREADGROUP consumer loops.

    Subclasses implement process_message() with their business logic.
    The base class handles the consumer loop, ack, error recovery, and group creation.
    """

    def __init__(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        batch_size: int = 10,
        block_ms: int = 2000,
        pel_reclaim_idle_ms: int = _DEFAULT_PEL_RECLAIM_IDLE_MS,
    ) -> None:
        self.stream_key = stream_key
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.batch_size = batch_size
        self.block_ms = block_ms
        self.pel_reclaim_idle_ms = max(0, int(pel_reclaim_idle_ms))
        self.redis_client: Any = None

    async def connect(self, redis_client: Any) -> None:
        """Store client reference and ensure consumer group exists."""
        self.redis_client = redis_client
        await ensure_consumer_group(redis_client, self.stream_key, self.group_name)

    @abc.abstractmethod
    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Process a single stream message. Implement in subclass."""
        ...

    async def run(self) -> None:
        """Main consumer loop with error recovery and OTel tracing."""
        if not self.redis_client:
            logger.warning(f"No redis client for {self.stream_key} — consumer inactive")
            return

        logger.info(f"Listening to stream {self.stream_key} via XREADGROUP...")

        # --- Attempt OTel setup (graceful if not available) ---
        _tracer = None
        _extract_trace_context = None
        _msg_duration = None
        _msg_counter = None
        _error_counter = None
        try:
            from opentelemetry import trace as _trace, metrics as _metrics
            from libs.common.telemetry.propagation import extract_trace_context as _etc
            _tracer = _trace.get_tracer(__name__)
            _extract_trace_context = _etc
            _meter = _metrics.get_meter(__name__)
            _msg_duration = _meter.create_histogram(
                "stream.message.duration_ms",
                description="Time to process a single stream message",
                unit="ms",
            )
            _msg_counter = _meter.create_counter(
                "stream.message.processed_total",
                description="Total messages processed",
            )
            _error_counter = _meter.create_counter(
                "stream.message.error_total",
                description="Total message processing errors",
            )
        except ImportError:
            pass

        # Drain any messages left in the Pending Entry List (PEL) from previous
        # runs before reading new messages. We only reclaim entries that have
        # been idle long enough to suggest their previous consumer is gone.
        try:
            next_id = "0-0"
            while True:
                result = await self.redis_client.xautoclaim(
                    self.stream_key,
                    self.group_name,
                    self.consumer_name,
                    min_idle_time=self.pel_reclaim_idle_ms,
                    start_id=next_id,
                    count=self.batch_size,
                )
                # xautoclaim returns (next_start_id, [(id, data), ...], [deleted_ids])
                next_id, pending_messages, _ = result
                if not pending_messages:
                    break
                for message_id, data in pending_messages:
                    try:
                        await self.process_message(message_id, data)
                        await self.redis_client.xack(self.stream_key, self.group_name, message_id)
                    except Exception:
                        logger.exception(
                            f"Error reprocessing PEL message {message_id} from {self.stream_key} — leaving in PEL"
                        )
                if next_id == "0-0":
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(f"PEL drain failed for {self.stream_key} — skipping, proceeding to live stream", exc_info=True)

        streams = {self.stream_key: ">"}
        consecutive_failures = 0
        circuit_breaker_threshold = _DEFAULT_CIRCUIT_BREAKER_THRESHOLD

        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    streams,
                    count=self.batch_size,
                    block=self.block_ms,
                )
                if not response:
                    continue

                for stream_name, messages in response:
                    for message_id, data in messages:
                        try:
                            if _tracer and _extract_trace_context:
                                parent_ctx = _extract_trace_context(data)
                                _start = _time.monotonic()
                                with _tracer.start_as_current_span(
                                    f"{self.stream_key}.process",
                                    context=parent_ctx,
                                    attributes={
                                        "messaging.system": "valkey",
                                        "messaging.destination": self.stream_key,
                                        "messaging.message_id": message_id
                                        if isinstance(message_id, str)
                                        else message_id.decode("utf-8", errors="replace"),
                                        "messaging.consumer_group": self.group_name,
                                    },
                                ):
                                    await self.process_message(message_id, data)
                                _elapsed = (_time.monotonic() - _start) * 1000
                                if _msg_duration:
                                    _msg_duration.record(_elapsed, {"stream": self.stream_key})
                                if _msg_counter:
                                    _msg_counter.add(1, {"stream": self.stream_key})
                            else:
                                await self.process_message(message_id, data)

                            await self.redis_client.xack(
                                self.stream_key, self.group_name, message_id
                            )
                        except Exception:
                            if _error_counter:
                                _error_counter.add(1, {"stream": self.stream_key})
                            logger.exception(
                                f"Error processing message {message_id} from {self.stream_key} — not acking, message will remain in PEL for redelivery"
                            )

                # Successful iteration — reset circuit breaker
                consecutive_failures = 0

            except asyncio.CancelledError:
                logger.info(f"Consumer {self.consumer_name} cancelled")
                break
            except ValkeyTimeoutError:
                consecutive_failures += 1
                logger.warning(
                    "Stream read timeout on %s (consecutive failures: %s)",
                    self.stream_key,
                    consecutive_failures,
                )
                if consecutive_failures >= circuit_breaker_threshold:
                    logger.critical(
                        f"Circuit breaker tripped for {self.stream_key}: "
                        f"{consecutive_failures} consecutive failures. Breaking consumer loop."
                    )
                    break
                await asyncio.sleep(1)
            except Exception as exc:
                if isinstance(exc, ResponseError) and "NOGROUP" in str(exc):
                    logger.info(
                        "Consumer %s stopping because stream/group disappeared for %s",
                        self.consumer_name,
                        self.stream_key,
                    )
                    break
                consecutive_failures += 1
                logger.exception(f"Stream read error on {self.stream_key} (consecutive failures: {consecutive_failures})")
                if consecutive_failures >= circuit_breaker_threshold:
                    logger.critical(
                        f"Circuit breaker tripped for {self.stream_key}: "
                        f"{consecutive_failures} consecutive failures. Breaking consumer loop."
                    )
                    break
                await asyncio.sleep(1)
