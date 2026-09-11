"""Shared connection factories for Valkey and DB pools."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from math import isfinite
from urllib.parse import parse_qs, urlsplit

import valkey.asyncio as valkey
from valkey.asyncio.connection import parse_url as _parse_valkey_url

from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

_VALKEY_CONNECT_RETRIES = 3
_VALKEY_RETRY_DELAYS = [1, 2, 4]  # exponential backoff seconds
CleanupCallback = Callable[[Awaitable[object], bool], Awaitable[None]]


def _validate_decision_valkey_uri(uri: str, timeout: float) -> None:
    """Reject URI options that would bypass Decision's explicit wire budget."""

    query = parse_qs(urlsplit(uri).query, keep_blank_values=True)
    # Use the installed driver's parser for values and precedence.  The raw
    # query is inspected only for duplicate detection because the driver
    # intentionally keeps the first value and would otherwise hide a second
    # option.
    parsed_options = _parse_valkey_url(uri)
    for name in ("socket_timeout", "socket_connect_timeout"):
        values = query.get(name, ())
        if not values:
            continue
        if len(values) != 1:
            raise ValueError(f"conflicting Valkey URI option: {name}")
        value = parsed_options.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
            or value != timeout
        ):
            raise ValueError(f"conflicting Valkey URI option: {name}")

    # No URI retry override is part of the Decision contract.  Rejecting the
    # whole family is both safer and faithful to the native parser's first
    # value/unquote semantics; it also prevents arbitrary truthy strings or a
    # duplicate query from silently enabling retries.
    for name in ("retry_on_timeout", "retry_on_error", "retry"):
        if name in query:
            raise ValueError(f"conflicting Valkey URI option: {name}")


def _masked_target(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.hostname is not None:
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.hostname}{port}"
    return "(unix socket)" if parsed.path else "(configured URI)"


