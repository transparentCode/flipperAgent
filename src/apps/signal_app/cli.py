from __future__ import annotations

import argparse
import asyncio
import json

from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.pipeline.snapshot import FeatureSnapshotService
from libs.common.config import ConfigManager
from libs.common.connections import init_db_pools
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager


def main() -> None:
    parser = argparse.ArgumentParser(description="signal_app offline utilities")
    parser.add_argument("--list-pairs", action="store_true", help="Print effective signal pairs as JSON")
    parser.add_argument("--snapshot", action="store_true", help="Compute one historical feature snapshot")
    parser.add_argument("--asset", help="Asset symbol for --snapshot, e.g. BTCUSDT")
    parser.add_argument("--timeframe", help="Timeframe for --snapshot, e.g. 1h")
    parser.add_argument("--lookback", type=int, default=250, help="Historical bars to fetch for --snapshot")
    args = parser.parse_args()

    if args.list_pairs:
        pairs = [pair.model_dump(mode="json") for pair in SignalPairCatalog().list_pairs()]
        print(json.dumps(pairs, indent=2))
        return

    if args.snapshot:
        if not args.asset or not args.timeframe:
            parser.error("--snapshot requires --asset and --timeframe")
        print(
            json.dumps(
                asyncio.run(_compute_snapshot(args.asset, args.timeframe, args.lookback)),
                indent=2,
            )
        )
        return

    parser.print_help()


async def _compute_snapshot(asset: str, timeframe: str, lookback: int) -> dict:
    config_manager = ConfigManager()
    config_manager.register_file(CONFIG_FILE_MODELS)
    config_manager.register_file(CONFIG_FILE_FEATURES)
    await init_db_pools(config_manager)
    try:
        feature_vector = await FeatureSnapshotService().compute(
            asset=asset,
            timeframe=timeframe,
            lookback=lookback,
        )
        return feature_vector.model_dump(mode="json")
    finally:
        await DBPoolManager.close_pools()


if __name__ == "__main__":
    main()
