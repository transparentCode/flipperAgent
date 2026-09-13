"""Provider configuration validation and historical-provider construction."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from apps.ingestion_app.providers.base import HistoricalCandleProvider
from apps.ingestion_app.settings import IngestionSettings

SUPPORTED_PROVIDER_IDS = frozenset({"binance_native", "ccxt_binance"})

ProviderConstructor = Callable[..., HistoricalCandleProvider]
ProviderResourceCloser = Callable[[list[Any]], Awaitable[None]]


def referenced_provider_ids(settings: IngestionSettings) -> frozenset[str]:
    """Return provider IDs referenced by configured instrument settings."""
    referenced: set[str] = set()
    for asset in settings.assets.values():
        for instrument in asset.instruments.values():
            referenced.add(instrument.live_provider)
            referenced.update(instrument.historical_providers)
    return frozenset(referenced)


def validate_provider_configuration(settings: IngestionSettings) -> frozenset[str]:
    """Validate configured provider references and return the referenced IDs."""
    referenced = referenced_provider_ids(settings)
    unsupported = referenced - SUPPORTED_PROVIDER_IDS
    if unsupported:
        raise ValueError(
            "unsupported ingestion provider IDs: " + ", ".join(sorted(unsupported))
        )

    for provider_id in sorted(referenced):
        provider = settings.providers[provider_id]
        if not provider.enabled:
            raise ValueError(f"referenced provider '{provider_id}' is disabled")
        if provider_id == "ccxt_binance" and not provider.exchange_id:
            raise ValueError("ccxt_binance requires an exchange_id")

    for asset in settings.assets.values():
        if not asset.enabled:
            continue
        for instrument_id, instrument in asset.instruments.items():
            if instrument.live_provider != "binance_native":
                raise ValueError(
                    f"enabled instrument '{instrument_id}' requires unsupported "
                    f"live provider '{instrument.live_provider}'"
                )
    return referenced


async def build_historical_providers(
    settings: IngestionSettings,
    referenced: frozenset[str],
    *,
    native_provider_factory: ProviderConstructor,
    ccxt_provider_factory: ProviderConstructor,
    close_resources: ProviderResourceCloser,
) -> tuple[dict[str, HistoricalCandleProvider], list[Any]]:
    """Construct referenced historical providers with caller-owned cleanup.

    The bootstrap owns the resource lifecycle.  Constructor callables are
    supplied by the caller so existing composition seams remain intact while
    this module stays free of a global provider registry.
    """
    providers: dict[str, HistoricalCandleProvider] = {}
    owned_resources: list[Any] = []

    if "binance_native" in referenced:
        provider = native_provider_factory(
            attempt_timeout_seconds=settings.recovery.provider_attempt_timeout_seconds,
            max_concurrency=settings.recovery.max_concurrency,
        )
        providers["binance_native"] = provider
        owned_resources.append(provider)

    try:
        if "ccxt_binance" in referenced:
            exchange_id = settings.providers["ccxt_binance"].exchange_id
            if exchange_id is None:  # pragma: no cover - validated above
                raise ValueError("ccxt_binance requires an exchange_id")
            provider = ccxt_provider_factory(
                provider_id="ccxt_binance",
                exchange_id=exchange_id,
                attempt_timeout_seconds=(
                    settings.recovery.provider_attempt_timeout_seconds
                ),
                max_concurrency=settings.recovery.max_concurrency,
            )
            providers["ccxt_binance"] = provider
            owned_resources.append(provider)
    except BaseException:
        await close_resources(owned_resources)
        raise

    return providers, owned_resources


async def wait_until_historical_providers_idle(
    providers: Mapping[str, HistoricalCandleProvider],
) -> None:
    """Await one bounded idle operation for each unique owned provider."""
    tasks: list[asyncio.Task[None]] = []
    seen_provider_ids: set[int] = set()
    try:
        for provider_id, provider in sorted(providers.items()):
            object_id = id(provider)
            if object_id in seen_provider_ids:
                continue
            seen_provider_ids.add(object_id)
            wait_coroutine = provider.wait_until_idle()
            try:
                task = asyncio.create_task(
                    wait_coroutine,
                    name=f"ingestion-provider-idle:{provider_id}",
                )
            except BaseException:
                wait_coroutine.close()
                raise
            tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


__all__ = [
    "SUPPORTED_PROVIDER_IDS",
    "build_historical_providers",
    "referenced_provider_ids",
    "validate_provider_configuration",
    "wait_until_historical_providers_idle",
]
