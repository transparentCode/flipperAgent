"""Offline profiling harness for the Trendline V2 reference provider."""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import math
import os
import pstats
import statistics
import tempfile
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from libs.models.trendline_v2.configuration import (
    ConfirmedExtremaPairConfig,
    PROVIDER_NAME,
    PROVIDER_VERSION,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    ConfirmedExtremaPairProvider,
    ProviderInput,
    ProviderReason,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)


UTC = timezone.utc
_HOUR_NS = 3_600_000_000_000
_BASE_TIME = datetime(2024, 1, 1, tzinfo=UTC)
_SCHEMA_VERSION = "trendline_v2_provider_profile_v1"


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    name: str
    purpose: str
    workload_class: str
    sizes: tuple[int, ...]
    expected_status: Callable[[int], ProviderStatus]
    expected_reason: Callable[[int], ProviderReason | None]
    input_factory: Callable[[int], ProviderInput]
    config_overrides: dict[str, int]
    profile_size: int
    memory_size: int | None


def _foundation_config():
    return resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )


def _timestamps_from_offsets(offsets_hours: Iterable[int]) -> tuple[int, ...]:
    base_ns = int(_BASE_TIME.timestamp() * 1_000_000_000)
    return tuple(base_ns + offset * _HOUR_NS for offset in offsets_hours)


def _input_from_offsets(
    offsets_hours: tuple[int, ...],
    *,
    shape: str,
) -> ProviderInput:
    rows = len(offsets_hours)
    lows = [5.0] * rows
    highs = [11.0] * rows
    if shape == "normal":
        first = rows // 3
        second = rows - 3
        lows[first] = 1.0
        lows[second] = 2.0
    elif shape == "rich":
        for position in range(1, rows - 1, 2):
            lows[position] = 1.0
            highs[position] = 12.0
    elif shape == "flat":
        pass
    else:
        raise ValueError(f"unknown benchmark shape: {shape}")
    timestamps = _timestamps_from_offsets(offsets_hours)
    observed_at = _BASE_TIME + timedelta(hours=offsets_hours[-1])
    body = (10.0,) * rows
    return ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=observed_at,
        confirmed_through=observed_at,
        timestamps=timestamps,
        open=body,
        high=tuple(highs),
        low=tuple(lows),
        close=body,
        volume=(1.0,) * rows,
    )


def _regular_input(rows: int, *, shape: str) -> ProviderInput:
    return _input_from_offsets(tuple(range(rows)), shape=shape)


def _irregular_input(rows: int) -> ProviderInput:
    offsets = [0]
    for position in range(1, rows):
        offsets.append(offsets[-1] + (1 if position % 2 else 2))
    return _input_from_offsets(tuple(offsets), shape="normal")


def _result_for(case: BenchmarkCase, rows: int) -> tuple[ProviderStatus, ProviderReason | None]:
    return case.expected_status(rows), case.expected_reason(rows)


def _success(_rows: int) -> ProviderStatus:
    return ProviderStatus.SUCCESS


def _abstained(_rows: int) -> ProviderStatus:
    return ProviderStatus.ABSTAINED


def _no_reason(_rows: int) -> ProviderReason | None:
    return None


def _insufficient(_rows: int) -> ProviderReason:
    return ProviderReason.INSUFFICIENT_INPUT


def _hypothesis_reason(rows: int) -> ProviderReason | None:
    return ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED if rows >= 31 else None


def _output_reason(rows: int) -> ProviderReason | None:
    return ProviderReason.OUTPUT_LIMIT_EXCEEDED if rows >= 15 else None


def _hypothesis_status(rows: int) -> ProviderStatus:
    return ProviderStatus.ABSTAINED if rows >= 31 else ProviderStatus.SUCCESS


def _output_status(rows: int) -> ProviderStatus:
    return ProviderStatus.ABSTAINED if rows >= 15 else ProviderStatus.SUCCESS


