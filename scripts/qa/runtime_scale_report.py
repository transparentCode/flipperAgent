from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from apps.ingestion_app.settings import load_ingestion_settings
from apps.signal_app.runtime_pairs import build_signal_pairs
from apps.strategy_app.runtime_pairs import build_strategy_pairs
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS
from libs.common.runtime_scale import (
    RuntimeScaleInputs,
    StreamCaps,
    estimate_runtime_scale,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Estimate worker fanout and bounded stream replay capacity at larger asset counts.",
    )
    parser.add_argument(
        "--asset-count", type=int, required=True, help="Projected live asset count."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    parser.add_argument(
        "--runtime-timeframes-per-asset",
        type=float,
        default=None,
        help="Override projected runtime timeframes per asset.",
    )
    parser.add_argument(
        "--signal-pairs-per-asset",
        type=float,
        default=None,
        help="Override projected signal workers per asset.",
    )
    parser.add_argument(
        "--strategy-pairs-per-asset",
        type=float,
        default=None,
        help="Override projected strategy workers per asset.",
    )
    return parser


def _load_current_counts() -> tuple[ConfigManager, dict[str, float | int]]:
    manager = ConfigManager()
    manager.register_file(CONFIG_FILE_MODELS)
    manager.register_file(CONFIG_FILE_FEATURES)
    ingestion_settings = load_ingestion_settings(manager)

    target_assets = sorted(
        asset.asset for asset in ingestion_settings.assets.values() if asset.enabled
    )

    runtime_timeframes_total = 0
    for asset in target_assets:
        asset_settings = ingestion_settings.assets[asset]
        runtime_timeframes_total += sum(
            len(instrument.timeframes)
            for instrument in asset_settings.instruments.values()
        )

    signal_pairs = build_signal_pairs(manager)
    strategy_pairs = build_strategy_pairs(manager)
    asset_count = len(target_assets)

    return manager, {
        "configured_asset_count": asset_count,
        "enabled_asset_count": asset_count,
        "runtime_timeframes_total": runtime_timeframes_total,
        "signal_pair_count": len(signal_pairs),
        "strategy_pair_count": len(strategy_pairs),
        "runtime_timeframes_per_asset": (
            runtime_timeframes_total / asset_count if asset_count else 0.0
        ),
        "signal_pairs_per_asset": (
            len(signal_pairs) / asset_count if asset_count else 0.0
        ),
        "strategy_pairs_per_asset": (
            len(strategy_pairs) / asset_count if asset_count else 0.0
        ),
    }


def _stream_caps(manager: ConfigManager, ingestion_settings) -> StreamCaps:
    return StreamCaps(
        ohlcv_maxlen=ingestion_settings.publication.stream_maxlen,
        feature_stream_maxlen=int(
            manager.get("signal.runtime.feature_stream_maxlen", 1000)
        ),
        price_update_stream_maxlen=int(
            manager.get("signal.runtime.price_update_stream_maxlen", 200)
        ),
        signal_stream_maxlen=int(
            manager.get("strategy.runtime.signal_stream_maxlen", 1000)
        ),
        order_stream_maxlen=int(manager.get("risk.runtime.order_stream_maxlen", 1000)),
        fill_stream_maxlen=int(
            manager.get("execution.runtime.fill_stream_maxlen", 1000)
        ),
        failure_stream_maxlen=int(
            manager.get("execution.runtime.failure_stream_maxlen", 1000)
        ),
        lifecycle_maxlen=ingestion_settings.publication.stream_maxlen,
    )


def main() -> int:
    args = _build_parser().parse_args()
    manager, current = _load_current_counts()
    ingestion_settings = load_ingestion_settings(manager)
    caps = _stream_caps(manager, ingestion_settings)
    report = estimate_runtime_scale(
        RuntimeScaleInputs(
            asset_count=args.asset_count,
            runtime_timeframes_per_asset=(
                args.runtime_timeframes_per_asset
                if args.runtime_timeframes_per_asset is not None
                else float(current["runtime_timeframes_per_asset"])
            ),
            signal_pairs_per_asset=(
                args.signal_pairs_per_asset
                if args.signal_pairs_per_asset is not None
                else float(current["signal_pairs_per_asset"])
            ),
            strategy_pairs_per_asset=(
                args.strategy_pairs_per_asset
                if args.strategy_pairs_per_asset is not None
                else float(current["strategy_pairs_per_asset"])
            ),
            stream_caps=caps,
        )
    )
    payload = {
        "current": current,
        "projected": report.to_dict(),
        "configured_stream_caps": asdict(caps),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
