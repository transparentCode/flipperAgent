from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from libs.models.trendline_family.contracts import ContractValidationError, LineGeometry
from libs.models.trendline_family.fitting import (
    FittedPath,
    PathfindingFitResult,
    PathfindingFitStatus,
    PathfindingLineFitter,
)
from libs.models.trendline_family.pivots import (
    ConfirmedPivot,
    PivotExtractionResult,
    PivotExtractionStatus,
)
from libs.models.trendline_family.provider import (
    CandidateGenerationResult,
    NativeDeterministicLineProvider,
)

from .support import candidate_ohlcv, resolved_config


def _pivot(
    frame: pd.DataFrame,
    *,
    index: int,
    price: float,
    kind: str = "low",
    pivot_id: str | None = None,
) -> ConfirmedPivot:
    return ConfirmedPivot(
        pivot_id=pivot_id or f"{kind}-{index}",
        index=index,
        timestamp=frame.index[index].to_pydatetime(),
        confirmation_index=index,
        confirmation_time=frame.index[index].to_pydatetime(),
        price=price,
        kind=kind,
    )


def _collinear_support_frame() -> tuple[pd.DataFrame, PivotExtractionResult]:
    index = pd.date_range("2024-01-01", periods=7, freq="h", tz="UTC")
    line = [float(value) for value in range(1, 8)]
    frame = pd.DataFrame(
        {"open": line, "high": [value + 1.0 for value in line], "low": line, "close": line},
        index=index,
    )
    pivots = tuple(_pivot(frame, index=value, price=line[value]) for value in (0, 3, 6))
    return frame, PivotExtractionResult(
        status="valid",
        pivots=pivots,
        input_bars=len(frame),
        confirmed_bars=len(frame),
    )


def test_timestamp_space_validation_rejects_irregular_bar_crossing() -> None:
    index = pd.DatetimeIndex(
        [
            datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 9, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 10, tzinfo=timezone.utc),
        ]
    )
    frame = pd.DataFrame(
        {
            "open": [0.0, 7.0, 10.0],
            "high": [1.0, 9.0, 11.0],
            "low": [0.0, 0.0, 10.0],
            "close": [0.0, 8.0, 10.0],
        },
        index=index,
    )
    pivots = PivotExtractionResult(
        status="valid",
        pivots=(_pivot(frame, index=0, price=0.0), _pivot(frame, index=2, price=10.0)),
        input_bars=3,
        confirmed_bars=3,
    )

    result = PathfindingLineFitter().fit(frame, pivots, config=resolved_config())

    assert result.status is PathfindingFitStatus.NO_VALID_FITTED_PATHS


def test_fitter_rejects_pivot_index_timestamp_misalignment() -> None:
    frame, pivots = _collinear_support_frame()
    misaligned = ConfirmedPivot(
        pivot_id="misaligned",
        index=3,
        timestamp=frame.index[2].to_pydatetime(),
        confirmation_index=3,
        confirmation_time=frame.index[3].to_pydatetime(),
        price=4.0,
        kind="low",
    )
    invalid_pivots = PivotExtractionResult(
        status="valid",
        pivots=(pivots.pivots[0], misaligned, pivots.pivots[2]),
        input_bars=len(frame),
        confirmed_bars=len(frame),
    )

    with pytest.raises(ContractValidationError, match="index/timestamp alignment"):
        PathfindingLineFitter().fit(frame, invalid_pivots, config=resolved_config())


def test_minimum_pivots_means_available_source_pivots_not_final_anchor_count() -> None:
    frame, pivots = _collinear_support_frame()

    result = PathfindingLineFitter().fit(
        frame,
        pivots,
        config=resolved_config(min_pivots_per_side=3),
    )

    assert result.status is PathfindingFitStatus.VALID
    line = result.lines[0]
    assert len(line.path_pivots) == 3
    assert len(line.anchor_pivots) == 2
    assert [pivot.index for pivot in line.anchor_pivots] == [3, 6]


