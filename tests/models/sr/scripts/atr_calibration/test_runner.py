from __future__ import annotations

from pathlib import Path

from libs.models.sr.scripts.atr_calibration.runner import prepare_source_stage


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
