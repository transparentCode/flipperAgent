from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.analyze_regression_momentum_r3c2 import (
    EXPECTED_ARTIFACT_ROOT,
    EXPECTED_HORIZONS,
    EXPECTED_MEMBER_IDS,
    EXPECTED_REGIONS,
    StudyBlocked,
    _artifact_payload,
    _outcome,
    _verify_artifacts,
    build_replay_graph,
    canonical_json_bytes,
    load_source,
    load_study_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT
    / "research"
    / "regression_r3c"
    / "r3c2_4h_short_overextension_replication_v1.yaml"
)


def test_study_config_is_strict_and_predeclared() -> None:
    config = load_study_config(CONFIG_PATH)
    assert tuple(item.member_id for item in config.members) == EXPECTED_MEMBER_IDS
    assert config.horizons == EXPECTED_HORIZONS
    assert (config.region_a, config.region_b) == EXPECTED_REGIONS
    assert config.output_root == ROOT / EXPECTED_ARTIFACT_ROOT


def test_all_frozen_sources_and_btc_manifests_are_locked() -> None:
    config = load_study_config(CONFIG_PATH)
    sources = {member.member_id: load_source(member) for member in config.members}
    assert {key: len(value.bars) for key, value in sources.items()} == {
        "btc_4h_candidate_normalized": 732,
        "btc_4h_saturating_normalized": 726,
        "eth_4h_tv_research_input": 3124,
    }
    assert sources["btc_4h_candidate_normalized"].input_manifest is not None
    assert sources["btc_4h_saturating_normalized"].input_manifest is not None
    assert sources["eth_4h_tv_research_input"].input_manifest is None


def test_btc_sources_are_complete_and_exactly_four_hourly() -> None:
    config = load_study_config(CONFIG_PATH)
    for member in config.members[:2]:
        source = load_source(member)
        assert all(bar.closed for bar in source.bars)
        assert all(
            current.bar_open_at - previous.bar_open_at == timedelta(hours=4)
            for previous, current in zip(source.bars, source.bars[1:])
        )


def test_eth_uses_datetime_and_is_explicitly_noncanonical() -> None:
    config = load_study_config(CONFIG_PATH)
    source = load_source(config.members[2])
    assert source.spec.provenance_class == "research_input_noncanonical"
    assert source.header[0] == "datetime"
    assert source.ignored_columns == ("timestamp", "open_interest", "funding_rate")
    assert all(bar.taker_buy_base is None for bar in source.bars)


def test_derivative_columns_do_not_enter_decision_bars() -> None:
    config = load_study_config(CONFIG_PATH)
    source = load_source(config.members[2])
    assert all(
        set(bar.__dataclass_fields__)
        == {
            "timeframe",
            "bar_open_at",
            "bar_close_at",
            "market_as_of",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "taker_buy_base",
            "closed",
        }
        for bar in source.bars[:3]
    )


def test_config_rejects_changed_primary_hypothesis(tmp_path: Path) -> None:
    raw = deepcopy(load_study_config(CONFIG_PATH).raw)
    raw["hypothesis"]["region_a"] = "INNER_CHANNEL"
    path = tmp_path / "study.yaml"
    import yaml

    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(StudyBlocked, match="approved A/B contrast"):
        load_study_config(path)


def test_config_rejects_missing_required_root_key(tmp_path: Path) -> None:
    raw = deepcopy(load_study_config(CONFIG_PATH).raw)
    del raw["output"]
    path = tmp_path / "study.yaml"
    import yaml

    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(StudyBlocked, match="study config keys mismatch"):
        load_study_config(path)


