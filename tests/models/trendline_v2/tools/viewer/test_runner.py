from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from libs.models.trendline_v2.tools.viewer import runner


UTC = timezone.utc
BASE_START = datetime(2026, 7, 20, tzinfo=UTC)
ROW_COUNT = 48
AS_OF = BASE_START + timedelta(hours=ROW_COUNT)


def _raw_frame(
    *,
    count: int = ROW_COUNT,
    start: datetime = BASE_START,
    step: timedelta = timedelta(hours=1),
    epoch: bool = False,
) -> pd.DataFrame:
    rows = []
    for index in range(count):
        timestamp = start + step * index
        base = 100.0 + (20.0 if index % 12 in {3, 4} else 0.0)
        if index % 12 in {8, 9}:
            base -= 20.0
        rows.append(
            {
                "timestamp": int(timestamp.timestamp() * 1_000)
                if epoch
                else timestamp.isoformat().replace("+00:00", "Z"),
                "open": base,
                "high": base + 10.0,
                "low": base - 10.0,
                "close": base,
                "volume": 1.0,
            }
        )
    return pd.DataFrame(rows)


def _write_csv(path: Path, frame: pd.DataFrame) -> Path:
    frame.to_csv(path, index=False)
    return path


def _binance_frame(
    *,
    count: int = ROW_COUNT,
    interval_seconds: int = 3_600,
) -> pd.DataFrame:
    frame = _raw_frame(
        count=count,
        step=timedelta(seconds=interval_seconds),
        epoch=True,
    )
    frame["close_time"] = frame["timestamp"] + interval_seconds * 1_000 - 1
    return frame


def _run(csv_path: Path, output: Path, **kwargs):
    return asyncio.run(
        runner.run_viewer(
            asset="ETHUSDT",
            timeframe="1h",
            input_csv=csv_path,
            as_of=AS_OF,
            output=output,
            **kwargs,
        )
    )


def _rebind_source_binding(output: Path, binding: dict) -> None:
    semantic = dict(binding)
    semantic.pop("source_binding_id")
    binding["source_binding_id"] = runner.deterministic_hash(
        runner.SOURCE_BINDING_SCHEMA_VERSION,
        semantic,
    )
    binding_bytes = runner._canonical_json_bytes(binding)
    (output / "source_binding.json").write_bytes(binding_bytes)
    report_path = output / "run_report.json"
    report = json.loads(report_path.read_text())
    report["source_binding_id"] = binding["source_binding_id"]
    report["source_binding_sha256"] = runner._sha256(binding_bytes)
    report["page_count"] = binding["page_count"]
    report["request_pages"] = binding["request_pages"]
    report["member_hashes"]["source_binding.json"] = runner._sha256(binding_bytes)
    report["run_id"] = runner._run_id(report)
    report_path.write_bytes(runner._canonical_json_bytes(report))


