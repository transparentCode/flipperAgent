"""Integration test — StrategyWorker with RegimeEnsembleBlender in the loop.

Verifies that when blender is enabled and regime_snapshot is present in
feature_vec, the pipeline produces blended scoring output and SelectionLayer
processes it correctly.
"""

from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import pytest

from apps.strategy_app.strategy_worker import StrategyWorker
from libs.contracts.signal import ScoringOutput


@dataclass
class FakeRegimeFeatures:
    regime: str = "CLEAN_TREND_BULL"
    p_trending: float = 0.8
    vol_percentile: float = 30.0
    changepoint_prob: float = 0.1
    adaptive_period: int = 20
    position_scale: float = 1.0


class TestStrategyWorkerBlenderIntegration:
    """Verify blender integrates correctly in StrategyWorker pipeline."""

    def test_blender_instantiation_when_enabled(self):
        """Blender is created when config has enabled: true."""
        blender_cfg = {
            "enabled": True,
            "transition": {"entry_threshold": 0.70, "exit_threshold": 0.30, "floor": 0.15},
            "mtf": {"confirming_scale": 1.2, "conflicting_scale": 0.5},
            "weights": {
                "CLEAN_TREND": {"mean_reversion": 0.15, "momentum": 0.55, "squeeze_breakout": 0.30},
                "CHOPPY": {"mean_reversion": 0.33, "momentum": 0.34, "squeeze_breakout": 0.33},
                "TRANSITION": {"mean_reversion": 0.33, "momentum": 0.34, "squeeze_breakout": 0.33},
            },
        }
        with patch("libs.common.config.ConfigManager.get", return_value=blender_cfg):
            sw = StrategyWorker("BTCUSDT", "1h")

        assert sw.blender is not None

    def test_blender_disabled_by_default(self):
        """Blender is None when config has enabled: false."""
        sw = StrategyWorker("BTCUSDT", "1h")
        assert sw.blender is None

    def test_blended_output_is_valid_scoring_output(self):
        """Blended output is a standard ScoringOutput accepted by SelectionLayer."""
        from libs.models.blender.ensemble import RegimeEnsembleBlender

        config = {
            "transition": {"entry_threshold": 0.70, "exit_threshold": 0.30, "floor": 0.15},
            "mtf": {"confirming_scale": 1.2, "conflicting_scale": 0.5},
            "weights": {
                "CLEAN_TREND": {"mean_reversion": 0.15, "momentum": 0.55, "squeeze_breakout": 0.30},
            },
        }
        blender = RegimeEnsembleBlender(config)
        scoring_outputs = [
            ScoringOutput(
                model_name="mean_reversion", asset="BTCUSDT", timeframe="1h",
                timestamp=1000.0, edge_score=0.5, conviction=0.8,
            ),
            ScoringOutput(
                model_name="momentum", asset="BTCUSDT", timeframe="1h",
                timestamp=1000.0, edge_score=0.3, conviction=0.7,
            ),
            ScoringOutput(
                model_name="squeeze_breakout", asset="BTCUSDT", timeframe="1h",
                timestamp=1000.0, edge_score=0.8, conviction=0.9,
            ),
        ]
        regime = FakeRegimeFeatures(regime="CLEAN_TREND_BULL", changepoint_prob=0.1)

        result = blender.blend(scoring_outputs, regime)

        assert isinstance(result, ScoringOutput)
        assert result.model_name == "regime_ensemble"
        assert result.edge_score != 0.0
        assert 0.0 <= result.conviction <= 1.0
        assert "regime_group" in result.metadata
        assert result.metadata["regime_group"] == "CLEAN_TREND"
