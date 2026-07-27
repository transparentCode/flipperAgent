from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import analyze_trendline_v2_quality_signal_feasibility as study


def _synthetic_dataset(role: str = "support", *, n: int = 80) -> tuple[study.Dataset, dict[str, object]]:
    timestamps = tuple(index * 3_600 * 1_000_000_000 for index in range(n))
    if role == "support":
        opens = tuple(101.0 for _ in range(n))
        closes = tuple(101.0 for _ in range(n))
        highs = tuple(104.0 for _ in range(n))
        lows = tuple(100.0 for _ in range(n))
    else:
        opens = tuple(99.0 for _ in range(n))
        closes = tuple(99.0 for _ in range(n))
        highs = tuple(100.0 for _ in range(n))
        lows = tuple(95.0 for _ in range(n))
    candidate = {
        "candidate_id": "candidate-1",
        "candidate_structure_id": "structure-1",
        "role": role,
        "first_anchor_id": "anchor-1",
        "second_anchor_id": "anchor-2",
        "source_positions": (5, 10),
        "confirmation_positions": (6, 11),
        "availability_position": 16,
        "start_price": 100.0,
        "end_price": 100.0,
        "record": {
            "anchor_span_bars": 5,
            "anchor_span_seconds": 18_000.0,
            "absolute_slope_bps_per_day": 0.0,
            "anchor_price_change_bps": 0.0,
            "minimum_anchor_prominence_bps": 10.0,
            "mean_anchor_prominence_bps": 12.0,
            "minimum_body_clearance_bps": 20.0,
            "median_body_clearance_bps": 20.0,
            "same_role_extrema_skip_count": 99,
            "first_anchor_prominence_bps": 10.0,
            "second_anchor_prominence_bps": 14.0,
            "slope_bps_per_day": 0.0,
        },
    }
    dataset = study.Dataset(
        dataset_id="synthetic_1h",
        asset="TEST",
        timeframe="1h",
        interval_seconds=3_600,
        timestamps=timestamps,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=tuple(1.0 for _ in range(n)),
        atr=study._atr14(highs, lows, closes),
        candidates=(candidate,),
        records={"candidate-1": candidate["record"]},
        family_membership={},
        source_hashes={},
        input_identity="0" * 64,
    )
    return dataset, candidate


def test_atr_is_causal() -> None:
    dataset, _ = _synthetic_dataset()
    future_highs = list(dataset.highs)
    future_highs[60] = 1_000.0
    changed = study._atr14(future_highs, dataset.lows, dataset.closes)
    assert changed[:60] == dataset.atr[:60]


def test_future_rows_do_not_change_checkpoint_features() -> None:
    dataset, candidate = _synthetic_dataset()
    row, _ = study._feature_row(dataset, candidate, 0)
    highs = list(dataset.highs)
    lows = list(dataset.lows)
    highs[30] = 10_000.0
    lows[30] = 1.0
    changed = replace(dataset, highs=tuple(highs), lows=tuple(lows), atr=study._atr14(highs, lows, dataset.closes))
    changed_row, _ = study._feature_row(changed, candidate, 0)
    assert changed_row["features"] == row["features"]


def test_later_feature_data_cannot_change_earlier_checkpoint() -> None:
    dataset, candidate = _synthetic_dataset()
    earlier, _ = study._feature_row(dataset, candidate, 0)
    closes = list(dataset.closes)
    closes[20] = 102.0
    changed = replace(dataset, closes=tuple(closes), atr=study._atr14(dataset.highs, dataset.lows, closes))
    changed_earlier, _ = study._feature_row(changed, candidate, 0)
    assert changed_earlier["features"] == earlier["features"]


def test_future_labels_start_strictly_after_checkpoint() -> None:
    dataset, candidate = _synthetic_dataset()
    row, _ = study._feature_row(dataset, candidate, 0)
    outcome = study._future_reaction(dataset, candidate, row, 6)
    assert outcome["future_start_position"] == row["checkpoint_position"] + 1
    assert outcome["future_start_position"] > row["checkpoint_position"]


def test_consecutive_contacts_form_one_episode() -> None:
    dataset, candidate = _synthetic_dataset()
    episodes = study._episode_ranges(dataset, candidate, [20, 21, 22])
    assert episodes == [(20, 21, 22)]


def test_episode_separation_requires_bars_and_atr_move() -> None:
    dataset, candidate = _synthetic_dataset()
    closes = list(dataset.closes)
    closes[21] = 101.1
    closes[22] = 101.1
    closes[23] = 101.1
    highs = list(dataset.highs)
    lows = list(dataset.lows)
    for position in (21, 22):
        highs[position] = closes[position]
        lows[position] = closes[position]
    moved = list(closes)
    moved[22] = 104.0
    moved[23] = 104.0
    moved_dataset = replace(
        dataset,
        opens=tuple(moved),
        closes=tuple(moved),
        highs=tuple(moved),
        lows=tuple(moved),
        atr=study._atr14(moved, moved, moved),
    )
    assert study._episode_ranges(dataset, candidate, [20, 23]) == [(20, 23)]
    assert study._episode_ranges(moved_dataset, candidate, [20, 23]) == [(20,), (23,)]


