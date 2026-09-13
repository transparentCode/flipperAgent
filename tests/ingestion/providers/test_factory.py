from __future__ import annotations

import asyncio

import pytest

from apps.ingestion_app.providers.factory import (
    build_historical_providers,
    referenced_provider_ids,
    validate_provider_configuration,
    wait_until_historical_providers_idle,
)
from tests.ingestion.runtime.test_supervisor import _settings


class _ProviderResource:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id


class _BlockingIdleProvider:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.wait_calls = 0

    async def wait_until_idle(self) -> None:
        self.wait_calls += 1
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


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


@pytest.mark.asyncio
async def test_provider_idle_barrier_deduplicates_and_orders_waits() -> None:
    native = _BlockingIdleProvider("native")
    ccxt = _BlockingIdleProvider("ccxt")
    barrier = asyncio.create_task(
        wait_until_historical_providers_idle(
            {"z-native": native, "a-ccxt": ccxt, "alias": native}
        )
    )

    await asyncio.wait_for(native.started.wait(), 1)
    await asyncio.wait_for(ccxt.started.wait(), 1)
    assert native.wait_calls == 1
    assert ccxt.wait_calls == 1
    assert not barrier.done()

    native.release.set()
    ccxt.release.set()
    await asyncio.wait_for(barrier, 1)


@pytest.mark.asyncio
async def test_provider_idle_barrier_cleans_siblings_and_reraises_original_failure() -> (
    None
):
    failing = _BlockingIdleProvider("failing")
    waiting = _BlockingIdleProvider("waiting")
    failure = RuntimeError("idle wait failed")

    async def fail() -> None:
        failing.wait_calls += 1
        failing.started.set()
        await asyncio.sleep(0)
        raise failure

    failing.wait_until_idle = fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError) as raised:
        await wait_until_historical_providers_idle(
            {"a-failing": failing, "b-waiting": waiting}
        )

    assert raised.value is failure
    await asyncio.wait_for(waiting.started.wait(), 1)
    assert waiting.cancelled.is_set()


@pytest.mark.asyncio
async def test_provider_idle_barrier_cancellation_cleans_every_wait_task() -> None:
    first = _BlockingIdleProvider("first")
    second = _BlockingIdleProvider("second")
    barrier = asyncio.create_task(
        wait_until_historical_providers_idle({"first": first, "second": second})
    )
    await asyncio.wait_for(first.started.wait(), 1)
    await asyncio.wait_for(second.started.wait(), 1)

    barrier.cancel()
    with pytest.raises(asyncio.CancelledError):
        await barrier

    assert first.cancelled.is_set()
    assert second.cancelled.is_set()
