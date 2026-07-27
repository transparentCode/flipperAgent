from __future__ import annotations

import json
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import analyze_trendline_v2_actionable_interaction_shortlist as study


def _dataset(role: str = "support", *, rows: int = 180) -> tuple[SimpleNamespace, dict[str, object]]:
    timestamps = tuple(index * 3_600 * 1_000_000_000 for index in range(rows))
    if role == "support":
        opens = tuple(101.0 for _ in range(rows))
        closes = tuple(101.0 for _ in range(rows))
        highs = tuple(103.0 for _ in range(rows))
        lows = tuple(100.0 for _ in range(rows))
        start_price = end_price = 100.0
    else:
        opens = tuple(104.0 for _ in range(rows))
        closes = tuple(104.0 for _ in range(rows))
        highs = tuple(105.0 for _ in range(rows))
        lows = tuple(102.0 for _ in range(rows))
        start_price = end_price = 105.0
    record = {
        "anchor_span_bars": 20,
        "anchor_span_seconds": 72_000.0,
    }
    candidate = {
        "candidate_id": f"candidate-{role}",
        "candidate_structure_id": f"structure-{role}",
        "role": role,
        "first_anchor_id": "anchor-first",
        "second_anchor_id": "anchor-second",
        "source_positions": (20, 40),
        "confirmation_positions": (21, 41),
        "availability_position": 50,
        "start_price": start_price,
        "end_price": end_price,
        "record": record,
    }
    dataset = SimpleNamespace(
        dataset_id=f"synthetic_{role}",
        asset="TEST",
        timeframe="1h",
        interval_seconds=3_600,
        timestamps=timestamps,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        volumes=tuple(1.0 for _ in range(rows)),
        atr=study.source_loader._atr14(highs, lows, closes),
    )
    return dataset, candidate


def _checkpoint(position: int = 120, index: int = 1) -> dict[str, object]:
    return {
        "checkpoint_index": index,
        "checkpoint": f"1970-01-01T{position // 3600:02d}:00:00Z",
        "checkpoint_position": position,
    }


def _replace_dataset(dataset: SimpleNamespace, **changes: object) -> SimpleNamespace:
    return SimpleNamespace(**{**vars(dataset), **changes})


def _feature(
    *,
    structure: str,
    candidate_id: str | None = None,
    role: str = "support",
    checkpoint_index: int = 1,
    state: str = "NEAR",
    actionable: bool = True,
    anchor: str | None = None,
    span: int = 30,
) -> dict[str, object]:
    candidate_id = candidate_id or f"candidate-{structure}"
    anchor = anchor or f"anchor-{structure}"
    return {
        "feature_row_id": f"feature-{structure}-{checkpoint_index}",
        "dataset_id": "synthetic_support",
        "asset": "TEST",
        "timeframe": "1h",
        "checkpoint_index": checkpoint_index,
        "checkpoint": "1970-01-01T00:00:00Z",
        "checkpoint_position": 120,
        "role": role,
        "candidate_id": candidate_id,
        "candidate_structure_id": structure,
        "first_anchor_id": "first",
        "second_anchor_id": anchor,
        "anchor_source_positions": [20, 40],
        "confirmation_positions": [21, 41],
        "anchor_span_bars": span,
        "record_anchor_span_bars": span,
        "policy_id": study.POLICIES[0]["policy_id"],
        "state": state,
        "actionable": actionable,
        "features": {
            "current_range_distance_atr": 0.25,
            "projected_contact_hours": 12.0,
            "approach_consistency": 0.8,
            "net_closure_atr": 1.0,
        },
    }


def _outcome_row(
    *,
    checkpoint_index: int,
    source_kind: str,
    zone: float,
    hit: bool | None = None,
    state: str = "NEAR",
    checkpoint_position: int = 120,
) -> dict[str, object]:
    hit = bool(zone) if hit is None else hit
    outcomes = {
        str(horizon): {
            "horizon_hours": horizon,
            "horizon_bar_count": horizon,
            "future_start_position": checkpoint_position,
            "future_end_exclusive_position": checkpoint_position + horizon,
            "evaluable": True,
            "current_or_future_zone_contact": bool(zone),
            "future_exact_contact": bool(zone),
            "zone_contact_and_survival": bool(zone),
            "sustained_breach": False,
            "post_contact_reaction": bool(zone),
            "first_zone_contact_offset_bars": 1 if zone else None,
            "median_time_to_contact": 1 if zone else None,
            "cell_hit": hit,
        }
        for horizon in (24, 48, 96)
    }
    return {
        "policy_id": study.POLICIES[0]["policy_id"],
        "budget": 5,
        "dataset_id": "synthetic_support",
        "checkpoint_index": checkpoint_index,
        "checkpoint_position": checkpoint_position,
        "role": "support",
        "state": state,
        "source_kind": source_kind,
        "candidate_structure_id": f"structure-{checkpoint_index}",
        "outcomes": outcomes,
    }


def _stability_schedules() -> dict[str, list[dict[str, int]]]:
    return {
        dataset_id: [{"checkpoint_index": index} for index in (1, 2, 3)]
        for dataset_id in study.DATASETS
    }


def _stability_key(checkpoint_index: int, role: str = "support") -> tuple[object, ...]:
    return (study.POLICIES[0]["policy_id"], "btcusdt_1h", checkpoint_index, role, 5)


def _audit_fixture() -> dict[str, object]:
    policy_id = study.POLICIES[0]["policy_id"]
    feature = _feature(structure="a")
    feature.update(policy_id=policy_id, dataset_id="btcusdt_1h")
    selected = {
        _stability_key(1): {
            "contender": {"a"},
            "nearest_distance_control": {"a"},
            "hash_order_control": {"a"},
        }
    }
    membership = [{
        "policy_id": policy_id,
        "budget": 5,
        "dataset_id": "btcusdt_1h",
        "checkpoint_index": 1,
        "role": "support",
        "candidate_structure_id": "a",
        "selection_status": "SELECTED",
    }]
    outcomes = []
    for source_kind in ("contender", "nearest_distance_control", "hash_order_control"):
        row = _outcome_row(checkpoint_index=1, source_kind=source_kind, zone=1)
        row.update(
            outcome_id=f"outcome-{source_kind}",
            policy_id=policy_id,
            dataset_id="btcusdt_1h",
            role="support",
            candidate_structure_id="a",
        )
        outcomes.append(row)
    return {
        "active_by_dataset": {"btcusdt_1h": [{"candidate_structure_id": "a"}]},
        "expected_active_structure_rows": 1,
        "expected_feature_rows": 1,
        "features": [feature],
        "selected": selected,
        "membership": membership,
        "outcomes": outcomes,
        "schedules": _stability_schedules(),
    }


def test_json_duplicate_keys_rejected() -> None:
    raw = b'{"a":1,"a":2}\n'
    with pytest.raises(study.StudyError, match="duplicate JSON key"):
        study._load_json_bytes(raw)


def test_json_nonfinite_constants_rejected() -> None:
    with pytest.raises(study.StudyError, match="non-finite"):
        study._load_json_bytes(b'{"a":NaN}\n')


