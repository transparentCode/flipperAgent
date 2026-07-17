from __future__ import annotations

import pytest


def test_cli_accepts_only_development_commands():
    from libs.models.sr.scripts.atr_calibration.cli import _parser

    parser = _parser()
    for command in ("prepare-source", "select-development"):
        parsed = parser.parse_args([command, "--config", "configs/sr_trials/taousdt_1d_atr_calibration.yaml"])
        assert parsed.command == command
    for command in ("run-all", "evaluate-holdout"):
        with pytest.raises(SystemExit):
            parser.parse_args([command, "--config", "configs/sr_trials/taousdt_1d_atr_calibration.yaml"])
