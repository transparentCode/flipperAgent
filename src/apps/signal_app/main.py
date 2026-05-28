"""signal_app entrypoint — boots SignalWorker(s) per asset/timeframe from config."""

from __future__ import annotations

import asyncio
import os
from typing import Sequence, Tuple

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_MODELS, CONFIG_FILE_FEATURES
from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader
from libs.common.discovery import discover_pairs
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from apps.signal_app.signal_worker import SignalWorker

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_MODELS)
    config_mgr.register_file(CONFIG_FILE_FEATURES)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=os.environ.get("LOG_FORMAT", "json"),
        log_file=os.environ.get("LOG_FILE"),
    )

    pairs = discover_pairs(config_mgr)
    if not pairs:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(pairs)} asset/timeframe pairs: {pairs}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)

    # --- Build db_fetcher for indicator priming ---
    reader_pool = DBPoolManager.get_reader_pool()
    reader = TimescaleReader(reader_pool)

    async def db_fetcher(
        asset: str, timeframe: str, max_lookback: int
    ) -> Sequence[Tuple[float, float, float, float, float]]:
        df = await reader.get_ohlcv_aggregated(asset, timeframe, max_lookback)
        if df.empty:
            return []
        # Return (high, low, close, volume, timestamp_as_float)
        return [
            (
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
                float(row["timestamp"].timestamp()) if hasattr(row["timestamp"], "timestamp") else float(row["timestamp"]),
            )
            for _, row in df.iterrows()
        ]

    try:
        tasks = []
        for asset, tf in pairs:
            worker = SignalWorker(asset, tf, db_fetcher=db_fetcher)
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
