from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd
import pytest

from libs.models.trendlines.research_viewer import runner
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
    generate_synthetic_frames,
)


UTC = timezone.utc
BASE_START = datetime(2026, 1, 1, tzinfo=UTC)


def _frame(*, timeframe: str = "1h", count: int = 48) -> pd.DataFrame:
    spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.SYNTHETIC,
            seed=17,
            start_time=BASE_START,
            bar_counts={timeframe: count},
        ),
        asset="BTCUSDT",
        timeframes=(timeframe,),
        primary_timeframe=timeframe,
    )
    frame = generate_synthetic_frames(spec)[timeframe]
    frame.attrs["bar_availability_source"] = "exchange_close_time"
    return frame


class FakeLoader:
    def __init__(self, frame: pd.DataFrame, calls: list[TrendlineResearchSpec]) -> None:
        self.frame = frame
        self.calls = calls
        self.provider_calls = 0
        self.page_counts: dict[str, int] = {}

    async def load(self, spec: TrendlineResearchSpec) -> dict[str, pd.DataFrame]:
        self.calls.append(spec)
        self.provider_calls = 1
        self.page_counts[spec.primary_timeframe] = 1
        return {spec.primary_timeframe: self.frame.copy(deep=True)}


def _run_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    asset: str = "TAOUSDT",
    output_name: str = "viewer",
) -> tuple[Path, dict, list]:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    frame = _frame()
    calls: list[TrendlineResearchSpec] = []
    loader = FakeLoader(frame, calls)
    output = tmp_path / output_name
    report = asyncio.run(
        runner.run_viewer(
            asset=asset,
            timeframe="1h",
            source="binance",
            start=frame.index[0].to_pydatetime(),
            end=frame["bar_available_at"].iloc[-1].to_pydatetime(),
            output=output,
            loader_factory=lambda: loader,
        )
    )
    return output, report, calls


def test_asset_validation_accepts_arbitrary_canonical_symbols() -> None:
    for asset in ("TAOUSDT", "1000PEPEUSDT", "BNBUSDT", "BTCUSDT_250926"):
        assert runner.validate_asset(asset) == asset
    for asset in (
        "ethusdt",
        "",
        "A",
        "1234",
        " ETHUSDT",
        "ETHUSDT ",
        "_BTCUSDT",
        "BTCUSDT_",
        "BTC__USDT",
        "BTC-USDT",
        "A" * 41,
    ):
        with pytest.raises(runner.ViewerRunnerError):
            runner.validate_asset(asset)


def test_timeframe_validation_is_fixed_duration_and_weekly_is_supported() -> None:
    expected = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1_800,
        "1h": 3_600,
        "2h": 7_200,
        "4h": 14_400,
        "6h": 21_600,
        "8h": 28_800,
        "12h": 43_200,
        "1d": 86_400,
        "3d": 259_200,
        "1w": 604_800,
    }
    assert runner.TIMEFRAME_INTERVAL_SECONDS == expected
    for timeframe, seconds in expected.items():
        assert runner.timeframe_interval_seconds(timeframe) == seconds
    for timeframe in ("1M", "7m", "2d", "monthly", "60", "1hour"):
        with pytest.raises(runner.ViewerRunnerError):
            runner.timeframe_interval_seconds(timeframe)


def test_mature_profile_parsers_resolve_weekly_minutes() -> None:
    from libs.models.trendlines.config.asset_profile import _tf_to_minutes as asset_minutes
    from libs.models.trendlines.config.oscillator_profile import _tf_to_minutes as oscillator_minutes

    assert asset_minutes("1w") == 10_080
    assert oscillator_minutes("1w") == 10_080


def test_utc_boundaries_require_whole_second_and_order() -> None:
    assert runner.parse_utc_timestamp("2026-01-01T00:00:00Z", field_name="start") == BASE_START
    for value in (
        "2026-01-01T00:00:00",
        "2026-01-01T05:30:00+05:30",
        "2026-01-01T00:00:00.001Z",
    ):
        with pytest.raises(runner.ViewerRunnerError):
            runner.parse_utc_timestamp(value, field_name="start")


