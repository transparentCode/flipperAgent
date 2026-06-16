"""Tests for per-model risk profile resolution."""

from libs.risk.profile_resolver import resolve_risk_config, resolve_risk_config_for_model


def test_returns_original_when_no_profiles() -> None:
    config = {"position_sizing": {"default_strategy": "fixed_fractional"}}
    resolved = resolve_risk_config_for_model(config, "Trend")
    assert resolved == config


def test_applies_default_and_model_profile_overrides() -> None:
    config = {
        "position_sizing": {
            "default_strategy": "fixed_fractional",
            "fixed_fractional": {"risk_per_trade_pct": 2.0},
            "volatility_scaled": {"target_risk_pct": 1.0},
        },
        "stop_loss": {
            "default_method": "fixed_pct",
            "fixed_pct": {"pct": 2.0},
            "atr_based": {"multiplier": 2.0},
        },
        "take_profit": {
            "default_method": "risk_reward",
            "risk_reward": {"ratio": 2.0},
            "multi_level": {"levels": [{"pct": 1.5, "portion": 1.0}]},
        },
        "global_limits": {"max_total_exposure_pct": 80},
        "mtf": {"default_conflict_resolution": "conviction_weighted"},
        "model_profiles": {
            "default": {
                "limits": {"max_total_exposure_pct": 70},
            },
            "Trend": {
                "position_sizing": {"strategy": "volatility_scaled"},
                "stop_loss": {"method": "atr_based"},
                "take_profit": {"method": "multi_level"},
                "mtf": {"conflict_resolution": "higher_tf_priority"},
                "limits": {"max_total_exposure_pct": 60},
            },
        },
    }

    resolved = resolve_risk_config_for_model(config, "Trend")

    assert resolved["position_sizing"]["default_strategy"] == "volatility_scaled"
    assert resolved["stop_loss"]["default_method"] == "atr_based"
    assert resolved["take_profit"]["default_method"] == "multi_level"
    assert resolved["mtf"]["default_conflict_resolution"] == "higher_tf_priority"
    assert resolved["global_limits"]["max_total_exposure_pct"] == 60
    assert config["position_sizing"]["default_strategy"] == "fixed_fractional"


def test_unknown_model_uses_default_profile_only() -> None:
    config = {
        "global_limits": {"max_total_exposure_pct": 80},
        "model_profiles": {
            "default": {"limits": {"max_total_exposure_pct": 75}},
        },
    }

    resolved = resolve_risk_config_for_model(config, "Unknown")

    assert resolved["global_limits"]["max_total_exposure_pct"] == 75


def test_asset_and_asset_model_overrides_are_applied_last() -> None:
    config = {
        "global_limits": {"max_total_exposure_pct": 80},
        "position_sizing": {"default_strategy": "fixed_fractional"},
        "stop_loss": {"default_method": "fixed_pct"},
        "take_profit": {"default_method": "risk_reward"},
        "model_profiles": {
            "Trend": {
                "position_sizing": {"strategy": "volatility_scaled"},
                "limits": {"max_total_exposure_pct": 70},
            }
        },
        "assets": {
            "default": {
                "stop_loss": {"method": "atr_based"},
                "model_profiles": {
                    "default": {"limits": {"max_total_exposure_pct": 75}},
                },
            },
            "BTCUSDT": {
                "take_profit": {"method": "multi_level"},
                "model_profiles": {
                    "Trend": {
                        "position_sizing": {"strategy": "kelly"},
                        "limits": {"max_total_exposure_pct": 55},
                    }
                },
            },
        },
    }

    resolved = resolve_risk_config(config, asset="BTCUSDT", model_name="Trend")

    assert resolved["stop_loss"]["default_method"] == "atr_based"
    assert resolved["take_profit"]["default_method"] == "multi_level"
    assert resolved["position_sizing"]["default_strategy"] == "kelly"
    assert resolved["global_limits"]["max_total_exposure_pct"] == 55
