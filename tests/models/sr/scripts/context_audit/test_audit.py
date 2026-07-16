from __future__ import annotations

from dataclasses import replace

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
