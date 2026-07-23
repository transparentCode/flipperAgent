from __future__ import annotations

import ast
import csv
import os
from pathlib import Path
import shutil

import pandas as pd
import pytest

from libs.models.trendline_v2.domain.identity import deterministic_hash
from scripts import freeze_trendline_v2_fresh_scope_sources as study


def _frame(timeframe: str) -> pd.DataFrame:
    interval_ms = study.INTERVAL_SECONDS[timeframe] * 1_000
    rows = study.EXPECTED_ADAPTER_ROWS[timeframe]
    start = study._epoch_ms(study.START_UTC)
    timestamps = [start + index * interval_ms for index in range(rows)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0 + index for index in range(rows)],
            "high": [101.0 + index for index in range(rows)],
            "low": [99.0 + index for index in range(rows)],
            "close": [100.5 + index for index in range(rows)],
            "volume": [10.0 + index for index in range(rows)],
        }
    )


def _frames() -> dict[tuple[str, str], pd.DataFrame]:
    return {
        (asset, timeframe): _frame(timeframe)
        for asset, timeframe in study.COHORT_ORDER
    }


class FakeAdapter:
    def __init__(
        self,
        frames: dict[tuple[str, str], pd.DataFrame],
        *,
        fail_on: tuple[str, str] | None = None,
    ) -> None:
        self.frames = frames
        self.fail_on = fail_on
        self.calls: list[dict[str, object]] = []

    async def get_historical_ohlcv(
        self,
        *,
        symbol: str,
        timeframe: str,
        since: int,
        until: int,
        limit: int,
    ) -> pd.DataFrame:
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "since": since,
                "until": until,
                "limit": limit,
            }
        )
        if self.fail_on == (symbol, timeframe):
            raise RuntimeError("fake request failure")
        return self.frames[(symbol, timeframe)].copy()


def _authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(study.NETWORK_ENV, "1")


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    frames: dict[tuple[str, str], pd.DataFrame] | None = None,
    fail_on: tuple[str, str] | None = None,
    before_promote: study.BeforePromoteHook | None = None,
) -> tuple[dict[str, object], FakeAdapter, Path]:
    _authorized(monkeypatch)
    adapter = FakeAdapter(_frames() if frames is None else frames, fail_on=fail_on)
    output = tmp_path / "freeze"
    result = study.run_freeze(
        output_root=output,
        adapter_factory=lambda: adapter,
        execute_network=True,
        _before_promote=before_promote,
    )
    return result, adapter, output


