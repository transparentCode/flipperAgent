from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

import scripts.analyze_trendline_v2_reachability_asymmetry_attribution as attribution


def _binding() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": attribution.R5_SOURCE_BINDING_SCHEMA,
        "r4_root": "synthetic-r4",
        "r4_diagnostic_id": "d" * 64,
        "r4_manifest_id": "m" * 64,
        "r4_inventory": "i" * 64,
        "r4_source_binding_id": "b" * 64,
        "r4_source_before": {"inventory": "before"},
        "r4_source_after": {"inventory": "after"},
    }
    payload["source_binding_id"] = attribution._identity_hash(
        attribution.R5_SOURCE_BINDING_NAMESPACE,
        payload,
    )
    return payload


def _feature(
    *,
    contender: str,
    budget: int,
    derivation: str,
    control: str | None,
    dataset: str,
    checkpoint: int,
    role: str,
    lineage: str,
    distance: float,
) -> dict[str, object]:
    namespace = [contender, budget, derivation, control, dataset]
    return {
        "population_namespace": namespace,
        "contender_policy_id": contender,
        "budget_per_role": budget,
        "derivation_type": derivation,
        "control_policy_id_or_null": control,
        "dataset_id": dataset,
        "checkpoint_index": checkpoint,
        "semantic_role_at_selection": role,
        "lineage_id": lineage,
        "fixed_geometry": {
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-02T00:00:00Z",
            "start_price": 100.0,
            "end_price": 101.0,
        },
        "initial_distance_atr": 1.0,
        "geometry_projected_distance_atr_96h": distance,
        "geometry_evaluable": True,
    }


def _cell(checkpoint: int, role: str, direction: str) -> dict[str, object]:
    return {
        "checkpoint_index": checkpoint,
        "role": role,
        "primary_stratum_class": direction,
        "terminal_cell_class": direction,
        "reconciliation_errors": [],
    }


def _synthetic_diagnostic() -> dict[str, object]:
    comparisons: list[dict[str, object]] = []
    features: list[dict[str, object]] = []
    direction_index = 0
    for comparison_index in range(51):
        cell_count = 3 if comparison_index < 15 else 2
        contender = f"contender-{comparison_index:02d}"
        control = f"control-{comparison_index:02d}"
        dataset = f"dataset-{comparison_index:02d}"
        budget = 3
        cells: list[dict[str, object]] = []
        contender_only = 0
        control_only = 0
        for cell_index in range(cell_count):
            direction = "contender_only" if direction_index < 25 else "control_only"
            direction_index += 1
            contender_only += direction == "contender_only"
            control_only += direction == "control_only"
            checkpoint = cell_index + 1
            role = "support" if cell_index % 2 == 0 else "resistance"
            lineage = f"lineage-{comparison_index:02d}-{cell_index}"
            cells.append(_cell(checkpoint, role, direction))
            contender_distance = 2.0 if direction == "contender_only" else 10.0
            control_distance = 10.0 if direction == "contender_only" else 2.0
            features.extend(
                [
                    _feature(
                        contender=contender,
                        budget=budget,
                        derivation="contender",
                        control=None,
                        dataset=dataset,
                        checkpoint=checkpoint,
                        role=role,
                        lineage=lineage,
                        distance=contender_distance,
                    ),
                    _feature(
                        contender=contender,
                        budget=budget,
                        derivation="matched_control",
                        control=control,
                        dataset=dataset,
                        checkpoint=checkpoint,
                        role=role,
                        lineage=lineage + "-control",
                        distance=control_distance,
                    ),
                ]
            )
        comparisons.append(
            {
                "population_namespace": [
                    contender,
                    budget,
                    "matched_control",
                    control,
                    dataset,
                ],
                "paired_cells": 0,
                "contender_only_cells": contender_only,
                "control_only_cells": control_only,
                "cells": cells,
            }
        )
    assert direction_index == 117
    return {
        "feature_rows": features,
        "comparisons": comparisons,
        "outcome_records": [{"survival": False, "zone_contact": True}],
    }


