"""risk_app entrypoint — discovers assets, spawns RiskWorker(s) from config."""

from __future__ import annotations

import asyncio
import os

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_RISK, CONFIG_FILE_MODELS
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

# Import rule modules to trigger @register decorators
import libs.risk.rules.max_exposure  # noqa: F401
import libs.risk.rules.max_positions  # noqa: F401
import libs.risk.rules.max_drawdown  # noqa: F401
import libs.risk.rules.daily_loss  # noqa: F401
import libs.risk.rules.cooldown  # noqa: F401

from apps.risk_app.fill_listener import FillListener
from apps.risk_app.risk_worker import RiskWorker

KEY_RISK = "risk"

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


def _build_risk_engine(risk_config: dict) -> RiskEngine:
    """Instantiate RiskEngine with rules from config."""
    rule_names = risk_config.get("rules", [])
    rules = []
    for name in rule_names:
        try:
            rule_cls = RiskRuleRegistry.get(name)
        except KeyError:
            raise ValueError(f"Unknown risk rule: {name}")
        rules.append(rule_cls())

    return RiskEngine(
        rules=rules,
        sizer=PositionSizer(),
        sl_calc=StopLossCalculator(),
        tp_calc=TakeProfitCalculator(),
    )


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

    # Discover assets from models.yaml
    asset_map = discover_asset_timeframes(config_mgr)
    if not asset_map:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(asset_map)} assets: {asset_map}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)

    # Load risk config
    risk_config = config_mgr.get(KEY_RISK, {})

    # Bootstrap account and position state
    initial_balance = risk_config.get("account", {}).get("initial_balance", 10_000)
    account = AccountState(initial_balance)
    positions = PositionTracker()

    # Build engine and aggregator
    risk_engine = _build_risk_engine(risk_config)
    signal_aggregator = SignalAggregator()

    tasks: list[asyncio.Task] = []
    try:
        # Spawn one RiskWorker per asset
        for asset, timeframes in asset_map.items():
            worker = RiskWorker(
                asset=asset,
                timeframes=timeframes,
                risk_engine=risk_engine,
                signal_aggregator=signal_aggregator,
                account=account,
                positions=positions,
                risk_config=risk_config,
            )
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        # Spawn one FillListener per asset
        unique_assets = list(asset_map.keys())
        for asset in unique_assets:
            listener = FillListener(
                asset=asset,
                account=account,
                positions=positions,
            )
            await listener.connect(redis_client)
            tasks.append(asyncio.create_task(listener.start()))

        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
