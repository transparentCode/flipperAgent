from __future__ import annotations

from libs.common.config import ConfigManager
from libs.contracts.model_runtime import (
    collect_runtime_trigger_timeframes,
    derive_trigger_timeframe,
    iter_enabled_runtime_specs,
)


def test_iter_enabled_runtime_specs_resolves_shared_runtime_contract() -> None:
    config_manager = _runtime_config_manager()

    specs = iter_enabled_runtime_specs(
        config_manager,
        asset="BTCUSDT",
        roots=("models", "scoring_models"),
    )

    assert [(spec.model_name, spec.config_timeframe) for spec in specs] == [
        ("Momentum", "4h"),
        ("ScoringOverlay", "1h"),
    ]
    assert specs[0].decision_timeframe == "4h"
    assert specs[0].base_timeframe == "1m"
    assert specs[0].trigger_mode == "on_base_bar_close"
    assert specs[0].required_context_profiles == ["volatility_60m"]
    assert specs[0].required_fields == ["ctx_ltf_volatility_60m.value"]
    assert specs[0].warmup_bars == 240
    assert specs[0].stateful is True
    assert specs[0].priority_class == "high"
    assert derive_trigger_timeframe(specs[0]) == "1m"


def test_collect_runtime_trigger_timeframes_uses_shared_resolution() -> None:
    config_manager = _runtime_config_manager()

    assert collect_runtime_trigger_timeframes(config_manager, asset="BTCUSDT") == ["1m", "1h"]


def test_iter_enabled_runtime_specs_inherits_default_default_models_for_asset_timeframes() -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    config_manager.register_file = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    config_manager._load_configs = lambda trigger_callbacks=True: None  # type: ignore[method-assign]
    config_manager._state = {
        "models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "Momentum": {
                                "enabled": True,
                                "runtime": {
                                    "decision_timeframe": "1h",
                                    "base_timeframe": "1m",
                                    "trigger_mode": "on_bar_close",
                                },
                            }
                        }
                    }
                }
            }
        },
        "scoring_models": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "ScoringOverlay": {
                                "enabled": True,
                                "runtime": {
                                    "decision_timeframe": "1h",
                                    "base_timeframe": "1m",
                                    "trigger_mode": "on_bar_close",
                                },
                            }
                        }
                    }
                }
            }
        },
    }

    specs = iter_enabled_runtime_specs(
        config_manager,
        asset="BTCUSDT",
        roots=("models", "scoring_models"),
    )

    assert [(spec.model_name, spec.config_timeframe) for spec in specs] == [
        ("Momentum", "1h"),
        ("ScoringOverlay", "1h"),
    ]


def _runtime_config_manager() -> ConfigManager:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    config_manager.register_file = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    config_manager._load_configs = lambda trigger_callbacks=True: None  # type: ignore[method-assign]
    config_manager._state = {
        "models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "4h": {
                            "Momentum": {
                                "enabled": True,
                                "runtime": {
                                    "decision_timeframe": "4h",
                                    "base_timeframe": "1m",
                                    "trigger_mode": "on_base_bar_close",
                                    "required_context_profiles": ["volatility_60m"],
                                    "required_fields": ["ctx_ltf_volatility_60m.value"],
                                    "warmup_bars": 240,
                                    "stateful": True,
                                    "priority_class": "high",
                                },
                            }
                        }
                    }
                }
            }
        },
        "scoring_models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "ScoringOverlay": {
                                "enabled": True,
                                "runtime": {
                                    "decision_timeframe": "1h",
                                    "base_timeframe": "1m",
                                    "trigger_mode": "on_bar_close",
                                    "required_context_profiles": ["breakout_pressure_15m"],
                                },
                            }
                        }
                    }
                }
            }
        },
    }
    return config_manager
