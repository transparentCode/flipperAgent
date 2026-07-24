from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import os
import shutil

import pytest

from scripts import analyze_trendline_v2_structural_selection as study


UTC = timezone.utc


def _record(
    index: int,
    *,
    role: str = "support",
    first_anchor_id: str | None = None,
    second_anchor_id: str | None = None,
    price: float | None = None,
    slope: float | None = None,
) -> study.ResearchCandidate:
    first = first_anchor_id or f"{index + 1:064x}"
    second = second_anchor_id or f"{index + 10_000:064x}"
    return study.ResearchCandidate(
        candidate=None,
        evidence=None,
        fields={
            "candidate_id": f"{index + 100_000:064x}",
            "candidate_structure_id": f"{index + 200_000:064x}",
            "role": role,
            "first_anchor_id": first,
            "second_anchor_id": second,
            "first_anchor_time": f"2025-01-{(index % 9) + 1:02d}T00:00:00Z",
            "second_anchor_time": "2025-02-01T00:00:00Z",
            "anchor_span_seconds": float(200 + index),
            "anchor_span_bars": 200 + index,
            "anchor_span_hours": float(200 + index) / 3600,
            "anchor_source_positions": [index, index + 200],
            "minimum_anchor_prominence_bps": float(index + 1),
            "minimum_body_clearance_bps": float(index + 2),
            "historical_exact_contact_count": index % 5,
            "historical_last_contact_age_bars": index + 1,
            "current_absolute_distance_bps": float(index + 1),
            "current_projected_line_price": price if price is not None else 100.0 + index,
            "same_role_extrema_skip_count": index % 4,
            "slope_bps_per_day": slope if slope is not None else float(index),
            "current_exact_side_valid": True,
            "structurally_eligible": True,
            "candidate_available_at": "2025-01-01T00:00:00Z",
        },
    )


def _causal_feature_fixture() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, datetime]:
    first = datetime(2025, 1, 1, tzinfo=UTC)
    timestamps = tuple(
        int((first + timedelta(hours=offset)).timestamp() * study.NANOSECONDS)
        for offset in range(20)
    )
    data = SimpleNamespace(
        row_count=len(timestamps),
        timestamps=timestamps,
        timeframe="1h",
        open=tuple(99.0 for _ in timestamps),
        high=tuple(101.0 for _ in timestamps),
        low=tuple(98.0 for _ in timestamps),
        close=tuple(100.0 for _ in timestamps),
    )

    class Geometry:
        def value_at(self, _timestamp: datetime) -> float:
            return 100.0

    candidate = SimpleNamespace(
        candidate_id="c" * 64,
        anchors=(
            SimpleNamespace(anchor_id="a" * 64, pivot_time=first + timedelta(hours=1)),
            SimpleNamespace(anchor_id="b" * 64, pivot_time=first + timedelta(hours=3)),
        ),
        geometry=Geometry(),
        role=SimpleNamespace(value="support"),
    )
    evidence = SimpleNamespace(
        candidate_id=candidate.candidate_id,
        anchor_source_positions=(1, 3),
        confirmation_positions=(1, 3),
    )
    return data, candidate, evidence, first + timedelta(hours=10)


def _copy_external_bundle(tmp_path: Path) -> Path:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external frozen study disabled")
    return Path(shutil.copytree(study.OUTPUT_ROOT, tmp_path / "bundle"))


def _rebind_manifest(root: Path) -> None:
    manifest = study._load_json(root / "manifest.json")
    payload = {
        key: value for key, value in manifest.items() if key != "manifest_id"
    }
    members = tuple(
        item for item in study._inventory(root) if item["path"] != "manifest.json"
    )
    payload["member_count"] = len(members)
    payload["members"] = list(members)
    rebound = {
        **payload,
        "manifest_id": study.deterministic_hash(study.MANIFEST_NAMESPACE, payload),
    }
    (root / "manifest.json").write_bytes(study._canonical_bytes(rebound))


