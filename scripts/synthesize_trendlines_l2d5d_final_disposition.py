"""Synthesize final mature-trendlines disposition from committed evidence only."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research.adequacy import (
    TrendlineAdequacyBaselineSpec,
    TrendlineGeometrySensitivityCapsule,
    TrendlineSensitivityDeltaRow,
    TrendlineSensitivityStageDigest,
    build_final_cohort_evidence,
    build_final_disposition_bundle,
    build_final_disposition_protocol,
    build_geometry_sensitivity_protocol,
    build_decision_matrix,
    frozen_geometry_sensitivity_variants,
    validate_final_disposition_bundle,
    validate_geometry_sensitivity_bundle,
)
from libs.models.trendlines.workflows.research.adequacy.baselines import (
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineDataPolicy,
)
from libs.models.trendlines.workflows.research.adequacy.robustness_sources import (
    TrendlineRobustnessSourceMemberEvidence,
    TrendlineRobustnessSourceMemberSpec,
    build_robustness_source_matrix_bundle,
    validate_robustness_source_matrix_bundle,
)


SOURCE_MATRIX_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5a_source_matrix_v1"
)
D5B_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5b_offline_replication_v1"
)
D5C_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5c_geometry_sensitivity_v1"
)
REFERENCE_SOURCE_ROOT = Path(
    "artifacts/trendlines_research_validation/"
    "20260726_btcusdt_1h_single_call_v1"
)
REFERENCE_ROOTS = {
    "d2": Path(
        "artifacts/trendlines_research_adequacy/"
        "20260727_btcusdt_1h_l2d2_structural_stability_v1"
    ),
    "d3": Path(
        "artifacts/trendlines_research_adequacy/"
        "20260727_btcusdt_1h_l2d3_interaction_utility_v1"
    ),
    "d4a": Path(
        "artifacts/trendlines_research_adequacy/"
        "20260727_btcusdt_1h_l2d4a_deterministic_naive_baselines_v1"
    ),
    "d4b": Path(
        "artifacts/trendlines_research_adequacy/"
        "20260727_btcusdt_1h_l2d4b_seeded_stochastic_nulls_v1"
    ),
}
OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_l2d5d_final_disposition_v1"
)
IMPLEMENTATION_BASE_COMMIT = "bd419f38027217a2ea3fdad5e31517f1954ba211"
D5A_ID = "9e324fff3bfce51eadb86fdcc173d75e984064d7eeaccb3d413fc4c8b13e907a"
D5B_PROTOCOL_ID = "b722750e2b4deb627bec302431101e2a7d54b43a886af351d99c3be77819b639"
D5B_ID = "b0eff1ecd259af4193f70d6ada991a3f7ef0e8731bece95ffd02c15045c7da9b"
D5C_PROTOCOL_ID = "f59c285a453138c0c2b09dba9f28911b0a14a776e02be6d4caaa0e0964300e47"
D5C_ID = "26247da3bd7a76a169112c9bb36284fc91c2f5946ef624493d2f3b857cb6acd7"
REFERENCE_IDS = {
    "d2": "f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f",
    "d3": "56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4",
    "d4a": "664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663",
    "d4b": "98f04441c0ef9c643640c78004a875ab6fa6a8de6c797eb1f2e68420910323db",
}
MEMBER_NAMES = (
    "reference-btcusdt-1h-20250101-v1",
    "temporal-btcusdt-1h-20250401-v1",
    "cross-asset-ethusdt-1h-20250401-v1",
    "cross-asset-solusdt-1h-20250401-v1",
    "cross-timeframe-btcusdt-4h-20250401-v1",
)
VARIANT_NAMES = ("dense-geometry-v1", "sparse-geometry-v1")
STAGE_FILE_NAMES = {
    "d2": "structural_stability_bundle.json",
    "d3": "interaction_utility_bundle.json",
    "d4a": "deterministic_baseline_comparison_bundle.json",
    "d4b": "stochastic_null_comparison_bundle.json",
}
D5B_MANIFEST_KEYS = {
    "d2": "structural_stability_bundle",
    "d3": "interaction_utility_bundle",
    "d4a": "deterministic_baseline_comparison_bundle",
    "d4b": "stochastic_null_comparison_bundle",
}
STAGE_ID_KEYS = {
    "d2": "structural_stability_bundle_id",
    "d3": "interaction_utility_bundle_id",
    "d4a": "baseline_comparison_bundle_id",
    "d4b": "stochastic_null_comparison_bundle_id",
}
FINAL_FILES = (
    "final_disposition_bundle.json",
    "cohort_evidence.json",
    "decision_matrix.json",
    "run_manifest.json",
    "review.md",
    "checksums.json",
)


class D5DError(RuntimeError):
    """Raised when committed D5D input or output evidence is invalid."""


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise D5DError(f"cannot load JSON: {path}") from exc
    if not isinstance(value, dict):
        raise D5DError(f"JSON root must be object: {path}")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise D5DError(f"{name} is not lowercase SHA-256")
    return value


def _content_id(payload: Mapping[str, Any], id_key: str, name: str) -> str:
    ident = _sha(payload.get(id_key), name)
    body = dict(payload)
    body.pop(id_key, None)
    semantics = body.get("semantics_version")
    if not isinstance(semantics, str) or not semantics:
        raise D5DError(f"{name} has no semantics version")
    if canonical_hash(body, semantics_version=semantics) != ident:
        raise D5DError(f"{name} content identity differs")
    return ident


def _protocol_id(payload: Mapping[str, Any], id_key: str, name: str) -> str:
    ident = _sha(payload.get(id_key), name)
    body = dict(payload)
    body.pop(id_key, None)
    semantics = body.get("semantics_version")
    if canonical_hash(body, semantics_version=semantics) != ident:
        raise D5DError(f"{name} identity differs")
    return ident


def _verify_checksums(root: Path) -> tuple[dict[str, Any], ...]:
    checksums = _load(root / "checksums.json")
    entries = checksums.get("files")
    if not isinstance(entries, list):
        raise D5DError(f"checksum inventory is not a list: {root}")
    listed = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise D5DError(f"malformed checksum entry: {root}")
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise D5DError(f"unsafe checksum path: {entry['path']}")
        path = root / relative
        if not path.is_file():
            raise D5DError(f"checksum file missing: {path}")
        if path.stat().st_size != entry.get("byte_length"):
            raise D5DError(f"checksum byte length differs: {path}")
        if _sha256(path) != entry.get("sha256"):
            raise D5DError(f"checksum differs: {path}")
        listed.append(entry["path"])
    actual = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "checksums.json"
    )
    if sorted(listed) != actual or len(set(listed)) != len(listed):
        raise D5DError(f"checksum inventory does not cover root: {root}")
    return tuple(entries)


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise D5DError("timestamp must be text")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _d5a_matrix() -> tuple[Any, dict[str, Any]]:
    root = SOURCE_MATRIX_ROOT
    entries = _verify_checksums(root)
    payload = _load(root / "robustness_source_matrix_bundle.json")
    if _content_id(payload, "robustness_source_matrix_bundle_id", "D5A matrix") != D5A_ID:
        raise D5DError("D5A matrix ID differs")
    specs = []
    for raw in payload.get("member_specs", []):
        value = dict(raw)
        value.pop("member_spec_id", None)
        value["event_start"] = _parse_datetime(value["event_start"])
        value["knowledge_cutoff"] = _parse_datetime(value["knowledge_cutoff"])
        spec = TrendlineRobustnessSourceMemberSpec(**value)
        if spec.member_spec_id != raw.get("member_spec_id"):
            raise D5DError(f"D5A member spec ID differs: {spec.name}")
        specs.append(spec)
    evidence = []
    for raw in payload.get("member_evidence", []):
        value = dict(raw)
        value.pop("member_evidence_id", None)
        for name in (
            "first_event_at",
            "last_event_at",
            "first_availability_at",
            "last_availability_at",
        ):
            value[name] = _parse_datetime(value[name])
        row = TrendlineRobustnessSourceMemberEvidence(**value)
        if row.member_evidence_id != raw.get("member_evidence_id"):
            raise D5DError(f"D5A member evidence ID differs: {row.member_spec_id}")
        evidence.append(row)
    matrix = build_robustness_source_matrix_bundle(tuple(specs), tuple(evidence))
    validate_robustness_source_matrix_bundle(matrix)
    if matrix.to_dict() != payload:
        raise D5DError("D5A typed matrix differs from persisted matrix")
    return matrix, {
        "root": str(root),
        "id": D5A_ID,
        "checksums": list(entries),
    }


def _verify_stage_bundle(path: Path, expected_id: str, stage: str) -> dict[str, Any]:
    payload = _load(path)
    if _content_id(payload, STAGE_ID_KEYS[stage], stage) != expected_id:
        raise D5DError(f"{stage} bundle ID differs: {path}")
    return payload


def _verify_reference_chain() -> dict[str, dict[str, Any]]:
    chain = {}
    for stage, root in REFERENCE_ROOTS.items():
        _verify_checksums(root)
        path = root / {
            "d2": "structural_stability_bundle.json",
            "d3": "interaction_utility_bundle.json",
            "d4a": "baseline_comparison_bundle.json",
            "d4b": "stochastic_null_comparison_bundle.json",
        }[stage]
        chain[stage] = _verify_stage_bundle(path, REFERENCE_IDS[stage], stage)
    return chain


def _verify_d5b(matrix: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = D5B_ROOT
    entries = _verify_checksums(root)
    aggregate = _load(root / "robustness_replication_bundle.json")
    if _content_id(aggregate, "robustness_replication_bundle_id", "D5B aggregate") != D5B_ID:
        raise D5DError("D5B aggregate ID differs")
    if aggregate.get("source_matrix_bundle_id") != D5A_ID:
        raise D5DError("D5B source matrix ID differs")
    if aggregate.get("replication_protocol_id") != D5B_PROTOCOL_ID:
        raise D5DError("D5B protocol ID differs")
    protocol = aggregate.get("protocol")
    if not isinstance(protocol, dict) or _protocol_id(
        {**protocol, "replication_protocol_id": aggregate["replication_protocol_id"]},
        "replication_protocol_id",
        "D5B protocol",
    ) != D5B_PROTOCOL_ID:
        raise D5DError("D5B protocol content differs")
    chains: dict[str, dict[str, Any]] = {}
    expected_names = tuple(matrix.member_specs[i].name for i in range(1, len(matrix.member_specs)))
    results = aggregate.get("member_results", [])
    if tuple(row.get("member_name") for row in results) != expected_names:
        raise D5DError("D5B member result order differs")
    for row in results:
        name = row["member_name"]
        result_id = _content_id(row, "member_result_id", f"D5B member result {name}")
        manifest = _load(root / "members" / name / "member_manifest.json")
        if manifest.get("row_counts", {}).get("member_result_id") != result_id:
            raise D5DError(f"D5B manifest result ID differs: {name}")
        for key, filename in STAGE_FILE_NAMES.items():
            path_value = manifest.get("bundle_paths", {}).get(D5B_MANIFEST_KEYS[key])
            if not isinstance(path_value, str):
                raise D5DError(f"D5B manifest omits {key}: {name}")
            bundle = _load(root / path_value)
            expected_stage_id = row[f"{key}_bundle_id"]
            _verify_stage_bundle(root / path_value, expected_stage_id, key)
            if bundle.get("study_config_id") != row.get("study_config_id"):
                raise D5DError(f"D5B {key} study ID differs: {name}")
            chains.setdefault(name, {})[key] = bundle
        chains[name]["member_result"] = row
        chains[name]["manifest"] = manifest
    return {
        "root": str(root),
        "id": D5B_ID,
        "aggregate": aggregate,
        "checksums": list(entries),
        "protocol": protocol,
    }, chains


def _baseline_specs(raw_specs: Any) -> tuple[TrendlineAdequacyBaselineSpec, ...]:
    result = []
    for raw in raw_specs:
        result.append(
            TrendlineAdequacyBaselineSpec(
                name=raw["name"],
                kind=TrendlineAdequacyBaselineKind(raw["kind"]),
                repetitions=raw["repetitions"],
                seed=raw.get("seed"),
                preserves=tuple(raw["preserves"]),
                data_policy=TrendlineAdequacyBaselineDataPolicy(raw["data_policy"]),
            )
        )
    return tuple(result)


def _typed_capsule(raw: Mapping[str, Any]) -> TrendlineGeometrySensitivityCapsule:
    payload = dict(raw)
    ident = payload.pop("geometry_sensitivity_capsule_id")
    payload["stage_digests"] = tuple(
        TrendlineSensitivityStageDigest(**row) for row in payload["stage_digests"]
    )
    payload["delta_rows"] = tuple(
        TrendlineSensitivityDeltaRow(**row) for row in payload["delta_rows"]
    )
    payload["capsule_id"] = ident
    capsule = TrendlineGeometrySensitivityCapsule(**payload)
    if capsule.to_dict() != raw:
        raise D5DError(f"typed D5C capsule differs: {ident}")
    return capsule


def _verify_d5c(matrix: Any, d5b: Mapping[str, Any], d5b_chains: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = D5C_ROOT
    entries = _verify_checksums(root)
    aggregate = _load(root / "geometry_sensitivity_bundle.json")
    if _content_id(aggregate, "geometry_sensitivity_bundle_id", "D5C aggregate") != D5C_ID:
        raise D5DError("D5C aggregate ID differs")
    if aggregate.get("d5a_source_matrix_bundle_id") != D5A_ID or aggregate.get("d5b_replication_bundle_id") != D5B_ID:
        raise D5DError("D5C prior identity differs")
    protocol_payload = dict(aggregate["sensitivity_protocol"])
    protocol_id = _protocol_id(
        protocol_payload,
        "geometry_sensitivity_protocol_id",
        "D5C protocol",
    )
    if protocol_id != D5C_PROTOCOL_ID:
        raise D5DError("D5C protocol ID differs")
    protocol = build_geometry_sensitivity_protocol(
        d5a_source_matrix_bundle_id=protocol_payload["d5a_source_matrix_bundle_id"],
        d5b_replication_protocol_id=protocol_payload["d5b_replication_protocol_id"],
        d5b_replication_bundle_id=protocol_payload["d5b_replication_bundle_id"],
        member_names=tuple(protocol_payload["member_names"]),
        variants=frozen_geometry_sensitivity_variants(),
        deterministic_baseline_ids=tuple(protocol_payload["deterministic_baseline_ids"]),
        stochastic_baseline_specs=_baseline_specs(protocol_payload["stochastic_baseline_specs"]),
    )
    if protocol.to_dict() != protocol_payload:
        raise D5DError("D5C typed protocol differs")
    matrix_rows = {spec.name: (spec, evidence) for spec, evidence in zip(matrix.member_specs, matrix.member_evidence)}
    bindings = {}
    reference_manifest = _load(
        root / "members" / MEMBER_NAMES[0] / "member_manifest.json"
    )
    reference_result_id = reference_manifest["canonical_baseline"]["baseline_member_result_id"]
    for name, (spec, evidence) in matrix_rows.items():
        if name == MEMBER_NAMES[0]:
            result_id = reference_result_id
        else:
            result_id = d5b_chains[name]["member_result"]["member_result_id"]
        bindings[name] = (
            SimpleNamespace(
                member_spec_id=spec.member_spec_id,
                name=spec.name,
                relation=spec.relation,
                asset=spec.asset,
                timeframe=spec.timeframe,
            ),
            SimpleNamespace(
                member_evidence_id=evidence.member_evidence_id,
                source_id=evidence.source_id,
                availability_id=evidence.availability_id,
                dataset_id=evidence.dataset_id,
                research_configuration_id=evidence.research_configuration_id,
                preparation_id=evidence.preparation_id,
            ),
            result_id,
        )
    capsules = []
    by_member: dict[str, dict[str, Any]] = {}
    for capsule_id in aggregate.get("capsule_ids", []):
        matches = [
            row for row in _load(root / "run_manifest.json").get("capsules", [])
            if row.get("capsule_id") == capsule_id
        ]
        if len(matches) != 1:
            raise D5DError(f"D5C capsule manifest binding differs: {capsule_id}")
        path = root / matches[0]["path"]
        raw = _load(path)
        if _content_id(raw, "geometry_sensitivity_capsule_id", "D5C capsule") != capsule_id:
            raise D5DError(f"D5C capsule file ID differs: {path}")
        capsule = _typed_capsule(raw)
        spec, evidence, result_id = bindings[capsule.member_name]
        if capsule.baseline_member_result_id != result_id:
            raise D5DError(f"D5C baseline result binding differs: {capsule.member_name}")
        capsules.append(capsule)
        by_member.setdefault(capsule.member_name, {})[matches[0]["variant"]] = raw
    bundle = __import__(
        "libs.models.trendlines.workflows.research.adequacy.geometry_sensitivity",
        fromlist=["TrendlineGeometrySensitivityBundle"],
    ).TrendlineGeometrySensitivityBundle(
        d5a_source_matrix_bundle_id=D5A_ID,
        d5b_replication_bundle_id=D5B_ID,
        sensitivity_protocol=protocol,
        capsules=tuple(capsules),
        geometry_sensitivity_bundle_id=D5C_ID,
    )
    validate_geometry_sensitivity_bundle(bundle, protocol=protocol, member_bindings=bindings)
    return {
        "root": str(root),
        "id": D5C_ID,
        "aggregate": aggregate,
        "checksums": list(entries),
        "protocol": protocol,
    }, by_member


def _count_inventory(chain: Mapping[str, Any]) -> dict[str, int]:
    return {
        "d2_state_count": len(chain["d2"].get("state_rows", [])),
        "d2_transition_count": len(chain["d2"].get("transition_rows", [])),
        "d2_drift_count": len(chain["d2"].get("drift_rows", [])),
        "d2_episode_count": len(chain["d2"].get("episode_rows", [])),
        "d2_survival_count": len(chain["d2"].get("survival_rows", [])),
        "d2_summary_count": len(chain["d2"].get("summaries", [])),
        "d3_event_count": len(chain["d3"].get("events", [])),
        "d3_outcome_count": len(chain["d3"].get("outcomes", [])),
        "d3_summary_count": len(chain["d3"].get("summaries", [])),
        "d4a_selection_count": len(chain["d4a"].get("baseline_selections", [])),
        "d4a_outcome_count": len(chain["d4a"].get("baseline_outcomes", [])),
        "d4a_comparison_count": len(chain["d4a"].get("comparison_summaries", [])),
        "d4b_selection_count": len(chain["d4b"].get("stochastic_selections", [])),
        "d4b_available_selection_count": sum(bool(row.get("available")) for row in chain["d4b"].get("stochastic_selections", [])),
        "d4b_abstention_count": sum(not bool(row.get("available")) for row in chain["d4b"].get("stochastic_selections", [])),
        "d4b_outcome_count": len(chain["d4b"].get("null_outcomes", [])),
        "d4b_comparison_count": len(chain["d4b"].get("repetition_comparisons", [])),
        "d4b_distribution_count": len(chain["d4b"].get("distribution_summaries", [])),
    }


def _canonical_chain(
    matrix: Any,
    reference_chain: Mapping[str, Any],
    d5b_chains: Mapping[str, Any],
    d5c_by_member: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result = {}
    for index, spec in enumerate(matrix.member_specs):
        name = spec.name
        if index == 0:
            chain = dict(reference_chain)
            result_id = _load(D5C_ROOT / "members" / name / "member_manifest.json")["canonical_baseline"]["baseline_member_result_id"]
            ids = REFERENCE_IDS
        else:
            chain = {key: value for key, value in d5b_chains[name].items() if key in STAGE_FILE_NAMES}
            result_id = d5b_chains[name]["member_result"]["member_result_id"]
            ids = {key: chain[key][STAGE_ID_KEYS[key]] for key in STAGE_FILE_NAMES}
        for key, expected in ids.items():
            field = STAGE_ID_KEYS[key]
            if chain[key].get(field) != expected:
                raise D5DError(f"canonical {key} ID differs: {name}")
        if len(set(chain[key].get("study_config_id") for key in STAGE_FILE_NAMES)) != 1:
            raise D5DError(f"canonical study identity differs: {name}")
        result[name] = {
            "member_name": name,
            "relation": spec.relation,
            "asset": spec.asset,
            "timeframe": spec.timeframe,
            "d5a_member_spec_id": spec.member_spec_id,
            "d5a_member_evidence_id": matrix.member_evidence[index].member_evidence_id,
            "canonical_d2_bundle_id": ids["d2"],
            "canonical_d3_bundle_id": ids["d3"],
            "canonical_d4a_bundle_id": ids["d4a"],
            "canonical_d4b_bundle_id": ids["d4b"],
            "baseline_member_result_id": result_id,
            "d2": chain["d2"],
            "d3": chain["d3"],
            "d4a": chain["d4a"],
            "d4b": chain["d4b"],
            "baseline_count_inventory": _count_inventory(chain),
            "dense_capsule": d5c_by_member[name]["dense-geometry-v1"],
            "sparse_capsule": d5c_by_member[name]["sparse-geometry-v1"],
        }
    return result


def verify_prior_evidence() -> dict[str, Any]:
    """Verify all committed D5A-D5C roots and return synthesis inputs."""

    matrix, d5a_meta = _d5a_matrix()
    reference_chain = _verify_reference_chain()
    d5b_meta, d5b_chains = _verify_d5b(matrix)
    d5c_meta, d5c_capsules = _verify_d5c(matrix, d5b_meta, d5b_chains)
    if tuple(d5c_capsules) != MEMBER_NAMES:
        raise D5DError("D5C member scope differs")
    canonical = _canonical_chain(matrix, reference_chain, d5b_chains, d5c_capsules)
    return {
        "matrix": matrix,
        "d5a_meta": d5a_meta,
        "d5b_meta": d5b_meta,
        "d5b_chains": d5b_chains,
        "d5c_meta": d5c_meta,
        "d5c_capsules": d5c_capsules,
        "canonical": canonical,
        "reference_chain": reference_chain,
    }


def _prior_manifest(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "root": meta["root"],
        "bundle_id": meta["id"],
        "checksums": meta["checksums"],
    }


def _expected_cohort_bindings(canonical: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, str]]:
    fields = (
        "d5a_member_spec_id",
        "d5a_member_evidence_id",
        "canonical_d2_bundle_id",
        "canonical_d3_bundle_id",
        "canonical_d4a_bundle_id",
        "canonical_d4b_bundle_id",
        "baseline_member_result_id",
    )
    return {
        name: {
            **{field: str(row[field]) for field in fields},
            "dense_capsule_id": str(row["dense_capsule"]["geometry_sensitivity_capsule_id"]),
            "sparse_capsule_id": str(row["sparse_capsule"]["geometry_sensitivity_capsule_id"]),
        }
        for name, row in canonical.items()
    }


def _review(bundle: Any, cohorts: list[Any], decision: Mapping[str, Any]) -> str:
    return "\n".join(
        (
            "# L2-D5D Final Mature-Trendlines Research Disposition",
            "",
            "This is the final mature-trendlines research disposition.",
            "No provider call, model execution, replay or parameter trial occurred.",
            "No favourable subset was selected.",
            "All five canonical cohorts and all ten sensitivity capsules were included.",
            "Random-pair and density-matched nulls were evaluated separately.",
            "Decisive comparator: causal-density-matched-null-v1; it is the stronger utility comparator.",
            "UTILITY_NOT_BETTER_THAN_NAIVE_NULL is legacy outcome vocabulary; the decisive failed comparator is the causal density-matched null.",
            "Sensitivity comparisons were treated as different event populations.",
            "The selected outcome followed the frozen decision hierarchy.",
            "No production promotion was authorised.",
            "",
            f"Selected outcome: `{bundle.selected_outcome.value}`.",
            f"Recommended action: `{bundle.recommended_action.value}`.",
            f"Decisive rule: `{decision['first_selected_rule']}`.",
            "",
            "## Evidence axes",
            "",
            *(
                f"- {name}: `{value}`"
                for name, value in bundle.axis_classifications
            ),
            "",
            "## Cohort scope",
            "",
            *(
                f"- {row.member_name}: structure `{row.structural_classification}`, "
                f"random robust-positive cells `{row.random_robust_positive_count}`, "
                f"density robust-positive cells `{row.density_robust_positive_count}`, "
                f"parameter `{ 'robust' if row.parameter_robust else 'fragile' }`."
                for row in cohorts
            ),
            "",
            "## Limitations",
            "",
            *(f"- {value}" for value in bundle.residual_limitations),
            "",
            "Mature trendlines research formally closed: **yes**.",
            "Any redesign, cleanup, merge or production work is a new programme.",
            "",
        )
    )


def _decision_cohort_summaries(cohorts: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "member_name": row.member_name,
            "structural_classification": row.structural_classification,
            "random_null_cells": row.to_dict()["random_null_cells"],
            "density_null_cells": row.to_dict()["density_null_cells"],
            "random_member_support": row.random_member_support,
            "density_member_support": row.density_member_support,
            "parameter_robust": row.parameter_robust,
            "dense_event_overlap": row.to_dict()["dense_event_overlap"],
            "sparse_event_overlap": row.to_dict()["sparse_event_overlap"],
        }
        for row in cohorts
    ]


def _inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "byte_length": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.iterdir())
        if path.name != "checksums.json" and path.is_file()
    ]


def synthesize(output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Run one artifact-only D5D synthesis; refuse existing output roots."""

    output_root = Path(output_root)
    if output_root.exists():
        raise D5DError(f"D5D output root already exists: {output_root}")
    evidence = verify_prior_evidence()
    protocol = build_final_disposition_protocol(
        d5a_source_matrix_bundle_id=D5A_ID,
        d5b_replication_protocol_id=D5B_PROTOCOL_ID,
        d5b_replication_bundle_id=D5B_ID,
        d5c_sensitivity_protocol_id=D5C_PROTOCOL_ID,
        d5c_sensitivity_bundle_id=D5C_ID,
    )
    cohorts = [
        build_final_cohort_evidence(
            canonical=evidence["canonical"][name],
            dense_capsule=evidence["canonical"][name]["dense_capsule"],
            sparse_capsule=evidence["canonical"][name]["sparse_capsule"],
            protocol=protocol,
        )
        for name in MEMBER_NAMES
    ]
    bundle = build_final_disposition_bundle(protocol, cohorts)
    validate_final_disposition_bundle(
        bundle,
        protocol=protocol,
        cohorts=cohorts,
        expected_cohort_bindings=_expected_cohort_bindings(evidence["canonical"]),
    )
    decision = build_decision_matrix(protocol, cohorts, bundle)
    staging = Path(tempfile.mkdtemp(prefix="l2d5d-", dir=output_root.parent))
    try:
        cohort_payload = {
            "schema_version": "trendlines.l2d5d-cohort-evidence.v1",
            "cohort_evidence": [row.to_dict() for row in cohorts],
        }
        _write_json(staging / "final_disposition_bundle.json", bundle.to_dict())
        _write_json(staging / "cohort_evidence.json", cohort_payload)
        decision["cohort_evidence"] = _decision_cohort_summaries(cohorts)
        _write_json(staging / "decision_matrix.json", decision)
        manifest = {
            "schema_version": "trendlines.l2d5d-final-disposition-manifest.v1",
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "prior_evidence": {
                "d5a": _prior_manifest(evidence["d5a_meta"]),
                "d5b": _prior_manifest(evidence["d5b_meta"]),
                "d5c": _prior_manifest(evidence["d5c_meta"]),
                "reference": {
                    "roots": {key: str(value) for key, value in REFERENCE_ROOTS.items()},
                    "bundle_ids": REFERENCE_IDS,
                },
            },
            "final_disposition_protocol_id": protocol.protocol_id,
            "cohort_evidence_ids": [row.cohort_evidence_id for row in cohorts],
            "final_disposition_bundle_id": bundle.final_disposition_bundle_id,
            "decisive_null": decision["decisive_null"],
            "provider_calls": 0,
            "provider_retries": 0,
            "model_executions": 0,
            "replay_executions": 0,
            "parameter_trials": 0,
            "test_disposition": {
                "status": "PENDING_CLOSEOUT",
                "provider_calls": 0,
                "provider_retries": 0,
                "model_executions": 0,
                "replay_executions": 0,
                "parameter_trials": 0,
            },
            "outcome": bundle.selected_outcome.value,
            "recommended_action": bundle.recommended_action.value,
        }
        _write_json(staging / "run_manifest.json", manifest)
        (staging / "review.md").write_text(
            _review(bundle, cohorts, decision), encoding="utf-8"
        )
        _write_json(
            staging / "checksums.json",
            {
                "schema_version": "trendlines.l2d5d-final-disposition-checksums.v1",
                "files": _inventory(staging),
            },
        )
        staging.rename(output_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "output_root": output_root,
        "protocol_id": protocol.protocol_id,
        "bundle_id": bundle.final_disposition_bundle_id,
        "outcome": bundle.selected_outcome.value,
        "recommended_action": bundle.recommended_action.value,
    }


