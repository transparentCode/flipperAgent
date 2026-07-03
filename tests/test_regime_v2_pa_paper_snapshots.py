"""Tests for Phase 6R PA paper candidate-ranking snapshots."""

from __future__ import annotations

import json

from libs.contracts.signal import FeatureVector, ModelOutput
from libs.selection.regime_v2_pa_paper_log import persist_pa_paper_decision
from libs.selection.selection_layer import SelectionLayer
from libs.selection.strategies import OverlapPenalizedStrategy, TopKStrategy


def _feature_vec():
    return FeatureVector(
        asset="BNBUSDT",
        timeframe="1h",
        timestamp=1000.0,
        features={"regime_v2": {"evidence": {}, "policy": {}}},
        bar_data={"close": 100.0},
    )


def _layer(path):
    layer = object.__new__(SelectionLayer)
    layer.asset = "BNBUSDT"
    layer.timeframe = "1h"
    layer._strategy = TopKStrategy(OverlapPenalizedStrategy())
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
    return layer


def test_selection_layer_pa_paper_payload_contains_ranked_snapshots(tmp_path):
    path = tmp_path / "pa_paper.jsonl"
    layer = _layer(path)
    outputs = [
        ModelOutput(model_name="PriceAction", asset="BNBUSDT", timeframe="1h", timestamp=1000.0, direction=1, conviction=0.99),
        ModelOutput(model_name="Momentum", asset="BNBUSDT", timeframe="1h", timestamp=1000.0, direction=1, conviction=0.8),
        ModelOutput(model_name="TrendFollowing", asset="BNBUSDT", timeframe="1h", timestamp=1000.0, direction=-1, conviction=0.7),
    ]

    results = layer.select(outputs, None, _feature_vec())

    payload = results[0].candidate.metadata["regime_v2_pa_asset_paper_guardrail"]
    assert payload["candidate_snapshot_schema_version"] == 1
    assert payload["baseline_ranked_candidates"][0]["model_name"] == "PriceAction"
    assert {row["model_name"] for row in payload["baseline_ranked_candidates"]} == {"PriceAction", "Momentum", "TrendFollowing"}
    assert {row["model_name"] for row in payload["paper_ranked_candidates"]} == {"Momentum", "TrendFollowing"}
    assert all("selection_score" in row for row in payload["baseline_ranked_candidates"])
    assert all("rank" in row for row in payload["paper_ranked_candidates"])

    record = json.loads(path.read_text().strip())
    assert record["candidate_snapshot_schema_version"] == 1
    assert record["baseline_ranked_candidates"] == payload["baseline_ranked_candidates"]
    assert record["paper_ranked_candidates"] == payload["paper_ranked_candidates"]


def test_pa_paper_log_persists_candidate_snapshots(tmp_path):
    path = tmp_path / "pa_paper.jsonl"
    payload = {
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
        "candidate_snapshot_schema_version": 1,
        "baseline_ranked_candidates": [{"rank": 1, "model_name": "PriceAction", "selection_score": 0.9}],
        "paper_ranked_candidates": [{"rank": 1, "model_name": "Momentum", "selection_score": 0.7}],
    }

    persist_pa_paper_decision(
        payload,
        asset="BNBUSDT",
        timeframe="1h",
        timestamp=1000.0,
        config={"paper_persist_enabled": True, "paper_persist_path": str(path)},
        selected_count=2,
    )

    record = json.loads(path.read_text().strip())
    assert record["candidate_snapshot_schema_version"] == 1
    assert record["baseline_ranked_candidates"][0]["model_name"] == "PriceAction"
    assert record["paper_ranked_candidates"][0]["model_name"] == "Momentum"
    assert record["payload"]["baseline_ranked_candidates"] == record["baseline_ranked_candidates"]
