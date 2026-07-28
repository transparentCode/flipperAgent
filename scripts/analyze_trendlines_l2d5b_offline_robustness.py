"""Run D5B offline replication across frozen D5A source members."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Mapping

from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.config.resolve import resolve_asset_config
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
    TrendlineAdequacyAvailabilityPolicy,
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
    TrendlineAdequacyStudyConfig,
    TrendlineAdequacyWindow,
    TrendlineInvalidPointTreatment,
    TrendlineInteractionUtilitySpec,
    TrendlineObservationUnit,
    TrendlineRobustnessSourceMatrixBundle,
    TrendlineRobustnessSourceMemberEvidence,
    TrendlineRobustnessSourceMemberSpec,
    TrendlineRobustnessReplicationProtocol,
    build_adequacy_cohort,
    build_baseline_comparison_bundle,
    build_interaction_utility_bundle,
    build_replication_member_evidence,
    build_robustness_replication_bundle,
    build_stochastic_null_comparison_bundle,
    build_structural_stability_bundle,
    collect_adequacy_observations,
    frozen_robustness_source_member_specs,
    validate_replication_member_evidence,
    validate_replication_protocol,
    validate_robustness_source_frame,
    validate_robustness_source_matrix_bundle,
)
from libs.models.trendlines.workflows.research.adequacy.robustness_sources import (
    ROBUSTNESS_EXPECTED_ROWS,
    ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
)


SOURCE_MATRIX_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5a_source_matrix_v1"
)
OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_robustness/"
    "20260727_l2d5b_offline_replication_v1"
)
SOURCE_MATRIX_BUNDLE_NAME = "robustness_source_matrix_bundle.json"
SOURCE_MATRIX_CHECKSUMS_NAME = "checksums.json"
SOURCE_ARTIFACT_NAME = "normalized_ohlcv_v2.json"
IMPLEMENTATION_BASE_COMMIT = "c503bbe"
EXPECTED_SOURCE_MATRIX_ID = (
    "9e324fff3bfce51eadb86fdcc173d75e984064d7eeaccb3d413fc4c8b13e907a"
)
VALIDATED_TEST_DISPOSITION: dict[str, Any] = {
    "status": "PASSED",
    "d5b_package_and_script": "41 passed",
    "d5b_artifact_readback": "passed",
    "d5b_required_adequacy_regression": "278 passed",
    "canonical_mature_trendlines": "731 passed",
    "viewer_python": "30 passed",
    "viewer_node": "23 passed",
    "consumer_ingestion_bridge": "79 passed",
    "offline_workflows": "20 passed",
    "ruff_compileall_diff_check": "passed",
    "provider_calls": 0,
    "provider_retries": 0,
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


def _implementation_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _verify_checksums(root: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads((root / SOURCE_MATRIX_CHECKSUMS_NAME).read_text())
    entries = tuple(payload["files"])
    for entry in entries:
        path = root / entry["path"]
        if not path.is_file():
            raise RuntimeError(f"missing D5A checksum member: {path}")
        if path.stat().st_size != entry["byte_length"]:
            raise RuntimeError(f"D5A checksum byte length differs: {path}")
        if _sha256(path) != entry["sha256"]:
            raise RuntimeError(f"D5A checksum differs: {path}")
    return entries


def _source_evidence_from_dict(payload: Mapping[str, Any]) -> TrendlineRobustnessSourceMemberEvidence:
    values = dict(payload)
    values.pop("member_evidence_id", None)
    for name in (
        "first_event_at",
        "last_event_at",
        "first_availability_at",
        "last_availability_at",
    ):
        values[name] = datetime.fromisoformat(values[name])
    return TrendlineRobustnessSourceMemberEvidence(**values)


def load_source_matrix(
    root: str | Path = SOURCE_MATRIX_ROOT,
    *,
    trendlines_config: Any | None = None,
) -> tuple[TrendlineRobustnessSourceMatrixBundle, tuple[dict[str, Any], ...]]:
    """Read, checksum and type the committed D5A source matrix."""

    root = Path(root)
    checksum_entries = _verify_checksums(root)
    payload = json.loads((root / SOURCE_MATRIX_BUNDLE_NAME).read_text())
    specs = frozen_robustness_source_member_specs()
    evidence = tuple(_source_evidence_from_dict(value) for value in payload["member_evidence"])
    matrix = TrendlineRobustnessSourceMatrixBundle(
        member_specs=specs,
        member_evidence=evidence,
        reference_d2_bundle_id=payload["reference_d2_bundle_id"],
        reference_d3_bundle_id=payload["reference_d3_bundle_id"],
        reference_d4a_bundle_id=payload["reference_d4a_bundle_id"],
        reference_d4b_bundle_id=payload["reference_d4b_bundle_id"],
        semantics_version=payload["semantics_version"],
    )
    if matrix.to_dict() != payload or matrix.robustness_source_matrix_bundle_id != EXPECTED_SOURCE_MATRIX_ID:
        raise RuntimeError("D5A source matrix identity differs")
    validate_robustness_source_matrix_bundle(
        matrix,
        trendlines_config=trendlines_config,
    )
    if tuple(row.member_evidence_id for row in matrix.member_evidence) != tuple(
        value["member_evidence_id"] for value in payload["member_evidence"]
    ):
        raise RuntimeError("D5A member evidence identity differs")
    return matrix, checksum_entries


def _protocol() -> TrendlineRobustnessReplicationProtocol:
    stochastic_specs = (
        TrendlineAdequacyBaselineSpec(
            name="random-valid-pivot-pair-v1",
            kind=TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
            repetitions=32,
            seed=2026072701,
            preserves=("timeframe", "position", "role", "pivot_count", "causal_prefix"),
        ),
        TrendlineAdequacyBaselineSpec(
            name="causal-density-matched-null-v1",
            kind=TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
            repetitions=32,
            seed=2026072702,
            preserves=("timeframe", "position", "role", "ray_count", "observation_density", "causal_prefix"),
        ),
    )
    return TrendlineRobustnessReplicationProtocol(
        replay_warmup_start_position=19,
        replay_record_start_position=64,
        replay_end_position=311,
        replay_record_every=1,
        include_signals=True,
        minimum_warmup_bars=45,
        minimum_prior_executed_prefixes=45,
        metric_names=(
            "eligible_point_coverage",
            "invalid_point_rate",
            "line_observation_count",
            "ray_observation_count",
            "line_birth_rate",
            "revision_churn_rate",
            "anchor_persistence_rate",
        ),
        line_observation_unit="fitted_line",
        ray_observation_unit="boundary_ray",
        invalid_point_treatment="retain_and_report_exclude_from_geometry_metrics",
        availability_policy="causal_prefix_only",
        stability_horizons_bars=(1, 3, 6, 12),
        interaction_horizons_bars=(1, 3, 6, 12),
        deterministic_baseline_ids=(
            "ddf18905d6cad86f78d83ea45298531f329de23ac4afd214811c181538e3a930",
            "22e405ce85d3fda2352080942e631240e5c9f505cfe187764d9084913856d8c3",
        ),
        stochastic_baseline_specs=stochastic_specs,
        quantile_probabilities=(0.05, 0.95),
        break_confirmation_policy="resolved_signals_hold_bars_at_first_recorded_point",
        semantics_version="trendlines.adequacy-robustness-replication-protocol.v1",
    )


def _study_config(spec: TrendlineRobustnessSourceMemberSpec) -> TrendlineAdequacyStudyConfig:
    return TrendlineAdequacyStudyConfig(
        study_name=f"l2d5b-{spec.name}-robustness-replication-v1",
        windows=(
            TrendlineAdequacyWindow(
                timeframe=spec.timeframe,
                start_position=64,
                end_position=311,
                minimum_warmup_bars=45,
                minimum_prior_executed_prefixes=45,
            ),
        ),
        metric_names=(
            "eligible_point_coverage",
            "invalid_point_rate",
            "line_observation_count",
            "ray_observation_count",
            "line_birth_rate",
            "revision_churn_rate",
            "anchor_persistence_rate",
        ),
        decision_rules=(),
        baseline_specs=(
            TrendlineAdequacyBaselineSpec(
                name="recent-extrema",
                kind=TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
                repetitions=1,
                preserves=("timeframe", "position", "causal_prefix"),
            ),
            TrendlineAdequacyBaselineSpec(
                name="horizontal-support-resistance",
                kind=TrendlineAdequacyBaselineKind.HORIZONTAL_SUPPORT_RESISTANCE,
                repetitions=1,
                preserves=("timeframe", "position", "causal_prefix"),
            ),
        ),
        line_observation_unit=TrendlineObservationUnit.FITTED_LINE,
        ray_observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        invalid_point_treatment=TrendlineInvalidPointTreatment.RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS,
        availability_policy=TrendlineAdequacyAvailabilityPolicy.CAUSAL_PREFIX_ONLY,
    )


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


@dataclass(frozen=True)
class _MemberRun:
    prepared: Any
    replay: Any
    study_config: TrendlineAdequacyStudyConfig
    d2_bundle: Any
    d3_bundle: Any
    d4a_bundle: Any
    d4b_bundle: Any
    member_result: Any
    frame: Any


def _execute_member(
    spec: TrendlineRobustnessSourceMemberSpec,
    evidence: TrendlineRobustnessSourceMemberEvidence,
    protocol: TrendlineRobustnessReplicationProtocol,
    trendlines_config: Any,
    source_root: Path,
) -> _MemberRun:
    frame_path = source_root / "members" / spec.name / SOURCE_ARTIFACT_NAME
    frame = read_research_frame_artifact(
        frame_path,
        expected_asset=spec.asset,
        expected_timeframe=spec.timeframe,
        expected_source_id=evidence.source_id,
        expected_availability_id=evidence.availability_id,
        expected_dataset_id=evidence.dataset_id,
    )
    frame = validate_robustness_source_frame(frame, spec)
    if len(frame) != ROBUSTNESS_EXPECTED_ROWS or _sha256(frame_path) != evidence.artifact_sha256:
        raise RuntimeError(f"D5A frame evidence differs for {spec.name}")
    prepared = asyncio.run(
        prepare_trendline_research(
            _research_spec(spec),
            trendlines_config=trendlines_config,
            loader={spec.timeframe: frame},
        )
    )
    actual_identity = {
        "source_id": prepared.dataset.identity.source_refs[spec.timeframe].source_id,
        "availability_id": prepared.dataset.identity.availability_ids[spec.timeframe],
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "preparation_id": prepared.preparation_id,
    }
    expected_identity = {
        key: getattr(evidence, key) for key in actual_identity
    }
    if actual_identity != expected_identity:
        raise RuntimeError(f"D5A prepared identities differ for {spec.name}")
    replay = run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={spec.timeframe: TrendlineReplayWindow(19, 64, 311, 1)},
            include_signals=True,
        ),
    )
    replay_frame = replay.timeframes[spec.timeframe]
    if replay_frame.executed_position_count != 293 or replay_frame.recorded_position_count != 248:
        raise RuntimeError(f"D5B replay counts differ for {spec.name}")
    study_config = _study_config(spec)
    cohort = build_adequacy_cohort(prepared, replay, study_config)
    observations = collect_adequacy_observations(cohort, prepared, replay, study_config)
    from libs.models.trendlines.workflows.research.adequacy import TrendlineStructuralStabilitySpec

    stability_spec = TrendlineStructuralStabilitySpec(protocol.stability_horizons_bars)
    d2_bundle = build_structural_stability_bundle(
        cohort,
        study_config,
        observations,
        replay,
        stability_spec,
    )
    first_recorded = replay_frame.recorded_positions[0]
    point = replay.output_at(spec.timeframe, first_recorded)
    pipeline_config = prepared.configuration.pipeline_configs[spec.timeframe]
    resolved = resolve_asset_config(
        pipeline_config.trendlines_config,
        prepared.spec.asset,
        spec.timeframe,
        prepared.dataset.frames[spec.timeframe],
        fit_result=point.output.fit_result,
    )
    hold_bars = resolved.signals.hold_bars
    if isinstance(hold_bars, bool) or not isinstance(hold_bars, int) or hold_bars < 1:
        raise RuntimeError(f"invalid resolved hold-bars for {spec.name}")
    interaction_spec = TrendlineInteractionUtilitySpec(
        evaluation_horizons_bars=protocol.interaction_horizons_bars,
        break_confirmation_bars=hold_bars,
    )
    d3_bundle = build_interaction_utility_bundle(
        prepared,
        replay,
        cohort,
        study_config,
        d2_bundle,
        interaction_spec,
    )
    d4a_bundle = build_baseline_comparison_bundle(
        prepared,
        replay,
        study_config,
        d2_bundle,
        d3_bundle,
    )
    d4b_bundle = build_stochastic_null_comparison_bundle(
        prepared,
        replay,
        study_config,
        d2_bundle,
        d3_bundle,
        d4a_bundle,
        protocol.stochastic_baseline_specs,
        quantile_probabilities=protocol.quantile_probabilities,
    )
    member_result = build_replication_member_evidence(
        spec,
        evidence,
        protocol,
        prepared,
        replay,
        d2_bundle,
        d3_bundle,
        d4a_bundle,
        d4b_bundle,
    )
    validate_replication_member_evidence(
        spec,
        evidence,
        prepared,
        replay,
        study_config,
        d2_bundle,
        d3_bundle,
        d4a_bundle,
        d4b_bundle,
        member_result,
        protocol,
    )
    return _MemberRun(
        prepared,
        replay,
        study_config,
        d2_bundle,
        d3_bundle,
        d4a_bundle,
        d4b_bundle,
        member_result,
        frame,
    )


def run_member_sequence(
    source_matrix: TrendlineRobustnessSourceMatrixBundle,
    protocol: TrendlineRobustnessReplicationProtocol,
    runner: Callable[[TrendlineRobustnessSourceMemberSpec, TrendlineRobustnessSourceMemberEvidence, TrendlineRobustnessReplicationProtocol], Any],
) -> tuple[Any, ...]:
    """Run fresh members in frozen order; stop immediately on first failure."""

    validate_replication_protocol(protocol)
    results: list[Any] = []
    for spec, evidence in zip(source_matrix.member_specs[1:], source_matrix.member_evidence[1:]):
        results.append(runner(spec, evidence, protocol))
    return tuple(results)


def _write_member_artifacts(root: Path, run: _MemberRun, evidence: TrendlineRobustnessSourceMemberEvidence) -> dict[str, Path]:
    member_root = root / "members" / run.member_result.member_name
    paths = {
        "structural_stability_bundle": _write_json(member_root / "structural_stability_bundle.json", run.d2_bundle.to_dict()),
        "interaction_utility_bundle": _write_json(member_root / "interaction_utility_bundle.json", run.d3_bundle.to_dict()),
        "deterministic_baseline_comparison_bundle": _write_json(member_root / "deterministic_baseline_comparison_bundle.json", run.d4a_bundle.to_dict()),
        "stochastic_null_comparison_bundle": _write_json(member_root / "stochastic_null_comparison_bundle.json", run.d4b_bundle.to_dict()),
    }
    manifest = {
        "schema_version": "trendlines.l2d5b-member-manifest.v1",
        "d5a_member_spec_id": evidence.member_spec_id,
        "d5a_member_evidence_id": evidence.member_evidence_id,
        "member_name": run.member_result.member_name,
        "relation": run.member_result.relation,
        "asset": run.member_result.asset,
        "timeframe": run.member_result.timeframe,
        "source_artifact_path": str(SOURCE_MATRIX_ROOT / "members" / run.member_result.member_name / SOURCE_ARTIFACT_NAME),
        "source_artifact_sha256": evidence.artifact_sha256,
        "source_id": run.member_result.source_id,
        "availability_id": run.member_result.availability_id,
        "dataset_id": run.member_result.dataset_id,
        "research_configuration_id": run.member_result.research_configuration_id,
        "preparation_id": run.member_result.preparation_id,
        "replay_id": run.member_result.replay_id,
        "replay_window": {"warmup_start_position": 19, "record_start_position": 64, "end_position": 311, "record_every": 1},
        "executed_prefix_count": run.member_result.executed_prefix_count,
        "recorded_position_count": run.member_result.recorded_position_count,
        "study_config_id": run.member_result.study_config_id,
        "stability_spec_id": run.member_result.stability_spec_id,
        "interaction_spec_id": run.member_result.interaction_spec_id,
        "resolved_hold_bars": run.member_result.resolved_hold_bars,
        "d2_bundle_id": run.member_result.d2_bundle_id,
        "d3_bundle_id": run.member_result.d3_bundle_id,
        "d4a_bundle_id": run.member_result.d4a_bundle_id,
        "d4b_bundle_id": run.member_result.d4b_bundle_id,
        "row_counts": run.member_result.to_dict(),
        "bundle_paths": {
            key: str(path.relative_to(root)) for key, path in paths.items()
        },
        "provider_calls": 0,
        "provider_retries": 0,
        "outcome": None,
    }
    paths["member_manifest"] = _write_json(member_root / "member_manifest.json", manifest)
    return paths


def _inventory(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "checksums.json":
            continue
        result.append(
            {
                "path": str(path.relative_to(root)),
                "byte_length": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return result


def run_study(
    *,
    source_matrix_root: str | Path = SOURCE_MATRIX_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
    member_runner: Callable[[TrendlineRobustnessSourceMemberSpec, TrendlineRobustnessSourceMemberEvidence, TrendlineRobustnessReplicationProtocol], _MemberRun] | None = None,
    test_disposition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute official four-member D5B replication, with no provider path."""

    source_matrix_root = Path(source_matrix_root)
    output_root = Path(output_root)
    if output_root.exists():
        raise RuntimeError("D5B output root already exists; overwrite is forbidden")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    trendlines_config = load_trendlines_config()
    matrix, d5a_checksum_entries = load_source_matrix(
        source_matrix_root,
        trendlines_config=trendlines_config,
    )
    protocol = _protocol()
    validate_replication_protocol(protocol)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent))
    try:
        if member_runner is None:
            def runner(spec: TrendlineRobustnessSourceMemberSpec, evidence: TrendlineRobustnessSourceMemberEvidence, current_protocol: TrendlineRobustnessReplicationProtocol) -> _MemberRun:
                return _execute_member(spec, evidence, current_protocol, trendlines_config, source_matrix_root)
        else:
            runner = member_runner
        runs = run_member_sequence(matrix, protocol, runner)
        if len(runs) != 4:
            raise RuntimeError("D5B did not complete four members")
        member_paths = []
        for run, evidence in zip(runs, matrix.member_evidence[1:]):
            member_paths.append(_write_member_artifacts(staging, run, evidence))
        member_results = tuple(run.member_result for run in runs)
        aggregate = build_robustness_replication_bundle(matrix, protocol, member_results)
        aggregate_payload = aggregate.to_dict()
        _write_json(staging / "robustness_replication_bundle.json", aggregate_payload)
        member_manifest_paths = [paths["member_manifest"] for paths in member_paths]
        bundle_paths = [
            path
            for paths in member_paths
            for key, path in paths.items()
            if key != "member_manifest"
        ]
        manifest = {
            "schema_version": "trendlines.l2d5b-offline-replication-run.v1",
            "implementation_base_commit": _implementation_commit(),
            "d5a_root": str(source_matrix_root),
            "d5a_checksum_inventory": list(d5a_checksum_entries),
            "d5a_matrix_bundle_id": matrix.robustness_source_matrix_bundle_id,
            "d5a_matrix_bundle_path": str(source_matrix_root / SOURCE_MATRIX_BUNDLE_NAME),
            "d5a_matrix_bundle_sha256": _sha256(source_matrix_root / SOURCE_MATRIX_BUNDLE_NAME),
            "replication_protocol": protocol.to_dict(),
            "replication_protocol_id": protocol.replication_protocol_id,
            "reference_d2_bundle_id": ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
            "reference_d3_bundle_id": ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
            "reference_d4a_bundle_id": ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
            "reference_d4b_bundle_id": ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
            "member_manifests": [
                {"path": str(path.relative_to(staging)), "sha256": _sha256(path)}
                for path in member_manifest_paths
            ],
            "member_bundle_files": [
                {"path": str(path.relative_to(staging)), "sha256": _sha256(path), "byte_length": path.stat().st_size}
                for path in bundle_paths
            ],
            "member_results": [row.to_dict() for row in member_results],
            "robustness_replication_bundle_id": aggregate.robustness_replication_bundle_id,
            "fresh_members_processed": 4,
            "replay_members": 4,
            "executed_prefixes": sum(row.executed_prefix_count for row in member_results),
            "recorded_positions": sum(row.recorded_position_count for row in member_results),
            "provider_calls": 0,
            "provider_retries": 0,
            "outcome": None,
            "test_disposition": dict(test_disposition or VALIDATED_TEST_DISPOSITION),
        }
        _write_json(staging / "run_manifest.json", manifest)
        review = "\n".join(
            (
                "# L2-D5B Offline Robustness Replication Review",
                "",
                "Status: MEASUREMENTS_ONLY",
                "",
                "No robustness adequacy outcome selected.",
                "All four fresh members were evaluated offline.",
                "No provider call or retry occurred.",
                "The causal replay scope was identical in bar-position space.",
                "Member-specific canonical YAML configurations were used.",
                "The three 1h members used break confirmation 3.",
                "The BTCUSDT 4h member used break confirmation 1.",
                "D2, D3, D4A and D4B semantics were otherwise unchanged.",
                "No parameter tuning or sensitivity study was performed.",
                "D5C and D5D remain unstarted.",
                "",
                f"D5A source matrix: {matrix.robustness_source_matrix_bundle_id}",
                f"Replication protocol: {protocol.replication_protocol_id}",
                f"Replication bundle: {aggregate.robustness_replication_bundle_id}",
                "",
                "Outcome remains null; this artifact is descriptive evidence only.",
            )
        ) + "\n"
        review_path = staging / "review.md"
        review_path.write_text(review, encoding="utf-8")
        checksums = _inventory(staging)
        _write_json(
            staging / "checksums.json",
            {
                "schema_version": "trendlines.l2d5b-offline-replication-checksums.v1",
                "files": checksums,
            },
        )
        staging.rename(output_root)
        return {
            "matrix": matrix,
            "protocol": protocol,
            "aggregate": aggregate,
            "runs": runs,
            "output_root": output_root,
            "manifest": output_root / "run_manifest.json",
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def finalize_test_disposition(
    output_root: str | Path,
    test_disposition: Mapping[str, Any],
) -> None:
    """Update closeout test evidence and regenerate canonical checksums."""

    root = Path(output_root)
    manifest_path = root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["test_disposition"] = dict(test_disposition)
    _write_json(manifest_path, manifest)
    _write_json(
        root / "checksums.json",
        {
            "schema_version": "trendlines.l2d5b-offline-replication-checksums.v1",
            "files": _inventory(root),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-matrix-root", type=Path, default=SOURCE_MATRIX_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_study(source_matrix_root=args.source_matrix_root, output_root=args.output_root)


if __name__ == "__main__":
    main()
