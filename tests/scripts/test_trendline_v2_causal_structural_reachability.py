from __future__ import annotations

import hashlib
import json
import shutil
from itertools import product
from pathlib import Path

import pytest
import scripts.analyze_trendline_v2_causal_structural_reachability as reachability

from scripts.analyze_trendline_v2_causal_structural_reachability import (
    HORIZONS_HOURS,
    TEMPORAL_V2_ROOT,
    RawDataset,
    ReachabilityError,
    _artifact_inventory,
    _build_pair_comparison,
    _canonical_bytes,
    _feature_key,
    _identity_hash,
    _inventory_sha256,
    build_feature_rows,
    classify_stratum_cell,
    decision_from_comparisons,
    join_horizon_outcomes,
    matched_within_stratum,
    publish_bundle,
    read_allowed_raw_member,
    verify_reachability_bundle,
    verify_raw_source_root,
    verify_temporal_v2_root,
)


def _dataset(extra_bars: int = 0) -> RawDataset:
    timestamps = tuple(
        1_767_225_600_000_000_000 + index * 3_600_000_000_000
        for index in range(7 + extra_bars)
    )
    close = tuple(100.0 + index for index in range(len(timestamps)))
    high = tuple(value + 1.0 for value in close)
    low = tuple(value - 1.0 for value in close)
    return RawDataset(
        dataset_id="btcusdt_1h",
        asset="BTCUSDT",
        timeframe="1h",
        timestamps=timestamps,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=tuple(1.0 for _ in timestamps),
        input_identity="input-test",
    )


def _row(
    *,
    checkpoint_index: int = 1,
    role: str = "support",
    lineage_id: str = "lineage-1",
    selection_id: str = "selection-1",
    derivation_type: str = "contender",
    control_id: str | None = None,
    contender: str = "joint_incumbent_near_v1",
    role_transfer: bool = False,
) -> dict[str, object]:
    return {
        "contender_policy_id": contender,
        "budget_per_role": 1,
        "derivation_type": derivation_type,
        "control_policy_id_or_null": control_id,
        "dataset_id": "btcusdt_1h",
        "checkpoint_index": checkpoint_index,
        "semantic_role_at_selection": role,
        "semantic_role": role,
        "lineage_id": lineage_id,
        "selection_id": selection_id,
        "checkpoint_observed_at": (
            "2026-01-01T03:00:00Z"
            if checkpoint_index == 1
            else "2026-01-01T04:00:00Z"
        ),
        "role_transfer": role_transfer,
        "fixed_geometry": {
            "start_time": "2025-12-31T00:00:00Z",
            "end_time": "2026-01-01T00:00:00Z",
            "start_price": 100.0,
            "end_price": 100.0,
        },
    }


def _outcomes(feature: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "contender_policy_id": feature["contender_policy_id"],
            "budget_per_role": feature["budget_per_role"],
            "derivation_type": feature["derivation_type"],
            "control_policy_id_or_null": feature["control_policy_id_or_null"],
            "dataset_id": feature["dataset_id"],
            "checkpoint_index": feature["checkpoint_index"],
            "semantic_role_at_selection": feature["semantic_role_at_selection"],
            "lineage_id": feature["lineage_id"],
            "selection_id": feature["selection_id"],
            "horizon_hours": horizon,
            "survival": True,
            "zone_contact": False,
            "post_contact_reaction": False,
        }
        for horizon in HORIZONS_HOURS
    ]


def test_feature_row_is_unique_before_horizon_expansion() -> None:
    features, errors = build_feature_rows([_row()], {"btcusdt_1h": _dataset()})
    joined, join_errors = join_horizon_outcomes(features, _outcomes(features[0]))

    assert errors == []
    assert join_errors == []
    assert len(features) == 1
    assert len(joined) == 3
    assert {_feature_key(row) for row in joined} == {_feature_key(features[0])}
    assert [row["horizon_hours"] for row in joined] == [24, 48, 96]


def test_outcome_join_requires_exact_three_and_full_relevant_consumption() -> None:
    features, errors = build_feature_rows([_row()], {"btcusdt_1h": _dataset()})
    outcomes = _outcomes(features[0])
    orphan = dict(outcomes[0])
    orphan["checkpoint_index"] = 2
    outcomes.append(orphan)
    joined, join_errors = join_horizon_outcomes(features, outcomes[:2] + [orphan])

    assert errors == []
    assert len(joined) == 2
    assert "outcome does not bind to feature identity" in join_errors
    assert "orphan outcome key" in join_errors


