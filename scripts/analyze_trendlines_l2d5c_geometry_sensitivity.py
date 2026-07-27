"""Run D5C geometry-width sensitivity entirely offline."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Mapping

from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.config.resolve import resolve_asset_config
from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
    TrendlineReplayWindow,
    prepare_trendline_research,
    read_research_frame_artifact,
    run_causal_replay,
)
from libs.models.trendlines.workflows.research.adequacy import (
    TrendlineAdequacyStudyConfig,
    TrendlineInteractionUtilitySpec,
    TrendlineStructuralStabilitySpec,
    build_adequacy_cohort,
    build_baseline_comparison_bundle,
    build_geometry_sensitivity_bundle,
    build_geometry_sensitivity_protocol,
    build_interaction_utility_bundle,
    build_sensitivity_capsule,
    build_stochastic_null_comparison_bundle,
    build_structural_stability_bundle,
    expected_geometry_variant_identity,
    validate_geometry_sensitivity_bundle,
    validate_geometry_sensitivity_capsule,
    validate_variant_root_configuration,
    validate_baseline_comparison_bundle,
    validate_interaction_utility_bundle,
    validate_stochastic_null_comparison_bundle,
    validate_structural_stability_bundle,
    collect_adequacy_observations,
)
from libs.models.trendlines.workflows.research.adequacy.robustness_sources import (
    ROBUSTNESS_EXPECTED_ROWS,
    TrendlineRobustnessSourceMemberEvidence,
    TrendlineRobustnessSourceMemberSpec,
    validate_robustness_source_frame,
)
from scripts import analyze_trendlines_l2d2_structural_stability as d2_script
from scripts import analyze_trendlines_l2d5b_offline_robustness as d5b_script


SOURCE_MATRIX_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5a_source_matrix_v1"
)
D5B_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5b_offline_replication_v1"
)
REFERENCE_SOURCE_ROOT = Path(
    "artifacts/trendlines_research_validation/"
    "20260726_btcusdt_1h_single_call_v1"
)
OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5c_geometry_sensitivity_v1"
)
SOURCE_ARTIFACT_NAME = "normalized_ohlcv_v2.json"
D5A_MATRIX_ID = "9e324fff3bfce51eadb86fdcc173d75e984064d7eeaccb3d413fc4c8b13e907a"
D5B_PROTOCOL_ID = "b722750e2b4deb627bec302431101e2a7d54b43a886af351d99c3be77819b639"
D5B_BUNDLE_ID = "b0eff1ecd259af4193f70d6ada991a3f7ef0e8731bece95ffd02c15045c7da9b"
IMPLEMENTATION_BASE_COMMIT = "492a0be0ffb49aca59d40c348f2a9303d6a4863c"
YAML_PATH = Path("src/libs/models/trendlines/config/trendlines.yaml")
YAML_SHA256 = "57d33ec35b3a3a5bf0f13c98cf123e15608cdbe9c61f0442b09bf1b5d8c83735"
EXPECTED_D2_ID = "f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f"
EXPECTED_D3_ID = "56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4"
EXPECTED_D4A_ID = "664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663"
EXPECTED_D4B_ID = "98f04441c0ef9c643640c78004a875ab6fa6a8de6c797eb1f2e68420910323db"
REFERENCE_BASELINE_ROOTS = {
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
VALIDATED_TEST_DISPOSITION: dict[str, Any] = {
    "status": "PENDING_CLOSEOUT",
    "provider_calls": 0,
    "provider_retries": 0,
    "outcome": None,
}


def _canonical_json(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(payload))
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _verify_checksums(root: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
    entries = tuple(payload["files"])
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["byte_length"]:
            raise RuntimeError(f"checksum inventory mismatch: {path}")
        if _sha256(path) != entry["sha256"]:
            raise RuntimeError(f"checksum differs: {path}")
    return entries


def _inventory(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "byte_length": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "checksums.json"
    ]


def _member_frame_path(spec: TrendlineRobustnessSourceMemberSpec) -> Path:
    if _relation_value(spec) == "reference":
        return REFERENCE_SOURCE_ROOT / SOURCE_ARTIFACT_NAME
    return SOURCE_MATRIX_ROOT / "members" / spec.name / SOURCE_ARTIFACT_NAME


def _relation_value(spec: TrendlineRobustnessSourceMemberSpec) -> str:
    value = spec.relation
    return value.value if hasattr(value, "value") else str(value)


def _research_spec(spec: TrendlineRobustnessSourceMemberSpec) -> TrendlineResearchSpec:
    return TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.BINANCE,
            event_start=spec.event_start,
            knowledge_cutoff=spec.knowledge_cutoff,
        ),
        asset=spec.asset,
        timeframes=(spec.timeframe,),
        primary_timeframe=spec.timeframe,
    )


def _read_member_frame(
    spec: TrendlineRobustnessSourceMemberSpec,
    evidence: TrendlineRobustnessSourceMemberEvidence,
) -> Any:
    path = _member_frame_path(spec)
    frame = read_research_frame_artifact(
        path,
        expected_asset=spec.asset,
        expected_timeframe=spec.timeframe,
        expected_source_id=evidence.source_id,
        expected_availability_id=evidence.availability_id,
        expected_dataset_id=evidence.dataset_id,
    )
    if len(frame) != ROBUSTNESS_EXPECTED_ROWS:
        raise RuntimeError(f"D5A frame row count differs: {spec.name}")
    if _sha256(path) != evidence.artifact_sha256:
        raise RuntimeError(f"D5A frame checksum differs: {spec.name}")
    return validate_robustness_source_frame(frame, spec)


def _study_config(spec: TrendlineRobustnessSourceMemberSpec, *, variant_name: str | None) -> TrendlineAdequacyStudyConfig:
    if _relation_value(spec) == "reference":
        base = d2_script._study_config()
    else:
        base = d5b_script._study_config(spec)
    if variant_name is None:
        return base
    return replace(
        base,
        study_name=f"l2d5c-{spec.name}-{variant_name}-geometry-sensitivity-v1",
    )


def _variant_config(canonical_config: Any, variant: Any) -> Any:
    return replace(
        canonical_config,
        extractor_params=dict(variant.extractor_params),
        fitter_params=dict(variant.fitter_params),
    )


def _resolve_hold_bars(prepared: Any, replay: Any, timeframe: str) -> int:
    position = replay.timeframes[timeframe].recorded_positions[0]
    point = replay.output_at(timeframe, position)
    pipeline = prepared.configuration.pipeline_configs[timeframe]
    resolved = resolve_asset_config(
        pipeline.trendlines_config,
        prepared.spec.asset,
        timeframe,
        prepared.dataset.frames[timeframe],
        fit_result=point.output.fit_result,
    )
    value = resolved.signals.hold_bars
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError(f"invalid resolved hold-bars for {prepared.spec.asset}/{timeframe}")
    expected = 1 if timeframe == "4h" else 3
    if value != expected:
        raise RuntimeError(f"unexpected hold-bars for {prepared.spec.asset}/{timeframe}: {value}")
    return value


def _execute_chain(
    spec: TrendlineRobustnessSourceMemberSpec,
    evidence: TrendlineRobustnessSourceMemberEvidence,
    trendlines_config: Any,
    study_config: TrendlineAdequacyStudyConfig,
) -> dict[str, Any]:
    frame = _read_member_frame(spec, evidence)
    prepared = asyncio.run(
        prepare_trendline_research(
            _research_spec(spec),
            trendlines_config=trendlines_config,
            loader={spec.timeframe: frame},
        )
    )
    identity = {
        "source_id": prepared.dataset.identity.source_refs[spec.timeframe].source_id,
        "availability_id": prepared.dataset.identity.availability_ids[spec.timeframe],
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "preparation_id": prepared.preparation_id,
    }
    expected_source = {
        "source_id": evidence.source_id,
        "availability_id": evidence.availability_id,
        "dataset_id": evidence.dataset_id,
    }
    if any(identity[key] != expected_source[key] for key in expected_source):
        raise RuntimeError(f"source identity differs for {spec.name}")
    replay = run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={spec.timeframe: TrendlineReplayWindow(19, 64, 311, 1)},
            include_signals=True,
        ),
    )
    replay_frame = replay.timeframes[spec.timeframe]
    if replay_frame.executed_position_count != 293 or replay_frame.recorded_position_count != 248:
        raise RuntimeError(f"replay counts differ for {spec.name}")
    cohort = build_adequacy_cohort(prepared, replay, study_config)
    observations = collect_adequacy_observations(cohort, prepared, replay, study_config)
    stability_spec = TrendlineStructuralStabilitySpec((1, 3, 6, 12))
    d2 = build_structural_stability_bundle(cohort, study_config, observations, replay, stability_spec)
    hold_bars = _resolve_hold_bars(prepared, replay, spec.timeframe)
    interaction_spec = TrendlineInteractionUtilitySpec(
        evaluation_horizons_bars=(1, 3, 6, 12),
        break_confirmation_bars=hold_bars,
    )
    d3 = build_interaction_utility_bundle(prepared, replay, cohort, study_config, d2, interaction_spec)
    d4a = build_baseline_comparison_bundle(prepared, replay, study_config, d2, d3)
    protocol = d5b_script._protocol()
    d4b = build_stochastic_null_comparison_bundle(
        prepared,
        replay,
        study_config,
        d2,
        d3,
        d4a,
        protocol.stochastic_baseline_specs,
        quantile_probabilities=protocol.quantile_probabilities,
    )
    validate_structural_stability_bundle(d2)
    validate_interaction_utility_bundle(d3, structural_stability_bundle=d2, replay=replay)
    validate_baseline_comparison_bundle(
        d4a,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=d2,
        interaction_bundle=d3,
        study_config=study_config,
    )
    validate_stochastic_null_comparison_bundle(
        d4b,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=d2,
        interaction_bundle=d3,
        deterministic_baseline_bundle=d4a,
        study_config=study_config,
    )
    return {
        "prepared": prepared,
        "replay": replay,
        "study_config": study_config,
        "hold_bars": hold_bars,
        "bundles": {"d2": d2, "d3": d3, "d4a": d4a, "d4b": d4b},
        "identity": identity,
    }


def _canonical_baseline_ids(spec: TrendlineRobustnessSourceMemberSpec) -> dict[str, str]:
    if _relation_value(spec) == "reference":
        return {"d2": EXPECTED_D2_ID, "d3": EXPECTED_D3_ID, "d4a": EXPECTED_D4A_ID, "d4b": EXPECTED_D4B_ID}
    manifest = json.loads(
        (
            D5B_ROOT / "members" / spec.name / "member_manifest.json"
        ).read_text(encoding="utf-8")
    )
    row_counts = manifest["row_counts"]
    return {
        "d2": row_counts["d2_bundle_id"],
        "d3": row_counts["d3_bundle_id"],
        "d4a": row_counts["d4a_bundle_id"],
        "d4b": row_counts["d4b_bundle_id"],
    }


def _baseline_result_id(spec: TrendlineRobustnessSourceMemberSpec, bundle_ids: Mapping[str, str]) -> str:
    if _relation_value(spec) != "reference":
        manifest = json.loads(
            (D5B_ROOT / "members" / spec.name / "member_manifest.json").read_text(encoding="utf-8")
        )
        return manifest["row_counts"]["member_result_id"]
    return canonical_hash(
        {"member_name": spec.name, "bundle_ids": dict(bundle_ids)},
        semantics_version="trendlines.adequacy-d5c-reference-baseline-result.v1",
    )


def _assert_canonical_chain(run: Mapping[str, Any], expected: Mapping[str, str], evidence: Any) -> None:
    actual = {
        "d2": run["bundles"]["d2"].structural_stability_bundle_id,
        "d3": run["bundles"]["d3"].interaction_utility_bundle_id,
        "d4a": run["bundles"]["d4a"].baseline_comparison_bundle_id,
        "d4b": run["bundles"]["d4b"].stochastic_null_comparison_bundle_id,
    }
    if actual != dict(expected):
        raise RuntimeError(f"committed baseline chain differs: expected={expected}, actual={actual}")
    if run["prepared"].configuration.research_configuration_id != evidence.research_configuration_id:
        raise RuntimeError("canonical baseline research configuration differs from D5A")
    if run["prepared"].preparation_id != evidence.preparation_id:
        raise RuntimeError("canonical baseline preparation differs from D5A")


def _stage_digest_inventory(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    from libs.models.trendlines.workflows.research.adequacy import build_stage_digest

    rows = []
    counts = {
        "d2": len(run["bundles"]["d2"].summaries),
        "d3": len(run["bundles"]["d3"].summaries),
        "d4a": len(run["bundles"]["d4a"].comparison_summaries),
        "d4b": len(run["bundles"]["d4b"].distribution_summaries),
    }
    for stage in ("d2", "d3", "d4a", "d4b"):
        rows.append(build_stage_digest(stage, run["bundles"][stage], counts[stage]).to_dict())
    return rows


def _build_protocol(matrix: Any, d5b_protocol: Any) -> Any:
    return build_geometry_sensitivity_protocol(
        d5a_source_matrix_bundle_id=matrix.robustness_source_matrix_bundle_id,
        d5b_replication_protocol_id=d5b_protocol.replication_protocol_id,
        d5b_replication_bundle_id=D5B_BUNDLE_ID,
        member_names=tuple(spec.name for spec in matrix.member_specs),
        deterministic_baseline_ids=d5b_protocol.deterministic_baseline_ids,
        stochastic_baseline_specs=d5b_protocol.stochastic_baseline_specs,
    )


def _write_capsule(
    staging: Path,
    spec: TrendlineRobustnessSourceMemberSpec,
    variant: Any,
    capsule: Any,
) -> Path:
    path = staging / "members" / spec.name / variant.name / "sensitivity_capsule.json"
    return _write_json(path, capsule.to_dict())


def run_study(
    *,
    source_matrix_root: str | Path = SOURCE_MATRIX_ROOT,
    d5b_root: str | Path = D5B_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
    chain_runner: Callable[..., Mapping[str, Any]] | None = None,
    test_disposition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and publish ten validated compact sensitivity capsules."""

    output_root = Path(output_root)
    if output_root.exists():
        raise RuntimeError("D5C output root already exists; overwrite is forbidden")
    global D5B_ROOT
    D5B_ROOT = Path(d5b_root)
    trendlines_config = load_trendlines_config()
    yaml_before = _sha256(YAML_PATH)
    if yaml_before != YAML_SHA256:
        raise RuntimeError("canonical YAML hash differs before D5C")
    matrix, d5a_checksums = d5b_script.load_source_matrix(
        Path(source_matrix_root), trendlines_config=trendlines_config
    )
    if matrix.robustness_source_matrix_bundle_id != D5A_MATRIX_ID:
        raise RuntimeError("D5A matrix identity differs")
    d5b_checksums = _verify_checksums(D5B_ROOT)
    reference_baseline_checksums = {
        stage: list(_verify_checksums(root))
        for stage, root in REFERENCE_BASELINE_ROOTS.items()
    }
    d5b_payload = json.loads((D5B_ROOT / "robustness_replication_bundle.json").read_text(encoding="utf-8"))
    if d5b_payload["robustness_replication_bundle_id"] != D5B_BUNDLE_ID:
        raise RuntimeError("D5B aggregate identity differs")
    d5b_protocol = d5b_script._protocol()
    protocol = _build_protocol(matrix, d5b_protocol)
    variants = protocol.variants
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent))
    capsules = []
    member_manifests = []
    chain_records = []
    try:
        canonical_config = trendlines_config
        for spec, evidence in zip(matrix.member_specs, matrix.member_evidence):
            baseline_study = _study_config(spec, variant_name=None)
            baseline_run = (chain_runner or _execute_chain)(
                spec, evidence, canonical_config, baseline_study
            )
            expected_ids = _canonical_baseline_ids(spec)
            _assert_canonical_chain(baseline_run, expected_ids, evidence)
            baseline_result_id = _baseline_result_id(spec, expected_ids)
            baseline_record = {
                "chain": "canonical",
                "variant": "canonical",
                "member_name": spec.name,
                "bundle_ids": expected_ids,
                "research_configuration_id": baseline_run["prepared"].configuration.research_configuration_id,
                "preparation_id": baseline_run["prepared"].preparation_id,
                "replay_id": baseline_run["replay"].replay_id,
                "stage_digests": _stage_digest_inventory(baseline_run),
                "baseline_member_result_id": baseline_result_id,
            }
            chain_records.append(baseline_record)
            member_capsules = []
            for variant in variants:
                variant_config = _variant_config(canonical_config, variant)
                validate_variant_root_configuration(
                    canonical_config,
                    variant_config,
                    variant,
                )
                variant_study = _study_config(spec, variant_name=variant.name)
                run = (chain_runner or _execute_chain)(
                    spec, evidence, variant_config, variant_study
                )
                expected = expected_geometry_variant_identity(variant.name, spec.name)
                if run["prepared"].configuration.root_configuration_id != variant.expected_root_configuration_id:
                    raise RuntimeError(f"variant root config differs: {spec.name}/{variant.name}")
                if run["prepared"].configuration.research_configuration_id != expected["research_configuration_id"]:
                    raise RuntimeError(f"variant research config differs: {spec.name}/{variant.name}")
                if run["prepared"].preparation_id != expected["preparation_id"]:
                    raise RuntimeError(f"variant preparation differs: {spec.name}/{variant.name}")
                capsule = build_sensitivity_capsule(
                    d5a_member_spec=spec,
                    d5a_member_evidence=evidence,
                    baseline_member_result_id=baseline_result_id,
                    variant=variant,
                    baseline_prepared=baseline_run["prepared"],
                    baseline_replay=baseline_run["replay"],
                    baseline_bundles=baseline_run["bundles"],
                    variant_prepared=run["prepared"],
                    variant_replay=run["replay"],
                    variant_bundles=run["bundles"],
                    protocol=protocol,
                )
                validate_geometry_sensitivity_capsule(
                    capsule,
                    d5a_member_spec=spec,
                    d5a_member_evidence=evidence,
                    expected_baseline_member_result_id=baseline_result_id,
                    protocol=protocol,
                    variant=variant,
                    baseline_bundles=baseline_run["bundles"],
                    variant_bundles=run["bundles"],
                    baseline_prepared=baseline_run["prepared"],
                    variant_prepared=run["prepared"],
                    baseline_replay=baseline_run["replay"],
                    variant_replay=run["replay"],
                    baseline_study_config=baseline_study,
                    variant_study_config=variant_study,
                )
                path = _write_capsule(staging, spec, variant, capsule)
                member_capsules.append(
                    {
                        "variant": variant.name,
                        "variant_id": variant.variant_id,
                        "capsule_id": capsule.capsule_id,
                        "path": str(path.relative_to(staging)),
                        "sha256": _sha256(path),
                        "byte_length": path.stat().st_size,
                        "variant_bundle_ids": {
                            stage: run["bundles"][stage].to_dict().get(
                                {"d2": "structural_stability_bundle_id", "d3": "interaction_utility_bundle_id", "d4a": "baseline_comparison_bundle_id", "d4b": "stochastic_null_comparison_bundle_id"}[stage]
                            )
                            for stage in ("d2", "d3", "d4a", "d4b")
                        },
                        "stage_digests": _stage_digest_inventory(run),
                        "count_inventory": capsule.variant_count_inventory,
                    }
                )
                capsules.append(capsule)
                chain_records.append(
                    {
                        "member_name": spec.name,
                        "variant": variant.name,
                        "research_configuration_id": run["prepared"].configuration.research_configuration_id,
                        "preparation_id": run["prepared"].preparation_id,
                        "stage_digests": _stage_digest_inventory(run),
                        "bundle_ids": member_capsules[-1]["variant_bundle_ids"],
                    }
                )
            member_manifest = {
                "schema_version": "trendlines.l2d5c-member-manifest.v1",
                "member_name": spec.name,
                "relation": _relation_value(spec),
                "asset": spec.asset,
                "timeframe": spec.timeframe,
                "d5a_member_spec_id": evidence.member_spec_id,
                "d5a_member_evidence_id": evidence.member_evidence_id,
                "source_id": evidence.source_id,
                "availability_id": evidence.availability_id,
                "dataset_id": evidence.dataset_id,
                "canonical_baseline": baseline_record,
                "variants": member_capsules,
                "provider_calls": 0,
                "provider_retries": 0,
                "outcome": None,
            }
            member_manifest_path = _write_json(
                staging / "members" / spec.name / "member_manifest.json",
                member_manifest,
            )
            member_manifests.append(
                {
                    "path": str(member_manifest_path.relative_to(staging)),
                    "sha256": _sha256(member_manifest_path),
                }
            )
        aggregate = build_geometry_sensitivity_bundle(
            d5a_source_matrix_bundle_id=matrix.robustness_source_matrix_bundle_id,
            d5b_replication_bundle_id=D5B_BUNDLE_ID,
            protocol=protocol,
            capsules=tuple(capsules),
        )
        member_bindings = {
            record["member_name"]: (
                spec,
                evidence,
                record["baseline_member_result_id"],
            )
            for spec, evidence, record in zip(
                matrix.member_specs,
                matrix.member_evidence,
                (record for record in chain_records if record["chain"] == "canonical"),
            )
        }
        validate_geometry_sensitivity_bundle(
            aggregate,
            protocol=protocol,
            member_bindings=member_bindings,
        )
        _write_json(staging / "geometry_sensitivity_bundle.json", aggregate.to_dict())
        manifest = {
            "schema_version": "trendlines.l2d5c-geometry-sensitivity-run.v1",
            "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
            "d5a_root": str(source_matrix_root),
            "d5a_matrix_bundle_id": matrix.robustness_source_matrix_bundle_id,
            "d5a_checksum_inventory": list(d5a_checksums),
            "d5b_root": str(D5B_ROOT),
            "d5b_bundle_id": D5B_BUNDLE_ID,
            "d5b_checksum_inventory": list(d5b_checksums),
            "reference_baseline_artifact_inventory": {
                stage: {
                    "root": str(root),
                    "checksums": reference_baseline_checksums[stage],
                }
                for stage, root in REFERENCE_BASELINE_ROOTS.items()
            },
            "reference_baseline_chain_ids": {
                "d2": EXPECTED_D2_ID,
                "d3": EXPECTED_D3_ID,
                "d4a": EXPECTED_D4A_ID,
                "d4b": EXPECTED_D4B_ID,
            },
            "yaml_sha256_before": yaml_before,
            "yaml_sha256_after": _sha256(YAML_PATH),
            "sensitivity_protocol": protocol.to_dict(),
            "geometry_sensitivity_protocol_id": protocol.protocol_id,
            "baseline_validation_chains": 5,
            "variant_chains": 10,
            "total_chain_executions": 15,
            "executed_prefixes": 15 * 293,
            "recorded_positions": 15 * 248,
            "provider_calls": 0,
            "provider_retries": 0,
            "capsules": [
                {
                    "member_name": row.member_name,
                    "variant_id": row.variant_id,
                    "variant": next(value.name for value in variants if value.variant_id == row.variant_id),
                    "capsule_id": row.capsule_id,
                    "path": str((staging / "members" / row.member_name / next(value.name for value in variants if value.variant_id == row.variant_id) / "sensitivity_capsule.json").relative_to(staging)),
                    "sha256": _sha256(staging / "members" / row.member_name / next(value.name for value in variants if value.variant_id == row.variant_id) / "sensitivity_capsule.json"),
                    "byte_length": (staging / "members" / row.member_name / next(value.name for value in variants if value.variant_id == row.variant_id) / "sensitivity_capsule.json").stat().st_size,
                    "stage_digests": next(record["stage_digests"] for record in chain_records if record["member_name"] == row.member_name and record["variant"] == next(value.name for value in variants if value.variant_id == row.variant_id)),
                }
                for row in capsules
            ],
            "configuration_preparation_id_inventory": [
                {
                    "member_name": spec.name,
                    "variant": variant_name,
                    "expected_research_configuration_id": (
                        evidence.research_configuration_id
                        if variant_name == "canonical"
                        else expected_geometry_variant_identity(variant_name, spec.name)[
                            "research_configuration_id"
                        ]
                    ),
                    "actual_research_configuration_id": (
                        next(
                            record["research_configuration_id"]
                            for record in chain_records
                            if record["member_name"] == spec.name
                            and record["variant"] == variant_name
                        )
                    ),
                    "expected_preparation_id": (
                        evidence.preparation_id
                        if variant_name == "canonical"
                        else expected_geometry_variant_identity(variant_name, spec.name)[
                            "preparation_id"
                        ]
                    ),
                    "actual_preparation_id": (
                        next(
                            record["preparation_id"]
                            for record in chain_records
                            if record["member_name"] == spec.name
                            and record["variant"] == variant_name
                        )
                    ),
                }
                for spec, evidence in zip(matrix.member_specs, matrix.member_evidence)
                for variant_name in ("canonical", *(value.name for value in variants))
            ],
            "member_manifests": member_manifests,
            "full_chain_stage_digest_inventory": chain_records,
            "geometry_sensitivity_bundle_id": aggregate.geometry_sensitivity_bundle_id,
            "test_disposition": dict(test_disposition or VALIDATED_TEST_DISPOSITION),
            "outcome": None,
        }
        _write_json(staging / "run_manifest.json", manifest)
        review = "\n".join(
            (
                "# L2-D5C Geometry Sensitivity Review",
                "",
                "Status: MEASUREMENTS_ONLY",
                "",
                "No sensitivity adequacy outcome selected.",
                "No parameter optimisation or ranking performed.",
                "Two symmetric geometry-width profiles were predeclared.",
                "All five D5A members were evaluated.",
                "Baseline chains were reconstructed only to validate committed identities.",
                "Variant D2-D4B chains were fully built and validated in memory.",
                "Compact capsules retain complete summaries and full-chain digests.",
                "Baseline and variant event populations may differ.",
                "Cross-configuration rate deltas are descriptive, not paired causal effects.",
                "Canonical YAML remained unchanged.",
                "Provider calls and retries were zero.",
                "D5D remains unstarted.",
                "",
                f"D5A matrix: {matrix.robustness_source_matrix_bundle_id}",
                f"D5B bundle: {D5B_BUNDLE_ID}",
                f"D5C protocol: {protocol.protocol_id}",
                f"D5C bundle: {aggregate.geometry_sensitivity_bundle_id}",
                "",
                "Outcome remains null; artifact is descriptive evidence only.",
            )
        ) + "\n"
        (staging / "review.md").write_text(review, encoding="utf-8")
        _write_json(
            staging / "checksums.json",
            {
                "schema_version": "trendlines.l2d5c-geometry-sensitivity-checksums.v1",
                "files": _inventory(staging),
            },
        )
        if _sha256(YAML_PATH) != yaml_before:
            raise RuntimeError("canonical YAML changed during D5C")
        staging.rename(output_root)
        return {"matrix": matrix, "protocol": protocol, "aggregate": aggregate, "output_root": output_root, "manifest": output_root / "run_manifest.json"}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _closeout_manifest_evidence(root: Path, manifest: dict[str, Any]) -> None:
    """Rebuild manifest inventories from published compact evidence only."""

    stage_records: list[dict[str, Any]] = []
    identity_records: list[dict[str, Any]] = []
    for member_manifest_path in sorted(root.glob("members/*/member_manifest.json")):
        member_manifest = json.loads(member_manifest_path.read_text(encoding="utf-8"))
        member_name = member_manifest["member_name"]
        canonical = member_manifest["canonical_baseline"]
        stage_records.append(
            {
                "chain": "canonical",
                "variant": "canonical",
                "member_name": member_name,
                "bundle_ids": canonical["bundle_ids"],
                "research_configuration_id": canonical["research_configuration_id"],
                "preparation_id": canonical["preparation_id"],
                "replay_id": canonical["replay_id"],
                "stage_digests": canonical["stage_digests"],
                "baseline_member_result_id": canonical["baseline_member_result_id"],
            }
        )
        identity_records.append(
            {
                "member_name": member_name,
                "variant": "canonical",
                "expected_research_configuration_id": canonical["research_configuration_id"],
                "actual_research_configuration_id": canonical["research_configuration_id"],
                "expected_preparation_id": canonical["preparation_id"],
                "actual_preparation_id": canonical["preparation_id"],
            }
        )
        for variant_record in member_manifest["variants"]:
            capsule_path = root / variant_record["path"]
            capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
            variant_name = variant_record["variant"]
            stage_records.append(
                {
                    "chain": "variant",
                    "variant": variant_name,
                    "member_name": member_name,
                    "bundle_ids": variant_record["variant_bundle_ids"],
                    "research_configuration_id": capsule[
                        "variant_research_configuration_id"
                    ],
                    "preparation_id": capsule["variant_preparation_id"],
                    "replay_id": capsule["variant_replay_id"],
                    "stage_digests": variant_record["stage_digests"],
                }
            )
            expected = expected_geometry_variant_identity(variant_name, member_name)
            identity_records.append(
                {
                    "member_name": member_name,
                    "variant": variant_name,
                    "expected_research_configuration_id": expected[
                        "research_configuration_id"
                    ],
                    "actual_research_configuration_id": capsule[
                        "variant_research_configuration_id"
                    ],
                    "expected_preparation_id": expected["preparation_id"],
                    "actual_preparation_id": capsule["variant_preparation_id"],
                }
            )
    manifest["full_chain_stage_digest_inventory"] = stage_records
    manifest["configuration_preparation_id_inventory"] = identity_records
    manifest["reference_baseline_artifact_inventory"] = {
        stage: {
            "root": str(root_path),
            "checksums": list(_verify_checksums(root_path)),
        }
        for stage, root_path in REFERENCE_BASELINE_ROOTS.items()
    }


