from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import analyze_trendline_v2_consensus_corridor_families as study


HOUR_NS = 3_600 * 1_000_000_000


@dataclass(frozen=True)
class CandidateFixture:
    candidate_id: str
    structure_id: str
    role: str = "support"
    availability: int = 16
    first_anchor: str = "first"
    second_anchor: str = "second"
    start_price: float = 100.0
    end_price: float = 100.0

    def as_mapping(self, *, invalid: int | None = None) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_structure_id": self.structure_id,
            "role": self.role,
            "first_anchor_id": self.first_anchor,
            "second_anchor_id": self.second_anchor,
            "source_positions": (5, 10),
            "confirmation_positions": (6, 11),
            "availability_position": self.availability,
            "first_invalid_position": invalid,
            "start_price": self.start_price,
            "end_price": self.end_price,
            "anchor_span_bars": 5,
            "record": {"anchor_span_bars": 5},
        }


def _dataset(*candidates: dict[str, object], n: int = 600) -> SimpleNamespace:
    timestamps = tuple(index * HOUR_NS for index in range(n))
    values = tuple(100.0 for _ in range(n))
    return SimpleNamespace(
        dataset_id="btcusdt_1h",
        asset="BTCUSDT",
        timeframe="1h",
        interval_seconds=3_600,
        timestamps=timestamps,
        opens=values,
        highs=tuple(102.0 for _ in range(n)),
        lows=tuple(98.0 for _ in range(n)),
        closes=values,
        atr=tuple(1.0 for _ in range(n)),
        candidates=tuple(candidates),
        family_membership={},
    )


def _checkpoint(position: int = 40) -> dict[str, object]:
    return {
        "checkpoint_index": 1,
        "checkpoint": study._iso(position * HOUR_NS),
        "checkpoint_ns": position * HOUR_NS,
        "checkpoint_position": position,
        "checkpoint_close": 100.0,
        "checkpoint_atr_14": 1.0,
    }


def _family(
    family_id: str,
    structure_ids: tuple[str, ...],
    *,
    role: str = "support",
    g0: float = 0.0,
    g24: float = 0.0,
    g96: float = 0.0,
) -> dict[str, object]:
    return {
        "family_id": family_id,
        "dataset_id": "btcusdt_1h",
        "timeframe": "1h",
        "role": role,
        "checkpoint_index": 1,
        "checkpoint": "2026-01-01T00:00:00Z",
        "member_structure_ids": list(structure_ids),
        "member_candidate_ids": [f"candidate-{item}" for item in structure_ids],
        "member_count": len(structure_ids),
        "unique_first_anchor_count": 1,
        "unique_second_anchor_count": 1,
        "member_anchor_span_bars": [30] * len(structure_ids),
        "classification": "singleton" if len(structure_ids) == 1 else "pair_consensus",
        "medoid_candidate_id": f"candidate-{structure_ids[0]}",
        "medoid_structure_id": structure_ids[0],
        "g0_median": g0,
        "g24_median": g24,
        "g96_median": g96,
        "g0_minimum": g0,
        "g24_minimum": g24,
        "g96_minimum": g96,
        "g0_maximum": g0,
        "g24_maximum": g24,
        "g96_maximum": g96,
        "envelope_width_t0": 0.0,
        "envelope_width_t24": 0.0,
        "envelope_width_t96": 0.0,
    }


def _cluster_row(
    structure_id: str,
    *,
    role: str = "support",
    g0: float = 0.0,
    g24: float = 0.0,
    g96: float = 0.0,
) -> dict[str, object]:
    return {
        "dataset_id": "btcusdt_1h",
        "timeframe": "1h",
        "checkpoint_index": 1,
        "checkpoint": "2026-01-01T00:00:00Z",
        "role": role,
        "candidate_id": f"candidate-{structure_id}",
        "candidate_structure_id": structure_id,
        "first_anchor_id": f"first-{structure_id}",
        "second_anchor_id": f"second-{structure_id}",
        "anchor_span_bars": 30,
        "g0": g0,
        "g24": g24,
        "g96": g96,
    }