def test_support_and_resistance_excursion_directions() -> None:
    support, support_candidate = _synthetic_dataset("support")
    resistance, resistance_candidate = _synthetic_dataset("resistance")
    support_summary = study._reaction_summary(support, support_candidate, 20, 24)
    resistance_summary = study._reaction_summary(resistance, resistance_candidate, 20, 24)
    assert support_summary["maximum_favourable_excursion_atr"] > 0
    assert support_summary["maximum_adverse_penetration_atr"] == 0
    assert resistance_summary["maximum_favourable_excursion_atr"] > 0
    assert resistance_summary["maximum_adverse_penetration_atr"] == 0


def test_intermediate_count_is_not_contact_count() -> None:
    dataset, candidate = _synthetic_dataset()
    row, episodes = study._feature_row(dataset, candidate, 0)
    assert candidate["record"]["same_role_extrema_skip_count"] == 99
    assert row["features"]["independent_contact_episode_count"] == 1
    assert len(episodes) == 1


def test_relevance_fields_are_separate_family() -> None:
    assert set(study.FEATURE_FAMILIES["relevance_only_v1"]) == {
        "current_projected_distance_atr",
        "correct_side_of_current_price",
        "availability_age_bars",
        "last_contact_age_bars",
    }
    assert "current_projected_distance_atr" not in study.FEATURE_FAMILIES["combined_quality_v1"]


def test_holdout_loader_is_rejected() -> None:
    with pytest.raises(study.StudyError, match="outside Q1 validation allowlist"):
        study._load_dataset("suiusdt_1h")


def test_temporal_audit_is_closed_before_quality_lock() -> None:
    assert study.TEMPORAL_ROOT != study.SOURCE_ROOT
    assert "NOT_OPENED_BEFORE_VALIDATION_LOCK" in study._derive_evidence.__code__.co_consts


def test_source_manifest_and_selected_hashes_are_pinned() -> None:
    binding = study._load_source_manifest()
    assert binding["source_decision_id"] == study.SOURCE_DECISION_ID
    assert binding["source_manifest_id"] == study.SOURCE_MANIFEST_ID
    assert len(binding["loaded_members"]) == 12


def test_validation_groups_are_structure_bound() -> None:
    dataset, candidate = _synthetic_dataset()
    row, _ = study._feature_row(dataset, candidate, 0)
    outcome = study._future_reaction(dataset, candidate, row, 24)
    grouped, labels = study._group_rows([row, {**row, "checkpoint_position": 18}], {row["feature_row_id"]: outcome})
    assert len(grouped) == 1
    assert len(labels) == 1


def test_atomic_staging_persists_lock_before_analysis(tmp_path: Path) -> None:
    lock = {"schema_version": "lock", "validation_lock_id": "id"}
    staging = study._prepare_staging(tmp_path / "output", lock)
    try:
        assert (staging / "validation_lock.json").read_bytes() == study._canonical_bytes(lock)
    finally:
        (staging / "validation_lock.json").unlink()
        staging.rmdir()


def test_failed_execute_removes_staging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE12Q1_STUDY", "1")
    original = study._derive_evidence

    def fail(*args: object, **kwargs: object) -> dict[str, object]:
        raise study.StudyError("synthetic failure")

    monkeypatch.setattr(study, "_derive_evidence", fail)
    with pytest.raises(study.StudyError, match="synthetic failure"):
        study.execute_study(output_root=tmp_path / "output")
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".output.*"))
    monkeypatch.setattr(study, "_derive_evidence", original)


def test_rendered_bundle_rejects_rebound_member(tmp_path: Path) -> None:
    expected = {"manifest.json": study._canonical_bytes({"manifest_id": "expected"})}
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.json").write_bytes(study._canonical_bytes({"manifest_id": "forged"}))
    with pytest.raises(study.StudyError):
        study._validate_rendered(root, expected)


def test_network_and_provider_execution_are_frozen_zero() -> None:
    contract = study._contract()
    assert contract["network_request_count"] == 0
    assert contract["provider_execution_count"] == 0


def test_contract_contains_fixed_horizons_and_checkpoint_ages() -> None:
    contract = study._contract()
    assert contract["checkpoint_ages"] == [0, 6, 12, 24]
    assert contract["horizons"] == [6, 12, 24]


def test_deterministic_ids_and_json_reject_noncanonical(tmp_path: Path) -> None:
    payload = {"b": 2, "a": 1}
    path = tmp_path / "payload.json"
    path.write_bytes(study._canonical_bytes(payload))
    assert study._load_json(path) == payload
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(study.StudyError, match="non-canonical"):
        study._load_json(path)


