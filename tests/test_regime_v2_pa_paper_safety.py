"""Tests for Phase 6N PA paper rollout safety."""

from __future__ import annotations

from pathlib import Path

import yaml

from libs.models.regime_v2.scripts.pa_paper_safety import _parse_args
from libs.selection.regime_v2_pa_paper_safety import (
    render_pa_paper_rollout_safety_markdown,
    validate_pa_paper_rollout_config,
)


def _base_config(*, enabled: bool = False, persist: bool = False) -> dict:
    return {
        "selection": {
            "assets": {
                "default": {
                    "timeframes": {
                        "default": {
                            "overlays": {
                                "regime_v2_trend_gate": {"enabled": False},
                                "regime_v2_pa_asset_guardrail": {
                                    "paper_enabled": False,
                                    "paper_persist_enabled": False,
                                    "model_name": "PriceAction",
                                    "asset": "BNBUSDT",
                                    "timeframe": "1h",
                                    "direction": 1,
                                    "paper_persist_path": "logs/regime_v2_pa_asset_paper_decisions.jsonl",
                                },
                            }
                        }
                    }
                },
                "BNBUSDT": {
                    "timeframes": {
                        "1h": {
                            "overlays": {
                                "regime_v2_trend_gate": {"enabled": False, "shadow_enabled": True},
                                "regime_v2_pa_asset_guardrail": {
                                    "paper_enabled": enabled,
                                    "paper_persist_enabled": persist,
                                    "model_name": "PriceAction",
                                    "asset": "BNBUSDT",
                                    "timeframe": "1h",
                                    "direction": 1,
                                    "paper_persist_path": "logs/regime_v2_pa_asset_paper_decisions.jsonl",
                                },
                            }
                        }
                    }
                },
            }
        }
    }


def test_default_selection_yaml_is_safe_but_not_rollout_ready():
    config = yaml.safe_load(Path("configs/selection.yaml").read_text())

    report = validate_pa_paper_rollout_config(config)

    assert report["summary"]["safe"] is True
    assert report["summary"]["rollout_ready"] is False
    assert report["summary"]["enabled_pair_count"] == 0
    assert report["violations"] == []


def test_require_enabled_fails_when_default_disabled():
    report = validate_pa_paper_rollout_config(_base_config(), require_enabled=True)

    assert report["summary"]["safe"] is False
    assert {item["code"] for item in report["violations"]} == {"paper_not_enabled", "paper_persist_not_enabled"}


def test_expected_pair_enabled_and_persisted_is_rollout_ready():
    report = validate_pa_paper_rollout_config(_base_config(enabled=True, persist=True), require_enabled=True)

    assert report["summary"]["safe"] is True
    assert report["summary"]["rollout_ready"] is True
    assert report["summary"]["enabled_pairs"] == ["BNBUSDT|1h"]
    assert report["summary"]["persist_enabled_pairs"] == ["BNBUSDT|1h"]


def test_live_gate_or_unexpected_pair_enablement_is_unsafe():
    config = _base_config(enabled=True, persist=True)
    config["selection"]["assets"]["BNBUSDT"]["timeframes"]["1h"]["overlays"]["regime_v2_trend_gate"]["enabled"] = True
    config["selection"]["assets"]["BTCUSDT"] = {
        "timeframes": {
            "4h": {
                "overlays": {
                    "regime_v2_trend_gate": {"enabled": False},
                    "regime_v2_pa_asset_guardrail": {"paper_enabled": True, "paper_persist_enabled": False},
                }
            }
        }
    }

    report = validate_pa_paper_rollout_config(config)

    codes = {item["code"] for item in report["violations"]}
    assert "live_gate_enabled" in codes
    assert "unexpected_pa_paper_enabled" in codes
    assert report["summary"]["safe"] is False


def test_paper_log_cannot_use_main_shadow_log():
    config = _base_config(enabled=True, persist=True)
    config["selection"]["assets"]["BNBUSDT"]["timeframes"]["1h"]["overlays"]["regime_v2_pa_asset_guardrail"][
        "paper_persist_path"
    ] = "logs/regime_v2_shadow_decisions.jsonl"

    report = validate_pa_paper_rollout_config(config)

    assert report["summary"]["safe"] is False
    assert {item["code"] for item in report["violations"]} == {"paper_path_conflicts_with_shadow_log"}


def test_safety_markdown_and_cli_args():
    report = validate_pa_paper_rollout_config(_base_config())
    md = render_pa_paper_rollout_safety_markdown(report)
    assert "# RegimeV2 Phase 6N PA Paper Rollout Safety" in md
    assert "- none" in md

    args = _parse_args(["--config", "custom.yaml", "--asset", "ETHUSDT", "--timeframe", "4h", "--require-enabled"])
    assert args.config == "custom.yaml"
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.require_enabled is True
