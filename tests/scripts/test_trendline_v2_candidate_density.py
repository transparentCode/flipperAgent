from __future__ import annotations

import ast
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from apps.trendline_v2_viewer.payload import write_viewer_bundle
from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    ResolvedTrendlineV2Config,
)
from libs.models.trendline_v2.discovery import (
    ProviderDiagnostics,
    ProviderInput,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
    ExtremaKind,
    confirmed_extrema_anchor_id,
)
from libs.models.trendline_v2.domain.candidates import (
    AnchorRef,
    CandidateEvidence,
    LineCandidate,
)
from libs.models.trendline_v2.domain.enums import LineRole
from libs.models.trendline_v2.domain.geometry import LineGeometry
from libs.models.trendline_v2.domain.identity import canonical_json
from libs.models.trendline_v2.domain.validation import ContractValidationError
from scripts import analyze_trendline_v2_candidate_density as density


UTC = timezone.utc
BASE_TIME = datetime(2025, 8, 1, tzinfo=UTC)
BAR = timedelta(hours=4)


def _foundation_config() -> ResolvedTrendlineV2Config:
    return ResolvedTrendlineV2Config(
        model_name="trendline_v2",
        model_version="v1",
        schema_version=1,
        provenance={
            "model.name": "synthetic-test",
            "model.version": "synthetic-test",
            "model.schema_version": "synthetic-test",
        },
    )


def _provider_config() -> ConfirmedExtremaPairConfig:
    return ConfirmedExtremaPairConfig(**dict(density.BASELINE_VALUES))


def _source_result() -> ProviderResult:
    timestamps = tuple(
        int((BASE_TIME + index * BAR).timestamp() * 1_000_000_000)
        for index in range(density.EXPECTED_ROWS)
    )
    input_data = ProviderInput(
        asset=density.ASSET,
        timeframe=density.TIMEFRAME,
        observed_at=density.SOURCE_END,
        confirmed_through=density.SOURCE_END,
        timestamps=timestamps,
        open=(100.0,) * density.EXPECTED_ROWS,
        high=(101.0,) * density.EXPECTED_ROWS,
        low=(99.0,) * density.EXPECTED_ROWS,
        close=(100.0,) * density.EXPECTED_ROWS,
        volume=(1.0,) * density.EXPECTED_ROWS,
    )
    source_positions = (10, 20)
    confirmation_positions = (11, 21)
    pivot_times = tuple(
        datetime.fromtimestamp(timestamps[index] / 1_000_000_000, tz=UTC)
        for index in source_positions
    )
    confirmation_times = tuple(
        datetime.fromtimestamp(timestamps[index] / 1_000_000_000, tz=UTC)
        for index in confirmation_positions
    )
    anchors = tuple(
        AnchorRef(
            anchor_id=confirmed_extrema_anchor_id(
                asset=density.ASSET,
                timeframe=density.TIMEFRAME,
                extrema_kind=ExtremaKind.LOW,
                source_timestamp=pivot_time,
                confirmation_timestamp=confirmation_time,
                source_price=99.0,
            ),
            pivot_time=pivot_time,
            confirmation_time=confirmation_time,
            price=99.0,
        )
        for pivot_time, confirmation_time in zip(pivot_times, confirmation_times)
    )
    geometry = LineGeometry(
        start_time=anchors[0].pivot_time,
        end_time=anchors[1].pivot_time,
        start_price=anchors[0].price,
        end_price=anchors[1].price,
    )
    evidence = CandidateEvidence(
        anchor_count=2,
        distinct_anchor_timestamps=2,
        anchor_span_seconds=(pivot_times[1] - pivot_times[0]).total_seconds(),
    )
    candidate = LineCandidate.create(
        asset=density.ASSET,
        timeframe=density.TIMEFRAME,
        role=LineRole.SUPPORT,
        geometry=geometry,
        anchors=anchors,
        evidence=evidence,
        observed_at=input_data.observed_at,
        provider_name="confirmed_extrema_pair",
        provider_version="v1",
    )
    provider_evidence = ConfirmedExtremaPairEvidence(
        candidate_id=candidate.candidate_id,
        extrema_kind=ExtremaKind.LOW,
        anchor_source_positions=source_positions,
        confirmation_positions=confirmation_positions,
        validated_intermediate_count=9,
        body_violation_count=0,
    )
    request = ProviderRequest(
        input_data=input_data,
        config=_foundation_config(),
        provider_config=_provider_config(),
    )
    return ProviderResult(
        provider_name="confirmed_extrema_pair",
        provider_version="v1",
        request=request,
        status=ProviderStatus.SUCCESS,
        candidates=(candidate,),
        evidence=(provider_evidence,),
        diagnostics=ProviderDiagnostics(
            candidate_count=1,
            input_row_count=density.EXPECTED_ROWS,
            elapsed_ms=0.0,
        ),
    )


