from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pandas as pd
import pytest

from libs.models.trendlines.boundary import BoundaryResult, QualityMetrics, Ray
from libs.models.trendlines.contracts.identity import (
    PivotFinality,
    SourceIdentityKind,
    TrendlineCheckpoint,
    TrendlineExecutionMode,
    TrendlineSnapshotStage,
    TrendlineSourceRef,
    build_snapshot_identity,
)
from libs.models.trendlines.signals import (
    AlphaSignal,
    BaseAlphaExtractor,
    FakeoutAlphaExtractor,
    PatternAlphaExtractor,
    StructuralAlphaExtractor,
    TemporalAlphaExtractor,
    TrendlineSignalContext,
    TrendlineSignalInputs,
    TrendlineSignalOrchestrator,
)


def _make_ray(
    *,
    is_support: bool,
    slope: float,
    intercept: float,
    score: float,
    touch_count: int,
    kernel: str = "trendlines:pathfinding",
) -> Ray:
    return Ray(
        start_time=pd.Timestamp("2026-01-01T00:00:00Z"),
        end_time=pd.Timestamp("2026-01-01T01:00:00Z"),
        start_price=intercept,
        end_price=intercept + slope,
        slope=slope,
        intercept=intercept,
        touch_count=touch_count,
        is_support=is_support,
        kernel=kernel,
        score=score,
        r_squared=0.9,
    )


def _make_boundary_result(
    *,
    support_rays: list[Ray],
    resistance_rays: list[Ray],
    interaction: str = "NONE",
    hull_width_atr: float = 2.0,
    hull_floor: float = 99.0,
    hull_ceiling: float = 101.0,
    identity_bearing: bool = False,
) -> BoundaryResult:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = BoundaryResult(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=timestamp,
        active_support_rays=support_rays,
        active_resistance_rays=resistance_rays,
        convex_hull_floor=hull_floor,
        convex_hull_ceiling=hull_ceiling,
        interaction=interaction,
        is_valid=True,
        quality_metrics=QualityMetrics(
            n_support_rays=len(support_rays),
            n_resistance_rays=len(resistance_rays),
            mean_score=0.75,
            mean_touch_count=3.0,
            mean_r_squared=0.9,
            hull_width_atr=hull_width_atr,
        ),
    )
    if identity_bearing:
        source = TrendlineSourceRef(
            source_id="test-source",
            source_start=timestamp.isoformat(),
            as_of=timestamp.isoformat(),
            row_count=1,
            columns=("close",),
            identity_kind=SourceIdentityKind.COMPUTED,
        )
        checkpoint = TrendlineCheckpoint(
            checkpoint_id="test-checkpoint",
            source=source,
            config_id="test-config",
            execution_mode=TrendlineExecutionMode.RUNTIME,
            extractor_finality=PivotFinality.CONFIRMED_APPEND_ONLY,
        )
        result.snapshot_identity = build_snapshot_identity(
            checkpoint=checkpoint,
            stage=TrendlineSnapshotStage.BOUNDARY,
            content_payload={"test": "signals"},
            asset=result.asset,
            timeframe=result.timeframe,
        )
        result.__post_init__()
    return result


    def test_signal_contracts_are_canonical_in_trendlines():
        signal = AlphaSignal(
            name="example",
            direction=0.5,
            confidence=0.8,
            source="structural",
            timeframe="1h",
        )

        assert AlphaSignal.__module__ == "libs.models.trendlines.signals.base"
        assert BaseAlphaExtractor.__module__ == "libs.models.trendlines.signals.base"
        assert StructuralAlphaExtractor.__module__ == "libs.models.trendlines.signals.structural"
        assert TemporalAlphaExtractor.__module__ == "libs.models.trendlines.signals.temporal"
        assert PatternAlphaExtractor.__module__ == "libs.models.trendlines.signals.patterns"
        assert FakeoutAlphaExtractor.__module__ == "libs.models.trendlines.signals.fakeout"
        assert TrendlineSignalOrchestrator.__name__ == "TrendlineSignalOrchestrator"
        assert signal.to_dict()["strength"] == 0.4


    def test_alpha_native_signal_compatibility_modules_are_removed():
        alpha_module = importlib.import_module("app.alpha")
        runtime_module = importlib.import_module("app.alpha._runtime")

        assert not hasattr(alpha_module, "AlphaSignal")
        assert not hasattr(alpha_module, "BaseAlphaExtractor")
        assert not hasattr(runtime_module, "StructuralAlphaExtractor")
        assert not hasattr(runtime_module, "TemporalAlphaExtractor")
        assert not hasattr(runtime_module, "PatternAlphaExtractor")
        assert not hasattr(runtime_module, "FakeoutAlphaExtractor")

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("app.alpha.base")

        for module_name in (
            "app.alpha._runtime.structural",
            "app.alpha._runtime.temporal",
            "app.alpha._runtime.patterns",
            "app.alpha._runtime.fakeout",
            "app.alpha._runtime.constants",
            "app.alpha._runtime.quality",
            "app.alpha._runtime.temporal_utils",
            "app.alpha._runtime.context_utils",
        ):
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module(module_name)


    def test_geometry_alpha_orchestrator_remains_downstream_convenience_wrapper():
        orchestrator = GeometryAlphaOrchestrator()  # noqa: F821

        assert GeometryAlphaOrchestrator.DEFAULT_EXTRACTORS == [  # noqa: F821
            *TrendlineSignalOrchestrator.DEFAULT_EXTRACTORS,
            ConfluenceAlphaExtractor,  # noqa: F821
        ]
        assert orchestrator.extractor_names == [
            "structural",
            "temporal",
            "pattern",
            "fakeout",
            "confluence",
        ]


