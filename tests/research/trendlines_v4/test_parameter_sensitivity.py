"""Focused contract tests for the V4 H0 parameter-sensitivity tape."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from libs.models.trendlines_v4.core import TrendlineBar, TrendlineGeometry
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import parameter_sensitivity as h0

BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _source_bars(count: int = 700) -> tuple[n1.SourceBar, ...]:
    bars: list[n1.SourceBar] = []
    for index in range(count):
        open_price = 100.0 + index * 0.01
        close_price = open_price + (0.2 if index % 2 else -0.1)
        bars.append(
            n1.SourceBar(
                open_at=BASE + timedelta(hours=index),
                closed_at=BASE
                + timedelta(hours=index, minutes=59, seconds=59, milliseconds=999),
                open=open_price,
                high=max(open_price, close_price) + 0.5,
                low=min(open_price, close_price) - 0.5,
                close=close_price,
            )
        )
    return tuple(bars)


def _history(
    *,
    count: int = 300,
    default_body: float = 102.0,
    adverse_index: int | None = None,
) -> tuple[TrendlineBar, ...]:
    bars: list[TrendlineBar] = []
    for index in range(count):
        body = 99.0 if index == adverse_index else default_body
        bars.append(
            TrendlineBar(
                closed_at=BASE
                + timedelta(hours=index, minutes=59, seconds=59, milliseconds=999),
                open=body,
                high=body + 1.0,
                low=body - 1.0,
                close=body,
            )
        )
    return tuple(bars)


def _line(
    history: tuple[TrendlineBar, ...],
    *,
    side: str = "support",
    start_index: int = 5,
    end_index: int = 10,
    projected: float = 100.0,
    post_anchor_body_crossed: bool = False,
    post_anchor_body_cross_count: int = 0,
) -> TrendlineGeometry:
    start_price = 100.0
    end_price = 100.0
    return TrendlineGeometry(
        side=side,
        start_anchor_at=history[start_index].closed_at,
        start_anchor_price=start_price,
        end_anchor_at=history[end_index].closed_at,
        end_anchor_price=end_price,
        slope_per_bar=0.0,
        projected_price_at_market_as_of=projected,
        post_anchor_body_crossed=post_anchor_body_crossed,
        post_anchor_body_cross_count=post_anchor_body_cross_count,
        projection_positive=projected > 0,
    )


def _cutoff(
    *,
    source_position: int = 671,
    partition: str = "development",
) -> h0.H0Cutoff:
    return h0.H0Cutoff(
        asset="BTCUSDT",
        timeframe="1h",
        window="early",
        cutoff=0,
        source_position=source_position,
        market_as_of=n1._timestamp(
            BASE
            + timedelta(
                hours=source_position,
                minutes=59,
                seconds=59,
                milliseconds=999,
            )
        ),
        partition=partition,  # type: ignore[arg-type]
    )


def _stream(*, bars: tuple[n1.SourceBar, ...] | None = None) -> h0.H0Stream:
    source = bars or _source_bars()
    return h0.H0Stream(
        asset="BTCUSDT",
        timeframe="1h",
        bars=source,
        development=(_cutoff(),),
        holdout=(_cutoff(source_position=672, partition="holdout"),),
    )


def _fact(
    *,
    side: str = "support",
    role: str = "structural",
    geometry_id: str = "geometry",
    adverse: str = "respecting",
    non_positive: bool = False,
) -> h0.H0LineFact:
    return h0.H0LineFact(
        side=side,  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        geometry_id=geometry_id,
        start_anchor_at="2025-01-01T00:00:00.000000Z",
        end_anchor_at="2025-01-01T05:59:59.999000Z",
        start_anchor_price=100.0,
        end_anchor_price=100.0,
        projected_price=100.0,
        projected_price_hex=(100.0).hex(),
        slope_per_bar=0.0,
        projection_positive=not non_positive,
        absolute_close_distance_bps=0.0,
        body_clearance_bps=100.0,
        anchor_span_bars=5,
        start_anchor_age_bars=294,
        end_anchor_age_bars=289,
        start_anchor_headroom_bars=5,
        left_pivot_eligibility_margin_bars=2,
        slope_bps_per_bar=0.0,
        post_anchor_bar_count=289,
        post_anchor_adverse_body_bar_count=0,
        post_anchor_adverse_body_bar_rate=0.0,
        bars_since_last_adverse_body_bar=None,
        current_body_adverse_side=adverse,  # type: ignore[arg-type]
        projection_non_positive=non_positive,
    )


def _minimal_report_inputs(
    numerical: h0._NumericalAccumulator | None = None,
) -> dict[str, object]:
    stream = _stream()
    profile = next(
        profile for profile in h0.profiles_for_timeframe("1h") if profile.is_baseline
    )
    report = {
        "profile": profile.as_payload(),
        "metadata": {
            "role_observations": {"global": {"projection_non_positive_count": 0}}
        },
    }
    return {
        "prior": {},
        "streams": (stream,),
        "profiles": (profile,),
        "baseline_parity": {"status": "passed"},
        "pilot": {
            "status": "passed",
            "cutoff_membership": [],
            "evaluation_count": 960,
            "rss_limit_bytes": h0.PILOT_MAX_RSS_BYTES,
            "median_call_time_multiplier_limit_descriptive": 10.0,
            "median_call_time_multiplier_limit_is_gate": False,
            "resource_semantics": {
                "baseline_relative_ratio": "descriptive only; not a stop gate",
            },
        },
        "profile_reports": (report,),
        "matrix_resources": {
            "evaluation_count": 1,
            "wall_seconds": 0.1,
            "cpu_seconds": 0.1,
            "peak_process_rss_bytes": 1,
            "profile_resources": [
                {
                    "profile_id": profile.profile_id,
                    "call_count": 1,
                    "wall_seconds": 0.1,
                    "cpu_seconds": 0.1,
                }
            ],
        },
        "numerical": numerical or h0._NumericalAccumulator(),
        "rerun_evidence": {"run_count": 2},
    }


def test_profile_grid_is_exact_and_duration_conversion_is_physical() -> None:
    one_hour = h0.profiles_for_timeframe("1h")
    four_hour = h0.profiles_for_timeframe("4h")
    assert len(one_hour) == len(four_hour) == 15
    assert one_hour[0].is_baseline and four_hour[0].is_baseline
    assert {profile.pivot_window for profile in one_hour} == {2, 3, 5}
    assert {
        profile.effective_history_bars
        for profile in one_hour
        if profile.history_policy_kind == "fixed_duration"
    } == {336, 672}
    assert {
        profile.effective_history_bars
        for profile in four_hour
        if profile.history_policy_kind == "fixed_duration"
    } == {84, 168}
    assert len(h0.all_profiles()) == 30


def test_profile_ids_deduplicate_effective_profile_grid() -> None:
    profiles = h0.profiles_for_timeframe("1h")
    keys = {
        (
            profile.pivot_window,
            profile.history_policy_kind,
            profile.effective_history_bars,
        )
        for profile in profiles
    }
    assert (
        len(keys) == len(profiles) == len({profile.profile_id for profile in profiles})
    )


def test_patched_core_restores_globals_on_success_and_exception() -> None:
    profile = h0.profiles_for_timeframe("1h")[0]
    original = (h0.core.PIVOT_WINDOW, h0.core.HISTORY_CAPACITY_BARS)
    with h0._patched_core(profile):
        assert (h0.core.PIVOT_WINDOW, h0.core.HISTORY_CAPACITY_BARS) == (
            profile.pivot_window,
            profile.effective_history_bars,
        )
    assert (h0.core.PIVOT_WINDOW, h0.core.HISTORY_CAPACITY_BARS) == original
    with pytest.raises(RuntimeError), h0._patched_core(profile):
        raise RuntimeError("injected")
    assert (h0.core.PIVOT_WINDOW, h0.core.HISTORY_CAPACITY_BARS) == original


def test_history_is_exact_causal_slice_and_future_suffix_is_ignored() -> None:
    original = _source_bars()
    changed = original[:672] + tuple(
        replace(
            bar,
            open=bar.open + 50.0,
            high=bar.high + 50.0,
            low=bar.low + 50.0,
            close=bar.close + 50.0,
        )
        for bar in original[672:]
    )
    first = h0._history_for_cutoff(_stream(bars=original), _cutoff(), 300)
    second = h0._history_for_cutoff(_stream(bars=changed), _cutoff(), 300)
    assert len(first) == 300
    assert first == second
    assert first[0].closed_at == original[372].closed_at
    assert first[-1].closed_at == original[671].closed_at


def test_holdout_cutoff_cannot_enter_h0_history_evaluator() -> None:
    with pytest.raises(h0.H0ContractError, match="unopened holdout"):
        h0._history_for_cutoff(
            _stream(),
            _cutoff(source_position=672, partition="holdout"),
            300,
        )


def test_common_membership_has_expected_real_stream_shape() -> None:
    streams = h0.build_streams()
    assert len(streams) == 8
    counts = {
        (stream.asset, stream.timeframe): len(stream.development) for stream in streams
    }
    assert sum(counts.values()) == 4638
    assert counts[("HYPEUSDT", "4h")] == 438
    assert all(len(stream.holdout) == 192 for stream in streams)
    assert h0.development_membership(streams)["cutoff_count"] == 4638
    assert h0.holdout_membership(streams)["cutoff_count"] == 1536


def test_pivot_relative_margin_and_p0_adverse_body_semantics() -> None:
    profile = next(
        profile for profile in h0.profiles_for_timeframe("1h") if profile.is_baseline
    )
    history = _history(adverse_index=12)
    line = _line(
        history,
        post_anchor_body_crossed=True,
        post_anchor_body_cross_count=1,
    )
    fact = h0._line_fact(
        line,
        history,
        profile=profile,
        cutoff=_cutoff(),
        role="structural",
    )
    assert fact.left_pivot_eligibility_margin_bars == 2
    assert fact.start_anchor_headroom_bars == 5
    assert fact.post_anchor_adverse_body_bar_count == 1
    assert fact.current_body_adverse_side == "respecting"
    clean = _history()
    clean_line = _line(clean)
    current_valid = h0._line_fact(
        clean_line,
        clean,
        profile=profile,
        cutoff=_cutoff(),
        role="current_valid",
    )
    assert current_valid.post_anchor_adverse_body_bar_count == 0
    with pytest.raises(h0.H0ContractError, match="current-valid"):
        h0._line_fact(
            line,
            history,
            profile=profile,
            cutoff=_cutoff(),
            role="current_valid",
        )


def test_observed_runs_are_censor_aware_and_reappearance_is_exact() -> None:
    runs, eligible, replacements, reappearances = h0._run_records(
        ("a", "a", None, "b", "b", None, "a")
    )
    assert eligible == 2
    assert replacements == 0
    assert reappearances == 1
    assert runs == [
        {
            "geometry_id": "a",
            "observed_run_length_bars": 2,
            "left_censored": True,
            "right_censored": False,
            "reappearance": False,
        },
        {
            "geometry_id": "b",
            "observed_run_length_bars": 2,
            "left_censored": False,
            "right_censored": False,
            "reappearance": False,
        },
        {
            "geometry_id": "a",
            "observed_run_length_bars": 1,
            "left_censored": False,
            "right_censored": True,
            "reappearance": True,
        },
    ]
    gap_runs, gap_eligible, gap_replacements, _ = h0._run_records(("a", None, "b"))
    assert len(gap_runs) == 2
    assert (gap_eligible, gap_replacements) == (0, 0)


def test_duplicate_role_geometry_is_deduplicated_without_role_bias() -> None:
    cutoff = _cutoff()
    structural = h0.H0Observation(cutoff, _fact(role="structural"))
    current = h0.H0Observation(cutoff, _fact(role="current_valid"))
    unique: dict[tuple[object, ...], h0.H0Observation] = {}
    h0._register_unique(unique, structural)
    h0._register_unique(unique, current)
    assert len(unique) == 1


def test_same_identity_numerical_semantic_disagreement_blocks_conclusion() -> None:
    cutoff = _cutoff()
    first = h0.H0Observation(cutoff, _fact())
    second = h0.H0Observation(
        cutoff,
        replace(_fact(), current_body_adverse_side="adverse"),
    )
    accumulator = h0._NumericalAccumulator()
    accumulator.observe(first)
    accumulator.observe(second)
    assert (
        accumulator.as_payload()[
            "same_identity_adverse_body_semantic_disagreement_count"
        ]
        == 1
    )
    inputs = _minimal_report_inputs(accumulator)
    report = h0.build_report(**inputs)
    assert report["conclusion"] == "PARAMETER_SENSITIVITY_NUMERICAL_SEMANTICS_BLOCKED"


def test_report_contains_only_descriptive_contract_fields() -> None:
    report = h0.build_report(**_minimal_report_inputs())
    forbidden = {"ranking", "winner", "fitness", "recommendation", "score"}

    def walk(value: object) -> list[str]:
        if isinstance(value, dict):
            return [key for key, child in value.items() if key.lower() in forbidden] + [
                key for child in value.values() for key in walk(child)
            ]
        if isinstance(value, list):
            return [key for child in value for key in walk(child)]
        return []

    assert walk(report) == []
    assert report["holdout"]["results_published"] is False


def test_full_matrix_has_one_serial_call_path_and_exact_call_formula() -> None:
    source = inspect.getsource(h0._run_full_matrix)
    assert "ThreadPoolExecutor" not in source
    assert "multiprocessing" not in source
    streams = _minimal_report_inputs()["streams"]
    assert sum(len(stream.development) for stream in streams) * 15 == 15


def _amended_pilot_records() -> list[dict[str, object]]:
    records = []
    for profile in h0.all_profiles():
        records.append(
            {
                "profile_id": profile.profile_id,
                "timeframe": profile.timeframe,
                "pivot_window": profile.pivot_window,
                "effective_history_bars": profile.effective_history_bars,
                "median_core_call_seconds": (0.005 if profile.is_baseline else 0.060),
                "p90_core_call_seconds": 0.010 if profile.is_baseline else 0.080,
                "max_core_call_seconds": 0.020 if profile.is_baseline else 0.120,
                "peak_process_rss_bytes": 68_000_000,
                "failure_count": 0,
            }
        )
    return records


def test_relative_slowdown_is_descriptive_and_absolute_envelope_passes() -> None:
    records = _amended_pilot_records()
    h0._enforce_pilot_resource_gates(records, 960)
    slow = next(
        record
        for record in records
        if record["median_core_call_seconds"] == pytest.approx(0.060)
    )
    assert slow["median_call_time_ratio_to_baseline"] == pytest.approx(12.0)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("median_core_call_seconds", 0.100001, "median"),
        ("p90_core_call_seconds", 0.150001, "p90"),
        ("max_core_call_seconds", 0.250001, "maximum"),
        ("peak_process_rss_bytes", h0.PILOT_MAX_RSS_BYTES + 1, "RSS"),
        ("failure_count", 1, "failure"),
    ),
)
def test_amended_pilot_absolute_gates_fail_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    records = _amended_pilot_records()
    records[1][field] = value
    with pytest.raises(h0.H0ResourceBlocked, match=message):
        h0._enforce_pilot_resource_gates(records, 960)


def test_amended_pilot_requires_exact_960_calls() -> None:
    with pytest.raises(h0.H0ResourceBlocked, match="960"):
        h0._enforce_pilot_resource_gates(_amended_pilot_records(), 959)


def test_full_matrix_gate_requires_exact_calls_rss_and_zero_failures() -> None:
    resources = {
        "evaluation_count": 69_570,
        "peak_process_rss_bytes": 100_000_000,
        "profile_resources": [{"failure_count": 0} for _ in range(30)],
    }
    h0._enforce_full_matrix_resource_gates(resources, 69_570)
    resources["evaluation_count"] = 69_569
    with pytest.raises(h0.H0ResourceBlocked, match="call count"):
        h0._enforce_full_matrix_resource_gates(resources, 69_570)
    resources["evaluation_count"] = 69_570
    resources["peak_process_rss_bytes"] = h0.PILOT_MAX_RSS_BYTES + 1
    with pytest.raises(h0.H0ResourceBlocked, match="RSS"):
        h0._enforce_full_matrix_resource_gates(resources, 69_570)
    resources["peak_process_rss_bytes"] = 100_000_000
    resources["profile_resources"][0]["failure_count"] = 1
    with pytest.raises(h0.H0ResourceBlocked, match="failure"):
        h0._enforce_full_matrix_resource_gates(resources, 69_570)


def test_prior_artifact_and_primary_n1_authority_chain_authenticates() -> None:
    prior = h0.verify_prior_artifacts()
    assert prior["n1_authority_hashes"]["approval"]["sha256"] == (
        "fdf50eeaa9c49653ec2bde542417ae201bf08f3776c747b43c5116e376c4c5be"
    )
    assert prior["n1_artifact"]["inventory"]["episode_count"] == 2363
