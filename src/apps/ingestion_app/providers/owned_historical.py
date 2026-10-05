"""Shared lifecycle plumbing for historical providers that own their SDK calls."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from apps.ingestion_app.providers.base import (
    ProviderRateLimitedError,
    TransportDeadlineExceeded,
    parse_retry_after_seconds,
)
from apps.ingestion_app.transport.ownership import (
    OwnedAsyncCall,
    OwnedBlockingCall,
    OwnedOperationTracker,
    wait_for_owned_call,
)
from libs.common.exceptions import DataIngestionError


class OwnedHistoricalProvider[CallT: (OwnedBlockingCall, OwnedAsyncCall)](ABC):
    """Own admission state, the idle barrier, the rate-limit gate, and close.

    A subclass supplies its SDK request, error classification, decoding,
    admission rule, and close call. ``CallT`` is the owned-call type that wraps
    its SDK: ``OwnedBlockingCall`` for a blocking SDK, ``OwnedAsyncCall`` for an
    async one. A subclass sets ``provider_id``, ``_provider_label`` (the word
    in lifecycle errors), ``_close_operation`` (which also names the close
    drain), and ``_close_failure_message``, and implements ``_admit`` and
    ``_new_close_call``.
    """

    provider_id: str
    _provider_label: str
    _close_operation: str
    _close_failure_message: str

    def __init__(
        self,
        *,
        attempt_timeout_seconds: float,
        max_concurrency: int,
        monotonic_fn: Callable[[], float],
    ) -> None:
        self.attempt_timeout_seconds = float(attempt_timeout_seconds)
        self.max_concurrency = max_concurrency
        self._monotonic = monotonic_fn
        self._rate_limited_until = 0.0
        self._ownership = OwnedOperationTracker(max_concurrency)
        self._closed = False
        self._closing = False
        self._close_call: CallT | None = None
        self._close_cancelled = False
        self._close_operation_succeeded = False

    @property
    def retained_worker_count(self) -> int:
        return self._ownership.retained_count

    @property
    def quarantined(self) -> bool:
        return self._ownership.quarantined

    async def _wait_for_owned_calls_idle(self, *, operation: str) -> None:
        await self._ownership.wait_until_idle(
            timeout_seconds=self.attempt_timeout_seconds,
            timeout_error=lambda: TransportDeadlineExceeded(
                provider_id=self.provider_id,
                operation=operation,
                timeout_seconds=self.attempt_timeout_seconds,
            ),
        )

    async def wait_until_idle(self) -> None:
        """Wait for all provider-owned SDK work and admission to be released."""
        self._check_available("historical provider quiescence")
        await self._wait_for_owned_calls_idle(
            operation="historical provider quiescence"
        )

    def _finish_close_call(self, call: CallT) -> None:
        self._ownership.release(call)
        if self._close_call is not call:
            return
        self._close_call = None
        if call.failed:
            self._quarantine()
            return
        self._close_operation_succeeded = True
        if self._close_cancelled:
            self._closed = True
            self._closing = False
            self._close_cancelled = False

    def _quarantine(self) -> None:
        self._ownership.quarantine()

    def _check_available(self, operation: str, *, allow_closing: bool = False) -> None:
        if self._ownership.quarantined:
            raise TransportDeadlineExceeded(
                provider_id=self.provider_id,
                operation=f"quarantined {operation}",
                timeout_seconds=self.attempt_timeout_seconds,
            )
        if self._closed:
            raise DataIngestionError(
                f"{self._provider_label} historical provider is closed"
            )
        if self._closing and not allow_closing:
            raise DataIngestionError(
                f"{self._provider_label} historical provider is closing"
            )

    @abstractmethod
    def _admit(
        self,
        operation: str,
        *,
        call: CallT,
        exclusive: bool = False,
        allow_closing: bool = False,
    ) -> None:
        """Admit ``call`` or raise; each adapter owns its exclusive-admission rule."""

    @abstractmethod
    def _new_close_call(self, loop: asyncio.AbstractEventLoop) -> CallT:
        """Build the owned call that closes the SDK client.

        The call must report completion through ``self._finish_close_call``.
        """

    def _owned_call_deadline_error(self, operation: str) -> BaseException:
        self._quarantine()
        return TransportDeadlineExceeded(
            provider_id=self.provider_id,
            operation=operation,
            timeout_seconds=self.attempt_timeout_seconds,
        )

    async def _wait_owned_call(
        self,
        call: CallT,
        *,
        operation: str,
    ) -> Any:
        return await wait_for_owned_call(
            call,
            timeout_seconds=self.attempt_timeout_seconds,
            timeout_error=lambda _exc: self._owned_call_deadline_error(operation),
        )

    async def _drain_owned_calls(self) -> None:
        await self._wait_for_owned_calls_idle(
            operation=f"{self._close_operation} drain"
        )

    def _raise_if_rate_limited(self) -> None:
        remaining = self._rate_limited_until - self._monotonic()
        if remaining > 0:
            raise ProviderRateLimitedError(
                provider_id=self.provider_id,
                retry_after_seconds=remaining,
            )

    def _note_rate_limit(self, headers: object) -> ProviderRateLimitedError:
        retry_after = parse_retry_after_seconds(headers)
        now = self._monotonic()
        self._rate_limited_until = max(
            self._rate_limited_until,
            now + retry_after,
        )
        return ProviderRateLimitedError(
            provider_id=self.provider_id,
            retry_after_seconds=self._rate_limited_until - now,
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._check_available(self._close_operation)
        if self._closing:
            raise DataIngestionError(
                f"{self._provider_label} historical provider is closing"
            )
        self._closing = True
        self._close_cancelled = False
        self._close_operation_succeeded = False
        call: CallT | None = None
        loop = asyncio.get_running_loop()
        try:
            await self._drain_owned_calls()
            call = self._new_close_call(loop)
            self._admit(
                self._close_operation,
                call=call,
                exclusive=True,
                allow_closing=True,
            )
            self._close_call = call
            call.start()
            await self._wait_owned_call(call, operation=self._close_operation)
            await self._drain_owned_calls()
        except asyncio.CancelledError:
            self._close_cancelled = True
            if call is None:
                self._closing = False
                self._close_cancelled = False
                self._close_operation_succeeded = False
            elif call.finished or self._close_operation_succeeded:
                if call.failed or self._ownership.quarantined:
                    self._quarantine()
                else:
                    self._closed = True
                    self._closing = False
                    self._close_cancelled = False
            raise
        except DataIngestionError:
            self._quarantine()
            raise
        except Exception as exc:
            self._quarantine()
            raise DataIngestionError(self._close_failure_message) from exc
        else:
            self._closed = True
            self._close_cancelled = False


__all__ = ["OwnedHistoricalProvider"]