def _published_capsules(root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Load capsule files in manifest order without trusting aggregate payloads."""

    capsules: list[dict[str, Any]] = []
    for entry in manifest["capsules"]:
        path = root / entry["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["geometry_sensitivity_capsule_id"] != entry["capsule_id"]:
            raise RuntimeError(f"capsule manifest identity differs: {path}")
        capsules.append(payload)
    return capsules


def compact_published_aggregate(output_root: str | Path) -> dict[str, Any]:
    """Replace duplicated aggregate capsule payloads with ordered capsule IDs."""

    root = Path(output_root)
    manifest_path = root / "run_manifest.json"
    bundle_path = root / "geometry_sensitivity_bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    old_bundle_id = old_bundle["geometry_sensitivity_bundle_id"]
    capsules = _published_capsules(root, manifest)
    capsule_ids = tuple(row["geometry_sensitivity_capsule_id"] for row in capsules)
    if "capsules" in old_bundle:
        aggregate_ids = tuple(
            row["geometry_sensitivity_capsule_id"] for row in old_bundle["capsules"]
        )
    else:
        aggregate_ids = tuple(old_bundle.get("capsule_ids", ()))
    if aggregate_ids != capsule_ids:
        raise RuntimeError("aggregate capsule order differs from published capsule files")

    protected_paths = [
        root / entry["path"]
        for entry in manifest["capsules"]
    ] + [root / entry["path"] for entry in manifest["member_manifests"]]
    protected_hashes = {path: _sha256(path) for path in protected_paths}
    compact_payload = {
        "d5a_source_matrix_bundle_id": old_bundle["d5a_source_matrix_bundle_id"],
        "d5b_replication_bundle_id": old_bundle["d5b_replication_bundle_id"],
        "sensitivity_protocol": old_bundle["sensitivity_protocol"],
        "geometry_sensitivity_protocol_id": old_bundle[
            "geometry_sensitivity_protocol_id"
        ],
        "capsule_ids": list(capsule_ids),
        "semantics_version": old_bundle["semantics_version"],
    }
    new_bundle_id = canonical_hash(
        compact_payload,
        semantics_version=compact_payload["semantics_version"],
    )
    compact_payload["geometry_sensitivity_bundle_id"] = new_bundle_id
    _write_json(bundle_path, compact_payload)

    manifest["old_geometry_sensitivity_bundle_id"] = old_bundle_id
    manifest["geometry_sensitivity_bundle_id"] = new_bundle_id
    manifest["capsule_ids"] = list(capsule_ids)
    manifest["aggregate_compaction"] = {
        "old_bundle_id": old_bundle_id,
        "new_bundle_id": new_bundle_id,
        "capsule_payloads_embedded": False,
        "capsule_ids_only": True,
        "capsule_count": len(capsule_ids),
        "old_byte_length": len(_canonical_json(old_bundle)),
        "new_byte_length": bundle_path.stat().st_size,
        "capsule_files_unchanged": True,
        "numerical_evidence_unchanged": True,
    }
    _closeout_manifest_evidence(root, manifest)
    _write_json(manifest_path, manifest)
    review_path = root / "review.md"
    review = review_path.read_text(encoding="utf-8")
    review = review.replace(
        f"D5C bundle: {old_bundle_id}",
        f"D5C bundle: {new_bundle_id}",
    )
    closeout = "\n## Aggregate compaction closeout\n\n"
    closeout += f"Previous aggregate ID: `{old_bundle_id}`.\n"
    closeout += f"Compact aggregate ID: `{new_bundle_id}`.\n"
    closeout += "Aggregate binds capsule IDs only; complete capsule payloads remain in ten capsule files.\n"
    closeout += "Protocol, capsule IDs, stage digests and numerical evidence remain unchanged.\n"
    if "## Aggregate compaction closeout" in review:
        review = review.split("\n## Aggregate compaction closeout", 1)[0].rstrip() + "\n"
    review_path.write_text(review + closeout, encoding="utf-8")
    _write_json(
        root / "checksums.json",
        {
            "schema_version": "trendlines.l2d5c-geometry-sensitivity-checksums.v1",
            "files": _inventory(root),
        },
    )
    for path, digest in protected_hashes.items():
        if _sha256(path) != digest:
            raise RuntimeError(f"protected capsule or member manifest changed: {path}")
    return {
        "old_bundle_id": old_bundle_id,
        "new_bundle_id": new_bundle_id,
        "capsule_ids": capsule_ids,
    }


def finalize_test_disposition(output_root: str | Path, test_disposition: Mapping[str, Any]) -> None:
    root = Path(output_root)
    manifest_path = root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _closeout_manifest_evidence(root, manifest)
    manifest["test_disposition"] = dict(test_disposition)
    _write_json(manifest_path, manifest)
    review_path = root / "review.md"
    review = review_path.read_text(encoding="utf-8")
    closeout = "\n## Validation closeout\n\n" + json.dumps(
        dict(test_disposition), sort_keys=True, indent=2
    ) + "\n"
    if "## Validation closeout" in review:
        review = review.split("\n## Validation closeout", 1)[0].rstrip() + "\n"
    review_path.write_text(review + closeout, encoding="utf-8")
    _write_json(
        root / "checksums.json",
        {
            "schema_version": "trendlines.l2d5c-geometry-sensitivity-checksums.v1",
            "files": _inventory(root),
        },
    )


def write_handoff(output_root: str | Path, handoff_path: str | Path, *, test_disposition: Mapping[str, Any] | None = None) -> None:
    root = Path(output_root)
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    capsules = _published_capsules(root, manifest)
    variant_names = {
        row["variant_id"]: row["variant"] for row in manifest["capsules"]
    }
    artifact_file_count = sum(1 for path in root.rglob("*") if path.is_file())
    artifact_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    chain_inventory = []
    overlap_inventory = []
    metric_inventory = {"d2": [], "d3": [], "d4a": [], "d4b": []}

    def _compact_d4b_delta_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            source_metric, value_metric = row["metric_name"].rsplit(".", 1)
            key = (
                row["baseline_id"],
                row["timeframe"],
                row["role"],
                row["horizon_bars"],
                source_metric,
            )
            entry = grouped.setdefault(
                key,
                {
                    "baseline_id": row["baseline_id"],
                    "timeframe": row["timeframe"],
                    "role": row["role"],
                    "horizon_bars": row["horizon_bars"],
                    "source_metric": source_metric,
                    "changes": {},
                },
            )
            entry["changes"][value_metric] = row["delta"]
        return [grouped[key] for key in sorted(grouped)]

    for capsule in capsules:
        chain_inventory.append(
            {
                "member_name": capsule["member_name"],
                "variant_id": capsule["variant_id"],
                "variant": variant_names[capsule["variant_id"]],
                "capsule_id": capsule["geometry_sensitivity_capsule_id"],
                "baseline_member_result_id": capsule["baseline_member_result_id"],
                "canonical_root_configuration_id": capsule["canonical_root_configuration_id"],
                "variant_root_configuration_id": capsule["variant_root_configuration_id"],
                "canonical_research_configuration_id": capsule["canonical_research_configuration_id"],
                "variant_research_configuration_id": capsule["variant_research_configuration_id"],
                "canonical_preparation_id": capsule["canonical_preparation_id"],
                "variant_preparation_id": capsule["variant_preparation_id"],
                "variant_replay_id": capsule["variant_replay_id"],
                "variant_cohort_id": capsule["variant_cohort_id"],
                "variant_study_config_id": capsule["variant_study_config_id"],
                "variant_stability_spec_id": capsule["variant_stability_spec_id"],
                "variant_interaction_spec_id": capsule["variant_interaction_spec_id"],
                "variant_d2_bundle_id": capsule["variant_d2_bundle_id"],
                "variant_d3_bundle_id": capsule["variant_d3_bundle_id"],
                "variant_d4a_bundle_id": capsule["variant_d4a_bundle_id"],
                "variant_d4b_bundle_id": capsule["variant_d4b_bundle_id"],
            }
        )
        overlap_inventory.append(
            {
                "member_name": capsule["member_name"],
                "variant_id": capsule["variant_id"],
                **capsule["event_overlap"],
            }
        )
        for stage in metric_inventory:
            stage_delta_rows = [
                row
                for row in capsule["delta_rows"]
                if row["stage"] == stage
            ]
            if stage == "d4b":
                stage_delta_rows = _compact_d4b_delta_rows(stage_delta_rows)
            metric_inventory[stage].append(
                {
                    "member_name": capsule["member_name"],
                    "variant_id": capsule["variant_id"],
                    "summary_row_count": len(
                        capsule[
                            {
                                "d2": "d2_summaries",
                                "d3": "d3_summaries",
                                "d4a": "d4a_summaries",
                                "d4b": "d4b_summaries",
                            }[stage]
                        ]
                    ),
                    "delta_rows": stage_delta_rows,
                }
            )
    lines = [
        "# Coder-to-Orchestrator Handoff: L2-D5C Geometry Sensitivity",
        "",
        "## Disposition",
        "",
        "D5C is descriptive sensitivity evidence only. No adequacy outcome was selected.",
        "",
        "## Branch and starting commit",
        "",
        "Branch: `research/trendlines-adequacy-v1`.",
        f"Starting implementation base: `{manifest['implementation_base_commit']}`.",
        "Parallel main audit found no mature-trendlines or shared-dependency overlap.",
        "",
        "## Frozen envelope",
        "",
        "Canonical geometry is fractal 3/3 with pathfinding pivot_window 3.",
        "Dense profile is 2/2/2; sparse profile is 4/4/4.",
        "Extractor, fitter, endpoint mode and all other YAML-resolved fields remain inherited.",
        "This is a symmetric local envelope, not one-at-a-time attribution or optimisation.",
        "",
        "## Execution and persistence",
        "",
        f"D5A matrix: `{manifest['d5a_matrix_bundle_id']}`.",
        f"D5B bundle: `{manifest['d5b_bundle_id']}`.",
        f"D5C protocol: `{manifest['geometry_sensitivity_protocol_id']}`.",
        f"D5C bundle: `{manifest['geometry_sensitivity_bundle_id']}`.",
        f"Baseline validation chains: {manifest['baseline_validation_chains']}; variant chains: {manifest['variant_chains']}; total: {manifest['total_chain_executions']}.",
        f"Executed prefixes: {manifest['executed_prefixes']}; recorded positions: {manifest['recorded_positions']}.",
        f"Published artifact files: {artifact_file_count}; {artifact_bytes} bytes.",
        "Full D2-D4B chains were validated in memory. Capsules retain typed summary rows, event overlap, deltas, counts and full-chain digests; raw state/outcome arrays are not persisted.",
        f"Aggregate compaction: `{manifest.get('old_geometry_sensitivity_bundle_id', 'not applicable')}` -> `{manifest['geometry_sensitivity_bundle_id']}`; aggregate stores capsule IDs only; ten capsule files remain unchanged.",
        "",
        "## Member chain identities",
        "",
        "Canonical and variant configuration/preparation IDs, replay/cohort/study/spec IDs, stage bundle IDs and capsule IDs:",
        "",
        "```json",
        json.dumps(chain_inventory, sort_keys=True, indent=2),
        "```",
        "",
        "Expected/actual research-configuration and preparation identities:",
        "",
        "```json",
        json.dumps(
            manifest["configuration_preparation_id_inventory"],
            sort_keys=True,
            indent=2,
        ),
        "```",
        "",
        "## Event overlap",
        "",
        "Coarse key: `(timeframe, role, selection_position)`. Exact key: `(timeframe, role, selection_position, canonical anchor_key)`. No fuzzy matching:",
        "",
        "```json",
        json.dumps(overlap_inventory, sort_keys=True, indent=2),
        "```",
        "",
        "## Structural and interaction deltas",
        "",
        "D2 structural summary snapshots, D3 interaction summary snapshots, D4A delta-of-delta rows and D4B distribution changes are persisted below from compact capsules. Values remain descriptive; no profile is labelled better or worse.",
        "",
        "```json",
        json.dumps(metric_inventory, sort_keys=True, indent=2),
        "```",
        "",
        "## Full-chain digest inventory",
        "",
        "All 15 validated chains, including canonical baseline chains:",
        "",
        "```json",
        json.dumps(manifest["full_chain_stage_digest_inventory"], sort_keys=True, indent=2),
        "```",
        "",
        "## Integrity and validation",
        "",
        f"YAML before/after: `{manifest['yaml_sha256_before']}` / `{manifest['yaml_sha256_after']}`.",
        "Provider calls/retries: 0 / 0. Outcome: null.",
        f"Test disposition: `{json.dumps(test_disposition or manifest['test_disposition'], sort_keys=True)}`.",
        "Canonical YAML remained unchanged. No provider, model, replay, sensitivity optimisation or D5D execution occurred during closeout.",
        "",
        "## Residual risks and next phase",
        "",
        "Each member uses one bounded window. Event populations can differ across geometry profiles, so cross-configuration deltas are descriptive rather than paired causal effects. D5D cross-member synthesis and final adequacy disposition remain unstarted.",
    ]
    Path(handoff_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-matrix-root", type=Path, default=SOURCE_MATRIX_ROOT)
    parser.add_argument("--d5b-root", type=Path, default=D5B_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_study(
        source_matrix_root=args.source_matrix_root,
        d5b_root=args.d5b_root,
        output_root=args.output_root,
    )


if __name__ == "__main__":
    main()
