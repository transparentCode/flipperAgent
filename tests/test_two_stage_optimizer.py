"""Tests for the two-stage automated optimizer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from libs.contracts.optimization import ScreeningSummary, TwoStageResult
from libs.optim_utils.two_stage_optimizer import (
    TwoStageOptimizer,
    _resolve_optimizer_module,
)


# ── Helpers ──────────────────────────────────────────────────────────


@dataclass
class _FakeParamDef:
    default: Any


def _make_schema(*names_defaults: tuple[str, Any]) -> dict[str, _FakeParamDef]:
    return {n: _FakeParamDef(default=d) for n, d in names_defaults}


# ── classify_params tests ────────────────────────────────────────────


class TestClassifyParams:
    def setup_method(self):
        self.opt = TwoStageOptimizer(importance_threshold=0.05)

    def test_splits_by_threshold(self):
        importances = {"a": 0.40, "b": 0.03, "c": 0.01}
        schema = _make_schema(("a", 1), ("b", 2), ("c", 3))
        frozen, active = self.opt._classify_params(importances, schema)
        assert active == ["a"]
        assert frozen == {"b": 2, "c": 3}

    def test_all_important(self):
        importances = {"a": 0.40, "b": 0.30, "c": 0.20}
        schema = _make_schema(("a", 1), ("b", 2), ("c", 3))
        frozen, active = self.opt._classify_params(importances, schema)
        assert frozen == {}
        assert set(active) == {"a", "b", "c"}

    def test_all_frozen_keeps_best(self):
        importances = {"a": 0.04, "b": 0.03, "c": 0.01}
        schema = _make_schema(("a", 1), ("b", 2), ("c", 3))
        frozen, active = self.opt._classify_params(importances, schema)
        assert "a" in active
        assert "a" not in frozen
        assert len(active) == 1

    def test_empty_importances(self):
        schema = _make_schema(("a", 1), ("b", 2), ("c", 3))
        frozen, active = self.opt._classify_params({}, schema)
        assert frozen == {}
        assert set(active) == {"a", "b", "c"}

    def test_param_not_in_fanova_treated_as_active(self):
        importances = {"a": 0.40}  # b and c missing from fANOVA
        schema = _make_schema(("a", 1), ("b", 2), ("c", 3))
        frozen, active = self.opt._classify_params(importances, schema)
        assert set(active) == {"a", "b", "c"}
        assert frozen == {}


# ── OOS gate tests ───────────────────────────────────────────────────


class TestOOSGate:
    def setup_method(self):
        self.opt = TwoStageOptimizer(oos_sharpe_ratio=0.50)

    def _make_oos(self, val_sharpe: float, oos_sharpe: float) -> dict:
        return {
            "train": {"sharpe": 1.0},
            "validate": {"sharpe": val_sharpe},
            "oos": {"sharpe": oos_sharpe},
        }

    def test_rejects_negative_oos(self):
        deployed, reason = self.opt._apply_oos_gate(
            self._make_oos(val_sharpe=2.0, oos_sharpe=-0.5)
        )
        assert deployed is False
        assert "negative" in reason.lower()

    def test_rejects_excessive_degradation(self):
        deployed, reason = self.opt._apply_oos_gate(
            self._make_oos(val_sharpe=2.0, oos_sharpe=0.8)
        )
        assert deployed is False
        assert "degradation" in reason.lower()

    def test_rejects_both_negative(self):
        deployed, reason = self.opt._apply_oos_gate(
            self._make_oos(val_sharpe=-0.5, oos_sharpe=-1.0)
        )
        assert deployed is False
        assert "non-positive" in reason.lower()

    def test_passes_healthy(self):
        deployed, reason = self.opt._apply_oos_gate(
            self._make_oos(val_sharpe=2.0, oos_sharpe=1.5)
        )
        assert deployed is True
        assert reason is None

    def test_passes_edge_case_exactly_50pct(self):
        deployed, reason = self.opt._apply_oos_gate(
            self._make_oos(val_sharpe=2.0, oos_sharpe=1.0)
        )
        assert deployed is True
        assert reason is None

    def test_passes_val_negative_oos_positive(self):
        """Val negative but OOS positive — unusual but not a rejection case."""
        deployed, reason = self.opt._apply_oos_gate(
            self._make_oos(val_sharpe=-0.5, oos_sharpe=1.0)
        )
        assert deployed is True
        assert reason is None


# ── resolve_optimizer_module tests ───────────────────────────────────


class TestResolveOptimizerModule:
    @pytest.mark.parametrize(
        "model_name",
        ["MeanReversion", "Momentum", "SqueezeBreakout", "TrendFollowing"],
    )
    def test_resolves_known_models(self, model_name: str):
        mod = _resolve_optimizer_module(model_name)
        assert hasattr(mod, "make_objective")
        assert hasattr(mod, "evaluate_oos")
        assert hasattr(mod, "post_process_params")
        assert hasattr(mod, "STUDY_DEFAULTS")


# ── TwoStageResult contract tests ───────────────────────────────────


class TestTwoStageResult:
    def test_contains_all_fields(self):
        screening = ScreeningSummary(
            screening_trials=50,
            importance_threshold=0.05,
            importances={"a": 0.5},
            frozen_params={"b": 1},
            active_params=["a"],
            total_params=2,
            reduced_params=1,
        )
        result = TwoStageResult(
            model_name="Test",
            asset="BTCUSDT",
            timeframe="1h",
            best_params={"a": 10},
            deployed=True,
            screening=screening,
            oos_metrics={
                "train": {"sharpe": 1.0},
                "validate": {"sharpe": 2.0},
                "oos": {"sharpe": 1.5},
            },
            default_params={"a": 5, "b": 1},
            stage2_best_score=0.85,
            stage2_n_trials=200,
        )
        assert result.deployed is True
        assert result.rejection_reason is None
        assert result.screening.reduced_params == 1

    def test_json_serializable(self):
        screening = ScreeningSummary(
            screening_trials=10,
            importance_threshold=0.05,
            importances={"x": 0.9},
            frozen_params={},
            active_params=["x"],
            total_params=1,
            reduced_params=1,
        )
        result = TwoStageResult(
            model_name="Test",
            asset="",
            timeframe="1h",
            best_params={"x": 42},
            deployed=False,
            rejection_reason="test rejection",
            screening=screening,
            oos_metrics={"validate": {"sharpe": 1.0}, "oos": {"sharpe": -0.5}},
            default_params={"x": 10},
        )
        dump = result.model_dump()
        assert isinstance(dump, dict)
        assert dump["deployed"] is False

    def test_fallback_to_defaults_on_reject(self):
        """When rejected, best_params should be schema defaults."""
        opt = TwoStageOptimizer(oos_sharpe_ratio=0.50)
        deployed, reason = opt._apply_oos_gate(
            {
                "validate": {"sharpe": 2.0},
                "oos": {"sharpe": -1.0},
            }
        )
        assert deployed is False
        # The run() method sets final_params = default_params on rejection;
        # we verify the gate logic itself returns False here.


# ── Multi-objective support ──────────────────────────────────────────


class TestMultiObjective:
    def test_create_study_multi_objective(self):
        opt = TwoStageOptimizer()
        study_defaults = {"directions": ["maximize", "maximize"]}
        study = opt._create_study(
            "TestModel", "screening", study_defaults, is_multi=True
        )
        assert len(study.directions) == 2

    def test_create_study_single_objective(self):
        opt = TwoStageOptimizer()
        study_defaults = {"direction": "maximize"}
        study = opt._create_study(
            "TestModel", "screening", study_defaults, is_multi=False
        )
        assert len(study.directions) == 1

    def test_partial_fixed_sampler_applied(self):
        opt = TwoStageOptimizer()
        study_defaults = {"direction": "maximize"}
        frozen = {"a": 1, "b": 2}
        study = opt._create_study(
            "TestModel",
            "focused",
            study_defaults,
            is_multi=False,
            fixed_params=frozen,
        )
        assert isinstance(
            study.sampler, __import__("optuna").samplers.PartialFixedSampler
        )
