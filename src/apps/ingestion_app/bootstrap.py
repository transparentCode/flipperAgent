"""Runnable application composition for ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI

from apps.ingestion_app.api.app import create_app
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.planning import (
    IngestionPlan,
    compile_ingestion_plan,
)
from apps.ingestion_app.providers.base import HistoricalCandleProvider
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
from apps.ingestion_app.providers.factory import (
    SUPPORTED_PROVIDER_IDS,
    build_historical_providers,
    referenced_provider_ids,
    validate_provider_configuration,
    wait_until_historical_providers_idle,
)
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
_SUPPORTED_PROVIDER_IDS = SUPPORTED_PROVIDER_IDS


def _referenced_provider_ids(settings: IngestionSettings) -> frozenset[str]:
    return referenced_provider_ids(settings)


def _validate_provider_configuration(settings: IngestionSettings) -> frozenset[str]:
    return validate_provider_configuration(settings)


async def _build_historical_providers(
    settings: IngestionSettings,
    referenced: frozenset[str],
) -> tuple[dict[str, HistoricalCandleProvider], list[Any]]:
    return await build_historical_providers(
        settings,
        referenced,
        native_provider_factory=BinanceNativeHistoricalProvider,
        ccxt_provider_factory=CCXTHistoricalProvider,
        close_resources=_close_providers,
    )


def _supervisor_factory(
    *,
    repository: CandleRepository,
    ingestion_service: CandleIngestionService,
    htf_service: HTFAggregationService,
    recovery_engine: RecoveryEngine,
    live_provider: BinanceWebSocketManager,
    observability: IngestionObservability,
) -> Callable[[IngestionPlan], RuntimeSupervisor]:
    def build(plan: IngestionPlan) -> RuntimeSupervisor:
        return RuntimeSupervisor(
            plan=plan,
            live_provider=live_provider,
            repository=repository,
            ingestion_service=ingestion_service,
            htf_service=htf_service,
            recovery_engine=recovery_engine,
            observability=observability,
        )

    return build


def _plan_factory(
    *,
    composed_live_provider_ids: frozenset[str],
    owned_historical_provider_ids: frozenset[str],
) -> Callable[[IngestionSettings], IngestionPlan]:
    """Create a pure settings-to-plan seam for the composed application."""

    def build(candidate_settings: IngestionSettings) -> IngestionPlan:
        plan = compile_ingestion_plan(
            candidate_settings,
            live_provider_ids=composed_live_provider_ids,
            historical_provider_ids=owned_historical_provider_ids,
        )
        if not plan.lanes:
            return plan

        referenced = _validate_provider_configuration(candidate_settings)
        missing_provider_ids = referenced - (
            composed_live_provider_ids | owned_historical_provider_ids
        )
        if missing_provider_ids:
            raise ValueError(
                "candidate settings reference providers not owned by the application: "
                + ", ".join(sorted(missing_provider_ids))
            )
        return plan

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


@dataclass(slots=True)
class _LifespanResources:
    """Own resources created by the ingestion lifespan.

    This is deliberately a cleanup ledger rather than a service registry. The
    application still constructs and wires each service explicitly in the
    lifespan below; this object only makes partial-startup ownership and the
    dependency-ordered cleanup path explicit.
    """

    config_manager: ConfigManager
    db_cleanup_required: bool = False
    owned_provider_resources: list[Any] = field(default_factory=list)
    controller: RuntimeController | None = None
    retention_janitor: RetentionJanitor | None = None
    retention_task: asyncio.Task[Any] | None = None
    publisher_task: asyncio.Task[Any] | None = None

    async def aclose(self) -> None:
        """Close owned resources in the established lifespan order."""
        if self.controller is not None:
            try:
                await self.controller.close()
            except Exception:
                _LOGGER.warning(
                    "Failed to close ingestion runtime controller",
                    exc_info=True,
                )

        if self.retention_task is not None and self.retention_janitor is not None:
            await self.retention_janitor.stop()
            await _cancel_task(self.retention_task)

        if self.publisher_task is not None:
            await _cancel_task(self.publisher_task)

        await _close_providers(self.owned_provider_resources)

        if self.db_cleanup_required:
            try:
                await DBPoolManager.close_pools()
            except Exception:
                _LOGGER.warning("Failed to close ingestion DB pools", exc_info=True)

        self.config_manager.shutdown()


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
        resources = _LifespanResources(config_manager=manager)

        try:
            settings = load_ingestion_settings(manager)
            _validate_provider_configuration(settings)

            resources.db_cleanup_required = True
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
            resources.owned_provider_resources.extend(provider_resources)
            live_provider = BinanceWebSocketManager(
                stream_url=settings.websocket.stream_url,
                queue_maxsize=settings.websocket.queue_maxsize,
                lifecycle_timeout_seconds=settings.websocket.lifecycle_timeout_seconds,
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
                observability=application_observability,
            )
            plan_factory = _plan_factory(
                composed_live_provider_ids=frozenset({live_provider.provider_id}),
                owned_historical_provider_ids=frozenset(historical_providers),
            )
            controller = RuntimeController(
                settings=settings,
                plan_factory=plan_factory,
                supervisor_factory=factory,
                observability=application_observability,
                historical_provider_quiescence=lambda: (
                    wait_until_historical_providers_idle(historical_providers)
                ),
            )
            resources.controller = controller
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
            resources.retention_janitor = retention_janitor

            await controller.start()
            app.state.config_manager = manager
            app.state.runtime_controller = controller
            app.state.config_service = config_service
            app.state.lifecycle_reconciler = lifecycle_reconciler
            app.state.retention_janitor = retention_janitor
            app.state.observability = application_observability
            resources.retention_task = asyncio.create_task(
                retention_janitor.run(),
                name="ingestion-retention-janitor",
            )
            app.state.retention_task = resources.retention_task
            resources.publisher_task = asyncio.create_task(
                _run_publisher_connection_loop(
                    config_manager=manager,
                    repository=repository,
                    settings=settings,
                    observability=application_observability,
                    lifecycle_reconciler=lifecycle_reconciler,
                ),
                name="ingestion-outbox-publisher",
            )
            app.state.publisher_task = resources.publisher_task
            _LOGGER.info("ingestion application started")
            yield
        finally:
            await resources.aclose()
            _LOGGER.info("ingestion application stopped")

    return create_app(lifespan=lifespan)


__all__ = ["create_application"]
