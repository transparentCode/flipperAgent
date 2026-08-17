"""M3 causal RSI/MACD semantics and evidence regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.decision_app.features.momentum import calculate_macd, calculate_rsi
from libs.features.indicators.momentum.macd import MACD
from libs.features.indicators.momentum.rsi import RSI
from scripts.certify_momentum_features_m3 import (
    CORPUS_LENGTH,
    ROUTES,
    _corpus_series,
    _select_candidate,
    build_certification,
    corpus_identity,
    evaluate_candidate,
    load_repository_market_members,
    measurement_payload_sha256,
    resolve_routes,
)


def _closes(length: int = 120) -> list[float]:
    return [100.0 + (index * 0.35) + ((index % 5) * 0.2) for index in range(length)]


def test_rsi_matches_legacy_batch_on_identical_supplied_history() -> None:
    closes = _closes()
    expected = RSI(14).batch(closes)[-1]
    assert expected is not None
    assert calculate_rsi(closes, period=14) == pytest.approx(float(expected), abs=1e-12)


def test_macd_matches_legacy_batch_on_identical_supplied_history() -> None:
    closes = _closes()
    expected = MACD(12, 26, 9).batch(closes)[-1]
    assert expected is not None
    actual = calculate_macd(
        closes,
        fast_period=12,
        slow_period=26,
        signal_period=9,
    )
    assert actual.line == pytest.approx(float(expected[0]), abs=1e-12)
    assert actual.signal == pytest.approx(float(expected[1]), abs=1e-12)
    assert actual.histogram == pytest.approx(float(expected[2]), abs=1e-12)


@pytest.mark.parametrize("family", sorted(_corpus_series()))
def test_pure_calculators_match_legacy_batch_across_corpus(family: str) -> None:
    closes = _corpus_series()[family]
    expected_rsi = RSI(14).batch(closes)[-1]
    expected_macd = MACD(12, 26, 9).batch(closes)[-1]
    assert expected_rsi is not None
    assert expected_macd is not None
    assert calculate_rsi(closes, period=14) == pytest.approx(
        float(expected_rsi), abs=1e-12
    )
    actual_macd = calculate_macd(
        closes,
        fast_period=12,
        slow_period=26,
        signal_period=9,
    )
    assert actual_macd.line == pytest.approx(float(expected_macd[0]), abs=1e-12)
    assert actual_macd.signal == pytest.approx(float(expected_macd[1]), abs=1e-12)
    assert actual_macd.histogram == pytest.approx(float(expected_macd[2]), abs=1e-12)


@pytest.mark.parametrize(
    "calculator",
    [
        lambda values: calculate_rsi(values, period=14),
        lambda values: calculate_macd(
            values,
            fast_period=12,
            slow_period=26,
            signal_period=9,
        ),
    ],
)
def test_calculators_reject_insufficient_and_nonfinite_history(calculator) -> None:
    with pytest.raises(ValueError):
        calculator([100.0] * 10)
    with pytest.raises(ValueError):
        calculator([100.0, float("nan")] + [100.0] * 50)


def test_future_bars_cannot_change_a_prior_causal_cutoff() -> None:
    closes = _closes()
    cutoff = 80
    prefix = closes[: cutoff + 1]
    future_extended = prefix + [10_000.0, 20_000.0]
    assert calculate_rsi(prefix, period=14) == calculate_rsi(
        future_extended[: cutoff + 1], period=14
    )
    assert calculate_macd(
        prefix, fast_period=12, slow_period=26, signal_period=9
    ) == calculate_macd(
        future_extended[: cutoff + 1],
        fast_period=12,
        slow_period=26,
        signal_period=9,
    )


def test_route_resolution_records_intended_fallback_and_legacy_discrepancy() -> None:
    routes = resolve_routes(Path(__file__).resolve().parents[3])
    assert [(route.asset, route.timeframe) for route in routes] == list(ROUTES)
    assert routes[0].rsi_params == {"period": 14}
    assert routes[0].macd_params == {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
    }
    assert routes[2].rsi_params == {"period": 12}
    assert routes[2].macd_params == routes[0].macd_params
    assert routes[2].legacy_runtime["instantiated"]["MACD"] is None
    assert routes[2].legacy_runtime["discrepancy"]["MACD"]["matches"] is False


def test_repository_market_manifest_is_explicit_and_hash_stable() -> None:
    root = Path(__file__).resolve().parents[3]
    first = load_repository_market_members(root)
    second = load_repository_market_members(root)
    assert [(member.member_id, member.row_count) for member in first] == [
        ("btc_1h_temporal_normalized", 312),
        ("btc_4h_saturating_normalized", 726),
        ("btc_4h_candidate_normalized", 732),
        ("eth_4h_tv_research_input", 3124),
    ]
    assert [member.file_sha256 for member in first] == [
        "763637b593f42923eda67fcb1d7a0ed2bf176b7dc55865f24b72a252ba00bd4f",
        "2be2f31fafef8188cf936326a43cbcc926ac4320a72658ed9977c403a98c1c42",
        "b8590c34400042fe8e38c23ac0d01b8d26916f2b0d5a6bed4f4b51d208d0a150",
        "49359cc6c94919767830ded5a008edf6ed8299663ac9ffe3868546f776c75964",
    ]
    assert [(member.member_id, member.file_sha256) for member in first] == [
        (member.member_id, member.file_sha256) for member in second
    ]
    assert first[0].provenance_class == "canonical_normalized_artifact"
    assert first[-1].provenance_class == "research_input"
    assert all(
        all(
            next_timestamp > timestamp
            for timestamp, next_timestamp in zip(
                member.timestamps, member.timestamps[1:]
            )
        )
        for member in first
    )


def test_corpus_is_deterministic_and_has_all_required_families() -> None:
    first = _corpus_series()
    second = _corpus_series()
    assert first == second
    assert all(len(values) == CORPUS_LENGTH for values in first.values())
    assert corpus_identity(first) == corpus_identity(second)
    assert set(first) == {
        "monotonic_uptrend",
        "monotonic_downtrend",
        "flat_prices",
        "alternating_gains_losses",
        "trend_reversal",
        "volatility_expansion",
        "low_amplitude_oscillation",
        "large_gap_shock",
        "near_threshold",
    }


def test_candidate_metrics_are_causal_and_repeatable() -> None:
    route = resolve_routes(Path(__file__).resolve().parents[3])[0]
    corpus = {"fixture": tuple(_closes(160))}
    horizon = {"rsi_bars": 30, "macd_bars": 68, "multiplier": 2}
    first = evaluate_candidate(
        route,
        corpus,
        candidate_name="bounded_x2",
        horizon=horizon,
    )
    second = evaluate_candidate(
        route,
        corpus,
        candidate_name="bounded_x2",
        horizon=horizon,
    )
    assert first == second
    assert first["eligible_cutoffs"] == 93


def test_candidate_selection_fails_closed_when_semantics_are_not_stable() -> None:
    unstable = {
        "candidate": "minimum_lookback",
        "horizon": {"rsi_bars": 15, "macd_bars": 34, "multiplier": 1},
        "rsi": {"p95_absolute_error": 1.0},
        "macd": {
            "line": {"p95_absolute_error": 1.0},
            "signal": {"p95_absolute_error": 1.0},
            "histogram": {"p95_absolute_error": 1.0},
        },
        "momentum": {
            "direction_disagreements": 1,
            "tradable_neutral_disagreements": 1,
        },
    }
    assert _select_candidate([unstable]) is None


def test_repository_member_eligibility_cannot_be_satisfied_by_synthetic_only() -> None:
    route = resolve_routes(Path(__file__).resolve().parents[3])[0]
    result = evaluate_candidate(
        route,
        {"synthetic": tuple(_closes(160))},
        candidate_name="bounded_x2",
        horizon={"rsi_bars": 30, "macd_bars": 68, "multiplier": 2},
        required_repository_members=("btc_1h_temporal_normalized",),
    )
    assert (
        result["repository_member_eligibility"]["btc_1h_temporal_normalized"][
            "eligible"
        ]
        is False
    )
    assert (
        _select_candidate(
            [result],
            required_repository_members=("btc_1h_temporal_normalized",),
        )
        is None
    )


@pytest.fixture(scope="module")
def certification_artifact() -> dict:
    return build_certification(Path(__file__).resolve().parents[3])


def test_certification_artifact_is_complete_and_fail_closed_for_no_stable_route(
    certification_artifact: dict,
) -> None:
    artifact = certification_artifact
    assert artifact["schema_version"] == 1
    assert artifact["source_sha"] == "e7bce3d5ca2ea46772447cdf003c989124ea1847"
    assert len(artifact["routes"]) == 3
    assert all(len(route["candidate_results"]) == 5 for route in artifact["routes"])
    assert artifact["corpus"]["repository_fixture_used"] is True
    assert len(artifact["corpus"]["repository_members"]) == 4
    assert artifact["recommendation"]["outcome"] == (
        "MOMENTUM_M3_CANONICAL_FEATURE_SEMANTICS_READY_FOR_REVIEW"
    )
    assert artifact["recommendation"]["selected_candidates"] == {
        "BTCUSDT/1h": artifact["routes"][0]["recommended_candidate"],
        "BTCUSDT/4h": artifact["routes"][1]["recommended_candidate"],
        "ETHUSDT/4h": artifact["routes"][2]["recommended_candidate"],
    }
    assert [
        route["recommended_candidate"]["horizon"]["multiplier"]
        for route in artifact["routes"]
    ] == [4, 8, 16]
    assert artifact["legacy_config_resolution_discrepancies"]["ETHUSDT/4h"]
    assert [
        route["legacy_runtime_resolution"]["observed_startup_max_lookback"]
        for route in artifact["routes"]
    ] == [250, 34, 13]
    assert (
        artifact["routes"][2]["observed_startup_restart"]["indicators"]["MACD"][
            "applicable"
        ]
        is False
    )
    assert artifact["barstore_practicality"]["status"] == "PASS"
    assert artifact["barstore_practicality"]["total_retained_bars"] == 952
    assert artifact["deterministic_identity_sha256"]
    assert artifact["measurement_payload_sha256"]


def test_measurement_evidence_is_serializable(certification_artifact: dict) -> None:
    encoded = json.dumps(certification_artifact, sort_keys=True, allow_nan=False)
    assert encoded


def test_measurement_digest_changes_when_evidence_is_tampered(
    certification_artifact: dict,
) -> None:
    original_digest = certification_artifact["measurement_payload_sha256"]
    tampered = json.loads(json.dumps(certification_artifact))
    tampered["routes"][0]["candidate_results"][0]["rsi"]["max_absolute_error"] += 1.0
    assert measurement_payload_sha256(tampered) != original_digest


def test_measurement_digest_covers_repository_member_identity(
    certification_artifact: dict,
) -> None:
    original_digest = certification_artifact["measurement_payload_sha256"]
    tampered = json.loads(json.dumps(certification_artifact))
    tampered["corpus"]["repository_members"][0]["file_sha256"] = "0" * 64
    assert measurement_payload_sha256(tampered) != original_digest


def test_measurement_digest_covers_barstore_practicality(
    certification_artifact: dict,
) -> None:
    original_digest = certification_artifact["measurement_payload_sha256"]
    tampered = json.loads(json.dumps(certification_artifact))
    tampered["barstore_practicality"]["total_retained_bars"] += 1
    assert measurement_payload_sha256(tampered) != original_digest
