"""Tests for the Phase 6L PA paper Binance collector."""

from __future__ import annotations

import argparse

from libs.models.regime_v2.scripts.collect_pa_paper_binance import _parse_args, _paper_replay_config


def test_paper_replay_config_enables_only_pa_paper_guardrail():
    config = {
        "top_k": 5,
        "overlays": {
            "regime_v2_trend_gate": {
                "enabled": True,
                "shadow_enabled": True,
                "shadow_persist_enabled": True,
            }
        },
    }

    out = _paper_replay_config(config, asset="BNBUSDT", timeframe="1h", log_path="logs/paper.jsonl")

    gate = out["overlays"]["regime_v2_trend_gate"]
    guardrail = out["overlays"]["regime_v2_pa_asset_guardrail"]
    assert gate["enabled"] is False
    assert gate["shadow_enabled"] is False
    assert gate["shadow_persist_enabled"] is False
    assert guardrail["paper_enabled"] is True
    assert guardrail["paper_persist_enabled"] is True
    assert guardrail["paper_persist_path"] == "logs/paper.jsonl"
    assert guardrail["asset"] == "BNBUSDT"
    assert guardrail["timeframe"] == "1h"
    assert guardrail["direction"] == 1
    assert config["overlays"]["regime_v2_trend_gate"]["enabled"] is True


def test_collect_pa_paper_parse_args_defaults():
    args = _parse_args([])

    assert args.asset == "BNBUSDT"
    assert args.timeframe == "1h"
    assert args.limit == 1000
    assert args.horizon_bars == 12
    assert args.warmup_bars == 220
    assert args.max_records == 180
    assert args.log_path.endswith("pa_asset_paper_decisions.jsonl")
    assert args.model is None


def test_collect_pa_paper_parse_args_custom():
    args = _parse_args(
        [
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "900",
            "--since",
            "2026-01-01T00:00:00Z",
            "--until",
            "2026-02-01T00:00:00Z",
            "--horizon-bars",
            "6",
            "--warmup-bars",
            "100",
            "--max-records",
            "50",
            "--model",
            "PriceAction",
            "--log-path",
            "logs/custom.jsonl",
            "--reset-log",
            "--output-json",
            "research/custom.json",
            "--report-json",
            "research/report.json",
            "--report-md",
            "research/report.md",
        ]
    )

    assert isinstance(args, argparse.Namespace)
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 900
    assert args.since == "2026-01-01T00:00:00Z"
    assert args.until == "2026-02-01T00:00:00Z"
    assert args.horizon_bars == 6
    assert args.warmup_bars == 100
    assert args.max_records == 50
    assert args.model == ["PriceAction"]
    assert args.log_path == "logs/custom.jsonl"
    assert args.reset_log is True
    assert args.output_json == "research/custom.json"
    assert args.report_json == "research/report.json"
    assert args.report_md == "research/report.md"
