"""Contract-freeze tests for Phase 11R.2 attribution."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import analyze_trendline_v2_sparse_geometry_failure_attribution as subject


def test_contract_triplet_is_self_derived() -> None:
    subject._assert_contract_triplet()
    identity, length, digest = subject._contract_triplet()
    assert identity == subject.CONTRACT_ID
    assert length == subject.CONTRACT_JSON_BYTE_LENGTH
    assert digest == subject.CONTRACT_JSON_SHA256


def test_contract_has_exact_top_level_sections() -> None:
    assert tuple(subject._contract_payload()) == (
        "schema_version",
        "base_commit",
        "phase11r1_dependency",
        "sources",
        "independence",
        "targets",
        "seed_funnel",
        "theil_sen_attrition",
        "churn_attribution",
        "inversion_attribution",
        "survival_regret",
        "reconciliation",
        "artifacts",
        "execution_accounting",
        "decision_statuses",
        "study_controls",
    )


@pytest.mark.parametrize(
    "section",
    [
        "phase11r1_dependency",
        "sources",
        "independence",
        "targets",
        "seed_funnel",
        "theil_sen_attrition",
        "churn_attribution",
        "inversion_attribution",
        "survival_regret",
        "reconciliation",
        "artifacts",
        "execution_accounting",
        "decision_statuses",
        "study_controls",
    ],
)
def test_contract_section_drift_changes_contract_identity(section: str) -> None:
    payload = subject._contract_payload()
    changed = dict(payload)
    value = changed[section]
    if isinstance(value, dict):
        changed[section] = {**value, "_review_mutation": True}
    elif isinstance(value, list):
        changed[section] = [*value, "_review_mutation"]
    else:
        changed[section] = f"{value}_review_mutation"
    assert subject.contract_id(changed) != subject.contract_id(payload)


def test_phase11r1_dependency_is_pinned() -> None:
    dependency = subject._contract_payload()["phase11r1_dependency"]
    assert dependency["commit"] == subject.BASE_COMMIT
    assert dependency["script_git_blob"] == subject.PHASE11R1_SCRIPT_BLOB
    assert dependency["script_sha256"] == subject.PHASE11R1_SCRIPT_SHA256
    assert dependency["contract_id"] == subject.PHASE11R1_CONTRACT_ID
    assert dependency["manifest_id"] == subject.PHASE11R1_MANIFEST_ID
    assert dependency["inventory_sha256"] == subject.PHASE11R1_INVENTORY


def test_source_allowlist_is_exact_and_excludes_sui_temporal() -> None:
    sources = subject._contract_payload()["sources"]
    assert tuple(sources["allowed_raw_paths"]) == subject.EXPECTED_ALLOWED_RAW_PATHS
    assert all("sui" not in path for path in sources["allowed_raw_paths"])
    assert all("phase10c2" in root for root in sources["forbidden_roots"])
    assert set(subject.FORBIDDEN_RAW_PATHS).isdisjoint(subject.EXPECTED_ALLOWED_RAW_PATHS)


def test_raw_file_inventory_is_bound_without_opening_forbidden_files() -> None:
    assert len(subject.EXPECTED_ALLOWED_RAW_PATHS) == 4
    assert subject.PHASE9C2_RAW_FILE_INVENTORY == subject._inventory_sha256(
        (
            {
                "path": "datasets/btcusdt_1h/provider_result.json",
                "byte_length": 5615167,
                "sha256": "39589107f6512af36bf69987a3580668851e3781d4990fd1d7d4ac6f912ff012",
            },
            {
                "path": "datasets/btcusdt_4h/provider_result.json",
                "byte_length": 877457,
                "sha256": "0fb88993e8ceed7b3812ec8fed895164b4fd00d1d392f5018f81aeea66dd4fe3",
            },
            {
                "path": "datasets/ethusdt_1h/provider_result.json",
                "byte_length": 5509927,
                "sha256": "547b1818f2df0e1b95190355120960f55ca8379808fa94ce8f3f2ad0b3c5ab35",
            },
            {
                "path": "datasets/ethusdt_4h/provider_result.json",
                "byte_length": 938059,
                "sha256": "2b3ccd8316d3119cbf3459d1eb98034124a90e0b20cad661955b1b1bf627087a",
            },
        )
    )


@pytest.mark.parametrize("relative", subject.FORBIDDEN_RAW_PATHS)
def test_forbidden_raw_path_rejected(relative: str) -> None:
    with pytest.raises(subject.AttributionBlocked):
        subject._assert_allowed_raw_path(subject.VALIDATION_ROOT / relative)


def test_temporal_root_rejected() -> None:
    with pytest.raises(subject.AttributionBlocked):
        subject._assert_allowed_raw_path(Path(subject.FORBIDDEN_ROOTS[0]) / "x.json")


def test_unknown_raw_path_rejected() -> None:
    with pytest.raises(subject.AttributionBlocked):
        subject._assert_allowed_raw_path(subject.VALIDATION_ROOT / "datasets/btcusdt_1h/other.json")


def test_allowed_raw_inventory_reads_only_four_files(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = subject._sha256_file

    def record(path: Path) -> str:
        calls.append(path.relative_to(subject.VALIDATION_ROOT).as_posix())
        return original(path)

    monkeypatch.setattr(subject, "_sha256_file", record)
    inventory = subject._allowed_raw_inventory()
    assert tuple(item["path"] for item in inventory) == subject.EXPECTED_ALLOWED_RAW_PATHS
    assert tuple(calls) == subject.EXPECTED_ALLOWED_RAW_PATHS


def test_output_root_refusal_precedes_source_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    source_probe = Mock(side_effect=AssertionError("source access"))
    monkeypatch.setattr(subject, "_assert_phase11r1_dependency", source_probe)
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION", "1")
    with pytest.raises(FileExistsError):
        subject.run_attribution(output_root=root)
    source_probe.assert_not_called()


def test_execute_guard_precedes_source_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_probe = Mock(side_effect=AssertionError("source access"))
    monkeypatch.setattr(subject, "_assert_phase11r1_dependency", source_probe)
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION", raising=False)
    with pytest.raises(subject.AttributionError):
        subject.run_attribution(output_root=tmp_path / "new")
    source_probe.assert_not_called()


def test_staging_failure_cleans_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "new"
    staging_paths: list[Path] = []
    original_mkdtemp = subject.tempfile.mkdtemp

    def make_staging(**kwargs: object) -> str:
        path = Path(original_mkdtemp(**kwargs))
        staging_paths.append(path)
        return str(path)

    monkeypatch.setattr(subject.tempfile, "mkdtemp", make_staging)
    monkeypatch.setattr(subject, "_run_attribution", Mock(side_effect=subject.AttributionBlocked("probe")))
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION", "1")
    with pytest.raises(subject.AttributionBlocked):
        subject.run_attribution(output_root=root)
    assert staging_paths and not staging_paths[0].exists()
    assert not root.exists()


def test_successful_publication_is_atomic_from_missing_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "missing" / "nested" / "bundle"
    monkeypatch.setattr(subject, "_run_attribution", lambda staging: {"study_status": "ok"})
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION", "1")
    result = subject.run_attribution(output_root=root)
    assert result == {"study_status": "ok"}
    assert root.is_dir()


def test_verify_does_not_require_execution_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION", raising=False)
    with pytest.raises(subject.AttributionError, match="attribution bundle missing"):
        subject._verify_bundle(tmp_path / "missing")


def test_exact_future_inventory_has_24_files_and_23_members() -> None:
    assert len(subject.EXPECTED_ARTIFACT_PATHS) == 24
    assert "manifest.json" in subject.EXPECTED_ARTIFACT_PATHS
    assert len([path for path in subject.EXPECTED_ARTIFACT_PATHS if path != "manifest.json"]) == 23
    assert all("sui" not in path and "temporal" not in path for path in subject.EXPECTED_ARTIFACT_PATHS)


def test_execution_accounting_is_frozen() -> None:
    execution = subject._contract_payload()["execution_accounting"]
    assert execution["checkpoints"] == 88
    assert execution["derivation_repeats"] == 2
    assert execution["attribution_checkpoint_reconstructions"] == 176
    assert execution["raw_sui_accesses"] == 0
    assert execution["temporal_accesses"] == 0
    assert execution["network_requests"] == 0


@pytest.mark.parametrize("stage", subject.FUNNEL_STAGES)
def test_funnel_stage_names_are_stable(stage: str) -> None:
    assert stage in subject._contract_payload()["seed_funnel"]["stages"]


@pytest.mark.parametrize("label", subject.FUNNEL_LABELS)
def test_funnel_labels_are_stable(label: str) -> None:
    assert label in subject._contract_payload()["seed_funnel"]["labels"]


def test_funnel_labels_match_stage_order() -> None:
    assert len(subject.FUNNEL_STAGES) == len(subject.FUNNEL_LABELS)


def test_pair_lineage_identity_omits_checkpoint() -> None:
    first = {"pivot_id": "p1"}
    second = {"pivot_id": "p2"}
    left = subject._pivot_lineage_id(first, second, role="support", asset="BTCUSDT", timeframe="1h")
    right = subject._pivot_lineage_id(first, second, role="support", asset="BTCUSDT", timeframe="1h")
    assert left == right


def test_pair_lineage_identity_binds_role_asset_timeframe_and_order() -> None:
    first = {"pivot_id": "p1"}
    second = {"pivot_id": "p2"}
    base = subject._pivot_lineage_id(first, second, role="support", asset="BTCUSDT", timeframe="1h")
    assert base != subject._pivot_lineage_id(first, second, role="resistance", asset="BTCUSDT", timeframe="1h")
    assert base != subject._pivot_lineage_id(first, second, role="support", asset="ETHUSDT", timeframe="1h")
    assert base != subject._pivot_lineage_id(first, second, role="support", asset="BTCUSDT", timeframe="4h")
    assert base != subject._pivot_lineage_id(second, first, role="support", asset="BTCUSDT", timeframe="1h")


def test_phase11r1_bundle_identity_constants_are_complete() -> None:
    assert all(len(value) == 64 for value in (subject.PHASE11R1_CONTRACT_ID, subject.PHASE11R1_DECISION_ID, subject.PHASE11R1_MANIFEST_ID, subject.PHASE11R1_INVENTORY, subject.PHASE11R1_LOCK_ID))


def test_decision_statuses_are_fail_closed() -> None:
    assert subject.DECISION_STATUSES == (
        "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_COMPLETE",
        "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_INCOMPLETE",
        "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_BLOCKED",
    )


@pytest.mark.parametrize("label", subject.THEIL_LABELS)
def test_theil_labels_are_stable(label: str) -> None:
    assert label in subject._contract_payload()["theil_sen_attrition"]["labels"]


@pytest.mark.parametrize("stage", subject.THEIL_STAGES)
def test_theil_stages_are_stable(stage: str) -> None:
    assert stage in subject._contract_payload()["theil_sen_attrition"]["stages"]


def test_churn_labels_have_no_unknown_bucket() -> None:
    labels = subject._contract_payload()["churn_attribution"]["labels"]
    assert all("UNKNOWN" not in label and "OTHER" not in label for label in labels)


@pytest.mark.parametrize("label", subject.INVERSION_LABELS + subject.REGRET_LABELS)
def test_attribution_labels_are_typed(label: str) -> None:
    section = "inversion_attribution" if label in subject.INVERSION_LABELS else "survival_regret"
    assert label in subject._contract_payload()[section]["labels"]


def test_survival_regret_uses_exact_matched_key_and_horizons() -> None:
    section = subject._contract_payload()["survival_regret"]
    assert section["matched_key"] == ["checkpoint_index", "role"]
    assert section["horizons_hours"] == [48, 96]


def test_source_audit_has_no_forbidden_scope() -> None:
    audit = subject._build_source_audit()
    assert audit["holdout_accessed"] is False
    assert audit["temporal_accessed"] is False
    assert audit["network_request_count"] == 0
    assert audit["loaded_dataset_ids"] == list(subject.VALIDATION_DATASETS)
    assert audit["raw_sui_accesses"] == 0
    assert audit["phase11r1_persisted_sui_placeholder_reads_allowed"] is True
    assert audit["phase9c2_raw_sui_reads_prohibited"] is True
    assert audit["source_immutability"]["before"][
        "phase11r1_bundle_inventory_sha256"
    ] == subject.PHASE11R1_INVENTORY
    assert audit["source_immutability"]["after"] == audit["source_immutability"]["before"]


def test_contract_distinguishes_persisted_placeholders_from_forbidden_raw_sui() -> None:
    sources = subject._contract_payload()["sources"]
    assert sources["phase11r1_persisted_sui_placeholder_reads"] == "allowed"
    assert sources["phase9c2_raw_sui_reads"] == "prohibited"
    assert sources["source_immutability"]["policy"] == "exact_before_after_equality"


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="requires frozen external Phase 11R.1 evidence",
)
def test_scope_limited_phase11r1_verifier_never_reads_raw_sui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden_reads: list[str] = []
    original_read_bytes = Path.read_bytes

    def record_read(path: Path) -> bytes:
        rendered = str(path)
        if (
            str(subject.VALIDATION_ROOT) in rendered
            and "/datasets/suiusdt" in rendered
        ) or any(root in rendered for root in subject.FORBIDDEN_ROOTS):
            forbidden_reads.append(rendered)
        return original_read_bytes(path)

    full_verifier = Mock(side_effect=AssertionError("full Phase 11R.1 verifier is forbidden"))
    monkeypatch.setattr(Path, "read_bytes", record_read)
    monkeypatch.setattr(subject.phase11r1, "_verify_bundle", full_verifier)
    result = subject._assert_phase11r1_bundle()
    assert result["study_status"] == "NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST"
    full_verifier.assert_not_called()
    assert forbidden_reads == []


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1"
    or not subject.OUTPUT_ROOT.is_dir(),
    reason="requires generated Phase 11R.2 evidence",
)
def test_external_bundle_is_semantically_rederived() -> None:
    result = subject._verify_bundle(subject.OUTPUT_ROOT)
    assert result["raw_sui_accesses"] == 0
    assert result["temporal_accesses"] == 0


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="requires frozen external Phase 11R.1 evidence",
)
def test_canonical_read_only_attribution_reconciles_all_scopes() -> None:
    subject._assert_phase11r1_bundle()
    source_before = subject._source_snapshot()
    scopes = {scope.dataset_id: scope for scope in subject._load_allowed_scope()}
    memberships = {
        dataset: subject._load_json(
            subject.PHASE11R1_ROOT / "datasets" / dataset / "checkpoint_membership.json"
        )
        for dataset in subject.VALIDATION_DATASETS
    }
    evidence = subject._derive_attribution(
        scopes, memberships, source_before=source_before
    )
    coverage = [
        case
        for dataset in evidence["dataset_payloads"].values()
        for case in dataset["seed_funnel"]["coverage_cases"]
    ]
    assert len(coverage) == 52
    assert all(
        case["final_seed_count"] == 0
        and case["origin"] == "COMMON_SEED_POOL_EMPTY"
        for case in coverage
    )
    assert evidence["decision"]["evidence_flags"][
        "coverage_failures_originating_in_common_seed_pool"
    ] is True
    assert evidence["decision"]["unresolved_count"] == 0
    assert evidence["decision"]["study_status"] == (
        "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_COMPLETE"
    )
    deduped = [
        trace
        for dataset in evidence["dataset_payloads"].values()
        for checkpoint in dataset["seed_funnel"]["theil_sen_attrition"]
        for trace in checkpoint["traces"]
        if trace["status"] == "DEDUPED_BY_LOWER_SEED_ID"
    ]
    assert len(deduped) > 0
    assert all(
        trace["incumbent_seed_id"]
        and trace["retained_lower_seed_id"]
        and trace["shared_final_inlier_ids"]
        and trace["deduplication_id"]
        for trace in deduped
    )
    for dataset in evidence["dataset_payloads"].values():
        for funnel in dataset["seed_funnel"]["checkpoints"]:
            for role_data in funnel["roles"].values():
                for pair in role_data["pairs"]:
                    assert pair["pair_evaluation_id"]
                    assert pair["checkpoint_index"] == funnel["checkpoint_index"]
                    assert pair["source_input_identity"] == funnel[
                        "source_input_identity"
                    ]
        for record in dataset["churn_attribution"]["records"]:
            assert record["incumbent_pair_lineage_id"]
            assert "incumbent_pair_evaluation_id" in record
            assert "incumbent_first_failure_stage" in record
            assert "incumbent_passed_stages" in record
        for record in dataset["inversion_attribution"]["records"]:
            assert record["selected_support_rank"] == 1
            assert record["selected_resistance_rank"] == 1
            assert record["combinations"]
            assert all(
                "support_projection" in combination
                and "resistance_projection" in combination
                for combination in record["combinations"]
            )
        for result in dataset["survival_regret"].values():
            assert all(result["canonical_reconciliation"]["checks"].values())
    deduped_incumbent_events = [
        record
        for dataset in evidence["dataset_payloads"].values()
        for record in dataset["churn_attribution"]["records"]
        if record["cause"] == "INCUMBENT_DEDUPED_BY_LOWER_SEED"
    ]
    assert len(deduped_incumbent_events) == 5
    assert all(
        record["incumbent_seed_id"]
        and record["retained_lower_seed_id"]
        and record["shared_final_inlier_ids"]
        and record["deduplication_id"]
        for record in deduped_incumbent_events
    )
    assert evidence["source_before"] == evidence["source_after"]


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1"
    or not subject.OUTPUT_ROOT.is_dir(),
    reason="requires generated Phase 11R.2 evidence",
)
def test_semantic_verifier_rejects_rebound_evidence_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_before = subject._source_snapshot()
    scopes = tuple(subject._load_allowed_scope())
    memberships = {
        dataset: subject._load_json(
            subject.PHASE11R1_ROOT / "datasets" / dataset / "checkpoint_membership.json"
        )
        for dataset in subject.VALIDATION_DATASETS
    }
    expected = subject._derive_attribution(
        {scope.dataset_id: scope for scope in scopes},
        memberships,
        source_before=source_before,
    )
    monkeypatch.setattr(subject, "_assert_phase11r1_bundle", lambda: None)
    monkeypatch.setattr(subject, "_load_allowed_scope", lambda: scopes)
    monkeypatch.setattr(subject, "_source_snapshot", lambda: source_before)
    monkeypatch.setattr(
        subject,
        "_derive_attribution",
        lambda scopes, memberships, source_before: expected,
    )

    def rebind_manifest(root: Path) -> None:
        decision = subject._load_json(root / "decision.json")
        members = tuple(
            item for item in subject._inventory(root) if item["path"] != "manifest.json"
        )
        subject._write_json(root / "manifest.json", subject._manifest_from_members(members, decision))

    def mutate_json(root: Path, relative: str, mutate: object) -> None:
        path = root / relative
        payload = subject._load_json(path)
        mutate(payload)
        subject._write_json(path, payload)
        rebind_manifest(root)
        with pytest.raises(subject.AttributionError):
            subject._verify_bundle(root)

    mutations = (
        (
            "datasets/btcusdt_1h/seed_funnel.json",
            lambda payload: payload.__setitem__("study_id", "forged-seed-study"),
        ),
        (
            "datasets/btcusdt_1h/churn_attribution.json",
            lambda payload: payload.__setitem__("attribution_id", "forged-churn"),
        ),
        (
            "datasets/ethusdt_1h/inversion_attribution.json",
            lambda payload: payload.__setitem__("attribution_id", "forged-inversion"),
        ),
        (
            "datasets/btcusdt_4h/survival_regret.json",
            lambda payload: payload.__setitem__("attribution_id", "forged-survival"),
        ),
    )
    for index, (relative, mutate) in enumerate(mutations):
        copied = tmp_path / f"json-{index}"
        shutil.copytree(subject.OUTPUT_ROOT, copied)
        mutate_json(copied, relative, mutate)

    copied = tmp_path / "decision"
    shutil.copytree(subject.OUTPUT_ROOT, copied)
    decision = subject._load_json(copied / "decision.json")
    decision["evidence_flags"]["forged"] = True
    decision["decision_id"] = subject.deterministic_hash(
        subject.DECISION_NAMESPACE,
        {key: value for key, value in decision.items() if key != "decision_id"},
    )
    subject._write_json(copied / "decision.json", decision)
    rebind_manifest(copied)
    with pytest.raises(subject.AttributionError):
        subject._verify_bundle(copied)

    copied = tmp_path / "source-audit"
    shutil.copytree(subject.OUTPUT_ROOT, copied)
    source_audit = subject._load_json(copied / "source_audit.json")
    source_audit["loaded_dataset_ids"].append("forged")
    source_audit["source_audit_id"] = subject.deterministic_hash(
        subject.SOURCE_AUDIT_NAMESPACE,
        {key: value for key, value in source_audit.items() if key != "source_audit_id"},
    )
    subject._write_json(copied / "source_audit.json", source_audit)
    rebind_manifest(copied)
    with pytest.raises(subject.AttributionError):
        subject._verify_bundle(copied)

    copied = tmp_path / "csv"
    shutil.copytree(subject.OUTPUT_ROOT, copied)
    path = copied / "churn_summary.csv"
    path.write_bytes(path.read_bytes().replace(b"count", b"forge", 1))
    rebind_manifest(copied)
    with pytest.raises(subject.AttributionError):
        subject._verify_bundle(copied)


def test_decision_id_is_content_addressed() -> None:
    decision = subject._decision_payload(status=subject.DECISION_STATUSES[0], unresolved_count=0, flags={}, counts={})
    assert decision["decision_id"] == subject.deterministic_hash(subject.DECISION_NAMESPACE, {key: value for key, value in decision.items() if key != "decision_id"})


def test_contract_json_is_canonical() -> None:
    payload = subject._contract_payload()
    assert subject._canonical_json_bytes(payload).decode() == subject.canonical_json(payload)


def test_contract_artifact_binds_identity_triplet() -> None:
    payload = subject._contract_payload()
    assert subject.contract_id(payload) == subject.CONTRACT_ID
    assert subject._sha256_bytes(subject._canonical_json_bytes(payload)) == subject.CONTRACT_JSON_SHA256
    assert len(subject._canonical_json_bytes(payload)) == subject.CONTRACT_JSON_BYTE_LENGTH


@pytest.mark.parametrize("path", ["datasets/suiusdt_1h/provider_result.json", "datasets/suiusdt_4h/provider_result.json", "/tmp/trendline_v2_phase10c2_lookback_eviction/x.json"])
def test_forbidden_scope_strings_are_not_allowed(path: str) -> None:
    assert path not in subject.EXPECTED_ALLOWED_RAW_PATHS


def test_no_finalist_controls_are_frozen() -> None:
    controls = subject._contract_payload()["study_controls"]
    assert controls["execution_authorized_at_freeze"] is False
    assert controls["parameter_search"] is False
    assert controls["threshold_changes"] is False
    assert controls["new_provider"] is False
    assert controls["counterfactual_promotion"] is False


def test_csv_writer_is_deterministic() -> None:
    rows = ({"dataset_id": "btc", "count": 1}, {"dataset_id": "eth", "count": 2})
    assert subject._csv_bytes(rows) == subject._csv_bytes(rows)


def test_json_loader_rejects_noncanonical(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"b": 1, "a": 2}\n')
    with pytest.raises(subject.AttributionError, match="non-canonical"):
        subject._load_json(path)


def test_json_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"a": 1, "a": 2}\n')
    with pytest.raises(subject.AttributionError, match="invalid JSON"):
        subject._load_json(path)


def test_manifest_member_set_is_sorted() -> None:
    assert subject.EXPECTED_ARTIFACT_PATHS == tuple(sorted(subject.EXPECTED_ARTIFACT_PATHS))


def test_contract_source_paths_are_safe() -> None:
    paths = subject._contract_payload()["sources"]["allowed_raw_paths"]
    assert all(".." not in path and not path.startswith("/") for path in paths)


def test_source_audit_id_is_content_addressed() -> None:
    audit = subject._build_source_audit()
    body = {key: value for key, value in audit.items() if key != "source_audit_id"}
    assert audit["source_audit_id"] == subject.deterministic_hash(subject.SOURCE_AUDIT_NAMESPACE, body)


def test_pair_evaluation_namespace_is_distinct() -> None:
    assert subject.PAIR_EVALUATION_NAMESPACE != subject.PAIR_LINEAGE_NAMESPACE
    assert subject.SEED_FUNNEL_NAMESPACE != subject.PAIR_EVALUATION_NAMESPACE


def test_phase11r1_dependency_check_is_explicitly_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subject, "_git_is_ancestor", lambda ancestor: False)
    with pytest.raises(subject.AttributionBlocked, match="not an ancestor"):
        subject._assert_phase11r1_dependency()


def test_atomic_publication_does_not_leave_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "bundle"
    observed: list[Path] = []

    def writer(staging: Path) -> dict[str, str]:
        observed.append(staging)
        (staging / "payload").write_text("ok")
        return {"status": "ok"}

    monkeypatch.setattr(subject, "_run_attribution", writer)
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION", "1")
    assert subject.run_attribution(output_root=root) == {"status": "ok"}
    assert observed and not observed[0].exists()
    assert (root / "payload").read_text() == "ok"


def test_contract_payload_does_not_access_files(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Mock(side_effect=AssertionError("file access"))
    monkeypatch.setattr(subject.Path, "read_bytes", probe)
    subject._contract_payload()
    probe.assert_not_called()


def test_contract_id_namespace_is_exact() -> None:
    assert subject.CONTRACT_NAMESPACE == "trendline_v2_phase11r2_sparse_geometry_failure_attribution_contract"


def test_reconciliation_requires_zero_unresolved() -> None:
    assert subject._contract_payload()["reconciliation"]["zero_unresolved"] is True


def test_coverage_target_is_not_cherry_picked() -> None:
    targets = subject._contract_payload()["targets"]
    assert targets["coverage"] == "every_dataset_checkpoint_role_without_primary_line"
    assert targets["churn"] == "every_primary_replacement_event_both_roles"


def test_inversion_target_is_not_hardcoded_to_eth_case() -> None:
    assert subject._contract_payload()["targets"]["inversion"].startswith("every_selected")


def test_survival_target_includes_both_outcomes() -> None:
    assert "every_matched_48h_or_96h_disagreement" == subject._contract_payload()["targets"]["survival_regret"]


def test_decision_flags_are_evidence_not_policy() -> None:
    assert "evidence_flags" not in subject._contract_payload()["study_controls"]
    assert "evidence_flags" not in subject._contract_payload()["targets"]


def test_holdout_and_temporal_are_not_artifact_paths() -> None:
    assert all("holdout" not in path and "temporal" not in path for path in subject.EXPECTED_ARTIFACT_PATHS)


def test_manifest_namespace_is_distinct_from_contract() -> None:
    assert subject.MANIFEST_NAMESPACE != subject.CONTRACT_NAMESPACE


def test_decision_namespace_is_distinct_from_manifest() -> None:
    assert subject.DECISION_NAMESPACE != subject.MANIFEST_NAMESPACE


def test_phase11r1_dependency_path_is_canonical() -> None:
    assert subject._contract_payload()["phase11r1_dependency"]["script_path"].startswith("scripts/")


def test_allowed_dataset_names_are_four() -> None:
    assert subject.VALIDATION_DATASETS == ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")


def test_primary_provider_set_is_two() -> None:
    assert len(subject.PRIMARY_PROVIDERS) == 2


def test_roles_are_support_and_resistance() -> None:
    assert subject.ROLES == ("support", "resistance")


def test_no_new_provider_is_contract_control() -> None:
    assert subject._contract_payload()["study_controls"]["new_provider"] is False


def test_parameter_search_is_contract_control() -> None:
    assert subject._contract_payload()["study_controls"]["parameter_search"] is False


def test_thresholds_match_phase11r1() -> None:
    thresholds = subject._contract_payload()["seed_funnel"]["thresholds"]
    assert thresholds == {
        "minimum_span_hours": 96,
        "touch_atr": 0.35,
        "breach_atr": 0.5,
        "breach_consecutive_bars": 2,
        "maximum_distance_atr": 8.0,
    }


def test_regret_horizons_exclude_24h() -> None:
    assert subject.HORIZONS_HOURS == (48, 96)


def test_output_root_is_research_temp_root() -> None:
    assert str(subject.OUTPUT_ROOT).startswith("/tmp/trendline_v2_phase11r2_failure_attribution/")


def test_contract_payload_is_repeatable() -> None:
    assert subject._contract_payload() == subject._contract_payload()


def test_contract_identity_is_repeatable() -> None:
    assert subject._contract_triplet() == subject._contract_triplet()


def test_study_status_set_is_exact() -> None:
    assert set(subject.DECISION_STATUSES) == {
        "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_COMPLETE",
        "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_INCOMPLETE",
        "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_BLOCKED",
    }


def test_no_legacy_model_import() -> None:
    source = Path(subject.__file__).read_text()
    assert "libs.models.trendlines_old" not in source
    assert "libs.trendlines" not in source


def test_no_sui_data_literal_in_allowed_paths() -> None:
    assert all("sui" not in path.lower() for path in subject.EXPECTED_ALLOWED_RAW_PATHS)


def test_forbidden_root_is_explicit() -> None:
    assert subject.FORBIDDEN_ROOTS == ("/tmp/trendline_v2_phase10c2_lookback_eviction",)


def test_source_audit_counts_reconstructions() -> None:
    assert _source_audit_count() == EXPECTED_RECONSTRUCTION_COUNT()


def EXPECTED_RECONSTRUCTION_COUNT() -> int:
    return len(subject.VALIDATION_DATASETS) * subject.CHECKPOINTS_PER_DATASET * 2


def _source_audit_count() -> int:
    return subject._build_source_audit()["attribution_checkpoint_reconstructions"]