def test_bent_path_provenance_does_not_overstate_exact_line_diagnostics() -> None:
    index = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [0.0, 0.0, 0.0, 5.0, 10.0],
            "high": [1.0, 1.0, 1.0, 6.0, 11.0],
            "low": [0.0, 0.0, 0.0, 5.0, 10.0],
            "close": [0.0, 0.0, 0.0, 5.0, 10.0],
        },
        index=index,
    )
    first = _pivot(frame, index=0, price=0.0, pivot_id="first")
    second = _pivot(frame, index=2, price=0.0, pivot_id="second")
    third = _pivot(frame, index=4, price=10.0, pivot_id="third")
    pivots = PivotExtractionResult(
        status="valid",
        pivots=(first, second, third),
        input_bars=len(frame),
        confirmed_bars=len(frame),
    )
    fitted = PathfindingLineFitter().fit(frame, pivots, config=resolved_config()).lines[0]

    candidate = NativeDeterministicLineProvider._to_candidate(
        fitted,
        source_line_index=0,
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=frame.index[-1].to_pydatetime(),
        config=resolved_config(),
    )

    assert candidate.geometry.value_at(first.timestamp) == pytest.approx(-10.0)
    assert [pivot.pivot_id for pivot in fitted.path_pivots] == ["first", "second", "third"]
    assert candidate.diagnostics.coverage == pytest.approx(0.5)
    assert candidate.diagnostics.normalized_quality == pytest.approx(0.5)
    assert candidate.diagnostics.touch_count == 2
    assert candidate.diagnostics.effective_touch_count == 2
    assert candidate.diagnostics.inlier_ratio is None
    assert candidate.diagnostics.cut_fraction is None
    assert candidate.diagnostics.fitter_consensus is None
    assert candidate.diagnostics.anchor_stability is None
    assert candidate.metadata["path_length"] == 3
    assert candidate.metadata["quality_method"] == "anchor_span_coverage_v1"


def test_phase_b_result_contracts_coerce_and_freeze_publication_boundaries() -> None:
    frame, pivots = _collinear_support_frame()
    nested = {"nested": {"values": [1]}}
    pivot_result = PivotExtractionResult(
        status="valid",
        pivots=[pivots.pivots[0]],
        input_bars=7,
        confirmed_bars=7,
        metadata=nested,
    )
    nested["nested"]["values"].append(2)
    assert pivot_result.status is PivotExtractionStatus.VALID
    assert isinstance(pivot_result.pivots, tuple)
    assert pivot_result.metadata["nested"]["values"] == (1,)

    geometry = LineGeometry(
        reference_time=pivots.pivots[0].timestamp,
        reference_price=pivots.pivots[0].price,
        slope_per_second=1 / 3600,
    )
    fitted = FittedPath(
        role="SUPPORT",
        geometry=geometry,
        anchor_pivots=[pivots.pivots[0], pivots.pivots[1]],
        path_pivots=[pivots.pivots[0], pivots.pivots[1]],
        coverage=0.5,
        quality=0.5,
        metadata={"nested": {"values": [1]}},
    )
    fit_result = PathfindingFitResult(status="valid", lines=[fitted], metadata={"path": ["a"]})
    assert isinstance(fitted.anchor_pivots, tuple)
    assert isinstance(fit_result.lines, tuple)
    assert fit_result.metadata["path"] == ("a",)

    candidate = NativeDeterministicLineProvider().generate(
        candidate_ohlcv(),
        asset="BTCUSDT",
        timeframe="1h",
        observed_at=candidate_ohlcv().index[-1].to_pydatetime(),
        config=resolved_config(),
    ).candidates[0]
    result_metadata = {"nested": {"values": [1]}}
    result = CandidateGenerationResult(
        status="valid",
        candidates=[candidate],
        reason_codes=[],
        metadata=result_metadata,
    )
    result_metadata["nested"]["values"].append(2)
    assert isinstance(result.candidates, tuple)
    assert result.metadata["nested"]["values"] == (1,)


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (
            lambda: PivotExtractionResult(
                status="valid", pivots=(), input_bars=0, confirmed_bars=0
            ),
            "requires pivots",
        ),
        (
            lambda: PathfindingFitResult(status="bogus", lines=()),
            "invalid pathfinding fit status",
        ),
        (
            lambda: CandidateGenerationResult(
                status="valid", candidates=(), reason_codes=(), metadata={}
            ),
            "requires candidates",
        ),
    ],
)
def test_phase_b_result_contracts_reject_contradictory_or_unknown_states(factory, match: str) -> None:
    with pytest.raises(ContractValidationError, match=match):
        factory()
