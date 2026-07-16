from __future__ import annotations

from dataclasses import replace
from copy import deepcopy

import pytest

from libs.models.sr.domain.contracts import ContractValidationError, ZoneStatus
from libs.models.sr.domain.identity import deterministic_hash
from libs.models.sr.scripts.context_audit.contracts import validate_audit_payload


def test_exact_case_mapping_and_populations(context_result):
    audit, chart = context_result
    assert len(audit.cases) == 36
    assert len({case.case_id for case in audit.cases}) == 36
    assert len({case.zone_id for case in audit.cases}) == 36
    assert len({case.record_id for case in audit.cases}) == 36
    assert sum(case.comparison is not None for case in audit.cases) == 31
    assert sum(case.comparison is None for case in audit.cases) == 5
    assert audit.v19_parity["approved_pooled"]["total_outcomes"] == 36
    assert audit.v19_parity["approved_pooled"]["completed_outcomes"] == 36
    assert audit.v19_parity["approved_pooled"]["right_censored_outcomes"] == 0
    assert audit.v19_parity["fold_local"]["completed_outcomes"] == 34
    assert audit.v19_parity["fold_local"]["right_censored_outcomes"] == 2
    assert audit.v19_parity["comparable_mapped"]["completed_outcomes"] == 31
    assert chart["casebook"]["case_count"] == 36
    assert [case["case_id"] for case in chart["casebook"]["cases"]] == [case.case_id for case in audit.cases]


def test_frozen_parity_values_and_fold_boundaries(context_result):
    audit, _ = context_result
    aggregate = audit.v19_parity["approved_pooled"]
    assert aggregate["median_quality_reference_atr"] == pytest.approx(-0.014070405071082426)
    fold_local = audit.v19_parity["fold_local"]
    assert fold_local["median_quality_reference_atr"] == pytest.approx(0.1807362526958346)
    study_aggregate = audit.v19_parity["disposition"]
    assert study_aggregate["disposition"] == "BASELINE_NOT_BETTER_THAN_NAIVE_NULL"
    fold_counts = [row["completed_real_count"] for row in audit.v19_parity["fold_metrics"]]
    assert fold_counts == [7, 8, 6, 6, 3, 4]
    assert audit.v19_parity["comparable_mapped"]["fold_count"] == 5
    assert audit.v19_parity["aggregate"]["pooled_median_excess_quality"] == pytest.approx(0.026200435413100243)
    assert audit.v19_parity["aggregate"]["positive_comparable_fold_fraction"] == pytest.approx(0.4)
    assert audit.v19_parity["aggregate"]["worst_comparable_fold_excess"] == pytest.approx(-1.1546071281136923)
    q3 = next(row for row in audit.v19_parity["fold_metrics"] if row["fold"] == "2025_q3")
    assert q3["comparable"] is False


def test_causal_statuses_and_inclusive_lifecycle_window(context_result):
    audit, _ = context_result
    for case in audit.cases:
        assert case.entering_status in {ZoneStatus.ACTIVE, ZoneStatus.BREACH_PENDING}
        assert case.touch_bar.closed_at == case.first_touch_at
        assert case.pooled_outcome.tenth_outcome_bar_closed_at is not None
        assert all(case.first_touch_at <= event.timestamp <= case.pooled_outcome.tenth_outcome_bar_closed_at for event in case.lifecycle_events)
        assert case.creation_event.timestamp == case.zone.available_at
        assert case.creation_event.event_type.value == "CREATED"
        assert case.case_id == deterministic_hash(case.identity_payload())


def test_causal_event_order_and_metric_reconciliation(context_result):
    audit, chart = context_result
    for case in audit.cases:
        timestamps = [event.timestamp for event in case.lifecycle_events]
        assert timestamps == sorted(timestamps)
        horizon = case.pooled_outcome.tenth_outcome_bar_closed_at
        assert horizon is not None
        assert all(event.timestamp <= event.snapshot_as_of <= horizon for event in case.lifecycle_events)
        if case.pooled_outcome.completed:
            assert case.pooled_outcome.quality_reference_atr == pytest.approx(
                case.pooled_outcome.favorable_reference_atr - case.pooled_outcome.adverse_reference_atr
            )
        else:
            assert case.pooled_outcome.quality_reference_atr is None
        case_payload = next(item for item in chart["casebook"]["cases"] if item["case_id"] == case.case_id)
        if case.comparison is None:
            assert case_payload["comparison"] is None
        else:
            assert case_payload["comparison"] is not None


