from __future__ import annotations

import ast
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import run_trendline_v2_real_asset_smoke as smoke
from libs.models.trendline_v2.discovery import ProviderReason, ProviderStatus


def _raw_frame(*, include_terminal: bool = True) -> pd.DataFrame:
    count = smoke.EXPECTED_PRIMARY_ROWS + (1 if include_terminal else 0)
    timestamps = [
        smoke._epoch_milliseconds(smoke.START_UTC + index * smoke.BAR_INTERVAL)
        for index in range(count)
    ]
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for index in range(count):
        if index == 0:
            high, low = 11.0, 9.0
        elif index == 1:
            high, low = 12.0, 5.0
        elif index == 2:
            high, low = 20.0, 8.0
        elif index == 3:
            high, low = 14.0, 6.0
        elif index == 4:
            high, low = 18.0, 7.0
        elif index == 5:
            high, low = 17.0, 8.0
        else:
            high, low = 19.0 + (index - 6), 9.0 + (index - 6)
        body = 10.0 + min(index, 6)
        opens.append(body)
        closes.append(body)
        highs.append(max(high, body))
        lows.append(min(low, body))
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * count,
            "taker_buy_base": [0.5] * count,
        }
    )


class _FakeAdapter:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls: list[tuple[str, str, dict[str, int]]] = []

    async def get_historical_ohlcv(self, symbol, timeframe, **kwargs):
        self.calls.append((symbol, timeframe, kwargs))
        return self.frame.copy(deep=True)


def _patch_run_seams(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    statuses = {
        "/": 200,
        "/styles.css": 200,
        "/dist/main.js": 200,
        "/vendor/lightweight-charts.mjs": 200,
        "/bundle/chart_payload.json": 200,
        "/node_modules/lightweight-charts/package.json": 404,
        "/manifest.json": 404,
        "/bundle/../manifest.json": 404,
    }
    monkeypatch.setattr(smoke, "_http_smoke", lambda *_args, **_kwargs: statuses)
    monkeypatch.setattr(
        smoke,
        "_git_identity",
        lambda: ("a" * 40, "research/trendline-v2-phase-8v1-real-asset-smoke-v1"),
    )
    return statuses


@pytest.fixture
def successful_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _patch_run_seams(monkeypatch)
    adapter = _FakeAdapter(_raw_frame())
    report = asyncio.run(smoke.run_smoke(adapter=adapter, output_root=tmp_path / "run"))
    return tmp_path / "run", adapter, report


def test_normalization_uses_exact_utc_boundaries_and_ignores_extra_fields() -> None:
    normalized = smoke.normalize_binance_ohlcv(_raw_frame())
    assert list(normalized.columns) == list(smoke.MODEL_COLUMNS)
    assert normalized.index.tz is not None
    assert str(normalized.index.tz) == "UTC"
    assert len(normalized) == smoke.EXPECTED_PRIMARY_ROWS
    assert normalized.index[0].to_pydatetime() == smoke.START_UTC
    assert normalized.index[-1].to_pydatetime() == smoke.END_UTC - smoke.BAR_INTERVAL
    assert normalized.index[-1].to_pydatetime() + smoke.BAR_INTERVAL == smoke.END_UTC
    first_frame = smoke.build_confirmed_frame(normalized)
    copied_frame = smoke.build_confirmed_frame(normalized.copy(deep=True))
    assert first_frame.input_identity == copied_frame.input_identity
    assert first_frame.row_count == copied_frame.row_count == smoke.EXPECTED_PRIMARY_ROWS


def test_normalization_requires_integer_milliseconds() -> None:
    raw = _raw_frame()
    raw["timestamp"] = raw["timestamp"].astype(float)
    with pytest.raises(smoke.SmokeBlocked, match="integer milliseconds"):
        smoke.normalize_binance_ohlcv(raw)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing", "missing columns"),
        ("nan", "missing/non-numeric"),
        ("gap", "contain a gap"),
        ("duplicate", "duplicated"),
    ],
)
def test_normalization_rejects_source_preflight_failures(case: str, message: str) -> None:
    raw = _raw_frame()
    if case == "missing":
        raw = raw.drop(columns=["volume"])
    elif case == "nan":
        raw.loc[3, "close"] = float("nan")
    elif case == "gap":
        raw.loc[10, "timestamp"] = raw.loc[10, "timestamp"] + 1
    elif case == "duplicate":
        raw.loc[10, "timestamp"] = raw.loc[9, "timestamp"]
    with pytest.raises(smoke.SmokeBlocked, match=message):
        smoke.normalize_binance_ohlcv(raw)


def test_fixed_configs_are_explicit_and_smoke_only() -> None:
    provider_config = smoke.smoke_provider_config()
    assert provider_config.to_dict()["active_config"] == {
        "lookback_duration_seconds": 10_540_800.0,
        "left_confirmation_bars": 1,
        "right_confirmation_bars": 1,
        "min_extrema_per_role": 2,
        "max_hypotheses": 100_000,
        "max_output_candidates": 10_000,
    }
    config = smoke.foundation_config()
    assert config.to_dict()["model"] == smoke.FOUNDATION_CONFIG_INPUT["model"]
    assert "SMOKE_ONLY" in smoke.SMOKE_CONFIG_CLASSIFICATION
    assert "NOT_CANONICAL" in smoke.SMOKE_CONFIG_CLASSIFICATION


