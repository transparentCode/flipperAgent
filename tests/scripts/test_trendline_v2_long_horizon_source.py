from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as RealDecimal
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from scripts import freeze_trendline_v2_long_horizon_source as study


UTC = timezone.utc
CSV_COLUMNS = study.REQUIRED_COLUMNS


def _csv_row(timestamp: datetime, **overrides: str) -> dict[str, str]:
    row = {
        "timestamp": timestamp.isoformat(),
        "open": "9",
        "high": "10",
        "low": "8",
        "close": "9.5",
        "volume": "1.25",
        "taker_buy_base": "0.5",
        "complete": "True",
    }
    row.update(overrides)
    return row


def _write_csv(path: Path, rows: list[dict[str, str]], *, columns=CSV_COLUMNS) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _small_spec(path: Path, row_count: int = 2) -> study.ComponentSpec:
    start = datetime(2025, 8, 1, tzinfo=UTC)
    rows = [
        _csv_row(start + timedelta(seconds=study.INTERVAL_SECONDS * index))
        for index in range(row_count)
    ]
    _write_csv(path, rows)
    return study.ComponentSpec(
        component_id="synthetic",
        source_path=path,
        output_name="synthetic.csv",
        expected_sha256="0" * 64,
        expected_rows=row_count,
        expected_first=start,
        expected_last=start + timedelta(seconds=study.INTERVAL_SECONDS * (row_count - 1)),
        usage_status="test",
    )


def _rebind_manifest(root: Path) -> None:
    manifest = study._load_json(root / "manifest.json")
    members = study._inventory(root, exclude={"manifest.json"})
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_id"
    }
    payload["members"] = members
    payload["member_inventory_sha256"] = study._inventory_digest(members)
    rebound = {
        **payload,
        "manifest_id": study.deterministic_hash(study.MANIFEST_NAMESPACE, payload),
    }
    study._write_json(root / "manifest.json", rebound)


@pytest.fixture(scope="module")
def frozen_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    previous = os.environ.get(study.FREEZE_ENV)
    os.environ[study.FREEZE_ENV] = "1"
    try:
        root = tmp_path_factory.mktemp("long-horizon") / "bundle"
        study.freeze_source(output_root=root, cli_flag=True)
        return root
    finally:
        if previous is None:
            os.environ.pop(study.FREEZE_ENV, None)
        else:
            os.environ[study.FREEZE_ENV] = previous


def test_exact_contract_payload_and_identity() -> None:
    payload = study._contract_payload()
    assert payload["schema_version"] == study.SOURCE_CONTRACT_SCHEMA
    assert payload["asset"] == "BTCUSDT"
    assert payload["timeframe"] == "4h"
    assert payload["expected_row_count"] == 1458
    assert payload["interval_seconds"] == 14400
    assert study._source_contract_id(payload) == study.EXPECTED_CONTRACT_ID
    assert study._source_contract_document()["source_contract_id"] == study.EXPECTED_CONTRACT_ID


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda p: p["component_sources"][0].__setitem__("sha256", "f" * 64), id="hash"),
        pytest.param(lambda p: p.__setitem__("expected_row_count", 1457), id="row-count"),
        pytest.param(lambda p: p.__setitem__("source_start", "2025-08-02T00:00:00Z"), id="date"),
        pytest.param(lambda p: p.__setitem__("downstream_trial_artifacts", "admitted"), id="quarantine-status"),
    ],
)
def test_contract_identity_changes_for_owned_mutation(mutation) -> None:
    payload = deepcopy(study._contract_payload())
    mutation(payload)
    assert study._source_contract_id(payload) != study.EXPECTED_CONTRACT_ID