def build_benchmark_cases() -> tuple[BenchmarkCase, ...]:
    """Return fixed synthetic cases and workload ladders."""

    return (
        BenchmarkCase(
            name="sparse_no_candidate_scan",
            purpose="Extrema scan over flat input with no candidate generation.",
            workload_class="linear_scan_workload",
            sizes=(7, 14, 28, 56, 112, 224),
            expected_status=_abstained,
            expected_reason=_insufficient,
            input_factory=lambda rows: _regular_input(rows, shape="flat"),
            config_overrides={"max_hypotheses": 100_000, "max_output_candidates": 100_000},
            profile_size=224,
            memory_size=None,
        ),
        BenchmarkCase(
            name="normal_success",
            purpose="Two confirmed support extrema with one exact candidate.",
            workload_class="successful_candidate_workload",
            sizes=(7, 14, 28, 56, 112, 224),
            expected_status=_success,
            expected_reason=_no_reason,
            input_factory=lambda rows: _regular_input(rows, shape="normal"),
            config_overrides={"max_hypotheses": 100_000, "max_output_candidates": 100_000},
            profile_size=224,
            memory_size=224,
        ),
        BenchmarkCase(
            name="candidate_rich_below_cap",
            purpose="Dense support/resistance extrema with complete pair construction.",
            workload_class="hypothesis_count_workload",
            sizes=(7, 15, 31, 63),
            expected_status=_success,
            expected_reason=_no_reason,
            input_factory=lambda rows: _regular_input(rows, shape="rich"),
            config_overrides={"max_hypotheses": 10_000, "max_output_candidates": 10_000},
            profile_size=63,
            memory_size=63,
        ),
        BenchmarkCase(
            name="hypothesis_limit",
            purpose="Early pair-count guard before pair materialization.",
            workload_class="overflow_workload",
            sizes=(7, 15, 31, 63, 127, 255),
            expected_status=_hypothesis_status,
            expected_reason=_hypothesis_reason,
            input_factory=lambda rows: _regular_input(rows, shape="rich"),
            config_overrides={"max_hypotheses": 100, "max_output_candidates": 100_000},
            profile_size=63,
            memory_size=63,
        ),
        BenchmarkCase(
            name="output_limit",
            purpose="Complete candidate construction followed by output abstention.",
            workload_class="body_validation_workload",
            sizes=(7, 15, 31, 63),
            expected_status=_output_status,
            expected_reason=_output_reason,
            input_factory=lambda rows: _regular_input(rows, shape="rich"),
            config_overrides={"max_hypotheses": 100_000, "max_output_candidates": 10},
            profile_size=63,
            memory_size=None,
        ),
        BenchmarkCase(
            name="irregular_timestamp_space",
            purpose="Successful candidate path with nonuniform elapsed UTC timestamps.",
            workload_class="timestamp_geometry_workload",
            sizes=(7, 14, 28, 56, 112),
            expected_status=_success,
            expected_reason=_no_reason,
            input_factory=_irregular_input,
            config_overrides={"max_hypotheses": 100_000, "max_output_candidates": 100_000},
            profile_size=112,
            memory_size=None,
        ),
    )


def _request_for(case: BenchmarkCase, rows: int) -> ProviderRequest:
    input_data = case.input_factory(rows)
    lookback_seconds = (input_data.timestamps[-1] - input_data.timestamps[0]) / 1_000_000_000
    config = ConfirmedExtremaPairConfig(
        lookback_duration_seconds=lookback_seconds + 3_600.0,
        left_confirmation_bars=1,
        right_confirmation_bars=1,
        min_extrema_per_role=2,
        **case.config_overrides,
    )
    return ProviderRequest(
        input_data=input_data,
        config=_foundation_config(),
        provider_config=config,
    )