def test_primary_run_makes_one_exact_request_and_validates_bundle(
    successful_run,
) -> None:
    output, adapter, report = successful_run
    assert len(adapter.calls) == 1
    assert adapter.calls[0] == (
        smoke.ASSET,
        smoke.TIMEFRAME,
        {
            "since": smoke._epoch_milliseconds(smoke.START_UTC),
            "until": smoke._epoch_milliseconds(smoke.END_UTC),
            "limit": smoke.REQUEST_LIMIT,
        },
    )
    assert report["network_request_count"] == 1
    assert report["raw_row_count"] == 733
    assert report["normalized_row_count"] == 732
    assert report["primary_status"] == "success"
    assert report["fallback_used"] is False
    assert report["chart_has_candidates"] is True
    manifest = smoke.validate_bundle(output / "viewer_bundle")
    payload = json.loads((output / "viewer_bundle/chart_payload.json").read_text())
    assert manifest["bundle_id"] == report["viewer_bundle_id"]
    assert payload["payload_id"] == report["viewer_payload_id"]


def test_provider_result_json_is_canonical_and_hashed(successful_run) -> None:
    output, _, report = successful_run
    path = output / "provider_result.json"
    data = path.read_bytes()
    assert data == smoke._canonical_json_bytes(json.loads(data))
    assert hashlib.sha256(data).hexdigest() == report["provider_result_sha256"]


def test_run_report_semantics_are_deterministic_across_empty_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run_seams(monkeypatch)
    first = asyncio.run(
        smoke.run_smoke(adapter=_FakeAdapter(_raw_frame()), output_root=tmp_path / "first")
    )
    second = asyncio.run(
        smoke.run_smoke(adapter=_FakeAdapter(_raw_frame()), output_root=tmp_path / "second")
    )
    first["viewer_bundle_path"] = None
    second["viewer_bundle_path"] = None
    assert first == second


def test_existing_nonempty_output_is_refused_before_adapter_call(tmp_path: Path) -> None:
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    adapter = _FakeAdapter(_raw_frame())
    with pytest.raises(smoke.SmokeBlocked, match="absent or empty"):
        asyncio.run(smoke.run_smoke(adapter=adapter, output_root=output))
    assert adapter.calls == []


def test_workload_fallback_reuses_data_and_provider_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run_seams(monkeypatch)
    adapter = _FakeAdapter(_raw_frame())
    real_discover = smoke.discover_trendlines
    calls = []

    def discover(frame, *, config, provider_config):
        calls.append((frame, config, provider_config))
        if len(calls) == 1:
            return real_discover(
                frame,
                config=config,
                provider_config=replace(provider_config, max_hypotheses=1),
            )
        return real_discover(frame, config=config, provider_config=provider_config)

    monkeypatch.setattr(smoke, "discover_trendlines", discover)
    report = asyncio.run(smoke.run_smoke(adapter=adapter, output_root=tmp_path / "run"))
    assert len(adapter.calls) == 1
    assert [call[0].row_count for call in calls] == [732, 366]
    assert calls[0][2].to_dict() == calls[1][2].to_dict()
    assert report["fallback_used"] is True
    assert report["selected_window"]["start"] == smoke._iso(smoke.SUFFIX_START_UTC)


@pytest.mark.parametrize(
    "reason",
    [
        ProviderReason.INSUFFICIENT_INPUT,
        ProviderReason.NO_CANDIDATES,
        ProviderReason.INVALID_INPUT,
        ProviderReason.CONFIGURATION_ERROR,
        ProviderReason.PROVIDER_FAILURE,
    ],
)
def test_non_workload_reasons_do_not_trigger_fallback(reason: ProviderReason) -> None:
    result = type(
        "Result",
        (),
        {"status": ProviderStatus.ABSTAINED, "reason": reason},
    )()
    assert smoke.should_use_workload_fallback(result) is False


def _minimal_web_root(root: Path) -> Path:
    (root / "dist").mkdir(parents=True)
    vendor = root / "node_modules/lightweight-charts/dist"
    vendor.mkdir(parents=True)
    (root / "index.html").write_text("viewer", encoding="utf-8")
    (root / "styles.css").write_text("body {}", encoding="utf-8")
    (root / "dist/main.js").write_text("", encoding="utf-8")
    (vendor / "lightweight-charts.standalone.production.mjs").write_text(
        "export {};", encoding="utf-8"
    )
    return root


def test_browserless_http_smoke_allowlists_routes(successful_run, tmp_path: Path) -> None:
    output, _, _ = successful_run
    statuses = smoke._http_smoke(
        output / "viewer_bundle",
        web_root=_minimal_web_root(tmp_path / "web"),
    )
    assert statuses["/"] == 200
    assert statuses["/bundle/chart_payload.json"] == 200
    assert statuses["/manifest.json"] == 404
    assert statuses["/bundle/../manifest.json"] == 404


def test_runner_has_no_browser_launcher_or_forbidden_model_imports() -> None:
    source_path = Path(smoke.__file__)
    source = source_path.read_text(encoding="utf-8")
    for forbidden in ("webbrowser.open", "Playwright", "Selenium", "Puppeteer", "Chromium launch"):
        assert forbidden not in source
    tree = ast.parse(source)
    allowed_prefixes = (
        "libs.market_data.binance_native",
        "libs.models.trendline_v2.tools.viewer",
        "libs.models.trendline_v2",
    )
    forbidden_prefixes = (
        "libs.models.trendline",
        "libs.models.trendline_family",
        "libs.trendlines",
        "libs.models.trendlines_old",
        "libs.models.sr",
        "libs.models.regime_v2",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if module.startswith(forbidden_prefixes):
                assert module.startswith(allowed_prefixes)
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden_prefixes)
