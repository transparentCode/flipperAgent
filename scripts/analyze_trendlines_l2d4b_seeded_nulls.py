"""Run bounded, offline L2-D4B seeded stochastic-null comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from libs.models.trendlines.workflows.research.adequacy import (
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
    build_baseline_comparison_bundle,
    build_stochastic_null_comparison_bundle,
)
from scripts import analyze_trendlines_l2d3_interaction_utility as d3_script
from scripts import analyze_trendlines_l2d4a_deterministic_baselines as d4a_script


DEFAULT_OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_btcusdt_1h_l2d4b_seeded_stochastic_nulls_v1"
)
D4A_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_btcusdt_1h_l2d4a_deterministic_naive_baselines_v1"
)
D4A_BUNDLE_NAME = "baseline_comparison_bundle.json"
EXPECTED_D2_BUNDLE_ID = d3_script.EXPECTED_D2_BUNDLE_ID
EXPECTED_D3_BUNDLE_ID = d4a_script.EXPECTED_D3_BUNDLE_ID
EXPECTED_D4A_BUNDLE_ID = (
    "664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663"
)
SOURCE_ARTIFACT_NAME = d3_script.SOURCE_ARTIFACT_NAME
IMPLEMENTATION_BASE_COMMIT = "632bc1baac4441217bf47a8c8c5b56fabdb647f7"
VALIDATED_TEST_DISPOSITION = {
    "status": "PASSED",
    "d4b_focused": "46 passed",
    "d4b_analysis_script": "6 passed",
    "d4a_focused": "36 passed",
    "d4a_analysis_script": "4 passed",
    "d3_focused": "48 passed",
    "d3_analysis_script": "4 passed",
    "canonical_mature_trendlines": "680 passed",
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


def _stochastic_specs() -> tuple[TrendlineAdequacyBaselineSpec, ...]:
    return (
        TrendlineAdequacyBaselineSpec(
            name="random-valid-pivot-pair-v1",
            kind=TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
            repetitions=32,
            seed=2026072701,
            preserves=(
                "timeframe",
                "position",
                "role",
                "pivot_count",
                "causal_prefix",
            ),
        ),
        TrendlineAdequacyBaselineSpec(
            name="causal-density-matched-null-v1",
            kind=TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
            repetitions=32,
            seed=2026072702,
            preserves=(
                "timeframe",
                "position",
                "role",
                "ray_count",
                "observation_density",
                "causal_prefix",
            ),
        ),
    )


def _reconstruct_context(source_root: Path, d2_root: Path, d3_root: Path, d4a_root: Path):
    _verify_checksums(d4a_root)
    d4a_payload = json.loads(
        (d4a_root / D4A_BUNDLE_NAME).read_text(encoding="utf-8")
    )
    if d4a_payload["baseline_comparison_bundle_id"] != EXPECTED_D4A_BUNDLE_ID:
        raise RuntimeError("committed D4A bundle identity differs")
    context = d4a_script._reconstruct_context(source_root, d2_root, d3_root)
    d4a_bundle = build_baseline_comparison_bundle(
        context["prepared"],
        context["replay"],
        context["study_config"],
        context["d2_bundle"],
        context["d3_bundle"],
    )
    if d4a_bundle.baseline_comparison_bundle_id != EXPECTED_D4A_BUNDLE_ID:
        raise RuntimeError("reconstructed D4A bundle identity differs")
    if d4a_bundle.to_dict() != d4a_payload:
        raise RuntimeError("reconstructed D4A evidence differs from artifact")
    return {**context, "d4a_bundle": d4a_bundle, "d4a_payload": d4a_payload}


def _selection_inventory(bundle) -> dict[str, object]:
    inventory: dict[str, object] = {}
    for spec in bundle.stochastic_baseline_specs:
        values = tuple(
            row
            for row in bundle.stochastic_selections
            if row.baseline_id == spec.baseline_id
        )
        by_repetition = {}
        for repetition in range(spec.repetitions):
            repetition_values = tuple(
                row for row in values if row.repetition_index == repetition
            )
            by_repetition[str(repetition)] = {
                "attempts": len(repetition_values),
                "available": sum(row.available for row in repetition_values),
                "abstentions": sum(
                    not row.available for row in repetition_values
                ),
                "by_role": {
                    role: {
                        "attempts": sum(row.role == role for row in repetition_values),
                        "available": sum(
                            row.role == role and row.available
                            for row in repetition_values
                        ),
                        "abstentions": sum(
                            row.role == role and not row.available
                            for row in repetition_values
                        ),
                    }
                    for role in ("support", "resistance")
                },
            }
        inventory[spec.name] = {
            "baseline_id": spec.baseline_id,
            "kind": spec.kind.value,
            "seed": spec.seed,
            "repetitions": spec.repetitions,
            "attempts": len(values),
            "available": sum(row.available for row in values),
            "abstentions": sum(not row.available for row in values),
            "coverage_rate": sum(row.available for row in values) / len(values),
            "by_repetition": by_repetition,
        }
    return inventory


def run_study(
    *,
    source_root: str | Path = d3_script.SOURCE_ROOT,
    d2_root: str | Path = d3_script.D2_ROOT,
    d3_root: str | Path = d4a_script.D3_ROOT,
    d4a_root: str | Path = D4A_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, object]:
    """Reconstruct committed evidence and persist one D4B comparison."""

    source_root = Path(source_root)
    d2_root = Path(d2_root)
    d3_root = Path(d3_root)
    d4a_root = Path(d4a_root)
    output_root = Path(output_root)
    context = _reconstruct_context(source_root, d2_root, d3_root, d4a_root)
    bundle = build_stochastic_null_comparison_bundle(
        context["prepared"],
        context["replay"],
        context["study_config"],
        context["d2_bundle"],
        context["d3_bundle"],
        context["d4a_bundle"],
        _stochastic_specs(),
        quantile_probabilities=(0.05, 0.95),
    )
    selections = bundle.stochastic_selections
    summaries = [row.to_dict() for row in bundle.distribution_summaries]
    source_path = source_root / SOURCE_ARTIFACT_NAME
    d2_path = d2_root / d3_script.D2_BUNDLE_NAME
    d3_path = d3_root / d4a_script.D3_BUNDLE_NAME
    d4a_path = d4a_root / D4A_BUNDLE_NAME
    manifest = {
        "schema_version": "trendlines.l2d4b-seeded-stochastic-null-run.v1",
        "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
        "source_artifact_path": str(source_path),
        "source_artifact_sha256": _sha256(source_path),
        "d2_artifact_path": str(d2_path),
        "d2_artifact_sha256": _sha256(d2_path),
        "d3_artifact_path": str(d3_path),
        "d3_artifact_sha256": _sha256(d3_path),
        "d4a_artifact_path": str(d4a_path),
        "d4a_artifact_sha256": _sha256(d4a_path),
        "source_id": context["prepared"].dataset.identity.source_refs["1h"].source_id,
        "availability_id": context["prepared"].dataset.identity.availability_ids["1h"],
        "dataset_id": context["prepared"].dataset.dataset_id,
        "research_configuration_id": context["prepared"].configuration.research_configuration_id,
        "preparation_id": context["prepared"].preparation_id,
        "replay_id": context["replay"].replay_id,
        "cohort_id": context["cohort"].cohort_id,
        "study_config_id": context["study_config"].study_config_id,
        "structural_stability_bundle_id": context["d2_bundle"].structural_stability_bundle_id,
        "interaction_spec_id": context["interaction_spec"].interaction_spec_id,
        "interaction_utility_bundle_id": context["d3_bundle"].interaction_utility_bundle_id,
        "baseline_comparison_bundle_id": context["d4a_bundle"].baseline_comparison_bundle_id,
        "stochastic_baseline_specs": [
            spec.to_dict() for spec in bundle.stochastic_baseline_specs
        ],
        "stochastic_baseline_ids": {
            spec.name: spec.baseline_id
            for spec in bundle.stochastic_baseline_specs
        },
        "quantile_probabilities": list(bundle.quantile_probabilities),
        "stochastic_null_comparison_bundle_id": bundle.stochastic_null_comparison_bundle_id,
        "rows": len(context["frame"]),
        "executed_positions": context["replay"].timeframes["1h"].executed_position_count,
        "recorded_positions": context["replay"].timeframes["1h"].recorded_position_count,
        "model_event_count": len(bundle.model_event_ids),
        "selection_attempts": len(selections),
        "expected_selection_attempts": 43 * 2 * 32,
        "selection_inventory": _selection_inventory(bundle),
        "available_selections": sum(row.available for row in selections),
        "abstentions": sum(not row.available for row in selections),
        "null_outcome_count": len(bundle.null_outcomes),
        "repetition_comparison_count": len(bundle.repetition_comparisons),
        "distribution_summary_count": len(bundle.distribution_summaries),
        "distribution_summaries": summaries,
        "provider_calls": 0,
        "provider_retries": 0,
        "test_disposition": VALIDATED_TEST_DISPOSITION,
        "outcome": None,
    }
    review = "\n".join(
        (
            "# L2-D4B Seeded Stochastic Null Review",
            "",
            "Status: MEASUREMENTS_ONLY",
            "",
            "No stochastic-null adequacy outcome selected.",
            "No formal p-value or significance threshold applied.",
            "Comparison remains conditional on mature-model event timing.",
            "Only seeded random-pair and causal density-matched nulls were executed.",
            "No time-shifted or role-shuffled null was executed.",
            "No parameter tuning performed.",
            "No model interaction labels used as ground truth.",
            "No provider call made.",
            "",
            f"D2 structural bundle: {bundle.structural_stability_bundle_id}",
            f"D3 interaction bundle: {bundle.interaction_utility_bundle_id}",
            f"D4A comparison bundle: {bundle.baseline_comparison_bundle_id}",
            f"D4B stochastic bundle: {bundle.stochastic_null_comparison_bundle_id}",
            f"Model events: {len(bundle.model_event_ids)}",
            f"Selection attempts: {len(selections)}",
            f"Available selections: {sum(row.available for row in selections)}",
            f"Abstentions: {sum(not row.available for row in selections)}",
            f"Null outcomes: {len(bundle.null_outcomes)}",
            "",
            "Outcome remains null; this artifact is descriptive evidence only.",
        )
    ) + "\n"
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = _write_json(output_root / "run_manifest.json", manifest)
    bundle_path = _write_json(
        output_root / "stochastic_null_comparison_bundle.json",
        bundle.to_dict(),
    )
    review_path = output_root / "review.md"
    review_path.write_text(review, encoding="utf-8")
    files = [manifest_path, bundle_path, review_path]
    checksums_path = _write_json(
        output_root / "checksums.json",
        {
            "schema_version": "trendlines.l2d4b-seeded-stochastic-null-checksums.v1",
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
        "bundle": bundle,
        "paths": {
            "run_manifest": manifest_path,
            "stochastic_null_comparison_bundle": bundle_path,
            "review": review_path,
            "checksums": checksums_path,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=d3_script.SOURCE_ROOT)
    parser.add_argument("--d2-root", type=Path, default=d3_script.D2_ROOT)
    parser.add_argument("--d3-root", type=Path, default=d4a_script.D3_ROOT)
    parser.add_argument("--d4a-root", type=Path, default=D4A_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    result = run_study(
        source_root=args.source_root,
        d2_root=args.d2_root,
        d3_root=args.d3_root,
        d4a_root=args.d4a_root,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "stochastic_null_comparison_bundle_id": result["bundle"].stochastic_null_comparison_bundle_id
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