def test_json_requires_canonical_bytes() -> None:
    with pytest.raises(study.StudyError, match="non-canonical"):
        study._load_json_bytes(b'{ "a": 1 }\n')


def test_policy_lookback_uses_owner_timeframe_bars() -> None:
    dataset, _ = _dataset()
    assert study._policy_bars(dataset, study.POLICIES[0]) == 24
    assert study._policy_bars(dataset, study.POLICIES[1]) == 48


def test_policy_rejects_nonrepresentable_timeframe() -> None:
    dataset, _ = _dataset()
    dataset.interval_seconds = 7_000
    with pytest.raises(study.StudyError, match="representable"):
        study._policy_bars(dataset, study.POLICIES[0])


def test_support_and_resistance_distance_roles() -> None:
    support, support_candidate = _dataset("support")
    resistance, resistance_candidate = _dataset("resistance")
    assert study._range_distance(support, support_candidate, 100) >= 0
    assert study._range_distance(resistance, resistance_candidate, 100) >= 0
    assert study._close_distance(support, support_candidate, 100) > 0
    assert study._close_distance(resistance, resistance_candidate, 100) > 0


def test_future_rows_do_not_change_causal_features() -> None:
    dataset, candidate = _dataset()
    checkpoint = _checkpoint(120)
    original = study._feature_row(dataset, checkpoint, candidate, study.POLICIES[0])
    highs = list(dataset.highs)
    lows = list(dataset.lows)
    highs[150] = 10_000.0
    lows[150] = 1.0
    changed = _replace_dataset(dataset, highs=tuple(highs), lows=tuple(lows), atr=study.source_loader._atr14(highs, lows, dataset.closes))
    assert study._feature_row(changed, checkpoint, candidate, study.POLICIES[0])["features"] == original["features"]


def test_historical_rows_change_causal_features() -> None:
    dataset, candidate = _dataset()
    checkpoint = _checkpoint(120)
    original = study._feature_row(dataset, checkpoint, candidate, study.POLICIES[0])
    lows = list(dataset.lows)
    lows[100] = 90.0
    changed = _replace_dataset(dataset, lows=tuple(lows), atr=study.source_loader._atr14(dataset.highs, lows, dataset.closes))
    assert study._feature_row(changed, checkpoint, candidate, study.POLICIES[0])["features"] != original["features"]


def test_wilder_atr_future_mutation_does_not_change_prefix() -> None:
    dataset, _ = _dataset()
    highs = list(dataset.highs)
    highs[150] = 10_000.0
    changed = study.source_loader._atr14(highs, dataset.lows, dataset.closes)
    assert changed[:150] == dataset.atr[:150]


def test_state_precedence_contact_near_approach_dormant() -> None:
    policy = study.POLICIES[0]
    assert study._classify_state(contacting=True, current_distance=9, median_delta=1, consistency=0, net_closure=0, projected_hours=None, policy=policy) == "CONTACTING"
    assert study._classify_state(contacting=False, current_distance=0.5, median_delta=1, consistency=0, net_closure=0, projected_hours=None, policy=policy) == "NEAR"
    assert study._classify_state(contacting=False, current_distance=3, median_delta=-1, consistency=0.8, net_closure=1, projected_hours=12, policy=policy) == "APPROACHING"
    assert study._classify_state(contacting=False, current_distance=3, median_delta=1, consistency=0.8, net_closure=1, projected_hours=12, policy=policy) == "DORMANT"


def test_feature_marks_only_first_three_states_actionable() -> None:
    dataset, candidate = _dataset()
    row = study._feature_row(dataset, _checkpoint(), candidate, study.POLICIES[0])
    assert row["actionable"] is (row["state"] != "DORMANT")


def test_anchor_suppression_is_one_per_second_anchor() -> None:
    rows = [_feature(structure="a", anchor="shared"), _feature(structure="b", anchor="shared"), _feature(structure="c", anchor="other")]
    chosen = study._one_per_anchor(rows, study._selection_key)
    assert {row["second_anchor_id"] for row in chosen} == {"shared", "other"}


def test_selection_is_order_invariant() -> None:
    rows = [_feature(structure="a", anchor="a"), _feature(structure="b", anchor="b", state="APPROACHING"), _feature(structure="c", anchor="c", actionable=False, state="DORMANT")]
    left = study._selection_records(rows, {})
    right = study._selection_records(list(reversed(rows)), {})
    assert left == right


def test_selection_membership_records_all_rejection_reasons() -> None:
    rows = [_feature(structure="a", anchor="a"), _feature(structure="b", anchor="b", actionable=False, state="DORMANT"), _feature(structure="c", anchor="a")]
    membership, _, _, _ = study._selection_records(rows, {})
    assert {row["selection_status"] for row in membership} >= {"SELECTED", "NOT_ACTIONABLE", "DUPLICATE_SECOND_ANCHOR"}


def test_budget_caps_contender_population() -> None:
    rows = [_feature(structure=str(index), anchor=str(index)) for index in range(20)]
    _, selected, _, _ = study._selection_records(rows, {})
    assert len(selected[(study.POLICIES[0]["policy_id"], "synthetic_support", 1, "support", 5)]["contender"]) == 5
    assert len(selected[(study.POLICIES[0]["policy_id"], "synthetic_support", 1, "support", 10)]["contender"]) == 10


def test_nearest_and_hash_controls_match_contender_count() -> None:
    rows = [_feature(structure=str(index), anchor=str(index)) for index in range(6)]
    _, selected, _, _ = study._selection_records(rows, {})
    for value in selected.values():
        assert len(value["contender"]) == len(value["nearest_distance_control"]) == len(value["hash_order_control"])


def test_focus_control_is_capped_and_descriptive_all_valid_exists() -> None:
    rows = [_feature(structure=str(index), anchor=str(index), span=30) for index in range(20)]
    _, _, controls, _ = study._selection_records(rows, {})
    assert any(row["source_kind"] == "current_focus" for row in controls)
    assert any(row["source_kind"] == "all_valid" for row in controls)
    assert max(sum(row["source_kind"] == "current_focus" for row in controls), 0) >= 1


def test_focus_order_matches_viewer_and_prefers_later_confirmations() -> None:
    rows = []
    for index in range(13):
        row = _feature(structure=str(index), anchor=str(index), span=30)
        row["confirmation_positions"] = [21, 120 + index]
        rows.append(row)
    assert study._focus_ids(rows, 200) == tuple(str(index) for index in range(12, 0, -1))


