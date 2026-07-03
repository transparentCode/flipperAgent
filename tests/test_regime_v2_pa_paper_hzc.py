"""Tests for Phase 6Y PA paper long-horizon candidate descriptor."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_hzc import _parse_args
from libs.selection.regime_v2_pa_paper_hzc import (
    build_pa_paper_horizon_candidate_report,
    render_pa_paper_horizon_candidate_markdown,
)


def _config(*, paper_enabled: bool = False, candidate_enabled: bool = False) -> dict:
    return {
        "selection": {
            "assets": {
                "BNBUSDT": {
                    "timeframes": {
                        "1h": {
                            "overlays": {
                                "regime_v2_trend_gate": {"enabled": False},
                                "regime_v2_pa_asset_guardrail": {
                                    "paper_enabled": paper_enabled,
                                    "paper_log_enabled": False,
                                    "paper_persist_enabled": False,
                                    "model_name": "PriceAction",
                                    "asset": "BNBUSDT",
                                    "timeframe": "1h",
                                    "direction": 1,
                                    "long_horizon_candidate": {
                                        "candidate_enabled": candidate_enabled,
                                        "paper_runtime_enabled": False,
                                        "rule_name": "rolling_avg_below_002_3",
                                        "rule_type": "rolling_avg_below",
                                        "window": 3,
                                        "threshold": -0.002,
                                        "valid_horizons_bars": [6, 12, 24],
                                        "invalid_horizons_bars": [3],
                                        "source_report": "research/regime_v2_pa_paper_hz.json",
                                    },
                                },
                            }
                        }
                    }
                }
            }
        }
    }


def _horizon_report(*, recommendation: str = "long_horizon_paper_candidate") -> dict:
    return {
        "summary": {
            "recommendation": recommendation,
            "long_horizon_candidate": True,
            "best_variant": {
                "name": "rolling_avg_below_002_3",
                "long_lost_avoided_loss_count": 0,
                "short_failed_cell_count": 3,
            },
        }
    }


def test_hzc_accepts_safe_disabled_candidate():
    report = build_pa_paper_horizon_candidate_report(_config(), _horizon_report())

    assert report["summary"]["safe"] is True
    assert report["summary"]["recommendation"] == "metadata_candidate_disabled_ok"
    assert report["violations"] == []
    assert report["summary"]["candidate_enabled"] is False
    assert report["summary"]["paper_runtime_enabled"] is False


def test_hzc_rejects_enabled_runtime_or_descriptor():
    report = build_pa_paper_horizon_candidate_report(_config(paper_enabled=True, candidate_enabled=True), _horizon_report())

    assert report["summary"]["safe"] is False
    assert "paper_runtime_enabled" in report["violations"]
    assert "descriptor_candidate_enabled" in report["violations"]


def test_hzc_rejects_bad_horizon_report_and_renders_markdown():
    report = build_pa_paper_horizon_candidate_report(_config(), _horizon_report(recommendation="hold_off_no_horizon_candidate"))

    assert report["summary"]["safe"] is False
    assert "horizon_report_not_candidate" in report["violations"]
    md = render_pa_paper_horizon_candidate_markdown(report)
    assert "# RegimeV2 Phase 6Y PA Long-Horizon Candidate" in md
    assert "horizon_report_not_candidate" in md


def test_hzc_cli_defaults_and_args():
    args = _parse_args(
        [
            "--config",
            "selection.yaml",
            "--horizon-report",
            "hz.json",
            "--asset",
            "BNBUSDT",
            "--timeframe",
            "1h",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.config == "selection.yaml"
    assert args.horizon_report == "hz.json"
    assert args.asset == "BNBUSDT"
    assert args.timeframe == "1h"

    defaults = _parse_args([])
    assert defaults.config == "configs/selection.yaml"
    assert defaults.horizon_report == "research/regime_v2_pa_paper_hz.json"
