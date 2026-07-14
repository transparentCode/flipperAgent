from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig, TrendlineFamilyConfig
from libs.models.trendline_family.optimization.contracts import (
    MetricRecord,
    OptimizationStage,
    StageEvaluationSpec,
    TrialConfig,
    WindowResult,
)
from libs.models.trendline_family.optimization.folds import ImmutableHistoricalFrame


def market_frame(*, rows: int = 72, start: datetime | None = None) -> pd.DataFrame:
    initial = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    index = pd.DatetimeIndex([initial + timedelta(hours=index) for index in range(rows)])
    close = [100.0 + index * 0.1 + (0.4 if index % 7 == 0 else 0.0) for index in range(rows)]
    return pd.DataFrame(
        {
            "open": [value - 0.1 for value in close],
            "high": [value + 0.5 for value in close],
            "low": [value - 0.5 for value in close],
            "close": close,
            "volume": [10.0 + index for index in range(rows)],
            "complete": True,
            "event_label": [index % 5 == 0 for index in range(rows)],
        },
        index=index,
    )


def dataset(*, rows: int = 72) -> ImmutableHistoricalFrame:
    return ImmutableHistoricalFrame(asset="BTCUSDT", timeframe="1h", _frame=market_frame(rows=rows))


def resolved_config() -> ResolvedTrendlineFamilyConfig:
    config = TrendlineFamilyConfig()
    return ResolvedTrendlineFamilyConfig.create(
        asset="BTCUSDT",
        timeframe="1h",
        config_version="test-v1",
        config=config,
        field_provenance={},
    )


def fixture_evaluation_spec(name: str = "fixture") -> StageEvaluationSpec:
    return StageEvaluationSpec(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        spec_type="synthetic_fixture_evaluator",
        semantic_inputs={"fixture_name": name, "fixture_version": "v1"},
    )


def window_result(
    trial: TrialConfig,
    window: Any,
    kind: str,
    *,
    metric_value: float,
    stage_fingerprint: str,
    forbidden_fingerprint: str,
) -> WindowResult:
    return WindowResult(
        trial_id=trial.trial_id,
        fold_id=window.fold_id if kind == "validation" else window.holdout_plan_id,
        window_kind=kind,
        metrics=(
            MetricRecord(
                "candidate_coverage_ratio",
                value=metric_value,
                sample_count=10,
                valid_row_count=10,
            ),
        ),
        evaluated_bar_count=10,
        diagnostics={
            "stage_output_fingerprint": stage_fingerprint,
            "forbidden_output_fingerprint": forbidden_fingerprint,
        },
    )
