from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.trendlines import (
    ExtractorCapabilities,
    PivotFinality,
    PivotSet,
    TrendlineExecutionMode,
    TrendlineFitResult,
    UnsupportedIdentityValueError,
    run_trendline_pipeline,
)
from libs.models.trendlines.fitting.pathfinding import PathfindingFitter
from libs.models.trendlines.pivots.fractal import FractalPivotExtractor
from libs.models.trendlines.contracts.identity import (
    canonical_json,
    resolve_component_identity_payload,
)


def _frame(rows: int = 48) -> pd.DataFrame:
    index = np.arange(rows, dtype=float)
    close = 100.0 + 0.25 * index + 2.0 * np.sin(index / 3.0)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
        }
    )


class _IdentityExtractor:
    CAPABILITIES = ExtractorCapabilities(
        supported_modes=frozenset({TrendlineExecutionMode.RUNTIME}),
        finality=PivotFinality.CONFIRMED_APPEND_ONLY,
    )

    def __init__(self, pivot_index: int):
        self.pivot_index = pivot_index

    def extract(self, df: pd.DataFrame) -> PivotSet:
        return PivotSet(
            high_indices=np.array([self.pivot_index]),
            high_values=np.array([df["high"].iloc[self.pivot_index]]),
            low_indices=np.array([], dtype=int),
            low_values=np.array([], dtype=float),
        )

    def trendline_identity_payload(self) -> dict[str, int]:
        return {"pivot_index": self.pivot_index}


class _UnclassifiedExtractor:
    CAPABILITIES = _IdentityExtractor.CAPABILITIES

    def extract(self, df: pd.DataFrame) -> PivotSet:
        return _IdentityExtractor(1).extract(df)


class _IdentityFitter:
    def __init__(self, marker: str):
        self.marker = marker

    def fit(self, df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult:
        del df, pivots
        return TrendlineFitResult(
            is_valid=True,
            metadata={"marker": self.marker},
        )

    def trendline_identity_payload(self) -> dict[str, str]:
        return {"marker": self.marker}


class _UnclassifiedFitter:
    def fit(self, df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult:
        del df, pivots
        return TrendlineFitResult(is_valid=True)


def _ids(result: TrendlineFitResult) -> tuple[str, str]:
    assert result.checkpoint is not None
    return result.checkpoint.config_id, result.checkpoint.checkpoint_id


def test_unsupported_arbitrary_objects_fail_canonicalisation() -> None:
    with pytest.raises(UnsupportedIdentityValueError, match="builtins.object"):
        canonical_json(object())


def test_canonical_identity_output_never_contains_memory_addresses() -> None:
    extractor = _IdentityExtractor(4)
    payload = resolve_component_identity_payload(extractor, role="extractor")
    serialized = canonical_json(payload)
    assert "0x" not in serialized
    assert "object at" not in serialized


def test_registered_named_component_identity_remains_stable() -> None:
    first = run_trendline_pipeline(
        _frame(),
        extractor="fractal",
        fitter="pathfinding",
        extractor_kwargs={"window_left": 2, "window_right": 2},
        fitter_kwargs={"pivot_window": 2},
    )
    second = run_trendline_pipeline(
        _frame(),
        extractor="fractal",
        fitter="pathfinding",
        extractor_kwargs={"window_left": 2, "window_right": 2},
        fitter_kwargs={"pivot_window": 2},
    )
    assert _ids(first) == _ids(second)


def test_identical_direct_builtin_instances_produce_stable_ids() -> None:
    first = run_trendline_pipeline(
        _frame(),
        extractor=FractalPivotExtractor(window_left=2, window_right=2),
        fitter=PathfindingFitter(
            pivot_window=2,
            pivot_extractor=FractalPivotExtractor(window_left=2, window_right=2),
        ),
    )
    second = run_trendline_pipeline(
        _frame(),
        extractor=FractalPivotExtractor(window_left=2, window_right=2),
        fitter=PathfindingFitter(
            pivot_window=2,
            pivot_extractor=FractalPivotExtractor(window_left=2, window_right=2),
        ),
    )
    assert _ids(first) == _ids(second)


def test_changing_direct_builtin_component_field_changes_ids() -> None:
    first = run_trendline_pipeline(
        _frame(),
        extractor=FractalPivotExtractor(window_left=2, window_right=2),
        fitter=PathfindingFitter(pivot_window=2),
    )
    second = run_trendline_pipeline(
        _frame(),
        extractor=FractalPivotExtractor(window_left=3, window_right=2),
        fitter=PathfindingFitter(pivot_window=2),
    )
    assert _ids(first)[0] != _ids(second)[0]
    assert _ids(first)[1] != _ids(second)[1]

    changed_fitter = run_trendline_pipeline(
        _frame(),
        extractor=FractalPivotExtractor(window_left=2, window_right=2),
        fitter=PathfindingFitter(pivot_window=3),
    )
    assert _ids(first)[0] != _ids(changed_fitter)[0]
    assert _ids(first)[1] != _ids(changed_fitter)[1]


def test_custom_extractor_without_identity_provider_is_rejected() -> None:
    with pytest.raises(UnsupportedIdentityValueError, match="identity_payload"):
        run_trendline_pipeline(
            _frame(),
            extractor=_UnclassifiedExtractor(),
            fitter="least_squares",
        )


def test_different_custom_extractor_payloads_change_ids() -> None:
    first = run_trendline_pipeline(
        _frame(),
        extractor=_IdentityExtractor(2),
        fitter="least_squares",
    )
    second = run_trendline_pipeline(
        _frame(),
        extractor=_IdentityExtractor(3),
        fitter="least_squares",
    )
    assert _ids(first)[0] != _ids(second)[0]
    assert _ids(first)[1] != _ids(second)[1]


def test_custom_fitter_without_identity_provider_is_rejected() -> None:
    with pytest.raises(UnsupportedIdentityValueError, match="identity_payload"):
        run_trendline_pipeline(
            _frame(),
            extractor=_IdentityExtractor(2),
            fitter=_UnclassifiedFitter(),
        )


def test_different_custom_fitter_payloads_change_ids() -> None:
    first = run_trendline_pipeline(
        _frame(),
        extractor=_IdentityExtractor(2),
        fitter=_IdentityFitter("first"),
    )
    second = run_trendline_pipeline(
        _frame(),
        extractor=_IdentityExtractor(2),
        fitter=_IdentityFitter("second"),
    )
    assert _ids(first)[0] != _ids(second)[0]
    assert _ids(first)[1] != _ids(second)[1]


def test_identical_custom_payloads_produce_stable_ids() -> None:
    first = run_trendline_pipeline(
        _frame(),
        extractor=_IdentityExtractor(2),
        fitter=_IdentityFitter("same"),
    )
    second = run_trendline_pipeline(
        _frame(),
        extractor=_IdentityExtractor(2),
        fitter=_IdentityFitter("same"),
    )
    assert _ids(first) == _ids(second)