def _base_cell(
    *,
    budget: int = 1,
    direction: str = "contender_only",
    key_suffix: str = "x",
) -> dict[str, object]:
    contender = ("dataset", 1, "support", f"a-{key_suffix}")
    control = ("dataset", 1, "support", f"b-{key_suffix}")
    reachable = [contender] if direction == "contender_only" else [control]
    return {
        "cell_identity": ["p", budget, "c", "dataset", 1, "support", 96],
        "contender_policy_id": "p",
        "control_policy_id": "c",
        "budget_per_role": budget,
        "dataset_id": "dataset",
        "checkpoint_index": 1,
        "semantic_role_at_selection": "support",
        "horizon_hours": 96,
        "one_sided_direction": direction,
        "contender_selected": [list(contender)],
        "control_selected": [list(control)],
        "contender_reachable": [list(item) for item in reachable if item == contender],
        "control_reachable": [list(item) for item in reachable if item == control],
        "shared_selected": [],
        "contender_unique": [list(contender)],
        "control_unique": [list(control)],
        "reconciliation_errors": [],
        "resolved": True,
    }


def _higher_source(primary: str = "paired") -> dict[str, object]:
    return {
        "primary_stratum_class": primary,
        "terminal_cell_class": primary,
        "reconciliation_errors": [],
    }


def _budget_features(*, nested: bool = True) -> list[dict[str, object]]:
    rows = [
        _feature(
            contender="p",
            budget=1,
            derivation="contender",
            control=None,
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="a-x",
            distance=2.0,
        ),
        _feature(
            contender="p",
            budget=1,
            derivation="matched_control",
            control="c",
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="b-x",
            distance=10.0,
        ),
        _feature(
            contender="p",
            budget=2,
            derivation="contender",
            control=None,
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="a-x" if nested else "a-new",
            distance=2.0,
        ),
        _feature(
            contender="p",
            budget=2,
            derivation="matched_control",
            control="c",
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="b-x",
            distance=9.0,
        ),
        _feature(
            contender="p",
            budget=2,
            derivation="matched_control",
            control="c",
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="c-new",
            distance=2.0,
        ),
    ]
    return rows