def test_duplicate_feature_rows_are_rejected_not_selected() -> None:
    features, errors = build_feature_rows(
        [_row(), _row()], {"btcusdt_1h": _dataset()}
    )

    assert len(features) == 1
    assert "duplicate causal feature key" in errors


def test_history_is_contender_namespaced() -> None:
    rows = [
        _row(checkpoint_index=1, selection_id="near-1"),
        _row(checkpoint_index=2, selection_id="near-2"),
        _row(
            checkpoint_index=1,
            selection_id="hash-1",
            derivation_type="matched_control",
            control_id="joint_hash_order_control_v1",
        ),
        _row(
            checkpoint_index=2,
            selection_id="hash-2",
            derivation_type="matched_control",
            control_id="joint_hash_order_control_v1",
        ),
    ]
    features, errors = build_feature_rows(rows, {"btcusdt_1h": _dataset()})

    assert errors == []
    second_near = next(row for row in features if row["selection_id"] == "near-2")
    second_hash = next(row for row in features if row["selection_id"] == "hash-2")
    assert second_near["previous_observation_key"][-1] == "near-1"
    assert second_hash["previous_observation_key"][-1] == "hash-1"


def test_role_transfer_is_included_in_primary_feature_population() -> None:
    rows = [
        _row(checkpoint_index=1, role="support", selection_id="support-1"),
        _row(
            checkpoint_index=2,
            role="resistance",
            selection_id="resistance-2",
            role_transfer=True,
        ),
    ]
    features, errors = build_feature_rows(rows, {"btcusdt_1h": _dataset()})
    second = next(row for row in features if row["selection_id"] == "resistance-2")

    assert errors == []
    assert len(features) == 2
    assert second["role_transfer"] is True
    assert second["previous_observation_key"][-1] == "support-1"
    assert second["prior_observed_distance_change_rate"] is not None


def test_analysis_covers_each_dataset_and_role_for_each_comparison() -> None:
    def fake_read_json(path: Path) -> object:
        if path.name in {"checkpoint_selection.json", "candidate_outcomes.json"}:
            return {"records": []}
        if path.name == "policy_metrics.json":
            return {"metrics": {}}
        if path.name == "structural_context.json":
            return {"selection_records": [], "outcome_records": []}
        raise AssertionError(f"unexpected synthetic path: {path}")

    original_read_json = reachability._read_json
    reachability._read_json = fake_read_json
    try:
        result = reachability.build_analysis(
            reachability.VerifiedSources(
                temporal_root=Path("/synthetic/temporal"),
                raw_root=Path("/synthetic/raw"),
                raw_datasets={},
                temporal_snapshot={},
                raw_snapshot={},
            )
        )
    finally:
        reachability._read_json = original_read_json

    expected = {
        (contender, budget, control, dataset_id, role)
        for contender, budget, control, dataset_id, role in product(
            reachability.CONTENDERS,
            reachability.BUDGETS,
            reachability.CONTROLS,
            reachability.DATASETS,
            reachability.ROLES,
        )
    }
    actual = {
        (
            comparison["population_namespace"][0],
            comparison["population_namespace"][1],
            comparison["population_namespace"][3],
            comparison["population_namespace"][4],
            comparison["role"],
        )
        for comparison in result["comparisons"]
    }

    assert len(result["comparisons"]) == len(expected)
    assert actual == expected
    assert {
        "feature_rows",
        "causal_feature_identities",
        "feature_evidence",
        "selection_evidence",
        "outcome_evidence",
        "r3b_reference_metrics",
        "structural_context_summary",
        "source_evidence",
    } <= result.keys()


def test_structural_evidence_errors_force_incomplete_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_json(path: Path) -> object:
        if path.name in {"checkpoint_selection.json", "candidate_outcomes.json"}:
            return {"records": []}
        if path.name == "policy_metrics.json":
            return {"metrics": {}}
        if path.name == "structural_context.json":
            return []
        raise AssertionError(f"unexpected synthetic path: {path}")

    monkeypatch.setattr(reachability, "_read_json", fake_read_json)
    result = reachability.build_analysis(
        reachability.VerifiedSources(
            temporal_root=Path("/synthetic/temporal"),
            raw_root=Path("/synthetic/raw"),
            raw_datasets={},
            temporal_snapshot={},
            raw_snapshot={},
        )
    )

    assert result["status"] == "R4_DIAGNOSTIC_INCOMPLETE"
    assert result["diagnostic_decision"] is None
    assert result["unresolved_evidence_count"] > 0


