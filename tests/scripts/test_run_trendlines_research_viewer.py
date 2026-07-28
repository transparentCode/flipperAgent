from __future__ import annotations

from scripts import run_trendlines_research_viewer as cli
from libs.models.trendlines.research_viewer import runner


def test_script_delegates_to_runner_main(monkeypatch) -> None:
    monkeypatch.setattr(cli, "main", lambda: 0)
    assert cli.main() == 0


def test_help_exposes_required_mature_viewer_options() -> None:
    help_text = runner.build_parser().format_help()
    for option in (
        "--asset",
        "--timeframe",
        "--source",
        "--start",
        "--end",
        "--output",
        "--display-bars",
        "--serve",
        "--port",
        "--verify-output",
    ):
        assert option in help_text
    assert "1w" in help_text


def test_verify_cli_rejects_run_options(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(runner, "verify_output", lambda _path: {})
    assert runner.main(["--verify-output", str(tmp_path), "--asset", "TAOUSDT"]) == 2


def test_port_requires_serve(tmp_path) -> None:
    assert (
        runner.main(
            [
                "--asset",
                "TAOUSDT",
                "--timeframe",
                "4h",
                "--source",
                "binance",
                "--start",
                "2026-01-01T00:00:00Z",
                "--end",
                "2026-03-01T00:00:00Z",
                "--output",
                str(tmp_path / "viewer"),
                "--port",
                "8766",
            ]
        )
        == 2
    )


def test_script_has_no_model_or_provider_execution_logic() -> None:
    source = __import__("pathlib").Path(cli.__file__).read_text(encoding="utf-8")
    assert "BinanceNativeAdapter" not in source
    assert "run_causal_replay" not in source
    assert "fit_trendlines" not in source
