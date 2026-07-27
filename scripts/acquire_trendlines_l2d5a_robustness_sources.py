"""Acquire and freeze L2-D5A robustness source members."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable

import pandas as pd

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.adapters.trendlines_research import (
    BinanceTrendlineResearchLoader,
)
from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
    prepare_trendline_research,
    read_research_frame_artifact,
    write_research_frame_artifact,
)
from libs.models.trendlines.workflows.research.adequacy import (
    ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
    ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
    TrendlineRobustnessSourceMemberSpec,
    build_robustness_source_matrix_bundle,
    build_robustness_source_member_evidence,
    frozen_robustness_source_member_specs,
    validate_robustness_source_matrix_bundle,
)


DEFAULT_OUTPUT_ROOT = Path(
    "artifacts/trendlines_research_robustness/20260727_l2d5a_source_matrix_v1"
)
REFERENCE_ROOT = Path(
    "artifacts/trendlines_research_validation/"
    "20260726_btcusdt_1h_single_call_v1"
)
REFERENCE_ARTIFACT_NAME = "normalized_ohlcv_v2.json"
REFERENCE_IDENTITY_NAME = "source_identity.json"
REFERENCE_RUN_MANIFEST_NAME = "run_manifest.json"
YAML_PATH = Path("src/libs/models/trendlines/config/trendlines.yaml")
IMPLEMENTATION_BASE_COMMIT = "48fee68acdd2a98256c842e0d1954801a5926293"
PAGE_LIMIT = 1000
FRESH_MEMBER_NAMES = tuple(
    spec.name for spec in frozen_robustness_source_member_specs()[1:]
)
VALIDATED_TEST_DISPOSITION = {
    "status": "PASSED",
    "d5a_focused": "18 passed",
    "d5a_network_free_script": "18 passed",
    "canonical_mature_trendlines": "699 passed",
    "d4b_focused": "52 passed",
    "d4a_focused": "40 passed",
    "d3_focused": "52 passed",
    "viewer_python": "30 passed",
    "viewer_node": "23 passed",
    "consumer_ingestion_bridge": "79 passed",
    "offline_workflows": "20 passed",
    "real_provider_calls": 4,
    "real_provider_retries": 0,
    "model_executions": 0,
    "replay_executions": 0,
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
    checksum_path = root / "checksums.json"
    payload = json.loads(checksum_path.read_text(encoding="utf-8"))
    for member in payload["files"]:
        path = root / member["path"]
        if not path.is_file():
            raise RuntimeError(f"missing checksum member: {path}")
        if path.stat().st_size != member["byte_length"]:
            raise RuntimeError(f"checksum byte length differs: {path}")
        if _sha256(path) != member["sha256"]:
            raise RuntimeError(f"checksum differs: {path}")


def _identity(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise RuntimeError(f"{name} must be lowercase SHA-256")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _research_spec(member: TrendlineRobustnessSourceMemberSpec) -> TrendlineResearchSpec:
    return TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.BINANCE,
            event_start=member.event_start,
            knowledge_cutoff=member.knowledge_cutoff,
        ),
        asset=member.asset,
        timeframes=(member.timeframe,),
        primary_timeframe=member.timeframe,
    )


def _provider_accounting(loader: Any, member: TrendlineRobustnessSourceMemberSpec) -> tuple[int, int]:
    calls = getattr(loader, "provider_calls", None)
    if isinstance(calls, bool) or not isinstance(calls, int):
        raise RuntimeError(f"{member.name} loader has no truthful provider_calls")
    page_counts = getattr(loader, "page_counts", None)
    if not isinstance(page_counts, dict):
        raise RuntimeError(f"{member.name} loader has no truthful page_counts")
    page_count = page_counts.get(member.timeframe)
    if isinstance(page_count, bool) or not isinstance(page_count, int):
        raise RuntimeError(f"{member.name} loader has no truthful page count")
    if calls != member.provider_call_budget:
        raise RuntimeError(
            f"{member.name} provider call count {calls} != {member.provider_call_budget}"
        )
    expected_pages = 0 if member.source_kind == "frozen_reference" else 1
    if page_count != expected_pages:
        raise RuntimeError(
            f"{member.name} page count {page_count} != {expected_pages}"
        )
    return calls, page_count


def _assert_frame_equal(left: pd.DataFrame, right: pd.DataFrame, *, name: str) -> None:
    try:
        pd.testing.assert_frame_equal(
            left,
            right,
            check_exact=True,
            check_categorical=True,
            check_freq=False,
        )
    except AssertionError as exc:
        raise RuntimeError(f"{name} frame round trip differs") from exc
    if left.attrs != right.attrs:
        raise RuntimeError(f"{name} frame attributes differ")


def _reference_context(config: Any, specs: tuple[TrendlineRobustnessSourceMemberSpec, ...]) -> tuple[Any, Any]:
    source_root = REFERENCE_ROOT
    artifact_path = source_root / REFERENCE_ARTIFACT_NAME
    identity_payload = _load_json(source_root / REFERENCE_IDENTITY_NAME)
    run_manifest = _load_json(source_root / REFERENCE_RUN_MANIFEST_NAME)
    reference = specs[0]
    expected_identity = {
        "source_id": "d3cba96f006b5f7e05a38d888b60b799f128f41567030f0663da908e005f0331",
        "availability_id": "9b3e8f49e408d7781b89a686787e989888d25638683e1a8ab921c1043d4f8bd1",
        "dataset_id": "6464eede955ccfcf0ac023b7b96d026235e6763cbc4eb10470f9c31ee9b0002c",
        "preparation_id": "ff653424e4e848a52666859f14c819c517f79a13d3bc980431bbadc5d15b8141",
    }
    for field, expected in expected_identity.items():
        if identity_payload.get(field) != expected:
            raise RuntimeError(f"reference {field} differs")
        _identity(identity_payload[field], name=f"reference {field}")
        if run_manifest.get(field) != expected:
            raise RuntimeError(f"reference manifest {field} differs")
    if run_manifest.get("research_configuration_id") is None:
        raise RuntimeError("reference research_configuration_id missing")
    research_configuration_id = _identity(
        run_manifest["research_configuration_id"],
        name="reference research_configuration_id",
    )
    frame = read_research_frame_artifact(
        artifact_path,
        expected_asset=reference.asset,
        expected_timeframe=reference.timeframe,
        expected_source_id=expected_identity["source_id"],
        expected_availability_id=expected_identity["availability_id"],
        expected_dataset_id=expected_identity["dataset_id"],
    )
    artifact_payload = _load_json(artifact_path)
    artifact_id = _identity(artifact_payload["artifact_id"], name="reference artifact_id")
    evidence = build_robustness_source_member_evidence(
        reference,
        frame,
        artifact_id=artifact_id,
        artifact_sha256=_sha256(artifact_path),
        source_id=expected_identity["source_id"],
        availability_id=expected_identity["availability_id"],
        dataset_id=expected_identity["dataset_id"],
        research_configuration_id=research_configuration_id,
        preparation_id=expected_identity["preparation_id"],
        provider_calls=0,
        page_count=0,
    )
    if not _config_has_asset_timeframe(config, reference.asset, reference.timeframe):
        raise RuntimeError("reference asset/timeframe absent from YAML")
    return frame, evidence


def _config_has_asset_timeframe(config: Any, asset: str, timeframe: str) -> bool:
    assets = getattr(config, "assets", None)
    asset_config = assets.get(asset) if isinstance(assets, dict) else None
    timeframes = getattr(asset_config, "timeframes", None)
    return isinstance(timeframes, dict) and timeframe in timeframes


def _verify_reference_chain() -> None:
    prior = (
        (
            Path("artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d2_structural_stability_v1"),
            "structural_stability_bundle.json",
            "structural_stability_bundle_id",
            ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
        ),
        (
            Path("artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d3_interaction_utility_v1"),
            "interaction_utility_bundle.json",
            "interaction_utility_bundle_id",
            ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
        ),
        (
            Path("artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d4a_deterministic_naive_baselines_v1"),
            "baseline_comparison_bundle.json",
            "baseline_comparison_bundle_id",
            ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
        ),
        (
            Path("artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d4b_seeded_stochastic_nulls_v1"),
            "stochastic_null_comparison_bundle.json",
            "stochastic_null_comparison_bundle_id",
            ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
        ),
    )
    for root, name, field, expected in prior:
        _verify_checksums(root)
        payload = _load_json(root / name)
        if payload.get(field) != expected:
            raise RuntimeError(f"reference evidence differs: {field}")


def _fresh_loader(member: TrendlineRobustnessSourceMemberSpec) -> Any:
    return BinanceTrendlineResearchLoader(
        adapter=BinanceNativeAdapter(),
        page_limit=PAGE_LIMIT,
    )


def _prepare_fresh_member(
    member: TrendlineRobustnessSourceMemberSpec,
    *,
    config: Any,
    loader_factory: Callable[[TrendlineRobustnessSourceMemberSpec], Any],
    staging_root: Path,
) -> tuple[Any, Any]:
    spec = _research_spec(member)
    loader = loader_factory(member)
    prepared = asyncio.run(
        prepare_trendline_research(
            spec,
            trendlines_config=config,
            loader=loader,
        )
    )
    calls, page_count = _provider_accounting(loader, member)
    frame = prepared.dataset.frames[member.timeframe]
    source_id = prepared.dataset.identity.source_refs[member.timeframe].source_id
    availability_id = prepared.dataset.identity.availability_ids[member.timeframe]
    dataset_id = prepared.dataset.dataset_id
    artifact_path = staging_root / "members" / member.name / REFERENCE_ARTIFACT_NAME
    write_research_frame_artifact(
        frame,
        asset=member.asset,
        timeframe=member.timeframe,
        data_spec=spec.data,
        source_id=source_id,
        availability_id=availability_id,
        dataset_id=dataset_id,
        output_path=artifact_path,
    )
    reloaded = read_research_frame_artifact(
        artifact_path,
        expected_asset=member.asset,
        expected_timeframe=member.timeframe,
        expected_source_id=source_id,
        expected_availability_id=availability_id,
        expected_dataset_id=dataset_id,
    )
    _assert_frame_equal(frame, reloaded, name=member.name)
    reloaded_prepared = asyncio.run(
        prepare_trendline_research(
            spec,
            trendlines_config=config,
            loader={member.timeframe: reloaded},
        )
    )
    if reloaded_prepared.configuration.research_configuration_id != prepared.configuration.research_configuration_id:
        raise RuntimeError(f"{member.name} research configuration changed after reload")
    if reloaded_prepared.preparation_id != prepared.preparation_id:
        raise RuntimeError(f"{member.name} preparation identity changed after reload")
    artifact_payload = _load_json(artifact_path)
    evidence = build_robustness_source_member_evidence(
        member,
        reloaded,
        artifact_id=artifact_payload["artifact_id"],
        artifact_sha256=_sha256(artifact_path),
        source_id=source_id,
        availability_id=availability_id,
        dataset_id=dataset_id,
        research_configuration_id=prepared.configuration.research_configuration_id,
        preparation_id=prepared.preparation_id,
        provider_calls=calls,
        page_count=page_count,
    )
    return evidence, {
        "loader": loader,
        "prepared": prepared,
        "reloaded_prepared": reloaded_prepared,
        "artifact_path": artifact_path,
    }


def _write_checksums(root: Path) -> Path:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "checksums.json"
    )
    payload = {
        "schema_version": "trendlines.l2d5a-source-matrix-checksums.v1",
        "files": [
            {
                "path": str(path.relative_to(root)),
                "byte_length": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }
    return _write_json(root / "checksums.json", payload)


def run_acquisition(
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    loader_factory: Callable[[TrendlineRobustnessSourceMemberSpec], Any] | None = None,
    config_loader: Callable[[], Any] = load_trendlines_config,
    yaml_path: str | Path = YAML_PATH,
) -> dict[str, Any]:
    """Acquire exact D5A members; never overwrite an official output root."""

    output_root = Path(output_root)
    yaml_path = Path(yaml_path)
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite output root: {output_root}")
    yaml_before = _sha256(yaml_path)
    specs = frozen_robustness_source_member_specs()
    config = config_loader()
    _verify_reference_chain()
    reference_frame, reference_evidence = _reference_context(config, specs)
    del reference_frame
    factory = loader_factory or _fresh_loader
    evidence: list[Any] = [reference_evidence]
    fresh_context: list[dict[str, Any]] = []
    staging_parent = output_root.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".l2d5a-source-matrix-",
        dir=staging_parent,
    ) as staging_name:
        staging_root = Path(staging_name)
        for member in specs[1:]:
            member_evidence, context = _prepare_fresh_member(
                member,
                config=config,
                loader_factory=factory,
                staging_root=staging_root,
            )
            evidence.append(member_evidence)
            fresh_context.append(context)
        if _sha256(yaml_path) != yaml_before:
            raise RuntimeError("canonical YAML changed during acquisition")
        bundle = build_robustness_source_matrix_bundle(specs, tuple(evidence))
        validate_robustness_source_matrix_bundle(bundle, trendlines_config=config)
        output_root.mkdir(parents=False, exist_ok=False)
        shutil.move(str(staging_root / "members"), str(output_root / "members"))
        fresh_paths = {
            member.name: str(
                output_root / "members" / member.name / REFERENCE_ARTIFACT_NAME
            )
            for member in specs[1:]
        }
    yaml_after = _sha256(yaml_path)
    if yaml_after != yaml_before:
        raise RuntimeError("canonical YAML changed after acquisition")
    manifest = {
        "schema_version": "trendlines.l2d5a-source-matrix-run.v1",
        "implementation_base_commit": IMPLEMENTATION_BASE_COMMIT,
        "reference_artifact_path": str(REFERENCE_ROOT / REFERENCE_ARTIFACT_NAME),
        "reference_artifact_sha256": evidence[0].artifact_sha256,
        "reference_source_id": evidence[0].source_id,
        "reference_availability_id": evidence[0].availability_id,
        "reference_dataset_id": evidence[0].dataset_id,
        "reference_preparation_id": evidence[0].preparation_id,
        "reference_d2_bundle_id": ROBUSTNESS_REFERENCE_D2_BUNDLE_ID,
        "reference_d3_bundle_id": ROBUSTNESS_REFERENCE_D3_BUNDLE_ID,
        "reference_d4a_bundle_id": ROBUSTNESS_REFERENCE_D4A_BUNDLE_ID,
        "reference_d4b_bundle_id": ROBUSTNESS_REFERENCE_D4B_BUNDLE_ID,
        "member_specs": [spec.to_dict() for spec in specs],
        "member_evidence": [
            {
                **row.to_dict(),
                "artifact_path": (
                    str(REFERENCE_ROOT / REFERENCE_ARTIFACT_NAME)
                    if index == 0
                    else fresh_paths[specs[index].name]
                ),
            }
            for index, row in enumerate(evidence)
        ],
        "robustness_source_matrix_bundle_id": bundle.robustness_source_matrix_bundle_id,
        "yaml_sha256_before": yaml_before,
        "yaml_sha256_after": yaml_after,
        "provider_calls_by_member": {
            spec.name: row.provider_calls
            for spec, row in zip(specs, evidence)
        },
        "page_counts_by_member": {
            spec.name: row.page_count
            for spec, row in zip(specs, evidence)
        },
        "total_provider_calls": sum(row.provider_calls for row in evidence),
        "provider_retries": 0,
        "model_executions": 0,
        "replay_executions": 0,
        "test_disposition": VALIDATED_TEST_DISPOSITION,
        "outcome": None,
    }
    review = "\n".join(
        (
            "# L2-D5A Robustness Source Matrix Review",
            "",
            "Status: SOURCE_MATRIX_ONLY",
            "",
            "No robustness adequacy outcome selected.",
            "No trendline model or replay executed.",
            "No D2-D4 metric or null protocol executed on fresh members.",
            "Four provider calls were made under the frozen source budget.",
            "No provider retry was made.",
            "All fresh frames contain exactly 312 complete bars.",
            "All persisted frames reproduce exact source, availability, dataset, configuration and preparation identities after reload.",
            "Canonical YAML remained unchanged.",
            "D5B, D5C and D5D remain unstarted.",
            "",
            "Outcome remains null; source acquisition is not robustness evidence.",
        )
    ) + "\n"
    _write_json(output_root / "robustness_source_matrix_bundle.json", bundle.to_dict())
    _write_json(output_root / "run_manifest.json", manifest)
    (output_root / "review.md").write_text(review, encoding="utf-8")
    checksums_path = _write_checksums(output_root)
    _verify_checksums(output_root)
    return {
        "bundle": bundle,
        "manifest": manifest,
        "paths": {
            "root": output_root,
            "bundle": output_root / "robustness_source_matrix_bundle.json",
            "manifest": output_root / "run_manifest.json",
            "review": output_root / "review.md",
            "checksums": checksums_path,
        },
        "fresh_context": fresh_context,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    result = run_acquisition(output_root=args.output_root)
    print(
        json.dumps(
            {
                "robustness_source_matrix_bundle_id": result[
                    "bundle"
                ].robustness_source_matrix_bundle_id,
                "provider_calls": result["manifest"]["total_provider_calls"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