def _rehashed_payload(payload: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(payload)
    result["attribution_id"] = attribution._identity_hash(
        attribution.R5_DIAGNOSTIC_NAMESPACE,
        {key: value for key, value in result.items() if key != "attribution_id"},
    )
    return result


def _rehashed_binding(binding: dict[str, object], **changes: object) -> dict[str, object]:
    result = copy.deepcopy(binding)
    result.update(changes)
    result["source_binding_id"] = attribution._identity_hash(
        attribution.R5_SOURCE_BINDING_NAMESPACE,
        {key: value for key, value in result.items() if key != "source_binding_id"},
    )
    return result


def _synthetic_source_and_verification() -> tuple[dict[str, object], dict[str, object]]:
    source_binding = _binding()
    source = {
        "diagnostic": _synthetic_diagnostic(),
        "source_binding": source_binding,
        "manifest": {},
    }
    verification = {
        "diagnostic_id": "d" * 64,
        "manifest_id": "m" * 64,
        "output_inventory_sha256": "i" * 64,
        "member_count": 2,
    }
    return source, verification


def _diagnostic_with_higher_budget_inconsistency() -> dict[str, object]:
    diagnostic = _synthetic_diagnostic()
    first_comparison = diagnostic["comparisons"][0]
    first_comparison["population_namespace"][1] = 1
    for row in diagnostic["feature_rows"]:
        if row["dataset_id"] == "dataset-00":
            row["budget_per_role"] = 1
            row["population_namespace"][1] = 1

    diagnostic["comparisons"].append(
        {
            "population_namespace": [
                "contender-00",
                2,
                "matched_control",
                "control-00",
                "dataset-00",
            ],
            "paired_cells": 1,
            "contender_only_cells": 0,
            "control_only_cells": 0,
            "cells": [_cell(1, "support", "paired")],
        }
    )
    diagnostic["feature_rows"].extend(
        [
            _feature(
                contender="contender-00",
                budget=2,
                derivation="contender",
                control=None,
                dataset="dataset-00",
                checkpoint=1,
                role="support",
                lineage="higher",
                distance=2.0,
            ),
            _feature(
                contender="contender-00",
                budget=2,
                derivation="contender",
                control=None,
                dataset="dataset-00",
                checkpoint=1,
                role="support",
                lineage="higher",
                distance=3.0,
            ),
            _feature(
                contender="contender-00",
                budget=2,
                derivation="matched_control",
                control="control-00",
                dataset="dataset-00",
                checkpoint=1,
                role="support",
                lineage="higher-control",
                distance=10.0,
            ),
        ]
    )
    return diagnostic


def test_exact_population_extraction_reconciles_51_117_25_92() -> None:
    extracted, _, errors = attribution._comparison_records(_synthetic_diagnostic())

    assert errors == []
    assert len(extracted) == 117
    assert sum(item["primary_stratum_class"] == "contender_only" for item in extracted) == 25
    assert sum(item["primary_stratum_class"] == "control_only" for item in extracted) == 92


def test_primary_terminal_mismatch_is_rejected() -> None:
    diagnostic = _synthetic_diagnostic()
    diagnostic["comparisons"][0]["cells"][0]["terminal_cell_class"] = "paired"

    _, _, errors = attribution._comparison_records(diagnostic)

    assert any("invalid extracted cell" in error for error in errors)


def test_reachable_direction_xor_is_required() -> None:
    rows = _budget_features()
    extracted = {
        "key": ("p", 1, "c", "dataset", 1, "support", 96),
        "primary_stratum_class": "contender_only",
        "reconciliation_errors": [],
    }
    rows[1]["geometry_projected_distance_atr_96h"] = 2.0
    cell = attribution._derive_cell(extracted, rows, {})

    assert cell["attribution_class"] == "UNATTRIBUTED_ONE_SIDED_CELL"
    assert "reachable-direction XOR failure" in cell["reconciliation_errors"]
    assert cell["resolved"] is False


def test_full_and_partial_substitution_are_mutually_exclusive() -> None:
    rows = _budget_features()
    full = attribution._derive_cell(
        {
            "key": ("p", 1, "c", "dataset", 1, "support", 96),
            "primary_stratum_class": "contender_only",
            "reconciliation_errors": [],
        },
        rows,
        {},
    )
    rows.append(
        _feature(
            contender="p",
            budget=1,
            derivation="matched_control",
            control="c",
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="shared",
            distance=10.0,
        )
    )
    rows.append(
        _feature(
            contender="p",
            budget=1,
            derivation="contender",
            control=None,
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="shared",
            distance=2.0,
        )
    )
    partial = attribution._derive_cell(
        {
            "key": ("p", 1, "c", "dataset", 1, "support", 96),
            "primary_stratum_class": "contender_only",
            "reconciliation_errors": [],
        },
        rows,
        {},
    )

    assert full["attribution_class"] == "FULL_LINEAGE_SUBSTITUTION"
    assert partial["attribution_class"] == "PARTIAL_LINEAGE_SUBSTITUTION"


def test_global_feature_inconsistency_is_one_record() -> None:
    first = _feature(
        contender="p",
        budget=1,
        derivation="contender",
        control=None,
        dataset="dataset",
        checkpoint=1,
        role="support",
        lineage="same",
        distance=2.0,
    )
    second = copy.deepcopy(first)
    second["budget_per_role"] = 2
    second["population_namespace"] = ["p", 2, "contender", None, "dataset"]
    second["geometry_projected_distance_atr_96h"] = 3.0
    key = ("p", 1, "c", "dataset", 1, "support", 96)
    records, errors = attribution._global_feature_consistency(
        [first, second], {key: {}}
    )

    assert errors == []
    assert list(records) == [("dataset", 1, "support", "same")]
    assert len(records[('dataset', 1, 'support', 'same')]["occurrences"]) == 2


def test_unrelated_feature_inconsistency_is_outside_r5_scope() -> None:
    diagnostic = _synthetic_diagnostic()
    first = _feature(
        contender="unrelated",
        budget=1,
        derivation="contender",
        control=None,
        dataset="unrelated",
        checkpoint=1,
        role="support",
        lineage="outside",
        distance=2.0,
    )
    second = copy.deepcopy(first)
    second["geometry_projected_distance_atr_96h"] = 3.0
    diagnostic["feature_rows"].extend([first, second])

    payload = attribution.build_attribution(diagnostic, _binding())

    assert payload["status"] == "R5_ATTRIBUTION_COMPLETE"
    assert payload["global_inconsistencies"] == []


def test_higher_budget_inconsistency_references_relevant_source_cell() -> None:
    payload = attribution.build_attribution(
        _diagnostic_with_higher_budget_inconsistency(),
        _binding(),
    )

    assert payload["status"] == "R5_ATTRIBUTION_INCOMPLETE"
    records = payload["global_inconsistencies"]
    assert len(records) == 1
    higher_key = ["contender-00", 2, "control-00", "dataset-00", 1, "support", 96]
    assert higher_key in records[0]["affected_cell_identities"]
    assert records[0]["global_inconsistency_id"] in payload["cells"][0]["global_inconsistency_ids"]


def test_typed_checkpoint_ordering_puts_2_before_10() -> None:
    keys = [
        ("p", 3, "c", "dataset", 10, "support", 96),
        ("p", 3, "c", "dataset", 2, "support", 96),
    ]

    assert sorted(keys, key=attribution._sort_identity)[0][4] == 2


def test_distance_and_overlap_formulas_are_exact() -> None:
    rows = _budget_features()
    rows.append(
        _feature(
            contender="p",
            budget=1,
            derivation="contender",
            control=None,
            dataset="dataset",
            checkpoint=1,
            role="support",
            lineage="shared",
            distance=2.0,
        )
    )
    extracted = {
        "key": ("p", 1, "c", "dataset", 1, "support", 96),
        "primary_stratum_class": "contender_only",
        "reconciliation_errors": [],
    }
    cell = attribution._derive_cell(extracted, rows, {})

    assert cell["reachable_side_projected_distances"] == [2.0, 2.0]
    assert cell["missing_side_projected_distances"] == [10.0]
    assert cell["minimum_excess_above_8_atr"] == 2.0
    assert cell["reachable_side_headroom_below_8_atr"] == 6.0
    assert cell["selected_lineage_overlap_numerator"] == 0
    assert cell["selected_lineage_overlap_denominator"] == 3


def test_first_paired_higher_budget_can_be_strict_rescue() -> None:
    cell = _base_cell()
    key = tuple(cell["cell_identity"])
    higher_key = ("p", 2, "c", "dataset", 1, "support", 96)
    attribution._cross_budget(
        cell,
        {higher_key: _higher_source()},
        _budget_features(),
        {},
    )

    assert cell["cross_budget_class"] == "STRICT_BUDGET_RESCUE"
    assert cell["rescue_budget"] == 2
    assert cell["contender_nested"] is True
    assert cell["control_nested"] is True
    assert cell["missing_side_reachable_gain"] == 1
    assert key[1] == 1


def test_budget_two_pair_is_selected_before_budget_three_pair() -> None:
    cell = _base_cell()
    budget_two = ("p", 2, "c", "dataset", 1, "support", 96)
    budget_three = ("p", 3, "c", "dataset", 1, "support", 96)
    source = {
        budget_two: _higher_source(),
        budget_three: _higher_source(),
    }

    attribution._cross_budget(cell, source, _budget_features(), {})

    assert cell["rescue_budget"] == 2
    assert cell["cross_budget_source_cell_identities"] == [list(budget_two)]


def test_budget_one_rescue_uses_budget_three_when_budget_two_is_unpaired() -> None:
    cell = _base_cell()
    budget_two = ("p", 2, "c", "dataset", 1, "support", 96)
    budget_three = ("p", 3, "c", "dataset", 1, "support", 96)
    features = _budget_features()
    features.extend(
        [
            _feature(
                contender="p",
                budget=3,
                derivation="contender",
                control=None,
                dataset="dataset",
                checkpoint=1,
                role="support",
                lineage="a-x",
                distance=2.0,
            ),
            _feature(
                contender="p",
                budget=3,
                derivation="matched_control",
                control="c",
                dataset="dataset",
                checkpoint=1,
                role="support",
                lineage="b-x",
                distance=10.0,
            ),
            _feature(
                contender="p",
                budget=3,
                derivation="matched_control",
                control="c",
                dataset="dataset",
                checkpoint=1,
                role="support",
                lineage="c-new",
                distance=2.0,
            ),
        ]
    )
    source = {
        budget_two: _higher_source("empty_both"),
        budget_three: _higher_source(),
    }

    attribution._cross_budget(cell, source, features, {})

    assert cell["rescue_budget"] == 3
    assert cell["cross_budget_source_cell_identities"] == [
        list(budget_two),
        list(budget_three),
    ]


def test_first_paired_higher_budget_non_nested_is_not_rescue() -> None:
    cell = _base_cell()
    higher_key = ("p", 2, "c", "dataset", 1, "support", 96)
    attribution._cross_budget(
        cell,
        {higher_key: _higher_source()},
        _budget_features(nested=False),
        {},
    )

    assert cell["cross_budget_class"] == "NON_NESTED_HIGHER_BUDGET_PAIRING"
    assert cell["contender_nested"] is False


def test_budget_three_direction_change_is_persistent_not_rescue() -> None:
    cell = _base_cell()
    key = ("p", 3, "c", "dataset", 1, "support", 96)
    source = {key: {"primary_stratum_class": "control_only"}}
    attribution._cross_budget(cell, source, [], {})

    assert cell["cross_budget_class"] == "PERSISTENT_THROUGH_BUDGET_3"
    assert cell["budget3_direction"] == "control_only"
    assert cell["direction_preserved"] is False


def test_empty_budget_three_trajectory_is_incomplete() -> None:
    cell = _base_cell()
    key = ("p", 3, "c", "dataset", 1, "support", 96)
    source = {key: {"primary_stratum_class": "empty_both"}}
    attribution._cross_budget(cell, source, [], {})

    assert cell["cross_budget_class"] is None
    assert cell["resolved"] is False
    assert cell["cross_budget_unresolved_reason"] == "budget3_empty_both"


def test_outcome_field_mutation_does_not_change_attribution() -> None:
    diagnostic = _synthetic_diagnostic()
    binding = _binding()
    before = attribution.build_attribution(diagnostic, binding)
    mutated = copy.deepcopy(diagnostic)
    mutated["outcome_records"] = [{"survival": True, "zone_contact": False}]
    mutated["candidate_outcomes"] = [{"breach": True, "reaction": True}]

    assert attribution.build_attribution(mutated, binding) == before
    assert before["forbidden_outcome_fields_used"] == []


def test_synthetic_build_is_complete_and_classes_are_single_valued() -> None:
    payload = attribution.build_attribution(_synthetic_diagnostic(), _binding())

    assert payload["status"] == "R5_ATTRIBUTION_COMPLETE"
    assert len(payload["cells"]) == 117
    assert all(cell["attribution_class"] in attribution.ATTRIBUTION_CLASSES for cell in payload["cells"])
    assert all(cell["cross_budget_class"] in attribution.CROSS_BUDGET_CLASSES for cell in payload["cells"])
    assert all(cell["resolved"] for cell in payload["cells"])


def test_synthetic_bundle_has_exact_three_files_and_verifies(tmp_path: Path) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    root = tmp_path / "bundle"
    manifest = attribution.publish_bundle(root, payload, binding)

    result = attribution.verify_attribution_bundle(
        root,
        source_backed=False,
        expected_evidence={"attribution": payload, "source_binding": binding},
    )

    assert manifest["member_count"] == 2
    assert sorted(path.name for path in root.iterdir()) == [
        "manifest.json",
        "reachability_asymmetry_attribution.json",
        "source_binding.json",
    ]
    assert result["status"] == "R5_ATTRIBUTION_COMPLETE"


def test_complete_payload_with_unresolved_evidence_is_rejected_before_publish(
    tmp_path: Path,
) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    payload["unresolved_evidence_count"] = 1
    payload = _rehashed_payload(payload)
    root = tmp_path / "missing-parent" / "bundle"

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="unresolved"):
        attribution.publish_bundle(root, payload, binding)

    assert not root.exists()
    assert not list(root.parent.glob(f".{root.name}.*"))


