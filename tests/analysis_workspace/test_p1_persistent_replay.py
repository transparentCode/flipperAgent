from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.analysis_workspace.p1_persistent_replay import (
    EXPECTED_CUTOFFS,
    EXPECTED_FAMILIES,
    EXPECTED_INPUT_HASHES,
    FAMILY_DEFAULTS,
    OUTPUT_FILES,
    P1ReplayError,
    assert_byte_identical_trees,
    build_once,
    canonical_selected_recipe_ids,
    decode_saved_state,
    initial_selected_recipe_ids,
    load_authenticated_replay,
    recipes_by_family,
    selection_status,
    sha256_file,
    visible_chart_lines,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_ROOT = REPO_ROOT / "artifacts/analysis_capabilities/r5b_final_tvlc_demo_v1"
EXPECTED_OUTPUT_HASHES = {
    "viewer_payloads.json": "039cdb2d2bf813c4acabd50c689831a8ca091a56f8ef918fea8122019b145768",
}


def test_immutable_input_hash_gate_and_two_cutoffs() -> None:
    bundle = load_authenticated_replay(REPLAY_ROOT)
    assert bundle.input_hashes == EXPECTED_INPUT_HASHES
    assert (
        tuple(payload["market_as_of"] for payload in bundle.payloads)
        == EXPECTED_CUTOFFS
    )
    assert len(bundle.payloads) == 2
    assert len(bundle.replay_audit_rows) == 2


def test_exact_seven_families_and_candidate_to_recipe_completeness() -> None:
    bundle = load_authenticated_replay(REPLAY_ROOT)
    for payload in bundle.payloads:
        family_groups = recipes_by_family(payload)
        assert tuple(family_groups) == EXPECTED_FAMILIES
        assert {family for family, ids in family_groups.items() if ids} == set(
            EXPECTED_FAMILIES
        )
        assert sum(len(ids) for ids in family_groups.values()) == 16
        assert len(visible_chart_lines(payload, ())) == 0
        assert (
            len(visible_chart_lines(payload, initial_selected_recipe_ids(payload))) > 0
        )


def test_recipe_ids_persist_across_cutoffs() -> None:
    bundle = load_authenticated_replay(REPLAY_ROOT)
    first = recipes_by_family(bundle.payloads[0])
    second = recipes_by_family(bundle.payloads[1])
    for family in EXPECTED_FAMILIES:
        assert set(first[family]) & set(second[family])
    assert set(first["ta.anchored_vwap_path"]) == set(second["ta.anchored_vwap_path"])
    assert set(first["ta.fibonacci_geometry"]) == set(second["ta.fibonacci_geometry"])


def test_accepted_defaults_select_only_initially_on_families() -> None:
    bundle = load_authenticated_replay(REPLAY_ROOT)
    selected = set(initial_selected_recipe_ids(bundle.payloads[0]))
    assert len(selected) == 10
    for row in bundle.payloads[0]["candidate_audit"]:
        expected = FAMILY_DEFAULTS[row["capability_id"]]
        assert (row["recipe_id"] in selected) is expected


def test_state_is_unique_sorted_and_minimal() -> None:
    assert canonical_selected_recipe_ids(["z", "a", "z", "m"]) == ("a", "m", "z")
    series = {
        "asset": "BTCUSDT",
        "venue": "binance",
        "instrument_id": "BTC-USDT-PERP",
        "timeframe": "1h",
    }
    state = {
        "schema_revision": "analysis-workspace-p1.v1",
        "series": series,
        "selected_recipe_ids": ["z", "a", "z"],
    }
    selected, note = decode_saved_state(state, series=series)
    assert selected == ("a", "z")
    assert note is None


@pytest.mark.parametrize(
    "raw, expected_note",
    [
        ("not-a-mapping", "valid workspace object"),
        (
            {"schema_revision": "old", "series": {}, "selected_recipe_ids": []},
            "different schema",
        ),
        (
            {
                "schema_revision": "analysis-workspace-p1.v1",
                "series": {"asset": "ETHUSDT"},
                "selected_recipe_ids": [],
            },
            "different series",
        ),
        (
            {
                "schema_revision": "analysis-workspace-p1.v1",
                "series": {
                    "asset": "BTCUSDT",
                    "venue": "binance",
                    "instrument_id": "BTC-USDT-PERP",
                    "timeframe": "1h",
                },
                "selected_recipe_ids": [3],
            },
            "invalid recipe IDs",
        ),
    ],
)
def test_malformed_or_wrong_series_state_falls_back(
    raw: object, expected_note: str
) -> None:
    series = {
        "asset": "BTCUSDT",
        "venue": "binance",
        "instrument_id": "BTC-USDT-PERP",
        "timeframe": "1h",
    }
    selected, note = decode_saved_state(raw, series=series)
    assert selected is None
    assert note is not None and expected_note in note


def test_synthetic_unavailable_recipe_has_no_substitution() -> None:
    bundle = load_authenticated_replay(REPLAY_ROOT)
    payload = json.loads(json.dumps(bundle.payloads[0]))
    absent_recipe = "synthetic-absent-recipe"
    selected = {absent_recipe}
    assert visible_chart_lines(payload, selected) == ()
    assert not any(row["selected"] for row in selection_status(payload, selected))
    synthetic_status = list(selection_status(payload, ()))
    assert all(row["candidate_id"] for row in synthetic_status)


def test_p1_copies_viewer_payload_byte_exact(tmp_path: Path) -> None:
    summary = build_once(tmp_path / "one")
    copied = tmp_path / "one" / "viewer_payloads.json"
    assert sha256_file(copied) == EXPECTED_OUTPUT_HASHES["viewer_payloads.json"]
    assert copied.read_bytes() == (REPLAY_ROOT / "viewer_payloads.json").read_bytes()
    assert (
        summary.output_hashes["viewer_payloads.json"]
        == EXPECTED_OUTPUT_HASHES["viewer_payloads.json"]
    )


def test_two_offline_builds_are_byte_identical(tmp_path: Path) -> None:
    first = build_once(tmp_path / "first")
    second = build_once(tmp_path / "second")
    assert_byte_identical_trees(first.output_root, second.output_root)
    assert first.manifest_id == second.manifest_id
    assert set(first.output_hashes) == set(OUTPUT_FILES)


def test_output_manifest_binds_inventory_and_forbidden_semantics(
    tmp_path: Path,
) -> None:
    summary = build_once(tmp_path / "one")
    root = summary.output_root
    assert tuple(sorted(path.name for path in root.iterdir())) == tuple(
        sorted(OUTPUT_FILES)
    )
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["candidate_id_persisted_as_identity"] is False
    assert manifest["persistent_state_fields"] == [
        "schema_revision",
        "series",
        "selected_recipe_ids",
    ]
    assert manifest["viewer_payload_copied_byte_exact"] is True
    html = (root / "viewer.html").read_text()
    assert "ANALYSIS SHADOW — NOT A TRADING SIGNAL" in html
    for forbidden in (
        "BUY",
        "SELL",
        "confidence",
        "expected return",
        "alpha",
        "prediction",
        "forecast",
    ):
        assert forbidden.lower() not in html.lower()


def test_viewer_contains_recipe_identity_and_navigation_contract(
    tmp_path: Path,
) -> None:
    build_once(tmp_path / "one")
    html = (tmp_path / "one" / "viewer.html").read_text()
    for text in (
        "selected_recipe_ids",
        "recipe_id",
        "candidate_id",
        "unavailable at this cutoff",
        "Reset selections",
        "localStorage",
        "Previous",
        "Next",
        "ta.anchored_vwap_path",
        "ta.fibonacci_geometry",
        "Lightweight Charts 5.2.1",
    ):
        assert text in html


def test_generated_schema_revision_is_single_json_string_literal(
    tmp_path: Path,
) -> None:
    build_once(tmp_path / "one")
    html = (tmp_path / "one" / "viewer.html").read_text()
    assert 'const schemaRevision = "analysis-workspace-p1.v1";' in html
    assert 'const schemaRevision = ""analysis-workspace-p1.v1"";' not in html


def test_bad_payload_hash_fails_closed(tmp_path: Path) -> None:
    altered = tmp_path / "replay"
    shutil_source = REPLAY_ROOT
    altered.mkdir()
    for path in shutil_source.iterdir():
        (altered / path.name).write_bytes(path.read_bytes())
    payload = altered / "viewer_payloads.json"
    payload.write_bytes(payload.read_bytes() + b"\n")
    with pytest.raises(P1ReplayError, match="immutable replay hash changed"):
        load_authenticated_replay(altered)
