"""Outcome-blind F1B selectors and a frozen pivot-consensus holdout packet.

This module is research-only.  It consumes the approved F1A candidate tape,
applies exactly two pre-registered selectors, and freezes an eight-case
same-cutoff visual comparison without collecting or interpreting ratings.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from libs.models.trendlines_v4.core_v2 import analyze_trendlines_v2
from libs.models.trendlines_v4.engine.types import Side, TrendlineBar
from research.trendlines_v4 import pivot_consensus_candidate_tape as f1a

ROOT = Path(__file__).parents[2]
PRIMARY_ROOT = Path("/Users/kajukatli/projects/flipperAgent")
SCHEMA_VERSION = "trendlines_v4_f1b_pivot_consensus_selector_challenge_v1"
FAMILY_NAME = "pivot_consensus"
HOLDOUT_LENGTH = 300
SIDES: tuple[Side, ...] = ("support", "resistance")
SELECTOR_IDS = ("span_first", "consensus_first")
OUTPUT_DIR = ROOT / (
    "artifacts/trendlines_v4/f1b_pivot_consensus_selector_challenge_v1"
)
PRIVATE_MAPPING_PATH = ROOT / "plans/.trendlines-v4-f1b-private-mapping-v1.json"
PRIVATE_MAPPING_SCHEMA = "trendlines_v4_f1b_hidden_panel_mapping_v2"
MAPPING_COMMITMENT_SCHEMA = "trendlines_v4_f1b_mapping_commitment_v2"

F1B_HANDOFF = (
    PRIMARY_ROOT
    / "plans/architect-to-coder-trendlines-v4-f1b-selector-visual-challenge-v1.md",
    "421262baf6c0c43475add451c2aa599df0884044673cb17c2d3a77cab575a992",
)
F1B_DESIGN = (
    PRIMARY_ROOT
    / "plans/orchestrator-decision-trendlines-v4-f1b-selector-visual-challenge-design-v1.md",
    "1dc2ba34873204981c05b523679416d625eaa5ca62095125c98f1c34ac89b53b",
)
F1A_APPROVAL = (
    PRIMARY_ROOT
    / "plans/orchestrator-decision-trendlines-v4-f1a-pivot-consensus-approval-v1.md",
    "80cfa9e76a62e4e2caf7e9633d705f815dc497015cf51e7cf497928fbfbe16ad",
)
G6_MANIFEST = (
    ROOT / "artifacts/trendlines_v4/g6_frozen_utility_benchmark_v1/manifest.json",
    "318f3e5b533ce45227452a12a3a84f9ae5bf03a90261371ed97c6ae0ef0bcd6b",
)
F1A_LOCKS = {
    "source": (
        ROOT / "research/trendlines_v4/pivot_consensus_candidate_tape.py",
        "830c7390bdfc53f7bf8e588e27e4c679b12c0d3d90dd6682929bc78b4d5b0423",
    ),
    "test": (
        ROOT / "tests/research/trendlines_v4/test_pivot_consensus_candidate_tape.py",
        "5e8c4f86cf65d32616e6830c986c0ba94c47b97c05ea60352c7323c0f7132952",
    ),
    "manifest": (
        ROOT
        / "artifacts/trendlines_v4/f1a_pivot_consensus_candidate_tape_v1/manifest.json",
        "f3d541aca2d04c551470b0fb9aca7c6446fa82e5ef3e9f590ad4397e724ab736",
    ),
    "report": (
        ROOT
        / "artifacts/trendlines_v4/f1a_pivot_consensus_candidate_tape_v1/report.json",
        "2b210702f9ea67cfe3d5e46bab36fdb3ba05f84ba4491507745e4aead54f0194",
    ),
}
EXPECTED_ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT")


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"missing authenticated file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _verify_lock(name: str, lock: tuple[Path, str]) -> str:
    observed = _sha256(lock[0])
    if observed != lock[1]:
        raise ValueError(f"{name} hash mismatch: {observed}")
    return observed


def verify_frozen_inputs() -> dict[str, str]:
    """Authenticate the F1B/F1A/G6 authority chain before reading holdouts."""

    observed = {
        "f1b_handoff": _verify_lock("F1B handoff", F1B_HANDOFF),
        "f1b_design": _verify_lock("F1B design", F1B_DESIGN),
        "f1a_approval": _verify_lock("F1A approval", F1A_APPROVAL),
        "g6_manifest": _verify_lock("G6 manifest", G6_MANIFEST),
    }
    for name, lock in F1A_LOCKS.items():
        observed[f"f1a_{name}"] = _verify_lock(f"F1A {name}", lock)
    manifest = json.loads(G6_MANIFEST[0].read_text(encoding="utf-8"))
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != _g6_digest(body):
        raise ValueError("G6 manifest identity mismatch")
    return observed


def _g6_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class HoldoutSpec:
    """One source-authenticated 300-row tail holdout."""

    asset: str
    timeframe: str
    path: str
    source_sha256: str
    source_row_count: int
    start_index: int
    end_index_exclusive: int
    first_open_time: str
    last_close_time: str
    ohlc_input_sha256: str
    g6_ranges: tuple[tuple[int, int, int], ...]
    bars: tuple[TrendlineBar, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "path": self.path,
            "source_sha256": self.source_sha256,
            "source_row_count": self.source_row_count,
            "start_index": self.start_index,
            "end_index_exclusive": self.end_index_exclusive,
            "row_count": len(self.bars),
            "first_open_time": self.first_open_time,
            "last_close_time": self.last_close_time,
            "ohlc_input_sha256": self.ohlc_input_sha256,
            "g6_ranges": [
                {
                    "window": number,
                    "start_index": start,
                    "end_index_exclusive": end,
                    "overlap": False,
                }
                for number, start, end in self.g6_ranges
            ],
            "non_overlap_proven": True,
        }


@dataclass(frozen=True, slots=True)
class _V4Line:
    role: str
    side: Side
    start_index: int
    end_index: int
    start_at: str
    end_at: str
    start_price: float
    end_price: float
    slope_per_bar: float
    intercept: float
    projected_price: float
    projection_positive: bool

    def price_at(self, index: int) -> float:
        return self.slope_per_bar * index + self.intercept

    def identity(self) -> tuple[object, ...]:
        return (
            self.side,
            self.start_at,
            self.start_price,
            self.end_at,
            self.end_price,
            self.slope_per_bar,
            self.intercept,
            self.projected_price,
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "role": self.role,
            "side": self.side,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "start_anchor_at": self.start_at,
            "end_anchor_at": self.end_at,
            "start_anchor_price": self.start_price,
            "end_anchor_price": self.end_price,
            "slope_per_bar": self.slope_per_bar,
            "intercept": self.intercept,
            "projected_price": self.projected_price,
            "projection_positive": self.projection_positive,
        }


def _candidate_key_span(candidate: f1a.PivotConsensusCandidate) -> tuple[object, ...]:
    has_evidence = bool(candidate.non_anchor_evidence)
    median_residual = (
        candidate.median_non_anchor_nearest_residual_bps if has_evidence else math.inf
    )
    return (
        -candidate.anchor_span_bars,
        -int(has_evidence),
        median_residual,
        candidate.candidate_id,
    )


def _candidate_key_consensus(
    candidate: f1a.PivotConsensusCandidate,
) -> tuple[object, ...]:
    has_evidence = bool(candidate.non_anchor_evidence)
    median_residual = (
        candidate.median_non_anchor_nearest_residual_bps if has_evidence else math.inf
    )
    return (
        -int(has_evidence),
        median_residual,
        -candidate.anchor_span_bars,
        candidate.candidate_id,
    )


def select_span_first(
    candidates: Sequence[f1a.PivotConsensusCandidate],
) -> f1a.PivotConsensusCandidate:
    """Select S1 using only the frozen span-first lexicographic order."""

    if not candidates:
        raise ValueError("cannot select from an empty candidate set")
    return min(candidates, key=_candidate_key_span)


def select_consensus_first(
    candidates: Sequence[f1a.PivotConsensusCandidate],
) -> f1a.PivotConsensusCandidate:
    """Select S2, with the frozen span-first fallback when evidence is absent."""

    if not candidates:
        raise ValueError("cannot select from an empty candidate set")
    if not any(candidate.non_anchor_evidence for candidate in candidates):
        return select_span_first(candidates)
    return min(candidates, key=_candidate_key_consensus)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed.utcoffset() != UTC.utcoffset(None):
        raise ValueError("source timestamp must be UTC")
    return parsed.astimezone(UTC)


def _bar_from_row(row: dict[str, str]) -> TrendlineBar:
    return TrendlineBar(
        closed_at=_parse_utc(row["close_time"]),
        open=_float(float(row["open"]), "open"),
        high=_float(float(row["high"]), "high"),
        low=_float(float(row["low"]), "low"),
        close=_float(float(row["close"]), "close"),
    )


def _read_source(path: Path) -> tuple[tuple[dict[str, str], ...], tuple[bytes, ...]]:
    raw = tuple(path.read_bytes().splitlines())
    if len(raw) < 2:
        raise ValueError("source must contain a header and rows")
    reader = csv.DictReader(line.decode("utf-8") for line in raw)
    required = {"open_time", "open", "high", "low", "close", "close_time"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("source schema does not contain the frozen OHLC columns")
    return tuple(reader), raw[1:]


def build_holdouts() -> tuple[HoldoutSpec, ...]:
    """Authenticate and load exactly one tail holdout for each frozen asset."""

    verify_frozen_inputs()
    manifest = json.loads(G6_MANIFEST[0].read_text(encoding="utf-8"))
    if tuple(item.get("asset") for item in manifest["sources"]) != EXPECTED_ASSETS:
        raise ValueError("G6 asset order changed")
    result: list[HoldoutSpec] = []
    for source in manifest["sources"]:
        path = Path(source["path"])
        if _sha256(path) != source["sha256"]:
            raise ValueError(f"G6 source hash mismatch: {source['asset']}")
        rows, raw_rows = _read_source(path)
        if len(rows) != source["data_row_count"]:
            raise ValueError(f"G6 source row count mismatch: {source['asset']}")
        start = len(rows) - HOLDOUT_LENGTH
        end = len(rows)
        if start < 0:
            raise ValueError("source is shorter than the required holdout")
        g6_ranges: list[tuple[int, int, int]] = []
        for window in source["windows"]:
            g6_start = int(window["start_index"])
            g6_end = int(window["end_index_exclusive"])
            if max(start, g6_start) < min(end, g6_end):
                raise ValueError(f"F1B holdout overlaps G6: {source['asset']}")
            g6_ranges.append((int(window["window"]), g6_start, g6_end))
        holdout_raw = b"\n".join(raw_rows[start:end])
        bars = tuple(_bar_from_row(row) for row in rows[start:end])
        if len(bars) != HOLDOUT_LENGTH:
            raise ValueError("F1B holdout row count mismatch")
        result.append(
            HoldoutSpec(
                asset=source["asset"],
                timeframe=source["timeframe"],
                path=str(path),
                source_sha256=source["sha256"],
                source_row_count=len(rows),
                start_index=start,
                end_index_exclusive=end,
                first_open_time=rows[start]["open_time"],
                last_close_time=rows[end - 1]["close_time"],
                ohlc_input_sha256=hashlib.sha256(holdout_raw).hexdigest(),
                g6_ranges=tuple(g6_ranges),
                bars=bars,
            )
        )
    if len(result) != len(EXPECTED_ASSETS):
        raise ValueError("F1B holdout inventory is incomplete")
    return tuple(result)


def _v4_line(
    role: str,
    side: Side,
    line: object,
    bars: Sequence[TrendlineBar],
) -> _V4Line | None:
    if line is None:
        return None
    start_at = _timestamp(line.start_anchor_at)
    end_at = _timestamp(line.end_anchor_at)
    index_by_at = {_timestamp(bar.closed_at): index for index, bar in enumerate(bars)}
    if start_at not in index_by_at or end_at not in index_by_at:
        raise ValueError("V4 geometry anchor is outside the causal holdout")
    start_index = index_by_at[start_at]
    end_index = index_by_at[end_at]
    if not 0 <= start_index < end_index < len(bars):
        raise ValueError("V4 geometry anchor ordering is invalid")
    slope = _float(line.slope_per_bar, "V4 slope")
    start_price = _float(line.start_anchor_price, "V4 start price")
    end_price = _float(line.end_anchor_price, "V4 end price")
    intercept = end_price - slope * end_index
    projected = _float(line.projected_price_at_market_as_of, "V4 projection")
    expected_projection = slope * (len(bars) - 1) + intercept
    if projected != expected_projection:
        raise ValueError("V4 projected geometry is not source-consistent")
    return _V4Line(
        role=role,
        side=side,
        start_index=start_index,
        end_index=end_index,
        start_at=start_at,
        end_at=end_at,
        start_price=start_price,
        end_price=end_price,
        slope_per_bar=slope,
        intercept=intercept,
        projected_price=projected,
        projection_positive=bool(line.projection_positive),
    )


def _v4_context(
    snapshot: object, side: Side, bars: Sequence[TrendlineBar]
) -> tuple[_V4Line, ...]:
    side_snapshot = getattr(snapshot, side)
    result: list[_V4Line] = []
    seen: dict[tuple[object, ...], int] = {}
    for role in ("structural", "current_valid", "secondary"):
        item = _v4_line(role, side, getattr(side_snapshot, role), bars)
        if item is None:
            continue
        result_index = seen.get(item.identity())
        if result_index is not None:
            previous = result[result_index]
            result[result_index] = _V4Line(
                role=f"{previous.role}+{role}",
                side=item.side,
                start_index=item.start_index,
                end_index=item.end_index,
                start_at=item.start_at,
                end_at=item.end_at,
                start_price=item.start_price,
                end_price=item.end_price,
                slope_per_bar=item.slope_per_bar,
                intercept=item.intercept,
                projected_price=item.projected_price,
                projection_positive=item.projection_positive,
            )
        else:
            seen[item.identity()] = len(result)
            result.append(item)
    return tuple(result)


def _candidate_facts(candidate: f1a.PivotConsensusCandidate) -> dict[str, object]:
    payload = candidate.as_payload(include_evidence=False)
    payload.update(
        {
            "body_intersection_rate": candidate.body_intersection_count
            / candidate.interaction_bar_count,
            "full_range_intersection_rate": candidate.full_range_intersection_count
            / candidate.interaction_bar_count,
        }
    )
    return payload


def _public_line(candidate: f1a.PivotConsensusCandidate) -> dict[str, object]:
    return {
        "side": candidate.side,
        "start_index": candidate.start_pivot.index,
        "end_index": candidate.end_pivot.index,
        "start_anchor_at": _timestamp(candidate.start_pivot.at),
        "end_anchor_at": _timestamp(candidate.end_pivot.at),
        "start_anchor_price": candidate.start_price,
        "end_anchor_price": candidate.end_price,
        "slope_per_bar": candidate.slope_per_bar,
        "intercept": candidate.intercept,
        "projected_price": candidate.projected_price_at_market_as_of,
        "projection_positive": candidate.projection_positive,
    }


def _public_context(lines: Sequence[_V4Line]) -> list[dict[str, object]]:
    return [
        {
            "role": line.role,
            "start_index": line.start_index,
            "end_index": line.end_index,
            "start_anchor_at": line.start_at,
            "end_anchor_at": line.end_at,
            "start_anchor_price": line.start_price,
            "end_anchor_price": line.end_price,
            "slope_per_bar": line.slope_per_bar,
            "intercept": line.intercept,
            "projected_price": line.projected_price,
            "projection_positive": line.projection_positive,
        }
        for line in lines
    ]


def _candle_payload(bars: Sequence[TrendlineBar]) -> list[dict[str, object]]:
    return [
        {
            "closed_at": _timestamp(bar.closed_at),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
        }
        for bar in bars
    ]


def _compare_candidate_to_v4(
    candidate: f1a.PivotConsensusCandidate, line: _V4Line | None
) -> dict[str, object]:
    if line is None:
        return {
            "present": False,
            "exact_geometry_equal": False,
            "projected_price_difference_bps": None,
            "slope_difference_per_bar": None,
            "anchor_time_equal": {"start": False, "end": False},
            "anchor_time_overlap_count": 0,
        }
    anchor_equal = {
        "start": candidate.start_pivot.at == _parse_utc(line.start_at),
        "end": candidate.end_pivot.at == _parse_utc(line.end_at),
    }
    exact = (
        anchor_equal["start"]
        and anchor_equal["end"]
        and candidate.start_price == line.start_price
        and candidate.end_price == line.end_price
        and candidate.slope_per_bar == line.slope_per_bar
        and candidate.intercept == line.intercept
        and candidate.projected_price_at_market_as_of == line.projected_price
    )
    difference = None
    if (
        candidate.projection_positive
        and line.projection_positive
        and line.projected_price != 0
    ):
        difference = (
            (candidate.projected_price_at_market_as_of - line.projected_price)
            / abs(line.projected_price)
            * 10_000.0
        )
    return {
        "present": True,
        "exact_geometry_equal": exact,
        "projected_price_difference_bps": difference,
        "slope_difference_per_bar": candidate.slope_per_bar - line.slope_per_bar,
        "anchor_time_equal": anchor_equal,
        "anchor_time_overlap_count": sum(anchor_equal.values()),
    }


def _case_measurement(
    spec: HoldoutSpec, case_number: int
) -> tuple[dict[str, object], dict[str, object]]:
    bars = spec.bars
    by_side = {side: f1a._confirmed_pivots(bars, side) for side in SIDES}
    preflight = f1a.candidate_cardinality_preflight(
        len(by_side["support"]), len(by_side["resistance"])
    )
    tape = f1a.build_candidate_tape(bars)
    if len(tape.candidates) != preflight["total_candidate_count"]:
        raise ValueError("F1B candidate preflight did not match enumeration")
    snapshot = analyze_trendlines_v2(bars)
    private: dict[str, object] = {
        "case_number": case_number,
        "case_id": f"{case_number:02d}|{spec.asset}|{spec.timeframe}|tail",
        "asset": spec.asset,
        "timeframe": spec.timeframe,
        "side_results": {},
        "candidate_preflight": preflight,
        "enumerated_candidate_count": len(tape.candidates),
    }
    public: dict[str, object] = {
        "case_number": case_number,
        "case_id": private["case_id"],
        "asset": spec.asset,
        "timeframe": spec.timeframe,
        "side": None,
        "market_as_of": _timestamp(bars[-1].closed_at),
        "candles": _candle_payload(bars),
        "panels": [],
    }
    for side in SIDES:
        candidates = tape.candidates_for_side(side)
        if not candidates:
            raise ValueError(f"no F1A candidates for {spec.asset}:{side}")
        span = select_span_first(candidates)
        consensus = select_consensus_first(candidates)
        if (
            span.observable_from_at > bars[-1].closed_at
            or consensus.observable_from_at > bars[-1].closed_at
        ):
            raise ValueError(
                "selected candidate is not observable at the holdout cutoff"
            )
        context = _v4_context(snapshot, side, bars)
        private_side = {
            "side": side,
            "span_first": _candidate_facts(span),
            "consensus_first": _candidate_facts(consensus),
            "selector_same_candidate": span.candidate_id == consensus.candidate_id,
            "selector_same_geometry": span.geometry_id == consensus.geometry_id,
            "v4_context": [line.as_payload() for line in context],
            "v4_comparison": {
                line.role: {
                    "span_first": _compare_candidate_to_v4(span, line),
                    "consensus_first": _compare_candidate_to_v4(consensus, line),
                }
                for line in context
            },
        }
        private["side_results"][side] = private_side
        # One case is one (asset, side) panel pair; carry a side-specific public case.
        side_public = {
            "case_number": case_number,
            "case_id": f"{case_number:02d}|{spec.asset}|{spec.timeframe}|{side}",
            "asset": spec.asset,
            "timeframe": spec.timeframe,
            "side": side,
            "market_as_of": _timestamp(bars[-1].closed_at),
            "candles": _candle_payload(bars),
            "context_lines": _public_context(context),
            "panels": [],
        }
        # The hidden assignment is injected by _assemble_packets below.
        public["panels"].append(side_public)
    return private, public


def _case_ids(specs: Sequence[HoldoutSpec]) -> tuple[str, ...]:
    return tuple(
        f"{case_number:02d}|{spec.asset}|{spec.timeframe}|{side}"
        for case_number, spec in enumerate(specs, start=1)
        for side in SIDES
    )


def _validate_private_mapping(
    payload: object, case_ids: Sequence[str]
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise TypeError("private F1B mapping must be an object")
    if set(payload) != {"schema_version", "case_count", "mappings"}:
        raise ValueError("private F1B mapping schema mismatch")
    if payload.get("schema_version") != PRIVATE_MAPPING_SCHEMA:
        raise ValueError("private F1B mapping version mismatch")
    if payload.get("case_count") != len(case_ids):
        raise ValueError("private F1B mapping case count mismatch")
    mappings = payload.get("mappings")
    if not isinstance(mappings, list) or len(mappings) != len(case_ids):
        raise ValueError("private F1B mapping inventory mismatch")
    expected_case_ids = tuple(case_ids)
    observed_case_ids: list[str] = []
    for item in mappings:
        if not isinstance(item, dict) or set(item) != {"case_id", "panel_to_selector"}:
            raise ValueError("private F1B mapping entry schema mismatch")
        case_id = item.get("case_id")
        panel_to_selector = item.get("panel_to_selector")
        if not isinstance(case_id, str) or not isinstance(panel_to_selector, dict):
            raise TypeError("private F1B mapping entry types invalid")
        if set(panel_to_selector) != {"A", "B"}:
            raise ValueError("private F1B mapping panels mismatch")
        if set(panel_to_selector.values()) != set(SELECTOR_IDS):
            raise ValueError("private F1B mapping selectors mismatch")
        observed_case_ids.append(case_id)
    if tuple(observed_case_ids) != expected_case_ids:
        raise ValueError("private F1B mapping case order mismatch")
    return payload


def _new_private_mapping(case_ids: Sequence[str]) -> dict[str, object]:
    mappings = []
    for case_id in case_ids:
        if secrets.randbelow(2) == 0:
            panel_to_selector = {"A": SELECTOR_IDS[0], "B": SELECTOR_IDS[1]}
        else:
            panel_to_selector = {"A": SELECTOR_IDS[1], "B": SELECTOR_IDS[0]}
        mappings.append({"case_id": case_id, "panel_to_selector": panel_to_selector})
    return _validate_private_mapping(
        {
            "schema_version": PRIVATE_MAPPING_SCHEMA,
            "case_count": len(case_ids),
            "mappings": mappings,
        },
        case_ids,
    )


def _load_or_create_private_mapping(
    case_ids: Sequence[str], path: Path = PRIVATE_MAPPING_PATH
) -> dict[str, object]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if path.read_bytes() != _canonical_bytes(payload):
            raise ValueError("private F1B mapping is not canonical JSON")
        return _validate_private_mapping(payload, case_ids)
    payload = _new_private_mapping(case_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_bytes(payload))
    os.replace(temporary, path)
    return payload


def _assemble_packets(
    specs: Sequence[HoldoutSpec],
    *,
    private_mapping: dict[str, object],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    case_ids = _case_ids(specs)
    mapping_payload = _validate_private_mapping(private_mapping, case_ids)
    mapping_by_case = {
        item["case_id"]: item["panel_to_selector"]
        for item in mapping_payload["mappings"]
    }
    private_cases: list[dict[str, object]] = []
    public_cases: list[dict[str, object]] = []
    case_number = 0
    for spec in specs:
        private, public = _case_measurement(spec, case_number // 2 + 1)
        for side_public in public["panels"]:
            case_number += 1
            case_id = side_public["case_id"]
            side = side_public["side"]
            private_case = {
                "case_number": case_number,
                "case_id": case_id,
                "asset": spec.asset,
                "timeframe": spec.timeframe,
                "side": side,
                "holdout": spec.as_payload(),
                "candidate_preflight": private["candidate_preflight"],
                "enumerated_candidate_count": private["enumerated_candidate_count"],
                "selector_same_candidate": private["side_results"][side][
                    "selector_same_candidate"
                ],
                "selector_same_geometry": private["side_results"][side][
                    "selector_same_geometry"
                ],
                "selected": {
                    selector: private["side_results"][side][selector]
                    for selector in SELECTOR_IDS
                },
                "v4_context": private["side_results"][side]["v4_context"],
                "v4_comparison": private["side_results"][side]["v4_comparison"],
            }
            mapping = mapping_by_case[case_id]
            public_case = {
                "case_number": case_number,
                "case_id": case_id,
                "asset": side_public["asset"],
                "timeframe": side_public["timeframe"],
                "side": side,
                "market_as_of": side_public["market_as_of"],
                "candles": side_public["candles"],
                "context_lines": side_public["context_lines"],
                "panels": [
                    {
                        "label": panel,
                        "highlighted_line": None,
                    }
                    for panel, selector_candidate in mapping.items()
                ],
            }
            public_cases.append(public_case)
            private_cases.append(private_case)
    if len(public_cases) != 8 or len(private_cases) != 8:
        raise ValueError("F1B must produce exactly eight side cases")
    for public_case, private_case in zip(public_cases, private_cases):
        selected = private_case["selected"]
        for panel in public_case["panels"]:
            selector = mapping_by_case[public_case["case_id"]][panel["label"]]
            facts = selected[selector]
            panel["highlighted_line"] = {
                "side": facts["side"],
                "start_index": facts["start_pivot"]["index"],
                "end_index": facts["end_pivot"]["index"],
                "start_anchor_at": facts["start_pivot"]["at"],
                "end_anchor_at": facts["end_pivot"]["at"],
                "start_anchor_price": facts["start_price"],
                "end_anchor_price": facts["end_price"],
                "slope_per_bar": facts["slope_per_bar"],
                "intercept": facts["intercept"],
                "projected_price": facts["projected_price_at_market_as_of"],
                "projection_positive": facts["projection_positive"],
            }
    mapping_commitment = _digest(mapping_payload)
    blind_base = {
        "schema_version": "trendlines_v4_f1b_blind_cases_v1",
        "case_count": 8,
        "cases": public_cases,
    }
    blind_packet = {**blind_base, "blind_packet_id": _digest(blind_base)}
    report_base = {
        "schema_version": SCHEMA_VERSION,
        "f1b_handoff_sha256": F1B_HANDOFF[1],
        "f1b_design_sha256": F1B_DESIGN[1],
        "f1a_approval_sha256": F1A_APPROVAL[1],
        "g6_manifest_sha256": G6_MANIFEST[1],
        "selector_ids": list(SELECTOR_IDS),
        "selector_definitions": {
            "span_first": "anchor_span desc, evidence_present desc, median_non_anchor_nearest_residual_bps asc, candidate_id asc",
            "consensus_first": "evidence_present desc, median_non_anchor_nearest_residual_bps asc, anchor_span desc, candidate_id asc; span_first fallback when no evidence",
        },
        "holdout_count": len(specs),
        "case_count": 8,
        "blind_packet_id": blind_packet["blind_packet_id"],
        "mapping_commitment": mapping_commitment,
        "hidden_mapping": mapping_payload["mappings"],
        "cases": private_cases,
        "ratings_collected": False,
        "unblinded": False,
        "promotion": None,
    }
    report = {**report_base, "report_id": _digest(report_base)}
    private_report_sha256 = hashlib.sha256(_canonical_bytes(report)).hexdigest()
    mapping_commitment_payload = {
        "schema_version": MAPPING_COMMITMENT_SCHEMA,
        "case_count": 8,
        "blind_packet_id": blind_packet["blind_packet_id"],
        "mapping_commitment": mapping_commitment,
        "private_report_sha256": private_report_sha256,
        "f1b_handoff_sha256": F1B_HANDOFF[1],
        "f1b_design_sha256": F1B_DESIGN[1],
        "f1a_approval_sha256": F1A_APPROVAL[1],
        "g6_manifest_sha256": G6_MANIFEST[1],
    }
    return report, blind_packet, mapping_commitment_payload


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _line_value(line: dict[str, object], index: int) -> float:
    return float(line["slope_per_bar"]) * index + float(line["intercept"])


def _svg_case(case: dict[str, object]) -> str:
    bars = case["candles"]
    context = case["context_lines"]
    all_lines = [*context]
    for panel in case["panels"]:
        all_lines.append(panel["highlighted_line"])
    values = [float(item[key]) for item in bars for key in ("low", "high")]
    for line in all_lines:
        start = int(line["start_index"])
        values.extend(_line_value(line, index) for index in range(start, len(bars)))
    low, high = min(values), max(values)
    pad = (high - low) * 0.05 or max(abs(high) * 0.01, 1e-9)
    low -= pad
    high += pad
    width, panel_width, height = 1480, 720, 560
    top, bottom = 48, 420

    def x(index: int, left: float) -> float:
        return left + 34 + index * (panel_width - 68) / max(1, len(bars) - 1)

    def y(value: float) -> float:
        return top + (high - value) * (bottom - top) / (high - low)

    fragments = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-candle-count="300">',
        f"<title>Case {_esc(case['case_number'])} {_esc(case['asset'])} {_esc(case['side'])}</title>",
    ]
    for panel_index, panel in enumerate(case["panels"]):
        left = panel_index * panel_width
        fragments.append(
            f'<g data-panel="{_esc(panel["label"])}"><rect x="{left + 8}" y="8" width="704" height="515" fill="#fff" stroke="#1f2937"/><text x="{left + 24}" y="30" font-family="sans-serif" font-size="18">Panel {_esc(panel["label"])}</text>'
        )
        for index, bar in enumerate(bars):
            cx = x(index, left)
            color = (
                "#15803d" if float(bar["close"]) >= float(bar["open"]) else "#b91c1c"
            )
            body_top = y(max(float(bar["open"]), float(bar["close"])))
            body_bottom = y(min(float(bar["open"]), float(bar["close"])))
            fragments.append(
                f'<line x1="{cx:.3f}" x2="{cx:.3f}" y1="{y(float(bar["high"])):.3f}" y2="{y(float(bar["low"])):.3f}" stroke="{color}" stroke-width="1"/><rect x="{cx - 1.4:.3f}" y="{body_top:.3f}" width="2.8" height="{max(1.0, body_bottom - body_top):.3f}" fill="{color}"/>'
            )
        for line in context:
            start = int(line["start_index"])
            fragments.append(
                f'<line x1="{x(start, left):.3f}" x2="{x(len(bars) - 1, left):.3f}" y1="{y(_line_value(line, start)):.3f}" y2="{y(_line_value(line, len(bars) - 1)):.3f}" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="5 4"/>'
            )
        line = panel["highlighted_line"]
        start = int(line["start_index"])
        fragments.append(
            f'<line x1="{x(start, left):.3f}" x2="{x(len(bars) - 1, left):.3f}" y1="{y(_line_value(line, start)):.3f}" y2="{y(_line_value(line, len(bars) - 1)):.3f}" stroke="#0f766e" stroke-width="3"/>'
        )
        for name, index, price in (
            ("start", int(line["start_index"]), float(line["start_anchor_price"])),
            ("end", int(line["end_index"]), float(line["end_anchor_price"])),
        ):
            fragments.append(
                f'<circle cx="{x(index, left):.3f}" cy="{y(price):.3f}" r="4" fill="#0f766e"><title>{name} anchor</title></circle>'
            )
        fragments.append(
            f'<text x="{left + 24}" y="452" font-family="sans-serif" font-size="12">{_esc(case["asset"])} · {_esc(case["timeframe"])} · {_esc(case["side"])} · {_esc(case["market_as_of"])}</text></g>'
        )
    return "".join(fragments) + "</svg>\n"


def _review_html(blind_packet: dict[str, object]) -> str:
    fragments = [
        '<!doctype html><html><head><meta charset="utf-8"><title>Trendlines V4 F1B Blind Review</title><style>body{font-family:sans-serif;background:#f3f4f6;color:#111827;margin:24px}section{background:#fff;border:1px solid #d1d5db;margin:0 0 28px;padding:16px}svg{max-width:100%;height:auto}h1{margin-top:0}p{max-width:1000px}</style></head><body>',
        "<h1>Trendlines V4 blind geometry review</h1><p>Review every case before any identity is revealed. For each panel, assess current geometric usefulness, redundancy, structural sense, anchors, and possible context or invalidation use. Record ratings outside this packet.</p>",
    ]
    for case in blind_packet["cases"]:
        fragments.append(
            f'<section data-case-id="{_esc(case["case_id"])}"><h2>Case {_esc(case["case_number"])} · {_esc(case["asset"])} · {_esc(case["timeframe"])} · {_esc(case["side"])}</h2>{_svg_case(case)}</section>'
        )
    fragments.append("</body></html>\n")
    return "".join(fragments)


def build_challenge_payloads() -> dict[str, bytes]:
    """Build the four-file pre-rating bundle without collecting ratings."""

    specs = build_holdouts()
    private_mapping = _load_or_create_private_mapping(_case_ids(specs))
    report, blind_packet, mapping_commitment = _assemble_packets(
        specs, private_mapping=private_mapping
    )
    blind_bytes = _canonical_bytes(blind_packet)
    html_bytes = _review_html(blind_packet).encode("utf-8")
    report_bytes = _canonical_bytes(report)
    mapping_bytes = _canonical_bytes(mapping_commitment)
    artifact_inventory = {
        "blind_cases.json": hashlib.sha256(blind_bytes).hexdigest(),
        "blind_review.html": hashlib.sha256(html_bytes).hexdigest(),
        "mapping_commitment.json": hashlib.sha256(mapping_bytes).hexdigest(),
    }
    manifest_base = {
        "schema_version": "trendlines_v4_f1b_holdout_manifest_v1",
        "f1b_handoff_sha256": F1B_HANDOFF[1],
        "f1b_design_sha256": F1B_DESIGN[1],
        "f1a_approval_sha256": F1A_APPROVAL[1],
        "f1a_locks": {
            name: {"path": str(path), "sha256": expected}
            for name, (path, expected) in F1A_LOCKS.items()
        },
        "g6_manifest_sha256": G6_MANIFEST[1],
        "g6_manifest_id": json.loads(G6_MANIFEST[0].read_text())["manifest_id"],
        "holdout_count": len(specs),
        "holdout_length": HOLDOUT_LENGTH,
        "sources": [spec.as_payload() for spec in specs],
        "case_count": 8,
        "blind_packet_id": blind_packet["blind_packet_id"],
        "mapping_commitment": mapping_commitment["mapping_commitment"],
        "private_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "artifact_inventory": artifact_inventory,
        "ratings_collected": False,
        "unblinded": False,
    }
    manifest = {**manifest_base, "manifest_id": _digest(manifest_base)}
    return {
        "holdout_manifest.json": _canonical_bytes(manifest),
        "blind_cases.json": blind_bytes,
        "mapping_commitment.json": mapping_bytes,
        "blind_review.html": html_bytes,
    }


def validate_artifact_bundle(output_dir: str | Path) -> dict[str, object]:
    """Validate the public pre-rating packet without unblinding it."""

    directory = Path(output_dir)
    expected_names = {
        "holdout_manifest.json",
        "blind_cases.json",
        "mapping_commitment.json",
        "blind_review.html",
    }
    actual_names = {path.name for path in directory.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise ValueError("F1B public artifact inventory mismatch")
    manifest = json.loads((directory / "holdout_manifest.json").read_text())
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != _digest(body):
        raise ValueError("F1B manifest identity mismatch")
    if set(manifest["artifact_inventory"]) != {
        "blind_cases.json",
        "mapping_commitment.json",
        "blind_review.html",
    }:
        raise ValueError("F1B public artifact hash inventory mismatch")
    for name, expected in manifest["artifact_inventory"].items():
        if _sha256(directory / name) != expected:
            raise ValueError(f"F1B artifact hash mismatch: {name}")
    blind = json.loads((directory / "blind_cases.json").read_text())
    if blind.get("case_count") != 8 or len(blind.get("cases", ())) != 8:
        raise ValueError("F1B blind case inventory mismatch")
    blind_body = {
        key: value for key, value in blind.items() if key != "blind_packet_id"
    }
    if blind.get("blind_packet_id") != _digest(blind_body):
        raise ValueError("F1B blind packet identity mismatch")
    mapping = json.loads((directory / "mapping_commitment.json").read_text())
    expected_mapping_keys = {
        "schema_version",
        "case_count",
        "blind_packet_id",
        "mapping_commitment",
        "private_report_sha256",
        "f1b_handoff_sha256",
        "f1b_design_sha256",
        "f1a_approval_sha256",
        "g6_manifest_sha256",
    }
    if set(mapping) != expected_mapping_keys:
        raise ValueError("F1B public mapping commitment schema mismatch")
    if mapping.get("schema_version") != MAPPING_COMMITMENT_SCHEMA:
        raise ValueError("F1B public mapping commitment version mismatch")
    public_text = "\n".join(
        (directory / name).read_text(encoding="utf-8") for name in expected_names
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
        if forbidden in public_text:
            raise ValueError(f"F1B public packet leakage: {forbidden}")
    if mapping.get("case_count") != 8:
        raise ValueError("F1B public mapping commitment case count mismatch")
    if mapping.get("blind_packet_id") != blind.get("blind_packet_id"):
        raise ValueError("F1B packet/mapping linkage mismatch")
    return {
        "manifest_id": manifest["manifest_id"],
        "blind_packet_id": blind["blind_packet_id"],
        "mapping_commitment": mapping["mapping_commitment"],
        "private_report_sha256": mapping["private_report_sha256"],
        "case_count": 8,
    }


def write_challenge(output_dir: str | Path = OUTPUT_DIR) -> dict[str, object]:
    """Publish the bounded four-file F1B pre-rating artifact set."""

    directory = Path(output_dir)
    files = build_challenge_payloads()
    allowed_existing = set(files) | {"report.json"}
    if directory.exists():
        existing = {path.name for path in directory.iterdir() if path.is_file()}
        if not existing <= allowed_existing:
            raise ValueError(f"unexpected F1B output files: {sorted(existing)}")
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
    else:
        directory.mkdir(parents=True)
    try:
        for name, content in files.items():
            (directory / name).write_bytes(content)
        return validate_artifact_bundle(directory)
    except Exception:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()
        raise


__all__ = [
    "F1A_LOCKS",
    "FAMILY_NAME",
    "HOLDOUT_LENGTH",
    "OUTPUT_DIR",
    "SCHEMA_VERSION",
    "SELECTOR_IDS",
    "HoldoutSpec",
    "build_challenge_payloads",
    "build_holdouts",
    "select_consensus_first",
    "select_span_first",
    "validate_artifact_bundle",
    "verify_frozen_inputs",
    "write_challenge",
]