def test_complete_payload_with_unresolved_cell_is_rejected_before_publish(
    tmp_path: Path,
) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    payload["cells"][0]["resolved"] = False
    payload["cells"][0]["reconciliation_errors"] = ["tampered"]
    payload = _rehashed_payload(payload)
    root = tmp_path / "bundle"

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="unresolved cell"):
        attribution.publish_bundle(root, payload, binding)

    assert not root.exists()


def test_complete_unattributed_class_is_rejected_before_publish(tmp_path: Path) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    payload["cells"][0]["attribution_class"] = "UNATTRIBUTED_ONE_SIDED_CELL"
    payload["summary_rows"] = attribution._summary_rows(payload["cells"])
    payload = _rehashed_payload(payload)

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="attribution class"):
        attribution.publish_bundle(tmp_path / "bundle", payload, binding)


def test_complete_shared_inconsistency_class_is_rejected_before_publish(
    tmp_path: Path,
) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    payload["cells"][0]["attribution_class"] = (
        "SHARED_LINEAGE_REACHABILITY_INCONSISTENCY"
    )
    payload["summary_rows"] = attribution._summary_rows(payload["cells"])
    payload = _rehashed_payload(payload)

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="attribution class"):
        attribution.publish_bundle(tmp_path / "bundle", payload, binding)