def _copy_bundle(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


def _offline_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    _, _, source = _run(tmp_path / "source-run", monkeypatch)
    source_copy = _copy_bundle(source, tmp_path / "source")
    monkeypatch.setattr(
        study,
        "SUPERSEDED_SOURCE_INVENTORY_SHA256",
        study._inventory_digest(study._inventory(source_copy)),
    )
    return source_copy, tmp_path / "offline"


def test_exact_six_dataset_contract_and_fixed_request_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, adapter, output = _run(tmp_path, monkeypatch)
    expected_calls = [
        {
            "symbol": asset,
            "timeframe": timeframe,
            "since": study._epoch_ms(study.START_UTC),
            "until": study._epoch_ms(study.END_UTC),
            "limit": 1000,
        }
        for asset, timeframe in study.COHORT_ORDER
    ]
    assert adapter.calls == expected_calls
    assert len(adapter.calls) == 6
    assert result["output_root"] == str(output)
    assert [
        report["dataset_id"] for report in result["dataset_reports"]
    ] == [spec.dataset_id for spec in study.DATASETS]
    assert result["network_audit"]["network_request_count"] == 6
    assert result["network_audit"]["retry_count"] == 0
    assert result["network_audit"]["fallback_count"] == 0
    assert output.is_dir()


def test_exact_raw_confirmed_counts_and_endpoint_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    for spec in study.DATASETS:
        report = study._load_json(output / "datasets" / spec.dataset_id / "run_report.json")
        assert report["adapter_row_count"] == study.EXPECTED_ADAPTER_ROWS[spec.timeframe]
        assert report["confirmed_row_count"] == study.EXPECTED_CONFIRMED_ROWS[spec.timeframe]
        assert report["dropped_unclosed_row_count"] == 1
        assert report["first_adapter_timestamp"] == "2026-05-22T00:00:00Z"
        assert report["last_adapter_timestamp"] == "2026-07-01T00:00:00Z"
        assert report["first_confirmed_timestamp"] == "2026-05-22T00:00:00Z"
        expected_last = (
            "2026-06-30T23:00:00Z"
            if spec.timeframe == "1h"
            else "2026-06-30T20:00:00Z"
        )
        assert report["last_confirmed_timestamp"] == expected_last
        assert report["request_end"] == "2026-07-01T00:00:00Z"


def test_network_gate_runs_before_adapter_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed = False

    def factory() -> FakeAdapter:
        nonlocal constructed
        constructed = True
        return FakeAdapter(_frames())

    monkeypatch.delenv(study.NETWORK_ENV, raising=False)
    with pytest.raises(study.NetworkGateError):
        study.run_freeze(
            output_root=tmp_path / "freeze",
            adapter_factory=factory,
            execute_network=True,
        )
    assert constructed is False
    assert not (tmp_path / "freeze").exists()


def test_cli_gate_requires_execute_flag_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(study.NETWORK_ENV, raising=False)
    assert study.main(["--output-root", str(tmp_path / "freeze")]) == 2
    assert "BLOCKED_FRESH_SOURCE_FREEZE" in capsys.readouterr().err


def test_one_hour_and_four_hour_spacing() -> None:
    for timeframe in study.TIMEFRAMES:
        rows, provider_input = study._normalize_frame(_frame(timeframe), study._dataset_spec("BTCUSDT", timeframe))
        timestamps = [row["timestamp"] for row in rows]
        interval_ms = study.INTERVAL_SECONDS[timeframe] * 1_000
        assert {right - left for left, right in zip(timestamps, timestamps[1:])} == {interval_ms}
        assert provider_input.row_count == study.EXPECTED_CONFIRMED_ROWS[timeframe]


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("duplicate", lambda frame: frame.__setitem__("timestamp", frame["timestamp"].mask(frame.index == 1, frame["timestamp"].iloc[0]))),
        ("gap", lambda frame: frame.__setitem__("timestamp", frame["timestamp"].mask(frame.index == 100, frame["timestamp"].iloc[100] + 3_600_000))),
        ("out_of_order", lambda frame: frame.__setitem__("timestamp", frame["timestamp"].where(frame.index != 1, frame["timestamp"].iloc[2]).where(frame.index != 2, frame["timestamp"].iloc[1]))),
        ("missing_column", lambda frame: frame.drop(columns=["close"], inplace=True)),
        ("non_numeric", lambda frame: frame.__setitem__("close", frame["close"].astype(object).mask(frame.index == 1, "bad"))),
        ("non_finite", lambda frame: frame.__setitem__("high", frame["high"].mask(frame.index == 1, float("inf")))),
        ("invalid_ohlc", lambda frame: frame.__setitem__("high", frame["low"] - 1.0)),
        ("negative_volume", lambda frame: frame.__setitem__("volume", frame["volume"].mask(frame.index == 1, -1.0))),
    ],
)
def test_invalid_source_stops_and_never_publishes(
    name: str,
    mutate: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = _frames()
    bad = frames[("BTCUSDT", "4h")]
    assert callable(mutate)
    mutate(bad)
    _authorized(monkeypatch)
    adapter = FakeAdapter(frames)
    output = tmp_path / f"freeze-{name}"
    with pytest.raises(study.FreezeError):
        study.run_freeze(
            output_root=output,
            adapter_factory=lambda: adapter,
            execute_network=True,
        )
    assert len(adapter.calls) == 2
    assert not output.exists()


def test_failure_stops_later_requests_and_never_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorized(monkeypatch)
    adapter = FakeAdapter(_frames(), fail_on=("BTCUSDT", "4h"))
    output = tmp_path / "freeze"
    with pytest.raises(study.FreezeError, match="dataset=btcusdt_4h"):
        study.run_freeze(
            output_root=output,
            adapter_factory=lambda: adapter,
            execute_network=True,
        )
    assert len(adapter.calls) == 2
    assert not output.exists()


def test_existing_output_root_refused_before_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorized(monkeypatch)
    output = tmp_path / "freeze"
    output.mkdir()
    constructed = False

    def factory() -> FakeAdapter:
        nonlocal constructed
        constructed = True
        return FakeAdapter(_frames())

    with pytest.raises(FileExistsError):
        study.run_freeze(output_root=output, adapter_factory=factory, execute_network=True)
    assert constructed is False


def test_atomic_staging_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[bool, bool, Path]] = []

    def before_promote(staging: Path, output: Path) -> None:
        seen.append((staging.is_dir(), output.exists(), staging))

    _, _, output = _run(tmp_path, monkeypatch, before_promote=before_promote)
    assert len(seen) == 1
    assert seen[0][0] is True
    assert seen[0][1] is False
    assert seen[0][2] != output
    assert output.is_dir()


