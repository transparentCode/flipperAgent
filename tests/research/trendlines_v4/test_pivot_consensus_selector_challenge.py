"""Focused tests for the outcome-blind F1B selector challenge."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from libs.models.trendlines_v4.engine.types import TrendlineBar
from research.trendlines_v4 import pivot_consensus_candidate_tape as f1a
from research.trendlines_v4 import pivot_consensus_selector_challenge as f1b


def _bars(count: int = 25) -> tuple[TrendlineBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    support_lows = {4: 10.0, 8: 10.0, 12: 12.0}
    resistance_highs = {4: 50.0, 8: 49.0, 12: 48.0}
    result = []
    for index in range(count):
        low = support_lows.get(index, 15.0 + 0.02 * index)
        high = resistance_highs.get(index, 40.0 - 0.02 * index)
        opening = closing = 25.0
        if index == 8:
            low, high, opening, closing = 10.0, 49.0, 11.0, 11.0
        result.append(
            TrendlineBar(
                closed_at=start + timedelta(hours=index),
                open=opening,
                high=high,
                low=low,
                close=closing,
            )
        )
    return tuple(result)


def _fake(
    name: str,
    span: int,
    evidence_count: int,
    median_residual: float | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id=name,
        anchor_span_bars=span,
        non_anchor_evidence=(object(),) * evidence_count,
        median_non_anchor_nearest_residual_bps=median_residual,
    )


def _synthetic_spec(asset: str) -> f1b.HoldoutSpec:
    bars = _bars()
    return f1b.HoldoutSpec(
        asset=asset,
        timeframe="1h",
        path=f"synthetic/{asset}.csv",
        source_sha256=f"source-{asset}",
        source_row_count=len(bars),
        start_index=0,
        end_index_exclusive=len(bars),
        first_open_time=bars[0].closed_at.isoformat(),
        last_close_time=bars[-1].closed_at.isoformat(),
        ohlc_input_sha256=f"window-{asset}",
        g6_ranges=(),
        bars=bars,
    )


def _fixed_mapping(specs: tuple[f1b.HoldoutSpec, ...]) -> dict[str, object]:
    mappings = []
    for index, case_id in enumerate(f1b._case_ids(specs)):
        if index % 2 == 0:
            panel_to_selector = {"A": "span_first", "B": "consensus_first"}
        else:
            panel_to_selector = {"A": "consensus_first", "B": "span_first"}
        mappings.append({"case_id": case_id, "panel_to_selector": panel_to_selector})
    return {
        "schema_version": f1b.PRIVATE_MAPPING_SCHEMA,
        "case_count": len(mappings),
        "mappings": mappings,
    }


def test_span_first_uses_the_exact_frozen_lexicographic_order() -> None:
    candidates = (
        _fake("narrow-evidence", 8, 1, 0.1),
        _fake("wide-no-evidence", 12, 0, None),
        _fake("wide-high-residual", 12, 1, 3.0),
        _fake("wide-low-residual", 12, 1, 1.0),
    )

    assert f1b.select_span_first(candidates).candidate_id == "wide-low-residual"


def test_consensus_first_prioritizes_evidence_then_residual_then_span() -> None:
    candidates = (
        _fake("wide-no-evidence", 100, 0, None),
        _fake("short-evidence", 10, 1, 2.0),
        _fake("longer-evidence", 20, 1, 2.0),
        _fake("best-evidence", 1, 1, 1.0),
    )

    assert f1b.select_consensus_first(candidates).candidate_id == "best-evidence"


def test_consensus_first_has_deterministic_span_first_no_evidence_fallback() -> None:
    candidates = (_fake("short", 3, 0, None), _fake("long", 9, 0, None))

    assert f1b.select_consensus_first(candidates).candidate_id == "long"
    assert f1b.select_consensus_first(candidates) == f1b.select_span_first(candidates)


def test_selectors_do_not_read_prohibited_quality_fields() -> None:
    class Guarded:
        candidate_id = "guarded"
        anchor_span_bars = 1
        non_anchor_evidence = (object(),)
        median_non_anchor_nearest_residual_bps = 1.0

        def __getattribute__(self, name: str) -> object:
            if name in {
                "body_intersection_count",
                "full_range_intersection_count",
                "slope_per_bar",
                "start_source",
                "end_source",
                "projected_price_at_market_as_of",
            }:
                raise AssertionError(f"selector read prohibited field: {name}")
            return object.__getattribute__(self, name)

    guarded = Guarded()
    assert f1b.select_span_first((guarded,)) is guarded
    assert f1b.select_consensus_first((guarded,)) is guarded


def test_all_four_anchor_modes_remain_eligible() -> None:
    tape = f1a.build_candidate_tape(_bars())

    assert {item.anchor_mode for item in tape.candidates} == set(f1a.ANCHOR_MODES)


def test_selection_is_stable_across_repeated_tapes() -> None:
    first = f1a.build_candidate_tape(_bars())
    second = f1a.build_candidate_tape(_bars())

    for side in f1b.SIDES:
        first_candidates = first.candidates_for_side(side)
        second_candidates = second.candidates_for_side(side)
        assert (
            f1b.select_span_first(first_candidates).candidate_id
            == f1b.select_span_first(second_candidates).candidate_id
        )
        assert (
            f1b.select_consensus_first(first_candidates).candidate_id
            == f1b.select_consensus_first(second_candidates).candidate_id
        )


def test_frozen_inputs_authenticate_exact_authority_chain() -> None:
    observed = f1b.verify_frozen_inputs()

    assert observed["f1b_handoff"] == f1b.F1B_HANDOFF[1]
    assert observed["f1b_design"] == f1b.F1B_DESIGN[1]
    assert observed["f1a_approval"] == f1b.F1A_APPROVAL[1]
    assert observed["g6_manifest"] == f1b.G6_MANIFEST[1]


def test_four_tail_holdouts_are_authenticated_and_exactly_300_rows() -> None:
    holdouts = f1b.build_holdouts()

    assert tuple(item.asset for item in holdouts) == f1b.EXPECTED_ASSETS
    assert all(len(item.bars) == 300 for item in holdouts)
    assert all(item.end_index_exclusive - item.start_index == 300 for item in holdouts)
    assert all(item.g6_ranges for item in holdouts)


def test_tail_holdouts_are_disjoint_from_every_g6_window() -> None:
    for holdout in f1b.build_holdouts():
        for _, start, end in holdout.g6_ranges:
            assert max(holdout.start_index, start) >= min(
                holdout.end_index_exclusive, end
            )


def test_holdout_manifest_identity_is_deterministic() -> None:
    first = [item.as_payload() for item in f1b.build_holdouts()]
    second = [item.as_payload() for item in f1b.build_holdouts()]

    assert first == second
    assert f1b._digest({"sources": first}) == f1b._digest({"sources": second})


def test_candidate_preflight_matches_actual_iteration() -> None:
    bars = _bars()
    by_side = {side: f1a._confirmed_pivots(bars, side) for side in f1b.SIDES}
    preflight = f1a.candidate_cardinality_preflight(
        len(by_side["support"]), len(by_side["resistance"])
    )
    tape = f1a.build_candidate_tape(bars)

    assert len(tape.candidates) == preflight["total_candidate_count"]


def test_future_bars_after_cutoff_do_not_enter_case_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = _bars()
    later = list(_bars(35)[25:])
    later[0] = TrendlineBar(
        closed_at=later[0].closed_at,
        open=30.0,
        high=60.0,
        low=1.0,
        close=30.0,
    )
    observed: list[tuple[TrendlineBar, ...]] = []
    original = f1b.f1a.build_candidate_tape

    def capture(history: tuple[TrendlineBar, ...]) -> f1a.PivotConsensusTape:
        observed.append(tuple(history))
        return original(history)

    monkeypatch.setattr(f1b.f1a, "build_candidate_tape", capture)
    spec = _synthetic_spec("TESTUSDT")
    f1b._case_measurement(spec, 1)

    assert observed == [prefix]
    assert later[0] not in observed[0]


def test_selected_candidates_are_not_observable_before_confirmation() -> None:
    tape = f1a.build_candidate_tape(_bars())
    cutoff = tape.market_as_of

    for side in f1b.SIDES:
        selected = f1b.select_span_first(tape.candidates_for_side(side))
        assert selected.observable_from_at <= cutoff
        assert (
            selected.observable_from_index
            == selected.end_pivot.index + f1a.PIVOT_WINDOW
        )


def test_factual_v4_comparison_is_threshold_free() -> None:
    text = Path(f1b.__file__).read_text()

    assert "quality_score" not in text
    assert "tolerance" not in text
    assert "future_return" not in text
    assert "top_k" not in text
    assert "math.isclose" not in text
    assert "projected_price_difference_bps" in text


def test_synthetic_blind_packet_has_eight_side_cases_and_two_panels() -> None:
    specs = tuple(_synthetic_spec(asset) for asset in f1b.EXPECTED_ASSETS)
    report, blind, mapping = f1b._assemble_packets(
        specs, private_mapping=_fixed_mapping(specs)
    )

    assert report["case_count"] == 8
    assert blind["case_count"] == 8
    assert len(blind["cases"]) == 8
    assert mapping["case_count"] == 8
    assert all(len(case["panels"]) == 2 for case in blind["cases"])
    assert all(case["panels"][0]["label"] == "A" for case in blind["cases"])
    assert all(len(case["candles"]) == 25 for case in blind["cases"])
    assert all(
        "candles" not in panel for case in blind["cases"] for panel in case["panels"]
    )


def test_public_blind_packet_does_not_reveal_selector_mapping_or_residuals() -> None:
    specs = tuple(_synthetic_spec(asset) for asset in f1b.EXPECTED_ASSETS)
    _, blind, _ = f1b._assemble_packets(specs, private_mapping=_fixed_mapping(specs))
    public_text = json.dumps(blind, sort_keys=True).lower()

    assert "span_first" not in public_text
    assert "consensus_first" not in public_text
    assert "mapping" not in public_text
    assert "residual" not in public_text
    assert "future" not in public_text
    assert "return" not in public_text


def test_private_mapping_is_deterministic_after_persistence() -> None:
    specs = tuple(_synthetic_spec(asset) for asset in f1b.EXPECTED_ASSETS)
    fixed = _fixed_mapping(specs)
    first_report, first_blind, first_commitment = f1b._assemble_packets(
        specs, private_mapping=fixed
    )
    second_report, second_blind, second_commitment = f1b._assemble_packets(
        specs, private_mapping=fixed
    )

    assert first_report["hidden_mapping"] == second_report["hidden_mapping"]
    assert first_report["mapping_commitment"] == second_report["mapping_commitment"]
    assert first_blind == second_blind
    assert first_commitment == second_commitment
    assert first_commitment["private_report_sha256"]


def test_private_mapping_loader_reuses_one_csprng_assignment(tmp_path) -> None:
    specs = tuple(_synthetic_spec(asset) for asset in f1b.EXPECTED_ASSETS)
    path = tmp_path / "private-mapping.json"
    first = f1b._load_or_create_private_mapping(f1b._case_ids(specs), path)
    first_bytes = path.read_bytes()
    second = f1b._load_or_create_private_mapping(f1b._case_ids(specs), path)

    assert first == second
    assert path.read_bytes() == first_bytes
    assert f1b._digest(first) == f1b._digest(second)


def test_public_mapping_commitment_has_no_selector_or_mapping_payload() -> None:
    specs = tuple(_synthetic_spec(asset) for asset in f1b.EXPECTED_ASSETS)
    _, _, commitment = f1b._assemble_packets(
        specs, private_mapping=_fixed_mapping(specs)
    )
    public_text = json.dumps(commitment, sort_keys=True).lower()

    assert "span_first" not in public_text
    assert "consensus_first" not in public_text
    assert "panel_to_selector" not in public_text
    assert "hidden_mapping" not in public_text
    assert commitment["private_report_sha256"]


def test_selector_same_geometry_is_factual_private_metadata() -> None:
    specs = tuple(_synthetic_spec(asset) for asset in f1b.EXPECTED_ASSETS)
    report, _, _ = f1b._assemble_packets(specs, private_mapping=_fixed_mapping(specs))

    assert all(
        isinstance(case["selector_same_geometry"], bool) for case in report["cases"]
    )
    assert all(
        isinstance(case["selector_same_candidate"], bool) for case in report["cases"]
    )


def test_generated_html_is_self_contained_and_has_eight_two_panel_cases() -> None:
    specs = tuple(_synthetic_spec(asset) for asset in f1b.EXPECTED_ASSETS)
    _, blind, _ = f1b._assemble_packets(specs, private_mapping=_fixed_mapping(specs))
    rendered = f1b._review_html(blind)

    assert rendered.startswith("<!doctype html>")
    assert rendered.count("data-case-id=") == 8
    assert rendered.count('data-candle-count="300"') == 8
    assert rendered.count('data-panel="A"') == 8
    assert rendered.count('data-panel="B"') == 8
    assert "https://" not in rendered
    assert "localhost" not in rendered


def test_artifact_validation_rejects_tampered_public_packet(tmp_path) -> None:
    files = f1b.build_challenge_payloads()
    assert set(files) == {
        "holdout_manifest.json",
        "blind_cases.json",
        "mapping_commitment.json",
        "blind_review.html",
    }
    output = tmp_path / "f1b"
    output.mkdir()
    for name, content in files.items():
        (output / name).write_bytes(content)
    f1b.validate_artifact_bundle(output)

    blind_path = output / "blind_cases.json"
    blind_path.write_bytes(blind_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        f1b.validate_artifact_bundle(output)


def test_no_production_v4_source_is_part_of_the_f1b_module() -> None:
    source = Path(f1b.__file__).read_text()

    assert "src/libs/models/trendlines_v4" not in source
    assert "decision_plugin" not in source
    assert "configs/" not in source


def test_no_public_case_id_mapping_function_or_hash_assignment_remains() -> None:
    source = Path(f1b.__file__).read_text()

    assert "def _mapping_for_case" not in source
    assert "panel-assignment" not in source
    assert "case_id).hexdigest()" not in source


def test_real_pre_rating_payload_has_exactly_four_public_files() -> None:
    files = f1b.build_challenge_payloads()
    assert set(files) == {
        "holdout_manifest.json",
        "blind_cases.json",
        "mapping_commitment.json",
        "blind_review.html",
    }
    public_text = "\n".join(
        content.decode("utf-8") for content in files.values()
    ).lower()
    for forbidden in (
        "span_first",
        "consensus_first",
        "hidden_mapping",
        "panel_to_selector",
        "selected",
        "median_non_anchor_nearest_residual_bps",
        "best_non_anchor_nearest_residual_bps",
    ):
        assert forbidden not in public_text