def _minimal_rendered() -> dict[str, dict[str, object]]:
    contract = study._contract({})
    before = {"snapshot_id": "snapshot"}
    binding = study._source_binding(before, before)
    decision_payload = {
        "schema_version": f"{study.STUDY_SCHEMA}_decision_v1",
        "status": "INSUFFICIENT_ACTIVE_STRUCTURE",
        "finalist": None,
        "passing_variants": [],
        "variant_gate_results": [],
        "active_candidate_row_count": 0,
        "family_geometry_row_count": 0,
        "unresolved_evidence_count": 0,
        "reconciliation_count": 0,
        "integrity_issue_count": 0,
        "future_utility_evaluated": False,
        "interpretation": "formation_and_density_compression_only",
    }
    decision = {
        **decision_payload,
        "decision_id": study._identity(study.DECISION_NAMESPACE, decision_payload),
    }
    lock = study._validation_lock(contract, binding, decision["status"])
    empty = {"schema_version": f"{study.STUDY_SCHEMA}_empty_v1", "rows": []}
    return {
        "study_contract.json": contract,
        "source_binding.json": binding,
        "checkpoint_schedule.json": empty,
        "active_candidate_rows.json": empty,
        "family_membership.json": empty,
        "family_geometry.json": empty,
        "temporal_family_links.json": empty,
        "compression_metrics.json": empty,
        "control_comparison.json": empty,
        "validation_lock.json": lock,
        "decision.json": decision,
    }


def test_canonical_json_rejects_duplicate_keys() -> None:
    with pytest.raises(study.StudyError, match="duplicate JSON key"):
        study._load_json_bytes(b'{"a":1,"a":2}')


def test_canonical_json_rejects_nonfinite_constants() -> None:
    with pytest.raises(study.StudyError, match="non-finite"):
        study._load_json_bytes(b'{"value":NaN}')


def test_source_root_allowlist_rejects_alternate_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called = False

    def fail_if_called(_: Path) -> dict[str, object]:
        nonlocal called
        called = True
        raise AssertionError("source loader called")

    monkeypatch.setattr(study.source_loader, "_load_source_manifest", fail_if_called)
    with pytest.raises(study.StudyError, match="alternate source root"):
        study._validate_source(tmp_path)
    assert not called


def test_holdout_dataset_is_outside_allowlist() -> None:
    with pytest.raises(study.source_loader.StudyError, match="outside Q1 validation allowlist"):
        study._load_datasets.__globals__["source_loader"]._load_dataset("suiusdt_1h")


def test_checkpoint_prefix_excludes_checkpoint_bar() -> None:
    dataset = _dataset(n=600)
    schedule = study._checkpoint_schedule(dataset)
    first = schedule[0]
    assert first["checkpoint_position"] == 336
    assert dataset.timestamps[first["checkpoint_position"]] >= first["checkpoint_ns"]
    assert dataset.timestamps[first["checkpoint_position"] - 1] < first["checkpoint_ns"]


def test_support_exact_body_side_accepts_equality() -> None:
    dataset = _dataset(n=80)
    candidate = CandidateFixture("candidate-1", "structure-1").as_mapping()
    assert study._first_invalid_position(dataset, candidate) is None


def test_resistance_exact_body_side_rejects_wrong_side() -> None:
    dataset = _dataset(n=80)
    candidate = CandidateFixture(
        "candidate-1", "structure-1", role="resistance", start_price=100.0, end_price=100.0
    ).as_mapping()
    opens = list(dataset.opens)
    closes = list(dataset.closes)
    opens[20] = closes[20] = 101.0
    dataset = SimpleNamespace(**{**vars(dataset), "opens": tuple(opens), "closes": tuple(closes)})
    assert study._first_invalid_position(dataset, candidate) == 20


def test_active_snapshot_deduplicates_by_role_and_structure() -> None:
    early = CandidateFixture("candidate-early", "structure-1", availability=16).as_mapping()
    late = CandidateFixture("candidate-late", "structure-1", availability=20).as_mapping()
    other = CandidateFixture("candidate-other", "structure-2", availability=16).as_mapping()
    rows, raw_count, role_counts = study._active_snapshot(
        _dataset(early, late, other), _checkpoint(), (early, late, other)
    )
    assert raw_count == 3
    assert role_counts == {"support": 3, "resistance": 0}
    assert [row["candidate_id"] for row in rows] == ["candidate-early", "candidate-other"]


def test_geometry_is_three_causal_normalized_coordinates() -> None:
    candidate = CandidateFixture("candidate-1", "structure-1", start_price=99.0, end_price=101.0).as_mapping()
    rows, _, _ = study._active_snapshot(_dataset(candidate), _checkpoint(), (candidate,))
    assert len((rows[0]["g0"], rows[0]["g24"], rows[0]["g96"])) == 3
    assert rows[0]["g0"] == 13.0