def test_future_rows_do_not_change_origin_features() -> None:
    row = _row()
    short_features, short_errors = build_feature_rows(
        [row], {"btcusdt_1h": _dataset()}
    )
    long_features, long_errors = build_feature_rows(
        [row], {"btcusdt_1h": _dataset(extra_bars=5)}
    )

    assert short_errors == long_errors == []
    fields = (
        "origin_close",
        "origin_atr",
        "initial_distance_atr",
        "geometry_projected_distance_atr_24h",
        "geometry_projected_distance_atr_48h",
        "geometry_projected_distance_atr_96h",
    )
    assert {field: short_features[0][field] for field in fields} == {
        field: long_features[0][field] for field in fields
    }


def test_outcome_mutation_cannot_change_feature_or_stratum() -> None:
    features, errors = build_feature_rows([_row()], {"btcusdt_1h": _dataset()})
    original_feature = dict(features[0])
    outcomes = _outcomes(features[0])
    outcomes[0]["survival"] = False
    joined, join_errors = join_horizon_outcomes(features, outcomes)

    assert errors == join_errors == []
    assert features[0] == original_feature
    assert len(joined) == 3


def test_cell_classification_precedence_and_empty_both_match() -> None:
    assert classify_stratum_cell([], [], unresolved=True) == "unresolved"
    assert classify_stratum_cell([], [], duplicate=True) == "duplicate"
    assert classify_stratum_cell([{"id": 1}], [{"id": 2}]) == "paired"
    assert classify_stratum_cell([{"id": 1}], []) == "contender_only"
    assert classify_stratum_cell([], [{"id": 2}]) == "control_only"
    assert classify_stratum_cell([], []) == "empty_both"
    assert matched_within_stratum(
        {
            "paired_cells": 1,
            "contender_only_cells": 0,
            "control_only_cells": 0,
            "duplicate_cells": 0,
            "unresolved_cells": 0,
            "empty_both_cells": 3,
        }
    )


@pytest.mark.parametrize(
    ("comparison", "expected"),
    [
        ({"paired_cells": 0}, ("R4_DIAGNOSTIC_COMPLETE", "INSUFFICIENT_REACHABLE_SUPPORT")),
        (
            {"paired_cells": 1, "contender_only_cells": 1},
            ("R4_DIAGNOSTIC_INCOMPLETE", None),
        ),
        (
            {"paired_cells": 1, "matched": True, "survival_delta_96h": 0.0},
            ("R4_DIAGNOSTIC_COMPLETE", "REACHABILITY_ELIGIBILITY_HYPOTHESIS_SUPPORTED"),
        ),
        (
            {"paired_cells": 1, "matched": True, "survival_delta_96h": -0.1},
            ("R4_DIAGNOSTIC_COMPLETE", "CLOSE_STRUCTURAL_COMPRESSION_BRANCH"),
        ),
    ],
)
def test_decision_precedence(comparison: dict[str, object], expected: tuple[str, str | None]) -> None:
    assert decision_from_comparisons([comparison]) == expected


def test_blocked_and_integrity_errors_have_no_decision() -> None:
    assert decision_from_comparisons([], blocked=True) == (
        "R4_DIAGNOSTIC_BLOCKED",
        None,
    )
    assert decision_from_comparisons(
        [{"paired_cells": 1, "matched": True, "survival_delta_96h": -1.0}],
        source_errors=1,
    ) == ("R4_DIAGNOSTIC_INCOMPLETE", None)


def _write_raw_bundle(root: Path) -> dict[str, tuple[str, int]]:
    members: dict[str, tuple[str, int]] = {}
    for dataset_id, timeframe in (
        ("btcusdt_1h", "1h"),
        ("btcusdt_4h", "4h"),
        ("ethusdt_1h", "1h"),
        ("ethusdt_4h", "4h"),
    ):
        timestamps = [
            "2026-01-01T00:00:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T02:00:00Z",
        ]
        if timeframe == "4h":
            timestamps = [
                "2026-01-01T00:00:00Z",
                "2026-01-01T04:00:00Z",
                "2026-01-01T08:00:00Z",
            ]
        input_data = {
            "asset": dataset_id.split("_")[0].upper(),
            "timeframe": timeframe,
            "timestamps": timestamps,
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
            "volume": [1.0, 1.0, 1.0],
            "input_identity": f"input-{dataset_id}",
        }
        payload = {
            "dataset_id": dataset_id,
            "network_request_count": 0,
            "provider_execution_count": 1,
            "provider_result": {"request": {"input_data": input_data}},
        }
        relative = f"datasets/{dataset_id}/provider_result.json"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(data)
        members[relative] = (hashlib.sha256(data).hexdigest(), len(data))
    return members


