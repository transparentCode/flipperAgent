"""Network-free D5A acquisition-script tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendlines.workflows.research.adequacy import (
    frozen_robustness_source_member_specs,
)
from scripts import acquire_trendlines_l2d5a_robustness_sources as d5a_script


SPECS = frozen_robustness_source_member_specs()


def _frame(member, *, rows=None):
    rows = member.expected_row_count if rows is None else rows
    cadence = pd.Timedelta(hours=int(member.timeframe[:-1]))
    index = pd.date_range(
        member.event_start,
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


class FakeLoader:
    def __init__(self, member, frame, *, failure=None, calls_override=None):
        self.member = member
        self.frame = frame
        self.failure = failure
        self.calls_override = calls_override
        self.provider_calls = 0
        self.page_counts = {}

    async def load(self, spec):
        self.provider_calls += 1
        if self.failure is not None:
            raise self.failure
        self.page_counts[spec.timeframes[0]] = 1
        if self.calls_override is not None:
            self.provider_calls = self.calls_override
        return {spec.timeframes[0]: self.frame.copy()}


@pytest.fixture(scope="module")
def successful_acquisition(tmp_path_factory):
    output_root = tmp_path_factory.mktemp("d5a-success") / "matrix"
    seen = []
    loaders = []

    def factory(member):
        loader = FakeLoader(member, _frame(member))
        seen.append(member.name)
        loaders.append(loader)
        return loader

    result = d5a_script.run_acquisition(
        output_root=output_root,
        loader_factory=factory,
    )
    return result, seen, loaders


def test_four_fake_loaders_use_fixed_order(successful_acquisition):
    _, seen, _ = successful_acquisition
    assert seen == [spec.name for spec in SPECS[1:]]


def test_each_fresh_loader_makes_one_call_and_one_page(successful_acquisition):
    _, _, loaders = successful_acquisition
    assert [loader.provider_calls for loader in loaders] == [1, 1, 1, 1]
    assert [loader.page_counts for loader in loaders] == [
        {spec.timeframe: 1} for spec in SPECS[1:]
    ]


def test_successful_manifest_records_source_only_execution(successful_acquisition):
    result, _, _ = successful_acquisition
    manifest = result["manifest"]
    assert manifest["total_provider_calls"] == 4
    assert manifest["provider_retries"] == 0
    assert manifest["model_executions"] == 0
    assert manifest["replay_executions"] == 0
    assert manifest["outcome"] is None


def test_successful_matrix_has_exact_five_members(successful_acquisition):
    result, _, _ = successful_acquisition
    assert len(result["bundle"].member_specs) == 5
    assert len(result["bundle"].member_evidence) == 5
    assert result["bundle"].member_specs[0].provider_call_budget == 0
    assert all(row.provider_calls == 1 for row in result["bundle"].member_evidence[1:])


def test_all_fresh_artifacts_are_exact_312_row_frames(successful_acquisition):
    result, _, _ = successful_acquisition
    root = result["paths"]["root"]
    for member in SPECS[1:]:
        path = root / "members" / member.name / "normalized_ohlcv_v2.json"
        frame = d5a_script.read_research_frame_artifact(
            path,
            expected_asset=member.asset,
            expected_timeframe=member.timeframe,
        )
        assert len(frame) == 312


def test_persisted_round_trip_reproduces_preparation_identities(successful_acquisition):
    result, _, _ = successful_acquisition
    for context in result["fresh_context"]:
        prepared = context["prepared"]
        reloaded = context["reloaded_prepared"]
        assert prepared.dataset.dataset_id == reloaded.dataset.dataset_id
        assert prepared.configuration.research_configuration_id == reloaded.configuration.research_configuration_id
        assert prepared.preparation_id == reloaded.preparation_id


def test_checksums_cover_matrix_and_all_nested_files(successful_acquisition):
    result, _, _ = successful_acquisition
    root = result["paths"]["root"]
    checksums = json.loads((root / "checksums.json").read_text())
    paths = {row["path"] for row in checksums["files"]}
    assert "robustness_source_matrix_bundle.json" in paths
    assert "run_manifest.json" in paths
    assert "review.md" in paths
    assert all(
        f"members/{member.name}/normalized_ohlcv_v2.json" in paths
        for member in SPECS[1:]
    )
    for row in checksums["files"]:
        path = root / row["path"]
        assert path.stat().st_size == row["byte_length"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]


def test_reference_artifact_and_prior_chain_are_bound(successful_acquisition):
    result, _, _ = successful_acquisition
    manifest = result["manifest"]
    assert manifest["reference_artifact_path"].endswith("normalized_ohlcv_v2.json")
    assert manifest["reference_d2_bundle_id"] == d5a_script.ROBUSTNESS_REFERENCE_D2_BUNDLE_ID
    assert manifest["reference_d3_bundle_id"] == d5a_script.ROBUSTNESS_REFERENCE_D3_BUNDLE_ID
    assert manifest["reference_d4a_bundle_id"] == d5a_script.ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID
    assert manifest["reference_d4b_bundle_id"] == d5a_script.ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID


def test_yaml_hash_is_unchanged(successful_acquisition):
    result, _, _ = successful_acquisition
    manifest = result["manifest"]
    assert manifest["yaml_sha256_before"] == manifest["yaml_sha256_after"]
    assert manifest["yaml_sha256_before"] == d5a_script._sha256(d5a_script.YAML_PATH)


def test_failure_stops_before_remaining_members_and_publishes_nothing(tmp_path):
    output_root = tmp_path / "failed"
    seen = []
    loaders = []

    def factory(member):
        seen.append(member.name)
        failure = RuntimeError("synthetic provider failure") if len(seen) == 2 else None
        loader = FakeLoader(member, _frame(member), failure=failure)
        loaders.append(loader)
        return loader

    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        d5a_script.run_acquisition(output_root=output_root, loader_factory=factory)
    assert len(seen) == 2
    assert len(loaders) == 2
    assert loaders[1].provider_calls == 1
    assert not output_root.exists()


def test_provider_accounting_failure_stops_without_retry(tmp_path):
    output_root = tmp_path / "bad-accounting"
    created = []

    def factory(member):
        loader = FakeLoader(member, _frame(member), calls_override=2)
        created.append(loader)
        return loader

    with pytest.raises(RuntimeError, match="provider call count"):
        d5a_script.run_acquisition(output_root=output_root, loader_factory=factory)
    assert len(created) == 1
    assert created[0].provider_calls == 2
    assert not output_root.exists()


def test_missing_interval_is_rejected_before_public_output(tmp_path):
    output_root = tmp_path / "missing-interval"

    def factory(member):
        frame = _frame(member)
        if member.name == SPECS[1].name:
            frame = frame.drop(frame.index[12])
        return FakeLoader(member, frame)

    with pytest.raises(ValueError):
        d5a_script.run_acquisition(output_root=output_root, loader_factory=factory)
    assert not output_root.exists()


def test_duplicate_timestamp_is_rejected_before_public_output(tmp_path):
    output_root = tmp_path / "duplicate-timestamp"

    def factory(member):
        frame = _frame(member)
        if member.name == SPECS[1].name:
            frame.index = frame.index.where(frame.index != frame.index[12], frame.index[11])
        return FakeLoader(member, frame)

    with pytest.raises(ValueError):
        d5a_script.run_acquisition(output_root=output_root, loader_factory=factory)
    assert not output_root.exists()


def test_existing_output_root_is_never_overwritten(tmp_path):
    output_root = tmp_path / "existing"
    output_root.mkdir()
    marker = output_root / "marker"
    marker.write_text("keep")
    called = False

    def factory(member):
        nonlocal called
        called = True
        return FakeLoader(member, _frame(member))

    with pytest.raises(FileExistsError):
        d5a_script.run_acquisition(output_root=output_root, loader_factory=factory)
    assert marker.read_text() == "keep"
    assert not called


def test_script_contains_no_model_or_replay_execution():
    source = Path("scripts/acquire_trendlines_l2d5a_robustness_sources.py").read_text()
    assert "run_causal_replay" not in source
    assert "run_causal_replay(" not in source
    assert "run_causal_replay" not in source


def test_real_provider_is_not_used_by_network_free_fixture(successful_acquisition):
    _, _, loaders = successful_acquisition
    assert all(type(loader) is FakeLoader for loader in loaders)


def test_member_evidence_inventory_contains_all_artifact_paths(successful_acquisition):
    result, _, _ = successful_acquisition
    inventory = result["manifest"]["member_evidence"]
    assert len(inventory) == 5
    assert inventory[0]["artifact_path"].endswith("normalized_ohlcv_v2.json")
    assert all("artifact_path" in row for row in inventory)
