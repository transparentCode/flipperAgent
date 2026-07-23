from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark_trendline_v2_provider import (
    _SCHEMA_VERSION,
    build_benchmark_cases,
    build_report,
    write_report,
)


def test_benchmark_cases_have_fixed_ladders_and_distinct_workloads() -> None:
    cases = build_benchmark_cases()
    assert tuple(case.name for case in cases) == (
        "sparse_no_candidate_scan",
        "normal_success",
        "candidate_rich_below_cap",
        "hypothesis_limit",
        "output_limit",
        "irregular_timestamp_space",
    )
    assert all(case.sizes == tuple(sorted(case.sizes)) for case in cases)
    assert all(len(case.sizes) >= 4 for case in cases)
    assert len({case.workload_class for case in cases}) == len(cases)


def test_benchmark_report_schema_and_semantic_repetition() -> None:
    report = build_report(repeats=2, warmups=1)
    assert report["schema_version"] == _SCHEMA_VERSION
    assert report["benchmark"]["offline"] is True
    assert report["benchmark"]["network_access"] is False
    assert report["decision"]["numba_authorization"] == "NOT_AUTHORIZED"
    assert len(report["workloads"]) == 6
    for workload in report["workloads"]:
        assert workload["results"]
        for result in workload["results"]:
            assert result["input_unchanged"] is True
            assert result["repetitions_identical"] is True
            assert len(result["result_digest"]) == 64
            assert result["timing"]["repeats"] == 2
    assert len(report["profiles"]) == 6
    assert len(report["memory"]) == 3
    json.dumps(report)


def test_expected_guard_and_success_semantics_are_present() -> None:
    report = build_report(repeats=1, warmups=0)
    workloads = {item["name"]: item for item in report["workloads"]}
    assert {item["status"] for item in workloads["sparse_no_candidate_scan"]["results"]} == {
        "abstained"
    }
    assert workloads["normal_success"]["results"][-1]["status"] == "success"
    assert any(
        item["reason"] == "hypothesis_limit_exceeded"
        for item in workloads["hypothesis_limit"]["results"]
    )
    assert any(
        item["reason"] == "output_limit_exceeded"
        for item in workloads["output_limit"]["results"]
    )
    assert workloads["irregular_timestamp_space"]["results"][-1]["status"] == "success"


def test_report_writer_emits_valid_json_at_explicit_path(tmp_path: Path) -> None:
    output = tmp_path / "profile.json"
    write_report(build_report(repeats=1, warmups=0), output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == _SCHEMA_VERSION