async def create_valkey_client(
    config_mgr: ConfigManager | None = None,
    *,
    io_timeout_seconds: float | None = None,
    cleanup_callback: CleanupCallback | None = None,
) -> valkey.Valkey:
    """Create a Valkey (redis-compatible) async client from config.

    Resolution order:
      1. ``VALKEY_URI`` env var  (Docker override)
      2. ``REDIS_URI``  env var  (legacy compat)
      3. ``valkey.uri`` from config YAML
      4. Hardcoded fallback ``redis://localhost:6379/0``

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) on connection failure.
    """
    uri = os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
    if not uri:
        if config_mgr is None:
            config_mgr = ConfigManager()
        uri = config_mgr.get("valkey.uri", "redis://localhost:6379/0")

    if io_timeout_seconds is not None:
        if (
            isinstance(io_timeout_seconds, bool)
            or not isinstance(io_timeout_seconds, (int, float))
            or not isfinite(float(io_timeout_seconds))
            or io_timeout_seconds <= 0
        ):
            raise ValueError("io_timeout_seconds must be finite and positive")
        _validate_decision_valkey_uri(uri, float(io_timeout_seconds))
    if cleanup_callback is not None and io_timeout_seconds is None:
        raise TypeError("cleanup_callback requires io_timeout_seconds")
    bounded_cleanup = io_timeout_seconds is not None and cleanup_callback is not None

    logger.info(f"Connecting Valkey client → {_masked_target(uri)}")

    last_err: Exception | None = None
    for attempt in range(_VALKEY_CONNECT_RETRIES):
        client: valkey.Valkey | None = None
        try:
            kwargs: dict[str, object] = {"decode_responses": True}
            if io_timeout_seconds is not None:
                kwargs.update(
                    {
                        "socket_timeout": float(io_timeout_seconds),
                        "socket_connect_timeout": float(io_timeout_seconds),
                        "retry_on_timeout": False,
                        "retry_on_error": [],
                    }
                )
            client = valkey.Valkey.from_url(uri, **kwargs)
            if io_timeout_seconds is None:
                await client.ping()
            else:
                async with asyncio.timeout(float(io_timeout_seconds)):
                    await client.ping()
            logger.info("Valkey client connected")
            return client
        except asyncio.CancelledError:
            if client is not None:
                if bounded_cleanup:
                    try:
                        if cleanup_callback is None:
                            raise RuntimeError(
                                "bounded Valkey cleanup callback missing"
                            )
                        await cleanup_callback(client.aclose(), False)
                    except asyncio.CancelledError:
                        raise
                    except Exception as close_error:  # noqa: BLE001
                        logger.warning(
                            "Valkey candidate cleanup interrupted (%s)",
                            type(close_error).__name__,
                        )
                else:
                    try:
                        await asyncio.shield(client.aclose())
                    except Exception:
                        logger.warning(
                            "Failed to close cancelled Valkey connection candidate",
                            exc_info=True,
                        )
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
            retrying = attempt < _VALKEY_CONNECT_RETRIES - 1
            if client is not None:
                try:
                    if bounded_cleanup:
                        if cleanup_callback is None:
                            raise RuntimeError(
                                "bounded Valkey cleanup callback missing"
                            )
                        await cleanup_callback(client.aclose(), retrying)
                    else:
                        await client.aclose()
                except asyncio.CancelledError:
                    raise
                except Exception as close_error:
                    if bounded_cleanup:
                        logger.warning(
                            "Valkey candidate cleanup failed (%s); retries aborted",
                            type(close_error).__name__,
                        )
                        raise ConnectionError(
                            "Valkey candidate cleanup was not confirmed; retries aborted"
                        ) from close_error
                    logger.warning(
                        "Failed to close Valkey connection candidate after failure",
                        exc_info=True,
                    )
            delay = (
                _VALKEY_RETRY_DELAYS[attempt]
                if attempt < len(_VALKEY_RETRY_DELAYS)
                else _VALKEY_RETRY_DELAYS[-1]
            )
            if bounded_cleanup:
                logger.warning(
                    "Valkey connection attempt %s/%s failed (%s); retrying in %ss",
                    attempt + 1,
                    _VALKEY_CONNECT_RETRIES,
                    type(e).__name__,
                    delay,
                )
            else:
                logger.warning(
                    f"Valkey connection attempt {attempt + 1}/{_VALKEY_CONNECT_RETRIES} failed: {e}. "
                    f"Retrying in {delay}s..."
                )
            if not bounded_cleanup or retrying:
                await asyncio.sleep(delay)

    if bounded_cleanup:
        raise ConnectionError(
            "Failed to connect to Valkey after "
            f"{_VALKEY_CONNECT_RETRIES} attempts ({type(last_err).__name__})"
        )
    raise ConnectionError(
        f"Failed to connect to Valkey after {_VALKEY_CONNECT_RETRIES} attempts: {last_err}"
    )


async def init_db_pools(
    config_mgr: ConfigManager | None = None,
    *,
    connect_timeout: float | None = None,
    return_created: bool = False,
    cleanup_timeout: float | None = None,
    retained_cleanup_tasks: set[asyncio.Task[object]] | None = None,
    cleanup_remaining: Callable[[], float] | None = None,
) -> bool | None:
    """Initialize DB connection pools via DBPoolManager.

    This is a thin wrapper that ensures ConfigManager is passed through.
    The actual retry logic and POSTGRES_URI env var override live in
    DBPoolManager.init_pools().
    """
    kwargs: dict[str, object] = {"config_manager": config_mgr}
    if connect_timeout is not None:
        kwargs["connect_timeout"] = connect_timeout
    if return_created:
        kwargs["return_created"] = True
    if cleanup_timeout is not None:
        kwargs["cleanup_timeout"] = cleanup_timeout
    if retained_cleanup_tasks is not None:
        kwargs["retained_cleanup_tasks"] = retained_cleanup_tasks
    if cleanup_remaining is not None:
        kwargs["cleanup_remaining"] = cleanup_remaining
    created = await DBPoolManager.init_pools(**kwargs)
    logger.info("DB pools initialized")
    return created if return_created else None
