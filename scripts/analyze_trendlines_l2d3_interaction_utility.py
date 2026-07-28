"""Run bounded, offline L2-D3 causal interaction measurements."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from libs.models.trendlines.config.resolve import resolve_asset_config
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
    TrendlineInteractionUtilitySpec,
    TrendlineStructuralStabilitySpec,
    build_adequacy_cohort,
    build_interaction_utility_bundle,
    build_structural_stability_bundle,
    collect_adequacy_observations,
)
from scripts.analyze_trendlines_l2d2_structural_stability import (
    EVENT_START,
    KNOWLEDGE_CUTOFF,
    SOURCE_ROOT,
    _load_source_identity,
    _study_config,
    _validate_prepared_identities,
    _validate_replay_identity,
)


DEFAULT_OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_btcusdt_1h_l2d3_interaction_utility_v1"
)
SOURCE_ARTIFACT_NAME = "normalized_ohlcv_v2.json"
D2_ROOT = Path(
    "artifacts/trendlines_research_adequacy/"
    "20260727_btcusdt_1h_l2d2_structural_stability_v1"
)
D2_BUNDLE_NAME = "structural_stability_bundle.json"
EXPECTED_D2_BUNDLE_ID = (
    "f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f"
)
DEFAULT_HORIZONS = (1, 3, 6, 12)
VALIDATED_TEST_DISPOSITION = {
    "status": "PASSED",
    "d3_focused": "48 passed",
    "analysis_script": "4 passed",
    "canonical_mature_trendlines": "598 passed",
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


def _research_spec() -> TrendlineResearchSpec:
    return TrendlineResearchSpec(
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


def _prepare_and_replay(source_root: Path):
    source_identity = _load_source_identity(source_root)
    frame = read_research_frame_artifact(
        source_root / SOURCE_ARTIFACT_NAME,
        expected_asset="BTCUSDT",
        expected_timeframe="1h",
        expected_source_id=source_identity["source_id"],
        expected_availability_id=source_identity["availability_id"],
        expected_dataset_id=source_identity["dataset_id"],
    )
    if len(frame) != 312:
        raise RuntimeError("committed L2-C frame must contain 312 rows")
    prepared = asyncio.run(
        prepare_trendline_research(
            _research_spec(),
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
    if replay.timeframes["1h"].recorded_position_count != 248:
        raise RuntimeError("unexpected recorded position count")
    return prepared, replay, source_identity, frame


def _resolved_confirmation_bars(prepared, replay) -> int:
    timeframe = "1h"
    point = replay.output_at(timeframe, replay.timeframes[timeframe].recorded_positions[0])
    pipeline_config = prepared.configuration.pipeline_configs[timeframe]
    resolved = resolve_asset_config(
        pipeline_config.trendlines_config,
        prepared.spec.asset,
        timeframe,
        prepared.dataset.frames[timeframe],
        fit_result=point.output.fit_result,
    )
    value = resolved.signals.hold_bars
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RuntimeError("resolved 1h signals.hold_bars is invalid")
    return value


def run_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    d2_root: str | Path = D2_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    evaluation_horizons_bars: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, object]:
    """Reconstruct D2, measure D3 outcomes, and persist canonical artifacts."""

    source_root = Path(source_root)
    d2_root = Path(d2_root)
    output_root = Path(output_root)
    _verify_checksums(d2_root)
    d2_payload = json.loads((d2_root / D2_BUNDLE_NAME).read_text(encoding="utf-8"))
    if d2_payload["structural_stability_bundle_id"] != EXPECTED_D2_BUNDLE_ID:
        raise RuntimeError("committed D2 bundle identity differs")
    prepared, replay, source_identity, frame = _prepare_and_replay(source_root)
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
    if d2_bundle.structural_stability_bundle_id != EXPECTED_D2_BUNDLE_ID:
        raise RuntimeError("reconstructed D2 bundle identity differs")
    confirmation_bars = _resolved_confirmation_bars(prepared, replay)
    interaction_spec = TrendlineInteractionUtilitySpec(
        evaluation_horizons_bars=evaluation_horizons_bars,
        break_confirmation_bars=confirmation_bars,
    )
    bundle = build_interaction_utility_bundle(
        prepared,
        replay,
        cohort,
        study_config,
        d2_bundle,
        interaction_spec,
    )
    role_event_counts = {
        role: sum(event.role == role for event in bundle.events)
        for role in ("support", "resistance")
    }
    summary_rows = [summary.to_dict() for summary in bundle.summaries]
    manifest = {
        "schema_version": "trendlines.l2d3-interaction-utility-run.v1",
        "implementation_base_commit": (
            "10d81ee690b833e52f0d73bee75be9bec5cbb4ea"
        ),
        "source_artifact_path": str(source_root / SOURCE_ARTIFACT_NAME),
        "source_artifact_sha256": _sha256(source_root / SOURCE_ARTIFACT_NAME),
        "d2_artifact_path": str(d2_root / D2_BUNDLE_NAME),
        "d2_artifact_sha256": _sha256(d2_root / D2_BUNDLE_NAME),
        "source_id": prepared.dataset.identity.source_refs["1h"].source_id,
        "availability_id": prepared.dataset.identity.availability_ids["1h"],
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "preparation_id": prepared.preparation_id,
        "replay_id": replay.replay_id,
        "cohort_id": cohort.cohort_id,
        "study_config_id": study_config.study_config_id,
        "stability_spec_id": stability_spec.stability_spec_id,
        "structural_stability_bundle_id": d2_bundle.structural_stability_bundle_id,
        "interaction_spec_id": interaction_spec.interaction_spec_id,
        "break_confirmation_bars": confirmation_bars,
        "interaction_utility_bundle_id": bundle.interaction_utility_bundle_id,
        "provider_calls": 0,
        "provider_retries": 0,
        "rows": len(frame),
        "executed_positions": replay.timeframes["1h"].executed_position_count,
        "recorded_positions": replay.timeframes["1h"].recorded_position_count,
        "event_count": len(bundle.events),
        "outcome_count": len(bundle.outcomes),
        "event_counts_by_role": role_event_counts,
        "summaries": summary_rows,
        "test_disposition": VALIDATED_TEST_DISPOSITION,
        "outcome": None,
    }
    review = "\n".join(
        (
            "# L2-D3 Interaction Utility Review",
            "",
            "Status: MEASUREMENTS_ONLY",
            "",
            "Boundary rays only; fitted lines not separately evaluated.",
            "Selection unit: non-left-censored boundary-ray episode birth.",
            "Geometry: birth-state slope/intercept frozen for all future rows.",
            "No interaction adequacy outcome selected.",
            "No model interaction labels used as ground truth.",
            "No null baseline executed.",
            "No parameter tuning performed.",
            "No retest or role-reversal lifecycle measured.",
            "No provider call made; committed artifacts were reloaded.",
            "",
            f"D2 structural bundle: {d2_bundle.structural_stability_bundle_id}",
            f"Interaction utility bundle: {bundle.interaction_utility_bundle_id}",
            f"Events: {len(bundle.events)}",
            f"Outcomes: {len(bundle.outcomes)}",
            f"Support events: {role_event_counts['support']}",
            f"Resistance events: {role_event_counts['resistance']}",
            f"Break confirmation bars: {confirmation_bars}",
            "",
            "Outcome remains null; this artifact is descriptive evidence only.",
        )
    ) + "\n"
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = _write_json(output_root / "run_manifest.json", manifest)
    bundle_path = _write_json(
        output_root / "interaction_utility_bundle.json",
        bundle.to_dict(),
    )
    review_path = output_root / "review.md"
    review_path.write_text(review, encoding="utf-8")
    files = [manifest_path, bundle_path, review_path]
    checksums = {
        "schema_version": "trendlines.l2d3-interaction-utility-checksums.v1",
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
        "structural_stability_bundle": d2_bundle,
        "interaction_spec": interaction_spec,
        "bundle": bundle,
        "paths": {
            "run_manifest": manifest_path,
            "interaction_utility_bundle": bundle_path,
            "review": review_path,
            "checksums": checksums_path,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--d2-root", type=Path, default=D2_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    result = run_study(
        source_root=args.source_root,
        d2_root=args.d2_root,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {"interaction_utility_bundle_id": result["bundle"].interaction_utility_bundle_id}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
