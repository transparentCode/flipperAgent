"""D9C resource ownership, generation construction, and ASGI lifespan."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

from apps.decision_app.api.app import create_app
from apps.decision_app.composition import (
    DecisionComposition,
    build_production_composition,
)
from apps.decision_app.runtime.lifecycle import (
    LifecycleNotificationReader,
    capture_lifecycle_tail,
)
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.service import (
    DecisionRuntimeGeneration,
    DecisionService,
    GenerationFactory,
)
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import DecisionConfig, load_decision_config
from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.storage.checkpoints import CheckpointRepository
from apps.decision_app.storage.market_history import CanonicalMarketHistoryRepository
from apps.decision_app.storage.shadow_progress import ShadowProgressRepository
from apps.decision_app.transport.price_relay import PriceRelay, plan_series_key
from apps.decision_app.transport.shadow import ValkeyShadowPublisher
from apps.decision_app.transport.signals import ValkeySignalPublisher
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager


def _require_production_stream_client(client: Any) -> None:
    required = ("xread", "xrange", "xrevrange", "xadd")
    missing = tuple(
        name for name in required if not callable(getattr(client, name, None))
    )
    if missing:
        raise TypeError(
            "production stream client is missing required methods: "
            + ", ".join(missing)
        )


def build_generation_factory(
    *,
    config: DecisionConfig,
    composition: DecisionComposition,
    stream_client: Any,
    history_repository: Any,
    checkpoint_repository: Any,
    shadow_progress_repository: Any | None = None,
    manifest_store: Any | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> GenerationFactory:
    """Create the explicit D9A -> D9B generation builder."""

    if not isinstance(config, DecisionConfig):
        raise TypeError("config must be DecisionConfig")
    if not isinstance(composition, DecisionComposition):
        raise TypeError("composition must be DecisionComposition")
    if stream_client is None:
        raise TypeError("stream_client is required")
    _require_production_stream_client(stream_client)
    if not callable(getattr(history_repository, "fetch_bars", None)):
        raise TypeError("history_repository must provide fetch_bars()")

    async def build(*, reason: str, generation_id: int) -> DecisionRuntimeGeneration:
        del reason
        coordinator = DecisionStartupCoordinator(
            decision_config=config,
            plugin_catalog=composition.plugin_catalog,
            feature_catalog=composition.feature_catalog,
            feature_policy=composition.feature_policy,
            data_policy=composition.data_policy,
            source_catalog=composition.data_source_catalog,
            runtime_plugin_catalog=composition.runtime_plugin_catalog,
            policy_catalog=composition.policy_catalog,
            history_repository=history_repository,
            stream_client=stream_client,
            checkpoint_repository=checkpoint_repository,
            shadow_progress_repository=shadow_progress_repository,
            manifest_store=manifest_store,
            data_resolver=composition.data_resolver,
        )
        startup = await coordinator.start()
        publisher = ValkeySignalPublisher(
            stream_client,
            stream_maxlen=config.global_settings.signal_publication.stream_maxlen,
            stream_approximate=config.global_settings.signal_publication.stream_approximate,
        )
        shadow_publisher = ValkeyShadowPublisher(
            stream_client,
            stream_maxlen=config.global_settings.shadow_publication.stream_maxlen,
            stream_approximate=(
                config.global_settings.shadow_publication.stream_approximate
            ),
        )
        relay = None
        if startup.relay_plans:
            relay = PriceRelay(
                plans=startup.relay_plans,
                stream_client=stream_client,
                history_repository=history_repository,
                timeframe_grid=config.timeframe_grid,
                warm_cutoffs={
                    key: position.warm_cutoff
                    for key, position in startup.snapshot.series_positions.items()
                    if any(key == plan_series_key(plan) for plan in startup.relay_plans)
                },
                stream_maxlen=config.global_settings.price_relay.stream_maxlen,
                stream_approximate=(
                    config.global_settings.price_relay.stream_approximate
                ),
                batch_size=config.global_settings.live_input.batch_size,
            )
            await relay.bootstrap()
        live_runtime = LiveDecisionRuntime(
            startup=startup,
            timeframe_grid=config.timeframe_grid,
            stream_client=stream_client,
            history_repository=history_repository,
            signal_publisher=publisher,
            shadow_publisher=shadow_publisher,
            checkpoint_repository=checkpoint_repository,
            shadow_progress_repository=shadow_progress_repository,
            policy_catalog=composition.policy_catalog,
            price_relay=relay,
            batch_size=config.global_settings.live_input.batch_size,
            block_ms=config.global_settings.live_input.block_ms,
            now_fn=now_fn,
        )
        created_at = (now_fn or (lambda: datetime.now(UTC)))()
        return DecisionRuntimeGeneration(
            generation_id=generation_id,
            created_at=created_at,
            startup=startup,
            live_runtime=live_runtime,
        )

    return build


def create_application(
    *,
    config_manager: ConfigManager | None = None,
    decision_config: DecisionConfig | None = None,
    decision_service: DecisionService | None = None,
    generation_factory: GenerationFactory | None = None,
    lifecycle_reader: LifecycleNotificationReader | None = None,
    stream_client: Any | None = None,
    history_repository: Any | None = None,
    checkpoint_repository: Any | None = None,
    shadow_progress_repository: Any | None = None,
    manifest_store: AssetManifestStore | None = None,
) -> FastAPI:
    """Build the ASGI app without performing I/O until lifespan startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = decision_config
        config_mgr = config_manager or ConfigManager()
        owned_valkey = False
        owned_db = False
        service = decision_service
        current_stream_client = stream_client
        current_history = history_repository
        current_checkpoints = checkpoint_repository
        current_shadow_progress = shadow_progress_repository
        current_manifest_store = manifest_store
        current_lifecycle_reader = lifecycle_reader
        try:
            if service is None and generation_factory is None:
                if config is None:
                    config = load_decision_config(config_mgr)
                if current_stream_client is None:
                    current_stream_client = await create_valkey_client(config_mgr)
                    owned_valkey = True
                if current_history is None or current_checkpoints is None:
                    owned_db = True
                    await init_db_pools(config_mgr)
                    reader_pool = DBPoolManager.get_reader_pool()
                    writer_pool = DBPoolManager.get_writer_pool()
                    if reader_pool is None or writer_pool is None:
                        raise RuntimeError("DB pools were not initialized")
                    await ensure_checkpoint_schema(writer_pool)
                    if current_history is None:
                        current_history = CanonicalMarketHistoryRepository(
                            reader_pool,
                            timeframe_grid=config.timeframe_grid,
                        )
                    if current_checkpoints is None:
                        current_checkpoints = CheckpointRepository(writer_pool)
                    if current_shadow_progress is None:
                        current_shadow_progress = ShadowProgressRepository(writer_pool)
                if current_manifest_store is None:
                    current_manifest_store = AssetManifestStore(current_stream_client)
                # This capture intentionally precedes coordinator.start(),
                # whose first manifest read is the D9A reconciliation boundary.
                lifecycle_cursor = await capture_lifecycle_tail(current_stream_client)
                composition = build_production_composition(config)
                factory = build_generation_factory(
                    config=config,
                    composition=composition,
                    stream_client=current_stream_client,
                    history_repository=current_history,
                    checkpoint_repository=current_checkpoints,
                    shadow_progress_repository=current_shadow_progress,
                    manifest_store=current_manifest_store,
                )
                current_lifecycle_reader = (
                    current_lifecycle_reader
                    or LifecycleNotificationReader(
                        stream_client=current_stream_client,
                        cursor=lifecycle_cursor,
                        configured_manifest_assets=config.assets,
                        block_ms=config.global_settings.live_input.block_ms,
                    )
                )
                service = DecisionService(
                    generation_factory=factory,
                    lifecycle_reader=current_lifecycle_reader,
                    configured_asset_count=len(config.active_assets),
                    configured_lane_count=len(config.lane_specs()),
                    block_ms=config.global_settings.live_input.block_ms,
                )
            elif service is None:
                if generation_factory is None:
                    raise RuntimeError("generation factory is required")
                service = DecisionService(
                    generation_factory=generation_factory,
                    lifecycle_reader=lifecycle_reader,
                    block_ms=(
                        config.global_settings.live_input.block_ms
                        if config is not None
                        else 1000
                    ),
                )

            app.state.config_manager = config_mgr
            app.state.decision_service = service
            app.state.redis_client = current_stream_client
            app.state.history_repository = current_history
            app.state.checkpoint_repository = current_checkpoints
            app.state.manifest_store = current_manifest_store
            if service is not None and service.service_state in {"STARTING", "STOPPED"}:
                await service.start()
            yield
        finally:
            try:
                if service is not None and service.service_state not in {
                    "STOPPED",
                    "STARTING",
                }:
                    await service.stop()
            finally:
                try:
                    if owned_valkey and current_stream_client is not None:
                        await current_stream_client.aclose()
                finally:
                    try:
                        if owned_db:
                            await DBPoolManager.close_pools()
                    finally:
                        config_mgr.shutdown()

    app = create_app(decision_service=decision_service, lifespan=lifespan)
    return app


__all__ = ["build_generation_factory", "create_application"]