def _json_default(value):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def semantic_digest(result: ProviderResult) -> str:
    payload = json.dumps(
        result.to_dict(),
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _timing_summary(samples_ns: list[int], repeats: int) -> dict[str, int]:
    return {
        "min_ns": min(samples_ns),
        "p50_ns": int(statistics.median(samples_ns)),
        "p95_ns": _percentile(samples_ns, 0.95),
        "max_ns": max(samples_ns),
        "repeats": repeats,
    }


def _profile_path(filename: str) -> str:
    normalized = Path(filename).as_posix()
    for marker in ("/src/", "/scripts/"):
        if marker in normalized:
            return normalized[normalized.index(marker) + 1 :]
    return Path(normalized).name


def _profile_rows(profile: cProfile.Profile, *, sort_key: str, limit: int = 15) -> list[dict[str, object]]:
    stats = pstats.Stats(profile).stats
    rows = []
    for (filename, line_number, function_name), (primitive_calls, total_calls, total_time, cumulative_time, _callers) in stats.items():
        rows.append(
            {
                "function": f"{_profile_path(filename)}:{line_number}:{function_name}",
                "primitive_calls": primitive_calls,
                "calls": total_calls,
                "total_time_s": total_time,
                "cumulative_time_s": cumulative_time,
            }
        )
    rows.sort(key=lambda row: (-float(row[sort_key]), str(row["function"])))
    return rows[:limit]


def _profile_one(provider: ConfirmedExtremaPairProvider, request: ProviderRequest) -> dict[str, object]:
    profile = cProfile.Profile()
    result = profile.runcall(provider.generate, request)
    digest = semantic_digest(result)
    return {
        "result_digest": digest,
        "status": result.status.value,
        "reason": result.reason.value if result.reason is not None else None,
        "top_cumulative": _profile_rows(profile, sort_key="cumulative_time_s"),
        "top_total": _profile_rows(profile, sort_key="total_time_s"),
        "top_call_count": _profile_rows(profile, sort_key="calls"),
    }


def _memory_one(provider: ConfirmedExtremaPairProvider, request: ProviderRequest) -> dict[str, object]:
    tracemalloc.start()
    result = provider.generate(request)
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "result_digest": semantic_digest(result),
        "status": result.status.value,
        "reason": result.reason.value if result.reason is not None else None,
        "current_bytes": current_bytes,
        "peak_bytes": peak_bytes,
    }


def _run_size(
    provider: ConfirmedExtremaPairProvider,
    case: BenchmarkCase,
    rows: int,
    *,
    repeats: int,
    warmups: int,
) -> dict[str, object]:
    request = _request_for(case, rows)
    expected_status, expected_reason = _result_for(case, rows)
    input_before = request.input_data.to_dict()
    warmup_result = provider.generate(request)
    warmup_digest = semantic_digest(warmup_result)
    if (warmup_result.status, warmup_result.reason) != (expected_status, expected_reason):
        raise AssertionError(
            f"{case.name}/{rows}: expected {expected_status.value}/{expected_reason}, "
            f"got {warmup_result.status.value}/{warmup_result.reason}"
        )
    samples_ns: list[int] = []
    digests: list[str] = []
    for _ in range(warmups):
        warmup = provider.generate(request)
        if semantic_digest(warmup) != warmup_digest:
            raise AssertionError(f"{case.name}/{rows}: warm-up output changed")
    for _ in range(repeats):
        started_ns = time.perf_counter_ns()
        result = provider.generate(request)
        samples_ns.append(time.perf_counter_ns() - started_ns)
        digest = semantic_digest(result)
        digests.append(digest)
        if digest != warmup_digest:
            raise AssertionError(f"{case.name}/{rows}: repeated output changed")
        if request.input_data.to_dict() != input_before:
            raise AssertionError(f"{case.name}/{rows}: provider mutated input")
    if len(set(digests)) != 1:
        raise AssertionError(f"{case.name}/{rows}: repeated digests differ")
    candidate_count = len(warmup_result.candidates)
    return {
        "rows": rows,
        "provider_config": request.provider_config.to_dict(),
        "status": warmup_result.status.value,
        "reason": warmup_result.reason.value if warmup_result.reason is not None else None,
        "candidate_count": candidate_count,
        "result_digest": warmup_digest,
        "input_unchanged": request.input_data.to_dict() == input_before,
        "repetitions_identical": len(set(digests)) == 1,
        "timing": _timing_summary(samples_ns, repeats),
    }