def test_fetch_guard_runs_before_loader_and_output_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(runner.FETCH_ENVIRONMENT_VARIABLE, raising=False)
    called = False

    def forbidden_loader() -> object:
        nonlocal called
        called = True
        raise AssertionError("loader construction must be guarded")

    output = tmp_path / "viewer"
    with pytest.raises(runner.ViewerRunnerError, match="TRENDLINES_ALLOW_RESEARCH_VIEWER_FETCH"):
        asyncio.run(
            runner.run_viewer(
                asset="TAOUSDT",
                timeframe="4h",
                source="binance",
                start="2026-01-01T00:00:00Z",
                end="2026-03-01T00:00:00Z",
                output=output,
                loader_factory=forbidden_loader,
            )
        )
    assert called is False
    assert output.exists() is False


def test_run_passes_exact_market_boundaries_and_records_final_point_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, report, calls = _run_success(tmp_path, monkeypatch)
    requested = calls[0]
    assert requested.asset == "TAOUSDT"
    assert requested.timeframes == ("1h",)
    assert requested.data.event_start == BASE_START
    assert requested.data.knowledge_cutoff == _frame()["bar_available_at"].iloc[-1].to_pydatetime()
    assert report["selected_position"] == 47
    assert report["prepared_row_count"] == 48
    assert report["display_bar_count"] == 48
    payload = json.loads((output / "viewer_bundle" / "chart_payload.json").read_text())
    assert len(payload["replay_timeline"]) == 1
    assert payload["selected_position"] == 47
    assert report["provider_calls"] == 1
    assert report["page_count"] == 1


def test_display_lookback_is_bounded_by_available_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    frame = _frame()
    loader = FakeLoader(frame, [])
    output = tmp_path / "viewer"
    asyncio.run(
        runner.run_viewer(
            asset="BNBUSDT",
            timeframe="1h",
            source="binance",
            start=frame.index[0].to_pydatetime(),
            end=frame["bar_available_at"].iloc[-1].to_pydatetime(),
            output=output,
            display_bars=250,
            loader_factory=lambda: loader,
        )
    )
    payload = json.loads((output / "viewer_bundle" / "chart_payload.json").read_text())
    assert len(payload["candles"]) == 48


def test_output_overwrite_is_rejected_before_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    output = tmp_path / "existing"
    output.mkdir()
    called = False

    def forbidden_loader() -> object:
        nonlocal called
        called = True
        raise AssertionError("existing output must fail before loader")

    with pytest.raises(runner.ViewerRunnerError, match="already exists"):
        asyncio.run(
            runner.run_viewer(
                asset="TAOUSDT",
                timeframe="1h",
                source="binance",
                start="2026-01-01T00:00:00Z",
                end="2026-03-01T00:00:00Z",
                output=output,
                loader_factory=forbidden_loader,
            )
        )
    assert called is False


def test_failed_execution_removes_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    frame = _frame()
    loader = FakeLoader(frame, [])

    def fail_replay(*_args, **_kwargs):
        raise runner.ViewerRunnerError("synthetic replay failure")

    monkeypatch.setattr(runner, "run_causal_replay", fail_replay)
    output = tmp_path / "viewer"
    with pytest.raises(runner.ViewerRunnerError, match="synthetic replay failure"):
        asyncio.run(
            runner.run_viewer(
                asset="TAOUSDT",
                timeframe="1h",
                source="binance",
                start=frame.index[0].to_pydatetime(),
                end=frame["bar_available_at"].iloc[-1].to_pydatetime(),
                output=output,
                loader_factory=lambda: loader,
            )
        )
    assert output.exists() is False
    assert not tuple(tmp_path.glob(".viewer.staging-*"))


def test_verify_output_detects_payload_and_manifest_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _, _ = _run_success(tmp_path, monkeypatch)
    payload_path = output / "viewer_bundle" / "chart_payload.json"
    payload = json.loads(payload_path.read_text())
    payload["selected_position"] = 1
    payload_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises((runner.ViewerRunnerError, ValueError)):
        runner.verify_output(output)

    output, _, _ = _run_success(
        tmp_path,
        monkeypatch,
        asset="BNBUSDT",
        output_name="manifest-viewer",
    )
    manifest_path = output / "viewer_bundle" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["bundle_id"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises((runner.ViewerRunnerError, ValueError)):
        runner.verify_output(output)


def test_verify_output_rejects_extra_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output, _, _ = _run_success(tmp_path, monkeypatch)
    (output / "unexpected.txt").write_text("x")
    with pytest.raises(runner.ViewerRunnerError, match="unexpected files"):
        runner.verify_output(output)


def test_no_trendline_v2_import_or_d5_execution_in_runner() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "trendline_v2" not in source
    assert "analyze_trendlines_l2d" not in source