def test_structural_extractor_emits_interaction_and_squeeze_signals():
    support_a = _make_ray(is_support=True, slope=0.06, intercept=99.0, score=0.9, touch_count=4)
    support_b = _make_ray(is_support=True, slope=0.05, intercept=98.5, score=0.82, touch_count=3)
    resistance = _make_ray(is_support=False, slope=0.01, intercept=101.0, score=0.55, touch_count=2)
    result = _make_boundary_result(
        support_rays=[support_a, support_b],
        resistance_rays=[resistance],
        interaction="STRUCTURAL_BREAKOUT",
        hull_width_atr=1.2,
    )

    signals = StructuralAlphaExtractor().extract(result)
    names = {signal.name for signal in signals}

    assert "interaction_structural_breakout" in names
    assert "hull_squeeze" in names


def test_temporal_extractor_emits_transition_and_convergence_signals():
    support = _make_ray(is_support=True, slope=0.03, intercept=99.0, score=0.9, touch_count=4)
    resistance = _make_ray(is_support=False, slope=0.01, intercept=101.0, score=0.7, touch_count=3)

    history = [
        _make_boundary_result(
            support_rays=[support],
            resistance_rays=[resistance],
            interaction="NONE",
            hull_width_atr=2.6,
        ),
        _make_boundary_result(
            support_rays=[support],
            resistance_rays=[resistance],
            interaction="NONE",
            hull_width_atr=2.1,
        ),
        _make_boundary_result(
            support_rays=[support],
            resistance_rays=[resistance],
            interaction="NONE",
            hull_width_atr=1.7,
        ),
    ]
    current = _make_boundary_result(
        support_rays=[support],
        resistance_rays=[resistance],
        interaction="STRUCTURAL_BREAKOUT",
        hull_width_atr=1.3,
    )

    from libs.models.trendlines.config.state_transitions import build_state_transition_table
    signals = TemporalAlphaExtractor(state_transitions=build_state_transition_table()).extract(current, history=history)
    names = {signal.name for signal in signals}

    assert "transition_none_to_structural_breakout" in names
    assert "hull_convergence" in names


def test_pattern_extractor_detects_ascending_triangle():
    support = _make_ray(is_support=True, slope=0.08, intercept=99.0, score=0.85, touch_count=4)
    resistance = _make_ray(is_support=False, slope=0.0, intercept=101.0, score=0.8, touch_count=4)
    result = _make_boundary_result(
        support_rays=[support],
        resistance_rays=[resistance],
        interaction="NONE",
    )

    signals = PatternAlphaExtractor().extract(result)

    assert len(signals) == 1
    assert signals[0].name == "pattern_ascending_triangle"
    assert signals[0].direction == 1.0


def test_fakeout_extractor_detects_low_volume_breakout_and_retest_confirmation():
    support = _make_ray(is_support=True, slope=0.02, intercept=99.0, score=0.8, touch_count=3)
    resistance = _make_ray(is_support=False, slope=0.01, intercept=101.0, score=0.75, touch_count=3)
    history = [
        _make_boundary_result(
            support_rays=[support],
            resistance_rays=[resistance],
            interaction="STRUCTURAL_BREAKOUT",
        ),
        _make_boundary_result(
            support_rays=[support],
            resistance_rays=[resistance],
            interaction="STRUCTURAL_BREAKOUT",
        ),
        _make_boundary_result(
            support_rays=[support],
            resistance_rays=[resistance],
            interaction="STRUCTURAL_BREAKOUT",
        ),
    ]
    current = _make_boundary_result(
        support_rays=[support],
        resistance_rays=[resistance],
        interaction="STRUCTURAL_BREAKOUT",
    )
    ohlcv = pd.DataFrame(
        {
            "open": [100.0] * 21,
            "high": [100.5] * 21,
            "low": [99.5] * 21,
            "close": [100.2] * 21,
            "volume": [100.0] * 20 + [10.0],
        }
    )

    signals = FakeoutAlphaExtractor().extract(
        current,
        history=history,
        context={
            "ohlcv": ohlcv,
            "atr": 2.0,
            "volume_is_trustworthy": True,
        },
    )
    names = {signal.name for signal in signals}

    assert "low_volume_breakout" in names
    assert "confirmed_breakout" in names


def test_trendline_signal_orchestrator_runs_native_extractors_only():
    support = _make_ray(is_support=True, slope=0.08, intercept=99.0, score=0.9, touch_count=4)
    resistance = _make_ray(is_support=False, slope=0.0, intercept=101.0, score=0.75, touch_count=3)
    current = _make_boundary_result(
        support_rays=[support],
        resistance_rays=[resistance],
        interaction="STRUCTURAL_BREAKOUT",
        hull_width_atr=1.1,
        identity_bearing=True,
    )
    frame = pd.DataFrame(
        {"close": [100.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-01T00:00:00Z")]),
    )
    output = TrendlineSignalOrchestrator().run(
        current,
        signal_inputs=TrendlineSignalInputs(
            context=TrendlineSignalContext.from_close_time_index(
                frame.index,
                volume_is_trustworthy=True,
            )
        ),
        frame=frame,
    )

    assert set(output["by_source"]) == {"structural", "temporal", "pattern", "fakeout"}
    assert "confluence" not in output["by_source"]
    assert output["signal_count"] >= 1