def test_raw_source_allows_untouched_extra_files_but_rejects_extra_access(tmp_path: Path) -> None:
    expected = _write_raw_bundle(tmp_path)
    extra = tmp_path / "datasets" / "suiusdt_1h" / "provider_result.json"
    extra.parent.mkdir(parents=True)
    extra.write_text("untouched", encoding="utf-8")

    datasets, snapshot = verify_raw_source_root(tmp_path, expected_members=expected)

    assert sorted(datasets) == ["btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h"]
    assert snapshot["members"]
    with pytest.raises(ReachabilityError, match="prohibited"):
        read_allowed_raw_member(tmp_path, "datasets/suiusdt_1h/provider_result.json")


def test_raw_source_mutation_is_rejected(tmp_path: Path) -> None:
    expected = _write_raw_bundle(tmp_path)
    target = tmp_path / "datasets" / "btcusdt_1h" / "provider_result.json"
    target.write_bytes(target.read_bytes() + b"x")

    with pytest.raises(ReachabilityError, match="byte drift"):
        verify_raw_source_root(tmp_path, expected_members=expected)


def _copy_temporal_bundle(tmp_path: Path) -> Path:
    target = tmp_path / "temporal"
    shutil.copytree(TEMPORAL_V2_ROOT, target)
    return target