def _scaling_points(size_results: list[dict[str, object]]) -> list[dict[str, object]]:
    points = []
    for item in size_results:
        rows = int(item["rows"])
        median_ns = int(item["timing"]["p50_ns"])
        candidates = int(item["candidate_count"])
        points.append(
            {
                "rows": rows,
                "median_ns": median_ns,
                "median_ns_per_row": median_ns / rows,
                "candidate_count": candidates,
                "median_ns_per_candidate": median_ns / candidates if candidates else None,
            }
        )
    return points


def build_report(*, repeats: int = 20, warmups: int = 1) -> dict[str, object]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    provider = ConfirmedExtremaPairProvider()
    cases_report = []
    profile_cases = []
    memory_cases = []
    for case in build_benchmark_cases():
        size_results = [
            _run_size(provider, case, rows, repeats=repeats, warmups=warmups)
            for rows in case.sizes
        ]
        cases_report.append(
            {
                "name": case.name,
                "purpose": case.purpose,
                "workload_class": case.workload_class,
                "sizes": list(case.sizes),
                "results": size_results,
                "scaling_points": _scaling_points(size_results),
                "profile_size": case.profile_size,
                "memory_size": case.memory_size,
            }
        )
        profile_cases.append(
            {
                "name": case.name,
                "rows": case.profile_size,
                "profile": _profile_one(provider, _request_for(case, case.profile_size)),
            }
        )
        if case.memory_size is not None:
            memory_cases.append(
                {
                    "name": case.name,
                    "rows": case.memory_size,
                    "memory": _memory_one(provider, _request_for(case, case.memory_size)),
                }
            )
    return {
        "schema_version": _SCHEMA_VERSION,
        "provider": {"name": PROVIDER_NAME, "version": PROVIDER_VERSION},
        "benchmark": {
            "offline": True,
            "network_access": False,
            "repeats": repeats,
            "warmups": warmups,
            "timer": "time.perf_counter_ns",
            "profiler": "cProfile",
            "memory_profiler": "tracemalloc",
            "fixture_policy": "deterministic_synthetic_only",
        },
        "workloads": cases_report,
        "profiles": profile_cases,
        "memory": memory_cases,
        "decision": {
            "recommendation": "RETAIN_PYTHON",
            "numba_authorization": "NOT_AUTHORIZED",
            "rationale": (
                "Dense profiles are dominated by candidate construction, contract "
                "validation, identity hashing and serialization; no isolated numeric "
                "loop dominates the public path."
            ),
            "numeric_targets_ordered_by_evidence": [
                {
                    "target": "_candidate_record body-validation segment",
                    "evidence": "highest aggregate provider-side cumulative region; mixed with candidate construction",
                    "next_step": "profile isolated numeric segment before any kernel study",
                },
                {
                    "target": "_confirmed_extrema",
                    "evidence": "linear guard-path scan and repeated extrema work",
                    "next_step": "retain as Python until isolated cost is measured",
                },
                {
                    "target": "LineGeometry.value_at",
                    "evidence": "repeated per-intermediate-candle projection calls",
                    "next_step": "candidate only after body-validation isolation",
                },
            ],
            "python_owned_functions": [
                "ConfirmedExtremaPairProvider.generate",
                "ProviderResult validation",
                "LineCandidate construction and validation",
                "deterministic identity hashing",
                "semantic serialization",
            ],
        },
    }


def write_report(report: dict[str, object], output: Path) -> None:
    payload = json.dumps(
        report,
        default=_json_default,
        sort_keys=True,
        indent=2,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_report(build_report(repeats=args.repeats, warmups=args.warmups), args.output)


if __name__ == "__main__":
    main()