def test_focus_age_uses_final_completed_candle_boundary() -> None:
    included = _feature(structure="age-100", anchor="age-100", span=25)
    included["confirmation_positions"] = [21, 100]
    excluded = _feature(structure="age-101", anchor="age-101", span=25)
    excluded["confirmation_positions"] = [21, 99]

    assert study._focus_ids([included, excluded], 200) == ("age-100",)


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="set TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE=1 for frozen population preflight",
)
def test_frozen_population_focus_matches_committed_viewer_semantics() -> None:
    _, _, schedule_payload, active_payload = study._verify_h1_bundle()
    datasets = study._load_phase9_datasets()
    active_by_dataset, schedules = study._validate_active_population(
        active_payload,
        schedule_payload,
        datasets,
    )
    mismatches = []
    cell_count = 0
    for dataset_id in study.DATASETS:
        for checkpoint in schedules[dataset_id]:
            checkpoint_index = int(checkpoint["checkpoint_index"])
            last_candle_position = int(checkpoint["checkpoint_position"]) - 1
            for role in study.ROLES:
                rows = [
                    row
                    for row in active_by_dataset[dataset_id]
                    if int(row["checkpoint_index"]) == checkpoint_index
                    and row["role"] == role
                ]
                viewer_candidate_ids = set(
                    study.source_loader._focus_selected_ids(
                        [row["candidate"] for row in rows],
                        last_candle_position,
                    )
                )
                viewer_structures = {
                    row["candidate_structure_id"]
                    for row in rows
                    if row["candidate_id"] in viewer_candidate_ids
                }
                research_structures = set(
                    study._focus_ids(rows, last_candle_position)
                )
                if viewer_structures != research_structures:
                    mismatches.append(
                        (dataset_id, checkpoint_index, role, viewer_structures, research_structures)
                    )
                cell_count += 1
    assert cell_count == 216
    assert mismatches == []


def test_identical_adjacent_shortlists_have_jaccard_one() -> None:
    selected = {
        _stability_key(1): {"contender": {"a", "b"}},
        _stability_key(2): {"contender": {"a", "b"}},
        _stability_key(3): {"contender": {"a", "b"}},
    }
    rows, summaries = study._shortlist_stability(selected, _stability_schedules())
    lane_rows = [row for row in rows if row["dataset_id"] == "btcusdt_1h" and row["role"] == "support" and row["policy_id"] == study.POLICIES[0]["policy_id"] and row["budget"] == 5]
    summary = next(row for row in summaries if row["dataset_id"] == "btcusdt_1h" and row["role"] == "support" and row["policy_id"] == study.POLICIES[0]["policy_id"] and row["budget"] == 5)
    assert [row["adjacent_jaccard"] for row in lane_rows] == [1.0, 1.0]
    assert summary["full_replacement_count"] == 0


def test_disjoint_nonempty_shortlists_are_full_replacements() -> None:
    selected = {
        _stability_key(1): {"contender": {"a"}},
        _stability_key(2): {"contender": {"b"}},
    }
    _, summaries = study._shortlist_stability(selected, _stability_schedules())
    summary = next(row for row in summaries if row["dataset_id"] == "btcusdt_1h" and row["role"] == "support" and row["policy_id"] == study.POLICIES[0]["policy_id"] and row["budget"] == 5)
    assert summary["full_replacement_count"] == 1
    assert summary["full_replacement_rate"] == 0.5


def test_empty_and_one_empty_stability_transitions_are_separate() -> None:
    selected = {
        _stability_key(1): {"contender": set()},
        _stability_key(2): {"contender": set()},
        _stability_key(3): {"contender": {"c"}},
    }
    rows, summaries = study._shortlist_stability(selected, _stability_schedules())
    lane_rows = [row for row in rows if row["dataset_id"] == "btcusdt_1h" and row["role"] == "support" and row["policy_id"] == study.POLICIES[0]["policy_id"] and row["budget"] == 5]
    summary = next(row for row in summaries if row["dataset_id"] == "btcusdt_1h" and row["role"] == "support" and row["policy_id"] == study.POLICIES[0]["policy_id"] and row["budget"] == 5)
    assert lane_rows[0]["both_empty"] is True
    assert lane_rows[0]["full_replacement"] is False
    assert lane_rows[1]["one_empty"] is True
    assert lane_rows[1]["full_replacement"] is False
    assert summary["one_empty_transition_count"] == 1


def test_stability_is_scoped_by_policy_budget_dataset_and_role() -> None:
    _, summaries = study._shortlist_stability({}, _stability_schedules())
    assert len(summaries) == len(study.POLICIES) * len(study.BUDGETS) * len(study.DATASETS) * len(study.ROLES)
    assert len({(row["policy_id"], row["budget"], row["dataset_id"], row["role"]) for row in summaries}) == len(summaries)


def test_future_exact_contact_uses_future_bars_only() -> None:
    dataset, candidate = _dataset()
    checkpoint = _checkpoint(120)
    lows = list(dataset.lows)
    highs = list(dataset.highs)
    lows[120] = 100.0
    highs[120] = 100.0
    changed = _replace_dataset(dataset, lows=tuple(lows), highs=tuple(highs), atr=study.source_loader._atr14(highs, lows, dataset.closes))
    result = study._future_outcome(changed, candidate, checkpoint, "DORMANT", "policy", 5, "contender")
    assert result["outcomes"]["24"]["first_exact_contact_offset_bars"] == 0


def test_reaction_cannot_use_contact_bar() -> None:
    dataset, candidate = _dataset()
    checkpoint = _checkpoint(120)
    lows = list(dataset.lows)
    highs = list(dataset.highs)
    lows[120] = 100.0
    highs[120] = 100.0
    highs[121] = 102.0
    changed = _replace_dataset(dataset, lows=tuple(lows), highs=tuple(highs), atr=study.source_loader._atr14(highs, lows, dataset.closes))
    result = study._future_outcome(changed, candidate, checkpoint, "DORMANT", "policy", 5, "contender")
    assert result["outcomes"]["24"]["post_contact_reaction"] is True


def test_sustained_breach_requires_two_closes_and_records_second_bar() -> None:
    dataset, candidate = _dataset()
    checkpoint = _checkpoint(120)
    closes = list(dataset.closes)
    opens = list(dataset.opens)
    highs = list(dataset.highs)
    lows = list(dataset.lows)
    closes[120] = closes[121] = 98.0
    opens[120] = opens[121] = 98.0
    highs[120] = highs[121] = 99.0
    lows[120] = lows[121] = 97.0
    changed = _replace_dataset(dataset, opens=tuple(opens), closes=tuple(closes), highs=tuple(highs), lows=tuple(lows), atr=study.source_loader._atr14(highs, lows, closes))
    result = study._future_outcome(changed, candidate, checkpoint, "DORMANT", "policy", 5, "contender")
    assert result["outcomes"]["24"]["first_sustained_breach_offset_bars"] == 1


def test_incomplete_horizon_is_not_evaluable() -> None:
    dataset, candidate = _dataset(rows=130)
    result = study._future_outcome(dataset, candidate, _checkpoint(120), "DORMANT", "policy", 5, "contender")
    assert result["outcomes"]["24"]["evaluable"] is False


def test_future_outcome_persists_all_states_and_binds_state_identity() -> None:
    dataset, candidate = _dataset()
    checkpoint = _checkpoint(120)
    results = [
        study._future_outcome(
            dataset,
            candidate,
            checkpoint,
            state,
            "policy",
            5,
            "contender",
        )
        for state in study.ALL_STATES
    ]
    assert [result["state"] for result in results] == list(study.ALL_STATES)
    assert len({result["outcome_id"] for result in results}) == len(study.ALL_STATES)


