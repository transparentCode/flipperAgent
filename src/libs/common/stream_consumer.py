"""Reusable Valkey stream consumer base class."""

from __future__ import annotations

import abc
import asyncio
from typing import Any

from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__)


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
    ) -> None:
        self.stream_key = stream_key
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.batch_size = batch_size
        self.block_ms = block_ms
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
        """Main consumer loop with error recovery."""
        if not self.redis_client:
            logger.warning(f"No redis client for {self.stream_key} — consumer inactive")
            return

        logger.info(f"Listening to stream {self.stream_key} via XREADGROUP...")
        streams = {self.stream_key: ">"}

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
                            await self.process_message(message_id, data)
                        except Exception:
                            logger.exception(
                                f"Error processing message {message_id} from {self.stream_key}"
                            )
                        await self.redis_client.xack(
                            self.stream_key, self.group_name, message_id
                        )
            except asyncio.CancelledError:
                logger.info(f"Consumer {self.consumer_name} cancelled")
                break
            except Exception:
                logger.exception(f"Stream read error on {self.stream_key}")
                await asyncio.sleep(1)