def test_complete_lingering_global_inconsistency_reference_is_rejected(
    tmp_path: Path,
) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    payload["cells"][0]["global_inconsistency_ids"] = ["x" * 64]
    payload["cells"][0]["global_inconsistency_identities"] = [
        ["dataset", 1, "support", "lineage"]
    ]
    payload["cells"][0]["shared_lineage_projected_distance_equality"] = False
    payload = _rehashed_payload(payload)

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="inconsistency"):
        attribution.publish_bundle(tmp_path / "bundle", payload, binding)


def test_source_backed_rebound_bundle_is_rejected_after_rebinding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, verification = _synthetic_source_and_verification()
    r4_root = tmp_path / "verified-r4"
    binding = attribution._source_binding_payload(source, verification, r4_root)
    payload = attribution.build_attribution(source["diagnostic"], binding)
    root = tmp_path / "bundle"
    attribution.publish_bundle(root, payload, binding)
    forged_binding = _rehashed_binding(binding, r4_root=str(tmp_path / "other-r4"))
    forged_payload = copy.deepcopy(payload)
    forged_payload["source_binding"] = forged_binding
    forged_payload = _rehashed_payload(forged_payload)
    forged_root = tmp_path / "forged"
    attribution.publish_bundle(forged_root, forged_payload, forged_binding)
    monkeypatch.setattr(attribution, "_r4_source", lambda root: (source, verification))

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="artifact mismatch"):
        attribution.verify_attribution_bundle(
            forged_root,
            source_backed=True,
            r4_root=r4_root,
        )