def test_offline_regeneration_uses_raw_rows_and_never_constructs_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _offline_source(tmp_path, monkeypatch)
    constructed = False

    def forbidden_factory() -> object:
        nonlocal constructed
        constructed = True
        raise AssertionError("offline remediation must not construct Binance adapter")

    monkeypatch.setattr(study, "_default_adapter_factory", forbidden_factory)
    result = study.regenerate_offline(source_root=source, output_root=output)
    assert constructed is False
    assert result["remediation_network_request_count"] == 0
    assert result["historical_acquisition_request_count"] == 6
    for spec in study.DATASETS:
        payload = study._load_json(
            output / "datasets" / spec.dataset_id / "provider_input.json"
        )
        assert payload["row_count"] == study.EXPECTED_CONFIRMED_ROWS[spec.timeframe]
    verified = study.verify_bundle(output)
    assert verified["inventory_sha256"] == study._inventory_digest(
        study._inventory(output)
    )


def test_offline_regeneration_is_zero_network_and_source_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _offline_source(tmp_path, monkeypatch)
    before = study._inventory(source)
    network_calls = 0

    def forbidden_network(*args: object, **kwargs: object) -> object:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("offline remediation must not access network")

    monkeypatch.setattr(study, "_default_adapter_factory", forbidden_network)
    study.regenerate_offline(source_root=source, output_root=output)
    assert network_calls == 0
    assert study._inventory(source) == before


def test_offline_regeneration_refuses_existing_canonical_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = _offline_source(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError):
        study.regenerate_offline(source_root=source, output_root=source)


def test_provider_input_round_trip_and_exact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    payload = study._load_json(
        output / "datasets" / "btcusdt_1h" / "provider_input.json"
    )
    restored = study._provider_input_from_dict(payload)
    assert payload["schema_version"] == study.PROVIDER_INPUT_SCHEMA
    assert payload["row_count"] == 960
    assert restored.to_dict() == {
        key: value
        for key, value in payload.items()
        if key not in {"schema_version", "row_count"}
    }
    assert restored.input_identity == payload["input_identity"]
    assert restored.row_count == 960
    assert restored.confirmed_through == study.END_UTC


