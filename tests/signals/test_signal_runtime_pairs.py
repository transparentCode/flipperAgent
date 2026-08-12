from __future__ import annotations

import copy

from apps.signal_app.runtime_pairs import build_signal_pairs
from libs.common.asset_manifest import AssetManifest
from libs.common.config import ConfigManager


def test_build_signal_pairs_keeps_runtime_base_lane_when_live() -> None:
    config_manager = _runtime_models_config_manager()

    pairs = build_signal_pairs(
        config_manager,
        live_pairs=[("BTCUSDT", "1m"), ("BTCUSDT", "1h")],
    )

    assert [(pair.asset, pair.timeframe) for pair in pairs] == [
        ("BTCUSDT", "1h"),
        ("BTCUSDT", "1m"),
    ]
    assert pairs[0].required_context_profiles == ["volatility_60m"]
    assert pairs[1].required_context_profiles == ["volatility_60m"]


def test_build_signal_pairs_filters_out_non_live_decision_lane() -> None:
    config_manager = _runtime_models_config_manager()

    pairs = build_signal_pairs(
        config_manager,
        live_pairs=[("BTCUSDT", "1m")],
    )

    assert [(pair.asset, pair.timeframe) for pair in pairs] == [("BTCUSDT", "1m")]
    assert pairs[0].required_context_profiles == ["volatility_60m"]


def test_build_signal_pairs_supports_base_trigger_decision_projection() -> None:
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
                                },
                            }
                        }
                    }
                }
            }
        }
    }

    pairs = build_signal_pairs(config_manager, live_pairs=[("BTCUSDT", "1m")])

    assert [pair.key for pair in pairs] == ["BTCUSDT:1m", "BTCUSDT:4h@1m"]
    projected = pairs[1]
    assert projected.timeframe == "4h"
    assert projected.trigger_timeframe == "1m"
    assert projected.trigger_mode == "on_base_bar_close"
    assert projected.required_context_profiles == ["volatility_60m"]


def test_build_signal_pairs_includes_scoring_model_only_assets() -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    config_manager.register_file = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    config_manager._load_configs = lambda trigger_callbacks=True: None  # type: ignore[method-assign]
    config_manager._state = {
        "models": {"assets": {}},
        "scoring_models": {
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {
                            "RegimePullbackScorer": {
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

    pairs = build_signal_pairs(config_manager, live_pairs=[("BTCUSDT", "1h")])

    assert [pair.key for pair in pairs] == ["BTCUSDT:1h"]


def test_build_signal_pairs_inherits_default_scoring_models_for_asset_timeframes() -> None:
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
                            "RegimePullbackScorer": {
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

    pairs = build_signal_pairs(config_manager, live_pairs=[("BTCUSDT", "1h")])

    assert [pair.key for pair in pairs] == ["BTCUSDT:1h"]
    assert pairs[0].required_context_profiles == ["breakout_pressure_15m"]


def test_build_signal_pairs_does_not_create_manifest_only_workers() -> None:
    config_manager = _empty_models_config_manager()

    pairs = build_signal_pairs(
        config_manager,
        live_manifests=[
            AssetManifest(
                symbol="BTCUSDT",
                base_timeframe="1m",
                publish_timeframes=["1h"],
                timeframes=["1m", "1h"],
                updated_at=1.0,
            )
        ],
    )

    assert pairs == []


def test_partial_manifests_gate_owned_asset_without_suppressing_unowned_config() -> None:
    config_manager = _runtime_models_config_manager()
    config_manager._state["models"]["assets"]["ETHUSDT"] = copy.deepcopy(
        config_manager._state["models"]["assets"]["BTCUSDT"]
    )

    pairs = build_signal_pairs(
        config_manager,
        live_manifests=[
            AssetManifest(
                symbol="BTCUSDT",
                enabled=True,
                desired_state="LIVE",
                updated_at=1.0,
            )
        ],
    )

    assert [pair.key for pair in pairs] == [
        "BTCUSDT:1h",
        "BTCUSDT:1m",
        "ETHUSDT:1h",
        "ETHUSDT:1m",
    ]


def _runtime_models_config_manager() -> ConfigManager:
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
                                    "required_context_profiles": ["volatility_60m"],
                                },
                            }
                        }
                    }
                }
            }
        }
    }
    return config_manager


def _empty_models_config_manager() -> ConfigManager:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    config_manager.register_file = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    config_manager._load_configs = lambda trigger_callbacks=True: None  # type: ignore[method-assign]
    config_manager._state = {"models": {"assets": {}}}
    return config_manager
