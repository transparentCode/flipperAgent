"""Frozen, prospective utility measurements for the unchanged G1/G4/G5 paths."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from research.trendlines_v4.current_valid_legacy_score_reselection import (
    reselect_side_result,
)
from research.trendlines_v4.legacy_pathfinding_reference import (
    EmittedLine,
    analyze_legacy,
)
from research.trendlines_v4.post_anchor_filter_impact import filter_legacy_result

# fmt: off
HORIZONS = (1, 3, 6, 12)
VARIANTS = ("G1", "G4", "G5")
SIDES = ("support", "resistance")
ROOT = Path(__file__).parents[2]
G0_MANIFEST = ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/manifest.json"
SOURCE_SPECS = (
    ("BTCUSDT", "/Users/kajukatli/projects/KineticAlphaBot/app/trendlines/optimization/results/BTCUSDT_1h_2023-01-01_2026-03-01.csv", (1, 2, 3, 4), "f39bb06beee9e6991840d5c74f453906bfd7a6d68051b3bc04955e819084cf38", 27721),
    ("ETHUSDT", "/Users/kajukatli/projects/KineticAlphaBot/app/trendlines/optimization/results/ETHUSDT_1h_2023-01-01_2026-03-01.csv", (1, 2, 3, 4), "96bc7f72e56a4ad70048a17caaa0013dd9ef854b11e7ba6aafc2681ce21d3e77", 27721),
    ("SOLUSDT", "/Users/kajukatli/projects/KineticAlphaBot/app/trendlines/optimization/results/SOLUSDT_1h_2023-01-01_2026-03-01.csv", (1, 2, 3, 4), "0711849c9e665c8b5bdba85ffee4cda0eb16f9aa30f7b74678bf09d17bf19c46", 27721),
    ("HYPEUSDT", "/Users/kajukatli/projects/KineticAlphaBot/app/trendlines/optimization/results/HYPEUSDT_1h_2022-01-01_2026-03-01.csv", (1, 2, 3), "26e7f4276c60ea4c4d3dbe196383c1ef63c1c58d6db1b6280b821490d694d050", 6591),
)
PROTECTED = {
    "legacy_reference": (ROOT / "research/trendlines_v4/legacy_pathfinding_reference.py", "29fcee61805265c75f4d436085511bb9764885faf582ee8bed789445ea5dfcca"),
    "g0_manifest": (G0_MANIFEST, "77992577e0bb40fa6bd6773630989632a1fa7e896c43bde48853f6af7e1a6b91"),
    "g0_baseline": (ROOT / "artifacts/trendlines_v4/g0_legacy_corpus_v1/baseline.json", "e164ba3867ed9666d90744529f400686fd56374dd1ec51c94fe4ec79c266a9ca"),
    "g2_source": (ROOT / "research/trendlines_v4/causal_semantics_audit.py", "168dfbc56202698465c0fe852a70ecc555caff6672dbc73da77d533e6518e90a"),
    "g2_report": (ROOT / "artifacts/trendlines_v4/g2_causal_audit_v1/report.json", "9dedb3a4abcb10e002b29176beff4265de5c926bb0f64fdad451d92e67d7bee2"),
    "g3_source": (ROOT / "research/trendlines_v4/post_anchor_validity_audit.py", "def469a83b2c8aed608404ac366ab37cf72fb0d22554491fdabe20fb3fa9d169"),
    "g3_report": (ROOT / "artifacts/trendlines_v4/g3_post_anchor_validity_audit_v1/report.json", "4da943314936f6a962c315ba911d88bec7499e0df756090c43aba1ab7a905fba"),
    "g4_source": (ROOT / "research/trendlines_v4/post_anchor_filter_impact.py", "b11942199426e74051378ee774963a0962acca9aab801f1a488b5464ea4cac33"),
    "g5_source": (ROOT / "research/trendlines_v4/current_valid_legacy_score_reselection.py", "32abc73bd20f3f6c3ca27352d674c34e9a74a51bab2defb3c66a76ce56ffe4c6"),
    "g4_report": (ROOT / "artifacts/trendlines_v4/g4_post_anchor_filter_impact_v1/report.json", "26cf4d9b9ea0b359a18bcad1b7a1b0f187c21d0279d694bd53204b810e35b0fe"),
    "g5_report": (ROOT / "artifacts/trendlines_v4/g5_current_valid_legacy_score_reselection_v1/report.json", "674b29790e1085a1807837f956800e6b8e60b0e224a3d367b1e5078529258d89"),
    "external_oracle": (Path("/Users/kajukatli/projects/KineticAlphaBot/app/indicators/path_finding_trendline.py"), "758482545e43a2dbe1a0e239856ae1af02f7a4266e4b968641c56cf614eb4dd1"),
}


@dataclass(frozen=True, slots=True)
class G6Bar:
    open_time: str
    close_time: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class Selection:
    line: EmittedLine | None
    recovered: bool = False
    endpoint_age: int | None = None
    projected_log_distance: float | None = None
    legacy_score: int | None = None


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_protected_hashes() -> dict[str, str]:
    observed = {}
    for name, (path, expected) in PROTECTED.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"protected {name} hash mismatch: {digest}")
        observed[name] = digest
    return observed


def _read_source(path: str | Path) -> tuple[tuple[G6Bar, ...], tuple[bytes, ...]]:
    raw = tuple(Path(path).read_bytes().splitlines())
    if len(raw) < 2:
        raise ValueError("source must contain a header and data")
    rows = csv.DictReader(line.decode("utf-8") for line in raw)
    required = {"open_time", "open", "high", "low", "close", "close_time"}
    if rows.fieldnames is None or not required.issubset(rows.fieldnames):
        raise ValueError("source schema does not contain the frozen OHLC columns")
    bars = tuple(
        G6Bar(row["open_time"], row["close_time"], float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))
        for row in rows
    )
    return bars, raw[1:]


def _g0_ranges(asset: str) -> tuple[tuple[int, int], ...]:
    data = json.loads(G0_MANIFEST.read_text())
    for source in data["sources"]:
        if source["asset"] == asset:
            return tuple((item["start_index"], item["end_index_exclusive"]) for item in source["windows"])
    return ()


def _window_starts(asset: str, row_count: int) -> tuple[int, ...]:
    remainder = row_count - 300
    divisors = (5, 5, 5, 5) if asset != "HYPEUSDT" else (4, 4, 4)
    return tuple(remainder * (index + 1) // divisors[index] for index in range(len(divisors)))


def build_manifest() -> dict[str, object]:
    protected = verify_protected_hashes()
    sources = []
    for asset, path, _, expected_digest, expected_rows in SOURCE_SPECS:
        bars, raw_rows = _read_source(path)
        source_digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if source_digest != expected_digest or len(bars) != expected_rows:
            raise ValueError(f"frozen source mismatch for {asset}")
        windows = []
        for number, start in enumerate(_window_starts(asset, len(bars)), 1):
            end = start + 300
            if any(start < old_end and old_start < end for old_start, old_end in _g0_ranges(asset)):
                raise ValueError(f"G6 window overlaps G0 for {asset}:{number}")
            windows.append({
                "window": number,
                "start_index": start,
                "end_index_exclusive": end,
                "first_open_time": bars[start].open_time,
                "last_close_time": bars[end - 1].close_time,
                "ohlc_input_sha256": hashlib.sha256(b"\n".join(raw_rows[start:end])).hexdigest(),
            })
        sources.append({"asset": asset, "timeframe": "1h", "path": path, "sha256": source_digest, "data_row_count": len(bars), "windows": windows})
    body = {"schema_version": "g6_frozen_utility_benchmark_v1", "selection_rule": {"window_length": 300, "starts": "floor((N-300)/5), floor(2(N-300)/5), floor(3(N-300)/5), floor(4(N-300)/5); HYPE uses quarters", "outcome_blind": True}, "protected_hashes": protected, "g0_non_overlap": True, "sources": sources, "window_count": sum(len(item["windows"]) for item in sources), "row_count": 4500}
    if body["window_count"] != 15:
        raise ValueError("frozen G6 corpus did not produce 15 windows")
    return {**body, "manifest_id": _digest(body)}


def _write_json(payload: dict[str, object], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


write_manifest = _write_json


def _line_value(line: EmittedLine, index: int) -> float:
    return line.slope * index + line.intercept


def _event(line: EmittedLine, bar: G6Bar, index: int, side: str) -> str | None:
    value = _line_value(line, index)
    bottom, top = min(bar.open, bar.close), max(bar.open, bar.close)
    if side == "support":
        if bottom < value:
            return "BODY_BREAK"
        return "WICK_INTERACTION" if bar.low <= value <= bottom else None
    if side == "resistance":
        if top > value:
            return "BODY_BREAK"
        return "WICK_INTERACTION" if top <= value <= bar.high else None
    raise ValueError(f"unknown side: {side}")


def _body_break(line: EmittedLine, bar: G6Bar, index: int, side: str) -> bool:
    value = _line_value(line, index)
    body = min(bar.open, bar.close) if side == "support" else max(bar.open, bar.close)
    return body < value if side == "support" else body > value


def _select_window(bars: Sequence[G6Bar], pivot_window: int) -> dict[str, dict[str, list[Selection]]]:
    selections = {variant: {side: [] for side in SIDES} for variant in VARIANTS}
    for cutoff in range(len(bars)):
        prefix = bars[: cutoff + 1]
        baseline = analyze_legacy(prefix, pivot_window)
        filtered = filter_legacy_result(prefix, baseline)
        for side_result in (baseline.support, baseline.resistance):
            side = side_result.side
            g5 = reselect_side_result(prefix, side_result)
            line = g5.selected_line
            distance = None
            if line is not None:
                projected = _line_value(line, cutoff)
                if projected > 0:
                    distance = abs(math.log(projected / prefix[-1].close))
            selections["G1"][side].append(Selection(side_result.emitted_line))
            selections["G4"][side].append(Selection(getattr(filtered, side).filtered_line))
            selections["G5"][side].append(Selection(line, g5.recovered_by_g5, None if g5.selected_endpoint_index is None else cutoff - g5.selected_endpoint_index, distance, g5.selected_dp_score))
    return selections


def _episodes(bars: Sequence[G6Bar], selections: Sequence[Selection], side: str) -> tuple[list[dict[str, object]], int]:
    episodes: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    previous_key = None
    changes = 0
    for cutoff, selection in enumerate(selections):
        key = None if selection.line is None else (side, selection.line.start_index, selection.line.end_index, selection.line.start_price, selection.line.end_price, selection.line.slope, selection.line.intercept)
        if key != previous_key:
            if current is not None:
                current["end_cutoff"] = cutoff - 1
                current["duration"] = cutoff - current["start_cutoff"]
            current = None
            if key is not None:
                current = {"start_cutoff": cutoff, "end_cutoff": cutoff, "duration": 1, "first_event": None}
                episodes.append(current)
                if previous_key is not None:
                    changes += 1
            previous_key = key
        if current is not None and selection.line is not None and cutoff + 1 < len(bars) and current["first_event"] is None:
            event = _event(selection.line, bars[cutoff + 1], cutoff + 1, side)
            if event is not None:
                current["first_event"] = (event, cutoff + 1, selection.line, selection.recovered)
    if current is not None:
        current["end_cutoff"] = len(selections) - 1
        current["duration"] = len(selections) - current["start_cutoff"]
    return episodes, changes


def _nearest(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _distribution(values: Sequence[float | int]) -> dict[str, object]:
    if not values:
        return {"count": 0, "minimum": None, "median": None, "p90": None, "p95": None, "maximum": None}
    ordered = sorted(values)
    return {"count": len(ordered), "minimum": ordered[0], "median": median(ordered), "p90": _nearest(ordered, .90), "p95": _nearest(ordered, .95), "maximum": ordered[-1]}


def _group_key(asset: str, side: str) -> tuple[tuple[str, str], ...]:
    return ((asset, side), (asset, "combined"), ("combined", side), ("combined", "combined"))


def _structure_summary(records: Sequence[dict[str, object]]) -> dict[str, object]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for record in records:
        for key in _group_key(record["asset"], record["side"]):
            grouped.setdefault(key, []).append(record)
    result = {}
    for (asset, side), items in grouped.items():
        cutoffs = sum(item["cutoffs"] for item in items)
        episodes = [episode for item in items for episode in item["episodes"]]
        first = {name: sum(episode["first_event"][0] == name for episode in episodes if episode["first_event"] is not None) for name in ("WICK_INTERACTION", "BODY_BREAK")}
        first["NO_EVENT_BEFORE_GEOMETRY_CHANGE_OR_END"] = sum(episode["first_event"] is None for episode in episodes)
        result[f"{asset}:{side}"] = {"window_count": len(items), "cutoffs": cutoffs, "available_cutoffs": sum(item["available"] for item in items), "availability_fraction": sum(item["available"] for item in items) / cutoffs, "episode_count": len(episodes), "episodes_per_100_bars": 100 * len(episodes) / cutoffs, "boundary_change_count": sum(item["changes"] for item in items), "boundary_change_frequency": sum(item["changes"] for item in items) / max(1, sum(item["cutoffs"] - 1 for item in items)), "episode_duration": _distribution([episode["duration"] for episode in episodes]), "first_event_counts": first, "first_event_fractions": {name: count / len(episodes) if episodes else 0 for name, count in first.items()}, "time_to_first_event": _distribution([episode["first_event"][1] - episode["start_cutoff"] for episode in episodes if episode["first_event"] is not None])}
    return result


def _diagnostic_summary(items: Sequence[dict[str, object]]) -> dict[str, object]:
    return {"selected_count": len(items), "undefined_log_distance_count": sum(item["distance"] is None for item in items), "endpoint_age_bars": _distribution([item["age"] for item in items]), "projected_line_log_distance": _distribution([item["distance"] for item in items if item["distance"] is not None]), "legacy_dp_score": _distribution([item["score"] for item in items]), "recovered_count": sum(item["recovered"] for item in items), "recovered": _diagnostic_values([item for item in items if item["recovered"]]), "non_recovery": _diagnostic_values([item for item in items if not item["recovered"]])}


def _diagnostic_values(items: Sequence[dict[str, object]]) -> dict[str, object]:
    return {"count": len(items), "undefined_log_distance_count": sum(item["distance"] is None for item in items), "endpoint_age_bars": _distribution([item["age"] for item in items]), "projected_line_log_distance": _distribution([item["distance"] for item in items if item["distance"] is not None]), "legacy_dp_score": _distribution([item["score"] for item in items])}


def _future_outcome(event: dict[str, object], bars: Sequence[G6Bar], drift: dict[int, float]) -> dict[str, object]:
    index, line, side = event["index"], event["line"], event["side"]
    output = {"variant": event["variant"], "asset": event["asset"], "side": side, "recovered": event["recovered"], "horizons": {}}
    direction = 1 if side == "support" else -1
    for horizon in HORIZONS:
        target = index + horizon
        if target >= len(bars):
            output["horizons"][str(horizon)] = {"available": False}
            continue
        raw = math.log(bars[target].close / bars[index].close)
        signed = direction * raw
        future_break = any(_body_break(line, bars[position], position, side) for position in range(index + 1, target + 1))
        item = {"available": True, "signed_return": signed, "signed_excess": direction * (raw - drift[horizon]), "future_body_break": future_break}
        if horizon == 12:
            moves = [(math.log(bar.high / bars[index].close), math.log(bar.low / bars[index].close)) for bar in bars[index + 1 : target + 1]]
            item["mfe"] = max((high if side == "support" else -low) for high, low in moves)
            item["mae"] = min((low if side == "support" else -high) for high, low in moves)
        output["horizons"][str(horizon)] = item
    return output


def _response_summary(outcomes: Sequence[dict[str, object]]) -> dict[str, object]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for item in outcomes:
        for key in _group_key(item["asset"], item["side"]):
            grouped.setdefault(key, []).append(item)
    result = {}
    for (asset, side), items in grouped.items():
        horizons = {}
        for horizon in HORIZONS:
            values = [item["horizons"][str(horizon)] for item in items]
            available = [item for item in values if item["available"]]
            signed = [item["signed_return"] for item in available]
            excess = [item["signed_excess"] for item in available]
            payload = {"total_interactions": len(values), "uncensored_observation_count": len(available), "censored_count": len(values) - len(available), "median_signed_return": median(signed) if signed else None, "positive_signed_return_fraction": sum(value > 0 for value in signed) / len(signed) if signed else None, "median_signed_excess": median(excess) if excess else None, "positive_excess_fraction": sum(value > 0 for value in excess) / len(excess) if excess else None, "future_body_break_count": sum(item["future_body_break"] for item in available), "future_body_break_rate": sum(item["future_body_break"] for item in available) / len(available) if available else None}
            if horizon == 12:
                payload["median_mfe"] = median([item["mfe"] for item in available]) if available else None
                payload["median_mae"] = median([item["mae"] for item in available]) if available else None
            horizons[str(horizon)] = payload
        result[f"{asset}:{side}"] = horizons
    return result


def benchmark(manifest: dict[str, object], pivot_window: int = 3) -> dict[str, object]:
    if manifest.get("manifest_id") != _digest({key: value for key, value in manifest.items() if key != "manifest_id"}):
        raise ValueError("G6 manifest identity mismatch")
    verify_protected_hashes()
    structural, diagnostics, outcomes, inventory = [], [], [], []
    for source in manifest["sources"]:
        bars, raw_rows = _read_source(source["path"])
        if len(bars) != source["data_row_count"] or hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("G6 source changed after manifest freeze")
        for window in source["windows"]:
            start, end = window["start_index"], window["end_index_exclusive"]
            if hashlib.sha256(b"\n".join(raw_rows[start:end])).hexdigest() != window["ohlc_input_sha256"]:
                raise ValueError("G6 window bytes changed after manifest freeze")
            window_bars = bars[start:end]
            drift = {h: median(math.log(window_bars[index + h].close / window_bars[index].close) for index in range(len(window_bars) - h)) for h in HORIZONS}
            selections = _select_window(window_bars, pivot_window)
            window_key = f"{source['asset']}:{window['window']}"
            inventory.append({"window": window_key, "asset": source["asset"], "rows": len(window_bars), "first_open_time": window_bars[0].open_time, "last_close_time": window_bars[-1].close_time})
            for variant in VARIANTS:
                for side in SIDES:
                    selected = selections[variant][side]
                    episodes, changes = _episodes(window_bars, selected, side)
                    structural.append({"asset": source["asset"], "side": side, "variant": variant, "cutoffs": len(selected), "available": sum(item.line is not None for item in selected), "episodes": episodes, "changes": changes})
                    if variant == "G5":
                        diagnostics.extend({"asset": source["asset"], "side": side, "age": item.endpoint_age, "distance": item.projected_log_distance, "score": item.legacy_score, "recovered": item.recovered} for item in selected if item.line is not None)
                    for episode in episodes:
                        first = episode["first_event"]
                        if first is not None and first[0] == "WICK_INTERACTION":
                            _, index, line, recovered = first
                            outcomes.append(_future_outcome({"variant": variant, "asset": source["asset"], "side": side, "index": index, "line": line, "recovered": recovered}, window_bars, drift))
    diagnostic_groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for item in diagnostics:
        for key in _group_key(item["asset"], item["side"]):
            diagnostic_groups.setdefault(key, []).append(item)
    diagnostic_payload = {f"{asset}:{side}": _diagnostic_summary(items) for (asset, side), items in diagnostic_groups.items()}
    body = {"schema_version": "g6_frozen_utility_benchmark_v1", "manifest_id": manifest["manifest_id"], "window_count": len(inventory), "row_count": sum(item["rows"] for item in inventory), "window_inventory": inventory, "structural": {variant: _structure_summary([item for item in structural if item["variant"] == variant]) for variant in VARIANTS}, "g5_selection_diagnostics": diagnostic_payload, "forward_response": {variant: _response_summary([item for item in outcomes if item["variant"] == variant]) for variant in VARIANTS}, "g5_recovery_forward_response": _response_summary([item for item in outcomes if item["variant"] == "G5" and item["recovered"]]), "g5_non_recovery_forward_response": _response_summary([item for item in outcomes if item["variant"] == "G5" and not item["recovered"]]), "drift_definition": "median raw h-bar close log return over every eligible bar in the exact 300-row window", "conclusion": "FROZEN_UTILITY_BENCHMARK_MEASURED"}
    return {**body, "report_id": _digest(body)}


write_report = _write_json


def freeze_and_benchmark(output_dir: str | Path) -> tuple[dict[str, object], dict[str, object]]:
    directory = Path(output_dir)
    manifest = build_manifest()
    write_manifest(manifest, directory / "manifest.json")
    report = benchmark(manifest)
    write_report(report, directory / "report.json")
    return manifest, report


__all__ = ["G6Bar", "benchmark", "build_manifest", "freeze_and_benchmark", "verify_protected_hashes", "write_manifest", "write_report"]