def test_provider_input_schema_and_market_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    contract = study._load_json(output / "cohort_contract.json")
    assert contract["market"] == "binance_usd_m_futures"
    for spec in study.DATASETS:
        dataset_root = output / "datasets" / spec.dataset_id
        payload = study._load_json(dataset_root / "provider_input.json")
        report = study._load_json(dataset_root / "run_report.json")
        assert payload["schema_version"] == study.PROVIDER_INPUT_SCHEMA
        assert payload["row_count"] == study.EXPECTED_CONFIRMED_ROWS[spec.timeframe]
        assert report["market"] == "binance_usd_m_futures"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(row_count=payload["row_count"] + 1),
        lambda payload: payload.update(row_count=True),
        lambda payload: payload.update(row_count=0),
        lambda payload: payload.update(row_count=-1),
        lambda payload: payload.pop("row_count"),
    ],
    ids=["mismatch", "boolean", "zero", "negative", "missing"],
)
def test_provider_input_row_count_is_strictly_validated(
    mutation: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    payload = study._load_json(
        output / "datasets" / "btcusdt_1h" / "provider_input.json"
    )
    assert callable(mutation)
    mutation(payload)
    with pytest.raises(study.FreezeError):
        study._provider_input_from_dict(payload)


def test_provider_input_mismatch_is_rejected_even_with_updated_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, source = _run(tmp_path / "source", monkeypatch)
    output = _copy_bundle(source, tmp_path / "forged")
    other_payload = study._load_json(
        output / "datasets" / "ethusdt_1h" / "provider_input.json"
    )
    target_input = output / "datasets" / "btcusdt_1h" / "provider_input.json"
    target_input.write_bytes(study._canonical_bytes(other_payload))
    target_report = output / "datasets" / "btcusdt_1h" / "run_report.json"
    report = study._load_json(target_report)
    report["input_identity"] = other_payload["input_identity"]
    target_report.write_bytes(study._canonical_bytes(report))
    with pytest.raises(study.FreezeError, match="not derived from adapter rows"):
        study.verify_bundle(output)


def test_source_summary_semantics_are_verified_independently_of_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, source = _run(tmp_path / "source", monkeypatch)
    output = _copy_bundle(source, tmp_path / "forged")
    summary_path = output / "source_summary.csv"
    summary = summary_path.read_bytes()
    summary_path.write_bytes(summary.replace(b"btcusdt_1h", b"btcusdt_9h", 1))
    with pytest.raises(study.FreezeError, match="source summary semantic mismatch"):
        study.verify_bundle(output)


def test_asset_and_timeframe_are_identity_bound() -> None:
    rows, original = study._normalize_frame(_frame("1h"), study._dataset_spec("BTCUSDT", "1h"))
    _, other_asset = study._normalize_frame(_frame("1h"), study._dataset_spec("ETHUSDT", "1h"))
    _, other_timeframe = study._normalize_frame(_frame("4h"), study._dataset_spec("BTCUSDT", "4h"))
    assert rows
    assert original.input_identity != other_asset.input_identity
    assert original.input_identity != other_timeframe.input_identity


def test_dataset_identity_changes_on_source_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _, first_root = _run(tmp_path / "first", monkeypatch)
    frames = _frames()
    frames[("BTCUSDT", "1h")].loc[10, "close"] += 0.25
    second, _, second_root = _run(tmp_path / "second", monkeypatch, frames=frames)
    assert first["dataset_reports"][0]["input_identity"] != second["dataset_reports"][0]["input_identity"]
    assert first["dataset_reports"][0]["dataset_source_identity"] != second["dataset_reports"][0]["dataset_source_identity"]
    assert first_root != second_root


def test_cohort_identity_is_order_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, _, _ = _run(tmp_path, monkeypatch)
    ordered = [
        {
            "dataset_id": report["dataset_id"],
            "dataset_source_identity": report["dataset_source_identity"],
        }
        for report in result["dataset_reports"]
    ]
    reversed_identity = deterministic_hash(
        "trendline_v2_phase_9c1_cohort_source_v1",
        {
            "cohort_contract_id": result["cohort_contract_id"],
            "request_order": list(reversed(ordered)),
        },
    )
    assert reversed_identity != result["cohort_source_identity"]


def test_artifacts_are_canonical_and_manifest_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    verification = study.verify_bundle(output)
    assert verification["decision_id"]
    assert verification["manifest_id"]
    assert len(verification["inventory"]) == 22
    for path in output.rglob("*.json"):
        assert path.read_bytes() == study._canonical_bytes(study._load_json(path))
    manifest = study._load_json(output / "manifest.json")
    assert manifest["manifest_id"] == verification["manifest_id"]


def test_verifier_derives_typed_input_from_each_persisted_raw_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    for spec in study.DATASETS:
        dataset_root = output / "datasets" / spec.dataset_id
        adapter_rows = study._load_json(dataset_root / "adapter_rows.json")
        provider_payload = study._load_json(dataset_root / "provider_input.json")
        rows, provider_input = study._normalize_frame(
            pd.DataFrame(adapter_rows["rows"]), spec
        )
        assert rows == adapter_rows["rows"]
        assert provider_payload == study._provider_input_artifact(provider_input)
    study.verify_bundle(output)


def test_corrected_lineage_binds_superseded_inventory_and_zero_remediation_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _offline_source(tmp_path, monkeypatch)
    result = study.regenerate_offline(source_root=source, output_root=output)
    decision = study._load_json(output / "decision.json")
    manifest = study._load_json(output / "manifest.json")
    assert decision["remediation_source_inventory_sha256"] == study._inventory_digest(
        study._inventory(source)
    )
    assert decision["remediation_network_request_count"] == 0
    assert manifest["remediation_source_inventory_sha256"] == decision[
        "remediation_source_inventory_sha256"
    ]
    assert manifest["remediation_network_request_count"] == 0
    assert result["manifest_id"] == manifest["manifest_id"]


def test_network_audit_and_source_summary_are_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    audit = study._load_json(output / "network_audit.json")
    assert len(audit["requests"]) == 6
    assert [item["request_order"] for item in audit["requests"]] == list(range(1, 7))
    assert all(item["result_status"] == "success" for item in audit["requests"])
    with (output / "source_summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    assert [row["dataset_id"] for row in rows] == [spec.dataset_id for spec in study.DATASETS]


def test_run_reports_are_shadow_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    for spec in study.DATASETS:
        report = study._load_json(output / "datasets" / spec.dataset_id / "run_report.json")
        assert report["network_request_count"] == 1
        assert report["retry_count"] == 0
        assert report["fallback_used"] is False
        assert report["provider_execution_count"] == 0
        assert report["candidate_generation_status"] == "NOT_EXECUTED"


def test_no_provider_viewer_legacy_or_regime_imports() -> None:
    source_path = Path(study.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert all("trendline_family" not in module for module in modules)
    assert all("trendline_v2.provider" not in module for module in modules)
    assert all("regime" not in module.lower() for module in modules)
    assert all("viewer" not in module.lower() for module in modules)
    for forbidden in (
        "discover_trendlines",
        "ConfirmedExtremaPairProvider",
        "run_phase_i_evaluation",
        "CandidateGeometryEvaluator",
    ):
        assert forbidden not in source


def test_provider_factory_is_not_used_by_hermetic_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _authorized(monkeypatch)
    called = False

    def forbidden_factory() -> object:
        nonlocal called
        called = True
        raise AssertionError("real adapter factory must not run in hermetic test")

    adapter = FakeAdapter(_frames())
    study.run_freeze(
        output_root=tmp_path / "freeze",
        adapter_factory=lambda: adapter,
        execute_network=True,
    )
    assert called is False
    assert len(adapter.calls) == 6


def test_source_freeze_has_no_candidate_or_selection_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, output = _run(tmp_path, monkeypatch)
    decision = (output / "decision.json").read_text(encoding="utf-8")
    assert "winner" not in decision
    assert "best family" not in decision
    assert "recommended selector" not in decision
    assert "predictive improvement" not in decision
    assert "trading improvement" not in decision
    assert "production ready" not in decision


def test_read_only_external_verification_is_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    if monkeypatch is None:  # pragma: no cover
        return
    if study.OUTPUT_ROOT.exists():
        if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
            pytest.skip("external evidence verification disabled")
        before = study._inventory(study.OUTPUT_ROOT)
        verified = study.verify_bundle(study.OUTPUT_ROOT)
        after = study._inventory(study.OUTPUT_ROOT)
        assert before == after
        assert verified["inventory_sha256"] == study._inventory_digest(after)
    else:
        pytest.skip("canonical fresh source bundle absent")


def test_external_verification_requires_persisted_row_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not study.OUTPUT_ROOT.exists():
        pytest.skip("canonical fresh source bundle absent")
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external evidence verification disabled")
    before = study._inventory(study.OUTPUT_ROOT)
    forged = _copy_bundle(study.OUTPUT_ROOT, tmp_path / "missing-row-count")
    provider_path = forged / "datasets" / "btcusdt_1h" / "provider_input.json"
    payload = study._load_json(provider_path)
    payload.pop("row_count")
    provider_path.write_bytes(study._canonical_bytes(payload))
    with pytest.raises(study.FreezeError, match="artifact schema"):
        study.verify_bundle(forged)
    assert study._inventory(study.OUTPUT_ROOT) == before


def test_superseded_source_bundle_is_byte_identical_if_present() -> None:
    superseded = Path(
        "/tmp/trendline_v2_phase9c1_fresh_scope_sources_superseded/"
        "20260522_20260701_pre_integrity_remediation"
    )
    if not superseded.exists():
        pytest.skip("superseded source bundle not moved yet")
    before = study._inventory(superseded)
    assert study._inventory_digest(before) == study.SUPERSEDED_SOURCE_INVENTORY_SHA256
    after = study._inventory(superseded)
    assert after == before


def test_pre_row_count_bundle_is_byte_identical_if_present() -> None:
    superseded = Path(
        "/tmp/trendline_v2_phase9c1_fresh_scope_sources_superseded/"
        "20260522_20260701_pre_row_count_remediation"
    )
    if not superseded.exists():
        pytest.skip("pre-row-count bundle not moved yet")
    before = study._inventory(superseded)
    assert study._inventory_digest(before) == study.PRE_ROW_COUNT_SOURCE_INVENTORY_SHA256
    assert study._inventory(superseded) == before