def test_source_snapshot_does_not_include_sui_members() -> None:
    snapshot = study._source_snapshot()
    assert snapshot
    assert all("sui" not in key for key in snapshot)


def _analysis_row(
    *,
    feature_row_id: str,
    age: int,
    position: int,
    structure: str = "structure-1",
    second_anchor: str = "anchor-2",
) -> dict[str, object]:
    return {
        "feature_row_id": feature_row_id,
        "dataset_id": "synthetic_1h",
        "role": "support",
        "candidate_structure_id": structure,
        "second_anchor_id": second_anchor,
        "candidate_id": feature_row_id,
        "checkpoint_age_bars": age,
        "checkpoint_position": position,
        "features": {},
        "control_flags": {"current_focus_selected": False},
    }


def test_analysis_representative_is_label_independent() -> None:
    early = _analysis_row(feature_row_id="z-row", age=0, position=20)
    late = _analysis_row(feature_row_id="a-row", age=24, position=30)
    selected = study._select_analysis_rows([early, late])
    assert [row["feature_row_id"] for row in selected] == ["a-row"]


def test_unreachable_later_row_cannot_select_earlier_reachable_row() -> None:
    early = _analysis_row(feature_row_id="early", age=0, position=20)
    late = _analysis_row(feature_row_id="late", age=24, position=30)
    grouped, labels = study._group_rows(
        [early, late],
        {"early": {"reachability": True, "clean_reaction": True}, "late": {"reachability": False, "clean_reaction": False}},
    )
    assert grouped == []
    assert labels == []


def test_duplicate_checkpoint_rows_do_not_overweight_analysis_group() -> None:
    rows = [
        _analysis_row(feature_row_id="a", age=0, position=10),
        _analysis_row(feature_row_id="b", age=6, position=16),
        _analysis_row(feature_row_id="c", age=12, position=22),
    ]
    selected = study._select_analysis_rows(rows)
    assert len(selected) == 1
    assert selected[0]["feature_row_id"] == "c"


def test_bootstrap_is_deterministic_and_samples_analysis_groups() -> None:
    labels = [True, False, True, False]
    scores = [0.9, 0.8, 0.7, 0.1]
    first = study._bootstrap_samples(labels, scores, 123)
    second = study._bootstrap_samples(labels, scores, 123)
    assert first == second
    assert first[1] + first[2] == study.BOOTSTRAP_REPLICATES


def test_invalid_bootstrap_replicates_are_accounted() -> None:
    samples, valid, invalid = study._bootstrap_samples([True, True], [0.9, 0.8], 123)
    assert samples == [None] * study.BOOTSTRAP_REPLICATES
    assert valid == 0
    assert invalid == study.BOOTSTRAP_REPLICATES


def test_spearman_uses_two_sided_statistical_p_value() -> None:
    rho, p_value = study._spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert rho == pytest.approx(1.0)
    assert p_value == pytest.approx(0.0)


def test_benjamini_hochberg_reverse_cumulative_step() -> None:
    adjusted = study._benjamini_hochberg([0.04, 0.001, 0.03, None])
    assert adjusted[3] is None
    assert adjusted[1] <= adjusted[2] <= adjusted[0]
    assert adjusted[0] == pytest.approx(0.04)


def _focus_candidate(candidate_id: str, role: str, second_anchor: str, confirmation: int, span: int) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "role": role,
        "second_anchor_id": second_anchor,
        "confirmation_positions": (confirmation - 1, confirmation),
        "record": {"anchor_span_bars": span},
    }


def test_focus_control_matches_committed_defaults_and_caps_roles() -> None:
    candidates = [
        _focus_candidate(f"support-{index}", "support", f"s-{index}", 150 + index, 25)
        for index in range(13)
    ] + [
        _focus_candidate(f"resistance-{index}", "resistance", f"r-{index}", 150 + index, 25)
        for index in range(13)
    ]
    candidates.extend([
        _focus_candidate("old", "support", "old-anchor", 99, 40),
        _focus_candidate("short", "support", "short-anchor", 150, 24),
    ])
    selected = study._focus_selected_ids(candidates, 200)
    assert len([candidate for candidate in selected if candidate.startswith("support-")]) == 12
    assert len([candidate for candidate in selected if candidate.startswith("resistance-")]) == 12
    assert "old" not in selected
    assert "short" not in selected


def test_relevance_families_cannot_be_intrinsic_quality_finalists() -> None:
    assert set(study.INTRINSIC_QUALITY_FAMILIES) == {
        "interaction_reaction_v1",
        "combined_quality_v1",
    }
    assert set(study.DIAGNOSTIC_FAMILIES).isdisjoint(study.INTRINSIC_QUALITY_FAMILIES)


def test_r1_bundle_is_distinct_and_r2_is_target() -> None:
    assert study.R1_OUTPUT_ROOT != study.OUTPUT_ROOT
    assert study.OUTPUT_ROOT.name.endswith("_r2")
