"""Bounded thread-to-event-loop bridge for Binance websocket callbacks."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class _BridgeControl:
    """An urgent control signal that must be observed by the consumer."""

    reason: str
    detail: str | None = None


class _BoundedCallbackBridge:
    """Admit SDK callbacks before they can enter the event-loop ready queue."""

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._events: deque[object] = deque()
        self._urgent_control: _BridgeControl | None = None
        self._lock = Lock()
        self._drain_scheduled = False
        self._closed = False

    def offer(
        self,
        event: object,
        *,
        overflow_control: _BridgeControl,
    ) -> bool:
        """Admit one event and return whether a drain callback is needed."""
        with self._lock:
            if self._closed:
                return False
            if len(self._events) < self._maxsize:
                self._events.append(event)
            elif self._urgent_control is None:
                self._urgent_control = overflow_control

            if self._drain_scheduled:
                return False
            self._drain_scheduled = True
            return True

    def take_batch(self) -> tuple[tuple[object, ...], _BridgeControl | None]:
        with self._lock:
            events = tuple(self._events)
            self._events.clear()
            urgent_control = self._urgent_control
            self._urgent_control = None
            self._drain_scheduled = False
            return events, urgent_control

    def cancel_scheduled_drain(self) -> None:
        with self._lock:
            self._drain_scheduled = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._events.clear()
            self._urgent_control = None


__all__ = ["_BoundedCallbackBridge", "_BridgeControl"]