def refresh_closeout(output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Regenerate closeout files without rewriting content-addressed evidence."""

    root = Path(output_root)
    if not root.is_dir():
        raise D5DError(f"D5D output root missing: {root}")
    _verify_checksums(root)
    evidence = verify_prior_evidence()
    protocol = build_final_disposition_protocol(
        d5a_source_matrix_bundle_id=D5A_ID,
        d5b_replication_protocol_id=D5B_PROTOCOL_ID,
        d5b_replication_bundle_id=D5B_ID,
        d5c_sensitivity_protocol_id=D5C_PROTOCOL_ID,
        d5c_sensitivity_bundle_id=D5C_ID,
    )
    cohorts = [
        build_final_cohort_evidence(
            canonical=evidence["canonical"][name],
            dense_capsule=evidence["canonical"][name]["dense_capsule"],
            sparse_capsule=evidence["canonical"][name]["sparse_capsule"],
            protocol=protocol,
        )
        for name in MEMBER_NAMES
    ]
    bundle = build_final_disposition_bundle(protocol, cohorts)
    validate_final_disposition_bundle(
        bundle,
        protocol=protocol,
        cohorts=cohorts,
        expected_cohort_bindings=_expected_cohort_bindings(evidence["canonical"]),
    )
    expected_bundle = _load(root / "final_disposition_bundle.json")
    if expected_bundle != bundle.to_dict():
        raise D5DError("content-addressed final bundle changed")
    expected_cohorts = {
        "schema_version": "trendlines.l2d5d-cohort-evidence.v1",
        "cohort_evidence": [row.to_dict() for row in cohorts],
    }
    if _load(root / "cohort_evidence.json") != expected_cohorts:
        raise D5DError("content-addressed cohort evidence changed")
    decision = build_decision_matrix(protocol, cohorts, bundle)
    decision["cohort_evidence"] = _decision_cohort_summaries(cohorts)
    _write_json(root / "decision_matrix.json", decision)
    manifest = _load(root / "run_manifest.json")
    manifest["decisive_null"] = decision["decisive_null"]
    _write_json(root / "run_manifest.json", manifest)
    (root / "review.md").write_text(_review(bundle, cohorts, decision), encoding="utf-8")
    finalize_test_disposition(root, manifest["test_disposition"])
    return {
        "protocol_id": protocol.protocol_id,
        "bundle_id": bundle.final_disposition_bundle_id,
        "outcome": bundle.selected_outcome.value,
        "recommended_action": bundle.recommended_action.value,
    }


def finalize_test_disposition(
    output_root: str | Path,
    test_disposition: Mapping[str, Any],
) -> None:
    """Close manifest/review checksums without changing content-addressed evidence."""

    root = Path(output_root)
    manifest = _load(root / "run_manifest.json")
    manifest["test_disposition"] = dict(test_disposition)
    _write_json(root / "run_manifest.json", manifest)
    review = (root / "review.md").read_text(encoding="utf-8")
    closeout = "\n## Validation closeout\n\n" + json.dumps(
        dict(test_disposition), sort_keys=True, indent=2
    ) + "\n"
    if "## Validation closeout" in review:
        review = review.split("\n## Validation closeout", 1)[0].rstrip() + "\n"
    (root / "review.md").write_text(review + closeout, encoding="utf-8")
    _write_json(
        root / "checksums.json",
        {
            "schema_version": "trendlines.l2d5d-final-disposition-checksums.v1",
            "files": _inventory(root),
        },
    )


def verify_published_output(output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Read back six D5D files and recompute final identity/decision."""

    root = Path(output_root)
    if not root.is_dir():
        raise D5DError(f"D5D output root missing: {root}")
    _verify_checksums(root)
    files = sorted(path.name for path in root.iterdir() if path.is_file())
    if tuple(files) != tuple(sorted(FINAL_FILES)):
        raise D5DError("D5D output file inventory differs")
    evidence = verify_prior_evidence()
    protocol = build_final_disposition_protocol(
        d5a_source_matrix_bundle_id=D5A_ID,
        d5b_replication_protocol_id=D5B_PROTOCOL_ID,
        d5b_replication_bundle_id=D5B_ID,
        d5c_sensitivity_protocol_id=D5C_PROTOCOL_ID,
        d5c_sensitivity_bundle_id=D5C_ID,
    )
    cohort_payload = _load(root / "cohort_evidence.json")
    cohorts = []
    for row in cohort_payload.get("cohort_evidence", []):
        cohorts.append(__import__(
            "libs.models.trendlines.workflows.research.adequacy.final_disposition",
            fromlist=["TrendlineFinalCohortEvidence"],
        ).TrendlineFinalCohortEvidence(**row))
    bundle_payload = _load(root / "final_disposition_bundle.json")
    nested = dict(bundle_payload.pop("final_disposition_protocol"))
    protocol_id = nested.pop("final_disposition_protocol_id")
    nested["protocol_id"] = protocol_id
    from libs.models.trendlines.workflows.research.adequacy import (
        TrendlineFinalDispositionBundle,
        TrendlineFinalDispositionProtocol,
    )
    stored_protocol = TrendlineFinalDispositionProtocol(**nested)
    bundle_payload["final_disposition_protocol"] = stored_protocol
    bundle_payload.pop("final_disposition_protocol_id", None)
    bundle_payload["axis_classifications"] = tuple(
        tuple(value)
        for value in _load(root / "final_disposition_bundle.json")[
            "axis_classifications"
        ]
    )
    bundle = TrendlineFinalDispositionBundle(**bundle_payload)
    validate_final_disposition_bundle(
        bundle,
        protocol=protocol,
        cohorts=cohorts,
        expected_cohort_bindings=_expected_cohort_bindings(evidence["canonical"]),
    )
    decision = _load(root / "decision_matrix.json")
    expected_decision = build_decision_matrix(protocol, cohorts, bundle)
    expected_decision["cohort_evidence"] = _decision_cohort_summaries(cohorts)
    if decision != expected_decision:
        raise D5DError("decision matrix differs from recomputed evidence")
    manifest = _load(root / "run_manifest.json")
    if manifest.get("final_disposition_bundle_id") != bundle.final_disposition_bundle_id:
        raise D5DError("manifest bundle identity differs")
    if manifest.get("outcome") != bundle.selected_outcome.value:
        raise D5DError("manifest outcome differs")
    if manifest.get("decisive_null") != expected_decision["decisive_null"]:
        raise D5DError("manifest decisive null differs")
    return {
        "bundle_id": bundle.final_disposition_bundle_id,
        "protocol_id": protocol.protocol_id,
        "outcome": bundle.selected_outcome.value,
        "recommended_action": bundle.recommended_action.value,
        "cohort_count": len(cohorts),
        "decision_matrix": decision,
        "prior": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    result = synthesize(args.output_root)
    print(json.dumps({key: str(value) for key, value in result.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
