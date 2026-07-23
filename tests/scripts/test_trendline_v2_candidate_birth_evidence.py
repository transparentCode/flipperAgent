from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

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
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.provider_input import ProviderInput
from scripts import analyze_trendline_v2_candidate_birth_evidence as birth


UTC = timezone.utc
BASE_TIME = datetime(2025, 1, 1, tzinfo=UTC)
BAR = timedelta(hours=4)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((canonical_json(value) + "\n").encode("utf-8"))


def _synthetic_input() -> ProviderInput:
    row_count = 48
    timestamps = tuple(
        int((BASE_TIME + index * BAR).timestamp() * birth.NANOSECONDS)
        for index in range(row_count)
    )
    opens = [100.0] * row_count
    closes = [100.0] * row_count
    highs = [101.0] * row_count
    lows = [99.0] * row_count
    lows[5] = 90.0
    lows[10] = 95.0
    highs[15] = 110.0
    highs[20] = 105.0
    return ProviderInput(
        asset="SYNTHETIC",
        timeframe="4h",
        observed_at=BASE_TIME + row_count * BAR,
        confirmed_through=BASE_TIME + row_count * BAR,
        timestamps=timestamps,
        open=tuple(opens),
        high=tuple(highs),
        low=tuple(lows),
        close=tuple(closes),
        volume=(1.0,) * row_count,
    )


def _make_candidate(
    input_data: ProviderInput,
    *,
    role: LineRole,
    source_positions: tuple[int, int],
    prices: tuple[float, float],
) -> tuple[LineCandidate, ConfirmedExtremaPairEvidence]:
    kind = ExtremaKind.LOW if role is LineRole.SUPPORT else ExtremaKind.HIGH
    confirmation_positions = tuple(position + 1 for position in source_positions)
    anchors = tuple(
        AnchorRef(
            anchor_id=confirmed_extrema_anchor_id(
                asset=input_data.asset,
                timeframe=input_data.timeframe,
                extrema_kind=kind,
                source_timestamp=datetime.fromtimestamp(
                    input_data.timestamps[source] / birth.NANOSECONDS,
                    tz=UTC,
                ),
                confirmation_timestamp=datetime.fromtimestamp(
                    input_data.timestamps[confirmation] / birth.NANOSECONDS,
                    tz=UTC,
                ),
                source_price=price,
            ),
            pivot_time=datetime.fromtimestamp(
                input_data.timestamps[source] / birth.NANOSECONDS,
                tz=UTC,
            ),
            confirmation_time=datetime.fromtimestamp(
                input_data.timestamps[confirmation] / birth.NANOSECONDS,
                tz=UTC,
            ),
            price=price,
        )
        for source, confirmation, price in zip(
            source_positions, confirmation_positions, prices
        )
    )
    geometry = LineGeometry(
        start_time=anchors[0].pivot_time,
        end_time=anchors[1].pivot_time,
        start_price=prices[0],
        end_price=prices[1],
    )
    evidence = CandidateEvidence(
        anchor_count=2,
        distinct_anchor_timestamps=2,
        anchor_span_seconds=(
            anchors[1].pivot_time - anchors[0].pivot_time
        ).total_seconds(),
    )
    candidate = LineCandidate.create(
        asset=input_data.asset,
        timeframe=input_data.timeframe,
        role=role,
        geometry=geometry,
        anchors=anchors,
        evidence=evidence,
        observed_at=input_data.observed_at,
        provider_name="confirmed_extrema_pair",
        provider_version="v1",
    )
    provider_evidence = ConfirmedExtremaPairEvidence(
        candidate_id=candidate.candidate_id,
        extrema_kind=kind,
        anchor_source_positions=source_positions,
        confirmation_positions=confirmation_positions,
        validated_intermediate_count=source_positions[1] - source_positions[0] - 1,
        body_violation_count=0,
    )
    return candidate, provider_evidence


