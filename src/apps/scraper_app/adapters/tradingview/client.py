"""Async fetch of one TradingView series over the anonymous WebSocket.

One connection per read. The socket sits behind a small transport protocol so
tests replay recorded exchanges without a network.
"""

from __future__ import annotations

import asyncio
import secrets
import string
from collections.abc import Awaitable, Callable
from typing import Protocol

from apps.scraper_app.adapters.tradingview import protocol
from apps.scraper_app.adapters.tradingview.protocol import (
    SeriesAccumulator,
    SeriesResult,
)
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError
from apps.scraper_app.settings import TradingViewSettings
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_SESSION_ALPHABET = string.ascii_lowercase + string.digits
_CLOSE_CODE_TOO_BIG = 1009


class TransportClosed(Exception):
    """The peer closed the connection before the exchange finished."""

    def __init__(self, reason: str = "", *, oversize: bool = False) -> None:
        super().__init__(reason or "connection closed")
        self.oversize = oversize


class Transport(Protocol):
    async def send(self, text: str) -> None: ...

    async def recv(self) -> str: ...

    async def close(self) -> None: ...


Connector = Callable[[], Awaitable[Transport]]


class _WebsocketsTransport:
    def __init__(self, connection: object) -> None:
        self._connection = connection

    async def send(self, text: str) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            await self._connection.send(text)  # type: ignore[attr-defined]
        except ConnectionClosed as exc:
            raise TransportClosed(str(exc)) from exc

    async def recv(self) -> str:
        from websockets.exceptions import ConnectionClosed

        try:
            message = await self._connection.recv()  # type: ignore[attr-defined]
        except ConnectionClosed as exc:
            rcvd = getattr(exc, "rcvd", None)
            raise TransportClosed(
                str(exc), oversize=getattr(rcvd, "code", None) == _CLOSE_CODE_TOO_BIG
            ) from exc
        return message if isinstance(message, str) else message.decode("utf-8")

    async def close(self) -> None:
        await self._connection.close()  # type: ignore[attr-defined]


def websocket_connector(settings: TradingViewSettings) -> Connector:
    """Connector over the declared ``websockets`` package."""

    async def connect_once() -> Transport:
        from websockets.asyncio.client import connect

        connection = await connect(
            settings.ws_url,
            origin=settings.origin,
            additional_headers={"User-Agent": _USER_AGENT},
            open_timeout=settings.connect_timeout_seconds,
            close_timeout=2,  # a slow close handshake must not extend the deadline
            max_size=settings.max_response_bytes,
            ping_interval=None,  # TradingView heartbeats are answered in-band
        )
        return _WebsocketsTransport(connection)

    return connect_once


def _new_session_id() -> str:
    return "cs_" + "".join(secrets.choice(_SESSION_ALPHABET) for _ in range(12))


class TradingViewClient:
    """Fetch one series; return a complete result or raise a typed error."""

    def __init__(
        self,
        settings: TradingViewSettings,
        *,
        connector: Connector | None = None,
        session_factory: Callable[[], str] = _new_session_id,
    ) -> None:
        self._settings = settings
        self._connector = connector or websocket_connector(settings)
        self._session_factory = session_factory

    async def fetch_series(
        self, request_symbol: str, resolution: str, n_bars: int
    ) -> SeriesResult:
        try:
            async with asyncio.timeout(self._settings.read_deadline_seconds):
                return await self._exchange(request_symbol, resolution, n_bars)
        except TimeoutError as exc:
            raise ScraperError(
                errors.TIMEOUT,
                f"no complete answer within {self._settings.read_deadline_seconds}s",
            ) from exc

    async def _exchange(
        self, request_symbol: str, resolution: str, n_bars: int
    ) -> SeriesResult:
        try:
            transport = await self._connector()
        except ScraperError:
            raise
        except Exception as exc:
            raise ScraperError(
                errors.CONNECT_FAILED, f"{type(exc).__name__}: {exc}"
            ) from exc
        try:
            return await self._run(transport, request_symbol, resolution, n_bars)
        finally:
            try:
                await transport.close()
            except Exception:
                logger.debug("closing the TradingView socket failed", exc_info=True)

    async def _run(
        self, transport: Transport, request_symbol: str, resolution: str, n_bars: int
    ) -> SeriesResult:
        accumulator = SeriesAccumulator()
        received = 0
        try:
            session = self._session_factory()
            for frame in protocol.build_requests(
                session, request_symbol, resolution, n_bars
            ):
                await transport.send(frame)
            while not accumulator.completed:
                raw = await transport.recv()
                received += len(raw.encode("utf-8"))
                if received > self._settings.max_response_bytes:
                    raise ScraperError(
                        errors.OVERSIZE,
                        f"more than {self._settings.max_response_bytes} bytes received",
                    )
                for message in protocol.decode_message(raw):
                    if message.heartbeat:
                        await transport.send(protocol.heartbeat_reply(message))
                    accumulator.feed(message)
        except TransportClosed as exc:
            if exc.oversize:
                raise ScraperError(errors.OVERSIZE, str(exc)) from exc
            if not accumulator.completed:
                raise ScraperError(errors.INCOMPLETE, f"closed early: {exc}") from exc
        return accumulator.result()


__all__ = [
    "Connector",
    "TradingViewClient",
    "Transport",
    "TransportClosed",
    "websocket_connector",
]