def test_active_row_order_is_input_order_invariant() -> None:
    candidates = tuple(
        CandidateFixture(f"candidate-{index}", f"structure-{index}", start_price=99 + index / 10).as_mapping()
        for index in (1, 2, 3)
    )
    left, _, _ = study._active_snapshot(_dataset(*candidates), _checkpoint(), candidates)
    right, _, _ = study._active_snapshot(_dataset(*reversed(candidates)), _checkpoint(), tuple(reversed(candidates)))
    assert left == right


def test_complete_linkage_is_input_order_invariant() -> None:
    rows = [_cluster_row("a"), _cluster_row("b", g0=0.1, g24=0.1, g96=0.1), _cluster_row("c", g0=2.0, g24=2.0, g96=2.0)]
    assert study._cluster_rows(rows, variant_id="test", max_distance=0.25) == study._cluster_rows(
        list(reversed(rows)), variant_id="test", max_distance=0.25
    )


def test_support_and_resistance_are_clustered_separately() -> None:
    support = _cluster_row("s")
    resistance = _cluster_row("r", role="resistance")
    assert all(row["role"] == "support" for row in study._cluster_rows([support], variant_id="v", max_distance=1.0))
    assert all(row["role"] == "resistance" for row in study._cluster_rows([resistance], variant_id="v", max_distance=1.0))


def test_family_classification_distinguishes_singleton_pair_and_multi_anchor() -> None:
    one = {"first_anchor_id": "a", "second_anchor_id": "b"}
    two = {"first_anchor_id": "a", "second_anchor_id": "b"}
    three = {"first_anchor_id": "c", "second_anchor_id": "d"}
    assert study._family_classification([one]) == "singleton"
    assert study._family_classification([one, two]) == "pair_consensus"
    assert study._family_classification([one, two, three]) == "multi_anchor_consensus"


def test_envelope_overlap_requires_all_coordinates() -> None:
    left = _family("left", ("a",), g0=0.0, g24=0.0, g96=0.0)
    right = _family("right", ("b",), g0=0.0, g24=0.0, g96=1.0)
    assert study._envelope_overlap(left, right) == 0.0


def test_temporal_continuation_uses_primary_score() -> None:
    old = _family("old", ("a",))
    new = _family("new", ("a",))
    events, summary = study._match_family_snapshots([old], [new])
    assert events[0]["event_type"] == "continuation"
    assert summary["continuation_coverage"] == 1.0


def test_temporal_birth_and_death_are_persisted() -> None:
    old = _family("old", ("a",))
    new = _family("new", ("b",), g0=2.0, g24=2.0, g96=2.0)
    events, _ = study._match_family_snapshots([old], [new])
    assert {event["event_type"] for event in events} == {"death", "birth"}


def test_temporal_split_and_merge_diagnostics_are_persisted() -> None:
    old = _family("old", ("a",))
    new_a = _family("new-a", ("a",))
    new_b = _family("new-b", ("b",))
    events, _ = study._match_family_snapshots([old], [new_a, new_b])
    assert "continuation" in {event["event_type"] for event in events}
    assert "split" in {event["event_type"] for event in events}


def test_controls_include_raw_anchor_and_focus_counts() -> None:
    rows = [
        {"candidate_id": "a", "second_anchor_id": "anchor-a", "confirmation_positions": [10, 20], "anchor_span_bars": 30, "role": "support", "availability_position": 10},
        {"candidate_id": "b", "second_anchor_id": "anchor-a", "confirmation_positions": [10, 20], "anchor_span_bars": 30, "role": "support", "availability_position": 11},
    ]
    controls = study._controls(rows, set(), 30)
    assert controls["raw_currently_valid_structure_count"] == 2
    assert controls["one_per_second_anchor_count"] == 1
    assert controls["current_focus_count"] == 1


def test_source_binding_rejects_changed_snapshots() -> None:
    with pytest.raises(study.StudyError, match="source changed"):
        study._source_binding({"snapshot_id": "a"}, {"snapshot_id": "b"})


def test_decision_is_fail_closed_on_assignment_integrity_issue() -> None:
    compression = {"variant_results": [{"variant_id": "v", "gates": {"integrity": True}, "lane_summaries": [], "passes": True}]}
    decision = study._decision(compression, [{"candidate_id": "a"}], [{"family_id": "f"}], [{"variant_id": "v"}])
    assert decision["status"] == "CONSENSUS_CORRIDOR_EVIDENCE_INCOMPLETE"
    assert decision["finalist"] is None


