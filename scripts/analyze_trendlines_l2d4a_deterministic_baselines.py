"""Run the bounded, offline L2-D4A deterministic baseline comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from libs.models.trendlines.workflows.research.adequacy import (
    TrendlineInteractionUtilitySpec,
    TrendlineStructuralStabilitySpec,
    build_adequacy_cohort,
    build_baseline_comparison_bundle,
    build_structural_stability_bundle,
    collect_adequacy_observations,
)
from scripts import analyze_trendlines_l2d3_interaction_utility as d3_script
from scripts.analyze_trendlines_l2d2_structural_stability import (
    DEFAULT_HORIZONS,
    _study_config,
)


DEFAULT_OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_btcusdt_1h_l2d4a_deterministic_naive_baselines_v1"
)
D3_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_btcusdt_1h_l2d3_interaction_utility_v1"
)
D3_BUNDLE_NAME = "interaction_utility_bundle.json"
EXPECTED_D3_BUNDLE_ID = (
    "56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4"
)
IMPLEMENTATION_BASE_COMMIT = "dbe6c8dcff80396c42f92a27bf53f31facc3f8a6"
VALIDATED_TEST_DISPOSITION = {
    "status": "PASSED",
    "d4a_focused": "36 passed",
    "analysis_script": "4 passed",
    "d3_focused": "48 passed",
    "canonical_mature_trendlines": "634 passed",
    "viewer_python": "30 passed",
    "viewer_node": "23 passed",
    "consumer_ingestion_bridge": "79 passed",
    "offline_workflows": "20 passed",
    "provider_calls": 0,
    "provider_retries": 0,
    "ruff_compileall_diff_check": "passed",
}


def _canonical_json(payload: object) -> bytes:
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


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(payload))
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checksums(root: Path) -> None:
    payload = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
    for member in payload["files"]:
        path = root / member["path"]
        if not path.is_file():
            raise RuntimeError(f"missing checksum member: {path}")
        if path.stat().st_size != member["byte_length"]:
            raise RuntimeError(f"checksum byte length differs: {path}")
        if _sha256(path) != member["sha256"]:
            raise RuntimeError(f"checksum differs: {path}")


def _reconstruct_context(source_root: Path, d2_root: Path, d3_root: Path):
    _verify_checksums(d2_root)
    _verify_checksums(d3_root)
    d2_payload = json.loads(
        (d2_root / d3_script.D2_BUNDLE_NAME).read_text(encoding="utf-8")
    )
    d3_payload = json.loads((d3_root / D3_BUNDLE_NAME).read_text(encoding="utf-8"))
    if d2_payload["structural_stability_bundle_id"] != d3_script.EXPECTED_D2_BUNDLE_ID:
        raise RuntimeError("committed D2 bundle identity differs")
    if d3_payload["interaction_utility_bundle_id"] != EXPECTED_D3_BUNDLE_ID:
        raise RuntimeError("committed D3 bundle identity differs")

    prepared, replay, source_identity, frame = d3_script._prepare_and_replay(source_root)
    study_config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, study_config)
    observations = collect_adequacy_observations(
        cohort,
        prepared,
        replay,
        study_config,
    )
    stability_spec = TrendlineStructuralStabilitySpec(DEFAULT_HORIZONS)
    d2_bundle = build_structural_stability_bundle(
        cohort,
        study_config,
        observations,
        replay,
        stability_spec,
    )
    if d2_bundle.structural_stability_bundle_id != d3_script.EXPECTED_D2_BUNDLE_ID:
        raise RuntimeError("reconstructed D2 bundle identity differs")
    if d2_bundle.to_dict() != d2_payload:
        raise RuntimeError("reconstructed D2 evidence differs from committed artifact")
    confirmation_bars = d3_script._resolved_confirmation_bars(prepared, replay)
    interaction_spec = TrendlineInteractionUtilitySpec(
        evaluation_horizons_bars=d3_script.DEFAULT_HORIZONS,
        break_confirmation_bars=confirmation_bars,
    )
    from libs.models.trendlines.workflows.research.adequacy import (
        build_interaction_utility_bundle,
    )

    d3_bundle = build_interaction_utility_bundle(
        prepared,
        replay,
        cohort,
        study_config,
        d2_bundle,
        interaction_spec,
    )
    if d3_bundle.interaction_utility_bundle_id != EXPECTED_D3_BUNDLE_ID:
        raise RuntimeError("reconstructed D3 bundle identity differs")
    if d3_bundle.to_dict() != d3_payload:
        raise RuntimeError("reconstructed D3 evidence differs from committed artifact")
    return {
        "prepared": prepared,
        "replay": replay,
        "source_identity": source_identity,
        "frame": frame,
        "cohort": cohort,
        "study_config": study_config,
        "stability_spec": stability_spec,
        "d2_bundle": d2_bundle,
        "interaction_spec": interaction_spec,
        "d3_bundle": d3_bundle,
    }


def _selection_inventory(bundle) -> dict[str, object]:
    inventory: dict[str, object] = {}
    for spec in bundle.baseline_specs:
        values = tuple(
            value
            for value in bundle.baseline_selections
            if value.baseline_id == spec.baseline_id
        )
        by_role = {}
        for role in ("support", "resistance"):
            role_values = tuple(value for value in values if value.role == role)
            by_role[role] = {
                "attempts": len(role_values),
                "available": sum(value.available for value in role_values),
                "abstentions": sum(not value.available for value in role_values),
                "coverage_rate": (
                    sum(value.available for value in role_values) / len(role_values)
                    if role_values
                    else None
                ),
            }
        inventory[spec.name] = {
            "baseline_id": spec.baseline_id,
            "kind": spec.kind.value,
            "attempts": len(values),
            "available": sum(value.available for value in values),
            "abstentions": sum(not value.available for value in values),
            "coverage_rate": sum(value.available for value in values) / len(values),
            "by_role": by_role,
        }
    return inventory


def run_study(
    *,
    source_root: str | Path = d3_script.SOURCE_ROOT,
    d2_root: str | Path = d3_script.D2_ROOT,
    d3_root: str | Path = D3_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, object]:
    """Reconstruct committed evidence and persist one D4A comparison."""

    source_root = Path(source_root)
    d2_root = Path(d2_root)
    d3_root = Path(d3_root)
    output_root = Path(output_root)
    context = _reconstruct_context(source_root, d2_root, d3_root)
    comparison_bundle = build_baseline_comparison_bundle(
        context["prepared"],
        context["replay"],
        context["study_config"],
        context["d2_bundle"],
        context["d3_bundle"],
    )
    selections = comparison_bundle.baseline_selections
    comparison_payload = comparison_bundle.to_dict()
    comparison_summaries = [
        summary.to_dict()
        for summary in comparison_bundle.comparison_summaries
    ]
    if len(comparison_summaries) != 16:
        raise RuntimeError("D4A comparison summary inventory must contain 16 rows")
    if comparison_summaries != comparison_payload["comparison_summaries"]:
        raise RuntimeError("manifest comparison summaries differ from bundle rows")
    manifest = {
        "schema_version": "trendlines.l2d4a-deterministic-baseline-run.v1",
        "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
        "source_artifact_path": str(source_root / d3_script.SOURCE_ARTIFACT_NAME),
        "source_artifact_sha256": _sha256(source_root / d3_script.SOURCE_ARTIFACT_NAME),
        "d2_artifact_path": str(d2_root / d3_script.D2_BUNDLE_NAME),
        "d2_artifact_sha256": _sha256(d2_root / d3_script.D2_BUNDLE_NAME),
        "d3_artifact_path": str(d3_root / D3_BUNDLE_NAME),
        "d3_artifact_sha256": _sha256(d3_root / D3_BUNDLE_NAME),
        "source_id": context["prepared"].dataset.identity.source_refs["1h"].source_id,
        "availability_id": context["prepared"].dataset.identity.availability_ids["1h"],
        "dataset_id": context["prepared"].dataset.dataset_id,
        "research_configuration_id": context["prepared"].configuration.research_configuration_id,
        "preparation_id": context["prepared"].preparation_id,
        "replay_id": context["replay"].replay_id,
        "cohort_id": context["cohort"].cohort_id,
        "study_config_id": context["study_config"].study_config_id,
        "stability_spec_id": context["stability_spec"].stability_spec_id,
        "structural_stability_bundle_id": context["d2_bundle"].structural_stability_bundle_id,
        "interaction_spec_id": context["interaction_spec"].interaction_spec_id,
        "interaction_utility_bundle_id": context["d3_bundle"].interaction_utility_bundle_id,
        "baseline_specs": [spec.to_dict() for spec in comparison_bundle.baseline_specs],
        "baseline_ids": {
            spec.name: spec.baseline_id for spec in comparison_bundle.baseline_specs
        },
        "baseline_comparison_bundle_id": comparison_bundle.baseline_comparison_bundle_id,
        "rows": len(context["frame"]),
        "executed_positions": context["replay"].timeframes["1h"].executed_position_count,
        "recorded_positions": context["replay"].timeframes["1h"].recorded_position_count,
        "model_event_count": len(comparison_bundle.model_event_ids),
        "selection_attempts": len(selections),
        "selection_inventory": _selection_inventory(comparison_bundle),
        "available_selections": sum(value.available for value in selections),
        "abstentions": sum(not value.available for value in selections),
        "baseline_outcome_count": len(comparison_bundle.baseline_outcomes),
        "comparison_summary_count": len(comparison_bundle.comparison_summaries),
        "comparison_summaries": comparison_summaries,
        "provider_calls": 0,
        "provider_retries": 0,
        "test_disposition": VALIDATED_TEST_DISPOSITION,
        "outcome": None,
    }
    review = "\n".join(
        (
            "# L2-D4A Deterministic Baseline Comparison Review",
            "",
            "Status: MEASUREMENTS_ONLY",
            "",
            "Comparison is conditional on mature-model event timing.",
            "Only deterministic frozen naive baselines were executed.",
            "No baseline-comparison adequacy outcome selected.",
            "No random, shuffled or density-matched null was executed.",
            "No parameter tuning performed.",
            "No model interaction labels used as ground truth.",
            "No provider call made; committed artifacts were reloaded.",
            "",
            f"D2 structural bundle: {context['d2_bundle'].structural_stability_bundle_id}",
            f"D3 interaction bundle: {context['d3_bundle'].interaction_utility_bundle_id}",
            f"Baseline comparison bundle: {comparison_bundle.baseline_comparison_bundle_id}",
            f"Model events: {len(comparison_bundle.model_event_ids)}",
            f"Selection attempts: {len(selections)}",
            f"Available selections: {sum(value.available for value in selections)}",
            f"Abstentions: {sum(not value.available for value in selections)}",
            "",
            "Outcome remains null; this artifact is descriptive evidence only.",
        )
    ) + "\n"
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = _write_json(output_root / "run_manifest.json", manifest)
    bundle_path = _write_json(
        output_root / "baseline_comparison_bundle.json",
        comparison_payload,
    )
    review_path = output_root / "review.md"
    review_path.write_text(review, encoding="utf-8")
    files = [manifest_path, bundle_path, review_path]
    checksums_path = _write_json(
        output_root / "checksums.json",
        {
            "schema_version": "trendlines.l2d4a-deterministic-baseline-checksums.v1",
            "files": [
                {
                    "path": str(path.relative_to(output_root)),
                    "byte_length": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in sorted(
                    files,
                    key=lambda value: str(value.relative_to(output_root)),
                )
            ],
        },
    )
    return {
        **context,
        "comparison_bundle": comparison_bundle,
        "paths": {
            "run_manifest": manifest_path,
            "baseline_comparison_bundle": bundle_path,
            "review": review_path,
            "checksums": checksums_path,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=d3_script.SOURCE_ROOT)
    parser.add_argument("--d2-root", type=Path, default=d3_script.D2_ROOT)
    parser.add_argument("--d3-root", type=Path, default=D3_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    result = run_study(
        source_root=args.source_root,
        d2_root=args.d2_root,
        d3_root=args.d3_root,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "baseline_comparison_bundle_id": result[
                    "comparison_bundle"
                ].baseline_comparison_bundle_id
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