def test_alternate_verified_r4_root_is_bound_into_expected_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, verification = _synthetic_source_and_verification()
    alternate_root = tmp_path / "alternate-r4"
    binding = attribution._source_binding_payload(source, verification, alternate_root)
    payload = attribution.build_attribution(source["diagnostic"], binding)
    root = tmp_path / "bundle"
    attribution.publish_bundle(root, payload, binding)
    monkeypatch.setattr(attribution, "_r4_source", lambda r4_root: (source, verification))

    result = attribution.verify_attribution_bundle(
        root,
        source_backed=True,
        r4_root=alternate_root,
    )

    assert result["status"] == "R5_ATTRIBUTION_COMPLETE"


def test_identical_overwrite_passes_and_divergent_overwrite_fails(tmp_path: Path) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    root = tmp_path / "bundle"
    first = attribution.publish_bundle(root, payload, binding)
    second = attribution.publish_bundle(root, payload, binding)

    assert second == first
    divergent_binding = _rehashed_binding(binding, r4_root="different-r4")
    divergent_payload = copy.deepcopy(payload)
    divergent_payload["source_binding"] = divergent_binding
    divergent_payload = _rehashed_payload(divergent_payload)
    with pytest.raises(attribution.ReachabilityAsymmetryError, match="non-identical"):
        attribution.publish_bundle(root, divergent_payload, divergent_binding)


