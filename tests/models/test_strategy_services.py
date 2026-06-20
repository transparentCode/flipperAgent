from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.strategy_app.evaluation.service import StrategyEvaluationService
from apps.strategy_app.publishing.signals import (
    StrategySignalPublisher,
    make_signal_idempotency_key,
)
from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.contracts.strategy_model import ModelDecision


def _feature_vector() -> FeatureVector:
    return FeatureVector(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        features={},
        bar_data={
            "open": 49000.0,
            "high": 51000.0,
            "low": 48500.0,
            "close": 50000.0,
            "volume": 100.0,
        },
    )


def test_evaluation_service_blends_before_selection() -> None:
    model_manager = MagicMock()
    scoring_model_manager = MagicMock()
    selection_layer = MagicMock()
    blender = MagicMock()
    logger = MagicMock()

    feature_vec = _feature_vector().model_copy(
        update={
            "features": {
                "regime_snapshot": {"regime": "TREND", "changepoint_prob": 0.1},
                "mtf_agreement": 1.0,
            }
        }
    )
    blended = ScoringOutput(
        model_name="regime_ensemble",
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        edge_score=0.6,
        conviction=0.8,
    )
    scoring_output = ScoringOutput(
        model_name="Momentum",
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        edge_score=0.4,
        conviction=0.7,
    )
    adapted_output = ScoringOutput(
        model_name="MeanReversion",
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        edge_score=0.2,
        conviction=0.5,
    )

    model_manager.evaluate.return_value = []
    model_manager.evaluate_adapted.return_value = [adapted_output]
    model_manager.evaluate_scoring.return_value = []
    model_manager.evaluate_shadow.return_value = []
    scoring_model_manager.evaluate.return_value = [scoring_output]
    blender.blend.return_value = blended

    service = StrategyEvaluationService(
        asset="BTCUSDT",
        timeframe="1h",
        model_manager=model_manager,
        scoring_model_manager=scoring_model_manager,
        selection_layer=selection_layer,
        logger=logger,
        blender=blender,
    )

    service.evaluate_feature_vector(feature_vec)

    selection_layer.select.assert_called_once()
    kwargs = selection_layer.select.call_args.kwargs
    assert kwargs["scoring_outputs"] == [blended]


def test_evaluation_service_includes_unified_strategy_model_outputs() -> None:
    model_manager = MagicMock()
    scoring_model_manager = MagicMock()
    unified_model_manager = MagicMock()
    selection_layer = MagicMock()
    logger = MagicMock()

    feature_vec = _feature_vector()
    model_manager.evaluate.return_value = []
    model_manager.evaluate_adapted.return_value = []
    model_manager.evaluate_scoring.return_value = []
    model_manager.evaluate_shadow.return_value = []
    scoring_model_manager.evaluate.return_value = []
    unified_model_manager.evaluate.return_value = [
        ModelDecision(
            model_name="SqueezeBreakoutV2",
            asset="BTCUSDT",
            decision_timeframe="1h",
            trigger_timeframe="1h",
            timestamp=feature_vec.timestamp,
            score=0.55,
            direction_hint=1,
            conviction=0.7,
            metadata={"source": "canonical"},
        )
    ]

    service = StrategyEvaluationService(
        asset="BTCUSDT",
        timeframe="1h",
        model_manager=model_manager,
        scoring_model_manager=scoring_model_manager,
        unified_model_manager=unified_model_manager,
        selection_layer=selection_layer,
        logger=logger,
    )

    service.evaluate_feature_vector(feature_vec)

    kwargs = selection_layer.select.call_args.kwargs
    assert len(kwargs["scoring_outputs"]) == 1
    assert kwargs["scoring_outputs"][0].model_name == "SqueezeBreakoutV2"
    assert kwargs["scoring_outputs"][0].edge_score == 0.55


@pytest.mark.asyncio
async def test_signal_publisher_publishes_selected_candidates() -> None:
    logger = MagicMock()
    redis_client = AsyncMock()
    publisher = StrategySignalPublisher(
        signal_stream_key="signals:BTCUSDT:1h",
        maxlen=123,
        approximate=False,
        logger=logger,
    )
    feature_vec = _feature_vector()
    candidate = SimpleNamespace(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        direction=1,
        conviction=0.9,
        model_name="Momentum",
        metadata={"score": 0.7},
    )
    result = SimpleNamespace(
        candidate=candidate,
        rank=1,
        selection_score=0.8,
        penalties=[],
    )

    published = await publisher.publish_selected(
        redis_client=redis_client,
        feature_vec=feature_vec,
        selected=[result],
    )

    assert published == 1
    redis_client.xadd.assert_awaited_once()
    assert make_signal_idempotency_key("Momentum", "BTCUSDT", "1h", 1_700_000_000.0)
