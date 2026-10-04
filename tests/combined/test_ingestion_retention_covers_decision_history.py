from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

import yaml


def _history_bar_values(value: object) -> Iterator[object]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "history_bars":
                yield child
            else:
                yield from _history_bar_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _history_bar_values(child)


def test_ingestion_candle_retention_covers_enabled_decision_lane_history() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    with (repository_root / "configs/ingestion/global.yaml").open() as file:
        ingestion_config = yaml.safe_load(file)["ingestion"]

    timeframe_seconds = {
        name: definition["duration_seconds"]
        for name, definition in ingestion_config["timeframes"].items()
    }
    retention_days = ingestion_config["retention"]["candle_days"]
    startup_history_days = ingestion_config["recovery"].get("startup_history_days")
    observed_history_values: list[int] = []

    assert isinstance(startup_history_days, int) and not isinstance(
        startup_history_days, bool
    ), "ingestion recovery.startup_history_days must be configured as an integer"

    asset_paths = sorted((repository_root / "configs/decision/assets").glob("*.yaml"))
    for asset_path in asset_paths:
        with asset_path.open() as file:
            asset_config = yaml.safe_load(file)
        if not asset_config.get("enabled", False):
            continue

        asset_name = asset_path.stem
        for lane_name, lane_config in asset_config.get("lanes", {}).items():
            history_values = list(_history_bar_values(lane_config.get("bindings", {})))
            if not history_values:
                continue

            assert all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in history_values
            ), f"{asset_name} lane {lane_name}: history_bars must be integers"
            observed_history_values.extend(history_values)
            required_bars = max(history_values)
            timeframe = lane_config["decision_timeframe"]
            required_days = required_bars * timeframe_seconds[timeframe] / 86_400
            assert retention_days - required_days >= 30, (
                f"{asset_name} lane {lane_name}: requires {required_days:.2f} days; "
                f"retention is {retention_days} days, leaving "
                f"{retention_days - required_days:.2f} days (minimum 30)"
            )
            assert startup_history_days >= required_days + 7, (
                f"{asset_name} lane {lane_name}: requires {required_days:.2f} days; "
                f"startup_history_days is {startup_history_days}, below the "
                f"required {required_days + 7:.2f} days (history plus 7-day margin)"
            )

    assert observed_history_values, "no decision lane history_bars values found"
