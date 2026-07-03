"""Tests for the Phase 6J PriceAction asset paper guardrail."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from libs.contracts.signal import FeatureVector, ModelOutput, SelectionCandidate
from libs.selection.regime_v2_pa_asset_paper_guardrail import preview_pa_asset_paper_guardrail
from libs.selection.regime_v2_pa_paper_log import persist_pa_paper_decision
from libs.selection.selection_layer import SelectionLayer
from libs.selection.strategies import OverlapPenalizedStrategy, TopKStrategy


def _candidate(model_name="PriceAction", asset="BNBUSDT", timeframe="1h", direction=1):
    return SelectionCandidate(
        model_name=model_name,
        asset=asset,
        timeframe=timeframe,
        timestamp=1000.0,
        direction=direction,
        edge_score=0.9,
        conviction=0.9,
        source_type="threshold",
    )


def _feature_vec():
    return FeatureVector(
        asset="BNBUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={"regime_v2": {"evidence": {}, "policy": {}}},
        bar_data={"close": 100.0},
    )


def test_paper_guardrail_disabled_is_noop():
    candidates = [_candidate(), _candidate(model_name="Momentum")]

    paper_candidates, decision = preview_pa_asset_paper_guardrail(
        candidates,
        {"overlays": {"regime_v2_pa_asset_guardrail": {"paper_enabled": False}}},
    )

    assert paper_candidates is candidates
    assert decision["reason"] == "paper_disabled"
    assert decision["active"] is False
    assert decision["suppressed_count"] == 0


def test_paper_guardrail_suppresses_only_exact_bnb_long_price_action():
    candidates = [
        _candidate(direction=1),
        _candidate(direction=-1),
        _candidate(asset="BTCUSDT", timeframe="4h", direction=1),
        _candidate(model_name="Momentum", direction=1),
    ]
    config = {
        "overlays": {
            "regime_v2_pa_asset_guardrail": {
                "paper_enabled": True,
                "asset": "BNBUSDT",
                "timeframe": "1h",
                "direction": 1,
                "model_name": "PriceAction",
            }
        }
    }

    paper_candidates, decision = preview_pa_asset_paper_guardrail(candidates, config)

    assert decision["active"] is True
    assert decision["suppressed_count"] == 1
    assert [candidate.model_name for candidate in paper_candidates] == ["PriceAction", "PriceAction", "Momentum"]
    assert paper_candidates[0].direction == -1
    assert paper_candidates[1].asset == "BTCUSDT"


def test_paper_log_noop_and_write(tmp_path):
    path = tmp_path / "pa_paper.jsonl"
    assert persist_pa_paper_decision(
        {"paper_active": True},
        asset="BNBUSDT",
        timeframe="1h",
        timestamp=1000.0,
        config={"paper_persist_enabled": False, "paper_persist_path": str(path)},
        selected_count=1,
    ) is None
    assert not path.exists()

    result = persist_pa_paper_decision(
        {
            "paper_active": True,
            "paper_reason": "price_action_asset_direction_suppressed",
            "target_model": "PriceAction",
            "target_asset": "BNBUSDT",
            "target_timeframe": "1h",
            "target_direction": 1,
            "suppressed_count": 1,
            "suppressed_models": ["PriceAction"],
            "baseline_selected_model": "PriceAction",
            "paper_selected_model": "Momentum",
            "selection_changed": True,
        },
        asset="BNBUSDT",
        timeframe="1h",
        timestamp=1000.0,
        config={"paper_persist_enabled": True, "paper_persist_path": str(path)},
        selected_count=2,
    )

    assert result == path
    record = json.loads(path.read_text().strip())
    assert record["record_type"] == "regime_v2_pa_asset_paper_decision"
    assert record["paper_active"] is True
    assert record["paper_selected_model"] == "Momentum"


def test_selection_layer_paper_guardrail_preserves_live_pick_and_persists(tmp_path):
    layer = object.__new__(SelectionLayer)
    layer.asset = "BNBUSDT"
    layer.timeframe = "1h"
    layer._strategy = TopKStrategy(OverlapPenalizedStrategy())
    path = tmp_path / "pa_paper.jsonl"
    layer._config = {
        "top_k": 5,
        "same_direction_penalty": 0.3,
        "max_penalty": 0.8,
        "overlays": {
            "regime_v2_trend_gate": {"enabled": False, "shadow_enabled": False},
            "regime_v2_pa_asset_guardrail": {
                "paper_enabled": True,
                "paper_persist_enabled": True,
                "paper_persist_path": str(path),
                "asset": "BNBUSDT",
                "timeframe": "1h",
                "direction": 1,
                "model_name": "PriceAction",
            },
        },
    }
    outputs = [
        ModelOutput(model_name="PriceAction", asset="BNBUSDT", timeframe="1h", timestamp=1000.0, direction=1, conviction=0.99),
        ModelOutput(model_name="Momentum", asset="BNBUSDT", timeframe="1h", timestamp=1000.0, direction=1, conviction=0.8),
    ]

    results = layer.select(outputs, None, _feature_vec())

    assert results[0].candidate.model_name == "PriceAction"
    payload = results[0].candidate.metadata["regime_v2_pa_asset_paper_guardrail"]
    assert payload["paper_active"] is True
    assert payload["baseline_selected_model"] == "PriceAction"
    assert payload["paper_selected_model"] == "Momentum"
    assert payload["selection_changed"] is True
    record = json.loads(path.read_text().strip())
    assert record["baseline_selected_model"] == "PriceAction"
    assert record["paper_selected_model"] == "Momentum"


def test_selection_config_paper_guardrail_disabled_by_default():
    selection = yaml.safe_load(Path("configs/selection.yaml").read_text())["selection"]
    default_guardrail = selection["assets"]["default"]["timeframes"]["default"]["overlays"]["regime_v2_pa_asset_guardrail"]
    bnb_guardrail = selection["assets"]["BNBUSDT"]["timeframes"]["1h"]["overlays"]["regime_v2_pa_asset_guardrail"]

    assert default_guardrail["paper_enabled"] is False
    assert default_guardrail["paper_persist_enabled"] is False
    assert bnb_guardrail["paper_enabled"] is False
    assert bnb_guardrail["paper_persist_enabled"] is False
    assert bnb_guardrail["asset"] == "BNBUSDT"
    assert bnb_guardrail["timeframe"] == "1h"
    assert bnb_guardrail["direction"] == 1
