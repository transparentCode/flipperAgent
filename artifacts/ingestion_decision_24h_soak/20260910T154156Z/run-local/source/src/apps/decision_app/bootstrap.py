"""D9C resource ownership, generation construction, and ASGI lifespan."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import asyncpg
from fastapi import FastAPI
from valkey.asyncio import Valkey
from valkey.asyncio.connection import (
    Connection,
    ConnectionPool,
    SSLConnection,
    UnixDomainSocketConnection,
)

from apps.decision_app.api.app import create_app
from apps.decision_app.composition import (
    DecisionComposition,
    build_production_composition,
)
from apps.decision_app.observability import DecisionObservability
from apps.decision_app.runtime.deadlines import (
    CleanupBudget,
    Deadline,
    cleanup_with_timeout,
    run_until,
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

_LOGGER = logging.getLogger(__name__)


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


def _require_bounded_injected_stream_client(
    client: Any,
    *,
    io_timeout_seconds: float,
) -> None:
    """Require an injected Valkey client to expose its native wire contract."""

    if type(client) is not Valkey:
        raise TypeError("injected Decision stream client must be a Valkey client")
    _require_production_stream_client(client)
    pool = getattr(client, "connection_pool", None)
    if type(pool) is not ConnectionPool:
        raise TypeError(
            "injected Decision stream client must use the installed ConnectionPool"
        )
    if pool.connection_class not in {
        Connection,
        SSLConnection,
        UnixDomainSocketConnection,
    }:
        raise TypeError(
            "injected Decision stream client must use a supported built-in connection"
        )
    options = getattr(pool, "connection_kwargs", None)
    if not isinstance(options, Mapping):
        raise TypeError("injected Decision stream client must expose connection_kwargs")
    if (
        options.get("socket_timeout") != io_timeout_seconds
        or options.get("socket_connect_timeout") != io_timeout_seconds
        or options.get("retry_on_timeout") is not False
        or options.get("retry_on_error") not in ([], ())
        or options.get("retry") is not None
    ):
        raise TypeError(
            "injected Decision stream client has no verified bounded wire contract"
        )


def _require_bounded_repository(
    repository: Any,
    *,
    name: str,
    io_timeout_seconds: float,
    operation_timeout_seconds: float,
    cleanup_timeout_seconds: float,
) -> None:
    expected_types = {
        "history": CanonicalMarketHistoryRepository,
        "checkpoint": CheckpointRepository,
        "shadow-progress": ShadowProgressRepository,
    }
    expected_type = expected_types[name]
    if type(repository) is not expected_type:
        raise TypeError(
            f"injected Decision {name} repository must be the built-in "
            f"{expected_type.__name__}"
        )
    if type(getattr(repository, "_pool", None)) is not asyncpg.Pool:
        raise TypeError(
            f"injected Decision {name} repository must use the installed asyncpg.Pool"
        )
    expected = {
        "_io_timeout_seconds": io_timeout_seconds,
        "_operation_timeout_seconds": operation_timeout_seconds,
        "_cleanup_timeout_seconds": cleanup_timeout_seconds,
    }
    if any(
        getattr(repository, key, object()) != value for key, value in expected.items()
    ):
        raise TypeError(
            f"injected Decision {name} repository has no verified bounded I/O contract"
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
    observability: DecisionObservability | None = None,
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
    dependency_io = config.global_settings.dependency_io

    async def build(*, reason: str, generation_id: int) -> DecisionRuntimeGeneration:
        del reason
        for name, repository in (
            ("history", history_repository),
            ("checkpoint", checkpoint_repository),
            ("shadow-progress", shadow_progress_repository),
        ):
            if bool(getattr(repository, "poisoned", False)):
                raise RuntimeError(
                    f"{name} repository is poisoned; generation rebuild is fenced"
                )
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
            io_timeout_seconds=dependency_io.io_timeout_seconds,
        )
        startup = await coordinator.start()
        publisher = ValkeySignalPublisher(
            stream_client,
            stream_maxlen=config.global_settings.signal_publication.stream_maxlen,
            stream_approximate=config.global_settings.signal_publication.stream_approximate,
            io_timeout_seconds=dependency_io.io_timeout_seconds,
        )
        shadow_publisher = ValkeyShadowPublisher(
            stream_client,
            stream_maxlen=config.global_settings.shadow_publication.stream_maxlen,
            stream_approximate=(
                config.global_settings.shadow_publication.stream_approximate
            ),
            io_timeout_seconds=dependency_io.io_timeout_seconds,
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
                io_timeout_seconds=dependency_io.io_timeout_seconds,
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
            io_timeout_seconds=dependency_io.io_timeout_seconds,
            now_fn=now_fn,
            observability=observability,
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
    observability: DecisionObservability | None = None,
) -> FastAPI:
    """Build the ASGI app without performing I/O until lifespan startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owner = getattr(app.state, "decision_lifespan_owner", None)
        if owner is None:
            owner = {
                "poisoned": False,
                "retained_cleanup_tasks": set(),
                "stream_client": None,
                "history_repository": None,
                "checkpoint_repository": None,
                "shadow_progress_repository": None,
                "service": None,
                "owned_valkey": False,
                "owned_db": False,
            }
            app.state.decision_lifespan_owner = owner
        elif owner["poisoned"] or owner["retained_cleanup_tasks"]:
            raise RuntimeError(
                "Decision lifespan is poisoned after unconfirmed owned-resource cleanup"
            )
        config = decision_config
        config_mgr = config_manager or ConfigManager()
        owned_valkey = False
        owned_db = False
        service = decision_service
        current_stream_client = stream_client
        current_history = history_repository
        current_checkpoints = checkpoint_repository
        current_shadow_progress = shadow_progress_repository
        injected_history = history_repository is not None
        injected_checkpoints = checkpoint_repository is not None
        injected_shadow_progress = shadow_progress_repository is not None
        current_manifest_store = manifest_store
        current_lifecycle_reader = lifecycle_reader
        current_observability = observability
        retained_cleanup_tasks = owner["retained_cleanup_tasks"]
        startup_deadline: Deadline | None = None
        service_started = False
        service_clean = True
        shutdown_failure: BaseException | None = None
        shutdown_phase: str | None = None
        body_failure: BaseException | None = None
        cleanup_budget: CleanupBudget | None = None
        owner.update(
            stream_client=current_stream_client,
            history_repository=current_history,
            checkpoint_repository=current_checkpoints,
            shadow_progress_repository=current_shadow_progress,
            service=service,
            owned_valkey=False,
            owned_db=False,
        )
        try:
            if service is None and generation_factory is None:
                if config is None:
                    config = load_decision_config(config_mgr)
                dependency_io = config.global_settings.dependency_io
                _LOGGER.info(
                    "Decision bounded startup budget policy: "
                    "io_timeout_seconds=%s "
                    "db_operation_timeout_seconds=%s "
                    "generation_timeout_seconds=%s "
                    "control_wait_timeout_seconds=%s "
                    "cleanup_timeout_seconds=%s",
                    dependency_io.io_timeout_seconds,
                    dependency_io.db_operation_timeout_seconds,
                    dependency_io.generation_timeout_seconds,
                    dependency_io.control_wait_timeout_seconds,
                    dependency_io.cleanup_timeout_seconds,
                )
                startup_deadline = Deadline.after(
                    dependency_io.generation_timeout_seconds
                )
                cleanup_budget = CleanupBudget(
                    dependency_io.cleanup_timeout_seconds,
                    cap_expires_at=(
                        startup_deadline.expires_at
                        + dependency_io.cleanup_timeout_seconds
                    ),
                )
                if current_observability is None:
                    try:
                        current_observability = DecisionObservability(
                            timeframe_grid=config.timeframe_grid
                        )
                    except Exception:  # noqa: BLE001
                        try:
                            _LOGGER.warning(
                                "Decision observability initialization failed; "
                                "continuing without metrics",
                                exc_info=True,
                            )
                        except Exception:  # noqa: BLE001, S110
                            pass
                        current_observability = None
                if current_stream_client is None:

                    async def cleanup_valkey_candidate(
                        awaitable,
                        retrying: bool,
                    ) -> None:
                        nonlocal cleanup_budget
                        assert cleanup_budget is not None
                        await cleanup_with_timeout(
                            awaitable,
                            cleanup_budget.remaining(),
                            operation="Valkey candidate cleanup",
                            retained_tasks=retained_cleanup_tasks,
                        )
                        if not retrying:
                            return
                        current_task = asyncio.current_task()
                        if current_task is not None and current_task.cancelling() > 0:
                            return
                        assert startup_deadline is not None
                        if startup_deadline.remaining() <= 0:
                            return
                        cleanup_budget = CleanupBudget(
                            dependency_io.cleanup_timeout_seconds,
                            cap_expires_at=(
                                startup_deadline.expires_at
                                + dependency_io.cleanup_timeout_seconds
                            ),
                        )

                    current_stream_client = await run_until(
                        create_valkey_client(
                            config_mgr,
                            io_timeout_seconds=dependency_io.io_timeout_seconds,
                            cleanup_callback=cleanup_valkey_candidate,
                        ),
                        startup_deadline,
                        operation="initial Valkey resource",
                    )
                    owned_valkey = True
                    owner.update(
                        stream_client=current_stream_client,
                        owned_valkey=True,
                    )
                if current_history is None or current_checkpoints is None:
                    created_db = await run_until(
                        init_db_pools(
                            config_mgr,
                            connect_timeout=dependency_io.io_timeout_seconds,
                            return_created=True,
                            cleanup_timeout=dependency_io.cleanup_timeout_seconds,
                            retained_cleanup_tasks=retained_cleanup_tasks,
                            cleanup_remaining=cleanup_budget.remaining,
                        ),
                        startup_deadline,
                        operation="initial DB resources",
                    )
                    # Only the explicit opt-in signal proves ownership.  An
                    # omitted/legacy return is deliberately treated as
                    # borrowed, so a failed factory cannot close shared pools.
                    owned_db = created_db is True
                    owner["owned_db"] = owned_db
                    reader_pool = DBPoolManager.get_reader_pool()
                    writer_pool = DBPoolManager.get_writer_pool()
                    if reader_pool is None or writer_pool is None:
                        raise RuntimeError("DB pools were not initialized")
                    await run_until(
                        ensure_checkpoint_schema(
                            writer_pool,
                            io_timeout_seconds=dependency_io.io_timeout_seconds,
                            operation_timeout_seconds=(
                                dependency_io.db_operation_timeout_seconds
                            ),
                            cleanup_timeout_seconds=dependency_io.cleanup_timeout_seconds,
                            retained_cleanup_tasks=retained_cleanup_tasks,
                            cleanup_budget=cleanup_budget,
                        ),
                        startup_deadline,
                        operation="initial checkpoint schema",
                    )
                    if current_history is None:
                        current_history = CanonicalMarketHistoryRepository(
                            reader_pool,
                            timeframe_grid=config.timeframe_grid,
                            io_timeout_seconds=dependency_io.io_timeout_seconds,
                            operation_timeout_seconds=(
                                dependency_io.db_operation_timeout_seconds
                            ),
                            cleanup_timeout_seconds=dependency_io.cleanup_timeout_seconds,
                        )
                    if current_checkpoints is None:
                        current_checkpoints = CheckpointRepository(
                            writer_pool,
                            io_timeout_seconds=dependency_io.io_timeout_seconds,
                            operation_timeout_seconds=(
                                dependency_io.db_operation_timeout_seconds
                            ),
                            cleanup_timeout_seconds=dependency_io.cleanup_timeout_seconds,
                        )
                    if current_shadow_progress is None:
                        current_shadow_progress = ShadowProgressRepository(
                            writer_pool,
                            io_timeout_seconds=dependency_io.io_timeout_seconds,
                            operation_timeout_seconds=(
                                dependency_io.db_operation_timeout_seconds
                            ),
                            cleanup_timeout_seconds=dependency_io.cleanup_timeout_seconds,
                        )
                    owner.update(
                        history_repository=current_history,
                        checkpoint_repository=current_checkpoints,
                        shadow_progress_repository=current_shadow_progress,
                    )
                if current_manifest_store is None:
                    current_manifest_store = AssetManifestStore(current_stream_client)
                _require_bounded_injected_stream_client(
                    current_stream_client,
                    io_timeout_seconds=dependency_io.io_timeout_seconds,
                )
                for name, repository, injected in (
                    ("history", current_history, injected_history),
                    ("checkpoint", current_checkpoints, injected_checkpoints),
                    (
                        "shadow-progress",
                        current_shadow_progress,
                        injected_shadow_progress,
                    ),
                ):
                    if repository is not None and injected:
                        _require_bounded_repository(
                            repository,
                            name=name,
                            io_timeout_seconds=dependency_io.io_timeout_seconds,
                            operation_timeout_seconds=(
                                dependency_io.db_operation_timeout_seconds
                            ),
                            cleanup_timeout_seconds=dependency_io.cleanup_timeout_seconds,
                        )
                # This capture intentionally precedes coordinator.start(),
                # whose first manifest read is the D9A reconciliation boundary.
                lifecycle_cursor = await run_until(
                    capture_lifecycle_tail(
                        current_stream_client,
                        io_timeout_seconds=dependency_io.io_timeout_seconds,
                    ),
                    startup_deadline,
                    operation="initial lifecycle tail",
                )
                composition = build_production_composition(config)
                factory = build_generation_factory(
                    config=config,
                    composition=composition,
                    stream_client=current_stream_client,
                    history_repository=current_history,
                    checkpoint_repository=current_checkpoints,
                    shadow_progress_repository=current_shadow_progress,
                    manifest_store=current_manifest_store,
                    observability=current_observability,
                )
                current_lifecycle_reader = (
                    current_lifecycle_reader
                    or LifecycleNotificationReader(
                        stream_client=current_stream_client,
                        cursor=lifecycle_cursor,
                        configured_manifest_assets=tuple(
                            asset.decision_asset for asset in config.active_assets
                        ),
                        block_ms=config.global_settings.live_input.block_ms,
                        io_timeout_seconds=(
                            config.global_settings.dependency_io.io_timeout_seconds
                        ),
                    )
                )
                service = DecisionService(
                    generation_factory=factory,
                    lifecycle_reader=current_lifecycle_reader,
                    configured_asset_count=len(config.active_assets),
                    configured_lane_count=len(config.lane_specs()),
                    block_ms=config.global_settings.live_input.block_ms,
                    generation_timeout_seconds=(
                        config.global_settings.dependency_io.generation_timeout_seconds
                    ),
                    control_wait_timeout_seconds=(
                        config.global_settings.dependency_io.control_wait_timeout_seconds
                    ),
                    cleanup_timeout_seconds=(
                        config.global_settings.dependency_io.cleanup_timeout_seconds
                    ),
                    observability=current_observability,
                )
                owner["service"] = service
                await run_until(
                    service.start(deadline=startup_deadline),
                    startup_deadline,
                    operation="initial service start",
                )
                service_started = True
                cleanup_budget = CleanupBudget(dependency_io.cleanup_timeout_seconds)
            elif service is None:
                if generation_factory is None:
                    raise RuntimeError("generation factory is required")
                service = DecisionService(
                    generation_factory=generation_factory,
                    lifecycle_reader=lifecycle_reader,
                    observability=current_observability,
                    block_ms=(
                        config.global_settings.live_input.block_ms
                        if config is not None
                        else 1000
                    ),
                    generation_timeout_seconds=(
                        config.global_settings.dependency_io.generation_timeout_seconds
                        if config is not None
                        else None
                    ),
                    control_wait_timeout_seconds=(
                        config.global_settings.dependency_io.control_wait_timeout_seconds
                        if config is not None
                        else None
                    ),
                    cleanup_timeout_seconds=(
                        config.global_settings.dependency_io.cleanup_timeout_seconds
                        if config is not None
                        else None
                    ),
                )
                owner["service"] = service

            app.state.config_manager = config_mgr
            app.state.decision_service = service
            app.state.redis_client = current_stream_client
            app.state.history_repository = current_history
            app.state.checkpoint_repository = current_checkpoints
            app.state.manifest_store = current_manifest_store
            app.state.decision_observability = current_observability
            if (
                service is not None
                and not service_started
                and service.service_state in {"STARTING", "STOPPED"}
            ):
                await service.start()
                service_started = True
            yield
        except BaseException as exc:
            body_failure = exc
            raise
        finally:
            try:
                if service is not None and service.service_state != "STOPPED":
                    service_clean = False
                    cleanup_timeout = (
                        config.global_settings.dependency_io.cleanup_timeout_seconds
                        if config is not None
                        else 5.0
                    )
                    if cleanup_budget is None:
                        cleanup_budget = CleanupBudget(cleanup_timeout)
                    try:
                        stopped = await service.stop(cleanup_budget=cleanup_budget)
                    except BaseException as exc:  # noqa: BLE001
                        shutdown_failure = exc
                        shutdown_phase = "service stop"
                    else:
                        service_clean = stopped.service_state == "STOPPED"
                        if not service_clean:
                            shutdown_failure = RuntimeError(
                                "Decision service did not reach STOPPED"
                            )
            finally:
                try:
                    if not service_clean:
                        owner["poisoned"] = True
                        _LOGGER.error(
                            "Decision service did not reach STOPPED; retaining owned resources"
                        )
                    else:
                        if cleanup_budget is None:
                            cleanup_timeout = (
                                config.global_settings.dependency_io.cleanup_timeout_seconds
                                if config is not None
                                else 5.0
                            )
                            cleanup_budget = CleanupBudget(cleanup_timeout)
                        cleanup_deadline = cleanup_budget.deadline()
                        try:
                            if owned_valkey and current_stream_client is not None:
                                try:
                                    await cleanup_with_timeout(
                                        current_stream_client.aclose(),
                                        cleanup_deadline.remaining(),
                                        operation="Valkey resource cleanup",
                                        retained_tasks=retained_cleanup_tasks,
                                    )
                                except BaseException as exc:  # noqa: BLE001
                                    shutdown_failure = exc
                                    shutdown_phase = "valkey resource cleanup"
                        finally:
                            if owned_db:
                                try:
                                    await cleanup_with_timeout(
                                        DBPoolManager.close_pools(),
                                        cleanup_deadline.remaining(),
                                        operation="DB pool cleanup",
                                        retained_tasks=retained_cleanup_tasks,
                                    )
                                except BaseException as exc:  # noqa: BLE001
                                    if shutdown_failure is None:
                                        shutdown_failure = exc
                                        shutdown_phase = "db pool cleanup"
                        if shutdown_failure is not None:
                            service_clean = False
                            owner["poisoned"] = True
                        if retained_cleanup_tasks:
                            service_clean = False
                            owner["poisoned"] = True
                            if shutdown_failure is None:
                                shutdown_failure = RuntimeError(
                                    "owned resource cleanup remains unconfirmed"
                                )
                                shutdown_phase = "owned resource cleanup"
                finally:
                    owner.update(
                        stream_client=current_stream_client,
                        history_repository=current_history,
                        checkpoint_repository=current_checkpoints,
                        shadow_progress_repository=current_shadow_progress,
                        service=service,
                        owned_valkey=owned_valkey,
                        owned_db=owned_db,
                    )
                    config_mgr.shutdown()
            if not service_clean and body_failure is None:
                if isinstance(shutdown_failure, asyncio.CancelledError):
                    raise shutdown_failure
                raise RuntimeError(
                    "Decision lifespan shutdown was unclean during "
                    f"{shutdown_phase or 'resource cleanup'}; owned resources retained"
                ) from shutdown_failure

    app = create_app(decision_service=decision_service, lifespan=lifespan)
    return app


__all__ = ["build_generation_factory", "create_application"]