def test_staging_verification_failure_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, verification = _synthetic_source_and_verification()
    output_root = tmp_path / "output" / "bundle"
    monkeypatch.setenv(attribution.EXECUTION_GUARD, "1")
    monkeypatch.setattr(attribution, "_r4_source", lambda root: (source, verification))

    def reject_staging(*args: object, **kwargs: object) -> None:
        raise attribution.ReachabilityAsymmetryError("staging verification failed")

    monkeypatch.setattr(attribution, "verify_attribution_bundle", reject_staging)
    with pytest.raises(attribution.ReachabilityAsymmetryError, match="staging"):
        attribution.execute_attribution_study(output_root=output_root)

    assert not output_root.exists()
    assert list(output_root.parent.iterdir()) == []


def test_guarded_synthetic_execution_publishes_atomically_from_missing_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, verification = _synthetic_source_and_verification()
    output_root = tmp_path / "missing" / "output"
    calls: list[Path] = []
    monkeypatch.setenv(attribution.EXECUTION_GUARD, "1")
    monkeypatch.setattr(attribution, "_r4_source", lambda root: (source, verification))

    def verify_staged(root: Path, **kwargs: object) -> dict[str, object]:
        calls.append(root)
        assert root.is_dir()
        return {"status": "R5_ATTRIBUTION_COMPLETE"}

    monkeypatch.setattr(attribution, "verify_attribution_bundle", verify_staged)
    result = attribution.execute_attribution_study(output_root=output_root)

    assert result["status"] == "R5_ATTRIBUTION_COMPLETE"
    assert output_root.is_dir()
    assert calls[0] != output_root
    assert calls[1] == output_root
    assert not list(output_root.parent.glob(f".{output_root.name}.*"))


def test_source_mutation_between_prefix_reads_aborts_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_before, verification = _synthetic_source_and_verification()
    source_after = copy.deepcopy(source_before)
    source_after["source_binding"]["source_before"] = {"inventory": "changed"}
    output_root = tmp_path / "output" / "bundle"
    responses = iter(((source_before, verification), (source_after, verification)))
    monkeypatch.setenv(attribution.EXECUTION_GUARD, "1")
    monkeypatch.setattr(attribution, "_r4_source", lambda root: next(responses))

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="source mutation"):
        attribution.execute_attribution_study(output_root=output_root)

    assert not output_root.exists()
    assert not output_root.parent.exists()


def test_synthetic_verification_requires_explicit_expected_evidence(tmp_path: Path) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    root = tmp_path / "bundle"
    attribution.publish_bundle(root, payload, binding)

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="synthetic"):
        attribution.verify_attribution_bundle(root, source_backed=False)


def test_rebound_synthetic_bundle_is_rejected(tmp_path: Path) -> None:
    binding = _binding()
    payload = attribution.build_attribution(_synthetic_diagnostic(), binding)
    root = tmp_path / "bundle"
    attribution.publish_bundle(root, payload, binding)
    forged = copy.deepcopy(payload)
    forged["cells"][0]["attribution_class"] = "PARTIAL_LINEAGE_SUBSTITUTION"
    forged["summary_rows"] = attribution._summary_rows(forged["cells"])
    forged["attribution_id"] = attribution._identity_hash(
        attribution.R5_DIAGNOSTIC_NAMESPACE,
        {key: value for key, value in forged.items() if key != "attribution_id"},
    )
    forged_root = tmp_path / "forged-bundle"
    attribution.publish_bundle(forged_root, forged, binding)

    with pytest.raises(attribution.ReachabilityAsymmetryError, match="artifact mismatch"):
        attribution.verify_attribution_bundle(
            forged_root,
            source_backed=False,
            expected_evidence={"attribution": payload, "source_binding": binding},
        )


def test_output_root_refusal_precedes_r4_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    monkeypatch.setenv(attribution.EXECUTION_GUARD, "1")

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("R4 verifier called")

    monkeypatch.setattr(attribution, "verify_reachability_bundle", fail_if_called)
    with pytest.raises(attribution.ReachabilityAsymmetryError, match="already exists"):
        attribution.execute_attribution_study(r4_root=tmp_path / "r4", output_root=root)


def test_only_r4_verifier_is_imported() -> None:
    source = Path(attribution.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    r4_imports = [
        node
        for node in imports
        if node.module == "scripts.analyze_trendline_v2_causal_structural_reachability"
    ]

    assert len(r4_imports) == 1
    assert [alias.name for alias in r4_imports[0].names] == [
        "verify_reachability_bundle"
    ]
