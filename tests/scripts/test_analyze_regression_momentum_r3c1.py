from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import yaml

from scripts.analyze_regression_momentum_r3c1 import (
    CONFIG_PATH,
    EXPECTED_ARTIFACT_NAMES,
    EXPECTED_SOURCE_SHA,
    StudyBlocked,
    _causality_probe,
    _conditional_metrics,
    _outcome,
    _run_prefix,
    _summary,
    canonical_json_bytes,
    load_source,
    load_study_config,
    spearman_rho,
    validate_bar_rows,
    verify_artifacts,
)


@pytest.fixture(scope="module")
def study():
    return load_study_config()


@pytest.fixture(scope="module")
def source(study):
    return load_source(study)


def _row(index: int, *, open_time: str | None = None) -> dict[str, str]:
    opened = open_time or f"2022-01-01 {index:02d}:00:00"
    hour = datetime.fromisoformat(opened).replace(tzinfo=UTC) + timedelta(hours=1)
    close_time = hour - timedelta(milliseconds=1)
    return {
        "open_time": opened,
        "open": "100",
        "high": "110",
        "low": "90",
        "close": "105",
        "volume": "10",
        "close_time": close_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "quote_volume": "1",
        "trades": "1",
        "taker_buy_base": "4",
        "taker_buy_quote": "1",
        "ignore": "0",
    }