def test_exact_contract_payload_and_id() -> None:
    payload, identity = study._validated_contract()
    assert identity == "41c6054577193d64e4bf2ff985d40571e9f75427bfbf47508e3b673ee9e32b54"
    assert payload["budgets_per_role"] == [4, 6, 8]
    assert payload["sources"]["phase10c2"]["temporal_checkpoints"] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    "section",
    [
        "checkpoint_policy",
        "contenders",
        "controls",
        "eligibility",
        "holdout_gates",
        "redundancy",
        "sources",
        "temporal_audit_gates",
        "validation_gates",
        "validation_ranking",
    ],
)
def test_contract_drift_fails_closed(section: str) -> None:
    payload = study._contract_payload()
    value = payload[section]
    if isinstance(value, list):
        payload[section] = [*value, "drift"]
    elif isinstance(value, dict):
        payload[section] = {**value, "drift": True}
    else:
        payload[section] = "drift"
    assert study.replay_contract_id(payload) != study.CONTRACT_ID


def test_checkpoint_schedule_uses_warmup_daily_causal_boundaries() -> None:
    first = datetime(2025, 1, 1, tzinfo=UTC)
    timestamps = tuple(
        int((first + timedelta(hours=offset)).timestamp() * study.NANOSECONDS)
        for offset in range(434)
    )
    data = SimpleNamespace(
        row_count=len(timestamps),
        timestamps=timestamps,
        timeframe="1h",
        confirmed_through=first + timedelta(hours=434),
    )
    schedule = study._checkpoint_schedule(data)
    assert schedule == ((1, first + timedelta(hours=336), 335),)


def test_checkpoint_schedule_rejects_unaligned_prefix() -> None:
    first = datetime(2025, 1, 1, tzinfo=UTC)
    timestamps = tuple(
        int((first + timedelta(hours=offset)).timestamp() * study.NANOSECONDS)
        for offset in (*range(335), *range(336, 434))
    )
    data = SimpleNamespace(
        row_count=len(timestamps),
        timestamps=timestamps,
        timeframe="1h",
        confirmed_through=first + timedelta(hours=434),
    )
    with pytest.raises(study.StudyError, match="checkpoint"):
        study._checkpoint_schedule(data)


def test_exact_body_equality_is_not_violation() -> None:
    assert not study._body_violation("support", 100.0, 100.0, 101.0)
    assert not study._body_violation("resistance", 101.0, 100.0, 101.0)


def test_exact_body_side_rules() -> None:
    assert study._body_violation("support", 100.01, 100.0, 101.0)
    assert study._body_violation("resistance", 100.99, 100.0, 101.0)
    assert not study._body_violation("support", 99.99, 100.0, 101.0)
    assert not study._body_violation("resistance", 101.01, 100.0, 101.0)


def test_shared_anchor_suppression() -> None:
    left = _record(1)
    right = _record(2, first_anchor_id=left.fields["first_anchor_id"])
    assert study._is_redundant(left.fields, right.fields)


def test_projection_and_slope_suppression() -> None:
    left = _record(1, price=100.0, slope=2.0)
    right = _record(2, price=100.1, slope=11.0)
    assert study._is_redundant(left.fields, right.fields)


def test_projection_or_slope_outside_threshold_is_not_redundant() -> None:
    left = _record(1, price=100.0, slope=2.0)
    right = _record(2, price=100.4, slope=13.0)
    assert not study._is_redundant(left.fields, right.fields)


def test_cross_role_lines_do_not_suppress_in_selector() -> None:
    support = _record(1, price=100.0, slope=2.0)
    resistance = _record(2, role="resistance", price=100.0, slope=2.0)
    selected = study.select_records(
        (support, resistance),
        selector="hash_order_matched_budget_v1",
        budget_per_role=4,
    )
    assert {item.fields["role"] for item in selected} == {"support", "resistance"}