def test_exact_outcome_formulas_for_short_direction() -> None:
    from decimal import Decimal

    from libs.contracts.decision import CausalBarView

    bars = tuple(
        CausalBarView(
            timeframe="4h",
            bar_open_at=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=4 * index),
            bar_close_at=datetime(2025, 1, 1, tzinfo=UTC)
            + timedelta(hours=4 * (index + 1)),
            market_as_of=datetime(2025, 1, 1, tzinfo=UTC)
            + timedelta(hours=4 * (index + 1)),
            open=Decimal(str(100 + index)),
            high=Decimal(str(102 + index)),
            low=Decimal(str(98 + index)),
            close=Decimal(str(100 + index)),
            volume=Decimal(10),
            taker_buy_base=None,
            closed=True,
        )
        for index in range(3)
    )
    outcome = _outcome(bars, 0, 2, -1)
    assert outcome["aligned_log_return"] == pytest.approx(-0.01980262729617973)
    assert outcome["favorable_excursion_log"] == pytest.approx(0.010050335853501506)
    assert outcome["adverse_excursion_log"] == pytest.approx(0.03922071315328133)


def test_artifact_verifier_rejects_missing_or_extra_files(tmp_path: Path) -> None:
    output = tmp_path / "study"
    output.mkdir()
    with pytest.raises(StudyBlocked, match="artifact inventory mismatch"):
        _verify_artifacts(output)


def test_canonical_serialization_is_stable() -> None:
    value = {"b": [2, 1], "a": {"z": 3, "y": 4}}
    assert canonical_json_bytes(value) == canonical_json_bytes(
        {"a": {"y": 4, "z": 3}, "b": [2, 1]}
    )


def test_completed_artifacts_have_exact_inventory_if_present() -> None:
    output = ROOT / EXPECTED_ARTIFACT_ROOT
    if not (output / "checksums.json").is_file():
        pytest.skip("R3C2 study has not been executed yet")
    result = _verify_artifacts(output)
    assert result == {"verified": True, "covered_files": 8}


@pytest.mark.parametrize(
    ("member_id", "capacity", "regression_history"),
    (
        ("btc_4h_candidate_normalized", 272, 114),
        ("btc_4h_saturating_normalized", 272, 114),
        ("eth_4h_tv_research_input", 544, 181),
    ),
)
def test_m4_4h_transforms_to_shadow_graph_without_parameter_copy(
    member_id: str,
    capacity: int,
    regression_history: int,
) -> None:
    config = load_study_config(CONFIG_PATH)
    member = next(item for item in config.members if item.member_id == member_id)
    graph = build_replay_graph(config, member)
    assert graph.identity["authority"] == "shadow"
    assert graph.identity["policy"] == {
        "name": "passthrough",
        "version": "1",
        "source_slot": "primary",
    }
    assert graph.identity["execution_order"] == ["primary", "observer"]
    assert graph.identity["compiled_history_capacity"] == capacity
    assert graph.identity["feature_history_requirements"]["REGRESSION_CONTEXT"] == {
        "4h": regression_history
    }
    assert graph.identity["bindings"]["observer"]["parameters_empty"] is True
    assert graph.identity["bindings"]["primary"]["parameters_empty"] is False


def test_actual_observer_execution_is_ordered_real_and_decisionless() -> None:
    async def observe_first_ready() -> tuple[object, object, object]:
        config = load_study_config(CONFIG_PATH)
        member = next(
            item
            for item in config.members
            if item.member_id == "btc_4h_candidate_normalized"
        )
        source = load_source(member)
        graph = build_replay_graph(config, member)
        result = None
        for bar in source.bars[:272]:
            result = await graph.observe(bar)
        assert result is not None
        return graph, result, _artifact_payload(result)

    graph, result, payload = asyncio.run(observe_first_ready())
    assert graph.history_max == 272
    assert result["primary_status"] == result["observer_status"] == "EXECUTED"
    assert result["observer_decision"] is None
    assert payload["provenance"]["momentum_artifact_type"] == "momentum.signal.v1"
    assert (
        payload["provenance"]["momentum_binding_id"]
        == graph.binding_by_slot["primary"].binding_id
    )


