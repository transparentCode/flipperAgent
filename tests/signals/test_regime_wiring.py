"""Tests for regime context wiring in the modular signal pipeline."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from apps.signal_app.pipeline.regime import (
    FeatureProducerConfigResolver,
    RegimeFeaturePipeline,
    regime_features_to_dict,
)
from libs.common.config import ConfigManager
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
            "TREND_BULL": {"mean_reversion": 0.0, "momentum": 1.0},
            "CHOPPY": {"mean_reversion": 0.0, "momentum": 0.13, "squeeze_breakout": 0.87},
            "TRANSITION": {"mean_reversion": 0.0, "momentum": 0.78, "squeeze_breakout": 0.22},
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
        result = regime_features_to_dict(rf)

        assert result["regime"] == "CHOPPY"
        assert result["changepoint_prob"] == 0.05
        assert result["p_trending"] == 0.3
        assert result["hilbert_period"] == 20.0
        assert len(result) == 10

    def test_all_values_json_serializable(self) -> None:
        import json

        rf = types.SimpleNamespace(**SAMPLE_REGIME_SNAPSHOT)
        result = regime_features_to_dict(rf)

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
        assert result.metadata["regime_group"] == "TREND_BULL"

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
# Tests: modular regime pipeline integration
# ---------------------------------------------------------------------------


class TestRegimePipelineIntegration:
    def test_feature_producer_config_deep_merges_fallbacks(self, monkeypatch) -> None:
        ConfigManager.reset_singleton()
        config_manager = ConfigManager()
        monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
        monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
        config_manager._state = {
            "feature_producers": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "RegimeClassification": {
                                    "enabled": False,
                                    "params": {
                                        "bcpd_hazard_lambda": 150.0,
                                        "hurst_lookback": 100,
                                    },
                                    "frozen_overrides": {
                                        "hmm_crisis_vol_mult": 2.0,
                                    },
                                },
                            },
                        },
                    },
                    "BTCUSDT": {
                        "timeframes": {
                            "30m": {
                                "RegimeClassification": {
                                    "enabled": True,
                                    "params": {
                                        "hurst_lookback": 80,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }

        resolved = FeatureProducerConfigResolver(config_manager).resolve(
            "BTCUSDT",
            "30m",
            "RegimeClassification",
        )

        assert resolved["enabled"] is True
        assert resolved["params"]["bcpd_hazard_lambda"] == 150.0
        assert resolved["params"]["hurst_lookback"] == 80
        assert resolved["frozen_overrides"]["hmm_crisis_vol_mult"] == 2.0

    def test_regime_v2_config_fallback_keeps_defaults_disabled(self, monkeypatch) -> None:
        ConfigManager.reset_singleton()
        config_manager = ConfigManager()
        monkeypatch.setattr(config_manager, "_load_configs", lambda trigger_callbacks=True: None)
        monkeypatch.setattr(ConfigManager, "register_file", lambda self, _: None)
        config_manager._state = {
            "feature_producers": {
                "assets": {
                    "default": {
                        "timeframes": {
                            "default": {
                                "RegimeV2": {
                                    "enabled": False,
                                    "params": {
                                        "fusion.trend_threshold": 0.48,
                                        "policy.trend_min_strength": 0.48,
                                    },
                                },
                            },
                        },
                    },
                    "BTCUSDT": {
                        "timeframes": {
                            "4h": {
                                "RegimeV2": {
                                    "params": {
                                        "policy.min_confidence": 0.35,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }

        resolved = FeatureProducerConfigResolver(config_manager).resolve(
            "BTCUSDT",
            "4h",
            "RegimeV2",
        )

        assert resolved["enabled"] is False
        assert resolved["params"]["fusion.trend_threshold"] == 0.48
        assert resolved["params"]["policy.trend_min_strength"] == 0.48
        assert resolved["params"]["policy.min_confidence"] == 0.35

    @pytest.mark.asyncio
    async def test_regime_snapshot_injected_when_history_sufficient(self) -> None:
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
        regime = RegimeFeaturePipeline(
            "BTCUSDT",
            "4h",
            min_bars=3,
            orchestrator=mock_regime,
            classifier=None,
        )
        regime.prime(_history(length=3))

        enriched = await regime.enrich({"RSI": 50.0})

        mock_regime.analyze.assert_called_once()
        assert enriched["regime_snapshot"]["regime"] == "CLEAN_TREND_BULL"

    @pytest.mark.asyncio
    async def test_regime_skipped_when_history_insufficient(self) -> None:
        mock_regime = MagicMock()
        regime = RegimeFeaturePipeline(
            "BTCUSDT",
            "4h",
            min_bars=5,
            orchestrator=mock_regime,
            classifier=None,
        )
        regime.prime(_history(length=3))
        enriched = await regime.enrich({"RSI": 50.0})

        mock_regime.analyze.assert_not_called()
        assert "regime_snapshot" not in enriched

    @pytest.mark.asyncio
    async def test_regime_failure_does_not_break_feature_enrichment(self) -> None:
        mock_regime = MagicMock()
        mock_regime.analyze.side_effect = RuntimeError("HMM boom")
        regime = RegimeFeaturePipeline(
            "BTCUSDT",
            "4h",
            min_bars=3,
            orchestrator=mock_regime,
            classifier=None,
        )
        regime.prime(_history(length=3))

        enriched = await regime.enrich({"RSI": 50.0})

        assert enriched["RSI"] == 50.0
        assert "regime_snapshot" not in enriched


    @pytest.mark.asyncio
    async def test_regime_v2_injected_when_history_sufficient(self) -> None:
        mock_regime_v2 = MagicMock()
        mock_regime_v2.analyze.return_value = {
            "summary_label": "bull_trend",
            "confidence": 0.72,
            "policy": {"allow_trend_following": True, "trend_score": 0.61},
        }
        regime = RegimeFeaturePipeline(
            "BTCUSDT",
            "4h",
            min_bars=3,
            orchestrator=None,
            classifier=None,
            regime_v2=mock_regime_v2,
        )
        regime.prime(_history(length=3))

        enriched = await regime.enrich({"RSI": 50.0, "eng_regime_alignment_score": 0.4})

        mock_regime_v2.analyze.assert_called_once()
        assert enriched["regime_v2"]["summary_label"] == "bull_trend"
        assert enriched["regime_v2"]["policy"]["trend_score"] == 0.61
        assert mock_regime_v2.analyze.call_args.kwargs["latest_features"]["eng_regime_alignment_score"] == 0.4

    @pytest.mark.asyncio
    async def test_regime_v2_skipped_when_history_insufficient(self) -> None:
        mock_regime_v2 = MagicMock()
        regime = RegimeFeaturePipeline(
            "BTCUSDT",
            "4h",
            min_bars=5,
            orchestrator=None,
            classifier=None,
            regime_v2=mock_regime_v2,
        )
        regime.prime(_history(length=3))

        enriched = await regime.enrich({"RSI": 50.0})

        mock_regime_v2.analyze.assert_not_called()
        assert "regime_v2" not in enriched

    @pytest.mark.asyncio
    async def test_regime_v2_failure_does_not_break_feature_enrichment(self) -> None:
        mock_regime_v2 = MagicMock()
        mock_regime_v2.analyze.side_effect = RuntimeError("RegimeV2 boom")
        regime = RegimeFeaturePipeline(
            "BTCUSDT",
            "4h",
            min_bars=3,
            orchestrator=None,
            classifier=None,
            regime_v2=mock_regime_v2,
        )
        regime.prime(_history(length=3))

        enriched = await regime.enrich({"RSI": 50.0})

        assert enriched["RSI"] == 50.0
        assert "regime_v2" not in enriched


def _history(length: int) -> list[tuple[float, ...]]:
    base_ts = 1_700_000_000
    rows = []
    for index in range(length):
        close = 100.0 + index * 0.1
        rows.append(
            (
                close,
                close + 1,
                close - 1,
                close,
                1000.0,
                base_ts + index * 3600,
                550.0 + (index % 20),
            )
        )
    return rows
