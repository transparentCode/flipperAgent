"""Factories for execution_app runtime dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.execution_app.execution_worker import ExecutionWorker
from apps.execution_app.observability.runtime_state import ExecutionRuntimeStateStore
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.execution.fill_tracker import FillTracker
from libs.execution.idempotency import IdempotencyStore
from libs.execution.order_manager import OrderManager
from libs.execution.paper_executor import PaperExecutor

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


@dataclass(slots=True)
class ExecutionSharedServices:
    executor: Any
    idempotency_store: IdempotencyStore
    fill_tracker: FillTracker
    writer_pool: Any
    persist_to_db: bool
    runtime_state_store: ExecutionRuntimeStateStore | None = None


def build_executor(exec_config: dict[str, Any]) -> Any:
    mode = exec_config.get("mode", "paper")
    if mode == "paper":
        paper_cfg = exec_config.get("paper", {})
        logger.info("Using PaperExecutor")
        return PaperExecutor(
            slippage_bps=paper_cfg.get("slippage_bps", 5.0),
            slippage_jitter_bps=paper_cfg.get("slippage_jitter_bps", 2.0),
            commission_bps=paper_cfg.get("commission_bps", 4.0),
            fill_delay_ms=paper_cfg.get("fill_delay_ms", 50.0),
            seed=paper_cfg.get("seed", 42),
        )
    if mode == "live":
        raise NotImplementedError(
            "Live execution is not yet implemented. "
            "Set execution.mode to 'paper' in configs/execution.yaml"
        )
    raise ValueError(f"Unknown execution mode: {mode}")


async def build_idempotency_store(exec_config: dict[str, Any]) -> tuple[IdempotencyStore, bool]:
    idem_cfg = exec_config.get("idempotency", {})
    max_memory_keys = idem_cfg.get("max_memory_keys", 10_000)
    persist_to_db = idem_cfg.get("persist_to_db", False)

    if not persist_to_db:
        return IdempotencyStore(max_size=max_memory_keys), False

    try:
        reader_pool = DBPoolManager.get_reader_pool()
        store = await IdempotencyStore.load(reader_pool, max_size=max_memory_keys)
        logger.info("Restored %s idempotency keys from DB", len(store._seen))
        return store, True
    except Exception:
        logger.warning("Could not load idempotency keys from DB — starting empty", exc_info=True)
        return IdempotencyStore(max_size=max_memory_keys), True


async def build_shared_services(
    exec_config: dict[str, Any],
    *,
    writer_pool: Any,
    redis_client: Any | None = None,
) -> ExecutionSharedServices:
    executor = build_executor(exec_config)
    idempotency_store, persist_to_db = await build_idempotency_store(exec_config)
    return ExecutionSharedServices(
        executor=executor,
        idempotency_store=idempotency_store,
        fill_tracker=FillTracker(),
        writer_pool=writer_pool,
        persist_to_db=persist_to_db,
        runtime_state_store=ExecutionRuntimeStateStore(redis_client) if redis_client is not None else None,
    )


def build_worker(
    asset: str,
    *,
    shared: ExecutionSharedServices,
    exec_config: dict[str, Any],
) -> ExecutionWorker:
    return ExecutionWorker(
        asset=asset,
        order_manager=OrderManager(
            executor=shared.executor,
            idempotency_store=shared.idempotency_store,
            fill_tracker=shared.fill_tracker,
            db_pool=shared.writer_pool,
        ),
        exec_config=exec_config,
        runtime_state_store=shared.runtime_state_store,
    )


async def persist_runtime_state(shared: ExecutionSharedServices) -> None:
    if not shared.persist_to_db:
        return
    try:
        writer_pool = DBPoolManager.get_writer_pool()
        await shared.idempotency_store.save(writer_pool)
        logger.info("Idempotency keys persisted to DB")
    except Exception:
        logger.warning("Could not persist idempotency keys to DB", exc_info=True)