def test_asset_and_timeframe_rules_are_strict() -> None:
    for value in (
        "ethusdt",
        "ETH/USDT",
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
            runner.validate_asset(value)
    for value in ("ETHUSDT", "BNBUSDT", "1000PEPEUSDT", "BTCUSDT_250926"):
        assert runner.validate_asset(value) == value

    expected_intervals = {
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
    assert runner.TIMEFRAME_INTERVAL_SECONDS == expected_intervals
    for timeframe, seconds in expected_intervals.items():
        assert runner.timeframe_interval_seconds(timeframe) == seconds
    for value in ("1M", "7m", "2d", "monthly", "60", "1hour", "0h", "1.5h", "-1h"):
        with pytest.raises(runner.ViewerRunnerError):
            runner.timeframe_interval_seconds(value)


def test_arbitrary_canonical_asset_publishes_and_verifies(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "pepe.csv", _raw_frame())
    output = tmp_path / "output"
    report = asyncio.run(
        runner.run_viewer(
            asset="1000PEPEUSDT",
            timeframe="1h",
            input_csv=csv_path,
            as_of=AS_OF,
            output=output,
        )
    )
    assert report["asset"] == "1000PEPEUSDT"
    assert runner.verify_output(output)["asset"] == "1000PEPEUSDT"


def test_weekly_timeframe_publishes_and_verifies(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "weekly.csv",
        _raw_frame(step=timedelta(weeks=1)),
    )
    output = tmp_path / "output"
    as_of = BASE_START + timedelta(weeks=ROW_COUNT)
    report = asyncio.run(
        runner.run_viewer(
            asset="BNBUSDT",
            timeframe="1w",
            input_csv=csv_path,
            as_of=as_of,
            output=output,
        )
    )
    assert report["timeframe"] == "1w"
    assert runner.verify_output(output)["timeframe"] == "1w"


def test_valid_iso_csv_publishes_and_verifies(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "eth.csv", _raw_frame())
    output = tmp_path / "output"
    report = _run(csv_path, output)
    assert report["viewer_status"] == "VIEWER_READY_WITH_LINES"
    assert report["provider_status"] == "success"
    assert report["candidate_count"] > 0
    assert report["source_type"] == "csv"
    assert report["page_count"] == 0
    assert runner.verify_output(output)["run_id"] == report["run_id"]
    assert {
        path.name for path in output.iterdir()
    } == {"source_binding.json", "provider_result.json", "run_report.json", "viewer_bundle"}
    assert {path.name for path in (output / "viewer_bundle").iterdir()} == {
        "chart_payload.json",
        "manifest.json",
    }


def test_epoch_millisecond_csv_has_same_semantic_ids(tmp_path: Path) -> None:
    iso_path = _write_csv(tmp_path / "iso.csv", _raw_frame())
    epoch_path = _write_csv(tmp_path / "epoch.csv", _raw_frame(epoch=True))
    first = _run(iso_path, tmp_path / "first")
    second = _run(epoch_path, tmp_path / "second")
    for key in ("run_id", "provider_result_id", "viewer_payload_id", "viewer_bundle_id", "input_identity"):
        assert first[key] == second[key]


def test_future_rows_and_future_ohlcv_do_not_change_output_identity(tmp_path: Path) -> None:
    base = _raw_frame()
    future = _raw_frame(count=2, start=AS_OF + timedelta(hours=1))
    future.loc[:, "high"] = -100.0
    future.loc[:, "low"] = 100.0
    with_future = pd.concat([base, future], ignore_index=True)
    first = _run(_write_csv(tmp_path / "base.csv", base), tmp_path / "base")
    second = _run(
        _write_csv(tmp_path / "future.csv", with_future),
        tmp_path / "future",
    )
    for key in ("run_id", "provider_result_id", "viewer_payload_id", "viewer_bundle_id", "input_identity"):
        assert first[key] == second[key]


def test_unclosed_as_of_candle_is_excluded(tmp_path: Path) -> None:
    frame = _raw_frame(count=ROW_COUNT + 1)
    report = _run(_write_csv(tmp_path / "open.csv", frame), tmp_path / "output")
    provider = json.loads((tmp_path / "output/provider_result.json").read_text())
    assert provider["request"]["input_data"]["input_identity"] == report["input_identity"]
    assert provider["request"]["input_data"]["timestamps"][-1] < int(AS_OF.timestamp() * 1_000_000_000)
    assert provider["request"]["input_data"]["input_identity"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("mixed", "formats must not be mixed"),
        ("naive", "timezone-aware UTC"),
        ("duplicate", "duplicated"),
        ("unordered", "strictly increasing"),
        ("gap", "missing interval"),
        ("invalid_ohlc", "high bounds"),
        ("negative_volume", "negative"),
        ("non_numeric", "non-numeric"),
    ],
)
def test_csv_preflight_rejects_malformed_input(
    tmp_path: Path, mutation: str, message: str
) -> None:
    frame = _raw_frame()
    if mutation == "mixed":
        frame["timestamp"] = frame["timestamp"].astype(object)
        frame.loc[1, "timestamp"] = int((BASE_START + timedelta(hours=1)).timestamp() * 1_000)
    elif mutation == "naive":
        frame["timestamp"] = frame["timestamp"].astype(object)
        frame.loc[1, "timestamp"] = (BASE_START + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    elif mutation == "duplicate":
        frame["timestamp"] = frame["timestamp"].astype(object)
        frame.loc[5, "timestamp"] = frame.loc[4, "timestamp"]
    elif mutation == "unordered":
        frame["timestamp"] = frame["timestamp"].astype(object)
        frame.loc[5, "timestamp"], frame.loc[6, "timestamp"] = (
            frame.loc[6, "timestamp"],
            frame.loc[5, "timestamp"],
        )
    elif mutation == "gap":
        frame["timestamp"] = frame["timestamp"].astype(object)
        for index in range(5, len(frame)):
            frame.loc[index, "timestamp"] = (
                BASE_START + timedelta(hours=index + 1)
            ).isoformat().replace("+00:00", "Z")
    elif mutation == "invalid_ohlc":
        frame.loc[5, "high"] = frame.loc[5, "open"] - 1
    elif mutation == "negative_volume":
        frame.loc[5, "volume"] = -1
    elif mutation == "non_numeric":
        frame["close"] = frame["close"].astype(object)
        frame.loc[5, "close"] = "bad"
    with pytest.raises(runner.ViewerRunnerError, match=message):
        _run(_write_csv(tmp_path / "bad.csv", frame), tmp_path / "output")


def test_existing_nonempty_output_is_refused_before_csv_read(tmp_path: Path) -> None:
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(runner.ViewerRunnerError, match="absent or empty"):
        _run(tmp_path / "does-not-exist.csv", output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_provider_profile_is_frozen() -> None:
    assert runner.PROVIDER_PROFILE_NAME == "confirmed_extrema_pair_viewer_v1"
    assert runner.viewer_provider_config().to_dict()["active_config"] == runner.VIEWER_PROVIDER_CONFIG_VALUES


def test_abstention_publishes_valid_no_lines_bundle(tmp_path: Path) -> None:
    short = _raw_frame(count=2)
    report = _run(_write_csv(tmp_path / "short.csv", short), tmp_path / "output")
    assert report["provider_status"] == "abstained"
    assert report["viewer_status"] == "VIEWER_READY_NO_LINES"
    assert report["candidate_count"] == 0
    runner.verify_output(tmp_path / "output")


def test_source_mutation_changes_binding_and_result_identity(tmp_path: Path) -> None:
    first_path = _write_csv(tmp_path / "first.csv", _raw_frame())
    first = _run(first_path, tmp_path / "first")
    changed = _raw_frame()
    changed.loc[10, "close"] += 0.25
    second = _run(_write_csv(tmp_path / "second.csv", changed), tmp_path / "second")
    assert first["input_identity"] != second["input_identity"]
    assert first["source_binding_id"] != second["source_binding_id"]
    assert first["viewer_payload_id"] != second["viewer_payload_id"]


def test_same_normalized_input_is_deterministic(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "source.csv", _raw_frame())
    first = _run(csv_path, tmp_path / "first")
    second = _run(csv_path, tmp_path / "second")
    assert first["run_id"] == second["run_id"]
    assert first["provider_result_id"] == second["provider_result_id"]
    assert first["viewer_bundle_id"] == second["viewer_bundle_id"]


def test_verify_detects_provider_payload_mutation_and_extra_file(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "source.csv", _raw_frame())
    _run(csv_path, tmp_path / "original")
    copied = tmp_path / "copied"
    shutil.copytree(tmp_path / "original", copied)
    provider_path = copied / "provider_result.json"
    provider = json.loads(provider_path.read_text())
    provider["detail"] = "forged"
    provider_path.write_bytes(runner._canonical_json_bytes(provider))
    with pytest.raises(runner.ViewerRunnerError):
        runner.verify_output(copied)
    shutil.copytree(tmp_path / "original", tmp_path / "extra")
    (tmp_path / "extra" / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(runner.ViewerRunnerError, match="unexpected"):
        runner.verify_output(tmp_path / "extra")


def test_verify_rejects_rebound_source_close_and_report_boundary(
    tmp_path: Path,
) -> None:
    _run(_write_csv(tmp_path / "source.csv", _raw_frame()), tmp_path / "original")
    copied = tmp_path / "copied"
    shutil.copytree(tmp_path / "original", copied)
    binding_path = copied / "source_binding.json"
    binding = json.loads(binding_path.read_text())
    binding["last_candle_close"] = "2026-07-22T01:00:00Z"
    semantic = dict(binding)
    semantic.pop("source_binding_id")
    binding["source_binding_id"] = runner.deterministic_hash(
        runner.SOURCE_BINDING_SCHEMA_VERSION,
        semantic,
    )
    binding_bytes = runner._canonical_json_bytes(binding)
    binding_path.write_bytes(binding_bytes)
    report_path = copied / "run_report.json"
    report = json.loads(report_path.read_text())
    report["source_binding_id"] = binding["source_binding_id"]
    report["source_binding_sha256"] = runner._sha256(binding_bytes)
    report["member_hashes"]["source_binding.json"] = runner._sha256(binding_bytes)
    report["run_id"] = runner._run_id(report)
    report_path.write_bytes(runner._canonical_json_bytes(report))
    with pytest.raises(runner.ViewerRunnerError, match="last candle close"):
        runner.verify_output(copied)


def test_binance_guard_runs_before_adapter_and_output_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        raise AssertionError("adapter must not be constructed")

    monkeypatch.delenv(runner.FETCH_ENVIRONMENT_VARIABLE, raising=False)
    output = tmp_path / "binance-output"
    with pytest.raises(runner.ViewerRunnerError, match="requires"):
        asyncio.run(
            runner.run_viewer(
                asset="ETHUSDT",
                timeframe="1h",
                source="binance",
                start=BASE_START,
                as_of=AS_OF,
                output=output,
                adapter_factory=factory,
            )
        )
    assert calls == 0
    assert not output.exists()


def test_binance_pagination_is_deterministic_and_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    all_rows = _binance_frame(count=runner.BINANCE_PAGE_LIMIT + 2)

    class FakeAdapter:
        def __init__(self):
            self.calls = []

        async def get_historical_ohlcv(self, symbol, timeframe, **kwargs):
            self.calls.append((symbol, timeframe, kwargs))
            page = all_rows[all_rows["timestamp"] >= kwargs["since"]]
            return page.iloc[: runner.BINANCE_PAGE_LIMIT].copy()

    adapter = FakeAdapter()
    report = asyncio.run(
        runner.run_viewer(
            asset="1000PEPEUSDT",
            timeframe="1h",
            source="binance",
            start=BASE_START,
            as_of=BASE_START + timedelta(hours=len(all_rows)),
            output=tmp_path / "binance",
            adapter_factory=lambda: adapter,
        )
    )
    assert len(adapter.calls) == 2
    assert all(call[0] == "1000PEPEUSDT" for call in adapter.calls)
    assert all(call[1] == "1h" for call in adapter.calls)
    assert all(call[2]["limit"] == runner.BINANCE_PAGE_LIMIT for call in adapter.calls)
    assert all(call[2]["include_close_time"] is True for call in adapter.calls)
    assert report["page_count"] == 2
    runner.verify_output(tmp_path / "binance")


def test_binance_weekly_alignment_publishes_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    interval_seconds = runner.TIMEFRAME_INTERVAL_SECONDS["1w"]
    rows = _binance_frame(count=12, interval_seconds=interval_seconds)

    class FakeAdapter:
        async def get_historical_ohlcv(self, symbol, timeframe, **kwargs):
            assert symbol == "BNBUSDT"
            assert timeframe == "1w"
            return rows[rows["timestamp"] >= kwargs["since"]].copy()

    output = tmp_path / "weekly-binance"
    report = asyncio.run(
        runner.run_viewer(
            asset="BNBUSDT",
            timeframe="1w",
            source="binance",
            start=BASE_START,
            as_of=BASE_START + timedelta(weeks=12),
            output=output,
            adapter_factory=FakeAdapter,
        )
    )
    assert report["timeframe"] == "1w"
    assert runner.verify_output(output)["timeframe"] == "1w"


def test_binance_rebound_second_page_since_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    all_rows = _binance_frame(count=runner.BINANCE_PAGE_LIMIT + 2)

    class FakeAdapter:
        async def get_historical_ohlcv(self, _symbol, _timeframe, **kwargs):
            page = all_rows[all_rows["timestamp"] >= kwargs["since"]]
            return page.iloc[: runner.BINANCE_PAGE_LIMIT].copy()

    output = tmp_path / "binance"
    asyncio.run(
        runner.run_viewer(
            asset="ETHUSDT",
            timeframe="1h",
            source="binance",
            start=BASE_START,
            as_of=BASE_START + timedelta(hours=len(all_rows)),
            output=output,
            adapter_factory=FakeAdapter,
        )
    )
    binding = json.loads((output / "source_binding.json").read_text())
    binding["request_pages"][1]["since"] += 3_600_000
    _rebind_source_binding(output, binding)
    with pytest.raises(runner.ViewerRunnerError, match="page sequence"):
        runner.verify_output(output)


def test_binance_extra_impossible_request_page_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    all_rows = _binance_frame(count=runner.BINANCE_PAGE_LIMIT + 2)

    class FakeAdapter:
        async def get_historical_ohlcv(self, _symbol, _timeframe, **kwargs):
            page = all_rows[all_rows["timestamp"] >= kwargs["since"]]
            return page.iloc[: runner.BINANCE_PAGE_LIMIT].copy()

    output = tmp_path / "binance"
    asyncio.run(
        runner.run_viewer(
            asset="ETHUSDT",
            timeframe="1h",
            source="binance",
            start=BASE_START,
            as_of=BASE_START + timedelta(hours=len(all_rows)),
            output=output,
            adapter_factory=FakeAdapter,
        )
    )
    binding = json.loads((output / "source_binding.json").read_text())
    binding["page_count"] = 3
    binding["request_pages"].append(
        {
            "since": int(BASE_START.timestamp() * 1_000)
            + 2 * runner.BINANCE_PAGE_LIMIT * 3_600_000,
            "until": int((BASE_START + timedelta(hours=len(all_rows))).timestamp() * 1_000),
            "limit": runner.BINANCE_PAGE_LIMIT,
        }
    )
    _rebind_source_binding(output, binding)
    with pytest.raises(runner.ViewerRunnerError, match="row count"):
        runner.verify_output(output)


def test_binance_first_page_must_begin_at_requested_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    all_rows = _binance_frame()

    class FakeAdapter:
        async def get_historical_ohlcv(self, _symbol, _timeframe, **_kwargs):
            return all_rows.iloc[1:].copy()

    with pytest.raises(runner.ViewerRunnerError, match="unexpected timestamp"):
        asyncio.run(
            runner.run_viewer(
                asset="ETHUSDT",
                timeframe="1h",
                source="binance",
                start=BASE_START,
                as_of=AS_OF,
                output=tmp_path / "binance",
                adapter_factory=FakeAdapter,
            )
        )


def test_binance_within_page_missing_interval_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    rows = _binance_frame()
    rows.loc[5:, "timestamp"] += 3_600_000
    rows.loc[5:, "close_time"] += 3_600_000

    class FakeAdapter:
        async def get_historical_ohlcv(self, _symbol, _timeframe, **_kwargs):
            return rows.copy()

    with pytest.raises(runner.ViewerRunnerError, match="gap or duplicate"):
        asyncio.run(
            runner.run_viewer(
                asset="ETHUSDT",
                timeframe="1h",
                source="binance",
                start=BASE_START,
                as_of=AS_OF,
                output=tmp_path / "binance",
                adapter_factory=FakeAdapter,
            )
        )


def test_binance_within_page_duplicate_timestamp_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    rows = _binance_frame()
    rows.loc[5, "timestamp"] = rows.loc[4, "timestamp"]
    rows.loc[5, "close_time"] = rows.loc[5, "timestamp"] + 3_600_000 - 1

    class FakeAdapter:
        async def get_historical_ohlcv(self, _symbol, _timeframe, **_kwargs):
            return rows.copy()

    with pytest.raises(runner.ViewerRunnerError, match="strictly increasing"):
        asyncio.run(
            runner.run_viewer(
                asset="ETHUSDT",
                timeframe="1h",
                source="binance",
                start=BASE_START,
                as_of=AS_OF,
                output=tmp_path / "binance",
                adapter_factory=FakeAdapter,
            )
        )


@pytest.mark.parametrize("column", ["timestamp", "close_time"])
def test_binance_fractional_milliseconds_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, column: str
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    rows = _binance_frame()
    rows[column] = rows[column].astype(object)
    rows.loc[2, column] = float(rows.loc[2, column]) + 0.5

    class FakeAdapter:
        async def get_historical_ohlcv(self, _symbol, _timeframe, **_kwargs):
            return rows.copy()

    with pytest.raises(runner.ViewerRunnerError, match="finite integers"):
        asyncio.run(
            runner.run_viewer(
                asset="ETHUSDT",
                timeframe="1h",
                source="binance",
                start=BASE_START,
                as_of=AS_OF,
                output=tmp_path / "binance",
                adapter_factory=FakeAdapter,
            )
        )


def test_binance_non_exact_close_time_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    rows = _binance_frame()
    rows.loc[0, "close_time"] = rows.loc[0, "timestamp"] + 1

    class FakeAdapter:
        async def get_historical_ohlcv(self, _symbol, _timeframe, **_kwargs):
            return rows.copy()

    with pytest.raises(runner.ViewerRunnerError, match="close times are not exact"):
        asyncio.run(
            runner.run_viewer(
                asset="ETHUSDT",
                timeframe="1h",
                source="binance",
                start=BASE_START,
                as_of=AS_OF,
                output=tmp_path / "binance",
                adapter_factory=FakeAdapter,
            )
        )


def test_binance_failure_is_not_retried_and_staging_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(runner.FETCH_ENVIRONMENT_VARIABLE, "1")
    calls = 0

    class FailingAdapter:
        async def get_historical_ohlcv(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            raise RuntimeError("network failure")

    output = tmp_path / "failure"
    with pytest.raises(runner.ViewerRunnerError, match="no retry"):
        asyncio.run(
            runner.run_viewer(
                asset="ETHUSDT",
                timeframe="1h",
                source="binance",
                start=BASE_START,
                as_of=AS_OF,
                output=output,
                adapter_factory=FailingAdapter,
            )
        )
    assert calls == 1
    assert not output.exists()
    assert not list(tmp_path.glob(".failure.*"))


def test_runner_has_no_diagnostic_or_fixed_smoke_dependency() -> None:
    source = inspect.getsource(runner)
    assert "diagnostic_export" not in source
    assert "run_trendline_v2_real_asset_smoke" not in source


def test_loopback_server_is_fixed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = {}

    class FakeServer:
        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            calls["closed"] = True

    def fake_make_server(bundle, *, host, port):
        calls.update(bundle=Path(bundle), host=host, port=port)
        return FakeServer()

    monkeypatch.setattr(runner, "make_server", fake_make_server)
    runner.serve_viewer(tmp_path / "out", port=9876)
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 9876
    assert calls["closed"] is True