def test_resistance_breach_direction_is_opposite_support() -> None:
    dataset, candidate = _dataset("resistance")
    checkpoint = _checkpoint(120)
    closes = list(dataset.closes)
    opens = list(dataset.opens)
    highs = list(dataset.highs)
    lows = list(dataset.lows)
    closes[120] = closes[121] = 107.0
    opens[120] = opens[121] = 107.0
    highs[120] = highs[121] = 108.0
    lows[120] = lows[121] = 106.0
    changed = _replace_dataset(dataset, opens=tuple(opens), closes=tuple(closes), highs=tuple(highs), lows=tuple(lows), atr=study.source_loader._atr14(highs, lows, closes))
    result = study._future_outcome(changed, candidate, checkpoint, "DORMANT", "policy", 5, "contender")
    assert result["outcomes"]["24"]["sustained_breach"] is True


def test_cell_metric_excludes_ineligible_rows() -> None:
    rows = [_outcome_row(checkpoint_index=1, source_kind="contender", zone=1)]
    rows[0]["outcomes"]["24"]["evaluable"] = False
    assert study._cell_metric(rows, 24)["evaluable_count"] == 0


def test_cell_hit_rate_is_binary_and_distinct_from_line_precision() -> None:
    rows = [
        _outcome_row(checkpoint_index=1, source_kind="contender", zone=1),
        _outcome_row(checkpoint_index=1, source_kind="contender", zone=0),
    ]
    metric = study._cell_metric(rows, 48)
    assert metric["zone_contact_precision"] == 0.5
    assert metric["cell_hit"] is True
    assert metric["cell_hit_rate"] == 1.0


def test_cell_hit_rate_zero_when_no_selected_line_hits() -> None:
    rows = [
        _outcome_row(checkpoint_index=1, source_kind="contender", zone=0),
        _outcome_row(checkpoint_index=1, source_kind="contender", zone=0),
    ]
    metric = study._cell_metric(rows, 48)
    assert metric["zone_contact_precision"] == 0.0
    assert metric["cell_hit"] is False
    assert metric["cell_hit_rate"] == 0.0


def test_paired_comparison_is_cell_weighted_and_period_split() -> None:
    pairs = [
        {"checkpoint_index": 1, "contender": {metric: 1.0 for metric in study.COMPARISON_METRICS}, "control": {metric: 0.0 for metric in study.COMPARISON_METRICS}},
        {"checkpoint_index": 14, "contender": {metric: 0.0 for metric in study.COMPARISON_METRICS}, "control": {metric: 1.0 for metric in study.COMPARISON_METRICS}},
    ]
    result = study._paired_comparison(pairs, identity={"policy_id": "p", "budget": 5, "dataset_id": "d", "role": "support", "control_kind": "nearest_distance_control", "horizon_hours": 48})
    assert result["periods"]["pooled"]["metrics"]["zone_contact_precision"]["point_delta"] == 0.0
    assert result["periods"]["early"]["metrics"]["zone_contact_precision"]["point_delta"] == 1.0
    assert result["periods"]["late"]["metrics"]["zone_contact_precision"]["point_delta"] == -1.0


def test_paired_cell_hit_delta_uses_binary_cell_outcomes() -> None:
    pairs = [
        {"checkpoint_index": 1, "contender": {metric: 0.0 for metric in study.COMPARISON_METRICS}, "control": {metric: 0.0 for metric in study.COMPARISON_METRICS}},
        {"checkpoint_index": 2, "contender": {metric: 0.0 for metric in study.COMPARISON_METRICS}, "control": {metric: 0.0 for metric in study.COMPARISON_METRICS}},
    ]
    pairs[0]["contender"]["cell_hit_rate"] = 1.0
    pairs[0]["control"]["cell_hit_rate"] = 0.0
    pairs[1]["contender"]["cell_hit_rate"] = 0.0
    pairs[1]["control"]["cell_hit_rate"] = 1.0
    result = study._paired_comparison(
        pairs,
        identity={"policy_id": "p", "budget": 5, "dataset_id": "d", "role": "support", "control_kind": "nearest_distance_control", "horizon_hours": 48},
    )
    assert result["metrics"]["cell_hit_rate"]["point_delta"] == 0.0


def test_state_stratified_utility_keeps_actionable_states_separate() -> None:
    policy_id = study.POLICIES[0]["policy_id"]
    rows = []
    for state, structure, zone in (("CONTACTING", "contact", 1), ("NEAR", "near", 1), ("APPROACHING", "approach", 0)):
        row = _outcome_row(checkpoint_index=1, source_kind="contender", zone=zone, state=state)
        row.update(policy_id=policy_id, budget=5, dataset_id="btcusdt_1h", role="support", candidate_structure_id=structure)
        rows.append(row)
    schedules = {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS}
    utility = study._state_stratified_utility(rows, schedules)
    relevant = [row for row in utility if row["policy_id"] == policy_id and row["budget"] == 5 and row["dataset_id"] == "btcusdt_1h" and row["role"] == "support" and row["horizon_hours"] == 48]
    assert {row["state"] for row in relevant} == set(study.ACTIONABLE_STATES)
    assert {row["state"]: row["selected_observation_count"] for row in relevant} == {"CONTACTING": 1, "NEAR": 1, "APPROACHING": 1}


def test_state_utility_absent_state_uses_null_metrics() -> None:
    policy_id = study.POLICIES[0]["policy_id"]
    row = _outcome_row(checkpoint_index=1, source_kind="contender", zone=1, state="NEAR")
    row.update(policy_id=policy_id, budget=5, dataset_id="btcusdt_1h", role="support", candidate_structure_id="near")
    utility = study._state_stratified_utility(
        [row],
        {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS},
    )
    contacting = next(item for item in utility if item["policy_id"] == policy_id and item["budget"] == 5 and item["dataset_id"] == "btcusdt_1h" and item["role"] == "support" and item["state"] == "CONTACTING" and item["horizon_hours"] == 48)
    assert contacting["selected_observation_count"] == 0
    assert contacting["evaluable_observation_count"] == 0
    assert contacting["current_or_future_zone_contact_precision"] is None
    assert contacting["cell_hit_rate"] is None


def test_state_utility_cell_hit_rate_is_binary() -> None:
    policy_id = study.POLICIES[0]["policy_id"]
    rows = []
    for structure, zone in (("near-a", 1), ("near-b", 0)):
        row = _outcome_row(checkpoint_index=1, source_kind="contender", zone=zone, state="NEAR")
        row.update(policy_id=policy_id, budget=5, dataset_id="btcusdt_1h", role="support", candidate_structure_id=structure)
        rows.append(row)
    utility = study._state_stratified_utility(
        rows,
        {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS},
    )
    near = next(item for item in utility if item["policy_id"] == policy_id and item["budget"] == 5 and item["dataset_id"] == "btcusdt_1h" and item["role"] == "support" and item["state"] == "NEAR" and item["horizon_hours"] == 48)
    assert near["current_or_future_zone_contact_precision"] == 0.5
    assert near["cell_hit_rate"] == 1.0


def test_state_utility_rejects_missing_outcome_state() -> None:
    row = _outcome_row(checkpoint_index=1, source_kind="contender", zone=1)
    row.pop("state")
    with pytest.raises(study.StudyError, match="outcome state missing or invalid"):
        study._state_stratified_utility(
            [row],
            {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS},
        )


