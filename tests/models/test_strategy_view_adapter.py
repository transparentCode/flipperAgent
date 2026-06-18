from __future__ import annotations

from apps.strategy_app.evaluation import StrategyDecisionViewAdapter
from libs.contracts.schemas import FeatureVector


def _feature_vector(*, timeframe: str, features: dict | None = None) -> FeatureVector:
    return FeatureVector(
        asset="BTCUSDT",
        timeframe=timeframe,
        timestamp=1_700_000_000.0,
        features=features or {},
        bar_data={
            "open": 49000.0,
            "high": 51000.0,
            "low": 48500.0,
            "close": 50000.0,
            "volume": 100.0,
        },
    )


def test_adapter_keeps_matching_decision_timeframe_and_builds_runtime_metadata() -> None:
    adapter = StrategyDecisionViewAdapter(
        decision_timeframe="4h",
        trigger_timeframe="1m",
        trigger_mode="on_base_bar_close",
        base_timeframe="1m",
    )
    feature_vec = _feature_vector(
        timeframe="4h",
        features={
            "ctx_transport": {
                "decision_bar_closed": False,
                "projection_mode": "decision_view",
                "source_feature_timeframe": "1m",
            }
        },
    )

    decision_view = adapter.adapt(feature_vec)

    assert decision_view.feature_vector.timeframe == "4h"
    assert decision_view.feature_vector.features["ctx_transport"]["source_feature_timeframe"] == "1m"
    assert decision_view.runtime_metadata == {
        "decision_timeframe": "4h",
        "trigger_timeframe": "1m",
        "trigger_mode": "on_base_bar_close",
        "source_feature_timeframe": "1m",
        "base_timeframe": "1m",
        "decision_bar_closed": False,
        "projection_mode": "decision_view",
    }


def test_adapter_projects_source_lane_to_decision_timeframe() -> None:
    adapter = StrategyDecisionViewAdapter(
        decision_timeframe="4h",
        trigger_timeframe="1m",
        trigger_mode="on_base_bar_close",
        base_timeframe="1m",
    )
    feature_vec = _feature_vector(timeframe="1m", features={"RSI": {"value": 55.0}})

    decision_view = adapter.adapt(feature_vec)

    transport = decision_view.feature_vector.features["ctx_transport"]
    assert decision_view.feature_vector.timeframe == "4h"
    assert transport["base_timeframe"] == "1m"
    assert transport["trigger_timeframe"] == "1m"
    assert transport["decision_timeframe"] == "4h"
    assert transport["trigger_mode"] == "on_base_bar_close"
    assert transport["source_feature_timeframe"] == "1m"
    assert decision_view.runtime_metadata == {
        "decision_timeframe": "4h",
        "trigger_timeframe": "1m",
        "trigger_mode": "on_base_bar_close",
        "source_feature_timeframe": "1m",
        "base_timeframe": "1m",
    }