def _rebind_temporal_manifest(root: Path, target_path: str) -> None:
    path = root / target_path
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    members = []
    for member in manifest["members"]:
        value = dict(member)
        if value["path"] == target_path:
            value["byte_length"] = path.stat().st_size
            value["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        members.append(value)
    manifest["members"] = members
    manifest["output_inventory_sha256"] = _inventory_sha256(
        _artifact_inventory(root, include_manifest=False)
    )
    payload = {key: value for key, value in manifest.items() if key != "manifest_id"}
    manifest["manifest_id"] = _identity_hash(
        reachability.TEMPORAL_V2_MANIFEST_NAMESPACE, payload
    )
    (root / "manifest.json").write_bytes(_canonical_bytes(manifest))


def test_rehashed_temporal_decision_forgery_is_rejected(tmp_path: Path) -> None:
    root = _copy_temporal_bundle(tmp_path)
    decision_path = root / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["forged_evidence"] = True
    decision_path.write_bytes(_canonical_bytes(decision))
    _rebind_temporal_manifest(root, "decision.json")

    with pytest.raises(ReachabilityError, match="temporal manifest"):
        verify_temporal_v2_root(root)


def test_rehashed_temporal_validation_lock_forgery_is_rejected(tmp_path: Path) -> None:
    root = _copy_temporal_bundle(tmp_path)
    lock_path = root / "validation_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["forged_evidence"] = True
    lock_path.write_bytes(_canonical_bytes(lock))
    _rebind_temporal_manifest(root, "validation_lock.json")

    with pytest.raises(ReachabilityError, match="temporal manifest"):
        verify_temporal_v2_root(root)


def test_temporal_manifest_preserved_identity_is_rejected(tmp_path: Path) -> None:
    root = _copy_temporal_bundle(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["forged_evidence"] = True
    manifest_path.write_bytes(_canonical_bytes(manifest))

    with pytest.raises(ReachabilityError, match="temporal manifest"):
        verify_temporal_v2_root(root)


def _synthetic_r4_payload() -> dict[str, object]:
    return {
        "schema_version": "trendline_v2_phase11r4_causal_structural_reachability_v1",
        "status": "R4_DIAGNOSTIC_INCOMPLETE",
        "diagnostic_decision": None,
        "unresolved_evidence_count": 1,
        "unresolved_reconciliation_count": 1,
        "unresolved_errors": ["synthetic evidence"],
        "feature_rows": [{"feature_id": "feature-1"}],
        "comparisons": [{"comparison_id": "comparison-1"}],
        "source_binding": {
            "schema_version": "trendline_v2_phase11r4_source_binding_v1",
            "source_before": {"source": "synthetic"},
            "source_after": {"source": "synthetic"},
        },
    }


def _rebind_r4_bundle(root: Path, mutate: object) -> None:
    diagnostic_path = root / "reachability_diagnostic.json"
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    mutate(diagnostic)
    diagnostic_payload = {
        key: value for key, value in diagnostic.items() if key != "diagnostic_id"
    }
    diagnostic["diagnostic_id"] = _identity_hash(
        "trendline_v2_phase11r4_diagnostic", diagnostic_payload
    )
    diagnostic_path.write_bytes(_canonical_bytes(diagnostic))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    members = list(_artifact_inventory(root, include_manifest=False))
    manifest["members"] = members
    manifest["output_inventory_sha256"] = _inventory_sha256(members)
    manifest["diagnostic_id"] = diagnostic["diagnostic_id"]
    manifest_payload = {key: value for key, value in manifest.items() if key != "manifest_id"}
    manifest["manifest_id"] = _identity_hash(
        reachability.R4_MANIFEST_NAMESPACE, manifest_payload
    )
    manifest_path.write_bytes(_canonical_bytes(manifest))


def test_source_backed_r4_bundle_verification_and_rebound_evidence_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _synthetic_r4_payload()
    root = tmp_path / "bundle"
    publish_bundle(root, payload)
    verified = reachability.VerifiedSources(
        temporal_root=tmp_path,
        raw_root=tmp_path,
        raw_datasets={},
        temporal_snapshot={"source": "synthetic"},
        raw_snapshot={"source": "synthetic"},
    )
    monkeypatch.setattr(reachability, "verify_sources", lambda *args, **kwargs: verified)
    monkeypatch.setattr(reachability, "build_analysis", lambda _: payload)

    result = verify_reachability_bundle(root, source_backed=True)
    assert result["member_count"] == 2

    for field in ("feature_rows", "comparisons", "diagnostic_decision"):
        forged_root = tmp_path / f"forged-{field}"
        shutil.copytree(root, forged_root)
        if field == "feature_rows":
            _rebind_r4_bundle(forged_root, lambda value: value["feature_rows"].append({"forged": True}))
        elif field == "comparisons":
            _rebind_r4_bundle(forged_root, lambda value: value["comparisons"].append({"forged": True}))
        else:
            _rebind_r4_bundle(forged_root, lambda value: value.update({"diagnostic_decision": "FORGED"}))
        with pytest.raises(ReachabilityError, match="source-derived R4 artifact"):
            verify_reachability_bundle(
                forged_root,
                source_backed=False,
                expected_evidence=payload,
            )


def test_complete_status_with_unresolved_evidence_is_rejected(tmp_path: Path) -> None:
    payload = _synthetic_r4_payload()
    payload["status"] = "R4_DIAGNOSTIC_COMPLETE"
    with pytest.raises(ReachabilityError, match="unresolved"):
        publish_bundle(tmp_path / "bundle", payload)


def test_role_specific_eligible_cells() -> None:
    def row(derivation: str, control: str | None) -> dict[str, object]:
        return {
            "contender_policy_id": "joint_incumbent_near_v1",
            "budget_per_role": 1,
            "derivation_type": derivation,
            "control_policy_id_or_null": control,
            "dataset_id": "btcusdt_1h",
            "checkpoint_index": 1,
            "semantic_role_at_selection": "support",
            "horizon_hours": 96,
            "geometry_evaluable": True,
            "geometry_projected_distance_atr_96h": 1.0,
            "outcome": {"survival": True},
        }

    source_cells = {
        ("joint_incumbent_near_v1", 1, "contender", None, "btcusdt_1h", 1): {
            "counts": {"support": 1, "resistance": 0}
        },
        ("joint_incumbent_near_v1", 1, "matched_control", "joint_hash_order_control_v1", "btcusdt_1h", 1): {
            "counts": {"support": 1, "resistance": 0}
        },
    }
    comparison = _build_pair_comparison(
        contender="joint_incumbent_near_v1",
        budget=1,
        control="joint_hash_order_control_v1",
        dataset_id="btcusdt_1h",
        role="support",
        rows=[row("contender", None), row("matched_control", "joint_hash_order_control_v1")],
        source_cells=source_cells,
        source_errors=[],
    )
    assert comparison["eligible_cells"] == 1
    assert comparison["paired_cells"] == 1


def _summary_feature(
    namespace: tuple[object, ...],
    *,
    role: str = "support",
    checkpoint: int = 1,
    lineage: str = "lineage-1",
    selection: str = "selection-1",
    distance: float = 1.0,
    state: str = "STRICT_ACTIVE_NEAR",
) -> dict[str, object]:
    return {
        "population_namespace": list(namespace),
        "contender_policy_id": namespace[0],
        "budget_per_role": namespace[1],
        "derivation_type": namespace[2],
        "control_policy_id_or_null": namespace[3],
        "dataset_id": namespace[4],
        "checkpoint_index": checkpoint,
        "semantic_role_at_selection": role,
        "lineage_id": lineage,
        "selection_id": selection,
        "state": state,
        "geometry_evaluable": True,
        "geometry_projected_distance_atr_24h": distance,
        "geometry_projected_distance_atr_48h": distance,
        "geometry_projected_distance_atr_96h": distance,
        "initial_distance_atr": distance,
        "origin_close": 100.0,
        "origin_atr": 1.0,
    }


def _comparison_source_cells(
    contender: str = "joint_incumbent_near_v1",
    budget: int = 1,
    control: str = "joint_hash_order_control_v1",
) -> dict[tuple[object, ...], dict[str, object]]:
    cells: dict[tuple[object, ...], dict[str, object]] = {}
    for checkpoint in range(1, 23):
        count = 1 if checkpoint == 1 else 0
        cells[(contender, budget, "contender", None, "btcusdt_1h", checkpoint)] = {
            "counts": {"support": count, "resistance": 0},
            "duplicate": False,
            "reconciliation_errors": [],
        }
        cells[(contender, budget, "matched_control", control, "btcusdt_1h", checkpoint)] = {
            "counts": {"support": count, "resistance": 0},
            "duplicate": False,
            "reconciliation_errors": [],
        }
    return cells


def _comparison_feature_rows() -> list[dict[str, object]]:
    contender_ns = ("joint_incumbent_near_v1", 1, "contender", None, "btcusdt_1h")
    control_ns = (
        "joint_incumbent_near_v1",
        1,
        "matched_control",
        "joint_hash_order_control_v1",
        "btcusdt_1h",
    )
    return [
        _summary_feature(contender_ns, selection="c1"),
        _summary_feature(control_ns, selection="h1"),
    ]


def _comparison_outcomes(features: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            **feature,
            "horizon_hours": 96,
            "outcome": {"evaluable": True, "survival": True},
        }
        for feature in features
    ]


def test_feature_and_outcome_summaries_preserve_full_population_namespace() -> None:
    first = _summary_feature(
        ("joint_incumbent_near_v1", 1, "contender", None, "btcusdt_1h")
    )
    second = _summary_feature(
        (
            "joint_incumbent_tenure_v1",
            3,
            "matched_control",
            "joint_hash_order_control_v1",
            "btcusdt_1h",
        ),
        selection="selection-2",
    )
    feature_summary = reachability._feature_evidence_summary([first, second])
    assert {
        tuple(row["population_namespace"])
        for row in feature_summary["by_population_namespace_role"]
    } == {
        tuple(first["population_namespace"]),
        tuple(second["population_namespace"]),
    }
    outcome_rows = [
        {**first, "horizon_hours": 96, "outcome": {"evaluable": True, "survival": True}},
        {**second, "horizon_hours": 96, "outcome": {"evaluable": True, "survival": False}},
    ]
    outcome_summary = reachability._outcome_evidence_summary(outcome_rows)
    assert {tuple(row["population_namespace"]) for row in outcome_summary} == {
        tuple(first["population_namespace"]),
        tuple(second["population_namespace"]),
    }
    assert len(feature_summary["support_resistance_balance"]) == 2


def test_compression_retention_counts_rows_not_role_mapping_keys() -> None:
    namespace = ("joint_incumbent_near_v1", 1, "contender", None, "btcusdt_1h")
    features = [
        _summary_feature(
            namespace,
            role="support" if index < 3 else "resistance",
            checkpoint=index + 1,
            lineage=f"lineage-{index}",
            selection=f"selection-{index}",
            distance=1.0 if index < 3 else 9.0,
        )
        for index in range(5)
    ]
    source = {"btcusdt_1h": {"checkpoint_selection": {"records": []}}}
    result = reachability._selection_evidence_summary(features, source)
    support = next(
        row for row in result["by_population_namespace_role"] if row["role"] == "support"
    )
    assert sum(row["selected_line_count"] for row in result["by_population_namespace_role"]) == 5
    assert support["selected_line_count"] == 3
    assert support["compression_retention_numerator"] == 3
    assert support["compression_retention_denominator"] == 3


def test_incumbent_retained_ids_cannot_change_compression_retention() -> None:
    namespace = ("joint_incumbent_near_v1", 1, "contender", None, "btcusdt_1h")
    features = [
        _summary_feature(namespace, lineage=f"lineage-{index}", selection=f"s-{index}")
        for index in range(5)
    ]
    record = {
        "policy_id": "joint_incumbent_near_v1",
        "budget_per_role": 1,
        "retained_incumbent_ids": ["forged"] * 99,
    }
    source = {"btcusdt_1h": {"checkpoint_selection": {"records": [record]}}}
    result = reachability._selection_evidence_summary(features, source)
    row = result["by_population_namespace_role"][0]
    assert row["compression_retention_denominator"] == 5
    assert row["compression_retention_numerator"] == 5
    assert row["compression_retention_ratio"] == 1.0


def test_structural_overlap_requires_exact_checkpoint_role_identity() -> None:
    namespace = ("joint_incumbent_near_v1", 1, "contender", None, "btcusdt_1h")
    actionable = _summary_feature(namespace, checkpoint=1, lineage="shared")
    structural_row = {
        "lineage_id": "shared",
        "state": "PERSISTED_DISTANT",
    }
    source = {
        dataset_id: {"structural_context": {"selection_records": [], "outcome_records": []}}
        for dataset_id in reachability.DATASETS
    }
    source["btcusdt_1h"]["structural_context"]["selection_records"] = [
        {
            "checkpoint_index": 2,
            "selected_rows": {"support": [structural_row], "resistance": []},
        }
    ]
    audit = reachability._structural_evidence_summary(source, [actionable])[
        "btcusdt_1h"
    ]["lineage_overlap_audit"]
    assert audit["exact_identity_intersection_count"] == 0
    source["btcusdt_1h"]["structural_context"]["selection_records"][0][
        "checkpoint_index"
    ] = 1
    audit = reachability._structural_evidence_summary(source, [actionable])[
        "btcusdt_1h"
    ]["lineage_overlap_audit"]
    assert audit["exact_identity_intersection_tuples"] == [
        ["btcusdt_1h", 1, "support", "shared"]
    ]
    source["btcusdt_1h"]["structural_context"]["selection_records"][0][
        "selected_rows"
    ] = {"support": [], "resistance": [{**structural_row}]}
    audit = reachability._structural_evidence_summary(source, [actionable])[
        "btcusdt_1h"
    ]["lineage_overlap_audit"]
    assert audit["exact_identity_intersection_count"] == 0


def test_missing_outcome_does_not_change_causal_support_membership() -> None:
    features = _comparison_feature_rows()
    source_cells = _comparison_source_cells()
    before = _build_pair_comparison(
        contender="joint_incumbent_near_v1",
        budget=1,
        control="joint_hash_order_control_v1",
        dataset_id="btcusdt_1h",
        role="support",
        feature_rows=features,
        outcome_rows=_comparison_outcomes(features),
        source_cells=source_cells,
        source_errors=[],
    )
    after = _build_pair_comparison(
        contender="joint_incumbent_near_v1",
        budget=1,
        control="joint_hash_order_control_v1",
        dataset_id="btcusdt_1h",
        role="support",
        feature_rows=features,
        outcome_rows=[],
        source_cells=source_cells,
        source_errors=[],
    )
    for field in (
        "eligible_cells",
        "paired_cells",
        "contender_only_cells",
        "control_only_cells",
        "empty_both_cells",
    ):
        assert after[field] == before[field]
    assert after["unresolved_cells"] > 0


def test_duplicate_membership_is_counted_per_cell_and_unresolved_is_terminal() -> None:
    features = _comparison_feature_rows()
    duplicated = features + [dict(features[0])]
    outcomes = _comparison_outcomes(duplicated)
    result = _build_pair_comparison(
        contender="joint_incumbent_near_v1",
        budget=1,
        control="joint_hash_order_control_v1",
        dataset_id="btcusdt_1h",
        role="support",
        feature_rows=duplicated,
        outcome_rows=outcomes,
        source_cells=_comparison_source_cells(),
        source_errors=[],
    )
    assert result["duplicate_cells"] == 1
    first_cell = next(cell for cell in result["cells"] if cell["checkpoint_index"] == 1)
    assert first_cell["terminal_cell_class"] == "duplicate"
    unresolved = _build_pair_comparison(
        contender="joint_incumbent_near_v1",
        budget=1,
        control="joint_hash_order_control_v1",
        dataset_id="btcusdt_1h",
        role="support",
        feature_rows=features,
        outcome_rows=_comparison_outcomes(features),
        source_cells=_comparison_source_cells(),
        source_errors=[],
        cell_reconciliation={
            (
                "joint_incumbent_near_v1",
                1,
                "contender",
                None,
                "btcusdt_1h",
                1,
                "support",
            ): {"missing_outcome"},
        },
    )
    first_cell = next(cell for cell in unresolved["cells"] if cell["checkpoint_index"] == 1)
    assert unresolved["unresolved_cells"] == 1
    assert first_cell["terminal_cell_class"] == "unresolved"


def test_outcome_summary_excludes_non_evaluable_rows_from_denominators() -> None:
    namespace = ("joint_incumbent_near_v1", 1, "contender", None, "btcusdt_1h")
    rows = [
        {
            **_summary_feature(namespace, selection="evaluable"),
            "horizon_hours": 96,
            "outcome": {"evaluable": True, "survival": True},
        },
        {
            **_summary_feature(namespace, selection="not-evaluable"),
            "horizon_hours": 96,
            "outcome": {"evaluable": False, "survival": True},
        },
    ]
    result = reachability._outcome_evidence_summary(rows)[0]
    assert result["evaluable_count"] == 1
    assert result["survival_denominator"] == 1
    assert result["survival_count"] == 1


def test_complete_publication_rejects_unresolved_reconciliation() -> None:
    payload = _synthetic_r4_payload()
    payload["status"] = "R4_DIAGNOSTIC_COMPLETE"
    payload["unresolved_evidence_count"] = 0
    payload["unresolved_reconciliation_count"] = 1
    with pytest.raises(ReachabilityError, match="unresolved reconciliation"):
        publish_bundle(Path("/tmp") / "r4-unresolved-reconciliation-test", payload)


def test_atomic_bundle_writer_rejects_divergent_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    payload = {"source_binding": {"id": "source-1"}, "value": 1}

    first = publish_bundle(root, payload)
    second = publish_bundle(root, payload)

    assert first == second
    assert (root / "manifest.json").is_file()
    assert not list(tmp_path.glob(".bundle.*"))
    with pytest.raises(ReachabilityError, match="non-identical"):
        publish_bundle(root, {"source_binding": {"id": "source-1"}, "value": 2})


def _synthetic_verified(token: str = "same") -> reachability.VerifiedSources:
    return reachability.VerifiedSources(
        temporal_root=Path("/synthetic/temporal"),
        raw_root=Path("/synthetic/raw"),
        raw_datasets={},
        temporal_snapshot={"token": token},
        raw_snapshot={"token": token},
    )


def test_guarded_synthetic_execution_publishes_atomically_from_missing_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _synthetic_r4_payload()
    payload["source_binding"]["source_before"] = {
        "temporal": {"token": "same"},
        "raw": {"token": "same"},
    }
    payload["source_binding"]["source_after"] = payload["source_binding"]["source_before"]
    verified = _synthetic_verified()
    output = tmp_path / "missing-parent" / "bundle"
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R4_STUDY", "1")
    monkeypatch.setattr(reachability, "verify_sources", lambda *args, **kwargs: verified)
    monkeypatch.setattr(reachability, "build_analysis", lambda _: payload)

    result = reachability.execute_reachability_study(output_root=output)

    assert result["member_count"] == 2
    assert {path.name for path in output.iterdir()} == {
        "manifest.json",
        "reachability_diagnostic.json",
        "source_binding.json",
    }
    assert not list(output.parent.glob(f".{output.name}.*"))


def test_source_mutation_between_snapshots_aborts_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _synthetic_r4_payload()
    snapshots = iter((_synthetic_verified("before"), _synthetic_verified("after")))
    output = tmp_path / "parent" / "bundle"
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R4_STUDY", "1")
    monkeypatch.setattr(reachability, "verify_sources", lambda *args, **kwargs: next(snapshots))
    monkeypatch.setattr(reachability, "build_analysis", lambda _: payload)

    with pytest.raises(ReachabilityError, match="source mutation"):
        reachability.execute_reachability_study(output_root=output)
    assert not output.exists()
    assert not output.parent.exists()


def test_output_root_refusal_precedes_source_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R4_STUDY", "1")

    def fail_if_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("source read occurred")

    monkeypatch.setattr(reachability, "verify_sources", fail_if_read)
    with pytest.raises(ReachabilityError, match="already exists"):
        reachability.execute_reachability_study(output_root=output)


def test_staging_verification_failure_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _synthetic_r4_payload()
    verified = _synthetic_verified()
    output = tmp_path / "parent" / "bundle"
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R4_STUDY", "1")
    monkeypatch.setattr(reachability, "verify_sources", lambda *args, **kwargs: verified)
    monkeypatch.setattr(reachability, "build_analysis", lambda _: payload)
    monkeypatch.setattr(
        reachability,
        "verify_reachability_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(ReachabilityError("synthetic verify failure")),
    )

    with pytest.raises(ReachabilityError, match="synthetic verify failure"):
        reachability.execute_reachability_study(output_root=output)
    assert not output.exists()
    assert not list(output.parent.glob(f".{output.name}.*"))


def test_execution_requires_guard_before_source_access(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scripts.analyze_trendline_v2_causal_structural_reachability import (
        execute_reachability_study,
    )

    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11R4_STUDY", raising=False)
    with pytest.raises(ReachabilityError, match="missing execution guard"):
        execute_reachability_study(
            temporal_root=tmp_path / "missing-temporal",
            raw_root=tmp_path / "missing-raw",
            output_root=tmp_path / "output",
        )
