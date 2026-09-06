"""Deterministic, blinded SVG cases for human review of V4 geometry."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from research.trendlines_v4.frozen_utility_benchmark import (
    G6Bar,
    _digest,
    _read_source,
    _select_window,
    verify_protected_hashes,
)

# fmt: off

ROOT = Path(__file__).parents[2]
G6_MANIFEST = ROOT / "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/manifest.json"
G6_SOURCE = ROOT / "research/trendlines_v4/frozen_utility_benchmark.py"
G6_TEST = ROOT / "tests/research/trendlines_v4/test_frozen_utility_benchmark.py"
G6_REPORT = ROOT / "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/report.json"
OUTPUT = ROOT / "artifacts/trendlines_v4/g7_blinded_recovery_geometry_review_v1"
SIDES = ("support", "resistance")
STRATA = (("BTCUSDT", "support"), ("BTCUSDT", "resistance"), ("ETHUSDT", "support"), ("ETHUSDT", "resistance"), ("SOLUSDT", "support"), ("SOLUSDT", "resistance"), ("HYPEUSDT", "support"), ("HYPEUSDT", "resistance"))
_LOCKS = {
    G6_SOURCE: "11968e43ef5d8e40558f4b18e57a42bc51e4230a313f5916c8ab3b5092964949",
    G6_TEST: "90c4c9833f21387926ad90a6ab13125ba435fd396e507ddb0de7e171b4499789",
    G6_MANIFEST: "318f3e5b533ce45227452a12a3a84f9ae5bf03a90261371ed97c6ae0ef0bcd6b",
    G6_REPORT: "5aae0e57d2d9adbeb4294c9a57e6567fdc121f3f4c7b4d49870bcb12c29ea825",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_inputs(manifest: dict[str, object]) -> None:
    verify_protected_hashes()
    for path, expected in _LOCKS.items():
        if _sha(path) != expected:
            raise ValueError(f"G7 frozen hash mismatch: {path}")
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != _digest(body):
        raise ValueError("G6 manifest identity mismatch")


def _windows(manifest: dict[str, object]) -> list[tuple[str, dict[str, object], tuple[G6Bar, ...]]]:
    result = []
    for source in manifest["sources"]:
        bars, raw_rows = _read_source(source["path"])
        if len(bars) != source["data_row_count"] or _sha(Path(source["path"])) != source["sha256"]:
            raise ValueError(f"G7 source changed: {source['asset']}")
        for window in source["windows"]:
            start, end = window["start_index"], window["end_index_exclusive"]
            if hashlib.sha256(b"\n".join(raw_rows[start:end])).hexdigest() != window["ohlc_input_sha256"]:
                raise ValueError(f"G7 window changed: {source['asset']}:{window['window']}")
            result.append((source["asset"], window, bars[start:end]))
    return result


def _recoveries(manifest: dict[str, object]) -> dict[tuple[str, str], list[dict[str, object]]]:
    groups = {key: [] for key in STRATA}
    for asset, window, bars in _windows(manifest):
        selections = _select_window(bars, 3)
        for cutoff in range(len(bars)):
            for side in SIDES:
                g4, g5 = selections["G4"][side][cutoff], selections["G5"][side][cutoff]
                if g4.line is None and g5.line is not None:
                    groups[(asset, side)].append({"asset": asset, "side": side, "window": window, "bars": bars, "cutoff": cutoff, "lines": {"G1": selections["G1"][side][cutoff].line, "G4": g4.line, "G5": g5.line}})
    return groups


def select_cases(manifest: dict[str, object]) -> list[dict[str, object]]:
    verify_frozen_inputs(manifest)
    groups = _recoveries(manifest)
    cases = []
    for number, key in enumerate(STRATA, 1):
        candidates = groups[key]
        if not candidates:
            raise ValueError(f"no G5 recovery for {key[0]} {key[1]}")
        ordinal = (len(candidates) - 1) // 2
        item = candidates[ordinal]
        window = item["window"]
        cutoff = item["cutoff"]
        case_id = f"{item['asset']}|{item['side']}|{window['window']}|{cutoff}"
        start = max(0, cutoff + 1 - 120)
        cases.append({"case_number": number, "case_id": case_id, "asset": item["asset"], "side": item["side"], "window": f"{item['asset']}:{window['window']}", "cutoff": cutoff, "timestamp": item["bars"][cutoff].close_time, "candidate_count": len(candidates), "selected_ordinal": ordinal, "visible_bar_start": start, "visible_bar_end": cutoff, "window_source_sha256": window["ohlc_input_sha256"], "bars": item["bars"], "lines": item["lines"]})
    return cases


def _panel_order(case_id: str) -> tuple[str, ...]:
    return tuple(sorted(("G1", "G4", "G5"), key=lambda variant: hashlib.sha256(f"trendlines_v4.g7.panel.v1|{case_id}|{variant}".encode()).hexdigest()))


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _svg(case: dict[str, object]) -> str:
    bars, start, end = case["bars"], case["visible_bar_start"], case["visible_bar_end"]
    visible = bars[start : end + 1]
    low, high = min(bar.low for bar in visible), max(bar.high for bar in visible)
    pad = (high - low) * 0.05 or max(abs(high) * 0.01, 1e-9)
    low, high = low - pad, high + pad
    width, height, panel_width = 1440, 760, 480
    top, bottom = 62, 590
    def y(value: float) -> float:
        return top + (high - value) * (bottom - top) / (high - low)
    def x(index: int, left: float) -> float:
        return left + 30 + (index - start) * 408 / max(1, end - start)
    fragments = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', f'<title>{_esc(case["asset"])} {_esc(case["side"])} geometry review</title>']
    for panel, variant in zip(("A", "B", "C"), _panel_order(case["case_id"])):
        left = (ord(panel) - 65) * panel_width
        line = case["lines"][variant]
        fragments.append(f'<g data-panel="{panel}" data-visible-start="{start}" data-visible-end="{end}" data-y-min="{low!r}" data-y-max="{high!r}"><rect x="{left + 8}" y="8" width="464" height="690" fill="#fff" stroke="#222"/><text x="{left + 20}" y="32" font-family="sans-serif" font-size="18">Panel {panel}</text>')
        fragments.append(f'<text x="{left + 20}" y="50" font-family="sans-serif" font-size="12">{_esc(case["asset"])} · {_esc(case["side"])} · cutoff {case["cutoff"]}</text>')
        for index, bar in enumerate(visible, start):
            cx = x(index, left)
            color = "#16803c" if bar.close >= bar.open else "#b42318"
            body_top, body_bottom = y(max(bar.open, bar.close)), y(min(bar.open, bar.close))
            fragments.append(f'<line x1="{cx:.4f}" x2="{cx:.4f}" y1="{y(bar.high):.4f}" y2="{y(bar.low):.4f}" stroke="{color}"/><rect x="{cx - 1.5:.4f}" y="{body_top:.4f}" width="3" height="{max(1.0, body_bottom - body_top):.4f}" fill="{color}"/>')
        close = bars[end].close
        fragments.append(f'<line x1="{left + 20}" x2="{left + 450}" y1="{y(close):.4f}" y2="{y(close):.4f}" stroke="#555" stroke-dasharray="4 3"/><text x="{left + 20}" y="625" font-family="sans-serif" font-size="12">current close: {_esc(repr(close))}</text>')
        notes = []
        if line is None:
            notes.append("no boundary")
        else:
            line_start, line_end = line.start_index, line.end_index
            fragments.append(f'<line x1="{x(start, left):.4f}" x2="{x(end, left):.4f}" y1="{y(line.slope * start + line.intercept):.4f}" y2="{y(line.slope * end + line.intercept):.4f}" stroke="#075985" stroke-width="2"/>')
            for name, index, price in (("start", line_start, line.start_price), ("end", line_end, line.end_price)):
                if start <= index <= end:
                    fragments.append(f'<circle cx="{x(index, left):.4f}" cy="{y(price):.4f}" r="4" fill="#075985"/><title>{name} anchor</title>')
                else:
                    notes.append(f"anchor {name} outside viewport: index={index} price={price!r}")
            projected = line.projected_value_at_final_bar
            notes.append(f"projected boundary: {projected!r}")
            if not low <= projected <= high:
                notes.append(f"boundary outside visible range: {projected!r}")
            if projected <= 0:
                notes.append(f"non-positive projected boundary: {projected!r}")
        for offset, note in enumerate(notes):
            fragments.append(f'<text x="{left + 20}" y="{650 + 16 * offset}" font-family="sans-serif" font-size="11">{_esc(note)}</text>')
        fragments.append("</g>")
    return "".join(fragments) + "</svg>\n"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def build_review_pack(output_dir: str | Path = OUTPUT) -> dict[str, object]:
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"G7 output already exists: {output}")
    manifest = json.loads(G6_MANIFEST.read_text())
    cases = select_cases(manifest)
    output.mkdir(parents=True)
    public, hidden = [], []
    for case in cases:
        filename = f"case_{case['case_number']:02d}.svg"
        public.append({key: value for key, value in case.items() if key not in ("bars", "lines")})
        hidden.append({"case_id": case["case_id"], "panel_to_variant": dict(zip(("A", "B", "C"), _panel_order(case["case_id"])))})
        (output / filename).write_text(_svg(case))
    public_body = {"schema_version": "g7_blinded_recovery_geometry_review_v1", "case_count": len(public), "cases": public}
    hidden_body = {"schema_version": "g7_hidden_panel_mapping_v1", "case_count": len(hidden), "mappings": hidden}
    public_body["cases_id"] = _digest(public_body)
    hidden_body["mapping_id"] = _digest(hidden_body)
    _write(output / "cases.json", public_body)
    _write(output / "hidden_mapping.json", hidden_body)
    (output / "README.md").write_text("# Blinded Trendline Geometry Review\n\nReview all eight cases before seeking the hidden panel mapping. For each case, record which panel, if any, has the best current geometry; which is stale, irrelevant, structurally wrong, or implausibly extrapolated; whether anchors and the projected line respect the visible body/wick structure; and whether it would help as context or an invalidation/risk reference without assuming predictive power.\n")
    return {"case_count": len(cases), "output_dir": str(output), "cases_id": public_body["cases_id"], "mapping_id": hidden_body["mapping_id"]}


__all__ = ["OUTPUT", "STRATA", "build_review_pack", "select_cases", "verify_frozen_inputs"]
