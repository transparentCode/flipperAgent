"""Focused D5A frozen-source contracts and frame-grid tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest

from libs.models.trendlines.workflows.research.adequacy import (
    ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
    TrendlineRobustnessSourceContractError,
    TrendlineRobustnessSourceMatrixBundle,
    TrendlineRobustnessSourceMemberEvidence,
    build_robustness_source_matrix_bundle,
    frozen_robustness_source_member_specs,
    validate_robustness_source_member_evidence,
    validate_robustness_source_frame,
)


SPECS = frozen_robustness_source_member_specs()


def _frame(spec, *, rows=None):
    rows = spec.expected_row_count if rows is None else rows
    cadence = pd.Timedelta(hours=int(spec.timeframe[:-1]))
    index = pd.date_range(
        spec.event_start,
        periods=rows,
        freq=cadence,
        name="timestamp",
    )
    frame = pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.0] * rows,
            "volume": [1.0] * rows,
            "bar_available_at": index + cadence - pd.Timedelta(milliseconds=1),
        },
        index=index,
    )
    frame.attrs = {
        "bar_timestamp_semantics": "open_time",
        "bar_availability_source": "exchange_close_time",
    }
    return frame


def _evidence(spec, **changes):
    cadence = pd.Timedelta(hours=int(spec.timeframe[:-1]))
    index = pd.date_range(
        spec.event_start,
        periods=spec.expected_row_count,
        freq=cadence,
        name="timestamp",
    )
    values = {
        "member_spec_id": spec.member_spec_id,
        "artifact_id": "a" * 64,
        "artifact_sha256": "b" * 64,
        "source_id": "c" * 64,
        "availability_id": "d" * 64,
        "dataset_id": "e" * 64,
        "research_configuration_id": "f" * 64,
        "preparation_id": "1" * 64,
        "row_count": spec.expected_row_count,
        "first_event_at": index[0].to_pydatetime(),
        "last_event_at": index[-1].to_pydatetime(),
        "first_availability_at": (
            index[0] + cadence - pd.Timedelta(milliseconds=1)
        ).to_pydatetime(),
        "last_availability_at": (
            index[-1] + cadence - pd.Timedelta(milliseconds=1)
        ).to_pydatetime(),
        "provider_calls": spec.provider_call_budget,
        "page_count": 0 if spec.source_kind == "frozen_reference" else 1,
    }
    values.update(changes)
    return TrendlineRobustnessSourceMemberEvidence(**values)


def _valid_bundle():
    evidence = tuple(_evidence(spec) for spec in SPECS)
    return build_robustness_source_matrix_bundle(SPECS, evidence)


def test_member_relation_validation():
    with pytest.raises(ValueError):
        replace(SPECS[1], relation="not-a-relation")


def test_source_kind_validation():
    with pytest.raises(ValueError):
        replace(SPECS[1], source_kind="provider_pages")


def test_bounds_require_utc_and_order():
    with pytest.raises(ValueError):
        replace(SPECS[1], event_start=pd.Timestamp("2025-04-01"))
    with pytest.raises(ValueError):
        replace(
            SPECS[1],
            knowledge_cutoff=SPECS[1].event_start - timedelta(seconds=1),
        )


def test_row_count_requires_positive_non_boolean_integer():
    with pytest.raises(ValueError):
        replace(SPECS[1], expected_row_count=True)
    with pytest.raises(ValueError):
        replace(SPECS[1], expected_row_count=0)


def test_provider_budget_requires_non_boolean_integer():
    with pytest.raises(ValueError):
        replace(SPECS[1], provider_call_budget=True)
    with pytest.raises(ValueError):
        replace(SPECS[1], provider_call_budget=2)


def test_member_spec_identity_is_deterministic():
    assert SPECS[1].member_spec_id == replace(SPECS[1]).member_spec_id
    assert SPECS[1].member_spec_id != SPECS[2].member_spec_id


def test_evidence_requires_lowercase_sha256_identities():
    with pytest.raises(ValueError):
        _evidence(SPECS[1], artifact_sha256="A" * 64)


def test_reference_evidence_requires_zero_calls_and_zero_pages():
    valid = _evidence(SPECS[0])
    assert valid.provider_calls == 0
    assert valid.page_count == 0
    with pytest.raises(ValueError):
        validate_robustness_source_member_evidence(
            SPECS[0],
            _evidence(SPECS[0], provider_calls=1),
        )


def test_provider_evidence_requires_one_call_and_one_page():
    valid = _evidence(SPECS[1])
    assert valid.provider_calls == 1
    assert valid.page_count == 1
    with pytest.raises(ValueError):
        validate_robustness_source_member_evidence(
            SPECS[1],
            _evidence(SPECS[1], page_count=0),
        )


def test_matrix_requires_exact_five_members_and_order():
    bundle = _valid_bundle()
    assert len(bundle.member_specs) == 5
    assert tuple(spec.name for spec in bundle.member_specs) == (
        "reference-btcusdt-1h-20250101-v1",
        "temporal-btcusdt-1h-20250401-v1",
        "cross-asset-ethusdt-1h-20250401-v1",
        "cross-asset-solusdt-1h-20250401-v1",
        "cross-timeframe-btcusdt-4h-20250401-v1",
    )
    with pytest.raises(ValueError):
        build_robustness_source_matrix_bundle(SPECS[:-1], tuple(_evidence(s) for s in SPECS[:-1]))
    with pytest.raises(ValueError):
        TrendlineRobustnessSourceMatrixBundle(
            member_specs=tuple(reversed(SPECS)),
            member_evidence=tuple(reversed(tuple(_evidence(s) for s in SPECS))),
            reference_d2_bundle_id=ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
            reference_d3_bundle_id=ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
            reference_d4a_bundle_id=ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
            reference_d4b_bundle_id=ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
        )


def test_duplicate_member_name_and_asset_window_fail():
    duplicate_name = replace(SPECS[1], name=SPECS[0].name)
    with pytest.raises(ValueError):
        build_robustness_source_matrix_bundle(
            (SPECS[0], duplicate_name, *SPECS[2:]),
            tuple(_evidence(s) for s in (SPECS[0], duplicate_name, *SPECS[2:])),
        )
    duplicate_window = replace(SPECS[2], name=SPECS[2].name, asset="BTCUSDT")
    with pytest.raises(ValueError):
        build_robustness_source_matrix_bundle(
            (SPECS[0], SPECS[1], duplicate_window, SPECS[3], SPECS[4]),
            tuple(
                _evidence(s)
                for s in (SPECS[0], SPECS[1], duplicate_window, SPECS[3], SPECS[4])
            ),
        )


def test_fresh_1h_bounds_are_frozen():
    changed = replace(
        SPECS[1],
        knowledge_cutoff=SPECS[1].knowledge_cutoff - timedelta(hours=1),
    )
    with pytest.raises(ValueError):
        build_robustness_source_matrix_bundle(
            (SPECS[0], changed, SPECS[2], SPECS[3], SPECS[4]),
            tuple(
                _evidence(s)
                for s in (SPECS[0], changed, SPECS[2], SPECS[3], SPECS[4])
            ),
        )


def test_wrong_row_count_and_frame_grid_fail():
    with pytest.raises(TrendlineRobustnessSourceContractError):
        validate_robustness_source_frame(_frame(SPECS[1], rows=311), SPECS[1])
    frame = _frame(SPECS[1])
    frame = frame.drop(frame.index[10])
    frame = frame.iloc[:312]
    with pytest.raises(TrendlineRobustnessSourceContractError):
        validate_robustness_source_frame(frame, SPECS[1])


def test_duplicate_timestamp_is_rejected():
    frame = _frame(SPECS[1])
    frame.index = frame.index.where(frame.index != frame.index[10], frame.index[9])
    with pytest.raises(TrendlineRobustnessSourceContractError):
        validate_robustness_source_frame(frame, SPECS[1])


def test_timestamp_semantics_are_rejected():
    frame = _frame(SPECS[1])
    frame.attrs["bar_timestamp_semantics"] = "close_time"
    with pytest.raises(TrendlineRobustnessSourceContractError):
        validate_robustness_source_frame(frame, SPECS[1])


def test_availability_provenance_is_rejected():
    frame = _frame(SPECS[1])
    frame.attrs["bar_availability_source"] = "close_time_index"
    with pytest.raises(TrendlineRobustnessSourceContractError):
        validate_robustness_source_frame(frame, SPECS[1])


def test_prior_evidence_identity_mismatch_fails():
    with pytest.raises(ValueError):
        TrendlineRobustnessSourceMatrixBundle(
            member_specs=SPECS,
            member_evidence=tuple(_evidence(s) for s in SPECS),
            reference_d2_bundle_id="a" * 64,
            reference_d3_bundle_id=ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
            reference_d4a_bundle_id=ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
            reference_d4b_bundle_id=ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
        )


def test_matrix_identity_changes_when_member_identity_changes():
    first = _valid_bundle()
    changed_evidence = tuple(
        replace(_evidence(spec), artifact_id="9" * 64) if index == 1 else _evidence(spec)
        for index, spec in enumerate(SPECS)
    )
    second = TrendlineRobustnessSourceMatrixBundle(
        member_specs=SPECS,
        member_evidence=changed_evidence,
        reference_d2_bundle_id=ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
        reference_d3_bundle_id=ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
        reference_d4a_bundle_id=ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
        reference_d4b_bundle_id=ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
    )
    assert first.robustness_source_matrix_bundle_id != second.robustness_source_matrix_bundle_id


def test_paths_and_wall_clock_values_are_not_in_canonical_identity():
    payload = _valid_bundle().to_dict()
    text = repr(payload)
    assert "artifact_path" not in text
    assert "created_at" not in text
