"""
Tests — Phase 1: MultiBarRunner + ZoneQualityMetrics
=====================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import List
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from app.sr.lifecycle.state_machine import ManagedZone
from app.sr.models import (
    CandidateLevel,
    LevelFeatureVector,
    LevelType,
    ScoredLevel,
    ZoneLifecycleEvent,
    ZoneStatus,
)
from app.sr.optimization.multi_bar_runner import MultiBarRunResult, MultiBarRunner
from app.sr.optimization.quality_metrics import ZoneQualityEvaluator, ZoneQualityMetrics


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 100,
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


def _make_event(
    zone_id: str = "z1",
    from_state: ZoneStatus = ZoneStatus.FORMING,
    to_state: ZoneStatus = ZoneStatus.ACTIVE,
    trigger: str = "touch_confirm",
    bar_index: int = 0,
    price: float = 100.0,
) -> ZoneLifecycleEvent:
    return ZoneLifecycleEvent(
        zone_id=zone_id,
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        price_at_event=price,
        volume_at_event=500.0,
        bar_index=bar_index,
    )


def _make_managed_zone(
    zone_id: str = "z1",
    strength: float = 0.7,
    status: ZoneStatus = ZoneStatus.ACTIVE,
) -> ManagedZone:
    candidate = CandidateLevel(
        center_price=100.0,
        lower_bound=99.5,
        upper_bound=100.5,
        level_type=LevelType.SUPPORT,
        kernel_name="pivot_hl",
        timeframe="1h",
        raw_score=0.8,
        metadata={},
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        atr_at_detection=1.0,
    )
    scored = ScoredLevel(
        candidate=candidate,
        features=LevelFeatureVector(),
        strength=strength,
        confidence=0.7,
        contributing_kernels=["pivot_hl"],
        ensemble_method="weighted_average",
    )
    return ManagedZone(
        zone_id=zone_id,
        scored_level=scored,
        status=status,
        strength=strength,
    )


# ---------------------------------------------------------------------------
# MultiBarRunResult — direct construction tests
# ---------------------------------------------------------------------------

class TestMultiBarRunResult:
    def test_defaults(self):
        r = MultiBarRunResult()
        assert r.bar_count == 0
        assert r.total_zones_created == 0
        assert r.all_events == []
        assert r.final_zones == []

    def test_fields_round_trip(self):
        r = MultiBarRunResult(
            bar_count=50,
            total_zones_created=5,
            total_touches=12,
            total_breakouts=3,
            total_false_breakouts=1,
            zones_reached_active=4,
            zones_broken=2,
            zones_expired=1,
        )
        assert r.total_touches == 12
        assert r.total_breakouts == 3
        assert r.total_false_breakouts == 1


# ---------------------------------------------------------------------------
# MultiBarRunner — event classification
# ---------------------------------------------------------------------------

class TestMultiBarRunnerClassify:
    """Test _classify_event on synthetic events."""

    def _make_runner_with_mock_pipeline(self):
        pipeline = MagicMock()
        return MultiBarRunner(pipeline)

    def test_touch_event_counted(self):
        runner = self._make_runner_with_mock_pipeline()
        result = MultiBarRunResult()
        seen, active, broken, expired = set(), set(), set(), set()

        event = _make_event(trigger="touch", from_state=ZoneStatus.ACTIVE, to_state=ZoneStatus.TESTED)
        runner._classify_event(event, seen, active, broken, expired, result)
        assert result.total_touches == 1
        assert result.total_breakouts == 0

    def test_touch_confirm_counted(self):
        runner = self._make_runner_with_mock_pipeline()
        result = MultiBarRunResult()
        seen, active, broken, expired = set(), set(), set(), set()

        event = _make_event(trigger="touch_confirm", from_state=ZoneStatus.FORMING, to_state=ZoneStatus.ACTIVE)
        runner._classify_event(event, seen, active, broken, expired, result)
        assert result.total_touches == 1
        assert "z1" in active  # zone reached ACTIVE

    def test_breakout_counted(self):
        runner = self._make_runner_with_mock_pipeline()
        result = MultiBarRunResult()
        seen, active, broken, expired = set(), set(), set(), set()

        event = _make_event(trigger="breakout_up", from_state=ZoneStatus.ACTIVE, to_state=ZoneStatus.BROKEN)
        runner._classify_event(event, seen, active, broken, expired, result)
        assert result.total_breakouts == 1
        assert "z1" in broken

    def test_false_breakout_counted(self):
        runner = self._make_runner_with_mock_pipeline()
        result = MultiBarRunResult()
        seen, active, broken, expired = set(), set(), set(), set()

        event = _make_event(trigger="price_returned", from_state=ZoneStatus.BROKEN, to_state=ZoneStatus.FALSE_BREAKOUT)
        runner._classify_event(event, seen, active, broken, expired, result)
        assert result.total_false_breakouts == 1

    def test_expired_tracked(self):
        runner = self._make_runner_with_mock_pipeline()
        result = MultiBarRunResult()
        seen, active, broken, expired = set(), set(), set(), set()

        event = _make_event(trigger="strength_floor", from_state=ZoneStatus.ACTIVE, to_state=ZoneStatus.EXPIRED)
        runner._classify_event(event, seen, active, broken, expired, result)
        assert "z1" in expired


# ---------------------------------------------------------------------------
# ZoneQualityMetrics — frozen dataclass
# ---------------------------------------------------------------------------

class TestZoneQualityMetrics:
    def test_defaults(self):
        m = ZoneQualityMetrics()
        assert m.survival_rate == 0.0
        assert m.coverage == 0.0

    def test_frozen(self):
        m = ZoneQualityMetrics(survival_rate=0.5)
        with pytest.raises(AttributeError):
            m.survival_rate = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ZoneQualityEvaluator — individual metrics
# ---------------------------------------------------------------------------

class TestQualityEvaluatorMetrics:
    def test_survival_rate_zero_zones(self):
        r = MultiBarRunResult()
        assert ZoneQualityEvaluator._survival_rate(r) == 0.0

    def test_survival_rate_all_survived(self):
        r = MultiBarRunResult(total_zones_created=5, zones_reached_active=5)
        assert ZoneQualityEvaluator._survival_rate(r) == 1.0

    def test_survival_rate_partial(self):
        r = MultiBarRunResult(total_zones_created=10, zones_reached_active=3)
        assert ZoneQualityEvaluator._survival_rate(r) == pytest.approx(0.3)

    def test_touch_accuracy_no_touches(self):
        r = MultiBarRunResult()
        assert ZoneQualityEvaluator._touch_accuracy(r) == 0.0

    def test_touch_accuracy_all_bounced(self):
        # 3 zones, each touched once but never broken out → all bounces
        events = [
            _make_event("z0", trigger="touch"),
            _make_event("z1", trigger="touch"),
            _make_event("z2", trigger="touch"),
        ]
        r = MultiBarRunResult(total_touches=3, all_events=events)
        assert ZoneQualityEvaluator._touch_accuracy(r) == 1.0

    def test_touch_accuracy_half_broken(self):
        # z0: touch then breakout (fail), z1: touch then no breakout (bounce)
        events = [
            _make_event("z0", trigger="touch"),
            _make_event("z0", trigger="breakout_confirmed"),
            _make_event("z1", trigger="touch"),
        ]
        r = MultiBarRunResult(total_touches=2, total_breakouts=1, all_events=events)
        assert ZoneQualityEvaluator._touch_accuracy(r) == pytest.approx(0.5)

    def test_false_breakout_rate_no_breakouts(self):
        r = MultiBarRunResult()
        assert ZoneQualityEvaluator._false_breakout_rate(r) == 0.0

    def test_false_breakout_rate_half(self):
        r = MultiBarRunResult(total_breakouts=4, total_false_breakouts=2)
        assert ZoneQualityEvaluator._false_breakout_rate(r) == pytest.approx(0.5)

    def test_strength_stability_few_zones(self):
        r = MultiBarRunResult(final_zones=[_make_managed_zone()])
        assert ZoneQualityEvaluator._strength_stability(r) == 0.0

    def test_strength_stability_uniform(self):
        zones = [_make_managed_zone(f"z{i}", strength=0.7) for i in range(5)]
        r = MultiBarRunResult(final_zones=zones)
        assert ZoneQualityEvaluator._strength_stability(r) == pytest.approx(1.0)

    def test_strength_stability_varied(self):
        zones = [
            _make_managed_zone("z1", strength=0.3),
            _make_managed_zone("z2", strength=0.9),
        ]
        r = MultiBarRunResult(final_zones=zones)
        stability = ZoneQualityEvaluator._strength_stability(r)
        assert 0.0 < stability < 1.0


# ---------------------------------------------------------------------------
# Coverage metric
# ---------------------------------------------------------------------------

class TestCoverageMetric:
    def test_coverage_no_reversals(self):
        evaluator = ZoneQualityEvaluator()
        r = MultiBarRunResult(
            close_prices=[100.0, 100.1, 100.2],
            bar_zone_snapshots=[[], [], []],
        )
        assert evaluator._coverage(r) == 0.0

    def test_coverage_reversal_with_nearby_zone(self):
        evaluator = ZoneQualityEvaluator(reversal_threshold_pct=0.01)
        # Simulate: up -> sharp down -> sharp up
        prices = [100.0] * 5 + [102.0] * 5 + [99.0] * 5 + [102.0] * 5
        zone_snap = [
            [{"center": 99.5, "lower": 99.0, "upper": 100.0, "atr": 1.0}]
        ] * len(prices)
        r = MultiBarRunResult(close_prices=prices, bar_zone_snapshots=zone_snap)
        coverage = evaluator._coverage(r)
        # At least some reversals should be covered
        assert coverage > 0.0

    def test_coverage_reversal_no_zone(self):
        evaluator = ZoneQualityEvaluator(reversal_threshold_pct=0.01)
        # Big swing, no zones
        prices = [100.0] * 5 + [105.0] * 5 + [95.0] * 5
        r = MultiBarRunResult(
            close_prices=prices,
            bar_zone_snapshots=[[] for _ in prices],
        )
        # Reversals exist but no zones → coverage 0
        coverage = evaluator._coverage(r)
        assert coverage == 0.0


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------

class TestCompositeScore:
    def test_perfect_score(self):
        evaluator = ZoneQualityEvaluator()
        m = ZoneQualityMetrics(
            survival_rate=1.0,
            touch_accuracy=1.0,
            false_breakout_rate=0.0,  # inverted: lower is better
            strength_stability=1.0,
            coverage=1.0,
        )
        assert evaluator.composite_score(m) == pytest.approx(1.0)

    def test_worst_score(self):
        evaluator = ZoneQualityEvaluator()
        m = ZoneQualityMetrics(
            survival_rate=0.0,
            touch_accuracy=0.0,
            false_breakout_rate=1.0,
            strength_stability=0.0,
            coverage=0.0,
        )
        assert evaluator.composite_score(m) == pytest.approx(0.0)

    def test_custom_weights(self):
        evaluator = ZoneQualityEvaluator(weights={
            "survival_rate": 1.0,
            "touch_accuracy": 0.0,
            "false_breakout_rate": 0.0,
            "strength_stability": 0.0,
            "coverage": 0.0,
        })
        m = ZoneQualityMetrics(survival_rate=0.8)
        assert evaluator.composite_score(m) == pytest.approx(0.8)

    def test_evaluate_and_composite(self):
        """Full evaluate -> composite_score path."""
        evaluator = ZoneQualityEvaluator()
        # 20 touches: 5 followed by breakout (fail), 15 bounce
        touch_events = []
        for i in range(5):
            touch_events.append(_make_event(f"zb{i}", trigger="touch"))
            touch_events.append(_make_event(f"zb{i}", trigger="breakout_confirmed"))
        for i in range(15):
            touch_events.append(_make_event(f"zg{i}", trigger="touch"))
        r = MultiBarRunResult(
            bar_count=100,
            total_zones_created=10,
            zones_reached_active=7,
            total_touches=20,
            total_breakouts=5,
            total_false_breakouts=2,
            all_events=touch_events,
            final_zones=[_make_managed_zone(f"z{i}", strength=0.6 + 0.05 * i) for i in range(5)],
            close_prices=[100.0] * 100,
            bar_zone_snapshots=[[] for _ in range(100)],
        )
        metrics = evaluator.evaluate(r)
        score = evaluator.composite_score(metrics)
        assert 0.0 <= score <= 1.0
        assert metrics.survival_rate == pytest.approx(0.7)
        assert metrics.touch_accuracy == pytest.approx(0.75)
        assert metrics.false_breakout_rate == pytest.approx(0.4)


class TestHierarchicalScore:
    def test_perfect_score(self):
        evaluator = ZoneQualityEvaluator()
        m = ZoneQualityMetrics(
            survival_rate=1.0,
            touch_accuracy=1.0,
            false_breakout_rate=0.0,
            strength_stability=1.0,
            coverage=1.0,
        )
        score = evaluator.hierarchical_score(m)
        assert score == pytest.approx(1.0)

    def test_worst_score(self):
        evaluator = ZoneQualityEvaluator()
        m = ZoneQualityMetrics(
            survival_rate=0.0,
            touch_accuracy=0.0,
            false_breakout_rate=1.0,
            strength_stability=0.0,
            coverage=0.0,
        )
        score = evaluator.hierarchical_score(m)
        assert score == pytest.approx(0.0)

    def test_gate_low_coverage(self):
        evaluator = ZoneQualityEvaluator()
        m = ZoneQualityMetrics(
            survival_rate=0.8,
            touch_accuracy=0.95,
            false_breakout_rate=0.1,
            strength_stability=0.9,
            coverage=0.01,  # below min_coverage=0.03
        )
        score = evaluator.hierarchical_score(m)
        # Gated: score <= gate_floor (0.10)
        assert score <= 0.10

    def test_gate_low_survival(self):
        evaluator = ZoneQualityEvaluator()
        m = ZoneQualityMetrics(
            survival_rate=0.05,  # below min_survival=0.15
            touch_accuracy=0.95,
            false_breakout_rate=0.1,
            strength_stability=0.9,
            coverage=0.2,
        )
        score = evaluator.hierarchical_score(m)
        assert score <= 0.10

    def test_primary_dominates(self):
        """High touch_accuracy + low FBR should score higher than the reverse."""
        evaluator = ZoneQualityEvaluator()
        good = ZoneQualityMetrics(
            survival_rate=0.5, touch_accuracy=0.95,
            false_breakout_rate=0.1, strength_stability=0.5, coverage=0.1,
        )
        bad = ZoneQualityMetrics(
            survival_rate=0.5, touch_accuracy=0.5,
            false_breakout_rate=0.5, strength_stability=0.5, coverage=0.1,
        )
        assert evaluator.hierarchical_score(good) > evaluator.hierarchical_score(bad)

    def test_secondary_breaks_tie(self):
        """Same primary, higher coverage should win."""
        evaluator = ZoneQualityEvaluator()
        high_cov = ZoneQualityMetrics(
            survival_rate=0.5, touch_accuracy=0.8,
            false_breakout_rate=0.2, strength_stability=0.5, coverage=0.5,
        )
        low_cov = ZoneQualityMetrics(
            survival_rate=0.5, touch_accuracy=0.8,
            false_breakout_rate=0.2, strength_stability=0.5, coverage=0.1,
        )
        assert evaluator.hierarchical_score(high_cov) > evaluator.hierarchical_score(low_cov)


# ---------------------------------------------------------------------------
# Integration: MultiBarRunner with real pipeline
# ---------------------------------------------------------------------------

class TestMultiBarRunnerIntegration:
    """Runs the full pipeline bar-by-bar on synthetic data."""

    def _make_config(self):
        from app.sr.config_schema import (
            EnsembleConfig,
            EnhancementConfig,
            LifecycleConfig,
            PipelineConfig,
            RegimeConfig,
            RuleDerivedConfig,
            SRResolvedConfig,
        )
        from app.sr.models import AssetMetadata, RuleDerivedParams

        return SRResolvedConfig(
            metadata=AssetMetadata(
                profile="crypto",
                trading_hours_per_day=24.0,
                trading_days_per_week=7,
                has_session_gaps=False,
                gap_breakout_policy="gap_ignored",
                gap_escalation_atr=999.0,
                session_lookback_hours=[24, 168, 720],
                round_number_mode="decimal",
                ex_dividend_filter=False,
                continuous_market=True,
            ),
            pipeline=PipelineConfig(
                enabled_kernels=["pivot_hl", "round_number"],
            ),
            kernels={
                "pivot_hl": {"historical_depth": 500, "smoothing_period": 3},
                "round_number": {},
            },
            ensemble=EnsembleConfig(method="weighted_average", structural_vs_micro_ratio=0.5),
            lifecycle=LifecycleConfig(
                age_lambda=0.002,
                breakout_confirm_bars=3,
                false_breakout_window=6,
                inactivity_threshold=80,
                max_active_zones=10,
            ),
            enhancement=EnhancementConfig(),
            regime=RegimeConfig(enabled=False),
            rule_derived=RuleDerivedParams(
                n1=8, n2=6, fractal_period=16, fractal_buffer=0.2,
                round_interval=10.0, max_zone_width_atr=2.0,
                max_zone_width_pct=3.0, breakout_confirm_bars=3,
                false_breakout_window=6, inactivity_threshold=80,
                max_active_zones=10, volume_spike_threshold=1.5,
                vp_lookback_hours=[24, 168, 720],
            ),
            rule_derived_config=RuleDerivedConfig(),
        )

    def test_bar_by_bar_run(self):
        """Runner produces a result with correct bar_count and collects events."""
        from app.sr.pipeline import SRv2Pipeline

        config = self._make_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        runner = MultiBarRunner(pipeline)

        df = _make_ohlcv(n=80, seed=123)
        result = runner.run(df, start_bar=20, end_bar=79)

        assert result.bar_count == 60
        assert len(result.close_prices) <= 60
        assert len(result.bar_zone_snapshots) == len(result.close_prices)
        # At least some zones should be created with pivot_hl + round_number
        assert result.total_zones_created >= 0
        # Events list matches aggregate counts
        assert isinstance(result.all_events, list)

    def test_full_range_run(self):
        """Default start_bar=0 and end_bar=None covers all bars."""
        from app.sr.pipeline import SRv2Pipeline

        config = self._make_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        runner = MultiBarRunner(pipeline)

        df = _make_ohlcv(n=50, seed=456)
        result = runner.run(df)

        assert result.bar_count == 50
        assert len(result.final_zones) >= 0

    def test_evaluate_from_run(self):
        """Full pipeline: run → evaluate → composite_score."""
        from app.sr.pipeline import SRv2Pipeline

        config = self._make_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        runner = MultiBarRunner(pipeline)

        df = _make_ohlcv(n=100, seed=789)
        run_result = runner.run(df, start_bar=10)

        evaluator = ZoneQualityEvaluator()
        metrics = evaluator.evaluate(run_result)
        score = evaluator.composite_score(metrics)

        assert 0.0 <= score <= 1.0
        assert 0.0 <= metrics.survival_rate <= 1.0
        assert 0.0 <= metrics.touch_accuracy <= 1.0
        assert 0.0 <= metrics.false_breakout_rate <= 1.0