def _write_source_bundle(root: Path) -> None:
    result = _source_result()
    root.mkdir(parents=True)
    provider_path = root / "provider_result.json"
    provider_path.write_bytes(
        (canonical_json(result.to_dict()) + "\n").encode("utf-8")
    )
    write_viewer_bundle(result, root / "viewer_bundle")
    payload = json.loads(
        (root / "viewer_bundle" / "chart_payload.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (root / "viewer_bundle" / "manifest.json").read_text(encoding="utf-8")
    )
    run_report = {
        "schema_version": density.SOURCE_SCHEMA_VERSION,
        "asset": density.ASSET,
        "timeframe": density.TIMEFRAME,
        "market": "binance_usd_m_futures",
        "base_commit": "synthetic",
        "branch": "synthetic",
        "network_request_count": 1,
        "fallback_used": False,
        "provider_config_classification": (
            "SMOKE_ONLY / UNRESOLVED / NOT_PROMOTED / NOT_CANONICAL"
        ),
        "normalized_row_count": density.EXPECTED_ROWS,
        "raw_row_count": density.EXPECTED_ROWS + 1,
        "request_limit": 1000,
        "normalized_first_timestamp": "2025-08-01T00:00:00Z",
        "normalized_last_timestamp": "2025-11-30T20:00:00Z",
        "request_start": "2025-08-01T00:00:00Z",
        "request_end": "2025-12-01T00:00:00Z",
        "provider_result_sha256": density._sha256_file(provider_path),
        "provider_identity": result.provider_identity,
        "provider_contract_identity": result.provider_contract_identity,
        "request_identity": result.request.request_identity,
        "config_identity": result.request.config_identity,
        "provider_input_identity": result.request.input_identity,
        "primary_candidate_count": 1,
        "support_candidate_count": 1,
        "resistance_candidate_count": 0,
        "primary_status": "success",
        "primary_reason": None,
        "snapshot_id": result.to_snapshot().snapshot_id,
        "viewer_payload_id": payload["payload_id"],
        "viewer_bundle_id": manifest["bundle_id"],
        "smoke_only_provider_config": result.request.provider_config.to_dict(),
    }
    (root / "run_report.json").write_bytes(
        (json.dumps(run_report, ensure_ascii=True, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )


@pytest.fixture
def synthetic_source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    _write_source_bundle(root)
    return root


def test_source_bundle_validation_and_boundaries(synthetic_source: Path) -> None:
    audit = density._validate_source_bundle(synthetic_source)
    assert audit["asset"] == density.ASSET
    assert audit["timeframe"] == density.TIMEFRAME
    assert audit["input"]["row_count"] == density.EXPECTED_ROWS
    assert audit["input"]["first_timestamp"] == "2025-08-01T00:00:00Z"
    assert audit["input"]["last_timestamp"] == "2025-11-30T20:00:00Z"


def test_source_hash_tampering_is_rejected(synthetic_source: Path) -> None:
    report_path = synthetic_source / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["provider_result_sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(density.SourceArtifactError, match="provider_result_sha256"):
        density._validate_source_bundle(synthetic_source)


def test_configuration_matrix_is_exact_one_at_a_time() -> None:
    matrix = density.build_configuration_matrix()
    assert len(matrix) == 13
    assert matrix[0]["label"] == "baseline"
    for spec in matrix:
        changed = {
            field
            for field in density.TESTED_FIELDS
            if spec["values"][field] != density.BASELINE_VALUES[field]
        }
        if spec["changed_field"] is None:
            assert not changed
        else:
            assert changed == {spec["changed_field"]}
            assert spec["changed_value"] == spec["values"][spec["changed_field"]]
        assert spec["values"]["max_hypotheses"] == 100_000
        assert spec["values"]["max_output_candidates"] == 10_000


def test_fixed_windows_are_causal_and_exact(synthetic_source: Path) -> None:
    result = density._typed_source_result(
        density._load_json(synthetic_source / "provider_result.json")
    )
    mid = density._window_frame(result.request.input_data, density.WINDOWS[0])
    full = density._window_frame(result.request.input_data, density.WINDOWS[1])
    assert mid.row_count == density.EXPECTED_MID_ROWS
    assert full.row_count == density.EXPECTED_ROWS
    assert mid.observed_at.isoformat() == "2025-10-01T00:00:00+00:00"
    assert full.observed_at.isoformat() == "2025-12-01T00:00:00+00:00"
    assert mid.confirmed_through == mid.observed_at
    assert full.confirmed_through == full.observed_at
    assert mid.frame.index[-1].to_pydatetime() + BAR == mid.confirmed_through
    assert full.frame.index[-1].to_pydatetime() + BAR == full.confirmed_through


def test_history_rows_use_inclusive_physical_lookback_boundaries(
    synthetic_source: Path,
) -> None:
    result = density._typed_source_result(
        density._load_json(synthetic_source / "provider_result.json")
    )
    expected = {
        1_382_400.0: 96,
        2_764_800.0: 192,
        5_270_400.0: 366,
        10_540_800.0: 732,
    }
    for window, timestamps in (
        (density.WINDOWS[0], result.request.input_data.timestamps[:366]),
        (density.WINDOWS[1], result.request.input_data.timestamps),
    ):
        boundary = density._parse_utc(
            window["confirmed_through"], field_name="window.confirmed_through"
        )
        for lookback, count in expected.items():
            assert density._history_row_count(
                timestamps,
                confirmed_through=boundary,
                lookback_duration_seconds=lookback,
            ) == min(count, int(window["row_count"]))


def test_observation_bound_candidate_ids_and_structure_ids() -> None:
    result = _source_result()
    candidate = result.candidates[0]
    earlier = LineCandidate.create(
        asset=candidate.asset,
        timeframe=candidate.timeframe,
        role=candidate.role,
        geometry=candidate.geometry,
        anchors=candidate.anchors,
        evidence=candidate.evidence,
        observed_at=datetime(2025, 10, 1, tzinfo=UTC),
        provider_name=candidate.provider_name,
        provider_version=candidate.provider_version,
    )
    assert earlier.candidate_id != candidate.candidate_id
    assert density.candidate_structure_id(earlier) == density.candidate_structure_id(
        candidate
    )


def test_cross_window_structure_persistence_is_descriptive_and_nonzero() -> None:
    common = {
        "candidate_count_per_bar": 1.0,
        "unique_anchor_count": 3,
    }
    mid = {
        "window": {"name": "mid"},
        "total_candidate_count": 2,
        "support_candidate_count": 1,
        "resistance_candidate_count": 1,
        "_candidate_structure_ids": ("structure-a", "structure-b"),
        **common,
    }
    full = {
        "window": {"name": "full"},
        "total_candidate_count": 2,
        "support_candidate_count": 1,
        "resistance_candidate_count": 1,
        "_candidate_structure_ids": ("structure-b", "structure-c"),
        **common,
    }
    evidence = density._cross_window((mid, full))
    assert evidence["candidate_structure_persistence_ratio"] == 0.5
    assert "candidate_id_persistence_ratio" not in evidence
    assert "observation-bound" in evidence["persistence_definition"]


def test_run_study_has_fixed_execution_count_and_no_ranking_fields(
    synthetic_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, object, object]] = []
    original_discovery = density.discover_trendlines

    def counted_discovery(*args: object, **kwargs: object) -> ProviderResult:
        calls.append((args, kwargs.get("config"), kwargs.get("provider_config")))
        return original_discovery(*args, **kwargs)

    monkeypatch.setattr(density, "discover_trendlines", counted_discovery)
    output = tmp_path / "study"
    paths = density.run_study(source_root=synthetic_source, output_root=output)
    assert set(paths) == {"source_audit", "matrix", "summary", "decision"}
    matrix = json.loads(paths["matrix"].read_text(encoding="utf-8"))
    decision = json.loads(paths["decision"].read_text(encoding="utf-8"))
    assert len(matrix["runs"]) == 28
    assert len(calls) == 28
    assert sum(item["execution_kind"] == "semantic" for item in matrix["runs"]) == 26
    assert sum(item["execution_kind"] == "deterministic_repeat" for item in matrix["runs"]) == 2
    assert decision["determinism_status"]["all_baseline_repeats_match"] is True
    assert decision["determinism_status"]["total_provider_executions"] == 28
    assert decision["PARAMETER_PROMOTION"] == "NOT_AUTHORIZED"
    assert set(decision["tested_fields"]) == set(density.TESTED_FIELDS)
    for evidence in matrix["cross_window_evidence"].values():
        assert "candidate_structure_persistence_ratio" in evidence
        assert "candidate_id_persistence_ratio" not in evidence

    def keys(value: object) -> list[str]:
        if isinstance(value, dict):
            return [key for key in value for _ in (key,)] + [item for child in value.values() for item in keys(child)]
        if isinstance(value, list):
            return [item for child in value for item in keys(child)]
        return []

    assert not {"best", "winner", "recommendation", "recommended", "optimal"}.intersection(
        key.lower() for key in keys(decision)
    )
    run_files = sorted((output / "runs").glob("*.json"))
    assert len(run_files) == 28
    assert all(
        not any(key.startswith("_") for key in json.loads(path.read_text()).keys())
        for path in run_files
    )


def test_outputs_are_canonical_and_existing_output_is_refused(
    synthetic_source: Path, tmp_path: Path
) -> None:
    output = tmp_path / "study"
    density.run_study(source_root=synthetic_source, output_root=output)
    matrix_bytes = (output / "matrix.json").read_bytes()
    matrix = json.loads(matrix_bytes)
    assert matrix_bytes == density._canonical_bytes(matrix)
    with (output / "summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 28
    assert rows == sorted(
        rows,
        key=lambda row: (
            row["configuration_id"],
            row["window"],
            row["execution_kind"],
        ),
    )
    with pytest.raises(FileExistsError):
        density.run_study(source_root=synthetic_source, output_root=output)


def test_script_has_no_network_plotting_or_legacy_imports() -> None:
    path = Path(density.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )
    text = path.read_text(encoding="utf-8")
    assert not any(
        name.startswith(prefix)
        for name in imported
        for prefix in ("requests", "httpx", "urllib", "plotly", "matplotlib")
    )
    assert not any(
        token in text
        for token in (
            "BinanceNativeAdapter",
            "libs.models.trendline_family",
            "libs.trendlines",
            "app.trendlines",
            "RegimeV2",
            "figure.show(",
            "webbrowser.open",
        )
    )


def test_typed_source_reconstruction_rejects_malformed_payload(
    synthetic_source: Path,
) -> None:
    payload = density._load_json(synthetic_source / "provider_result.json")
    payload["request"]["input_data"]["volume"][0] = -1.0
    with pytest.raises((density.SourceArtifactError, ContractValidationError)):
        density._typed_source_result(payload)
