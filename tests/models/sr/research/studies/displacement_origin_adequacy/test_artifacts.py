from __future__ import annotations

import json
from pathlib import Path

import pytest

from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.research.artifacts.canonical_json import canonical_json_bytes
from libs.models.sr.research.artifacts.manifest import member_metadata
from libs.models.sr.research.studies.displacement_origin_adequacy.artifacts import (
    publish_study_bundle,
    validate_study_bundle,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.config import (
    load_displacement_origin_adequacy_config,
)
from libs.models.sr.research.studies.displacement_origin_adequacy.runner import (
    compute_displacement_origin_study,
)


_CONFIG = "configs/sr_trials/sr_v2_0_taousdt_1d_displacement_origin_adequacy.yaml"
_COMMIT = "a" * 40


def _published(tmp_path: Path):
    config = load_displacement_origin_adequacy_config(_CONFIG)
    study = compute_displacement_origin_study(
        config,
        repo_root=Path("."),
        implementation_commit=_COMMIT,
    )
    bundle_id, path = publish_study_bundle(study, config=config, output_root=tmp_path)
    return config, study, bundle_id, path


def test_artifact_round_trip_recomputes_the_exact_study(tmp_path: Path) -> None:
    config, study, bundle_id, path = _published(tmp_path)

    validated = validate_study_bundle(
        path,
        config=config,
        repo_root=Path("."),
        expected_bundle_id=bundle_id,
    )

    assert validated == study


def test_rehashed_disposition_tampering_is_rejected_by_semantic_recomputation(
    tmp_path: Path,
) -> None:
    config, _study, _bundle_id, path = _published(tmp_path)
    study_payload = json.loads((path / "study.json").read_text(encoding="utf-8"))
    study_payload["decision"]["disposition"] = "DISPLACEMENT_ORIGIN_BEATS_NAIVE_NULL"
    target = _rewrite_rehashed_bundle(path, study_payload=study_payload)

    with pytest.raises(ContractValidationError, match="semantic recomputation"):
        validate_study_bundle(target, config=config, repo_root=Path("."))


@pytest.mark.parametrize(
    ("payload_kind", "field", "value"),
    [
        ("cases", ("cases", 0, "base_distance_bars"), 2),
        ("study", ("fold_metrics", 0, "completed_real_count"), 999),
        ("study", ("study_id",), "b" * 64),
    ],
)
def test_rehashed_case_metric_or_identity_tampering_is_rejected_by_semantic_recomputation(
    tmp_path: Path,
    payload_kind: str,
    field: tuple[object, ...],
    value: object,
) -> None:
    config, _study, _bundle_id, path = _published(tmp_path)
    study_payload = json.loads((path / "study.json").read_text(encoding="utf-8"))
    cases_payload = json.loads((path / "cases.json").read_text(encoding="utf-8"))
    payload = cases_payload if payload_kind == "cases" else study_payload
    target_payload: object = payload
    for part in field[:-1]:
        target_payload = target_payload[part]  # type: ignore[index]
    target_payload[field[-1]] = value  # type: ignore[index]
    target = _rewrite_rehashed_bundle(
        path,
        study_payload=study_payload,
        cases_payload=cases_payload,
    )

    with pytest.raises(ContractValidationError, match="semantic recomputation"):
        validate_study_bundle(target, config=config, repo_root=Path("."))


def _rewrite_rehashed_bundle(
    path: Path,
    *,
    study_payload: dict[str, object] | None = None,
    cases_payload: dict[str, object] | None = None,
) -> Path:
    if study_payload is None:
        study_payload = json.loads((path / "study.json").read_text(encoding="utf-8"))
    if cases_payload is None:
        cases_payload = json.loads((path / "cases.json").read_text(encoding="utf-8"))
    study_bytes = canonical_json_bytes(study_payload)
    cases_bytes = canonical_json_bytes(cases_payload)
    (path / "study.json").write_bytes(study_bytes)
    (path / "cases.json").write_bytes(cases_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    semantic = manifest["bundle_id_semantic_payload"]
    semantic["study_id"] = study_payload["study_id"]
    semantic["disposition"] = study_payload["decision"]["disposition"]
    semantic["members"] = [
        member_metadata("study.json", study_bytes),
        member_metadata("cases.json", cases_bytes),
    ]
    bundle_id = deterministic_hash(semantic)
    rewritten = {**semantic, "bundle_id": bundle_id, "bundle_id_semantic_payload": semantic}
    target = path.parent / bundle_id
    path.rename(target)
    (target / "manifest.json").write_bytes(canonical_json_bytes(rewritten))
    return target