@pytest.fixture
def synthetic_bundle(tmp_path: Path):
    source_root = tmp_path / "source"
    phase9a_root = tmp_path / "phase9a"
    _write_json(source_root / "source.json", {"kind": "synthetic-source"})
    _write_json(source_root / "nested" / "metadata.json", {"version": 1})
    _write_json(phase9a_root / "matrix.json", {"kind": "synthetic-matrix"})
    _write_json(phase9a_root / "runs" / "run.json", {"kind": "synthetic-run"})
    (phase9a_root / "summary.csv").write_text("kind\nsynthetic\n", encoding="utf-8")

    input_data = _synthetic_input()
    support, support_evidence = _make_candidate(
        input_data,
        role=LineRole.SUPPORT,
        source_positions=(5, 10),
        prices=(90.0, 95.0),
    )
    resistance, resistance_evidence = _make_candidate(
        input_data,
        role=LineRole.RESISTANCE,
        source_positions=(15, 20),
        prices=(110.0, 105.0),
    )
    source_inventory = birth._artifact_inventory(source_root)
    phase9a_inventory = birth._artifact_inventory(phase9a_root)
    binding = birth.StudyBinding(
        source_identity="s" * 64,
        phase9a_study_id="a" * 64,
        phase9a_matrix_id="b" * 64,
        phase9a_decision_id="c" * 64,
        source_inventory_sha256=birth._inventory_digest(source_inventory),
        phase9a_inventory_sha256=birth._inventory_digest(phase9a_inventory),
        expected_candidate_count=2,
        expected_support_count=1,
        expected_resistance_count=1,
    )
    context = (
        {
            "source_audit": {
                "source_identity": binding.source_identity,
                "source_files": source_inventory,
            },
            "phase9a": {
                "study_id": binding.phase9a_study_id,
                "matrix_id": binding.phase9a_matrix_id,
                "decision_id": binding.phase9a_decision_id,
                "files": phase9a_inventory,
            },
        },
        input_data,
        (resistance, support),
        (resistance_evidence, support_evidence),
    )
    return {
        "source_root": source_root,
        "phase9a_root": phase9a_root,
        "output_root": tmp_path / "output",
        "input_data": input_data,
        "candidates": (resistance, support),
        "evidence": (resistance_evidence, support_evidence),
        "binding": binding,
        "context": context,
    }


@pytest.fixture
def synthetic_run(synthetic_bundle):
    paths = birth.run_study(
        source_root=synthetic_bundle["source_root"],
        phase9a_root=synthetic_bundle["phase9a_root"],
        output_root=synthetic_bundle["output_root"],
        _binding=synthetic_bundle["binding"],
        _context_override=synthetic_bundle["context"],
    )
    return synthetic_bundle, paths


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert path.read_bytes() == (canonical_json(value) + "\n").encode("utf-8")
    return value


