from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.atr_calibration import runner
from libs.models.sr.scripts.atr_calibration.runner import prepare_source_stage
from libs.models.sr.scripts.atr_calibration.source import publish_source_capsule


def test_prepare_source_is_deterministic_for_same_commit(tmp_path, monkeypatch, calibration_config):
    # The stage always uses the configured repository output root; this smoke
    # test exercises the explicit stage contract without a provider call.
    root = Path(__file__).resolve().parents[5]
    config = replace(calibration_config, output_root="output")
    real_root_path = runner._root_path
    monkeypatch.setattr(runner, "_load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        runner,
        "_root_path",
        lambda repo_root, relative, *, field_name: (
            tmp_path if field_name == "output_root" else real_root_path(repo_root, relative, field_name=field_name)
        ),
    )
    first = prepare_source_stage(
        "ignored.yaml",
        repo_root=root,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    second = prepare_source_stage(
        "ignored.yaml",
        repo_root=root,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    assert first == second
    assert set(first) == {"development_source_id", "development_path", "development_row_count"}
    assert first["development_row_count"] == 629


def test_prepare_source_cannot_recreate_sealed_capsule(tmp_path, monkeypatch, calibration_config):
    def denied(*args, **kwargs):
        raise AssertionError("retired sealed-source builder was called")

    monkeypatch.setattr(runner.source_module, "build_source_capsules", denied)
    root = Path(__file__).resolve().parents[5]
    config = replace(calibration_config, output_root="output")
    real_root_path = runner._root_path
    monkeypatch.setattr(runner, "_load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        runner,
        "_root_path",
        lambda repo_root, relative, *, field_name: (
            tmp_path if field_name == "output_root" else real_root_path(repo_root, relative, field_name=field_name)
        ),
    )
    result = runner.prepare_source_stage(
        "ignored.yaml",
        repo_root=root,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    assert "sealed_source_id" not in result
    assert "sealed_path" not in result


def test_cli_stage_has_no_override_surface():
    from libs.models.sr.scripts.atr_calibration.cli import _parser

    parser = _parser()
    parsed = parser.parse_args(["prepare-source", "--config", "configs/sr_trials/taousdt_1d_atr_calibration.yaml"])
    assert parsed.command == "prepare-source"


def test_selection_and_no_challenger_path_never_load_sealed_source(
    tmp_path,
    monkeypatch,
    calibration_config,
    resolved_sr_config,
    source_capsules,
):
    development, _ = source_capsules
    config = replace(calibration_config, output_root="output")
    repo_root = tmp_path
    output_root = repo_root / config.output_root
    publish_source_capsule(development, output_root=output_root)

    def denied(*args, **kwargs):
        raise AssertionError("sealed parent source access is forbidden in development/no-challenger stages")

    monkeypatch.setattr(runner.source_module, "load_frozen_source", denied)
    monkeypatch.setattr(runner.source_module, "build_source_capsules", denied)
    monkeypatch.setattr(runner, "_load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(runner, "resolve_frozen_sr_config", lambda *_args, **_kwargs: resolved_sr_config)

    selected = runner.select_development_stage(
        "ignored.yaml",
        repo_root=repo_root,
        implementation_commit=development.implementation_commit,
    )
    assert selected["selected_period"] is None
    with pytest.raises(ContractValidationError):
        runner.evaluate_holdout_stage(
            "ignored.yaml",
            repo_root=repo_root,
            implementation_commit=development.implementation_commit,
        )