def test_direct_nested_contracts_reject_invalid_enum_and_identity_reuse(context_result):
    audit, _ = context_result
    case = audit.cases[0]
    with pytest.raises(ContractValidationError):
        replace(case.zone, side="SUPPORT")
    with pytest.raises(ContractValidationError):
        replace(case, horizon_lifecycle_class="UNKNOWN")
    with pytest.raises(ContractValidationError):
        replace(case, entering_status="ACTIVE")

    duplicate_record = replace(audit.cases[-1], record_id=case.record_id)
    with pytest.raises(ContractValidationError):
        replace(audit, cases=(*audit.cases[:-1], duplicate_record))

    duplicate_zone_id = case.zone_id
    duplicate_creation_event = replace(audit.cases[-1].creation_event, zone_id=duplicate_zone_id)
    duplicate_lifecycle_events = tuple(
        replace(event, zone_id=duplicate_zone_id)
        for event in audit.cases[-1].lifecycle_events
    )
    duplicate_comparison = (
        None
        if audit.cases[-1].comparison is None
        else replace(audit.cases[-1].comparison, side=case.side)
    )
    duplicate_zone = replace(
        audit.cases[-1],
        zone=case.zone,
        zone_id=duplicate_zone_id,
        side=case.side,
        creation_event=duplicate_creation_event,
        lifecycle_events=duplicate_lifecycle_events,
        comparison=duplicate_comparison,
    )
    with pytest.raises(ContractValidationError):
        replace(audit, cases=(*audit.cases[:-1], duplicate_zone))

    first_comparable = next(item for item in audit.cases if item.comparison is not None)
    second_comparable = next(
        item for item in audit.cases
        if item is not first_comparable
        and item.comparison is not None
        and item.fold == first_comparable.fold
        and item.side is first_comparable.side
    )
    duplicate_comparison = replace(
        second_comparable,
        comparison_real_outcome_id=first_comparable.comparison_real_outcome_id,
        comparison=first_comparable.comparison,
    )
    with pytest.raises(ContractValidationError):
        replace(
            audit,
            cases=tuple(duplicate_comparison if item is second_comparable else item for item in audit.cases),
        )

    duplicate_event = replace(
        audit.cases[-1].creation_event,
        event_id=audit.cases[0].creation_event.event_id,
    )
    duplicate_event_case = replace(audit.cases[-1], creation_event=duplicate_event)
    with pytest.raises(ContractValidationError):
        replace(audit, cases=(*audit.cases[:-1], duplicate_event_case))


@pytest.mark.parametrize(
    "path_mutation",
    (
        lambda payload: payload["cases"][1].__setitem__("case_id", payload["cases"][0]["case_id"]),
        lambda payload: payload["cases"][1].__setitem__("zone_id", payload["cases"][0]["zone_id"]),
        lambda payload: payload["cases"][1].__setitem__("record_id", payload["cases"][0]["record_id"]),
        lambda payload: payload["cases"][1].__setitem__("touch_bar_id", payload["cases"][0]["touch_bar_id"]),
        lambda payload: payload["cases"][1]["touch_bar"].__setitem__("bar_id", payload["cases"][0]["touch_bar"]["bar_id"]),
        lambda payload: payload["cases"][1]["creation_event"].__setitem__("event_id", payload["cases"][0]["creation_event"]["event_id"]),
        lambda payload: payload["cases"][1]["creation_event"].__setitem__("snapshot_id", payload["cases"][0]["creation_event"]["snapshot_id"]),
        lambda payload: payload["v19_parity"]["aggregate"].__setitem__("pooled_median_excess_quality", 999.0),
        lambda payload: payload.__setitem__("audit_status", "INCOMPLETE"),
    ),
)
def test_rehashed_or_identity_tampering_rejected(path_mutation, context_result):
    audit, _ = context_result
    payload = deepcopy(audit.to_payload())
    path_mutation(payload)
    with pytest.raises(ContractValidationError):
        validate_audit_payload(payload, audit)


def test_repeated_case_identity_is_rejected(context_result):
    audit, _ = context_result
    cases = list(audit.cases)
    cases[-1] = cases[0]
    with pytest.raises(ContractValidationError):
        replace(audit, cases=tuple(cases))


def test_audit_payload_tampering_is_rejected(context_result):
    audit, _ = context_result
    payload = audit.to_payload()
    payload["cases"][0]["case_id"] = "0" * 64
    with pytest.raises(ContractValidationError):
        validate_audit_payload(payload, audit)