@pytest.mark.parametrize("selector", study.CONTENDERS + study.CONTROLS)
def test_all_rankers_are_deterministic(selector: str) -> None:
    records = tuple(_record(index) for index in range(6))
    forward = [item.fields["candidate_id"] for item in sorted(records, key=lambda item: study._rank_key(item.fields, selector))]
    reverse = [item.fields["candidate_id"] for item in sorted(reversed(records), key=lambda item: study._rank_key(item.fields, selector))]
    assert forward == reverse


@pytest.mark.parametrize("budget", study.BUDGETS)
def test_matched_budget_never_exceeds_role_budget(budget: int) -> None:
    records = tuple(_record(index) for index in range(20)) + tuple(
        _record(index + 100, role="resistance") for index in range(20)
    )
    selected = study.select_records(
        records,
        selector="hash_order_matched_budget_v1",
        budget_per_role=budget,
    )
    assert sum(item.fields["role"] == "support" for item in selected) <= budget
    assert sum(item.fields["role"] == "resistance" for item in selected) <= budget


def test_input_order_reversal_preserves_membership() -> None:
    records = tuple(_record(index) for index in range(10))
    selected = study.select_records(
        records,
        selector="span_prominence_clearance_v1",
        budget_per_role=8,
    )
    reversed_selected = study.select_records(
        tuple(reversed(records)),
        selector="span_prominence_clearance_v1",
        budget_per_role=8,
    )
    assert [item.fields["candidate_id"] for item in selected] == [
        item.fields["candidate_id"] for item in reversed_selected
    ]


def test_latest_predecessor_is_dense_diagnostic_only() -> None:
    records = tuple(_record(index) for index in range(5))
    selected = study.select_records(
        records,
        selector="latest_valid_predecessor_v1",
        budget_per_role=None,
    )
    assert len(selected) == 5


def test_future_candle_mutation_cannot_change_earlier_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data, candidate, evidence, checkpoint = _causal_feature_fixture()
    birth = {
        "anchor_span_seconds": 97 * 3_600,
        "same_role_extrema_skip_count": 0,
        "minimum_anchor_prominence_bps": 10.0,
        "minimum_body_clearance_bps": 5.0,
        "slope_bps_per_day": 1.0,
        "absolute_slope_bps_per_day": 1.0,
    }
    monkeypatch.setattr(study.phase9c2, "_birth_features", lambda *args, **kwargs: birth)
    monkeypatch.setattr(study.phase9c2, "_extrema_by_role", lambda _data: {})
    monkeypatch.setattr(study.phase9c2, "_structure_id", lambda _candidate: "structure")
    result = SimpleNamespace(candidates=(candidate,), evidence=(evidence,))
    before = study._records_for_checkpoint(
        result,
        data,
        checkpoint=checkpoint,
        prefix_last_position=10,
    )

    future_open = list(data.open)
    future_open[15] = 1_000.0
    future_close = list(data.close)
    future_close[15] = 1_001.0
    future_high = list(data.high)
    future_high[15] = 1_002.0
    future_low = list(data.low)
    future_low[15] = 999.0
    mutated = SimpleNamespace(
        row_count=data.row_count,
        timestamps=data.timestamps,
        timeframe=data.timeframe,
        open=tuple(future_open),
        high=tuple(future_high),
        low=tuple(future_low),
        close=tuple(future_close),
    )
    after = study._records_for_checkpoint(
        result,
        mutated,
        checkpoint=checkpoint,
        prefix_last_position=10,
    )
    assert before[0].fields == after[0].fields


