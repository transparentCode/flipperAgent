from __future__ import annotations

from apps.strategy_app.runtime_pairs import build_strategy_pairs
from libs.common.asset_manifest import AssetManifest
from libs.common.config import ConfigManager


def test_build_strategy_pairs_groups_models_by_decision_and_trigger_lane() -> None:
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
                                    "base_timeframe": "4h",
                                    "trigger_mode": "on_base_bar_close",
                                },
                            },
                            "MeanReversion": {
                                "enabled": True,
                                "runtime": {
                                    "decision_timeframe": "4h",
                                    "base_timeframe": "4h",
                                    "trigger_mode": "on_base_bar_close",
                                },
                            },
                        }
                    }
                }
            }
        }
    }

    pairs = build_strategy_pairs(config_manager)

    assert [(pair.asset, pair.timeframe, pair.trigger_timeframe) for pair in pairs] == [
        ("BTCUSDT", "4h", "4h"),
    ]
    assert pairs[0].model_names == ["MeanReversion", "Momentum"]


def test_build_strategy_pairs_supports_base_trigger_decision_projection() -> None:
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
                                },
                            },
                        }
                    }
                }
            }
        }
    }

    pairs = build_strategy_pairs(config_manager)

    assert [(pair.asset, pair.timeframe, pair.trigger_timeframe) for pair in pairs] == [
        ("BTCUSDT", "4h", "1m"),
    ]
    assert pairs[0].trigger_mode == "on_base_bar_close"
    assert pairs[0].base_timeframe == "1m"


def test_build_strategy_pairs_includes_scoring_model_only_assets() -> None:
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

    pairs = build_strategy_pairs(config_manager, live_pairs=[("BTCUSDT", "1h")])

    assert [pair.key for pair in pairs] == ["BTCUSDT:1h"]
    assert pairs[0].model_names == ["RegimePullbackScorer"]


def test_build_strategy_pairs_inherits_default_scoring_models_for_asset_timeframes() -> (
    None
):
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
                                },
                            }
                        }
                    }
                }
            }
        },
    }

    pairs = build_strategy_pairs(config_manager, live_pairs=[("BTCUSDT", "1h")])

    assert [pair.key for pair in pairs] == ["BTCUSDT:1h"]
    assert pairs[0].model_names == ["Momentum", "RegimePullbackScorer"]


def test_build_strategy_pairs_does_not_create_manifest_only_workers() -> None:
    ConfigManager.reset_singleton()
    config_manager = ConfigManager()
    config_manager.register_file = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    config_manager._load_configs = lambda trigger_callbacks=True: None  # type: ignore[method-assign]
    config_manager._state = {"models": {"assets": {}}}

    pairs = build_strategy_pairs(
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


def test_partial_manifests_gate_owned_strategy_asset_only() -> None:
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
                },
                "ETHUSDT": {
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
                },
            }
        }
    }

    pairs = build_strategy_pairs(
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

    assert [pair.key for pair in pairs] == ["BTCUSDT:1h", "ETHUSDT:1h"]
