"""Runnable application composition for ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from apps.ingestion_app.api.app import create_app
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.base import HistoricalCandleProvider
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.runtime.supervisor import RuntimeSupervisor
from apps.ingestion_app.runtime.websocket import BinanceWebSocketManager
from apps.ingestion_app.services.asset_lifecycle import AssetLifecycleReconciler
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.config_reconciliation import AssetConfigService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.services.retention import RetentionJanitor
from apps.ingestion_app.settings import (
    IngestionSettings,
    load_ingestion_settings,
)
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)
_SUPPORTED_PROVIDER_IDS = frozenset({"binance_native", "ccxt_binance"})


def _referenced_provider_ids(settings: IngestionSettings) -> frozenset[str]:
    referenced: set[str] = set()
    for asset in settings.assets.values():
        for instrument in asset.instruments.values():
            referenced.add(instrument.live_provider)
            referenced.update(instrument.historical_providers)
    return frozenset(referenced)


def _validate_provider_configuration(settings: IngestionSettings) -> frozenset[str]:
    referenced = _referenced_provider_ids(settings)
    unsupported = referenced - _SUPPORTED_PROVIDER_IDS
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


async def _build_historical_providers(
    settings: IngestionSettings,
    referenced: frozenset[str],
) -> tuple[dict[str, HistoricalCandleProvider], list[Any]]:
    providers: dict[str, HistoricalCandleProvider] = {}
    owned_resources: list[Any] = []

    if "binance_native" in referenced:
        provider = BinanceNativeHistoricalProvider()
        providers["binance_native"] = provider
        owned_resources.append(provider)

    try:
        if "ccxt_binance" in referenced:
            exchange_id = settings.providers["ccxt_binance"].exchange_id
            if exchange_id is None:  # pragma: no cover - validated above
                raise ValueError("ccxt_binance requires an exchange_id")
            provider = CCXTHistoricalProvider(
                provider_id="ccxt_binance",
                exchange_id=exchange_id,
            )
            providers["ccxt_binance"] = provider
            owned_resources.append(provider)
    except BaseException:
        await _close_providers(owned_resources)
        raise

    return providers, owned_resources


def _supervisor_factory(
    *,
    repository: CandleRepository,
    ingestion_service: CandleIngestionService,
    htf_service: HTFAggregationService,
    recovery_engine: RecoveryEngine,
    live_provider: BinanceWebSocketManager,
    available_provider_ids: frozenset[str],
    observability: IngestionObservability,
) -> Callable[[IngestionSettings], RuntimeSupervisor]:
    def build(candidate_settings: IngestionSettings) -> RuntimeSupervisor:
        referenced_provider_ids = _validate_provider_configuration(candidate_settings)
        missing_provider_ids = referenced_provider_ids - available_provider_ids
        if missing_provider_ids:
            raise ValueError(
                "candidate settings reference providers not owned by the application: "
                + ", ".join(sorted(missing_provider_ids))
            )
        return RuntimeSupervisor(
            settings=candidate_settings,
            live_provider=live_provider,
            repository=repository,
            ingestion_service=ingestion_service,
            htf_service=htf_service,
            recovery_engine=recovery_engine,
            observability=observability,
        )

    return build


async def _run_publisher_connection_loop(
    *,
    config_manager: ConfigManager,
    repository: CandleRepository,
    settings: IngestionSettings,
    observability: IngestionObservability,
    lifecycle_reconciler: AssetLifecycleReconciler,
) -> None:
    """Retry optional Valkey publication without affecting canonical startup."""
    while True:
        client: Any | None = None
        try:
            client = await create_valkey_client(config_manager)
            lifecycle_reconciler.bind_manifest_store(
                AssetManifestStore(
                    client,
                    lifecycle_stream_maxlen=settings.publication.stream_maxlen,
                    lifecycle_stream_approximate=settings.publication.stream_approximate,
                )
            )
            await lifecycle_reconciler.reconcile_all()
            await lifecycle_reconciler.start()
            publisher = OutboxPublisher(
                repository=repository,
                valkey_client=client,
                publication=settings.publication,
                observability=observability,
                on_connection_restored=lifecycle_reconciler.mark_all_managed_dirty,
            )
            await publisher.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.warning("ingestion outbox publisher cycle failed", exc_info=True)
            await asyncio.sleep(settings.publication.error_backoff_seconds)
        finally:
            await lifecycle_reconciler.stop()
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    _LOGGER.warning(
                        "Failed to close ingestion Valkey client",
                        exc_info=True,
                    )


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    if task.done():
        await asyncio.gather(task, return_exceptions=True)
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _close_providers(providers: list[Any]) -> None:
    for provider in reversed(providers):
        try:
            await provider.close()
        except Exception:
            _LOGGER.warning(
                "Failed to close ingestion provider resource", exc_info=True
            )


def create_application(
    *,
    config_manager: ConfigManager | None = None,
    observability: IngestionObservability | None = None,
) -> FastAPI:
    """Create the ingestion application without performing I/O."""

    application_observability = observability or IngestionObservability()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = config_manager or ConfigManager()
        owned_providers: list[Any] = []
        controller: RuntimeController | None = None
        publisher_task: asyncio.Task[Any] | None = None
        retention_janitor: RetentionJanitor | None = None
        retention_task: asyncio.Task[Any] | None = None
        db_init_started = False

        try:
            settings = load_ingestion_settings(manager)
            _validate_provider_configuration(settings)

            db_init_started = True
            await init_db_pools(manager)
            writer_pool = DBPoolManager.get_writer_pool()
            await apply_ingestion_schema(writer_pool)

            (
                historical_providers,
                provider_resources,
            ) = await _build_historical_providers(
                settings,
                _referenced_provider_ids(settings),
            )
            owned_providers.extend(provider_resources)
            live_provider = BinanceWebSocketManager(
                stream_url=settings.websocket.stream_url,
                queue_maxsize=settings.websocket.queue_maxsize,
                observability=application_observability,
            )

            repository = CandleRepository(writer_pool)
            (
                pending_count,
                oldest_pending,
            ) = await repository.fetch_pending_outbox_state()
            application_observability.set_outbox_state(
                pending=pending_count,
                oldest_pending=oldest_pending,
            )
            ingestion_service = CandleIngestionService(
                repository,
                observability=application_observability,
            )
            htf_service = HTFAggregationService(
                repository=repository,
                ingestion_service=ingestion_service,
            )
            recovery_engine = RecoveryEngine(
                providers=historical_providers,
                repository=repository,
                ingestion_service=ingestion_service,
                htf_service=htf_service,
                max_concurrency=settings.recovery.max_concurrency,
                page_limit=settings.recovery.page_limit,
                max_attempts_per_provider=settings.recovery.max_attempts_per_provider,
                retry_backoff_seconds=settings.recovery.retry_backoff_seconds,
                rest_finalization_grace_seconds=(
                    settings.recovery.rest_finalization_grace_seconds
                ),
                observability=application_observability,
            )
            factory = _supervisor_factory(
                repository=repository,
                ingestion_service=ingestion_service,
                htf_service=htf_service,
                recovery_engine=recovery_engine,
                live_provider=live_provider,
                available_provider_ids=frozenset(historical_providers),
                observability=application_observability,
            )
            controller = RuntimeController(
                settings=settings,
                supervisor_factory=factory,
            )
            lifecycle_reconciler = AssetLifecycleReconciler(
                settings_provider=lambda: controller.settings,
                retry_backoff_seconds=settings.publication.error_backoff_seconds,
            )
            config_service = AssetConfigService(
                config_manager=manager,
                runtime_controller=controller,
                on_asset_changed=lifecycle_reconciler.mark_dirty,
            )
            retention_janitor = RetentionJanitor(
                repository=repository,
                settings=settings.retention,
            )

            await controller.start()
            app.state.config_manager = manager
            app.state.runtime_controller = controller
            app.state.config_service = config_service
            app.state.lifecycle_reconciler = lifecycle_reconciler
            app.state.retention_janitor = retention_janitor
            app.state.observability = application_observability
            retention_task = asyncio.create_task(
                retention_janitor.run(),
                name="ingestion-retention-janitor",
            )
            app.state.retention_task = retention_task
            publisher_task = asyncio.create_task(
                _run_publisher_connection_loop(
                    config_manager=manager,
                    repository=repository,
                    settings=settings,
                    observability=application_observability,
                    lifecycle_reconciler=lifecycle_reconciler,
                ),
                name="ingestion-outbox-publisher",
            )
            app.state.publisher_task = publisher_task
            _LOGGER.info("ingestion application started")
            yield
        finally:
            if controller is not None:
                try:
                    await controller.close()
                except Exception:
                    _LOGGER.warning(
                        "Failed to close ingestion runtime controller",
                        exc_info=True,
                    )
            if retention_task is not None and retention_janitor is not None:
                await retention_janitor.stop()
                await _cancel_task(retention_task)
            if publisher_task is not None:
                await _cancel_task(publisher_task)
            await _close_providers(owned_providers)
            if db_init_started:
                try:
                    await DBPoolManager.close_pools()
                except Exception:
                    _LOGGER.warning("Failed to close ingestion DB pools", exc_info=True)
            manager.shutdown()
            _LOGGER.info("ingestion application stopped")

    return create_app(lifespan=lifespan)


__all__ = ["create_application"]
