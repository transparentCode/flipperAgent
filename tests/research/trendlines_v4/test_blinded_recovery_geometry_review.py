import json
import re
from pathlib import Path

from research.trendlines_v4 import blinded_recovery_geometry_review as g7
from research.trendlines_v4.frozen_utility_benchmark import G6Bar
from research.trendlines_v4.legacy_pathfinding_reference import EmittedLine


def _bars(count=5):
    return tuple(
        G6Bar(str(index), str(index), 10 + index, 12 + index, 9 + index, 11 + index)
        for index in range(count)
    )


def _case(number=1, lines=None):
    return {
        "case_number": number,
        "case_id": f"ASSET|support|{number}|3",
        "asset": "ASSET",
        "side": "support",
        "window": "ASSET:1",
        "cutoff": 3,
        "timestamp": "3",
        "candidate_count": 3,
        "selected_ordinal": 1,
        "visible_bar_start": 0,
        "visible_bar_end": 3,
        "window_source_sha256": "window-digest",
        "bars": _bars(),
        "lines": lines
        or {
            "G1": EmittedLine(0, 2, 9.5, 11.5, 1.0, 9.5, 12.5),
            "G4": None,
            "G5": EmittedLine(1, 3, 10.5, 12.5, 1.0, 9.5, 12.5),
        },
    }


def test_panel_order_is_deterministic_and_variant_independent() -> None:
    first = g7._panel_order("ASSET|support|1|3")
    second = g7._panel_order("ASSET|support|1|3")
    assert first == second
    assert set(first) == {"G1", "G4", "G5"}


def test_svg_has_shared_candle_view_and_excludes_future_bars() -> None:
    case = _case()
    svg = g7._svg(case)
    future = dict(case, bars=case["bars"] + _bars(1)[-1:])
    assert svg == g7._svg(future)
    groups = re.findall(
        r'<g data-panel="([ABC])" data-visible-start="(\d+)" '
        r'data-visible-end="(\d+)" data-y-min="([^"]+)" data-y-max="([^"]+)"',
        svg,
    )
    assert len(groups) == 3
    assert {item[1:] for item in groups} == {groups[0][1:]}
    assert groups[0][2] == "3"
    assert all(name not in svg for name in ("G1", "G4", "G5"))


def test_selection_uses_the_outcome_blind_middle_recovery(monkeypatch) -> None:
    groups = {}
    for key in g7.STRATA:
        groups[key] = []
        for ordinal in range(3):
            bars = _bars(3)
            groups[key].append(
                {
                    "asset": key[0],
                    "side": key[1],
                    "window": {"window": ordinal + 1, "ohlc_input_sha256": "digest"},
                    "bars": bars,
                    "cutoff": ordinal,
                    "lines": {"G1": None, "G4": None, "G5": None},
                }
            )
    monkeypatch.setattr(g7, "verify_frozen_inputs", lambda manifest: None)
    monkeypatch.setattr(g7, "_recoveries", lambda manifest: groups)
    first = g7.select_cases({"future_outcome": "ignored"})
    second = g7.select_cases({"future_outcome": "changed"})
    assert first == second
    assert len(first) == 8
    assert all(case["selected_ordinal"] == 1 for case in first)
    assert all(case["cutoff"] == 1 for case in first)


def test_frozen_corpus_has_eight_real_middle_recoveries() -> None:
    manifest = json.loads(g7.G6_MANIFEST.read_text())
    cases = g7.select_cases(manifest)
    observed = [
        (
            case["asset"],
            case["side"],
            case["window"],
            case["cutoff"],
            case["candidate_count"],
            case["selected_ordinal"],
        )
        for case in cases
    ]
    assert observed == [
        ("BTCUSDT", "support", "BTCUSDT:2", 232, 427, 213),
        ("BTCUSDT", "resistance", "BTCUSDT:3", 109, 316, 157),
        ("ETHUSDT", "support", "ETHUSDT:2", 106, 386, 192),
        ("ETHUSDT", "resistance", "ETHUSDT:3", 95, 326, 162),
        ("SOLUSDT", "support", "SOLUSDT:2", 245, 518, 258),
        ("SOLUSDT", "resistance", "SOLUSDT:3", 62, 381, 190),
        ("HYPEUSDT", "support", "HYPEUSDT:2", 147, 304, 151),
        ("HYPEUSDT", "resistance", "HYPEUSDT:2", 91, 322, 160),
    ]
    assert all(case["lines"]["G4"] is None for case in cases)
    assert all(case["lines"]["G5"] is not None for case in cases)
    assert all(case["visible_bar_end"] == case["cutoff"] for case in cases)
    assert all(
        case["lines"]["G5"].projected_value_at_final_bar
        == case["lines"]["G5"].slope * case["cutoff"] + case["lines"]["G5"].intercept
        for case in cases
    )


def test_public_pack_is_blinded_and_hidden_mapping_is_complete(
    tmp_path, monkeypatch
) -> None:
    cases = [_case(number) for number in range(1, 9)]
    monkeypatch.setattr(g7, "select_cases", lambda manifest: cases)
    result = g7.build_review_pack(tmp_path / "pack")
    output = Path(result["output_dir"])
    assert result["case_count"] == 8
    assert sorted(path.name for path in output.glob("case_*.svg")) == [
        f"case_{index:02d}.svg" for index in range(1, 9)
    ]
    public_text = "".join(
        path.read_text() for path in (output / "cases.json", output / "README.md")
    ) + "".join(path.read_text() for path in output.glob("case_*.svg"))
    assert all(name not in public_text for name in ("G1", "G4", "G5"))
    metadata = json.loads((output / "cases.json").read_text())
    hidden = json.loads((output / "hidden_mapping.json").read_text())
    assert metadata["case_count"] == 8
    assert hidden["case_count"] == 8
    assert all(
        set(item["panel_to_variant"]) == {"A", "B", "C"} for item in hidden["mappings"]
    )
    assert {
        variant
        for item in hidden["mappings"]
        for variant in item["panel_to_variant"].values()
    } == {"G1", "G4", "G5"}
