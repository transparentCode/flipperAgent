"""risk_app entrypoint — modular bootstrap around runtime orchestration."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_MODELS, CONFIG_FILE_RISK
from libs.common.db.pool_manager import DBPoolManager
from libs.common.discovery import discover_asset_timeframes
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from libs.risk.account_state import AccountState
from libs.risk.engine import RiskEngine
from libs.risk.mtf.aggregator import SignalAggregator
from libs.risk.position_tracker import PositionTracker
from libs.risk.rules.base import RiskRuleRegistry
from libs.risk.sizer import PositionSizer
from libs.risk.stop_loss import StopLossCalculator
from libs.risk.take_profit import TakeProfitCalculator

import libs.risk.rules.cooldown  # noqa: F401
import libs.risk.rules.daily_loss  # noqa: F401
import libs.risk.rules.max_drawdown  # noqa: F401
import libs.risk.rules.max_exposure  # noqa: F401
import libs.risk.rules.max_positions  # noqa: F401
from apps.risk_app.runtime import (
    FillListener,
    RiskRuntimeRunner,
    RiskWorker,
    persist_state_loop,
    supervise_consumer,
)

KEY_RISK = "risk"

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)

_persist_state_loop = persist_state_loop
_supervise_consumer = supervise_consumer


def _build_risk_engine(risk_config: dict[str, Any]) -> RiskEngine:
    """Instantiate RiskEngine with rules from config."""
    rule_names = risk_config.get("rules", [])
    rules = []
    for name in rule_names:
        try:
            rule_cls = RiskRuleRegistry.get(name)
        except KeyError as exc:
            raise ValueError(f"Unknown risk rule: {name}") from exc
        rules.append(rule_cls())

    return RiskEngine(
        rules=rules,
        sizer=PositionSizer(),
        sl_calc=StopLossCalculator(),
        tp_calc=TakeProfitCalculator(),
    )


async def _persist_final_state(account: AccountState, positions: PositionTracker) -> None:
    """Persist account and position state on shutdown."""
    db_pool = DBPoolManager.get_writer_pool()
    await account.update_unrealized(positions.all_positions())
    await account.save_snapshot(
        db_pool,
        open_position_count=positions.get_position_count(),
    )
    await positions.save_positions(db_pool)


async def _discover_runtime_asset_map(
    config_mgr: ConfigManager,
    manifest_store: AssetManifestStore,
) -> tuple[dict[str, list[str]], set[str]]:
    """Prefer canonical manifest assets, then fall back to config discovery."""
    manifests = await manifest_store.list_assets()
    if manifests:
        listener_assets = {manifest.symbol for manifest in manifests}
        runtime_asset_map: dict[str, list[str]] = {}
        for manifest in manifests:
            if not manifest.enabled or str(manifest.desired_state).upper() != "LIVE":
                continue
            timeframes = list(manifest.publish_timeframes or [manifest.base_timeframe])
            runtime_asset_map[manifest.symbol] = [
                timeframe for timeframe in timeframes if timeframe
            ]
        return runtime_asset_map, listener_assets

    discovered = discover_asset_timeframes(config_mgr)
    return discovered, set(discovered)


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_RISK)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    try:
        from libs.common.telemetry.bootstrap import init_telemetry

        init_telemetry("risk_app")
    except ImportError:
        pass

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=os.environ.get("LOG_FORMAT", "json"),
        log_file=os.environ.get("LOG_FILE"),
    )
    try:
        from libs.common.telemetry.bootstrap import attach_otel_log_handler

        attach_otel_log_handler()
    except ImportError:
        pass

    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)
    manifest_store = AssetManifestStore(redis_client)
    asset_map, listener_assets = await _discover_runtime_asset_map(config_mgr, manifest_store)
    if not asset_map and not listener_assets:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info("Discovered %s live risk assets: %s", len(asset_map), asset_map)

    risk_config = config_mgr.get(KEY_RISK, {})
    initial_balance = risk_config.get("account", {}).get("initial_balance", 10_000)
    db_pool = DBPoolManager.get_writer_pool()
    account = await AccountState.load_latest(db_pool, initial_balance)
    positions = await PositionTracker.load_positions(db_pool)

    runtime = RiskRuntimeRunner(
        asset_map=asset_map,
        redis_client=redis_client,
        risk_engine=_build_risk_engine(risk_config),
        signal_aggregator=SignalAggregator(),
        account=account,
        positions=positions,
        risk_config=risk_config,
        risk_worker_factory=RiskWorker,
        fill_listener_factory=FillListener,
        restart_delay_seconds=risk_config.get("consumer_restart_delay_seconds", 5),
        fill_listener_assets=listener_assets,
        persistence_interval_seconds=risk_config.get("state_persist_interval_seconds", 60),
    )

    try:
        await runtime.run()
    finally:
        try:
            await _persist_final_state(account, positions)
            logger.info("Final state persisted to DB on shutdown")
        except Exception:
            logger.exception("Failed to persist final state on shutdown")
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