def test_state_utility_rejects_invalid_outcome_state() -> None:
    row = _outcome_row(checkpoint_index=1, source_kind="contender", zone=1)
    row["state"] = "UNKNOWN"
    with pytest.raises(study.StudyError, match="outcome state missing or invalid"):
        study._state_stratified_utility(
            [row],
            {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS},
        )


def test_state_utility_accepts_dormant_control_without_actionable_utility() -> None:
    row = _outcome_row(
        checkpoint_index=1,
        source_kind="nearest_distance_control",
        zone=0,
        state="DORMANT",
    )
    utility = study._state_stratified_utility(
        [row],
        {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS},
    )
    assert all(item["selected_observation_count"] == 0 for item in utility)


def test_real_future_outcomes_flow_through_selection_utility_integrity_and_decision() -> None:
    dataset, candidate = _dataset()
    dataset = _replace_dataset(dataset, dataset_id="btcusdt_1h")
    checkpoint = _checkpoint(120)
    policy = study.POLICIES[0]
    feature = study._feature_row(dataset, checkpoint, candidate, policy)
    feature["candidate"] = candidate
    features = [feature]
    membership, selected, controls, _ = study._selection_records(features, {})

    outcomes = []
    for (policy_id, dataset_id, checkpoint_index, role, budget), source_sets in selected.items():
        for source_kind, structure_ids in source_sets.items():
            for structure_id in sorted(structure_ids):
                assert structure_id == candidate["candidate_structure_id"]
                outcomes.append(
                    study._future_outcome(
                        dataset,
                        candidate,
                        checkpoint,
                        feature["state"],
                        policy_id,
                        budget,
                        source_kind,
                    )
                )

    policy_rows, _, comparison_payload = study._selection_metrics(
        selected,
        membership,
        outcomes,
        features,
        controls,
    )
    utility = study._state_stratified_utility(
        outcomes,
        {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS},
    )
    audit = study._integrity_audit(
        active_by_dataset={"btcusdt_1h": [{"candidate_structure_id": candidate["candidate_structure_id"]}]},
        expected_active_structure_rows=1,
        expected_feature_rows=1,
        features=features,
        selected=selected,
        membership=membership,
        outcomes=outcomes,
        schedules={dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS},
    )
    policy_rows_by_lane = {
        (row["policy_id"], int(row["budget"])): row
        for row in policy_rows
    }
    decision_rows = [
        policy_rows_by_lane.get(
            (policy["policy_id"], budget),
            {
                "policy_id": policy["policy_id"],
                "budget": budget,
                "nonempty_cell_coverage": 0.0,
                "median_selected_count": 0,
                "actionable_eligible_median": 0,
                "actionable_eligible_p90": 0,
                "selected_count_total": 0,
                "state_distribution": {},
            },
        )
        for policy in study.POLICIES
        for budget in study.BUDGETS
    ]
    decision = study._make_decision(decision_rows, comparison_payload, membership, audit)

    assert any(row["selected_observation_count"] > 0 for row in utility)
    assert audit["integrity"] is True
    assert decision["status"] != "ACTIONABILITY_EVIDENCE_INCOMPLETE"


def test_integrity_audit_passes_valid_fixture() -> None:
    audit = study._integrity_audit(**_audit_fixture())
    assert audit["integrity"] is True
    assert audit["unresolved_evidence_count"] == 0
    assert audit["reconciliation_count"] == 0


def test_missing_outcome_state_fails_integrity_and_is_counted() -> None:
    fixture = _audit_fixture()
    fixture["outcomes"][0].pop("state")
    audit = study._integrity_audit(**fixture)
    assert audit["missing_outcome_state_count"] == 1
    assert audit["invalid_outcome_state_count"] == 0
    assert audit["outcome_state_feature_mismatch_count"] == 0
    assert audit["integrity_failure_count"] == 1
    assert audit["unresolved_evidence_count"] == 1
    assert audit["reconciliation_count"] == 1
    assert audit["integrity"] is False


def test_invalid_outcome_state_fails_integrity_and_is_counted() -> None:
    fixture = _audit_fixture()
    fixture["outcomes"][0]["state"] = "UNKNOWN"
    audit = study._integrity_audit(**fixture)
    assert audit["missing_outcome_state_count"] == 0
    assert audit["invalid_outcome_state_count"] == 1
    assert audit["outcome_state_feature_mismatch_count"] == 0
    assert audit["integrity_failure_count"] == 1
    assert audit["unresolved_evidence_count"] == 1
    assert audit["reconciliation_count"] == 1
    assert audit["integrity"] is False


def test_outcome_state_feature_mismatch_fails_integrity_and_is_counted() -> None:
    fixture = _audit_fixture()
    fixture["outcomes"][0]["state"] = "CONTACTING"
    audit = study._integrity_audit(**fixture)
    assert audit["missing_outcome_state_count"] == 0
    assert audit["invalid_outcome_state_count"] == 0
    assert audit["outcome_state_feature_mismatch_count"] == 1
    assert audit["integrity_failure_count"] == 1
    assert audit["unresolved_evidence_count"] == 1
    assert audit["reconciliation_count"] == 1
    assert audit["integrity"] is False


def test_duplicate_selected_membership_fails_integrity() -> None:
    fixture = _audit_fixture()
    fixture["membership"].append(deepcopy(fixture["membership"][0]))
    audit = study._integrity_audit(**fixture)
    assert audit["duplicate_selected_memberships"] == 1
    assert audit["integrity"] is False


def test_matched_control_count_failure_fails_integrity() -> None:
    fixture = _audit_fixture()
    fixture["selected"][_stability_key(1)]["nearest_distance_control"] = set()
    audit = study._integrity_audit(**fixture)
    assert audit["matched_control_count_failures"] == 1
    assert audit["integrity"] is False


def test_duplicate_outcome_identity_fails_integrity() -> None:
    fixture = _audit_fixture()
    fixture["outcomes"][1]["outcome_id"] = fixture["outcomes"][0]["outcome_id"]
    audit = study._integrity_audit(**fixture)
    assert audit["duplicate_outcome_ids"] == 1
    assert audit["integrity"] is False


def test_missing_selected_outcome_fails_integrity() -> None:
    fixture = _audit_fixture()
    fixture["outcomes"].pop()
    audit = study._integrity_audit(**fixture)
    assert audit["missing_selected_outcomes"] == 1
    assert audit["integrity"] is False


def test_future_feature_history_fails_integrity() -> None:
    fixture = _audit_fixture()
    fixture["features"][0]["features"]["historical_positions"] = [120]
    audit = study._integrity_audit(**fixture)
    assert audit["feature_history_future_leakage_rows"] == 1
    assert audit["integrity"] is False


def test_future_outcome_boundary_before_checkpoint_fails_integrity() -> None:
    fixture = _audit_fixture()
    fixture["outcomes"][0]["outcomes"]["24"]["future_start_position"] = 119
    audit = study._integrity_audit(**fixture)
    assert audit["outcome_future_boundary_violations"] == 1
    assert audit["integrity"] is False


def test_bootstrap_is_deterministic() -> None:
    cells = [{"contender": {"value": 1.0}, "control": {"value": 0.0}}, {"contender": {"value": 2.0}, "control": {"value": 0.0}}]
    payload = {"policy_id": "p", "budget": 5}
    assert study._paired_bootstrap(cells, "value", payload) == study._paired_bootstrap(cells, "value", payload)


