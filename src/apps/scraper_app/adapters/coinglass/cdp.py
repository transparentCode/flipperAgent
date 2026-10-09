"""Raw Chrome DevTools Protocol client on ``websockets``.

One fresh connection per cycle. Every command has a deadline; a closed socket
fails every command in flight at once. Events are dropped (never buffered).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

# Frame-level debug logging would print cookie values: pin this logger to INFO.
_wire_logger = logging.getLogger(__name__ + ".wire")
_wire_logger.setLevel(logging.INFO)

_CLOSE_CODE_TOO_BIG = 1009
_VERSION_BYTES = 65536
_CLOSE_TIMEOUT = 2.0


class CommandTimeout(ScraperError):
    """A CDP command got no answer within its deadline."""

    def __init__(self, method: str, seconds: float) -> None:
        super().__init__(errors.ENGINE_ERROR, f"{method} timed out after {seconds:g}s")
        self.method = method


def _fetch_version(url: str, timeout: float) -> dict[str, Any]:
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("engine_url must be http or https")
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read(_VERSION_BYTES))


def rewrite_socket_url(engine_url: str, advertised: str) -> str:
    """The engine advertises host ``0.0.0.0``; connect to the configured host."""
    base = urlsplit(engine_url)
    path = urlsplit(advertised).path
    return f"ws://{base.netloc}{path}"


class CdpConnection:
    def __init__(self, ws: Any, command_timeout: float) -> None:
        self._ws = ws
        self._command_timeout = command_timeout
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._closed_reason: str | None = None
        self._oversize = False
        self._reader = asyncio.create_task(self._read(), name="coinglass-cdp-reader")

    @classmethod
    async def open(
        cls,
        engine_url: str,
        *,
        connect_timeout: float,
        command_timeout: float,
        max_size: int,
    ) -> CdpConnection:
        from websockets.asyncio.client import connect

        try:
            async with asyncio.timeout(connect_timeout):
                info = await asyncio.to_thread(
                    _fetch_version,
                    engine_url.rstrip("/") + "/json/version",
                    connect_timeout,
                )
                ws = await connect(
                    rewrite_socket_url(engine_url, str(info["webSocketDebuggerUrl"])),
                    open_timeout=connect_timeout,
                    close_timeout=_CLOSE_TIMEOUT,
                    max_size=max_size,
                    ping_interval=None,
                    logger=_wire_logger,
                )
        except Exception as exc:
            raise ScraperError(
                errors.ENGINE_UNREACHABLE, f"{type(exc).__name__}: {str(exc)[:150]}"
            ) from exc
        return cls(ws, command_timeout)

    async def _read(self) -> None:
        reason = "connection closed"
        try:
            async for raw in self._ws:
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                future = self._pending.pop(message.get("id"), None)
                if future is not None and not future.done():
                    future.set_result(message)
        except Exception as exc:  # noqa: BLE001 - the socket died
            reason = f"{type(exc).__name__}: {str(exc)[:100]}"
            closing = (getattr(exc, "rcvd", None), getattr(exc, "sent", None))
            self._oversize = any(
                getattr(frame, "code", None) == _CLOSE_CODE_TOO_BIG for frame in closing
            )
        finally:
            self._closed_reason = reason
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(self._closed_error())
            self._pending.clear()

    def _closed_error(self) -> ScraperError:
        if self._oversize:
            return ScraperError(
                errors.PAYLOAD_TOO_LARGE, "engine message exceeded the size limit"
            )
        return ScraperError(
            errors.ENGINE_UNREACHABLE, self._closed_reason or "connection closed"
        )

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if self._closed_reason is not None:
            raise self._closed_error()
        seconds = self._command_timeout if timeout is None else timeout
        call_id = next(self._ids)
        message: dict[str, Any] = {"id": call_id, "method": method}
        if params:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[call_id] = future
        try:
            async with asyncio.timeout(seconds):
                await self._ws.send(json.dumps(message))
                response = await future
        except TimeoutError as exc:
            raise CommandTimeout(method, seconds) from exc
        except ScraperError:
            raise
        except Exception as exc:
            raise ScraperError(
                errors.ENGINE_UNREACHABLE, f"{type(exc).__name__} sending {method}"
            ) from exc
        finally:
            self._pending.pop(call_id, None)
        if "error" in response:
            error = response["error"] if isinstance(response["error"], dict) else {}
            raise ScraperError(
                errors.ENGINE_ERROR,
                f"{method}: {str(error.get('message', 'error'))[:150]}",
            )
        result = response.get("result", {})
        return result if isinstance(result, dict) else {}

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self._ws.close(), _CLOSE_TIMEOUT + 1)
        except Exception:
            logger.debug("closing the engine socket failed", exc_info=True)
        finally:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader


__all__ = ["CdpConnection", "CommandTimeout", "rewrite_socket_url"]
