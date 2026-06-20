from __future__ import annotations

from pathlib import Path

import yaml


def test_live_models_declare_explicit_runtime_contracts() -> None:
    config = yaml.safe_load(Path("configs/models.yaml").read_text(encoding="utf-8"))

    missing: list[str] = []
    invalid: list[str] = []

    for root_key in ("models", "scoring_models", "strategy_models"):
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
                    runtime = model_cfg.get("runtime")
                    model_ref = f"{root_key}:{asset}:{timeframe}:{model_name}"
                    if not isinstance(runtime, dict):
                        missing.append(model_ref)
                        continue
                    if str(runtime.get("decision_timeframe")) != str(timeframe):
                        invalid.append(f"{model_ref}:decision_timeframe")
                    if str(runtime.get("base_timeframe")) != "1m":
                        invalid.append(f"{model_ref}:base_timeframe")
                    if str(runtime.get("trigger_mode")) not in {
                        "on_bar_close",
                        "every_bar_close",
                        "on_base_bar_close",
                    }:
                        invalid.append(f"{model_ref}:trigger_mode")

    assert not missing, f"Enabled live models missing runtime blocks: {missing}"
    assert not invalid, f"Enabled live models with invalid runtime fields: {invalid}"


def test_enabled_strategy_models_do_not_declare_legacy_migration_mode() -> None:
    config = yaml.safe_load(Path("configs/models.yaml").read_text(encoding="utf-8"))

    invalid: list[str] = []

    root = config.get("strategy_models", {})
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
                if "migration_mode" in model_cfg:
                    invalid.append(f"strategy_models:{asset}:{timeframe}:{model_name}")

    assert not invalid, f"Canonical strategy models should not declare migration_mode: {invalid}"


def test_live_models_declare_explicit_migration_modes() -> None:
    config = yaml.safe_load(Path("configs/models.yaml").read_text(encoding="utf-8"))

    missing: list[str] = []
    invalid: list[str] = []
    valid_modes = {"legacy", "adapted", "scoring", "native_scoring"}

    root = config.get("models", {})
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
                model_ref = f"models:{asset}:{timeframe}:{model_name}"
                migration_mode = model_cfg.get("migration_mode")
                if migration_mode is None:
                    missing.append(model_ref)
                    continue
                if str(migration_mode) not in valid_modes:
                    invalid.append(f"{model_ref}:{migration_mode}")

    assert not missing, f"Enabled live models missing migration_mode: {missing}"
    assert not invalid, f"Enabled live models with invalid migration_mode: {invalid}"


def test_enabled_scoring_models_declare_native_scoring_mode() -> None:
    config = yaml.safe_load(Path("configs/models.yaml").read_text(encoding="utf-8"))

    missing: list[str] = []
    invalid: list[str] = []

    root = config.get("scoring_models", {})
    assets = root.get("assets", {}) if isinstance(root, dict) else {}
    for asset, asset_cfg in assets.items():
        if not isinstance(asset_cfg, dict):
            continue
        timeframes = asset_cfg.get("timeframes", {})
        for timeframe, timeframe_cfg in timeframes.items():
            if not isinstance(timeframe_cfg, dict):
                continue
            for model_name, model_cfg in timeframe_cfg.items():
                if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
                    continue
                model_ref = f"scoring_models:{asset}:{timeframe}:{model_name}"
                migration_mode = model_cfg.get("migration_mode")
                if migration_mode is None:
                    missing.append(model_ref)
                    continue
                if str(migration_mode) != "native_scoring":
                    invalid.append(f"{model_ref}:{migration_mode}")

    assert not missing, f"Enabled scoring models missing migration_mode: {missing}"
    assert not invalid, f"Enabled scoring models must use native_scoring: {invalid}"


def test_enabled_live_models_do_not_use_adapted_mode() -> None:
    config = yaml.safe_load(Path("configs/models.yaml").read_text(encoding="utf-8"))

    adapted: list[str] = []

    root = config.get("models", {})
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
                if str(model_cfg.get("migration_mode")) == "adapted":
                    adapted.append(f"models:{asset}:{timeframe}:{model_name}")

    assert not adapted, f"Enabled live models should not use adapted mode: {adapted}"


def test_enabled_live_models_do_not_use_legacy_mode() -> None:
    config = yaml.safe_load(Path("configs/models.yaml").read_text(encoding="utf-8"))

    legacy: list[str] = []

    root = config.get("models", {})
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
                if str(model_cfg.get("migration_mode")) == "legacy":
                    legacy.append(f"models:{asset}:{timeframe}:{model_name}")

    assert not legacy, f"Enabled live models should not use legacy mode: {legacy}"
