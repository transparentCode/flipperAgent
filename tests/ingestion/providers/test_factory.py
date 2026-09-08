from __future__ import annotations

import pytest

from apps.ingestion_app.providers.factory import (
    build_historical_providers,
    referenced_provider_ids,
    validate_provider_configuration,
)
from tests.ingestion.runtime.test_supervisor import _settings


class _ProviderResource:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id


@pytest.mark.asyncio
async def test_factory_builds_referenced_providers_with_bootstrap_owned_cleanup() -> (
    None
):
    settings = _settings()
    referenced = validate_provider_configuration(settings)
    assert referenced == referenced_provider_ids(settings)

    constructed: list[tuple[str, dict[str, object]]] = []

    def native_factory(**kwargs: object) -> _ProviderResource:
        constructed.append(("binance_native", kwargs))
        return _ProviderResource("binance_native")

    def ccxt_factory(**kwargs: object) -> _ProviderResource:
        constructed.append(("ccxt_binance", kwargs))
        return _ProviderResource("ccxt_binance")

    closed: list[list[object]] = []

    async def close_resources(resources: list[object]) -> None:
        closed.append(resources)

    providers, owned_resources = await build_historical_providers(
        settings,
        referenced,
        native_provider_factory=native_factory,
        ccxt_provider_factory=ccxt_factory,
        close_resources=close_resources,
    )

    assert set(providers) == {"binance_native", "ccxt_binance"}
    assert [provider_id for provider_id, _kwargs in constructed] == [
        "binance_native",
        "ccxt_binance",
    ]
    assert constructed[0][1] == {
        "attempt_timeout_seconds": settings.recovery.provider_attempt_timeout_seconds,
        "max_concurrency": settings.recovery.max_concurrency,
    }
    assert constructed[1][1] == {
        "provider_id": "ccxt_binance",
        "exchange_id": settings.providers["ccxt_binance"].exchange_id,
        "attempt_timeout_seconds": settings.recovery.provider_attempt_timeout_seconds,
        "max_concurrency": settings.recovery.max_concurrency,
    }
    assert owned_resources == [providers["binance_native"], providers["ccxt_binance"]]
    assert closed == []


@pytest.mark.asyncio
async def test_factory_closes_native_resource_when_ccxt_construction_fails() -> None:
    settings = _settings()
    referenced = referenced_provider_ids(settings)
    native = _ProviderResource("binance_native")
    closed: list[list[object]] = []

    async def close_resources(resources: list[object]) -> None:
        closed.append(resources)

    def fail_ccxt(**kwargs: object) -> _ProviderResource:
        del kwargs
        raise RuntimeError("CCXT unavailable")

    with pytest.raises(RuntimeError, match="CCXT unavailable"):
        await build_historical_providers(
            settings,
            referenced,
            native_provider_factory=lambda **kwargs: native,
            ccxt_provider_factory=fail_ccxt,
            close_resources=close_resources,
        )

    assert closed == [[native]]
