from __future__ import annotations

import json
from pathlib import Path

import yaml


def main() -> None:
    config = yaml.safe_load(Path("configs/models.yaml").read_text(encoding="utf-8"))
    rows: list[dict[str, str | bool | None]] = []

    for root_key in ("models", "scoring_models"):
        root = config.get(root_key, {})
        assets = root.get("assets", {}) if isinstance(root, dict) else {}
        for asset, asset_cfg in assets.items():
            if asset == "default" or not isinstance(asset_cfg, dict):
                continue
            timeframes = asset_cfg.get("timeframes", {})
            for timeframe, timeframe_cfg in timeframes.items():
                if not isinstance(timeframe_cfg, dict):
                    continue
                for model_name, model_cfg in timeframe_cfg.items():
                    if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
                        continue
                    runtime = model_cfg.get("runtime", {}) if isinstance(model_cfg.get("runtime"), dict) else {}
                    rows.append(
                        {
                            "root": root_key,
                            "asset": asset,
                            "timeframe": timeframe,
                            "model": model_name,
                            "migration_mode": model_cfg.get("migration_mode"),
                            "has_explicit_migration_mode": "migration_mode" in model_cfg,
                            "decision_timeframe": runtime.get("decision_timeframe"),
                            "base_timeframe": runtime.get("base_timeframe"),
                            "trigger_mode": runtime.get("trigger_mode"),
                            "has_runtime": bool(runtime),
                        }
                    )

    print(json.dumps(rows, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
