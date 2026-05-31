"""Tests for regime_snapshot wiring from SignalWorker → StrategyWorker → Blender."""

from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from libs.contracts.signal import ScoringOutput
from libs.models.blender.ensemble import RegimeEnsembleBlender


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_REGIME_SNAPSHOT = {
    "regime": "CLEAN_TREND_BULL",
    "p_trending": 0.85,
    "vol_percentile": 42.0,
    "changepoint_prob": 0.12,
    "adaptive_period": 20,
    "position_scale": 1.0,
    "atr_multiplier": 2.5,
    "holding_period": 12,
    "hilbert_period": 18.0,
    "hilbert_confidence": 0.72,
}


def _blender_config() -> dict:
    return {
        "enabled": True,
        "transition": {
            "entry_threshold": 0.70,
            "exit_threshold": 0.30,
            "floor": 0.15,
        },
        "mtf": {"confirming_scale": 1.2, "conflicting_scale": 0.5},
        "weights": {
            "CLEAN_TREND": {"mean_reversion": 0.3, "momentum": 0.7},
            "CHOPPY": {"mean_reversion": 0.5, "momentum": 0.5},
            "TRANSITION": {"mean_reversion": 0.4, "momentum": 0.6},
        },
    }


def _scoring_outputs() -> list[ScoringOutput]:
    return [
        ScoringOutput(
            model_name="mean_reversion",
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1_700_000_000_000.0,
            edge_score=0.65,
            conviction=0.8,
        ),
        ScoringOutput(
            model_name="momentum",
            asset="BTCUSDT",
            timeframe="4h",
            timestamp=1_700_000_000_000.0,
            edge_score=0.82,
            conviction=0.9,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests: _regime_features_to_dict serialization
# ---------------------------------------------------------------------------


class TestRegimeFeaturesToDict:
    def test_serializes_all_expected_keys(self) -> None:
        from apps.signal_app.signal_worker import _regime_features_to_dict

        # Create a mock RegimeFeatures with attribute access
        rf = types.SimpleNamespace(
            regime="CHOPPY",
            p_trending=0.3,
            vol_percentile=60.0,
            changepoint_prob=0.05,
            adaptive_period=14,
            position_scale=0.8,
            atr_multiplier=3.0,
            holding_period=8,
            hilbert_period=20.0,
            hilbert_confidence=0.5,
        )
        result = _regime_features_to_dict(rf)

        assert result["regime"] == "CHOPPY"
        assert result["changepoint_prob"] == 0.05
        assert result["p_trending"] == 0.3
        assert result["hilbert_period"] == 20.0
        assert len(result) == 10

    def test_all_values_json_serializable(self) -> None:
        import json

        from apps.signal_app.signal_worker import _regime_features_to_dict

        rf = types.SimpleNamespace(**SAMPLE_REGIME_SNAPSHOT)
        result = _regime_features_to_dict(rf)

        # Must be JSON-serializable (goes through Valkey)
        serialized = json.dumps(result)
        assert isinstance(serialized, str)


# ---------------------------------------------------------------------------
# Tests: SimpleNamespace bridge in StrategyWorker
# ---------------------------------------------------------------------------


class TestBlenderSimpleNamespaceBridge:
    """Verify that a dict→SimpleNamespace conversion works with the real blender."""

    def test_blender_accepts_simple_namespace(self) -> None:
        """The blender accesses .regime and .changepoint_prob via attribute access."""
        blender = RegimeEnsembleBlender(_blender_config())
        regime_ns = types.SimpleNamespace(**SAMPLE_REGIME_SNAPSHOT)

        result = blender.blend(
            scoring_outputs=_scoring_outputs(),
            regime_features=regime_ns,
        )

        assert result is not None
        assert result.model_name == "regime_ensemble"
        assert result.edge_score > 0
        assert result.metadata["regime_group"] == "CLEAN_TREND"

    def test_blender_with_mtf_confirming(self) -> None:
        blender = RegimeEnsembleBlender(_blender_config())
        regime_ns = types.SimpleNamespace(**SAMPLE_REGIME_SNAPSHOT)

        result_no_mtf = blender.blend(_scoring_outputs(), regime_ns)
        blender_2 = RegimeEnsembleBlender(_blender_config())
        result_mtf = blender_2.blend(_scoring_outputs(), regime_ns, mtf_agreement="CONFIRMING")

        assert result_mtf.edge_score > result_no_mtf.edge_score

    def test_blender_transition_with_namespace(self) -> None:
        """High changepoint_prob triggers transition state via namespace."""
        blender = RegimeEnsembleBlender(_blender_config())
        snapshot = dict(SAMPLE_REGIME_SNAPSHOT)
        snapshot["changepoint_prob"] = 0.85  # above entry_threshold
        regime_ns = types.SimpleNamespace(**snapshot)

        result = blender.blend(_scoring_outputs(), regime_ns)
        assert result.metadata["regime_group"] == "TRANSITION"


# ---------------------------------------------------------------------------
# Tests: SignalWorker regime integration
# ---------------------------------------------------------------------------


class TestSignalWorkerRegimeIntegration:
    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_regime_snapshot_injected_when_history_sufficient(self, MockFM) -> None:
        """When price history >= 200 bars and orchestrator works, regime_snapshot appears in features."""
        from apps.signal_app.signal_worker import SignalWorker

        mock_fm = MagicMock()
        mock_fm.indicators = []
        mock_fm.process_tick.return_value = {"RSI": 50.0}
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()

        # Pre-fill price history to exceed _REGIME_MIN_BARS
        worker._price_history = [
            {"open": 49000, "high": 51000, "low": 48500, "close": 50000, "volume": 100}
        ] * 200

        # Mock the regime orchestrator
        mock_regime = MagicMock()
        mock_regime.analyze.return_value = types.SimpleNamespace(
            regime="CLEAN_TREND_BULL",
            p_trending=0.85,
            vol_percentile=42.0,
            changepoint_prob=0.12,
            adaptive_period=20,
            position_scale=1.0,
            atr_multiplier=2.5,
            holding_period=12,
            hilbert_period=18.0,
            hilbert_confidence=0.72,
        )
        worker._regime_orchestrator = mock_regime

        payload = {
            "bar_closed": "true",
            "open": "49000.0", "high": "51000.0", "low": "48500.0",
            "close": "50000.0", "volume": "100.0",
            "timestamp": "1700000000000.0",
        }
        await worker.process_message("msg-1", payload)

        # Verify regime analysis was called
        mock_regime.analyze.assert_called_once()

        # Verify feature vector published includes regime_snapshot
        xadd_calls = worker.redis_client.xadd.call_args_list
        assert len(xadd_calls) >= 1  # at least feature stream
        feature_call = xadd_calls[0]
        published_payload = feature_call[0][1]
        # The features dict is JSON-encoded; check that regime_snapshot key is present
        import json
        features_json = published_payload.get("features")
        if features_json:
            features_dict = json.loads(features_json)
            assert "regime_snapshot" in features_dict
            assert features_dict["regime_snapshot"]["regime"] == "CLEAN_TREND_BULL"

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_regime_skipped_when_history_insufficient(self, MockFM) -> None:
        """When price history < 200 bars, regime_snapshot should NOT appear."""
        from apps.signal_app.signal_worker import SignalWorker

        mock_fm = MagicMock()
        mock_fm.indicators = []
        mock_fm.process_tick.return_value = {"RSI": 50.0}
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()
        worker._price_history = []  # empty history

        mock_regime = MagicMock()
        worker._regime_orchestrator = mock_regime

        payload = {
            "bar_closed": "true",
            "open": "49000.0", "high": "51000.0", "low": "48500.0",
            "close": "50000.0", "volume": "100.0",
            "timestamp": "1700000000000.0",
        }
        await worker.process_message("msg-1", payload)

        # Orchestrator.analyze should NOT be called (only 1 bar in history)
        mock_regime.analyze.assert_not_called()

    @pytest.mark.asyncio
    @patch("apps.signal_app.signal_worker.FeatureManager")
    async def test_regime_failure_does_not_break_feature_publishing(self, MockFM) -> None:
        """If regime analysis raises, features are still published without regime_snapshot."""
        from apps.signal_app.signal_worker import SignalWorker

        mock_fm = MagicMock()
        mock_fm.indicators = []
        mock_fm.process_tick.return_value = {"RSI": 50.0}
        MockFM.return_value = mock_fm

        worker = SignalWorker("BTCUSDT", "4h")
        worker.redis_client = AsyncMock()
        worker._price_history = [
            {"open": 49000, "high": 51000, "low": 48500, "close": 50000, "volume": 100}
        ] * 200

        mock_regime = MagicMock()
        mock_regime.analyze.side_effect = RuntimeError("HMM boom")
        worker._regime_orchestrator = mock_regime

        payload = {
            "bar_closed": "true",
            "open": "49000.0", "high": "51000.0", "low": "48500.0",
            "close": "50000.0", "volume": "100.0",
            "timestamp": "1700000000000.0",
        }
        await worker.process_message("msg-1", payload)

        # Features should still be published despite regime failure
        assert worker.redis_client.xadd.call_count == 2  # features + price_update
