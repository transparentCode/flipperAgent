"""risk_app entrypoint — discovers assets, spawns RiskWorker(s) from config."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
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

CONFIG_FILE_RISK = "configs/risk.yaml"
CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"
KEY_RISK = "risk"

logger = bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)


def _discover_assets(config_mgr: ConfigManager) -> dict[str, list[str]]:
    """Read models.yaml to find all (asset, [timeframes]) pairs.

    Returns: {"BTCUSDT": ["1h", "4h"], "ETHUSDT": ["4h"], ...}
    """
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    result: dict[str, list[str]] = {}

    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        tfs = asset_cfg.get(KEY_TIMEFRAMES, {})
        tf_list = [tf for tf in tfs if tf != KEY_DEFAULT]
        if tf_list:
            result[asset] = tf_list

    return result


def _build_risk_engine(risk_config: dict) -> RiskEngine:
    """Instantiate RiskEngine with rules from config."""
    rule_names = risk_config.get("rules", [])
    rules = []
    for name in rule_names:
        try:
            rule_cls = RiskRuleRegistry.get(name)
            rules.append(rule_cls())
        except KeyError:
            logger.warning(f"Unknown risk rule '{name}' — skipping")

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

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    # Discover assets from models.yaml
    asset_map = _discover_assets(config_mgr)
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

    try:
        # Spawn one RiskWorker per asset
        tasks = []
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
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
