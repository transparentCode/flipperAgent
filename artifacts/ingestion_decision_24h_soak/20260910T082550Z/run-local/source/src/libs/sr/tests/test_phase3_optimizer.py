"""
Tests — Phase 3: TwoStageOptimizer Orchestrator
=================================================
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.sr.optimization.asset_optimizer import (
    AssetOptimizationConfig,
    AssetOptimizationResult,
)
from app.sr.optimization.two_stage_optimizer import (
    TwoStageOptimizer,
    TwoStageResult,
    _RESULTS_DIR,
    _flat_to_nested,
)
from app.sr.optimization.universe_optimizer import (
    UniverseOptimizationConfig,
    UniverseOptimizationResult,
)
from app.sr.universe.config import AssetSRConfig, UniverseSRConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(
    n: int = 600,
    base_price: float = 100.0,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    closes = [base_price]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + volatility * rng.randn()))
    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0, volatility, n))
    lows = closes * (1 - rng.uniform(0, volatility, n))
    opens = closes * (1 + rng.uniform(-volatility / 2, volatility / 2, n))
    volumes = rng.uniform(100, 1000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_universe_config(assets: list[str]) -> UniverseSRConfig:
    return UniverseSRConfig(
        assets=[AssetSRConfig(symbol=a, timeframes=["1h"]) for a in assets],
        default_timeframes=["1h"],
        global_config={
            "asset_metadata": {"default_profile": "crypto"},
            "sr": {
                "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
                "ensemble": {"method": "weighted_average"},
                "lifecycle": {"age_lambda": 0.002},
                "kernels": {
                    "pivot_hl": {"historical_depth": 500},
                    "round_number": {},
                },
                "regime": {"enabled": False},
            },
        },
    )


def _make_data_map(
    assets: list[str],
    n_bars: int = 600,
) -> dict[str, dict[str, pd.DataFrame]]:
    return {
        asset: {"1h": _make_ohlcv(n=n_bars, seed=42 + i)}
        for i, asset in enumerate(assets)
    }


def _make_stage1_result(
    assets: list[str],
    best_params: dict | None = None,
) -> UniverseOptimizationResult:
    """Construct a mock Stage 1 result."""
    from app.sr.optimization.universe_optimizer import _DEFAULT_PARAM_VALUES

    return UniverseOptimizationResult(
        best_params=best_params or dict(_DEFAULT_PARAM_VALUES),
        best_score=0.72,
        all_trials=[],
        assets=assets,
        metadata={"n_trials": 1, "best_trial": 0},
    )


# ---------------------------------------------------------------------------
# _flat_to_nested helper
# ---------------------------------------------------------------------------


class TestFlatToNested:
    def test_single_level(self):
        assert _flat_to_nested({"a": 1}) == {"a": 1}

    def test_dotted_keys(self):
        result = _flat_to_nested({
            "kernels.order_block.displacement_atr": 1.8,
            "kernels.fair_value_gap.gap_min_atr": 0.6,
        })
        assert result == {
            "kernels": {
                "order_block": {"displacement_atr": 1.8},
                "fair_value_gap": {"gap_min_atr": 0.6},
            },
        }

    def test_empty(self):
        assert _flat_to_nested({}) == {}


# ---------------------------------------------------------------------------
# TwoStageResult
# ---------------------------------------------------------------------------


class TestTwoStageResult:
    def test_save_and_read(self):
        result = TwoStageResult(
            global_params={"ensemble.structural_vs_micro_ratio": 0.55},
            global_score=0.72,
            per_asset_params={
                "BTCUSDT": {"1h": {"kernels.order_block.displacement_atr": 1.8}},
            },
            per_asset_results=[
                AssetOptimizationResult(
                    asset="BTCUSDT", timeframe="1h", accepted=True,
                    best_params={"kernels.order_block.displacement_atr": 1.8},
                    train_score=0.65, val_score=0.60,
                ),
            ],
            metadata={"total_time_seconds": 42.0},
        )
        path = os.path.join(_RESULTS_DIR, "test_two_stage.json")
        try:
            result.save(path)
            with open(path) as f:
                data = json.load(f)
            assert data["global_score"] == pytest.approx(0.72)
            assert "BTCUSDT" in data["per_asset_params"]
            assert data["per_asset_results"][0]["asset"] == "BTCUSDT"
            assert data["per_asset_results"][0]["accepted"] is True
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_save_rejects_outside_results(self):
        result = TwoStageResult()
        with pytest.raises(ValueError, match="Save path must be under"):
            result.save("/tmp/not_allowed.json")

    def test_apply_to_yaml(self):
        result = TwoStageResult(
            global_params={
                "ensemble.structural_vs_micro_ratio": 0.55,
                "lifecycle.age_lambda": 0.0025,
            },
            per_asset_params={
                "ETHUSDT": {
                    "4h": {"kernels.order_block.displacement_atr": 1.9},
                },
            },
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write("sr:\n  pipeline:\n    enabled_kernels: [pivot_hl]\n")
            yaml_path = f.name

        try:
            result.apply_to_yaml(yaml_path, backup=True)
            assert os.path.exists(yaml_path + ".bak")

            import yaml
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)

            # Globals should NOT pollute sr.* — written to per-asset instead
            assert "ensemble" not in cfg.get("sr", {}), (
                "global params should not be written to sr.* when per-asset data exists"
            )
            # Existing config preserved
            assert cfg["sr"]["pipeline"]["enabled_kernels"] == ["pivot_hl"]
            # Stage 1 globals + Stage 2 per-asset merged into assets.{symbol}.{tf}
            eth_4h = cfg["assets"]["ETHUSDT"]["4h"]
            assert eth_4h["ensemble"]["structural_vs_micro_ratio"] == 0.55
            assert eth_4h["lifecycle"]["age_lambda"] == 0.0025
            assert eth_4h["kernels"]["order_block"]["displacement_atr"] == 1.9
        finally:
            if os.path.exists(yaml_path):
                os.remove(yaml_path)
            if os.path.exists(yaml_path + ".bak"):
                os.remove(yaml_path + ".bak")


# ---------------------------------------------------------------------------
# TwoStageOptimizer.emit_config
# ---------------------------------------------------------------------------


class TestEmitConfig:
    def test_global_only(self):
        result = TwoStageResult(
            global_params={
                "ensemble.structural_vs_micro_ratio": 0.55,
                "lifecycle.age_lambda": 0.0025,
            },
        )
        optimizer = TwoStageOptimizer(_make_universe_config(["A"]))
        config = optimizer.emit_config(result)
        assert config["sr"]["ensemble"]["structural_vs_micro_ratio"] == 0.55
        assert "assets" not in config

    def test_per_asset_per_tf(self):
        result = TwoStageResult(
            global_params={"ensemble.structural_vs_micro_ratio": 0.5},
            per_asset_params={
                "BTCUSDT": {
                    "1h": {"kernels.order_block.displacement_atr": 1.8},
                    "4h": {"kernels.order_block.displacement_atr": 2.0},
                },
            },
        )
        optimizer = TwoStageOptimizer(_make_universe_config(["BTCUSDT"]))
        config = optimizer.emit_config(result)

        # Different TF params → assets.{symbol}.{tf} structure
        assert config["assets"]["BTCUSDT"]["1h"]["kernels"]["order_block"]["displacement_atr"] == 1.8
        assert config["assets"]["BTCUSDT"]["4h"]["kernels"]["order_block"]["displacement_atr"] == 2.0

    def test_identical_tfs_use_defaults(self):
        """When all TFs have identical params, use defaults.* instead."""
        result = TwoStageResult(
            global_params={},
            per_asset_params={
                "BTCUSDT": {
                    "1h": {"kernels.order_block.displacement_atr": 1.8},
                    "4h": {"kernels.order_block.displacement_atr": 1.8},
                },
            },
        )
        optimizer = TwoStageOptimizer(_make_universe_config(["BTCUSDT"]))
        config = optimizer.emit_config(result)

        assert "defaults" in config["assets"]["BTCUSDT"]
        assert "1h" not in config["assets"]["BTCUSDT"]
        assert "4h" not in config["assets"]["BTCUSDT"]
        assert config["assets"]["BTCUSDT"]["defaults"]["kernels"]["order_block"]["displacement_atr"] == 1.8

    def test_single_tf_uses_direct_key(self):
        """Single TF should use assets.{symbol}.{tf}, not defaults."""
        result = TwoStageResult(
            global_params={},
            per_asset_params={
                "BTCUSDT": {
                    "1h": {"kernels.order_block.displacement_atr": 1.8},
                },
            },
        )
        optimizer = TwoStageOptimizer(_make_universe_config(["BTCUSDT"]))
        config = optimizer.emit_config(result)

        # Single TF → assets.{symbol}.{tf} directly
        assert "1h" in config["assets"]["BTCUSDT"]


# ---------------------------------------------------------------------------
# TwoStageOptimizer.optimize (mocked Stage 1)
# ---------------------------------------------------------------------------


class TestOptimizeOrchestration:
    def test_end_to_end_with_mock_stage1(self):
        """3 assets, mock Stage 1, real Stage 2 — verify both stages run."""
        assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        universe_config = _make_universe_config(assets)
        stage2_config = AssetOptimizationConfig(
            n_trials=2,
            timeout_s=30.0,
            min_bars=100,
            train_bars=50,
            test_bars=30,
            step_bars=30,
            purge_bars=5,
        )
        optimizer = TwoStageOptimizer(
            universe_config,
            stage2_config=stage2_config,
        )
        data_map = _make_data_map(assets, n_bars=200)

        # Mock Stage 1 to avoid full universe run
        mock_s1_result = _make_stage1_result(assets)
        with patch.object(
            optimizer._stage1_optimizer, "optimize",
            return_value=mock_s1_result,
        ):
            result = optimizer.optimize(data_map)

        assert isinstance(result, TwoStageResult)
        assert result.global_score == pytest.approx(0.72)
        assert len(result.per_asset_results) == 3
        for r in result.per_asset_results:
            assert r.asset in assets
            assert r.timeframe == "1h"
            assert len(r.best_params) > 0
        assert len(result.per_asset_params) == 3

    def test_insufficient_data_skips_stage2(self):
        """Asset with <min_bars gets skipped in Stage 2."""
        assets = ["BTCUSDT", "SMALL"]
        universe_config = _make_universe_config(assets)
        stage2_config = AssetOptimizationConfig(
            n_trials=2, timeout_s=30.0,
            min_bars=500,  # SMALL will have only 50 bars
            train_bars=50, test_bars=30, step_bars=30, purge_bars=5,
        )
        optimizer = TwoStageOptimizer(
            universe_config, stage2_config=stage2_config,
        )
        data_map = {
            "BTCUSDT": {"1h": _make_ohlcv(n=600, seed=42)},
            "SMALL": {"1h": _make_ohlcv(n=50, seed=99)},
        }

        mock_s1_result = _make_stage1_result(assets)
        with patch.object(
            optimizer._stage1_optimizer, "optimize",
            return_value=mock_s1_result,
        ):
            result = optimizer.optimize(data_map)

        # Only BTCUSDT should have per-asset results
        assert len(result.per_asset_results) == 1
        assert result.per_asset_results[0].asset == "BTCUSDT"
        assert "SMALL/1h" in result.metadata["stage2_assets_skipped"]

    def test_metadata_tracks_counts(self):
        """Verify metadata has correct counts."""
        assets = ["A", "B"]
        universe_config = _make_universe_config(assets)
        stage2_config = AssetOptimizationConfig(
            n_trials=2, timeout_s=30.0,
            min_bars=100, train_bars=50, test_bars=30,
            step_bars=30, purge_bars=5,
        )
        optimizer = TwoStageOptimizer(
            universe_config, stage2_config=stage2_config,
        )
        data_map = _make_data_map(assets, n_bars=200)

        mock_s1_result = _make_stage1_result(assets)
        with patch.object(
            optimizer._stage1_optimizer, "optimize",
            return_value=mock_s1_result,
        ):
            result = optimizer.optimize(data_map)

        assert result.metadata["stage2_assets_optimized"] == 2
        assert result.metadata["stage2_assets_total"] == 2
        assert isinstance(result.metadata["total_time_seconds"], float)

    def test_emit_config_from_optimize_result(self):
        """Full flow: optimize → emit_config → verify structure."""
        assets = ["BTCUSDT"]
        universe_config = _make_universe_config(assets)
        stage2_config = AssetOptimizationConfig(
            n_trials=2, timeout_s=30.0,
            min_bars=100, train_bars=50, test_bars=30,
            step_bars=30, purge_bars=5,
        )
        optimizer = TwoStageOptimizer(
            universe_config, stage2_config=stage2_config,
        )
        data_map = _make_data_map(assets, n_bars=200)

        mock_s1_result = _make_stage1_result(assets)
        with patch.object(
            optimizer._stage1_optimizer, "optimize",
            return_value=mock_s1_result,
        ):
            result = optimizer.optimize(data_map)

        config = optimizer.emit_config(result)
        # Global params in sr.*
        assert "sr" in config
        # Per-asset in assets.*
        assert "BTCUSDT" in config["assets"]


# ---------------------------------------------------------------------------
# TASK-020: Integration — emit_config → SRConfigResolver round-trip
# ---------------------------------------------------------------------------


class TestEmitConfigResolverRoundTrip:
    def test_per_asset_overrides_take_precedence(self):
        """emit_config → merge into raw_config → resolve() → verify per-asset wins."""
        from app.sr.config_resolver import SRConfigResolver

        assets = ["BTCUSDT", "ETHUSDT"]
        result = TwoStageResult(
            global_params={
                "ensemble.structural_vs_micro_ratio": 0.55,
                "lifecycle.age_lambda": 0.0025,
                "kernels.order_block.displacement_atr": 1.5,
            },
            per_asset_params={
                "BTCUSDT": {
                    "1h": {
                        "kernels.order_block.displacement_atr": 1.9,
                        "kernels.fair_value_gap.gap_min_atr": 0.7,
                    },
                },
                "ETHUSDT": {
                    "1h": {
                        "kernels.order_block.displacement_atr": 2.1,
                    },
                },
            },
        )

        optimizer = TwoStageOptimizer(_make_universe_config(assets))
        emitted = optimizer.emit_config(result)

        # Build raw_config by merging emitted into base
        base_raw = {
            "asset_metadata": {"default_profile": "crypto"},
            "sr": {
                "pipeline": {"enabled_kernels": ["pivot_hl", "order_block", "fair_value_gap"]},
                "ensemble": {"method": "weighted_average"},
                "lifecycle": {"age_lambda": 0.002},
                "kernels": {
                    "order_block": {"displacement_atr": 1.5},
                    "fair_value_gap": {"gap_min_atr": 0.5},
                },
                "regime": {"enabled": False},
            },
        }

        # Merge emitted config into base (simulating YAML load)
        from app.sr.optimization.universe_optimizer import _deep_merge
        merged_raw = _deep_merge(base_raw, emitted)

        resolver = SRConfigResolver()

        # BTCUSDT/1h: per-asset overrides should win
        btc_resolved = resolver.resolve("BTCUSDT", "1h", merged_raw)
        assert btc_resolved.kernels["order_block"]["displacement_atr"] == 1.9
        assert btc_resolved.kernels["fair_value_gap"]["gap_min_atr"] == 0.7
        assert btc_resolved.ensemble.structural_vs_micro_ratio == 0.55

        # ETHUSDT/1h: different per-asset override
        eth_resolved = resolver.resolve("ETHUSDT", "1h", merged_raw)
        assert eth_resolved.kernels["order_block"]["displacement_atr"] == 2.1
        # fair_value_gap not overridden for ETH → falls back to global
        assert eth_resolved.kernels["fair_value_gap"]["gap_min_atr"] == 0.5

    def test_defaults_key_applies_to_all_tfs(self):
        """When emit_config uses defaults.*, resolver should apply to any TF."""
        from app.sr.config_resolver import SRConfigResolver

        result = TwoStageResult(
            global_params={"ensemble.structural_vs_micro_ratio": 0.55},
            per_asset_params={
                "BTCUSDT": {
                    "1h": {"kernels.order_block.displacement_atr": 1.9},
                    "4h": {"kernels.order_block.displacement_atr": 1.9},
                },
            },
        )
        optimizer = TwoStageOptimizer(_make_universe_config(["BTCUSDT"]))
        emitted = optimizer.emit_config(result)

        # Should use defaults.* since both TFs identical
        assert "defaults" in emitted["assets"]["BTCUSDT"]

        base_raw = {
            "asset_metadata": {"default_profile": "crypto"},
            "sr": {
                "pipeline": {"enabled_kernels": ["pivot_hl", "order_block"]},
                "kernels": {"order_block": {"displacement_atr": 1.5}},
                "regime": {"enabled": False},
            },
        }
        from app.sr.optimization.universe_optimizer import _deep_merge
        merged_raw = _deep_merge(base_raw, emitted)

        resolver = SRConfigResolver()

        # defaults.* should apply to both 1h and 4h
        r1h = resolver.resolve("BTCUSDT", "1h", merged_raw)
        r4h = resolver.resolve("BTCUSDT", "4h", merged_raw)
        assert r1h.kernels["order_block"]["displacement_atr"] == 1.9
        assert r4h.kernels["order_block"]["displacement_atr"] == 1.9

    def test_schema_round_trip_from_yaml(self):
        """Stage 2 config fields survive YAML → OptimizationConfig round-trip."""
        from app.sr.config_resolver import SRConfigResolver

        raw_config = {
            "sr": {
                "optimization": {
                    "n_trials": 50,
                    "per_asset_n_trials": 20,
                    "per_asset_timeout_s": 300.0,
                    "per_asset_bound_fraction": 0.30,
                    "per_asset_min_bars": 400,
                    "per_asset_sampler": "cmaes",
                },
            },
        }
        resolver = SRConfigResolver()
        opt_config = resolver.resolve_typed_optimization_config(raw_config)

        assert opt_config.n_trials == 50
        assert opt_config.per_asset_n_trials == 20
        assert opt_config.per_asset_timeout_s == 300.0
        assert opt_config.per_asset_bound_fraction == 0.30
        assert opt_config.per_asset_min_bars == 400
        assert opt_config.per_asset_sampler == "cmaes"
        # Defaults for unset fields
        assert opt_config.per_asset_regularization_weight == 0.05
        assert opt_config.per_asset_validation_drop_threshold == 0.15
