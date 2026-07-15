from __future__ import annotations

import asyncio
from pathlib import Path
import shutil

import pytest

from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.scripts.baseline_trial.artifacts import publish_bundle, validate_bundle
from libs.models.sr.scripts.baseline_trial.runner import run_trial
from libs.models.sr.scripts.baseline_trial.dataset import _timestamp_to_ms

from .test_runner import _FakeAdapter, _trial
from .test_dataset import _frame


def _run_result(output_root: str):
    trial = _trial(output_root)
    result, publication = asyncio.run(
        run_trial(
            trial,
            repo_root=Path(__file__).parents[5],
            adapter=_FakeAdapter(_frame()),
            implementation_commit="c" * 40,
        )
    )
    return result, publication


def test_bundle_has_exact_members_and_rehashes_cleanly() -> None:
    root = Path(__file__).parents[5]
    output_root = "research/tmp_sr_v1_5_artifact_test"
    try:
        result, publication = _run_result(output_root)
        payload = validate_bundle(publication.output_path)
        assert set(path.name for path in publication.output_path.iterdir()) == {
            "manifest.json",
            "source_bars.json",
            "model_bars.json",
            "trace.json",
            "diagnostics.json",
            "chart_payload.json",
        }
        assert payload["bundle_id"] == publication.bundle_id
        assert deterministic_hash(payload["bundle_id_semantic_payload"]) == publication.bundle_id
        assert payload["window_policy"] == "half_open_utc_daily"
        assert payload["provider_request"] == {
            "startTime": _timestamp_to_ms(result.trial.requested_since),
            "endTime": _timestamp_to_ms(result.trial.requested_until) - 1,
        }
        assert all(
            path.read_bytes().endswith(b"\n")
            for path in publication.output_path.iterdir()
        )
    finally:
        shutil.rmtree(root / output_root, ignore_errors=True)


def test_identical_publish_is_byte_identical_and_mismatch_fails_closed() -> None:
    root = Path(__file__).parents[5]
    output_root = "research/tmp_sr_v1_5_artifact_collision_test"
    try:
        result, first = _run_result(output_root)
        before = {
            path.name: path.read_bytes() for path in first.output_path.iterdir()
        }
        second = publish_bundle(
            result,
            repo_root=root,
            implementation_commit="c" * 40,
        )
        after = {path.name: path.read_bytes() for path in second.output_path.iterdir()}
        assert first.bundle_id == second.bundle_id
        assert before == after

        member = first.output_path / "chart_payload.json"
        member.write_bytes(member.read_bytes() + b"tamper")
        with pytest.raises(ValueError, match="collision|mismatch"):
            publish_bundle(
                result,
                repo_root=root,
                implementation_commit="c" * 40,
            )
    finally:
        shutil.rmtree(root / output_root, ignore_errors=True)


def test_bundle_identity_includes_implementation_commit() -> None:
    root = Path(__file__).parents[5]
    result, first = _run_result("research/tmp_sr_v1_5_artifact_identity_a")
    try:
        second_root = "research/tmp_sr_v1_5_artifact_identity_b"
        second_result = result
        second_trial = second_result.trial
        from dataclasses import replace

        second_result = replace(
            second_result,
            trial=replace(second_trial, output_root=second_root),
        )
        second = publish_bundle(
            second_result,
            repo_root=root,
            implementation_commit="d" * 40,
        )
        assert first.bundle_id != second.bundle_id
    finally:
        shutil.rmtree(root / "research/tmp_sr_v1_5_artifact_identity_a", ignore_errors=True)
        shutil.rmtree(root / "research/tmp_sr_v1_5_artifact_identity_b", ignore_errors=True)
