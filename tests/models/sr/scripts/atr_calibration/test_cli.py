from __future__ import annotations

import pytest


def test_cli_accepts_only_the_three_explicit_commands():
    from libs.models.sr.scripts.atr_calibration.cli import _parser

    parser = _parser()
    for command in ("prepare-source", "select-development", "evaluate-holdout"):
        parsed = parser.parse_args([command, "--config", "configs/sr_trials/taousdt_1d_atr_calibration.yaml"])
        assert parsed.command == command
    with pytest.raises(SystemExit):
        parser.parse_args(["run-all", "--config", "configs/sr_trials/taousdt_1d_atr_calibration.yaml"])