def test_future_evaluation_starts_strictly_after_checkpoint() -> None:
    first = datetime(2025, 1, 1, tzinfo=UTC)
    timestamps = tuple(
        int((first + timedelta(hours=offset)).timestamp() * study.NANOSECONDS)
        for offset in range(30)
    )
    data = SimpleNamespace(
        timeframe="1h",
        timestamps=timestamps,
        row_count=len(timestamps),
        low=tuple(99.0 for _ in timestamps),
        high=tuple(101.0 for _ in timestamps),
        open=tuple(99.0 for _ in timestamps),
        close=tuple(100.0 for _ in timestamps),
    )

    class Geometry:
        def value_at(self, _timestamp: datetime) -> float:
            return 100.0

    candidate = SimpleNamespace(
        geometry=Geometry(),
        role=SimpleNamespace(value="support"),
    )
    record = study.ResearchCandidate(candidate, None, {"role": "support"})
    outcome = study._future_evaluation(
        record,
        data,
        checkpoint=first + timedelta(hours=10),
        horizon="24h",
    )
    assert outcome["evaluation_available"] is False


def test_source_inventory_and_generation_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY", raising=False)
    with pytest.raises(study.StudyError, match="requires"):
        study.run_study(output_root=Path("/tmp/unused-11s1-output"))
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY", "1")
    with pytest.raises(study.StudyError, match="verification"):
        study.verify_bundle(output_root=Path("/tmp/unused-11s1-output"))


def test_existing_output_rejected_before_source_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "existing-output"
    root.mkdir()
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY", "1")
    source_accessed = False

    def fail_source_access() -> dict[str, object]:
        nonlocal source_accessed
        source_accessed = True
        raise AssertionError("source must not load")

    monkeypatch.setattr(study, "_source_bindings", fail_source_access)
    with pytest.raises(FileExistsError, match="existing output root"):
        study.run_study(output_root=root)
    assert not source_accessed


def test_staging_preparation_failure_causes_zero_source_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "missing-parent" / "output"
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY", "1")
    source_accessed = False

    def fail_source_access() -> dict[str, object]:
        nonlocal source_accessed
        source_accessed = True
        raise AssertionError("source must not load")

    def fail_staging(**_kwargs: object) -> str:
        raise OSError("staging unavailable")

    monkeypatch.setattr(study, "_source_bindings", fail_source_access)
    monkeypatch.setattr(study.tempfile, "mkdtemp", fail_staging)
    with pytest.raises(OSError, match="staging unavailable"):
        study.run_study(output_root=root)
    assert not source_accessed
    assert not list(root.parent.glob(f".{root.name}.*"))


def test_analysis_failure_removes_precreated_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "missing-parent" / "output"
    monkeypatch.setattr(
        study,
        "_source_bindings",
        lambda: (_ for _ in ()).throw(study.StudyError("source failure")),
    )
    with pytest.raises(study.StudyError, match="source failure"):
        study._run_analysis(output_root=root)
    assert not list(root.parent.glob(f".{root.name}.*"))


def test_bundle_failure_removes_precreated_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bundle-failure"
    staging = study._prepare_staging(root)
    monkeypatch.setattr(
        study,
        "_validated_contract",
        lambda: (_ for _ in ()).throw(study.StudyError("bundle failure")),
    )
    with pytest.raises(study.StudyError, match="bundle failure"):
        study._build_bundle(
            output_root=root,
            staging=staging,
            bindings={},
            validation_memberships={},
            validation_metrics={},
            validation={},
            lock={},
            holdout={"status": "NOT_OPENED_BEFORE_VALIDATION_LOCK"},
            holdout_memberships={},
            temporal={"status": "NOT_OPENED_BEFORE_VALIDATION_LOCK"},
            temporal_membership={},
            temporal_metrics={},
            dense_diagnostic={},
        )
    assert not staging.exists()