def test_primary_metrics_are_short_only_and_use_exact_two_regions() -> None:
    output = ROOT / EXPECTED_ARTIFACT_ROOT
    if not (output / "replication_metrics.json").is_file():
        pytest.skip("R3C2 study has not been executed yet")
    metrics = json.loads(
        (output / "replication_metrics.json").read_text(encoding="utf-8")
    )
    for member in metrics["members"].values():
        assert set(member["primary_short_contrast"]) == {"2", "4", "8", "16"}
        for contrast in member["primary_short_contrast"].values():
            assert set(contrast["regions"]) == set(EXPECTED_REGIONS)
            assert "INNER_CHANNEL" not in contrast["regions"]
        assert set(member["long_negative_control"]) == {"2", "4", "8", "16"}


def test_members_replay_independently_and_eth_is_noncanonical_everywhere() -> None:
    output = ROOT / EXPECTED_ARTIFACT_ROOT
    if not (output / "coverage_summary.json").is_file():
        pytest.skip("R3C2 study has not been executed yet")
    coverage = json.loads(
        (output / "coverage_summary.json").read_text(encoding="utf-8")
    )
    assert (
        coverage["members"]["btc_4h_candidate_normalized"][
            "first_ready_source_row_index"
        ]
        == 271
    )
    assert (
        coverage["members"]["btc_4h_saturating_normalized"][
            "first_ready_source_row_index"
        ]
        == 271
    )
    assert (
        coverage["members"]["eth_4h_tv_research_input"]["first_ready_source_row_index"]
        == 543
    )
    assert (
        coverage["members"]["eth_4h_tv_research_input"]["provenance_class"]
        == "research_input_noncanonical"
    )
    eth_line = (
        (output / "member_observations" / "eth_4h_research.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    eth_identity = json.loads(eth_line)["identity"]
    assert eth_identity["provenance_class"] == "research_input_noncanonical"
    assert eth_identity["canonical_source"] is False


def test_causality_and_no_promotion_status_are_recorded() -> None:
    output = ROOT / EXPECTED_ARTIFACT_ROOT
    if not (output / "coverage_summary.json").is_file():
        pytest.skip("R3C2 study has not been executed yet")
    coverage = json.loads(
        (output / "coverage_summary.json").read_text(encoding="utf-8")
    )
    for probe in coverage["causality"].values():
        assert probe["observation_byte_identical"] is True
        assert probe["future_label_changed"] is True
        assert probe["future_suffix_supplied_before_cutoff"] is False
    summary = (output / "study_summary.md").read_text(encoding="utf-8")
    assert "PROMOTE_FUSION" not in summary
    assert "APPROVED_ALPHA" not in summary


def test_manifest_carries_all_immutable_member_and_fixture_identities() -> None:
    output = ROOT / EXPECTED_ARTIFACT_ROOT
    if not (output / "study_manifest.json").is_file():
        pytest.skip("R3C2 study has not been executed yet")
    manifest = json.loads((output / "study_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["members"]) == set(EXPECTED_MEMBER_IDS)
    assert (
        manifest["members"]["btc_4h_candidate_normalized"]["input_manifest_sha256"]
        == "089d1c743100a0a5591cb615ae453c19992cd3534fe274b8eef91e2af582fc48"
    )
    assert (
        manifest["members"]["eth_4h_tv_research_input"]["provenance_class"]
        == "research_input_noncanonical"
    )
    assert manifest["study_identity"]["m4_fixture_identity"]["global_sha256"]


def test_artifact_hashes_cover_the_manifest_and_all_observation_members() -> None:
    output = ROOT / EXPECTED_ARTIFACT_ROOT
    if not (output / "checksums.json").is_file():
        pytest.skip("R3C2 study has not been executed yet")
    checksums = json.loads((output / "checksums.json").read_text(encoding="utf-8"))
    assert set(checksums["files"]) == {
        "study_manifest.json",
        "source_audit.json",
        "coverage_summary.json",
        "replication_metrics.json",
        "member_observations/btc_4h_candidate.jsonl",
        "member_observations/btc_4h_saturating.jsonl",
        "member_observations/eth_4h_research.jsonl",
        "study_summary.md",
    }