def test_decision_reports_insufficient_active_structure() -> None:
    compression = {"variant_results": []}
    decision = study._decision(compression, [], [], [])
    assert decision["status"] == "INSUFFICIENT_ACTIVE_STRUCTURE"


def test_decision_does_not_select_variant() -> None:
    compression = {"variant_results": [{"variant_id": "v", "gates": {"integrity": True}, "lane_summaries": [], "passes": True}]}
    decision = study._decision(compression, [{"candidate_id": "a"}], [{"family_id": "f"}], [])
    assert decision["finalist"] is None


def test_inventory_and_manifest_are_content_addressed() -> None:
    rendered = _minimal_rendered()
    expected = study._render_bytes(rendered)
    assert len(expected) == 13
    assert expected["manifest.json"]
    assert expected["output_inventory.json"]


def test_bundle_validator_rejects_extra_file(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    expected = study._render_bytes(_minimal_rendered())
    for name, data in expected.items():
        (root / name).write_bytes(data)
    (root / "unexpected.json").write_bytes(b"{}")
    with pytest.raises(study.StudyError, match="output file set"):
        study._validate_bundle_files(root, expected)


def test_bundle_validator_rejects_rebound_member_bytes(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    expected = study._render_bytes(_minimal_rendered())
    for name, data in expected.items():
        (root / name).write_bytes(data)
    decision = root / "decision.json"
    decision.write_bytes(decision.read_bytes().replace(b"INSUFFICIENT", b"NO_STABLE", 1))
    with pytest.raises(study.StudyError, match="output bytes"):
        study._validate_bundle_files(root, expected)


def test_bundle_validator_rejects_noncanonical_member_bytes(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    expected = study._render_bytes(_minimal_rendered())
    for name, data in expected.items():
        (root / name).write_bytes(data)
    contract = root / "study_contract.json"
    contract.write_bytes(b"{\n" + contract.read_bytes() + b"}")
    with pytest.raises(study.StudyError, match="output bytes"):
        study._validate_bundle_files(root, expected)


def test_manifest_member_count_is_twelve_for_thirteen_files(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    study._publish(root, _minimal_rendered())
    manifest = study._load_json(root / "manifest.json")
    assert len(tuple(root.iterdir())) == 13
    assert manifest["member_count"] == 12


def test_publish_is_atomic_from_missing_parent(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "bundle"
    result = study._publish(root, _minimal_rendered())
    assert root.is_dir()
    assert result["member_count"] == 13
    assert not list(root.parent.glob(f".{root.name}.*"))


def test_publish_failure_cleans_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "missing" / "bundle"

    def fail(_: object) -> dict[str, bytes]:
        raise study.StudyError("render failure")

    monkeypatch.setattr(study, "_render_bytes", fail)
    with pytest.raises(study.StudyError, match="render failure"):
        study._publish(root, _minimal_rendered())
    assert not root.exists()
    assert not list(root.parent.glob(f".{root.name}.*"))


def test_execution_guard_precedes_source_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def forbidden() -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise AssertionError("source accessed")

    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE13H1_STUDY", raising=False)
    monkeypatch.setattr(study, "_validate_source", forbidden)
    with pytest.raises(study.StudyError, match="TRENDLINE_V2_ALLOW_PHASE13H1_STUDY"):
        study.execute_study(tmp_path / "output")
    assert calls == 0
    assert not (tmp_path / "output").exists()


def test_output_root_refusal_precedes_source_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    called = False

    def forbidden() -> dict[str, object]:
        nonlocal called
        called = True
        raise AssertionError("source accessed")

    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE13H1_STUDY", "1")
    monkeypatch.setattr(study, "_validate_source", forbidden)
    with pytest.raises(study.StudyError, match="output root already exists"):
        study.execute_study(root)
    assert not called


def test_holdout_and_future_utility_are_not_execution_paths() -> None:
    contract = study._contract({})
    assert contract["holdout_datasets"] == ["suiusdt_1h", "suiusdt_4h"]
    assert contract["future_utility"] == "not_evaluated_in_phase_13h1"
    assert contract["execution"] == {
        "provider_execution_count": 0,
        "network_request_count": 0,
        "legacy_execution_count": 0,
    }
