"""Outcome-blind N4 composition of independent 1h and closed 4h geometry.

The module deliberately keeps the two timeframes independent.  It authenticates
the frozen local source corpus, evaluates the fixed 3/300 single-timeframe
semantics, pairs each 1h cutoff with the latest closed 4h snapshot, and stops
at a factual two-panel review packet.  It contains no MTF solver, fusion,
confidence score, or research conclusion.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import resource
import shutil
import sys
import time
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal

from libs.models.trendlines_v4 import core
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import h1_profile_challenge as h1
from research.trendlines_v4 import n3b_secondary_visual_utility as n3b
from research.trendlines_v4 import parameter_sensitivity as h0
from research.trendlines_v4 import secondary_candidate_feasibility as n3a

ROOT = Path(__file__).parents[2]
PRIMARY_ROOT = Path("/Users/kajukatli/projects/flipperAgent")
OUTPUT_DIR = ROOT / "artifacts/trendlines_v4/n4_multitimeframe_context_v1"

PIVOT_WINDOW = 3
HISTORY_CAPACITY_BARS = 300
RSS_LIMIT_BYTES = 512 * 1024 * 1024
TIMEFRAMES = ("1h", "4h")
ROLES = ("structural", "current_valid", "secondary")
SIDES = ("support", "resistance")
N4_MEMBERSHIP_HASH = "3d521b199df900e37735648ca662e23d360e4d4b29d526113580d8a288ee94bb"
H1B_MEMBERSHIP_HASH = h1.CONFIRMATION_MEMBERSHIP_HASH
N4_RANGES = (
    ("BTCUSDT", 13059, 13154),
    ("ETHUSDT", 9995, 10090),
    ("SOLUSDT", 9995, 10090),
    ("HYPEUSDT", 3241, 3336),
)
N4_4H_RANGES = (
    ("BTCUSDT", 3264, 3287),
    ("ETHUSDT", 2498, 2521),
    ("SOLUSDT", 2498, 2521),
    ("HYPEUSDT", 809, 832),
)

AUTHORITY_HASHES = {
    "handoff": (
        PRIMARY_ROOT
        / "plans/architect-to-coder-trendlines-v4-n4-multitimeframe-context-v1.md",
        "24f7f47c8ba8fe4dce9146aa849f1214f8a0bc037f4cca0bdbad6373b22c48c1",
    ),
    "design": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n4-multitimeframe-context-design-v1.md",
        "180b2e0c476459e2afa0ab71ff9bb8ee4b7be4ceeb4a5b17f319bb16746b2deb",
    ),
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n4-multitimeframe-context-design-approval-v1.md",
        "b173a91b853c3b96166e70a8bbf3706f14b0c779b4585066b1e509942d03652d",
    ),
}

N3B_ARTIFACT_LOCKS = {
    "blind_cases": (
        ROOT
        / "artifacts/trendlines_v4/n3b_secondary_visual_utility_v1/blind_cases.json",
        "363d44a0a8057d809daf03ac3086197c802a3d38c33d0facc1879ee6717eea61",
    ),
    "blind_review": (
        ROOT
        / "artifacts/trendlines_v4/n3b_secondary_visual_utility_v1/blind_review.html",
        "1e1a7709e8af20a254d292e7e863d68689a147e16ddeb84a755327654d497568",
    ),
}


class N4ContractError(ValueError):
    """Raised when a frozen N4 contract or provenance invariant is violated."""


class N4ResourceBlocked(RuntimeError):
    """Raised when the N4 process exceeds the observational RSS ceiling."""


@dataclass(frozen=True, slots=True)
class N4Cutoff:
    asset: str
    timeframe: Literal["1h", "4h"]
    source_position: int
    ordinal: int
    market_as_of: str

    def as_payload(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "source_position": self.source_position,
            "ordinal": self.ordinal,
            "market_as_of": self.market_as_of,
        }


@dataclass(frozen=True, slots=True)
class N4Line:
    role: str
    fact: h0.H0LineFact
    start_index: int
    end_index: int
    intercept: float

    @property
    def geometry_id(self) -> str:
        return self.fact.geometry_id

    def as_payload(self) -> dict[str, object]:
        return {
            "role": self.role,
            "geometry_id": self.geometry_id,
            "fact": self.fact.as_payload(),
            "start_index": self.start_index,
            "end_index": self.end_index,
            "start_anchor_at": self.fact.start_anchor_at,
            "end_anchor_at": self.fact.end_anchor_at,
            "start_anchor_price_hex": self.fact.start_anchor_price.hex(),
            "end_anchor_price_hex": self.fact.end_anchor_price.hex(),
            "projected_price_hex": self.fact.projected_price.hex(),
            "slope_per_bar_hex": self.fact.slope_per_bar.hex(),
            "projection_positive": self.fact.projection_positive,
        }


@dataclass(frozen=True, slots=True)
class N4Snapshot:
    cutoff: N4Cutoff
    lines: tuple[tuple[str, str, N4Line | None], ...]
    same_geometry: tuple[tuple[str, bool], ...]

    def line(self, side: str, role: str) -> N4Line | None:
        for line_side, line_role, line in self.lines:
            if line_side == side and line_role == role:
                return line
        raise N4ContractError("snapshot role inventory is incomplete")

    def same_for(self, side: str) -> bool:
        for line_side, value in self.same_geometry:
            if line_side == side:
                return value
        raise N4ContractError("snapshot same-geometry inventory is incomplete")

    def semantic_payload(self) -> dict[str, object]:
        return {
            "cutoff": self.cutoff.as_payload(),
            "lines": [
                {
                    "side": side,
                    "role": role,
                    "line": None if line is None else line.as_payload(),
                }
                for side, role, line in self.lines
            ],
            "same_geometry": [
                {"side": side, "value": value} for side, value in self.same_geometry
            ],
        }


@dataclass(frozen=True, slots=True)
class N4Pair:
    one_hour: N4Snapshot
    four_hour: N4Snapshot
    pairing_lag_hours: int

    def semantic_payload(self) -> dict[str, object]:
        return {
            "one_hour": self.one_hour.semantic_payload(),
            "four_hour": self.four_hour.semantic_payload(),
            "pairing_lag_hours": self.pairing_lag_hours,
        }


@dataclass(frozen=True, slots=True)
class N4Measurement:
    one_hour_snapshots: tuple[N4Snapshot, ...]
    four_hour_snapshots: tuple[N4Snapshot, ...]
    pairs: tuple[N4Pair, ...]
    parity: dict[str, int]

    def semantic_payload(self) -> dict[str, object]:
        return {
            "one_hour_snapshots": [
                item.semantic_payload() for item in self.one_hour_snapshots
            ],
            "four_hour_snapshots": [
                item.semantic_payload() for item in self.four_hour_snapshots
            ],
            "pairs": [item.semantic_payload() for item in self.pairs],
            "parity": dict(self.parity),
        }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(file_path: Path) -> str:
    if not file_path.is_file():
        raise N4ContractError(f"missing locked file: {file_path}")
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def _verify_hashes(
    locks: dict[str, tuple[Path, str]],
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, (file_path, expected) in locks.items():
        observed[name] = _sha256(file_path)
        if observed[name] != expected:
            raise N4ContractError(f"locked hash mismatch: {name}")
    return observed


def _artifact_hashes(
    locks: dict[str, tuple[Path, str]],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, (file_path, expected) in locks.items():
        observed = _sha256(file_path)
        if observed != expected:
            raise N4ContractError(f"protected artifact hash mismatch: {name}")
        result[name] = {
            "path": file_path.relative_to(ROOT).as_posix(),
            "sha256": observed,
            "byte_length": file_path.stat().st_size,
        }
    return result


def membership_payload() -> list[dict[str, object]]:
    return [
        {
            "asset": asset,
            "first_1h_source_position": first,
            "last_1h_source_position": last,
            "cutoff_count": last - first + 1,
        }
        for asset, first, last in N4_RANGES
    ]


def membership_hash() -> str:
    return _digest(membership_payload())


def _assert_membership_contract() -> None:
    if membership_hash() != N4_MEMBERSHIP_HASH:
        raise N4ContractError("N4 1h membership hash changed")
    if sum(last - first + 1 for _, first, last in N4_RANGES) != 384:
        raise N4ContractError("N4 membership count is not 384")
    if sum(last - first + 1 for _, first, last in N4_4H_RANGES) != 96:
        raise N4ContractError("N4 paired 4h range count is not 96")


def verify_authorities() -> dict[str, object]:
    """Authenticate N4, protected V4, and all prior evidence authorities."""

    _assert_membership_contract()
    n4_authority = {
        name: {
            "path": file_path.relative_to(PRIMARY_ROOT).as_posix(),
            "sha256": digest,
        }
        for name, (file_path, digest) in AUTHORITY_HASHES.items()
    }
    _verify_hashes(AUTHORITY_HASHES)
    prior = h0.verify_prior_artifacts()
    h1_authority = h1.verify_authorities()
    h1a_scope_count = len(h1._original_scope_hashes())
    n3b_authority = n3b.verify_authorities()
    n3b_artifacts = _artifact_hashes(N3B_ARTIFACT_LOCKS)
    return {
        "n4": n4_authority,
        "prior_h0": prior,
        "h1_authority": h1_authority,
        "h1a_original_scope_count": h1a_scope_count,
        "n3b_authority": n3b_authority,
        "n3b_artifacts": n3b_artifacts,
        "h1b": {
            "membership_hash": H1B_MEMBERSHIP_HASH,
            "evaluated_cutoff_count": 0,
            "results_published": False,
        },
    }


def _n4_cutoff(
    stream: h0.H0Stream,
    source_position: int,
    ordinal: int,
) -> N4Cutoff:
    if not 0 <= source_position < len(stream.bars):
        raise N4ContractError("N4 source position is outside its stream")
    if source_position < HISTORY_CAPACITY_BARS - 1:
        raise N4ContractError("N4 cutoff lacks a complete 300-bar history")
    return N4Cutoff(
        asset=stream.asset,
        timeframe=stream.timeframe,  # type: ignore[arg-type]
        source_position=source_position,
        ordinal=ordinal,
        market_as_of=n1._timestamp(stream.bars[source_position].closed_at),
    )


def _build_cutoffs(streams: Sequence[h0.H0Stream]) -> tuple[N4Cutoff, ...]:
    _assert_membership_contract()
    stream_map = {(stream.asset, stream.timeframe): stream for stream in streams}
    result: list[N4Cutoff] = []
    for asset, first, last in N4_RANGES:
        stream = stream_map.get((asset, "1h"))
        if stream is None:
            raise N4ContractError(f"missing N4 1h stream: {asset}")
        for ordinal, source_position in enumerate(range(first, last + 1)):
            result.append(_n4_cutoff(stream, source_position, ordinal))
    if len(result) != 384:
        raise N4ContractError("N4 produced the wrong 1h cutoff inventory")
    return tuple(result)


def _build_expected_4h_positions() -> dict[str, set[int]]:
    return {asset: set(range(first, last + 1)) for asset, first, last in N4_4H_RANGES}


def _assert_no_prior_membership_overlap(
    streams: Sequence[h0.H0Stream],
    cutoffs: Sequence[N4Cutoff],
) -> dict[str, int]:
    """Check N4 positions against prior H0, H1A/H1B, and N3 review positions."""

    n4_positions = {(row.asset, row.timeframe, row.source_position) for row in cutoffs}
    stream_map = {(stream.asset, stream.timeframe): stream for stream in streams}
    h0_positions = {
        (stream.asset, stream.timeframe, cutoff.source_position)
        for stream in streams
        for cutoff in (*stream.development, *stream.holdout)
    }
    h1a_positions = {
        (stream.asset, stream.timeframe, cutoff.source_position)
        for stream in streams
        for cutoff in stream.holdout[: h1.SELECTION_CUTOFFS_PER_STREAM]
    }
    h1b_positions = {
        (stream.asset, stream.timeframe, cutoff.source_position)
        for stream in streams
        for cutoff in stream.holdout[h1.SELECTION_CUTOFFS_PER_STREAM :]
    }
    n3b_positions = {
        (asset, timeframe, position)
        for asset, timeframe, first, last in n3b.N3B_RANGES
        for position in range(first, last + 1)
    }
    if n4_positions & h0_positions:
        raise N4ContractError("N4 overlaps prior H0 membership")
    if n4_positions & h1a_positions:
        raise N4ContractError("N4 overlaps prior H1A membership")
    if n4_positions & h1b_positions:
        raise N4ContractError("N4 overlaps sealed H1B membership")
    if n4_positions & n3b_positions:
        raise N4ContractError("N4 overlaps prior N3B membership")
    return {
        "h0_overlap_count": 0,
        "h1a_overlap_count": 0,
        "h1b_overlap_count": 0,
        "n3b_overlap_count": 0,
        "checked_stream_count": len(stream_map),
    }


def _history_for_cutoff(
    stream: h0.H0Stream,
    cutoff: N4Cutoff,
) -> tuple[n1.TrendlineBar, ...]:
    source_slice = stream.bars[
        cutoff.source_position + 1 - HISTORY_CAPACITY_BARS : cutoff.source_position + 1
    ]
    if len(source_slice) != HISTORY_CAPACITY_BARS:
        raise N4ContractError("N4 history is not exactly 300 bars")
    history = n1._core_bars(source_slice)
    if history[-1].closed_at != stream.bars[cutoff.source_position].closed_at:
        raise N4ContractError("N4 history reads beyond its causal cutoff")
    if n1._timestamp(history[-1].closed_at) != cutoff.market_as_of:
        raise N4ContractError("N4 cutoff timestamp is not source-owned")
    return history


def _reference_secondary(
    endpoints: Sequence[n3a.EndpointCandidate],
    exposed_ids: frozenset[str],
) -> n3a.EndpointCandidate | None:
    selected = None
    for candidate in endpoints:
        if candidate.geometry_id in exposed_ids:
            continue
        if selected is None or candidate.score > selected.score:
            selected = candidate
    return selected


def _line_record(
    candidate: n3a.EndpointCandidate | None,
    fact: h0.H0LineFact | None,
    history: Sequence[core.TrendlineBar],
    role: str,
) -> N4Line | None:
    if candidate is None or fact is None:
        if candidate is not None or fact is not None:
            raise N4ContractError("candidate/fact presence mismatch")
        return None
    start = n1._anchor_position(history, candidate.geometry.start_anchor_at)
    end = n1._anchor_position(history, candidate.geometry.end_anchor_at)
    if not 0 <= start < end < len(history):
        raise N4ContractError("line anchor is outside causal history")
    intercept = (
        candidate.geometry.end_anchor_price - candidate.geometry.slope_per_bar * end
    )
    if not all(
        math.isfinite(value)
        for value in (
            intercept,
            candidate.geometry.slope_per_bar,
            candidate.geometry.projected_price_at_market_as_of,
        )
    ):
        raise N4ContractError("line projection is not finite")
    if fact.geometry_id != candidate.geometry_id:
        raise N4ContractError("line fact identity differs from endpoint geometry")
    return N4Line(role, fact, start, end, intercept)


def _evaluate_snapshot(
    stream: h0.H0Stream,
    cutoff: N4Cutoff,
    profiles: dict[str, h0.H0Profile],
    parity: dict[str, int],
) -> N4Snapshot:
    history = _history_for_cutoff(stream, cutoff)
    profile = profiles[cutoff.timeframe]
    snapshot = h0.analyze_profile(profile, history)
    h0_cutoff = h0.H0Cutoff(
        asset=cutoff.asset,
        timeframe=cutoff.timeframe,
        window="n4",
        cutoff=cutoff.ordinal,
        source_position=cutoff.source_position,
        market_as_of=cutoff.market_as_of,
        partition="development",
    )
    expected_facts = h0.snapshot_facts(
        snapshot,
        history,
        profile=profile,
        cutoff=h0_cutoff,
    )
    enumerations = {
        side: n3a._enumerate_side(
            history,
            side,
            asset=cutoff.asset,
            timeframe=cutoff.timeframe,
        )
        for side in SIDES
    }
    actual_facts, same_counts = n3a._assert_baseline_parity(
        snapshot,
        expected_facts,
        enumerations,
        history,
        profiles,
        h0_cutoff,
    )
    parity["snapshot_count"] += 1
    parity["p0_role_comparison_count"] += 4
    parity["p0_same_geometry_comparison_count"] += same_counts["same_geometry_count"]
    lines: list[tuple[str, str, N4Line | None]] = []
    same_geometry: list[tuple[str, bool]] = []
    for side in SIDES:
        enumeration = enumerations[side]
        structural = enumeration.structural
        current_valid = enumeration.current_valid
        exposed = frozenset(
            candidate.geometry_id
            for candidate in (structural, current_valid)
            if candidate is not None
        )
        selected = n3a._select_secondary(enumeration.endpoints, exposed)
        reference_selected = _reference_secondary(enumeration.endpoints, exposed)
        parity["secondary_selector_comparison_count"] += 1
        parity["secondary_selector_mismatch_count"] += int(
            selected != reference_selected
        )
        if selected != reference_selected:
            raise N4ContractError("N3A secondary selector parity failed")
        secondary = n3a._line_fact(
            selected,
            history,
            profile,
            h0_cutoff,
            "secondary",
        )
        reference_secondary = (
            None
            if reference_selected is None
            else h0._line_fact(
                reference_selected.geometry,
                history,
                profile=profile,
                cutoff=h0_cutoff,
                role="secondary",
            )
        )
        parity["secondary_fact_comparison_count"] += 1
        parity["secondary_fact_mismatch_count"] += int(secondary != reference_secondary)
        if secondary != reference_secondary:
            raise N4ContractError("N3A secondary fact parity failed")
        candidates = {
            "structural": structural,
            "current_valid": current_valid,
            "secondary": selected,
        }
        facts = {
            "structural": actual_facts[f"{side}.structural"],
            "current_valid": actual_facts[f"{side}.current_valid"],
            "secondary": secondary,
        }
        for role in ROLES:
            line = _line_record(candidates[role], facts[role], history, role)
            lines.append((side, role, line))
            if line is not None:
                parity[f"{role}_availability_count"] += 1
                parity[f"{role}_projection_non_positive_count"] += int(
                    line.fact.projection_non_positive
                )
                if role == "current_valid":
                    parity["current_valid_adverse_body_count"] += int(
                        line.fact.post_anchor_adverse_body_bar_count != 0
                    )
                if role == "secondary":
                    parity["secondary_current_adverse_side_count"] += int(
                        line.fact.current_body_adverse_side == "adverse"
                    )
        actual_same = (
            structural is not None
            and current_valid is not None
            and structural.geometry_id == current_valid.geometry_id
        )
        expected_same = getattr(snapshot, side).same_geometry
        if actual_same != expected_same:
            raise N4ContractError("same-geometry parity failed")
        same_geometry.append((side, actual_same))
        parity["same_geometry_snapshot_count"] += int(actual_same)
    if parity["current_valid_adverse_body_count"] < 0:
        raise N4ContractError("unreachable parity guard")
    return N4Snapshot(cutoff, tuple(lines), tuple(same_geometry))


def _build_pairs(
    streams: Sequence[h0.H0Stream],
    cutoffs: Sequence[N4Cutoff],
    parity: dict[str, int],
) -> tuple[tuple[N4Snapshot, ...], tuple[N4Snapshot, ...], tuple[N4Pair, ...]]:
    stream_map = {(stream.asset, stream.timeframe): stream for stream in streams}
    profiles = {timeframe: n3a._baseline_profile(timeframe) for timeframe in TIMEFRAMES}
    one_hour_snapshots: list[N4Snapshot] = []
    four_hour_by_key: dict[tuple[str, int], N4Snapshot] = {}
    pairs: list[N4Pair] = []
    expected_4h = _build_expected_4h_positions()
    for cutoff in cutoffs:
        stream_1h = stream_map[(cutoff.asset, "1h")]
        snapshot_1h = _evaluate_snapshot(stream_1h, cutoff, profiles, parity)
        one_hour_snapshots.append(snapshot_1h)
        stream_4h = stream_map[(cutoff.asset, "4h")]
        close_times = [bar.closed_at for bar in stream_4h.bars]
        one_hour_close = stream_1h.bars[cutoff.source_position].closed_at
        paired_position = bisect_right(close_times, one_hour_close) - 1
        if paired_position < 0:
            raise N4ContractError("no closed 4h bar exists for an N4 cutoff")
        paired_close = close_times[paired_position]
        lag_seconds = (one_hour_close - paired_close).total_seconds()
        if lag_seconds % 3600 != 0 or not 0 <= lag_seconds // 3600 <= 3:
            raise N4ContractError("N4 pairing lag is not an integer 0..3 hours")
        lag_hours = int(lag_seconds // 3600)
        if paired_close > one_hour_close:
            raise N4ContractError("N4 paired a future 4h close")
        if (
            paired_position + 1 < len(close_times)
            and close_times[paired_position + 1] <= one_hour_close
        ):
            raise N4ContractError("N4 did not choose the latest closed 4h bar")
        if paired_position not in expected_4h[cutoff.asset]:
            raise N4ContractError("paired 4h position is outside the frozen range")
        paired_key = (cutoff.asset, paired_position)
        snapshot_4h = four_hour_by_key.get(paired_key)
        if snapshot_4h is None:
            paired_cutoff = _n4_cutoff(stream_4h, paired_position, paired_position)
            snapshot_4h = _evaluate_snapshot(
                stream_4h,
                paired_cutoff,
                profiles,
                parity,
            )
            four_hour_by_key[paired_key] = snapshot_4h
        pairs.append(N4Pair(snapshot_1h, snapshot_4h, lag_hours))
    if len(one_hour_snapshots) != 384 or len(four_hour_by_key) != 96:
        raise N4ContractError("N4 snapshot inventory is not 384/96")
    lag_counts = Counter(pair.pairing_lag_hours for pair in pairs)
    if dict(lag_counts) != {0: 96, 1: 96, 2: 96, 3: 96}:
        raise N4ContractError("N4 lag inventory is not exactly 96/96/96/96")
    four_hour_snapshots = tuple(
        four_hour_by_key[key] for key in sorted(four_hour_by_key)
    )
    return tuple(one_hour_snapshots), four_hour_snapshots, tuple(pairs)


def _new_parity() -> dict[str, int]:
    return {
        "snapshot_count": 0,
        "p0_role_comparison_count": 0,
        "p0_same_geometry_comparison_count": 0,
        "secondary_selector_comparison_count": 0,
        "secondary_selector_mismatch_count": 0,
        "secondary_fact_comparison_count": 0,
        "secondary_fact_mismatch_count": 0,
        "same_geometry_snapshot_count": 0,
        "current_valid_adverse_body_count": 0,
        "secondary_current_adverse_side_count": 0,
        "structural_availability_count": 0,
        "current_valid_availability_count": 0,
        "secondary_availability_count": 0,
        "structural_projection_non_positive_count": 0,
        "current_valid_projection_non_positive_count": 0,
        "secondary_projection_non_positive_count": 0,
    }


def evaluate(streams: Sequence[h0.H0Stream]) -> N4Measurement:
    """Evaluate the frozen N4 corpus once without publishing any artifacts."""

    cutoffs = _build_cutoffs(streams)
    _assert_no_prior_membership_overlap(streams, cutoffs)
    parity = _new_parity()
    one_hour, four_hour, pairs = _build_pairs(streams, cutoffs, parity)
    if parity["current_valid_adverse_body_count"] != 0:
        raise N4ContractError("current-valid adverse-body invariant failed")
    if parity["secondary_selector_mismatch_count"] != 0:
        raise N4ContractError("secondary selector mismatch was observed")
    if parity["secondary_fact_mismatch_count"] != 0:
        raise N4ContractError("secondary fact mismatch was observed")
    return N4Measurement(one_hour, four_hour, pairs, parity)


def _line_identity(left: N4Line, right: N4Line) -> bool:
    return (
        left.fact.start_anchor_at == right.fact.start_anchor_at
        and left.fact.end_anchor_at == right.fact.end_anchor_at
        and left.fact.start_anchor_price.hex() == right.fact.start_anchor_price.hex()
        and left.fact.end_anchor_price.hex() == right.fact.end_anchor_price.hex()
    )


def _separation_bps(left: float, right: float) -> float:
    midpoint = (left + right) / 2.0
    if midpoint <= 0 or not math.isfinite(midpoint):
        raise N4ContractError("cross-timeframe separation has invalid midpoint")
    return abs(left - right) / midpoint * 10_000.0


def _cross_timeframe_evidence(
    measurement: N4Measurement,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    lag_zero_count = 0
    lagged_suppressed_count = 0
    for pair in measurement.pairs:
        if pair.pairing_lag_hours != 0:
            lagged_suppressed_count += 1
            continue
        lag_zero_count += 1
        for side in SIDES:
            for role in ROLES:
                left = pair.one_hour.line(side, role)
                right = pair.four_hour.line(side, role)
                if left is None or right is None:
                    continue
                anchor_timestamps = {
                    left.fact.start_anchor_at,
                    left.fact.end_anchor_at,
                }
                right_timestamps = {
                    right.fact.start_anchor_at,
                    right.fact.end_anchor_at,
                }
                overlap = len(anchor_timestamps & right_timestamps)
                rows.append(
                    {
                        "asset": pair.one_hour.cutoff.asset,
                        "source_position_1h": pair.one_hour.cutoff.source_position,
                        "source_position_4h": pair.four_hour.cutoff.source_position,
                        "side": side,
                        "role": role,
                        "physical_line_identity": _line_identity(left, right),
                        "projected_price_separation_bps": _separation_bps(
                            left.fact.projected_price,
                            right.fact.projected_price,
                        ),
                        "anchor_timestamp_overlap_count": overlap,
                    }
                )
    if lag_zero_count != 96:
        raise N4ContractError("N4 cross-timeframe evidence did not use 96 lag-0 pairs")
    values = [float(row["projected_price_separation_bps"]) for row in rows]
    return {
        "lag_zero_pair_count": lag_zero_count,
        "lagged_pair_count": lagged_suppressed_count,
        "lagged_projected_separation_count": 0,
        "corresponding_line_comparison_count": len(rows),
        "physical_line_identity_count": sum(
            bool(row["physical_line_identity"]) for row in rows
        ),
        "projected_price_separation_bps": n3b._distribution(values),
        "anchor_timestamp_overlap_count": {
            str(key): value
            for key, value in Counter(
                int(row["anchor_timestamp_overlap_count"]) for row in rows
            ).items()
        },
        "rows": rows,
    }


def _role_replacement_facts(
    snapshots: Sequence[N4Snapshot],
) -> dict[str, object]:
    grouped: dict[tuple[str, str], list[str | None]] = defaultdict(list)
    for snapshot in snapshots:
        for side in SIDES:
            for role in ROLES:
                line = snapshot.line(side, role)
                grouped[(side, role)].append(None if line is None else line.geometry_id)
    result: dict[str, object] = {}
    for (side, role), values in grouped.items():
        transitions = 0
        replacements = 0
        for previous, current in pairwise(values):
            transitions += 1
            if previous is not None and current is not None and previous != current:
                replacements += 1
        result[f"{side}.{role}"] = {
            "contiguous_transition_count": transitions,
            "replacement_count": replacements,
            "available_count": sum(value is not None for value in values),
        }
    return result


def _per_timeframe_inventory(measurement: N4Measurement) -> dict[str, object]:
    result: dict[str, object] = {}
    for timeframe, snapshots in (
        ("1h", measurement.one_hour_snapshots),
        ("4h", measurement.four_hour_snapshots),
    ):
        by_asset = {
            asset: tuple(
                snapshot for snapshot in snapshots if snapshot.cutoff.asset == asset
            )
            for asset, _, _ in N4_RANGES
        }
        for asset, rows in by_asset.items():
            for side in SIDES:
                key = f"{asset}.{timeframe}.{side}"
                role_rows: dict[str, object] = {}
                for role in ROLES:
                    facts = [row.line(side, role) for row in rows]
                    available = [fact for fact in facts if fact is not None]
                    role_rows[role] = {
                        "snapshot_count": len(rows),
                        "availability_count": len(available),
                        "availability_rate": len(available) / len(rows),
                        "projection_non_positive_count": sum(
                            fact.fact.projection_non_positive for fact in available
                        ),
                        "secondary_current_adverse_side_count": (
                            sum(
                                fact.fact.current_body_adverse_side == "adverse"
                                for fact in available
                            )
                            if role == "secondary"
                            else 0
                        ),
                    }
                same_count = sum(row.same_for(side) for row in rows)
                result[key] = {
                    "snapshot_count": len(rows),
                    "same_geometry_count": same_count,
                    "same_geometry_rate": same_count / len(rows),
                    "roles": role_rows,
                    "replacement_facts": _role_replacement_facts(rows),
                }
    return result


def _report(measurement: N4Measurement) -> dict[str, object]:
    cross = _cross_timeframe_evidence(measurement)
    lag_counts = Counter(pair.pairing_lag_hours for pair in measurement.pairs)
    overlap = {
        "checked_stream_count": 8,
        "h0_overlap_count": 0,
        "h1a_overlap_count": 0,
        "h1b_overlap_count": 0,
        "n3b_overlap_count": 0,
    }
    return {
        "schema": "trendlines.v4.n4.multitimeframe-context.v1",
        "disposition": "N4_CONTEXT_REVIEW_READY",
        "study_boundary": {
            "purpose": "causal MTF composition semantics and human utility",
            "four_hour_source": "derived from exact contiguous UTC 1h groups of four",
            "native_4h_parity_established": False,
            "production_rule": "consume independently closed native-timeframe artifacts",
            "fusion": False,
            "ratings_recorded": False,
        },
        "parameters": {
            "pivot_window": PIVOT_WINDOW,
            "history_capacity_bars": HISTORY_CAPACITY_BARS,
            "roles": list(ROLES),
            "secondary_selector": "highest_legacy_score_distinct_secondary",
        },
        "membership": {
            "one_hour_cutoff_count": 384,
            "membership_hash": N4_MEMBERSHIP_HASH,
            "ranges": membership_payload(),
            "paired_four_hour_ranges": [
                {
                    "asset": asset,
                    "first_source_position": first,
                    "last_source_position": last,
                    "cutoff_count": last - first + 1,
                }
                for asset, first, last in N4_4H_RANGES
            ],
            "paired_four_hour_unique_snapshot_count": 96,
            "prior_membership_overlap": overlap,
        },
        "pairing": {
            "paired_observation_count": len(measurement.pairs),
            "lag_hours": {str(hour): lag_counts[hour] for hour in range(4)},
            "future_four_hour_count": 0,
            "partial_four_hour_count": 0,
            "fractional_projection_count": 0,
        },
        "single_timeframe_parity": dict(measurement.parity),
        "per_timeframe_inventory": _per_timeframe_inventory(measurement),
        "cross_timeframe_lag_zero_evidence": cross,
        "h1b": {
            "membership_hash": H1B_MEMBERSHIP_HASH,
            "evaluated_cutoff_count": 0,
            "results_published": False,
        },
        "review": {
            "case_count": 16,
            "asset_case_counts": {asset: 4 for asset, _, _ in N4_RANGES},
            "lag_case_counts": {str(hour): 4 for hour in range(4)},
            "support_case_count": 8,
            "resistance_case_count": 8,
            "ratings_recorded": False,
            "conclusion": None,
        },
    }


def _case_hash(pair: N4Pair, side: str) -> str:
    return _digest(
        {
            "asset": pair.one_hour.cutoff.asset,
            "source_position": pair.one_hour.cutoff.source_position,
            "side": side,
            "lag_hours": pair.pairing_lag_hours,
        }
    )


def _select_cases(measurement: N4Measurement) -> tuple[tuple[N4Pair, str], ...]:
    asset_order = {asset: index for index, (asset, _, _) in enumerate(N4_RANGES)}
    selected: list[tuple[N4Pair, str]] = []
    for asset, _, _ in N4_RANGES:
        for lag_hours in range(4):
            side = SIDES[(asset_order[asset] + lag_hours) % 2]
            candidates = [
                pair
                for pair in measurement.pairs
                if pair.one_hour.cutoff.asset == asset
                and pair.pairing_lag_hours == lag_hours
            ]
            if not candidates:
                raise N4ContractError("N4 case pool is empty")
            selected.append(
                (min(candidates, key=lambda pair: _case_hash(pair, side)), side)
            )
    if len(selected) != 16:
        raise N4ContractError("N4 did not select exactly 16 cases")
    if len({pair.one_hour.cutoff.source_position for pair, _ in selected}) != 16:
        raise N4ContractError("N4 selected duplicate case cutoffs")
    if Counter(pair.pairing_lag_hours for pair, _ in selected) != Counter(
        {0: 4, 1: 4, 2: 4, 3: 4}
    ):
        raise N4ContractError("N4 case lag balance is not exact")
    if Counter(side for _, side in selected) != Counter(
        {"support": 8, "resistance": 8}
    ):
        raise N4ContractError("N4 case side balance is not exact")
    if Counter(pair.one_hour.cutoff.asset for pair, _ in selected) != Counter(
        {asset: 4 for asset, _, _ in N4_RANGES}
    ):
        raise N4ContractError("N4 case asset balance is not exact")
    return tuple(selected)


def _panel_line(line: N4Line, display_start: int) -> dict[str, object]:
    return {
        "role": line.role,
        "geometry_id": line.geometry_id,
        "color": {
            "structural": "#6f42c1",
            "current_valid": "#d97706",
            "secondary": "#16803c",
        }[line.role],
        "start_anchor": {
            "bar_offset": line.start_index - display_start,
            "closed_at": line.fact.start_anchor_at,
            "price": line.fact.start_anchor_price,
        },
        "end_anchor": {
            "bar_offset": line.end_index - display_start,
            "closed_at": line.fact.end_anchor_at,
            "price": line.fact.end_anchor_price,
        },
        "slope_per_bar": line.fact.slope_per_bar,
        "projected_price": line.fact.projected_price,
    }


def _panel(
    snapshot: N4Snapshot,
    stream: h0.H0Stream,
    side: str,
) -> dict[str, object]:
    lines = [
        snapshot.line(side, role)
        for role in ROLES
        if snapshot.line(side, role) is not None
    ]
    earliest = min((line.start_index for line in lines), default=0)
    display_start = max(0, earliest - 5)
    display_end = HISTORY_CAPACITY_BARS - 1
    source_start = (
        snapshot.cutoff.source_position + 1 - HISTORY_CAPACITY_BARS + display_start
    )
    source_bars = stream.bars[source_start : snapshot.cutoff.source_position + 1]
    if len(source_bars) != display_end - display_start + 1:
        raise N4ContractError("N4 panel is not an anchor-complete causal slice")
    return {
        "timeframe": snapshot.cutoff.timeframe,
        "side": side,
        "market_as_of": snapshot.cutoff.market_as_of,
        "source_position": snapshot.cutoff.source_position,
        "display_start_source_position": source_start,
        "display_end_source_position": snapshot.cutoff.source_position,
        "bars": [
            {
                "source_position": source_start + offset,
                "open_at": n1._timestamp(bar.open_at),
                "closed_at": n1._timestamp(bar.closed_at),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
            }
            for offset, bar in enumerate(source_bars)
        ],
        "lines": [_panel_line(line, display_start) for line in lines],
        "anchor_complete": True,
        "causal_cutoff_only": True,
    }


def _build_cases(
    measurement: N4Measurement,
    streams: Sequence[h0.H0Stream],
) -> tuple[dict[str, object], ...]:
    selected = _select_cases(measurement)
    stream_map = {(stream.asset, stream.timeframe): stream for stream in streams}
    cases: list[dict[str, object]] = []
    for number, (pair, side) in enumerate(selected, 1):
        case_hash = _case_hash(pair, side)
        cases.append(
            {
                "case_id": f"n4-{number:02d}-{case_hash[:12]}",
                "asset": pair.one_hour.cutoff.asset,
                "side": side,
                "pairing_lag_hours": pair.pairing_lag_hours,
                "one_hour": _panel(
                    pair.one_hour,
                    stream_map[(pair.one_hour.cutoff.asset, "1h")],
                    side,
                ),
                "four_hour": _panel(
                    pair.four_hour,
                    stream_map[(pair.four_hour.cutoff.asset, "4h")],
                    side,
                ),
                "ratings": {
                    "q1": ("ADDS_CONTEXT", "REDUNDANT", "DISTRACTING", "UNSURE"),
                    "q2": ("NOT_CLUTTERED", "CLUTTERED", "UNSURE"),
                    "recorded": False,
                },
            }
        )
    return tuple(cases)


def _svg(panel: dict[str, object], panel_id: str) -> str:
    bars = panel["bars"]
    lines = panel["lines"]
    width = max(2200, 8 * len(bars) + 80)
    height = 620
    left, right, top, bottom = 48, width - 48, 36, 500
    values = [value for bar in bars for value in (bar["high"], bar["low"])]
    for line in lines:
        values.extend(
            (
                line["projected_price"],
                line["start_anchor"]["price"],
                line["end_anchor"]["price"],
            )
        )
    low, high = min(values), max(values)
    padding = (high - low) * 0.06 or max(abs(high) * 0.01, 1e-9)
    low -= padding
    high += padding

    def x(offset: int) -> float:
        return left + (right - left) * offset / max(1, len(bars) - 1)

    def y(value: float) -> float:
        return top + (high - value) * (bottom - top) / (high - low)

    fragments = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'data-panel="{html.escape(panel_id, quote=True)}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            f'<text x="48" y="22" font-family="sans-serif" font-size="16">'
            f"{html.escape(str(panel['timeframe']))} · "
            f"{html.escape(str(panel['market_as_of']))}</text>"
        ),
    ]
    for offset, bar in enumerate(bars):
        center = x(offset)
        color = "#16803c" if bar["close"] >= bar["open"] else "#b42318"
        fragments.append(
            f'<line x1="{center:.3f}" x2="{center:.3f}" '
            f'y1="{y(bar["high"]):.3f}" y2="{y(bar["low"]):.3f}" stroke="{color}"/>'
        )
        body_top = y(max(bar["open"], bar["close"]))
        body_bottom = y(min(bar["open"], bar["close"]))
        fragments.append(
            f'<rect x="{center - 2:.3f}" y="{body_top:.3f}" width="4" '
            f'height="{max(1.0, body_bottom - body_top):.3f}" fill="{color}"/>'
        )
    for line in lines:
        start = line["start_anchor"]["bar_offset"]
        slope = line["slope_per_bar"]
        start_price = line["start_anchor"]["price"]
        color = line["color"]
        fragments.append(
            f'<line x1="{x(0):.3f}" y1="{y(start_price - slope * start):.3f}" '
            f'x2="{x(len(bars) - 1):.3f}" '
            f'y2="{y(start_price + slope * (len(bars) - 1 - start)):.3f}" '
            f'stroke="{color}" stroke-width="2.5" data-role="{line["role"]}"/>'
        )
        for anchor_name in ("start_anchor", "end_anchor"):
            anchor = line[anchor_name]
            offset = anchor["bar_offset"]
            fragments.append(
                f'<circle cx="{x(offset):.3f}" cy="{y(anchor["price"]):.3f}" '
                f'r="5" fill="{color}" data-anchor="{line["role"]}-{anchor_name}">'
                f"<title>{html.escape(str(line['role']))} {anchor_name}</title></circle>"
            )
    fragments.extend(
        [
            (
                f'<line x1="{left}" x2="{right}" '
                f'y1="{y(bars[-1]["close"]):.3f}" '
                f'y2="{y(bars[-1]["close"]):.3f}" '
                'stroke="#555" stroke-dasharray="5 4"/>'
            ),
            (
                '<text x="48" y="540" font-family="sans-serif" font-size="12">'
                "purple structural · orange current_valid · green secondary · anchors marked</text>"
            ),
            "</svg>",
        ]
    )
    return "".join(fragments)


def _html(cases: Sequence[dict[str, object]]) -> bytes:
    sections: list[str] = []
    for case in cases:
        case_id = html.escape(str(case["case_id"]), quote=True)
        q1 = "".join(
            f'<label><input type="radio" name="q1-{case_id}" value="{value}">{value}</label>'
            for value in ("ADDS_CONTEXT", "REDUNDANT", "DISTRACTING", "UNSURE")
        )
        q2 = "".join(
            f'<label><input type="radio" name="q2-{case_id}" value="{value}">{value}</label>'
            for value in ("NOT_CLUTTERED", "CLUTTERED", "UNSURE")
        )
        sections.append(
            '<section class="case">'
            f"<h2>{case_id} · {html.escape(str(case['asset']))} · "
            f"{html.escape(str(case['side']))} · lag {case['pairing_lag_hours']}h</h2>"
            '<div class="panel"><h3>1h panel</h3><div class="chart-scroll">'
            f"{_svg(case['one_hour'], case_id + '-1h')}</div></div>"
            '<div class="panel"><h3>4h panel — last closed context</h3><div class="chart-scroll">'
            f"{_svg(case['four_hour'], case_id + '-4h')}</div></div>"
            "<fieldset><legend>Q1 — does 4h add context beyond 1h?</legend>"
            f"{q1}</fieldset>"
            "<fieldset><legend>Q2 — combined information density</legend>"
            f"{q2}</fieldset>"
            "</section>"
        )
    document = (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Trendlines V4 N4 context review</title>"
        "<style>body{font-family:sans-serif;margin:24px;background:#f5f5f5;}"
        ".case{background:#fff;padding:18px;margin:24px 0;border:1px solid #bbb;}"
        ".panel{margin:14px 0}.chart-scroll{overflow-x:auto;border:1px solid #ddd;}"
        "fieldset{display:inline-block;vertical-align:top;margin:12px 12px 0 0;}"
        "label{margin-right:12px;white-space:nowrap;}</style></head><body>"
        "<h1>Trendlines V4 N4 independent 1h + last-closed 4h context</h1>"
        "<p>Review each two-panel case. The panels are independently computed; "
        "the 4h panel is never overlaid or fractionally projected onto 1h.</p>"
        + "".join(sections)
        + "</body></html>\n"
    )
    return document.encode("utf-8")


def _resource_record(start_wall: float, start_cpu: float) -> dict[str, object]:
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak = raw if sys.platform == "darwin" else raw * 1024
    return {
        "wall_seconds": time.perf_counter() - start_wall,
        "cpu_seconds": time.process_time() - start_cpu,
        "peak_process_rss_bytes": peak,
    }


def _atomic_write(output_dir: Path, files: dict[str, bytes]) -> None:
    if output_dir.exists():
        raise N4ContractError("N4 output directory already exists")
    temp_dir = output_dir.with_name(output_dir.name + ".tmp")
    if temp_dir.exists():
        raise N4ContractError("N4 temporary output directory already exists")
    try:
        temp_dir.mkdir(parents=True)
        for name, data in files.items():
            (temp_dir / name).write_bytes(data)
        os.replace(temp_dir, output_dir)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def _semantic_view(measurement: N4Measurement) -> bytes:
    return _canonical_bytes(measurement.semantic_payload())


def run_n4(output_dir: Path = OUTPUT_DIR) -> dict[str, object]:
    """Run two exact N4 semantic passes and publish only the review packet."""

    if output_dir.exists():
        raise N4ContractError("N4 output target must be absent before execution")
    authority = verify_authorities()
    streams = h0.build_streams()
    first_start_wall = time.perf_counter()
    first_start_cpu = time.process_time()
    first = evaluate(streams)
    first_resources = _resource_record(first_start_wall, first_start_cpu)
    second_start_wall = time.perf_counter()
    second_start_cpu = time.process_time()
    second = evaluate(streams)
    second_resources = _resource_record(second_start_wall, second_start_cpu)
    if _semantic_view(first) != _semantic_view(second):
        raise N4ContractError("N4 semantic runs are not exactly equal")
    for record in (first_resources, second_resources):
        if int(record["peak_process_rss_bytes"]) > RSS_LIMIT_BYTES:
            raise N4ResourceBlocked("N4 peak RSS exceeded 512 MiB")
    cases = _build_cases(first, streams)
    report = _report(first)
    report["authority"] = authority
    report["determinism"] = {
        "semantic_runs": 2,
        "exact_semantic_equality": True,
        "semantic_digest": hashlib.sha256(_semantic_view(first)).hexdigest(),
    }
    report["resource_observation"] = {
        "rss_limit_bytes": RSS_LIMIT_BYTES,
        "first": first_resources,
        "second": second_resources,
    }
    report_bytes = _pretty_bytes(report)
    cases_payload = {
        "schema": "trendlines.v4.n4.multitimeframe-context-review-cases.v1",
        "case_count": len(cases),
        "cases": cases,
        "identity_revealed": True,
        "ratings_recorded": False,
    }
    cases_bytes = _pretty_bytes(cases_payload)
    html_bytes = _html(cases)
    manifest_body = {
        "schema": "trendlines.v4.n4.multitimeframe-context-manifest.v1",
        "disposition": "N4_CONTEXT_REVIEW_READY",
        "authority": authority,
        "membership_hash": N4_MEMBERSHIP_HASH,
        "membership_count": 384,
        "paired_four_hour_snapshot_count": 96,
        "lag_inventory": {"0": 96, "1": 96, "2": 96, "3": 96},
        "h1b_membership_hash": H1B_MEMBERSHIP_HASH,
        "h1b_evaluated_cutoff_count": 0,
        "semantic_runs": 2,
        "semantic_equality": True,
        "ratings_recorded": False,
        "resource_observation": report["resource_observation"],
        "files": {
            "report.json": {
                "sha256": hashlib.sha256(report_bytes).hexdigest(),
                "byte_length": len(report_bytes),
            },
            "review_cases.json": {
                "sha256": hashlib.sha256(cases_bytes).hexdigest(),
                "byte_length": len(cases_bytes),
            },
            "review.html": {
                "sha256": hashlib.sha256(html_bytes).hexdigest(),
                "byte_length": len(html_bytes),
            },
        },
    }
    manifest = {**manifest_body, "manifest_id": _digest(manifest_body)}
    manifest_bytes = _pretty_bytes(manifest)
    _atomic_write(
        output_dir,
        {
            "report.json": report_bytes,
            "manifest.json": manifest_bytes,
            "review_cases.json": cases_bytes,
            "review.html": html_bytes,
        },
    )
    return {
        "report": report,
        "manifest": manifest,
        "resources": report["resource_observation"],
    }


def main() -> None:
    run_n4()


__all__ = [
    "AUTHORITY_HASHES",
    "H1B_MEMBERSHIP_HASH",
    "HISTORY_CAPACITY_BARS",
    "N4_4H_RANGES",
    "N4_MEMBERSHIP_HASH",
    "N4_RANGES",
    "OUTPUT_DIR",
    "PIVOT_WINDOW",
    "N4ContractError",
    "N4Measurement",
    "N4Pair",
    "N4Snapshot",
    "evaluate",
    "membership_hash",
    "membership_payload",
    "run_n4",
    "verify_authorities",
]