def _bar(index: int, close: int, high: int, low: int) -> object:
    opened = datetime(2022, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    closed = opened + timedelta(hours=1)
    return {
        "timeframe": "1h",
        "bar_open_at": opened,
        "bar_close_at": closed,
        "market_as_of": closed,
        "open": Decimal(close),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "volume": Decimal(10),
        "taker_buy_base": Decimal(4),
        "closed": True,
    }


def _causal_bar(index: int, close: int, high: int, low: int):
    from libs.contracts.decision import CausalBarView

    return CausalBarView(**_bar(index, close, high, low))


def _record(direction: int, *, region: str = "INNER_CHANNEL") -> dict:
    return {
        "identity": {
            "market_as_of": "2025-01-02T00:00:00Z",
            "bar_open_at": "2025-01-01T23:00:00Z",
            "fold": "holdout",
            "source_row_index": 1,
        },
        "momentum": {
            "direction": direction,
            "conviction": 0.5,
            "score": float(direction),
        },
        "regression": {
            "slope_log_per_hour": 0.1,
            "fit_quality": 0.8,
            "region": region,
            "outer_channel_position": 0.2,
            "outer_width_fraction": 0.3,
            "upper_outer_breach": False,
            "lower_outer_breach": False,
            "previous_region": None,
            "reentered_from_upper_outer": False,
            "reentered_from_lower_outer": False,
        },
        "regression_provenance": {
            "feature_config_fingerprint": "feature",
            "source_config_hash": "30d530f70382",
            "channel_config_hash": "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2",
            "context_id": "structural_channel_location_one_step_v1",
        },
        "outcomes": {
            str(horizon): {
                "forward_log_return": 0.1 * direction,
                "aligned_log_return": None if direction == 0 else 0.1,
                "favorable_excursion_log": None if direction == 0 else 0.2,
                "adverse_excursion_log": None if direction == 0 else 0.05,
                "continuation": None if direction == 0 else True,
            }
            for horizon in (1, 2, 4, 8, 16)
        },
    }


def test_frozen_source_identity_and_coverage(study, source):
    assert study.source_sha256 == EXPECTED_SOURCE_SHA
    assert len(source.bars) == 36481
    assert source.bars[0].bar_open_at == datetime(2022, 1, 1, tzinfo=UTC)
    assert source.bars[-1].bar_open_at == datetime(2026, 3, 1, tzinfo=UTC)
    assert source.bars[-1].bar_close_at == datetime(2026, 3, 1, 1, tzinfo=UTC)


def test_study_config_rejects_unknown_keys(tmp_path):
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(StudyBlocked, match="keys mismatch"):
        load_study_config(path)


def test_source_hash_drift_fails_closed(study):
    drifted = replace(study, source_sha256="0" * 64)
    with pytest.raises(StudyBlocked, match="SHA-256 mismatch"):
        load_source(drifted)


@pytest.mark.parametrize(
    "rows",
    [
        [_row(0), _row(1, open_time="2022-01-01 02:00:00")],
        [_row(0), _row(1, open_time="2022-01-01 00:00:00")],
        [_row(1, open_time="2022-01-01 01:00:00"), _row(0)],
    ],
)
def test_source_timestamp_grid_rejects_gap_duplicate_and_unordered(rows):
    with pytest.raises(StudyBlocked, match="gap, duplicate, or ordering"):
        validate_bar_rows(rows)


def test_exact_long_short_and_neutral_outcomes():
    bars = (
        _causal_bar(0, 100, 100, 100),
        _causal_bar(1, 105, 110, 90),
        _causal_bar(2, 95, 120, 80),
    )
    long = _outcome(bars, 0, 2, 1)
    short = _outcome(bars, 0, 2, -1)
    neutral = _outcome(bars, 0, 2, 0)
    assert long["forward_log_return"] == pytest.approx(math.log(0.95))
    assert long["aligned_log_return"] == pytest.approx(math.log(0.95))
    assert long["favorable_excursion_log"] == pytest.approx(math.log(1.2))
    assert long["adverse_excursion_log"] == pytest.approx(math.log(1.25))
    assert short["aligned_log_return"] == pytest.approx(-math.log(0.95))
    assert short["favorable_excursion_log"] == pytest.approx(math.log(1.25))
    assert short["adverse_excursion_log"] == pytest.approx(math.log(1.2))
    assert neutral["aligned_log_return"] is None
    assert neutral["favorable_excursion_log"] is None
    assert neutral["adverse_excursion_log"] is None
    assert neutral["continuation"] is None


def test_spearman_rejects_non_finite_data():
    with pytest.raises(StudyBlocked, match="non-finite"):
        spearman_rho([1.0, math.inf], [1.0, 2.0])


def test_actual_r3b_graph_prefix_is_causal_and_decisionless(study, source):
    result = asyncio.run(_run_prefix(study, source.bars, 135))
    assert result["history_max"] == 136
    assert result["retained_count"] == 136
    assert result["artifact"]["provenance"]["momentum_artifact_type"] == (
        "momentum.signal.v1"
    )
    assert result["artifact"]["provenance"]["regression_source_config_hash"] == (
        "30d530f70382"
    )


def test_future_suffix_mutation_preserves_observation_and_changes_label(study, source):
    evidence = asyncio.run(_causality_probe(study, source.bars))
    assert evidence["future_ohlcv_mutated_after_cutoff"] is True
    assert evidence["observation_byte_identical"] is True
    assert evidence["future_label_changed"] is True
    assert evidence["original_history_max"] <= 136
    assert evidence["mutated_history_max"] <= 136


def test_momentum_baseline_matches_direct_ledger_aggregation(study):
    rows = [_record(1), _record(-1), _record(0)]
    direct = _summary(rows[:2], 1)
    metrics = _conditional_metrics(rows, study)
    reported = metrics["baseline"]["holdout"]["combined"]["1"]
    assert reported == direct
    assert metrics["baseline"]["holdout"]["long"]["1"]["count"] == 1
    assert metrics["baseline"]["holdout"]["short"]["1"]["count"] == 1


def test_artifact_verifier_detects_tampering(tmp_path):
    for name in EXPECTED_ARTIFACT_NAMES:
        if name != "checksums.json":
            (tmp_path / name).write_bytes(b"stable\n")
    checksums = {
        "algorithm": "sha256",
        "files": {
            name: __import__("hashlib")
            .sha256((tmp_path / name).read_bytes())
            .hexdigest()
            for name in EXPECTED_ARTIFACT_NAMES
            if name != "checksums.json"
        },
    }
    (tmp_path / "checksums.json").write_bytes(canonical_json_bytes(checksums) + b"\n")
    assert verify_artifacts(tmp_path)["verified"] is True
    (tmp_path / "conditional_metrics.json").write_bytes(b"tampered\n")
    with pytest.raises(StudyBlocked, match="checksum mismatch"):
        verify_artifacts(tmp_path)