def _inventory(root: Path) -> dict[str, tuple[int, str]]:
    return {
        str(path.relative_to(root)): (
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _record_map(synthetic_bundle):
    input_data = synthetic_bundle["input_data"]
    extrema = birth._reconstruct_extrema(input_data)
    return {
        candidate.candidate_id: birth.build_candidate_record(
            candidate,
            evidence,
            input_data,
            extrema,
        )
        for candidate, evidence in zip(
            synthetic_bundle["candidates"], synthetic_bundle["evidence"]
        )
    }


def _mutate_input(input_data: ProviderInput, position: int, **updates) -> ProviderInput:
    arrays = {
        name: list(getattr(input_data, name))
        for name in ("open", "high", "low", "close", "volume")
    }
    for name, value in updates.items():
        arrays[name][position] = value
    return replace(
        input_data,
        **{name: tuple(values) for name, values in arrays.items()},
    )


def test_hermetic_run_uses_synthetic_source_and_phase9a_fixtures(synthetic_run) -> None:
    bundle, _paths = synthetic_run
    source_audit = _load_json(bundle["output_root"] / "source_audit.json")
    manifest = _load_json(bundle["output_root"] / "manifest.json")
    records = _load_json(bundle["output_root"] / "candidate_records.json")["records"]
    assert len(records) == 2
    assert [record["role"] for record in records] == ["resistance", "support"]
    assert source_audit["source_inventory_sha256"] == bundle["binding"].source_inventory_sha256
    assert source_audit["phase9a_inventory_sha256"] == bundle["binding"].phase9a_inventory_sha256
    assert source_audit["post_run_source_inventory_sha256"] == source_audit["source_inventory_sha256"]
    assert source_audit["post_run_phase9a_inventory_sha256"] == source_audit["phase9a_inventory_sha256"]
    assert source_audit["source_immutability_verified"] is True
    assert manifest["source_inventory_sha256"] == source_audit["source_inventory_sha256"]


def test_exact_recursive_inventory_and_canonical_json_binding(synthetic_bundle) -> None:
    source_root = synthetic_bundle["source_root"]
    inventory = birth._artifact_inventory(source_root)
    assert [item["path"] for item in inventory] == [
        "nested/metadata.json",
        "source.json",
    ]
    assert birth._inventory_digest(inventory) == synthetic_bundle["binding"].source_inventory_sha256
    with pytest.raises(birth.StudyArtifactError, match="canonical JSON"):
        (source_root / "source.json").write_text('{ "changed": true }\n', encoding="utf-8")
        birth._validate_canonical_json_tree(source_root)


def test_phase9a_inventory_change_is_rejected_before_analysis(synthetic_bundle) -> None:
    summary = synthetic_bundle["phase9a_root"] / "summary.csv"
    summary.write_text("kind\nchanged\n", encoding="utf-8")
    with pytest.raises(birth.StudyArtifactError, match="inventory SHA-256"):
        birth.run_study(
            source_root=synthetic_bundle["source_root"],
            phase9a_root=synthetic_bundle["phase9a_root"],
            output_root=synthetic_bundle["output_root"],
            _binding=synthetic_bundle["binding"],
            _context_override=synthetic_bundle["context"],
        )


def test_post_run_source_mutation_is_rejected(monkeypatch, synthetic_bundle) -> None:
    original = birth._write_json
    mutated = False

    def write_then_mutate(path: Path, value: object) -> None:
        nonlocal mutated
        original(path, value)
        if not mutated and path.name == "decision.json":
            mutated = True
            source = synthetic_bundle["source_root"] / "source.json"
            _write_json(source, {"mutated": True})

    monkeypatch.setattr(birth, "_write_json", write_then_mutate)
    with pytest.raises(birth.StudyArtifactError, match="source changed"):
        birth.run_study(
            source_root=synthetic_bundle["source_root"],
            phase9a_root=synthetic_bundle["phase9a_root"],
            output_root=synthetic_bundle["output_root"],
            _binding=synthetic_bundle["binding"],
            _context_override=synthetic_bundle["context"],
        )


def test_output_root_is_atomic_and_existing_output_is_refused(synthetic_run) -> None:
    bundle, _paths = synthetic_run
    with pytest.raises(FileExistsError):
        birth.run_study(
            source_root=bundle["source_root"],
            phase9a_root=bundle["phase9a_root"],
            output_root=bundle["output_root"],
            _binding=bundle["binding"],
            _context_override=bundle["context"],
        )
    manifest = _load_json(bundle["output_root"] / "manifest.json")
    manifest_semantics = dict(manifest)
    manifest_id = manifest_semantics.pop("manifest_id")
    assert deterministic_hash("trendline_v2_phase_9b1_manifest", manifest_semantics) == manifest_id
    for member in manifest["members"]:
        path = bundle["output_root"] / member["path"]
        assert path.stat().st_size == member["byte_length"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == member["sha256"]


def test_source_and_phase9a_bytes_remain_unchanged(synthetic_run) -> None:
    bundle, _paths = synthetic_run
    assert _inventory(bundle["source_root"])
    assert _inventory(bundle["phase9a_root"])
    source_audit = _load_json(bundle["output_root"] / "source_audit.json")
    assert source_audit["source_immutability_verified"] is True


def test_candidate_structure_identity_excludes_observed_at(synthetic_bundle) -> None:
    candidate = synthetic_bundle["candidates"][1]
    shifted = LineCandidate.create(
        asset=candidate.asset,
        timeframe=candidate.timeframe,
        role=candidate.role,
        geometry=candidate.geometry,
        anchors=candidate.anchors,
        evidence=candidate.evidence,
        observed_at=candidate.observed_at + BAR,
        provider_name=candidate.provider_name,
        provider_version=candidate.provider_version,
    )
    assert shifted.candidate_id != candidate.candidate_id
    assert birth.candidate_structure_id(shifted) == birth.candidate_structure_id(candidate)
    assert birth.candidate_structure_id(candidate) == deterministic_hash(
        birth.STRUCTURE_NAMESPACE,
        {
            "asset": candidate.asset,
            "timeframe": candidate.timeframe,
            "role": candidate.role.value,
            "geometry": candidate.geometry.to_dict(),
            "anchors": [anchor.to_dict() for anchor in candidate.anchors],
            "evidence": candidate.evidence.to_dict(),
            "provider_name": candidate.provider_name,
            "provider_version": candidate.provider_version,
        },
    )


def test_candidate_record_ordering_and_population(synthetic_run) -> None:
    bundle, _paths = synthetic_run
    records = _load_json(bundle["output_root"] / "candidate_records.json")["records"]
    keys = [
        (
            record["role"],
            record["first_anchor_time"],
            record["second_anchor_time"],
            record["candidate_structure_id"],
            record["candidate_id"],
        )
        for record in records
    ]
    assert keys == sorted(keys)
    assert len({record["candidate_id"] for record in records}) == 2
    assert len({record["candidate_structure_id"] for record in records}) == 2


def test_availability_and_span_semantics(synthetic_bundle) -> None:
    input_data = synthetic_bundle["input_data"]
    record = _record_map(synthetic_bundle)[synthetic_bundle["candidates"][1].candidate_id]
    evidence = synthetic_bundle["evidence"][1]
    last_confirmation = max(evidence.confirmation_positions)
    open_time = datetime.fromtimestamp(
        input_data.timestamps[last_confirmation] / birth.NANOSECONDS,
        tz=UTC,
    )
    assert record["confirmation_bar_open"] == birth._iso(open_time)
    assert record["candidate_available_at"] == birth._iso(open_time + BAR)
    assert record["availability_position"] == last_confirmation + 1
    assert record["anchor_span_bars"] == 5
    assert record["anchor_span_seconds"] == 5 * BAR.total_seconds()
    assert record["same_role_extrema_skip_count"] == 0


def test_independent_extrema_plateau_policy_and_buckets() -> None:
    highs = birth.extract_confirmed_extrema((1.0, 3.0, 3.0, 1.0), kind="high")
    lows = birth.extract_confirmed_extrema((3.0, 1.0, 1.0, 3.0), kind="low")
    assert [(item.source_position, item.confirmation_position) for item in highs] == [(1, 2)]
    assert [(item.source_position, item.confirmation_position) for item in lows] == [(1, 2)]
    assert [birth._bucket(value, birth.SPAN_BUCKETS) for value in (2, 6, 7, 12, 13, 48, 49, 96, 97)] == [
        "2-6", "2-6", "7-12", "7-12", "13-24", "25-48", "49-96", "49-96", "97+"
    ]
    assert [birth._bucket(value, birth.SKIP_BUCKETS) for value in (0, 1, 2, 3, 4, 7, 8)] == [
        "0", "1", "2-3", "2-3", "4-7", "4-7", "8+"
    ]


def test_body_clearance_and_prominence_are_birth_only(synthetic_bundle) -> None:
    input_data = synthetic_bundle["input_data"]
    candidate = synthetic_bundle["candidates"][1]
    evidence = synthetic_bundle["evidence"][1]
    record = _record_map(synthetic_bundle)[candidate.candidate_id]
    clearances = []
    for position in range(6, 10):
        projected = candidate.geometry.value_at(
            birth._datetime_from_ns(input_data.timestamps[position])
        )
        clearances.append(
            (min(input_data.open[position], input_data.close[position]) - projected)
            / abs(projected)
            * 10_000.0
        )
    assert record["minimum_body_clearance_bps"] == pytest.approx(min(clearances))
    prominence = []
    for position, anchor in zip(evidence.anchor_source_positions, candidate.anchors):
        raw = min(input_data.low[position - 1], input_data.low[position + 1]) - anchor.price
        prominence.append(raw / abs(anchor.price) * 10_000.0)
    assert record["minimum_anchor_prominence_bps"] == pytest.approx(min(prominence))
    future_position = record["availability_position"]
    mutated = _mutate_input(
        input_data,
        future_position,
        open=50.0,
        close=50.0,
        low=49.0,
        high=51.0,
    )
    mutated_record = birth.build_candidate_record(
        candidate,
        evidence,
        mutated,
        birth._reconstruct_extrema(mutated),
    )
    birth_keys = {key for key in record if key != "evaluations"}
    assert all(mutated_record[key] == record[key] for key in birth_keys)
    assert mutated_record["evaluations"] != record["evaluations"]


@pytest.mark.parametrize("horizon", birth.HORIZONS)
def test_exact_future_horizon_labels(horizon: int, synthetic_bundle) -> None:
    record = _record_map(synthetic_bundle)[synthetic_bundle["candidates"][1].candidate_id]
    evaluation = record["evaluations"][str(horizon)]
    assert evaluation["evaluation_available"] is True
    assert evaluation["has_exact_contact"] == (evaluation["future_contact_count"] > 0)
    assert evaluation["survives_exact_side"] == (
        evaluation["future_body_violation_count"] == 0
    )
    assert evaluation["contact_and_survives_exact_side"] == (
        evaluation["has_exact_contact"] and evaluation["survives_exact_side"]
    )


def test_deterministic_spearman_ties_and_undefined_reasons() -> None:
    assert birth._rankdata((1.0, 1.0, 2.0)) == (1.5, 1.5, 3.0)
    assert birth._spearman((1.0, 1.0), (False, True)) == (None, "feature_constant")
    assert birth._spearman((1.0, 2.0), (True, True)) == (None, "outcome_constant")
    assert birth._spearman((1.0,), (True,)) == (None, "insufficient_evaluation_rows")


def test_no_provider_network_visual_or_legacy_dependency() -> None:
    tree = ast.parse(Path(birth.__file__).read_text(encoding="utf-8"))
    source = Path(birth.__file__).read_text(encoding="utf-8")
    banned = (
        "BinanceNativeAdapter",
        "requests",
        "httpx",
        "plotly",
        "matplotlib",
        "webbrowser",
        "trendline_family",
        "trendlines_old",
        "libs.trendlines",
        "RegimeV2",
    )
    assert not any(token in source for token in banned)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "discover_trendlines"
        for node in ast.walk(tree)
    )


def test_decision_boundary_and_dependence_disclosure(synthetic_run) -> None:
    bundle, _paths = synthetic_run
    decision = _load_json(bundle["output_root"] / "decision.json")
    assert decision["QUALITY_SCORE_SELECTION"] == "NOT_AUTHORIZED"
    assert decision["ELIGIBILITY_RULE_SELECTION"] == "NOT_AUTHORIZED"
    assert decision["PARAMETER_PROMOTION"] == "NOT_AUTHORIZED"
    assert decision["TRACKER_START"] == "NOT_AUTHORIZED"
    assert any("share anchors" in item for item in decision["limitations"])
    text = canonical_json(decision).lower()
    for forbidden in (
        "best",
        "winner",
        "optimal",
        "recommended threshold",
        "top candidates",
        "production ready",
        "predictive",
        "profitable",
    ):
        assert forbidden not in text


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="set TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE=1 for real local evidence",
)
def test_opt_in_external_population_and_binding() -> None:
    context, input_data, candidates, evidence = birth._load_context(
        source_root=birth.SOURCE_ROOT,
        phase9a_root=birth.PHASE9A_ROOT,
    )
    assert context["source_audit"]["source_identity"] == birth.SOURCE_IDENTITY
    assert input_data.row_count == birth.EXPECTED_ROWS
    assert len(candidates) == len(evidence) == birth.EXPECTED_CANDIDATES
    assert sum(candidate.role is LineRole.SUPPORT for candidate in candidates) == birth.EXPECTED_SUPPORT
    assert sum(candidate.role is LineRole.RESISTANCE for candidate in candidates) == birth.EXPECTED_RESISTANCE
