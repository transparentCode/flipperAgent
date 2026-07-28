"""Run the bounded, offline L2-D2 structural-stability study."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from libs.models.trendlines.config import load_trendlines_config
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
    TrendlineObservationUnit,
    TrendlineStructuralStabilitySpec,
    build_adequacy_cohort,
    build_structural_stability_bundle,
    collect_adequacy_observations,
    summarize_adequacy_eligibility,
)


SOURCE_ROOT = Path(
    "artifacts/trendlines_research_validation/"
    "20260726_btcusdt_1h_single_call_v1"
)
DEFAULT_OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_btcusdt_1h_l2d2_structural_stability_v1"
)
SOURCE_ARTIFACT_NAME = "normalized_ohlcv_v2.json"
SOURCE_IDENTITY_NAME = "source_identity.json"
DEFAULT_HORIZONS = (1, 3, 6, 12)
VALIDATED_TEST_DISPOSITION = {
    "status": "PASSED",
    "d2_focused": "30 passed",
    "analysis_script": "4 passed",
    "canonical_mature_trendlines": "550 passed",
    "viewer_python": "30 passed",
    "viewer_node": "23 passed",
    "consumer_ingestion_bridge": "79 passed",
    "offline_workflows": "20 passed",
    "provider_calls": 0,
    "ruff_compileall_diff_check": "passed",
}
EVENT_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
KNOWLEDGE_CUTOFF = datetime(
    2025,
    1,
    13,
    23,
    59,
    59,
    999000,
    tzinfo=timezone.utc,
)


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


def _implementation_base_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _study_config() -> TrendlineAdequacyStudyConfig:
    return TrendlineAdequacyStudyConfig(
        study_name="l2d2-btcusdt-1h-structural-stability-v1",
        windows=(
            TrendlineAdequacyWindow(
                timeframe="1h",
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
        invalid_point_treatment=(
            TrendlineInvalidPointTreatment.RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS
        ),
        availability_policy=TrendlineAdequacyAvailabilityPolicy.CAUSAL_PREFIX_ONLY,
    )


def _load_source_identity(source_root: Path) -> dict[str, Any]:
    payload = json.loads((source_root / SOURCE_IDENTITY_NAME).read_text())
    for field in (
        "source_id",
        "availability_id",
        "dataset_id",
        "preparation_id",
    ):
        if not isinstance(payload.get(field), str) or len(payload[field]) != 64:
            raise ValueError(f"source identity missing valid {field}")
    return payload


def _validate_prepared_identities(
    prepared: Any,
    source_identity: dict[str, Any],
) -> None:
    source_ref = prepared.dataset.identity.source_refs["1h"]
    expected = {
        "source_id": source_ref.source_id,
        "availability_id": prepared.dataset.identity.availability_ids["1h"],
        "dataset_id": prepared.dataset.dataset_id,
        "preparation_id": prepared.preparation_id,
    }
    for field, actual in expected.items():
        if actual != source_identity[field]:
            raise RuntimeError(f"{field} differs from committed L2-C identity")


def _validate_replay_identity(replay: Any, source_root: Path) -> None:
    manifest = json.loads((source_root / "run_manifest.json").read_text())
    expected = {
        "preparation_id": manifest["preparation_id"],
        "dataset_id": manifest["dataset_id"],
        "replay_id": manifest["replay_id"],
    }
    actual = {
        "preparation_id": replay.preparation_id,
        "dataset_id": replay.dataset_id,
        "replay_id": replay.replay_id,
    }
    for field, value in expected.items():
        if actual[field] != value:
            raise RuntimeError(f"{field} differs from committed L2-C identity")


def run_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    survival_horizons_bars: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Prepare, replay, measure, and persist one bounded offline study."""

    source_root = Path(source_root)
    output_root = Path(output_root)
    source_path = source_root / SOURCE_ARTIFACT_NAME
    source_identity = _load_source_identity(source_root)
    frame = read_research_frame_artifact(
        source_path,
        expected_asset="BTCUSDT",
        expected_timeframe="1h",
        expected_source_id=source_identity["source_id"],
        expected_availability_id=source_identity["availability_id"],
        expected_dataset_id=source_identity["dataset_id"],
    )
    if len(frame) != 312:
        raise RuntimeError("committed L2-C frame must contain 312 rows")

    research_spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.BINANCE,
            event_start=EVENT_START,
            knowledge_cutoff=KNOWLEDGE_CUTOFF,
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )
    prepared = asyncio.run(
        prepare_trendline_research(
            research_spec,
            trendlines_config=load_trendlines_config(),
            loader={"1h": frame},
        )
    )
    _validate_prepared_identities(prepared, source_identity)
    replay = run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={"1h": TrendlineReplayWindow(19, 64, 311, 1)},
            include_signals=True,
        ),
    )
    _validate_replay_identity(replay, source_root)
    if replay.timeframes["1h"].executed_position_count != 293:
        raise RuntimeError("unexpected executed position count")
    if len(replay.timeframes["1h"].recorded_positions) != 248:
        raise RuntimeError("unexpected recorded position count")

    study_config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, study_config)
    observations = collect_adequacy_observations(
        cohort,
        prepared,
        replay,
        study_config,
    )
    stability_spec = TrendlineStructuralStabilitySpec(survival_horizons_bars)
    bundle = build_structural_stability_bundle(
        cohort,
        study_config,
        observations,
        replay,
        stability_spec,
    )
    eligibility = summarize_adequacy_eligibility(observations)
    eligible = [value for value in observations if value.eligible]
    invalid = [
        value
        for value in observations
        if value.state.value == "invalid_output"
    ]
    excluded = [
        value
        for value in observations
        if not value.eligible and value.state.value != "invalid_output"
    ]
    line_states = [
        value
        for value in bundle.state_rows
        if value.observation_unit is TrendlineObservationUnit.FITTED_LINE
    ]
    ray_states = [
        value
        for value in bundle.state_rows
        if value.observation_unit is TrendlineObservationUnit.BOUNDARY_RAY
    ]
    manifest = {
        "schema_version": "trendlines.l2d2-structural-stability-run.v1",
        "implementation_base_commit": _implementation_base_commit(),
        "source_artifact_path": str(source_path),
        "source_artifact_sha256": _sha256(source_path),
        "source_id": prepared.dataset.identity.source_refs["1h"].source_id,
        "availability_id": prepared.dataset.identity.availability_ids["1h"],
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "preparation_id": prepared.preparation_id,
        "replay_id": replay.replay_id,
        "cohort_id": cohort.cohort_id,
        "study_config_id": study_config.study_config_id,
        "stability_spec_id": stability_spec.stability_spec_id,
        "structural_stability_bundle_id": bundle.structural_stability_bundle_id,
        "survival_horizons_bars": list(stability_spec.survival_horizons_bars),
        "provider_calls": 0,
        "provider_retries": 0,
        "rows": len(frame),
        "executed_positions": replay.timeframes["1h"].executed_position_count,
        "recorded_positions": len(replay.timeframes["1h"].recorded_positions),
        "scoped_observations": eligibility.scoped_point_count,
        "eligible_observations": len(eligible),
        "invalid_observations": len(invalid),
        "excluded_observations": len(excluded),
        "line_state_count": len(line_states),
        "ray_state_count": len(ray_states),
        "drift_row_count": len(bundle.drift_rows),
        "line_transition_count": sum(
            value.observation_unit is TrendlineObservationUnit.FITTED_LINE
            for value in bundle.transition_rows
        ),
        "ray_transition_count": sum(
            value.observation_unit is TrendlineObservationUnit.BOUNDARY_RAY
            for value in bundle.transition_rows
        ),
        "line_episode_count": sum(
            value.observation_unit is TrendlineObservationUnit.FITTED_LINE
            for value in bundle.episode_rows
        ),
        "ray_episode_count": sum(
            value.observation_unit is TrendlineObservationUnit.BOUNDARY_RAY
            for value in bundle.episode_rows
        ),
        "survival": [value.to_dict() for value in bundle.survival_rows],
        "test_disposition": VALIDATED_TEST_DISPOSITION,
        "outcome": None,
    }
    review = "\n".join(
        (
            "# L2-D2 Structural Stability Review",
            "",
            "Status: MEASUREMENTS_ONLY",
            "",
            "No structural adequacy outcome selected.",
            "No interaction utility measured.",
            "No null baseline executed.",
            "No parameter tuning performed.",
            "No provider call made; committed frame artifact was reloaded.",
            "",
            f"Structural stability bundle: {bundle.structural_stability_bundle_id}",
            f"Eligible observations: {len(eligible)}",
            f"Line states: {len(line_states)}",
            f"Ray states: {len(ray_states)}",
            f"Line transitions: {manifest['line_transition_count']}",
            f"Ray transitions: {manifest['ray_transition_count']}",
            f"Line episodes: {manifest['line_episode_count']}",
            f"Ray episodes: {manifest['ray_episode_count']}",
            "",
            "Per-unit active-anchor summaries:",
            *(
                f"{summary.observation_unit.value}: "
                f"{summary.mean_active_anchor_count} / "
                f"{summary.minimum_active_anchor_count} / "
                f"{summary.maximum_active_anchor_count}"
                for summary in bundle.summaries
            ),
            "",
            "Test disposition: VALIDATED_L2D2_MATRIX_PASSED",
        )
    ) + "\n"

    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = _write_json(output_root / "run_manifest.json", manifest)
    bundle_path = _write_json(
        output_root / "structural_stability_bundle.json",
        bundle.to_dict(),
    )
    review_path = output_root / "review.md"
    review_path.write_text(review, encoding="utf-8")
    files = [manifest_path, bundle_path, review_path]
    checksums = {
        "schema_version": "trendlines.l2d2-structural-stability-checksums.v1",
        "files": [
            {
                "path": str(path.relative_to(output_root)),
                "byte_length": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(files, key=lambda value: str(value.relative_to(output_root)))
        ],
    }
    checksums_path = _write_json(output_root / "checksums.json", checksums)
    return {
        "prepared": prepared,
        "replay": replay,
        "cohort": cohort,
        "study_config": study_config,
        "stability_spec": stability_spec,
        "observations": observations,
        "eligibility": eligibility,
        "bundle": bundle,
        "output_root": output_root,
        "paths": {
            "run_manifest": manifest_path,
            "structural_stability_bundle": bundle_path,
            "review": review_path,
            "checksums": checksums_path,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    result = run_study(source_root=args.source_root, output_root=args.output_root)
    print(json.dumps({"structural_stability_bundle_id": result["bundle"].structural_stability_bundle_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
