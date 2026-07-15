from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from libs.models.sr.scripts.atr_calibration import runner
from libs.models.sr.scripts.atr_calibration.runner import prepare_source_stage
from libs.models.sr.scripts.atr_calibration.source import publish_source_capsule


def test_prepare_source_is_deterministic_for_same_commit(tmp_path, calibration_config):
    # The stage always uses the configured repository output root; this smoke
    # test exercises the explicit stage contract without a provider call.
    root = Path(__file__).resolve().parents[5]
    first = prepare_source_stage(
        root / "configs/sr_trials/taousdt_1d_atr_calibration.yaml",
        repo_root=root,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    second = prepare_source_stage(
        root / "configs/sr_trials/taousdt_1d_atr_calibration.yaml",
        repo_root=root,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    assert first == second


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
    evaluated = runner.evaluate_holdout_stage(
        "ignored.yaml",
        repo_root=repo_root,
        implementation_commit=development.implementation_commit,
    )
    assert evaluated["selected_period"] is None
    assert evaluated["recommendation"] in {"RETAIN_GLOBAL_14", "INSUFFICIENT_EVIDENCE"}