def test_bootstrap_empty_population_fails_sufficiency() -> None:
    result = study._paired_bootstrap([], "value", {"policy_id": "p"})
    assert result["valid_replicates"] == 0
    assert result["invalid_replicates"] == study.BOOTSTRAP_REPLICATES


def test_early_and_late_checkpoint_sets_are_disjoint() -> None:
    early = set(range(1, 14))
    late = set(range(14, 28))
    assert early.isdisjoint(late)
    assert len(early) == 13
    assert len(late) == 14


def test_holdout_allowlist_is_closed() -> None:
    assert set(study.HOLDOUT_DATASETS).isdisjoint(study.DATASETS)
    with pytest.raises(study.source_loader.StudyError, match="allowlist"):
        study._load_phase9_datasets.__globals__["source_loader"]._load_dataset("suiusdt_1h", study.SOURCE_ROOT)


def test_contract_pins_zero_execution_boundary() -> None:
    contract = study._contract({dataset: [{"checkpoint_index": 1}] * 27 for dataset in study.DATASETS})
    assert contract["execution"] == {"provider_execution_count": 0, "network_request_count": 0, "legacy_execution_count": 0, "holdout_access": False, "temporal_access": False}


def test_prepare_staging_creates_missing_parent(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "output"
    staging = study._prepare_staging(root)
    assert root.parent.is_dir()
    assert staging.parent == root.parent
    study._cleanup(staging)


def test_prepare_staging_refuses_existing_output(tmp_path: Path) -> None:
    root = tmp_path / "output"
    root.mkdir()
    with pytest.raises(study.StudyError, match="already exists"):
        study._prepare_staging(root)


def test_execute_staging_failure_makes_zero_derive_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = []
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY", "1")
    monkeypatch.setattr(study, "_prepare_staging", lambda _: (_ for _ in ()).throw(study.StudyError("staging failed")))
    monkeypatch.setattr(study, "_derive_evidence", lambda *_: calls.append(True))
    with pytest.raises(study.StudyError, match="staging failed"):
        study.execute_study(tmp_path / "output")
    assert calls == []


def test_execute_failure_cleans_staging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY", "1")
    output = tmp_path / "output"
    def fail(_callback: object) -> dict[str, object]:
        raise study.StudyError("derivation failed")
    monkeypatch.setattr(study, "_derive_evidence", fail)
    with pytest.raises(study.StudyError, match="derivation failed"):
        study.execute_study(output)
    assert not output.exists()
    assert list(output.parent.glob(f".{output.name}.*")) == []


def test_successful_execution_publishes_from_missing_parent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY", "1")
    output = tmp_path / "missing" / "output"
    rendered = {name: {} for name in study.ARTIFACT_NAMES[:-2]}
    rendered["validation_lock.json"] = {"status": "COMPLETE"}
    rendered["decision.json"] = {"status": "NO_ACTIONABLE_INTERACTION_SHORTLIST_FINALIST"}
    manifest = {
        "study_status": rendered["decision.json"]["status"],
        "decision_id": "decision",
        "output_inventory_sha256": "inventory",
        "manifest_id": "manifest",
    }
    rendered["output_inventory.json"] = {}
    rendered["manifest.json"] = manifest
    monkeypatch.setattr(study, "_derive_evidence", lambda _callback: rendered)
    monkeypatch.setattr(
        study,
        "_render_bytes",
        lambda _rendered: {
            name: study._canonical_bytes(
                {
                    "study_status": manifest["study_status"],
                    "decision_id": "decision",
                    "output_inventory_sha256": "inventory",
                    "manifest_id": "manifest",
                }
                if name == "manifest.json"
                else {}
            )
            for name in study.ARTIFACT_NAMES
        },
    )
    monkeypatch.setattr(study, "_validate_bundle", lambda *_: None)
    result = study.execute_study(output)
    assert output.is_dir()
    assert result["status"] == manifest["study_status"]


def test_execute_requires_explicit_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE14A1_STUDY", "1")
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY", raising=False)
    with pytest.raises(study.StudyError, match="TRENDLINE_V2_ALLOW_PHASE14A1R1_STUDY"):
        study.execute_study(tmp_path / "output")


def test_r1_identity_retires_original_schema_and_output_root() -> None:
    original_schema = "trendline_v2_phase_14a1_actionable_interaction_shortlist_v1"
    original_root = Path(
        "/tmp/trendline_v2_phase14a1_actionable_interaction_shortlist/20260522_20260701"
    )
    assert study.STUDY_SCHEMA == "trendline_v2_phase_14a1r1_actionable_interaction_shortlist_v1"
    assert study.STUDY_SCHEMA != original_schema
    assert study.OUTPUT_ROOT != original_root
    assert "phase14a1r1" in str(study.OUTPUT_ROOT)
    contract = study._contract(
        {dataset_id: [{"checkpoint_index": 1}] for dataset_id in study.DATASETS}
    )
    assert contract["schema_version"] != f"{original_schema}_contract_v1"


def test_output_root_is_fixed() -> None:
    with pytest.raises(study.StudyError, match="alternate output root"):
        study.verify_bundle(Path("/tmp/other-phase14a1-output"))


def test_bundle_verifier_rejects_forged_member_and_extra_path(tmp_path: Path) -> None:
    rendered = {name: {} for name in study.MEMBER_NAMES[:-1]}
    rendered["study_contract.json"] = {"contract_id": "contract"}
    rendered["source_binding.json"] = {"source_binding_id": "source"}
    rendered["validation_lock.json"] = {"validation_lock_id": "lock"}
    rendered["decision.json"] = {"decision_id": "decision", "status": "STATUS"}
    expected = study._render_bytes(rendered)
    root = tmp_path / "bundle"
    root.mkdir()
    for name, data in expected.items():
        (root / name).write_bytes(data)
    study._validate_bundle(root, expected)
    forged = bytearray((root / "decision.json").read_bytes())
    forged[-2] = ord(" ")
    (root / "decision.json").write_bytes(bytes(forged))
    with pytest.raises(study.StudyError, match="output bytes mismatch"):
        study._validate_bundle(root, expected)
    (root / "decision.json").write_bytes(expected["decision.json"])
    (root / "unexpected.json").write_bytes(study._canonical_bytes({}))
    with pytest.raises(study.StudyError, match="output file set"):
        study._validate_bundle(root, expected)


def test_no_forbidden_data_scope_is_in_validation_datasets() -> None:
    assert set(study.DATASETS) == {"btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h"}
    assert "suiusdt_1h" not in study.DATASETS
    assert "suiusdt_4h" not in study.DATASETS


def test_artifact_contract_has_thirteen_files_and_twelve_members() -> None:
    assert len(study.ARTIFACT_NAMES) == 13
    assert len(study.MEMBER_NAMES) == 12


def test_source_binding_rejects_source_drift() -> None:
    before = {"snapshot_id": "one"}
    with pytest.raises(study.StudyError, match="source changed"):
        study._source_binding({"source_binding_id": "h1"}, before, {"snapshot_id": "two"})


def test_final_source_binding_uses_post_evaluation_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    source_calls = 0
    binding_calls: list[tuple[dict[str, str], dict[str, str]]] = []
    pre_bindings: list[dict[str, str]] = []
    lock_bindings: list[dict[str, str]] = []
    stable_snapshot = {"snapshot_id": "stable"}

    def validate_source() -> dict[str, str]:
        nonlocal source_calls
        source_calls += 1
        events.append("source_before" if source_calls == 1 else "source_after")
        return dict(stable_snapshot)

    def source_binding(
        h1_binding: dict[str, str],
        before: dict[str, str],
        after: dict[str, str],
    ) -> dict[str, str]:
        del h1_binding
        binding_calls.append((before, after))
        binding_id = f"binding-{len(binding_calls)}"
        return {
            "source_binding_id": binding_id,
            "source_before": before["snapshot_id"],
            "source_after": after["snapshot_id"],
        }

    monkeypatch.setattr(
        study,
        "_verify_h1_bundle",
        lambda: ({}, {"source_binding_id": "h1"}, {"datasets": {}}, {"rows": []}),
    )
    monkeypatch.setattr(study, "_validate_phase9_source", validate_source)
    monkeypatch.setattr(study, "_source_snapshot", lambda: pytest.fail("early source snapshot"))
    monkeypatch.setattr(study, "_load_phase9_datasets", lambda: ())
    monkeypatch.setattr(study, "_validate_active_population", lambda *_: ({}, {}))
    monkeypatch.setattr(study, "_contract", lambda *_: {})
    monkeypatch.setattr(study, "_source_binding", source_binding)

    def derive_features(*_: object) -> list[dict[str, object]]:
        events.append("derive_features")
        return []

    monkeypatch.setattr(study, "_derive_features", derive_features)
    monkeypatch.setattr(study, "_selection_records", lambda *_: ([], {}, [], {}))
    monkeypatch.setattr(
        study,
        "_selection_metrics",
        lambda *_: ([], [], {"comparisons": [], "pooled_comparisons": [], "dataset_comparisons": []}),
    )
    monkeypatch.setattr(study, "_shortlist_stability", lambda *_: ([], []))
    monkeypatch.setattr(study, "_state_stratified_utility", lambda *_: [])

    def integrity_audit(**_: object) -> dict[str, object]:
        events.append("integrity")
        return {"integrity": True, "unresolved_evidence_count": 0, "reconciliation_count": 0}

    monkeypatch.setattr(study, "_integrity_audit", integrity_audit)
    monkeypatch.setattr(
        study,
        "_make_decision",
        lambda *_: {"status": "NO_ACTIONABLE_INTERACTION_SHORTLIST_FINALIST", "decision_id": "decision"},
    )

    def validation_lock(
        _contract: object,
        binding: dict[str, str],
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, str]:
        lock_bindings.append(binding)
        return {"validation_lock_id": "lock", "source_binding_id": binding["source_binding_id"]}

    monkeypatch.setattr(study, "_validation_lock", validation_lock)
    monkeypatch.setattr(study, "_checkpoint_population", lambda *_: {})

    rendered = study._derive_evidence(
        lambda _contract, binding: pre_bindings.append(binding)
    )

    assert events == ["source_before", "derive_features", "integrity", "source_after"]
    assert source_calls == 2
    assert binding_calls == [(stable_snapshot, stable_snapshot), (stable_snapshot, stable_snapshot)]
    assert pre_bindings[0]["source_binding_id"] == "binding-1"
    assert rendered["source_binding.json"]["source_binding_id"] == "binding-2"
    assert lock_bindings[0]["source_binding_id"] == "binding-2"


def test_decision_without_selected_actionables_is_insufficient() -> None:
    rows = [{"policy_id": policy["policy_id"], "budget": budget, "nonempty_cell_coverage": 0.0, "median_selected_count": 0, "actionable_eligible_median": 0, "actionable_eligible_p90": 0, "selected_count_total": 0, "state_distribution": {}} for policy in study.POLICIES for budget in study.BUDGETS]
    result = study._make_decision(rows, {"comparisons": [], "pooled_comparisons": [], "dataset_comparisons": []}, [], {"integrity": True, "unresolved_evidence_count": 0, "reconciliation_count": 0})
    assert result["status"] == "INSUFFICIENT_ACTIONABLE_POPULATION"


def test_decision_has_six_gate_results() -> None:
    rows = [{"policy_id": policy["policy_id"], "budget": budget, "nonempty_cell_coverage": 0.0, "median_selected_count": 1, "actionable_eligible_median": 1, "actionable_eligible_p90": 1, "selected_count_total": 1, "state_distribution": {"NEAR": 1}} for policy in study.POLICIES for budget in study.BUDGETS]
    result = study._make_decision(rows, {"comparisons": [], "pooled_comparisons": [], "dataset_comparisons": []}, [{"x": 1}], {"integrity": True, "unresolved_evidence_count": 0, "reconciliation_count": 0})
    assert len(result["policy_budget_gate_results"]) == 6


def test_decision_counts_come_from_integrity_audit() -> None:
    rows = [{"policy_id": policy["policy_id"], "budget": budget, "nonempty_cell_coverage": 0.0, "median_selected_count": 0, "actionable_eligible_median": 0, "actionable_eligible_p90": 0, "selected_count_total": 0, "state_distribution": {}} for policy in study.POLICIES for budget in study.BUDGETS]
    audit = {"integrity": False, "unresolved_evidence_count": 2, "reconciliation_count": 3}
    result = study._make_decision(rows, {"comparisons": [], "pooled_comparisons": [], "dataset_comparisons": []}, [], audit)
    assert result["status"] == "ACTIONABILITY_EVIDENCE_INCOMPLETE"
    assert result["unresolved_evidence_count"] == 2
    assert result["reconciliation_count"] == 3


def test_integrity_failure_precedes_population_status() -> None:
    rows = [{"policy_id": policy["policy_id"], "budget": budget, "nonempty_cell_coverage": 1.0, "median_selected_count": 2, "actionable_eligible_median": 2, "actionable_eligible_p90": 2, "selected_count_total": 2, "state_distribution": {"NEAR": 2}} for policy in study.POLICIES for budget in study.BUDGETS]
    result = study._make_decision(
        rows,
        {"comparisons": [], "pooled_comparisons": [], "dataset_comparisons": []},
        [{"x": 1}],
        {"integrity": False, "unresolved_evidence_count": 1, "reconciliation_count": 1},
    )
    assert result["status"] == "ACTIONABILITY_EVIDENCE_INCOMPLETE"


def test_finalist_ranking_starts_with_worst_dataset_precision() -> None:
    def metric_payload(value: float, *, lower: float | None = None) -> dict[str, float | int]:
        return {"point_delta": value, "lower": value if lower is None else lower, "upper": value, "valid_replicates": study.BOOTSTRAP_REPLICATES, "invalid_replicates": 0}

    def comparison(policy_id: str, budget: int, dataset_id: str, horizon_hours: int, zone_delta: float, breach_delta: float) -> dict[str, object]:
        metrics = {
            metric: metric_payload(0.0)
            for metric in study.COMPARISON_METRICS
        }
        metrics["zone_contact_precision"] = metric_payload(zone_delta, lower=zone_delta / 2)
        metrics["future_exact_contact_precision"] = metric_payload(0.1)
        metrics["cell_hit_rate"] = metric_payload(0.1)
        metrics["zone_contact_and_survival_rate"] = metric_payload(0.1)
        metrics["sustained_breach_rate"] = metric_payload(breach_delta if horizon_hours == 96 else 0.0)
        period_payload = {
            period: {"matched_cell_count": 1, "paired_cell_count": 1, "metrics": metrics}
            for period in ("pooled", "early", "late")
        }
        return {
            "policy_id": policy_id,
            "budget": budget,
            "dataset_id": dataset_id,
            "role": "__all__",
            "control_kind": "nearest_distance_control",
            "horizon_hours": horizon_hours,
            "periods": period_payload,
            "metrics": metrics,
        }

    policy_rows = [
        {
            "policy_id": "actionable_immediate_v1",
            "budget": 5,
            "nonempty_cell_coverage": 1.0,
            "median_selected_count": 2,
            "actionable_eligible_median": 2,
            "actionable_eligible_p90": 2,
            "selected_count_total": 2,
            "state_distribution": {"NEAR": 2},
        },
        {
            "policy_id": "actionable_balanced_v1",
            "budget": 10,
            "nonempty_cell_coverage": 1.0,
            "median_selected_count": 2,
            "actionable_eligible_median": 2,
            "actionable_eligible_p90": 2,
            "selected_count_total": 2,
            "state_distribution": {"NEAR": 2},
        },
    ]
    for policy in study.POLICIES:
        for budget in study.BUDGETS:
            if any(row["policy_id"] == policy["policy_id"] and row["budget"] == budget for row in policy_rows):
                continue
            policy_rows.append(
                {
                    "policy_id": policy["policy_id"],
                    "budget": budget,
                    "nonempty_cell_coverage": 0.0,
                    "median_selected_count": 0,
                    "actionable_eligible_median": 0,
                    "actionable_eligible_p90": 0,
                    "selected_count_total": 0,
                    "state_distribution": {},
                }
            )
    pooled: list[dict[str, object]] = []
    dataset_rows: list[dict[str, object]] = []
    for policy_id, budget, zone_delta, breach_delta in (
        ("actionable_immediate_v1", 5, 0.20, 0.02),
        ("actionable_balanced_v1", 10, 0.10, -0.50),
    ):
        pooled.extend(
            comparison(policy_id, budget, "__pooled__", horizon_hours, zone_delta, breach_delta)
            for horizon_hours in (48, 96)
        )
        dataset_rows.extend(
            comparison(policy_id, budget, dataset_id, horizon_hours, zone_delta, breach_delta)
            for dataset_id in study.DATASETS
            for horizon_hours in (48, 96)
        )
    result = study._make_decision(
        policy_rows,
        {"comparisons": [], "pooled_comparisons": pooled, "dataset_comparisons": dataset_rows},
        [{"x": 1}],
        {"integrity": True, "unresolved_evidence_count": 0, "reconciliation_count": 0},
    )
    assert result["status"] == "ACTIONABLE_INTERACTION_SHORTLIST_FEASIBLE"
    assert result["finalist"] == {"policy_id": "actionable_immediate_v1", "budget": 5}


def test_manifest_path_set_is_canonical() -> None:
    assert study.ARTIFACT_NAMES[-1] == "manifest.json"
    assert study.ARTIFACT_NAMES[-2] == "output_inventory.json"


def test_source_snapshot_id_is_content_bound(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(study, "SOURCE_ROOT", tmp_path)
    (tmp_path / "datasets").mkdir()
    (tmp_path / "manifest.json").write_bytes(study._canonical_bytes({"source_decision_id": study.SOURCE_DECISION_ID, "source_manifest_id": study.SOURCE_MANIFEST_ID, "output_inventory_sha256": study.SOURCE_INVENTORY_SHA256, "underlying_source_inventory_sha256": study.UNDERLYING_SOURCE_INVENTORY_SHA256}))
    with pytest.raises(study.StudyError):
        study._validate_phase9_source()


def test_feature_identity_changes_with_policy() -> None:
    dataset, candidate = _dataset()
    first = study._feature_row(dataset, _checkpoint(), candidate, study.POLICIES[0])
    second = study._feature_row(dataset, _checkpoint(), candidate, study.POLICIES[1])
    assert first["feature_row_id"] != second["feature_row_id"]


def test_outcome_identity_binds_source_kind() -> None:
    dataset, candidate = _dataset()
    checkpoint = _checkpoint()
    first = study._future_outcome(dataset, candidate, checkpoint, "NEAR", "policy", 5, "contender")
    second = study._future_outcome(dataset, candidate, checkpoint, "NEAR", "policy", 5, "hash_order_control")
    assert first["outcome_id"] != second["outcome_id"]


def test_source_loader_does_not_accept_holdout_dataset() -> None:
    with pytest.raises(study.source_loader.StudyError, match="allowlist"):
        study.source_loader._load_dataset("suiusdt_1h", study.SOURCE_ROOT)


def test_no_provider_execution_constants_are_zero() -> None:
    assert study.BOOTSTRAP_REPLICATES == 1_000
    assert study.BOOTSTRAP_MIN_VALID == 950


def test_horizon_set_is_exact() -> None:
    dataset, candidate = _dataset()
    result = study._future_outcome(dataset, candidate, _checkpoint(), "DORMANT", "policy", 5, "contender")
    assert set(result["outcomes"]) == {"24", "48", "96"}
    assert result["outcomes"]["24"]["horizon_hours"] == 24
    assert result["outcomes"]["24"]["horizon_bar_count"] == 24
    assert result["outcomes"]["48"]["horizon_bar_count"] == 48
    assert result["outcomes"]["96"]["horizon_bar_count"] == 96


def test_four_hour_horizon_bar_counts_are_owner_timeframe_counts() -> None:
    dataset, candidate = _dataset(rows=240)
    dataset = _replace_dataset(dataset, interval_seconds=14_400)
    result = study._future_outcome(dataset, candidate, _checkpoint(), "DORMANT", "policy", 5, "contender")
    assert result["outcomes"]["24"]["horizon_hours"] == 24
    assert result["outcomes"]["24"]["horizon_bar_count"] == 6
    assert result["outcomes"]["48"]["horizon_bar_count"] == 12
    assert result["outcomes"]["96"]["horizon_bar_count"] == 24


def test_contract_labels_horizons_in_hours() -> None:
    contract = study._contract({dataset: [{"checkpoint_index": 1}] * 27 for dataset in study.DATASETS})
    assert contract["outcome_policy"]["horizons_hours"] == [24, 48, 96]
    assert "horizons_bars" not in contract["outcome_policy"]


def test_state_rows_keep_dormant_out_of_actionable_shortlist() -> None:
    row = _feature(structure="dormant", state="DORMANT", actionable=False)
    assert row["actionable"] is False


def test_canonical_json_round_trip_is_mapping() -> None:
    value = {"z": [1, 2], "a": True}
    assert json.loads(study._canonical_bytes(value)) == value