def test_atomic_directory_publication_uses_staging_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    staging = study._prepare_staging(root)
    replacements: list[tuple[Path, Path]] = []
    real_replace = study.os.replace

    def observe_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        source_path = Path(source)
        target_path = Path(target)
        if source_path == staging and target_path == root:
            replacements.append((source_path, target_path))
        real_replace(source, target)

    monkeypatch.setattr(study.os, "replace", observe_replace)
    monkeypatch.setattr(study, "_validated_contract", lambda: ({}, "contract"))
    monkeypatch.setattr(study, "_source_audit", lambda _bindings: {"audit": True})
    monkeypatch.setattr(study, "_summary_rows", lambda _metrics: ({"value": 1},))
    monkeypatch.setattr(study, "_temporal_summary_rows", lambda _temporal: ({"value": 1},))
    monkeypatch.setattr(
        study,
        "_decision",
        lambda *args: {"study_status": "TEST", "decision_id": "d"},
    )
    monkeypatch.setattr(study, "_manifest", lambda _root, _decision: {"manifest_id": "m"})
    try:
        result = study._build_bundle(
            output_root=root,
            staging=staging,
            bindings={},
            validation_memberships={},
            validation_metrics={},
            validation={},
            lock={},
            holdout={"status": "NOT_OPENED_BEFORE_VALIDATION_LOCK"},
            holdout_memberships={},
            temporal={"status": "NOT_OPENED_BEFORE_VALIDATION_LOCK"},
            temporal_membership={},
            temporal_metrics={},
            dense_diagnostic={},
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    assert result["decision_id"] == "d"
    assert root.is_dir()
    assert replacements == [(staging, root)]


def test_no_finalist_never_loads_holdout_or_temporal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "no-finalist"
    bindings = {"binding": "test"}
    metrics = {
        dataset_id: {"dataset_result_id": dataset_id}
        for dataset_id in study.VALIDATION_DATASETS
    }
    validation = {
        "status": "NO_STRUCTURAL_SELECTION_FINALIST",
        "winner": None,
        "all_variants": [],
        "eligible_variants": [],
    }
    monkeypatch.setattr(study, "_source_bindings", lambda: bindings)
    monkeypatch.setattr(study, "_load_validation_scope", lambda _bindings: ())
    monkeypatch.setattr(study, "_build_scope_results", lambda *_args, **_kwargs: ({}, metrics))
    monkeypatch.setattr(study, "_validation_result", lambda _metrics: validation)
    monkeypatch.setattr(study.phase9c2, "_load_cohort", lambda: (_ for _ in ()).throw(AssertionError("holdout loaded")))
    monkeypatch.setattr(study, "_load_temporal_scope", lambda: (_ for _ in ()).throw(AssertionError("temporal loaded")))
    monkeypatch.setattr(study, "_dense_diagnostic_baseline", lambda: {"baseline_id": "b"})
    monkeypatch.setattr(study, "_assert_source_unchanged", lambda _bindings: None)

    def publish(**kwargs: object) -> dict[str, str]:
        staging = kwargs["staging"]
        output_root = kwargs["output_root"]
        assert isinstance(staging, Path)
        assert isinstance(output_root, Path)
        assert (staging / "validation_lock.json").is_file()
        os.replace(staging, output_root)
        return {"decision_id": "d"}

    monkeypatch.setattr(study, "_build_bundle", publish)
    monkeypatch.setattr(study, "verify_bundle", lambda **_kwargs: {"decision_id": "d"})
    result = study._run_analysis(output_root=root)
    assert result == {"decision_id": "d"}
    assert root.is_dir()


def test_validation_lock_persisted_before_holdout_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "finalist"
    bindings = {"binding": "test"}
    metrics = {
        dataset_id: {"dataset_result_id": dataset_id}
        for dataset_id in study.VALIDATION_DATASETS
    }
    validation = {
        "status": "VALIDATION_FINALIST_FROZEN",
        "winner": {
            "selector_id": "span_prominence_clearance_v1",
            "budget_per_role": 4,
            "ranking_key": [],
        },
        "all_variants": [],
        "eligible_variants": [],
    }
    stage_holder: dict[str, Path] = {}
    original_prepare = study._prepare_staging

    def prepare(output_root: Path) -> Path:
        stage = original_prepare(output_root)
        stage_holder["path"] = stage
        return stage

    monkeypatch.setattr(study, "_prepare_staging", prepare)
    monkeypatch.setattr(study, "_source_bindings", lambda: bindings)
    monkeypatch.setattr(study, "_load_validation_scope", lambda _bindings: ())
    monkeypatch.setattr(study, "_build_scope_results", lambda *_args, **_kwargs: ({}, metrics))
    monkeypatch.setattr(study, "_validation_result", lambda _metrics: validation)

    dataset_rows = tuple(
        SimpleNamespace(
            dataset_id=dataset_id,
            asset="SUIUSDT",
            timeframe="1h" if dataset_id.endswith("1h") else "4h",
            input_data=SimpleNamespace(input_identity=f"input-{dataset_id}"),
        )
        for dataset_id in study.HOLDOUT_DATASETS
    )

    def load_cohort() -> SimpleNamespace:
        assert (stage_holder["path"] / "validation_lock.json").is_file()
        return SimpleNamespace(datasets=dataset_rows)

    def load_provider(*_args: object, **_kwargs: object) -> object:
        assert (stage_holder["path"] / "validation_lock.json").is_file()
        return object()

    monkeypatch.setattr(study.phase9c2, "_load_cohort", load_cohort)
    monkeypatch.setattr(study.phase9c2, "_foundation_config", lambda: object())
    monkeypatch.setattr(study.phase9c2, "_provider_config", lambda: object())
    monkeypatch.setattr(study.phase9c2, "_load_persisted_provider_result", load_provider)
    monkeypatch.setattr(study.phase9c2, "_provider_result_id", lambda _result: "provider-result")
    monkeypatch.setattr(study, "_checkpoint_schedule", lambda _data: ())
    monkeypatch.setattr(
        study,
        "_holdout_result",
        lambda *_args, **_kwargs: (
            {"status": "STRUCTURAL_SELECTION_HOLDOUT_PASSED", "winner": validation["winner"]},
            {},
        ),
    )
    monkeypatch.setattr(
        study,
        "_temporal_result",
        lambda *_args, **_kwargs: (
            {"status": "STRUCTURAL_SELECTION_TEMPORAL_REJECTED"},
            {},
            {},
        ),
    )
    monkeypatch.setattr(study, "_dense_diagnostic_baseline", lambda: {"baseline_id": "b"})
    monkeypatch.setattr(study, "_assert_source_unchanged", lambda _bindings: None)

    def publish(**kwargs: object) -> dict[str, str]:
        staging = kwargs["staging"]
        output_root = kwargs["output_root"]
        assert isinstance(staging, Path)
        assert isinstance(output_root, Path)
        assert (staging / "validation_lock.json").is_file()
        os.replace(staging, output_root)
        return {"decision_id": "d"}

    monkeypatch.setattr(study, "_build_bundle", publish)
    monkeypatch.setattr(study, "verify_bundle", lambda **_kwargs: {"decision_id": "d"})
    result = study._run_analysis(output_root=root)
    assert result == {"decision_id": "d"}
    assert root.is_dir()


def test_selection_helpers_do_not_execute_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_provider(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("provider must not execute")

    monkeypatch.setattr(study.phase9c2, "discover_trendlines", fail_provider)
    records = (_record(1), _record(2))
    selected = study.select_records(
        records,
        selector="hash_order_matched_budget_v1",
        budget_per_role=4,
    )
    assert len(selected) == 2


def test_not_opened_payload_has_no_selector_outputs() -> None:
    payload = study._not_opened(
        "checkpoint_membership",
        "suiusdt_1h",
        "NOT_OPENED_BEFORE_VALIDATION_LOCK",
    )
    assert payload["selector_outputs"] == []


def test_structural_filter_excludes_ineligible_records() -> None:
    eligible = _record(1)
    ineligible_fields = {**eligible.fields, "structurally_eligible": False}
    ineligible = study.ResearchCandidate(None, None, ineligible_fields)
    selected = study.select_records(
        (eligible, ineligible),
        selector="hash_order_matched_budget_v1",
        budget_per_role=4,
    )
    assert [item.fields["candidate_id"] for item in selected] == [
        eligible.fields["candidate_id"]
    ]


def test_outcome_summary_retains_counts_for_pooled_rates() -> None:
    evaluations = [
        {
            "evaluation_available": True,
            "has_exact_contact": True,
            "survives_exact_side": True,
            "contact_and_survives_exact_side": True,
            "future_contact_count": 2,
            "future_body_violation_count": 0,
        },
        {
            "evaluation_available": True,
            "has_exact_contact": False,
            "survives_exact_side": True,
            "contact_and_survives_exact_side": False,
            "future_contact_count": 0,
            "future_body_violation_count": 0,
        },
    ]
    summary = study._outcome_summary(evaluations)
    assert summary["evaluation_available_count"] == 2
    assert summary["contact_count"] == 1
    assert summary["survival_count"] == 2
    assert summary["contact_and_survival_count"] == 1


def test_pooled_delta_uses_counts_not_dataset_rate_mean() -> None:
    def selector(selector_id: str, survival_count: int, evaluation_count: int) -> dict:
        outcome = {
            "evaluation_available_count": evaluation_count,
            "survival_count": survival_count,
            "contact_and_survival_count": survival_count,
        }
        return {
            "selector_id": selector_id,
            "budget_per_role": 4,
            "outcomes": {
                horizon: {"candidate_weighted": outcome}
                for horizon in study.HORIZONS
            },
        }

    metrics = {
        "small": {
            "selectors": [
                selector("hash_order_matched_budget_v1", 1, 1),
                selector("contender", 1, 1),
            ]
        },
        "large": {
            "selectors": [
                selector("hash_order_matched_budget_v1", 50, 100),
                selector("contender", 60, 100),
            ]
        },
    }
    assert study._pooled_delta(
        metrics,
        selector="contender",
        budget=4,
        horizon="96h",
        field="survival_rate",
    ) == pytest.approx(10 / 101)


def test_horizon_mapping_is_fixed_by_timeframe() -> None:
    assert study.HORIZON_HOURS == {"24h": 24, "48h": 48, "96h": 96}
    assert {
        horizon: study.HORIZON_HOURS[horizon] * 3_600 // study.INTERVAL_SECONDS["1h"]
        for horizon in study.HORIZONS
    } == {"24h": 24, "48h": 48, "96h": 96}
    assert {
        horizon: study.HORIZON_HOURS[horizon] * 3_600 // study.INTERVAL_SECONDS["4h"]
        for horizon in study.HORIZONS
    } == {"24h": 6, "48h": 12, "96h": 24}


def test_jaccard_empty_sets_are_identical() -> None:
    assert study._jaccard(set(), set()) == 1.0
    assert study._jaccard({"a"}, {"b"}) == 0.0


def test_decision_persists_all_validation_gate_results() -> None:
    validation = {
        "status": "NO_STRUCTURAL_SELECTION_FINALIST",
        "winner": None,
        "all_variants": [{"selector_id": "x", "budget_per_role": 4}],
        "eligible_variants": [],
    }
    decision = study._decision(
        validation,
        {"validation_lock_id": "lock"},
        {"status": "NOT_OPENED_BEFORE_VALIDATION_LOCK"},
        {"status": "NOT_OPENED_BEFORE_VALIDATION_LOCK"},
        {"baseline_id": "baseline"},
    )
    assert decision["validation_gate_results"] == validation["all_variants"]
    assert decision["validation_eligible_variants"] == []
    assert decision["dense_diagnostic_baseline"]["baseline_id"] == "baseline"


def test_validation_lock_without_finalist_is_explicit() -> None:
    validation = {
        "status": "NO_STRUCTURAL_SELECTION_FINALIST",
        "winner": None,
    }
    lock = study._validation_lock(
        validation,
        bindings={"source": "frozen"},
        metrics_by_dataset={
            dataset_id: {"dataset_result_id": dataset_id}
            for dataset_id in study.VALIDATION_DATASETS
        },
    )
    assert lock["locked_finalist"] is None
    assert lock["status"] == "NO_STRUCTURAL_SELECTION_FINALIST"
    assert len(lock["validation_lock_id"]) == 64


def test_manifest_requires_exact_twenty_members(tmp_path: Path) -> None:
    for index in range(20):
        path = tmp_path / f"member_{index}.json"
        path.write_bytes(b"{}\n")
    decision = {"decision_id": "a" * 64}
    manifest = study._manifest(tmp_path, decision)
    assert manifest["member_count"] == 20
    assert len(manifest["members"]) == 20


def test_external_bundle_verification_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external frozen study disabled")
    expected = {
        "study_status": "NO_STRUCTURAL_SELECTION_FINALIST",
        "decision_id": "44ffc590402b49d25b44a327522411e2f5ffadce13607fe0ed957e5db02e3b9d",
        "manifest_id": "3c0f999220b4397bcfc208475c876fb79af1ec1df0bfc558d245bc56e3850930",
        "output_inventory_sha256": "3731fd6d35472002eae4ae81cc9eb0d87bfcdfbc8552e44209ba1ede46b2c4b3",
        "provider_execution_count": 0,
        "network_request_count": 0,
    }
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY", raising=False)
    assert study.verify_bundle(output_root=study.OUTPUT_ROOT) == expected


@pytest.mark.parametrize(
    ("relative_path", "mutator"),
    [
        (
            "datasets/btcusdt_1h/checkpoint_membership.json",
            lambda payload: payload["checkpoints"][0]["selectors"][0]["selected_candidates"][0].update(
                candidate_id="f" * 64
            ),
        ),
        (
            "datasets/btcusdt_1h/selector_metrics.json",
            lambda payload: payload["selectors"][0]["structural"].update(selected_count=999),
        ),
        (
            "validation_lock.json",
            lambda payload: payload.update(source_binding_digest="0" * 64),
        ),
        (
            "decision.json",
            lambda payload: payload.update(study_status="STRUCTURAL_SELECTION_PROMOTION_CANDIDATE"),
        ),
    ],
)
def test_forged_derived_member_rejected_after_manifest_rebinding(
    tmp_path: Path,
    relative_path: str,
    mutator: object,
) -> None:
    root = _copy_external_bundle(tmp_path)
    path = root / relative_path
    payload = study._load_json(path)
    assert callable(mutator)
    mutator(payload)
    if relative_path == "validation_lock.json":
        identity_payload = {
            key: value for key, value in payload.items() if key != "validation_lock_id"
        }
        payload["validation_lock_id"] = study.deterministic_hash(
            study.LOCK_NAMESPACE,
            identity_payload,
        )
    elif relative_path == "decision.json":
        identity_payload = {
            key: value for key, value in payload.items() if key != "decision_id"
        }
        payload["decision_id"] = study.deterministic_hash(
            study.DECISION_NAMESPACE,
            identity_payload,
        )
    path.write_bytes(study._canonical_bytes(payload))
    _rebind_manifest(root)
    with pytest.raises(study.StudyError):
        study.verify_bundle(output_root=root)


def test_source_inventories_unchanged_before_and_after_external_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external frozen study disabled")
    bindings = study._source_bindings()
    roots = {
        "phase9c1": study.phase9c2.SOURCE_ROOT,
        "phase9c2": study.SOURCE_ROOT,
        "phase10c1": study.phase10c2.SOURCE_ROOT,
        "phase10c2": study.TEMPORAL_ROOT,
    }
    before = {
        name: study._inventory_sha256(study._inventory(root)) for name, root in roots.items()
    }
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11S1_STUDY", raising=False)
    study.verify_bundle(output_root=study.OUTPUT_ROOT)
    study._assert_source_unchanged(bindings)
    after = {
        name: study._inventory_sha256(study._inventory(root)) for name, root in roots.items()
    }
    assert before == after
