from __future__ import annotations

from pathlib import Path

from scripts import run_trendline_v2_viewer as cli
from libs.models.trendline_v2.tools.viewer import runner


def test_help_exposes_csv_binance_serve_and_verify_modes() -> None:
    parser = runner.build_parser()
    help_text = parser.format_help()
    assert "--input-csv" in help_text
    assert "--source" in help_text
    assert "--verify-output" in help_text
    assert "--serve" in help_text
    assert "--port" in help_text
    assert "--end" in help_text
    assert "1000PEPEUSDT" in help_text
    assert "1w" in help_text


def test_end_alias_populates_causal_as_of_boundary(tmp_path: Path) -> None:
    args = runner.build_parser().parse_args(
        [
            "--asset",
            "BNBUSDT",
            "--timeframe",
            "4h",
            "--end",
            "2026-07-25T00:00:00Z",
            "--output",
            str(tmp_path / "output"),
        ]
    )
    assert args.as_of == "2026-07-25T00:00:00Z"


def test_script_entry_point_preserves_runner_main(monkeypatch) -> None:
    monkeypatch.setattr(cli, "main", lambda: 0)
    assert cli.main() == 0


def test_verify_cli_rejects_run_options(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "verify_output", lambda _path: {})
    assert (
        runner.main(
            ["--verify-output", str(tmp_path), "--asset", "ETHUSDT"]
        )
        == 2
    )


def test_verify_cli_rejects_explicit_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "verify_output", lambda _path: {})
    assert (
        runner.main(
            ["--verify-output", str(tmp_path), "--source", "binance"]
        )
        == 2
    )


def test_verify_cli_rejects_explicit_port(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "verify_output", lambda _path: {})
    assert (
        runner.main(
            ["--verify-output", str(tmp_path), "--port", "9999"]
        )
        == 2
    )


def test_cli_rejects_port_without_serve(tmp_path: Path) -> None:
    assert (
        runner.main(
            [
                "--asset",
                "ETHUSDT",
                "--timeframe",
                "1h",
                "--as-of",
                "2026-07-25T00:00:00Z",
                "--output",
                str(tmp_path / "output"),
                "--port",
                "9999",
            ]
        )
        == 2
    )


def test_cli_error_is_nonzero_for_invalid_asset(tmp_path: Path) -> None:
    assert (
        runner.main(
            [
                "--asset",
                "ethusdt",
                "--timeframe",
                "1h",
                "--as-of",
                "2026-07-25T00:00:00Z",
                "--output",
                str(tmp_path / "output"),
                "--input-csv",
                str(tmp_path / "missing.csv"),
            ]
        )
        == 2
    )