@pytest.mark.parametrize(
    ("cli_flag", "environment"),
    [(False, "1"), (True, None), (False, None)],
)
def test_dual_generation_guard_refuses_before_source_read(
    cli_flag: bool,
    environment: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if environment is None:
        monkeypatch.delenv(study.FREEZE_ENV, raising=False)
    else:
        monkeypatch.setenv(study.FREEZE_ENV, environment)
    monkeypatch.setattr(
        study,
        "_source_fingerprints",
        lambda: pytest.fail("source read before generation guard"),
    )
    with pytest.raises(study.FreezeError, match="freeze requires"):
        study.freeze_source(output_root=tmp_path / "bundle", cli_flag=cli_flag)


def test_existing_output_refused_before_source_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    monkeypatch.setenv(study.FREEZE_ENV, "1")
    monkeypatch.setattr(
        study,
        "_source_fingerprints",
        lambda: pytest.fail("source read before output guard"),
    )
    with pytest.raises(FileExistsError):
        study.freeze_source(output_root=output, cli_flag=True)


def test_source_hash_drift_rejected_before_parse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(study.FREEZE_ENV, "1")
    mutated = (
        replace(study.COMPONENTS[0], expected_sha256="f" * 64),
        *study.COMPONENTS[1:],
    )
    monkeypatch.setattr(study, "COMPONENTS", mutated)
    monkeypatch.setattr(
        study,
        "_build_source_data",
        lambda: pytest.fail("source parsing started before hash gate"),
    )
    with pytest.raises(study.FreezeError, match="source component hash mismatch"):
        study.freeze_source(output_root=tmp_path / "bundle", cli_flag=True)


def test_exact_header_accepted(tmp_path: Path) -> None:
    spec = _small_spec(tmp_path / "source.csv")
    assert len(study._parse_component(spec.source_path, spec)) == 2


def test_header_reordering_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    spec = _small_spec(path)
    rows = [
        _csv_row(datetime(2025, 8, 1, tzinfo=UTC) + timedelta(hours=4 * index))
        for index in range(2)
    ]
    _write_csv(path, rows, columns=("open", "timestamp", *CSV_COLUMNS[2:]))
    with pytest.raises(study.FreezeError, match="exact header"):
        study._parse_component(path, spec)


def test_missing_column_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    spec = _small_spec(path)
    rows = [
        {key: value for key, value in _csv_row(datetime(2025, 8, 1, tzinfo=UTC)).items() if key != "volume"},
        {key: value for key, value in _csv_row(datetime(2025, 8, 1, 4, tzinfo=UTC)).items() if key != "volume"},
    ]
    _write_csv(path, rows, columns=tuple(key for key in CSV_COLUMNS if key != "volume"))
    with pytest.raises(study.FreezeError, match="exact header"):
        study._parse_component(path, spec)


@pytest.mark.parametrize(
    "timestamps",
    [
        (datetime(2025, 8, 1, tzinfo=UTC), datetime(2025, 8, 1, tzinfo=UTC)),
        (datetime(2025, 8, 1, tzinfo=UTC), datetime(2025, 8, 1, 8, tzinfo=UTC)),
        (datetime(2025, 8, 1, 4, tzinfo=UTC), datetime(2025, 8, 1, tzinfo=UTC)),
    ],
)
def test_duplicate_missing_or_out_of_order_timestamp_rejected(
    timestamps: tuple[datetime, datetime],
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.csv"
    rows = [_csv_row(value) for value in timestamps]
    _write_csv(path, rows)
    spec = study.ComponentSpec(
        component_id="synthetic",
        source_path=path,
        output_name="synthetic.csv",
        expected_sha256="0" * 64,
        expected_rows=2,
        expected_first=timestamps[0],
        expected_last=timestamps[-1],
        usage_status="test",
    )
    with pytest.raises(study.FreezeError):
        study._parse_component(path, spec)


def test_overlapping_components_rejected() -> None:
    start = datetime(2025, 8, 1, tzinfo=UTC)
    first = [study._parse_row(_csv_row(start + timedelta(hours=4 * i)), line_number=i + 2) for i in range(2)]
    second = [study._parse_row(_csv_row(start + timedelta(hours=4 * i)), line_number=i + 2) for i in range(1, 3)]
    with pytest.raises(study.FreezeError):
        study._validate_combined(first + second)


def test_noncontiguous_components_rejected() -> None:
    start = datetime(2025, 8, 1, tzinfo=UTC)
    rows = [
        study._parse_row(_csv_row(start), line_number=2),
        study._parse_row(_csv_row(start + timedelta(hours=4)), line_number=3),
        study._parse_row(_csv_row(start + timedelta(hours=12)), line_number=4),
    ]
    with pytest.raises(study.FreezeError):
        study._validate_combined(rows)


def test_incomplete_row_rejected(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    start = datetime(2025, 8, 1, tzinfo=UTC)
    rows = [
        _csv_row(start, complete="False"),
        _csv_row(start + timedelta(hours=4)),
    ]
    _write_csv(path, rows)
    spec = study.ComponentSpec(
        component_id="synthetic",
        source_path=path,
        output_name="synthetic.csv",
        expected_sha256="0" * 64,
        expected_rows=2,
        expected_first=start,
        expected_last=start + timedelta(hours=4),
        usage_status="test",
    )
    with pytest.raises(study.FreezeError, match="incomplete"):
        study._parse_component(path, spec)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("open", "NaN", "non-finite"),
        ("high", "Infinity", "non-finite"),
        ("volume", "-1", "negative volume"),
        ("taker_buy_base", "-1", "negative taker_buy_base"),
        ("high", "7", "high below low"),
        ("open", "11", "open outside"),
        ("close", "7", "close outside"),
    ],
)
def test_numeric_and_candle_validation(field: str, value: str, message: str) -> None:
    row = _csv_row(datetime(2025, 8, 1, tzinfo=UTC), **{field: value})
    with pytest.raises(study.FreezeError, match=message):
        study._parse_row(row, line_number=2)


def test_decimal_conversion_occurs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def counting_decimal(value: str) -> RealDecimal:
        nonlocal calls
        calls += 1
        return RealDecimal(value)

    monkeypatch.setattr(study, "Decimal", counting_decimal)
    study._parse_row(_csv_row(datetime(2025, 8, 1, tzinfo=UTC)), line_number=2)
    assert calls == 6


def test_json_reload_preserves_provider_input_identity() -> None:
    start = datetime(2025, 8, 1, tzinfo=UTC)
    rows = [
        study._parse_row(
            _csv_row(
                start + timedelta(hours=4 * index),
                open="9.0000000000000001",
                close="9.9999999999999999",
            ),
            line_number=index + 2,
        )
        for index in range(2)
    ]
    value = study._provider_input(rows)
    payload = study._provider_input_artifact(value)
    assert study._provider_input_from_dict(payload) == value
    assert study._provider_input_from_dict(payload).input_identity == value.input_identity


def test_source_and_component_bytes_are_unchanged(frozen_bundle: Path) -> None:
    for spec in study.COMPONENTS:
        source = spec.source_path.read_bytes()
        copied = (frozen_bundle / "components" / spec.output_name).read_bytes()
        assert hashlib.sha256(source).hexdigest() == spec.expected_sha256
        assert copied == source


def test_bundle_has_canonical_json_csv_and_eight_members(frozen_bundle: Path) -> None:
    provider_path = frozen_bundle / "provider_input.json"
    payload = study._load_json(provider_path)
    assert provider_path.read_bytes() == study._canonical_bytes(payload)
    assert (frozen_bundle / "source_summary.csv").read_bytes().startswith(
        (",".join(study.SUMMARY_COLUMNS) + "\n").encode()
    )
    manifest = study._load_json(frozen_bundle / "manifest.json")
    assert manifest["member_count"] == 8
    assert len(manifest["members"]) == 8
    assert len(study._inventory(frozen_bundle)) == 9
    for path in sorted(frozen_bundle.rglob("*.json")):
        payload = study._load_json(path)
        assert path.read_bytes() == study._canonical_bytes(payload)


def test_pretty_printed_manifest_is_rejected(
    frozen_bundle: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "pretty"
    shutil.copytree(frozen_bundle, root)
    manifest = study._load_json(root / "manifest.json")
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(study.FreezeError, match="non-canonical JSON"):
        study.verify_bundle(output_root=root)


def test_reordered_decision_with_rebound_manifest_is_rejected(
    frozen_bundle: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "reordered-decision"
    shutil.copytree(frozen_bundle, root)
    decision = study._load_json(root / "decision.json")
    reordered = dict(reversed(tuple(decision.items())))
    (root / "decision.json").write_text(
        json.dumps(reordered, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _rebind_manifest(root)
    with pytest.raises(study.FreezeError, match="non-canonical JSON"):
        study.verify_bundle(output_root=root)


def test_whitespace_modified_provider_input_with_rebound_manifest_is_rejected(
    frozen_bundle: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "whitespace-provider-input"
    shutil.copytree(frozen_bundle, root)
    payload = study._load_json(root / "provider_input.json")
    (root / "provider_input.json").write_text(
        json.dumps(payload, separators=(", ", ": ")) + "\n",
        encoding="utf-8",
    )
    _rebind_manifest(root)
    with pytest.raises(study.FreezeError, match="non-canonical JSON"):
        study.verify_bundle(output_root=root)


def test_atomic_publication_uses_single_directory_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    previous = os.environ.get(study.FREEZE_ENV)
    os.environ[study.FREEZE_ENV] = "1"
    calls: list[tuple[Path, Path]] = []
    original_replace = study.os.replace

    def recording_replace(source: str | bytes | os.PathLike, destination: str | bytes | os.PathLike) -> None:
        calls.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(study.os, "replace", recording_replace)
    try:
        study.freeze_source(output_root=tmp_path / "bundle", cli_flag=True)
    finally:
        if previous is None:
            os.environ.pop(study.FREEZE_ENV, None)
        else:
            os.environ[study.FREEZE_ENV] = previous
    assert len(calls) == 1


def test_forged_provider_input_rejected_after_manifest_rebinding(
    frozen_bundle: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "forged"
    shutil.copytree(frozen_bundle, root)
    payload = study._load_json(root / "provider_input.json")
    payload["input_identity"] = "f" * 64
    study._write_json(root / "provider_input.json", payload)
    _rebind_manifest(root)
    with pytest.raises(study.FreezeError, match="ProviderInput identity mismatch"):
        study.verify_bundle(output_root=root)


def test_forged_quarantine_rejected_after_manifest_rebinding(
    frozen_bundle: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "forged"
    shutil.copytree(frozen_bundle, root)
    notice = study._load_json(root / "quarantine_notice.json")
    notice["status"] = "ADMITTED"
    study._write_json(root / "quarantine_notice.json", notice)
    _rebind_manifest(root)
    with pytest.raises(study.FreezeError, match="quarantine notice mismatch"):
        study.verify_bundle(output_root=root)


def test_verifier_is_provider_free_and_reports_zero_execution(frozen_bundle: Path) -> None:
    source = Path(study.__file__).read_text(encoding="utf-8")
    assert "binance_native" not in source
    assert "discover_trendlines" not in source
    assert "select_trendline" not in source
    assert "track_trendline" not in source
    assert "pandas" not in source
    result = study.verify_bundle(output_root=frozen_bundle)
    assert result["provider_execution_count"] == 0
    assert result["network_request_count"] == 0


def test_decision_contains_eviction_readiness_fields(frozen_bundle: Path) -> None:
    decision = study._load_json(frozen_bundle / "decision.json")
    assert decision["study_status"] == "LONG_HORIZON_SOURCE_READY_FOR_EVICTION_REPLAY"
    assert decision["asset"] == "BTCUSDT"
    assert decision["timeframe"] == "4h"
    assert decision["component_count"] == 2
    assert decision["row_count"] == 1458
    assert decision["gap_count"] == 0
    assert decision["duplicate_timestamp_count"] == 0
    assert decision["incomplete_row_count"] == 0
    assert decision["source_duration_days"] == 243
    assert decision["provider_lookback_days"] == 122
    assert decision["lookback_eviction_observable"] is True
    assert decision["provider_execution_count"] == 0
    assert decision["network_request_count"] == 0


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="requires the verified external Phase 10C.1 bundle",
)
def test_external_bundle_matches_verified_long_horizon_source() -> None:
    result = study.verify_bundle()
    assert result == {
        "study_status": "LONG_HORIZON_SOURCE_READY_FOR_EVICTION_REPLAY",
        "source_contract_id": (
            "136215cc9d14b471eac40439dad143987e1738ae4b7365307bc87a2f0c752eae"
        ),
        "provider_input_identity": (
            "6397fc215f0c9d2fc7c6cdf1fe44e60e5530d7fef2c040cce2731661a5657a4c"
        ),
        "decision_id": (
            "086d502cf29ea0d41bae42ecf776749540750bce81bfafd129407a65909eab1a"
        ),
        "manifest_id": (
            "5b8876f61aef2adcc00a0f3c4f22c6ee8bad83bc9bd27fd7ccff58c1fc8ff9a9"
        ),
        "output_inventory_sha256": (
            "872bffa5aa232bfbeac2788c4575a8e73b344476c75cfedb67b8014bc82b550f"
        ),
        "member_count": 8,
        "component_count": 2,
        "row_count": 1458,
        "provider_execution_count": 0,
        "network_request_count": 0,
    }
    for spec in study.COMPONENTS:
        source = spec.source_path.read_bytes()
        copied = (study.OUTPUT_ROOT / "components" / spec.output_name).read_bytes()
        assert hashlib.sha256(source).hexdigest() == spec.expected_sha256
        assert hashlib.sha256(copied).hexdigest() == spec.expected_sha256
        assert copied == source
