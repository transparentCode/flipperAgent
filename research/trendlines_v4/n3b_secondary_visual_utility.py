"""Outcome-blind N3B secondary-geometry visual-review packet.

This module deliberately stops at a committed A/B/C review packet.  It reuses
the frozen V4 core and N3A selector as authenticated research dependencies, but
does not publish a utility score, a ranking, or an interpretation of the
blind review.
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
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import permutations
from pathlib import Path
from statistics import median
from typing import Literal

from libs.models.trendlines_v4 import core
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import parameter_sensitivity as h0
from research.trendlines_v4 import secondary_candidate_feasibility as n3a

ROOT = Path(__file__).parents[2]
PRIMARY_ROOT = Path("/Users/kajukatli/projects/flipperAgent")
OUTPUT_DIR = ROOT / "artifacts/trendlines_v4/n3b_secondary_visual_utility_v1"

PIVOT_WINDOW = 3
HISTORY_CAPACITY_BARS = 300
RSS_LIMIT_BYTES = 536_870_912
N3B_MEMBERSHIP_HASH = "42042794f9db09c8120b67a8c0d70e99c2c7f867d9b87313a22a4e1365b1360c"
H1B_MEMBERSHIP_HASH = "71bce66333b89f96d093de764f93a954add7c7e9d4f28848767ed8d67697fbda"
N3B_RANGES = (
    ("BTCUSDT", "1h", 18342, 18437),
    ("BTCUSDT", "4h", 4662, 4757),
    ("ETHUSDT", "1h", 13962, 14057),
    ("ETHUSDT", "4h", 3567, 3662),
    ("SOLUSDT", "1h", 13962, 14057),
    ("SOLUSDT", "4h", 3567, 3662),
    ("HYPEUSDT", "1h", 3397, 3492),
    ("HYPEUSDT", "4h", 925, 1020),
)
BLIND_ROLE_SET = ("structural", "current_valid", "secondary")
PUBLIC_LETTERS = ("A", "B", "C")
PUBLIC_COLORS = {"A": "purple", "B": "orange", "C": "green"}

AUTHORITY_HASHES = {
    "handoff": (
        PRIMARY_ROOT
        / "plans/architect-to-coder-trendlines-v4-n3b-secondary-visual-utility-v1.md",
        "d1c2f47d6881a858349386dfb133f513feda31c04cd696395b9fa52fae0b4eaf",
    ),
    "design": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n3b-secondary-visual-utility-design-v1.md",
        "5360f5950899f2ca8436dae67d4f7709dfd1870edd3b9d65dd0ba4949d90daae",
    ),
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n3b-secondary-visual-utility-design-approval-v1.md",
        "b1e904534ad89b1bd7337481ffb1b3b736aeffb36a085f9fd2b6657b34ed14c7",
    ),
    "n3a_approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n3a-secondary-candidate-feasibility-approval-v1.md",
        "5e169866ef2d4ea6a7beb6d3d5a8492bd5cebfe30805071c053abf9661276035",
    ),
}

HISTORICAL_PRE_MODULARIZATION_HASHES = {
    "core": "c92076e72891b222cf8359cba614c8ed969f04d1734a8985abdb0b68ffc9509f",
    "root_namespace": "66ccb45f10ab0c3b530f81919ad172fdde93b51cda04d935a6ce581641d0ac61",
    "decision_adapter": "9d65b6f1cc0d00bbd60c9f40299f47701a161eadc2d5d0ae29b28747d415e523",
    "decision_composition": "41d9d9562e48c54042b46ce9880247b4ba23769ff80d708c2ee7c15c951ee763",
}
PROTECTED_HASHES = {
    "core": (
        ROOT / "src/libs/models/trendlines_v4/core.py",
        "43cd16de5f0cff3506a83c0c153df0cbec89ee8e3c679627b1f418dc7cd52f65",
    ),
    "root_namespace": (
        ROOT / "src/libs/models/trendlines_v4/__init__.py",
        "66ccb45f10ab0c3b530f81919ad172fdde93b51cda04d935a6ce581641d0ac61",
    ),
    "decision_adapter": (
        ROOT / "src/libs/models/trendlines_v4/adapters/decision_plugin.py",
        "be920fa709cc168bedc8ccfeae6bfd75d3001e9f11c2b338f1b191dfab8b9d76",
    ),
    "decision_composition": (
        ROOT / "src/apps/decision_app/composition.py",
        "41d9d9562e48c54042b46ce9880247b4ba23769ff80d708c2ee7c15c951ee763",
    ),
}

N3A_LOCKS = {
    "source": (
        ROOT / "research/trendlines_v4/secondary_candidate_feasibility.py",
        "9ab2ed08c6f96de3201d622d272bb671794102d773ec0c6326e4b6c696dabfe9",
    ),
    "test": (
        ROOT / "tests/research/trendlines_v4/test_secondary_candidate_feasibility.py",
        "70a27df1d49c6950748733f6f8054dd4a1e616f466ce979afa833721d14cc0de",
    ),
    "report": (
        ROOT
        / "artifacts/trendlines_v4/n3a_secondary_candidate_feasibility_v1/report.json",
        "ca7054c5892705445a83b0dbc1ca4c16e1d13ffb9bfe680a557f85aa4de557b6",
    ),
    "manifest": (
        ROOT
        / "artifacts/trendlines_v4/n3a_secondary_candidate_feasibility_v1/manifest.json",
        "7f89003e4a0011ae1e0a9d2064ad8513776d1bde567ad7da462882c6b91977bf",
    ),
}


class N3BContractError(ValueError):
    """Raised when a frozen N3B contract or provenance invariant fails."""


class N3BResourceBlocked(RuntimeError):
    """Raised when the N3B process exceeds its frozen RSS ceiling."""


@dataclass(frozen=True, slots=True)
class N3BCutoff:
    """One source-owned N3B cutoff and its exact 300-bar history boundary."""

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
class N3BLine:
    """Compact source-owned line facts retained for aggregate/case construction."""

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
            "start_index": self.start_index,
            "end_index": self.end_index,
            "intercept": self.intercept,
            "fact": self.fact.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class N3BObservation:
    cutoff: N3BCutoff
    side: Literal["support", "resistance"]
    structural: N3BLine | None
    current_valid: N3BLine | None
    secondary: N3BLine | None
    positive_score_endpoint_count: int
    exact_distinct_endpoint_geometry_count: int
    exposed_exact_geometry_count: int

    @property
    def lines(self) -> tuple[N3BLine | None, ...]:
        return (self.structural, self.current_valid, self.secondary)

    @property
    def all_present(self) -> bool:
        return all(line is not None for line in self.lines)

    @property
    def pairwise_distinct(self) -> bool:
        lines = [line for line in self.lines if line is not None]
        return len(lines) == 3 and len({line.geometry_id for line in lines}) == 3

    @property
    def eligible_for_blind_case(self) -> bool:
        if not self.all_present or not self.pairwise_distinct:
            return False
        return all(
            math.isfinite(value)
            for line in self.lines
            if line is not None
            for value in (
                line.fact.projected_price,
                line.fact.slope_per_bar,
                line.fact.start_anchor_price,
                line.fact.end_anchor_price,
            )
        )

    def semantic_payload(self) -> dict[str, object]:
        return {
            "cutoff": self.cutoff.as_payload(),
            "side": self.side,
            "structural": None
            if self.structural is None
            else self.structural.as_payload(),
            "current_valid": (
                None if self.current_valid is None else self.current_valid.as_payload()
            ),
            "secondary": None
            if self.secondary is None
            else self.secondary.as_payload(),
            "positive_score_endpoint_count": self.positive_score_endpoint_count,
            "exact_distinct_endpoint_geometry_count": (
                self.exact_distinct_endpoint_geometry_count
            ),
            "exposed_exact_geometry_count": self.exposed_exact_geometry_count,
        }


@dataclass(frozen=True, slots=True)
class N3BMeasurement:
    observations: tuple[N3BObservation, ...]
    parity: dict[str, int]
    eligible_case_count: int

    def semantic_payload(self) -> dict[str, object]:
        return {
            "observations": [item.semantic_payload() for item in self.observations],
            "parity": self.parity,
            "eligible_case_count": self.eligible_case_count,
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


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise N3BContractError(f"missing locked file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_hashes(locks: dict[str, tuple[Path, str]]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, (path, expected) in locks.items():
        observed[name] = _sha256(path)
        if observed[name] != expected:
            raise N3BContractError(f"locked hash mismatch: {name}")
    return observed


def _authority_view(locks: dict[str, tuple[Path, str]]) -> dict[str, dict[str, str]]:
    return {
        name: {"path": path.as_posix(), "sha256": _sha256(path)}
        for name, (path, _) in locks.items()
    }


def verify_authorities() -> dict[str, object]:
    """Authenticate all N3B and protected prior-stage authorities."""

    observed = {
        "n3b": _authority_view(AUTHORITY_HASHES),
        "production": _authority_view(PROTECTED_HASHES),
        "n3a": _authority_view(N3A_LOCKS),
    }
    for group in observed.values():
        for name, value in group.items():
            if not value["sha256"]:
                raise N3BContractError(f"empty authority digest: {name}")
    return observed


def membership_payload() -> list[dict[str, object]]:
    return [
        {
            "asset": asset,
            "timeframe": timeframe,
            "first_source_position": first,
            "last_source_position": last,
            "cutoff_count": last - first + 1,
        }
        for asset, timeframe, first, last in N3B_RANGES
    ]


def membership_hash() -> str:
    return _digest(membership_payload())


def _assert_membership_contract() -> None:
    if membership_hash() != N3B_MEMBERSHIP_HASH:
        raise N3BContractError("N3B membership hash changed")
    if N3B_MEMBERSHIP_HASH == H1B_MEMBERSHIP_HASH:
        raise N3BContractError("N3B membership was relabeled as H1B")
    if sum(item[3] - item[2] + 1 for item in N3B_RANGES) != 768:
        raise N3BContractError("N3B membership count is not 768")
    if len({(asset, timeframe) for asset, timeframe, _, _ in N3B_RANGES}) != 8:
        raise N3BContractError("N3B membership does not cover eight streams")


def _baseline_profile(timeframe: str) -> h0.H0Profile:
    profile = n3a._baseline_profile(timeframe)
    if (
        profile.pivot_window != PIVOT_WINDOW
        or profile.effective_history_bars != HISTORY_CAPACITY_BARS
    ):
        raise N3BContractError("N3B profile is not the frozen 3/300 profile")
    return profile


def _build_cutoffs(
    streams: Sequence[h0.H0Stream],
) -> tuple[N3BCutoff, ...]:
    _assert_membership_contract()
    stream_map = {(stream.asset, stream.timeframe): stream for stream in streams}
    result: list[N3BCutoff] = []
    for asset, timeframe, first, last in N3B_RANGES:
        stream = stream_map.get((asset, timeframe))
        if stream is None:
            raise N3BContractError(f"missing N3B stream: {asset}:{timeframe}")
        if last >= len(stream.bars) or first < HISTORY_CAPACITY_BARS - 1:
            raise N3BContractError("N3B range lacks a causal 300-bar history")
        for ordinal, position in enumerate(range(first, last + 1)):
            result.append(
                N3BCutoff(
                    asset=asset,
                    timeframe=timeframe,  # type: ignore[arg-type]
                    source_position=position,
                    ordinal=ordinal,
                    market_as_of=n1._timestamp(stream.bars[position].closed_at),
                )
            )
    if len(result) != 768:
        raise N3BContractError("N3B produced the wrong number of cutoffs")
    return tuple(result)


def _history_for_cutoff(
    stream: h0.H0Stream,
    cutoff: N3BCutoff,
) -> tuple[n1.TrendlineBar, ...]:
    start = cutoff.source_position + 1 - HISTORY_CAPACITY_BARS
    stop = cutoff.source_position + 1
    source_slice = stream.bars[start:stop]
    if len(source_slice) != HISTORY_CAPACITY_BARS:
        raise N3BContractError("N3B history is not exactly 300 bars")
    history = n1._core_bars(source_slice)
    if history[-1].closed_at != stream.bars[cutoff.source_position].closed_at:
        raise N3BContractError("N3B history reads beyond its causal cutoff")
    if n1._timestamp(history[-1].closed_at) != cutoff.market_as_of:
        raise N3BContractError("N3B cutoff timestamp is not source-owned")
    return history


def _line_record(
    candidate: n3a.EndpointCandidate | None,
    fact: h0.H0LineFact | None,
    history: Sequence[core.TrendlineBar],
    role: str,
) -> N3BLine | None:
    if candidate is None or fact is None:
        if candidate is not None or fact is not None:
            raise N3BContractError("candidate/fact presence mismatch")
        return None
    start = n1._anchor_position(history, candidate.geometry.start_anchor_at)
    end = n1._anchor_position(history, candidate.geometry.end_anchor_at)
    if not 0 <= start < end < len(history):
        raise N3BContractError("line anchor is outside the causal history")
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
        raise N3BContractError("line projection is not finite")
    return N3BLine(role, fact, start, end, intercept)


def _source_line_record(
    candidate: n3a.EndpointCandidate | None,
    fact: h0.H0LineFact | None,
    history: Sequence[core.TrendlineBar],
    cutoff: N3BCutoff,
    role: str,
) -> N3BLine | None:
    if candidate is None or fact is None:
        if candidate is not None or fact is not None:
            raise N3BContractError("candidate/fact presence mismatch")
        return None
    expected = n1.geometry_id(
        n1.identity_payload(
            candidate.geometry,
            history,
            asset=cutoff.asset,
            timeframe=cutoff.timeframe,
        )
    )
    if fact.geometry_id != expected:
        raise N3BContractError("source-bound geometry identity mismatch")
    return _line_record(candidate, fact, history, role)


def _reference_secondary_selector(
    endpoints: Sequence[n3a.EndpointCandidate], exposed_ids: frozenset[str]
) -> n3a.EndpointCandidate | None:
    """Independent strict-order oracle for the frozen N3A selector."""

    selected = None
    for candidate in endpoints:
        if candidate.geometry_id in exposed_ids:
            continue
        if selected is None or candidate.score > selected.score:
            selected = candidate
    return selected


def _evaluate(
    streams: Sequence[h0.H0Stream],
) -> N3BMeasurement:
    cutoffs = _build_cutoffs(streams)
    stream_map = {(stream.asset, stream.timeframe): stream for stream in streams}
    profiles = {timeframe: _baseline_profile(timeframe) for timeframe in ("1h", "4h")}
    observations: list[N3BObservation] = []
    parity = {
        "cutoff_count": 0,
        "side_observation_count": 0,
        "p0_role_comparison_count": 0,
        "p0_same_geometry_comparison_count": 0,
        "p0_presence_mismatch_count": 0,
        "p0_geometry_mismatch_count": 0,
        "p0_fact_mismatch_count": 0,
        "n3a_secondary_selector_comparison_count": 0,
        "n3a_secondary_selector_mismatch_count": 0,
        "n3a_secondary_fact_comparison_count": 0,
        "n3a_secondary_fact_mismatch_count": 0,
        "current_valid_adverse_body_count": 0,
    }
    for cutoff in cutoffs:
        stream = stream_map[(cutoff.asset, cutoff.timeframe)]
        history = _history_for_cutoff(stream, cutoff)
        snapshot = h0.analyze_profile(profiles[cutoff.timeframe], history)
        h0_cutoff = h0.H0Cutoff(
            asset=cutoff.asset,
            timeframe=cutoff.timeframe,
            window="n3b",
            cutoff=cutoff.ordinal,
            source_position=cutoff.source_position,
            market_as_of=cutoff.market_as_of,
            partition="development",  # pure H0 fact builders require a known literal
        )
        expected_facts = h0.snapshot_facts(
            snapshot,
            history,
            profile=profiles[cutoff.timeframe],
            cutoff=h0_cutoff,
        )
        enumerations = {
            side: n3a._enumerate_side(
                history,
                side,
                asset=cutoff.asset,
                timeframe=cutoff.timeframe,
            )
            for side in n1.SIDES
        }
        actual_facts, same_counts = n3a._assert_baseline_parity(
            snapshot,
            expected_facts,
            enumerations,
            history,
            profiles,
            h0_cutoff,
        )
        parity["cutoff_count"] += 1
        parity["p0_same_geometry_comparison_count"] += same_counts[
            "same_geometry_count"
        ]
        for side in n1.SIDES:
            enumeration = enumerations[side]
            structural = enumeration.structural
            current_valid = enumeration.current_valid
            for role, candidate in (
                ("structural", structural),
                ("current_valid", current_valid),
            ):
                actual_fact = actual_facts[f"{side}.{role}"]
                expected_fact = expected_facts.line(side, role)
                expected_geometry = getattr(getattr(snapshot, side), role)
                actual_geometry = None if candidate is None else candidate.geometry
                parity["p0_role_comparison_count"] += 1
                parity["p0_presence_mismatch_count"] += int(
                    (actual_fact is None) != (expected_fact is None)
                )
                parity["p0_geometry_mismatch_count"] += int(
                    actual_geometry != expected_geometry
                )
                parity["p0_fact_mismatch_count"] += int(actual_fact != expected_fact)
            exposed = frozenset(
                candidate.geometry_id
                for candidate in (structural, current_valid)
                if candidate is not None
            )
            distinct_ids = {
                candidate.geometry_id for candidate in enumeration.endpoints
            }
            selected = n3a._select_secondary(enumeration.endpoints, exposed)
            if selected is not None and selected.geometry_id in exposed:
                raise N3BContractError("N3A selector exposed a duplicate secondary")
            reference_selected = _reference_secondary_selector(
                enumeration.endpoints, exposed
            )
            parity["n3a_secondary_selector_mismatch_count"] += int(
                selected != reference_selected
            )
            secondary = n3a._line_fact(
                selected,
                history,
                profiles[cutoff.timeframe],
                h0_cutoff,
                "secondary",
            )
            reference_secondary = (
                None
                if reference_selected is None
                else h0._line_fact(
                    reference_selected.geometry,
                    history,
                    profile=profiles[cutoff.timeframe],
                    cutoff=h0_cutoff,
                    role="secondary",
                )
            )
            parity["n3a_secondary_selector_comparison_count"] += 1
            parity["n3a_secondary_fact_comparison_count"] += 1
            parity["n3a_secondary_fact_mismatch_count"] += int(
                secondary != reference_secondary
            )
            structural_line = _source_line_record(
                structural,
                actual_facts[f"{side}.structural"],
                history,
                cutoff,
                "structural",
            )
            current_line = _source_line_record(
                current_valid,
                actual_facts[f"{side}.current_valid"],
                history,
                cutoff,
                "current_valid",
            )
            secondary_line = _source_line_record(
                selected,
                secondary,
                history,
                cutoff,
                "secondary",
            )
            if current_line is not None:
                parity["current_valid_adverse_body_count"] += int(
                    current_line.fact.post_anchor_adverse_body_bar_count != 0
                )
            observations.append(
                N3BObservation(
                    cutoff=cutoff,
                    side=side,  # type: ignore[arg-type]
                    structural=structural_line,
                    current_valid=current_line,
                    secondary=secondary_line,
                    positive_score_endpoint_count=len(enumeration.endpoints),
                    exact_distinct_endpoint_geometry_count=len(distinct_ids),
                    exposed_exact_geometry_count=len(distinct_ids & exposed),
                )
            )
    parity["side_observation_count"] = len(observations)
    if parity["cutoff_count"] != 768 or len(observations) != 1536:
        raise N3BContractError("N3B observation inventory is incomplete")
    if parity["current_valid_adverse_body_count"] != 0:
        raise N3BContractError("N3B current-valid adverse-body invariant failed")
    return N3BMeasurement(
        observations=tuple(observations),
        parity=parity,
        eligible_case_count=sum(
            int(observation.eligible_for_blind_case) for observation in observations
        ),
    )


def _distribution(values: Sequence[float | int]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "p90": None,
            "max": None,
        }
    clean = [float(value) for value in values]
    return {
        "count": len(clean),
        "min": min(clean),
        "median": median(clean),
        "p90": n1._percentile(clean, 0.90),
        "max": max(clean),
    }


def _secondary_run_facts(rows: Sequence[N3BObservation]) -> dict[str, int]:
    ordered = sorted(rows, key=lambda row: row.cutoff.source_position)
    observed = [
        row.secondary.geometry_id if row.secondary is not None else None
        for row in ordered
    ]
    runs = 0
    replacements = 0
    for index, value in enumerate(observed):
        if value is None:
            continue
        if index == 0 or observed[index - 1] is None:
            runs += 1
        elif observed[index - 1] != value:
            replacements += 1
    return {
        "observed_cutoff_count": sum(value is not None for value in observed),
        "observed_run_count": runs,
        "replacement_count": replacements,
    }


def _separation_bps(observation: N3BObservation) -> float | None:
    secondary = observation.secondary
    if (
        secondary is None
        or observation.structural is None
        or observation.current_valid is None
    ):
        return None
    close = secondary.fact.projected_price
    if close <= 0 or not math.isfinite(close):
        return None
    distances = (
        abs(
            secondary.fact.projected_price - observation.structural.fact.projected_price
        ),
        abs(
            secondary.fact.projected_price
            - observation.current_valid.fact.projected_price
        ),
    )
    return min(distances) / close * 10_000


def _fact_pool_report(observations: Sequence[N3BObservation]) -> dict[str, object]:
    groups: dict[tuple[str, str, str], list[N3BObservation]] = defaultdict(list)
    for observation in observations:
        groups[
            (
                observation.cutoff.asset,
                observation.cutoff.timeframe,
                observation.side,
            )
        ].append(observation)
    result: dict[str, object] = {}
    for key, rows in sorted(groups.items()):
        asset, timeframe, side = key
        present = [row for row in rows if row.all_present]
        distinct = [row for row in present if row.pairwise_distinct]
        duplicate_count = sum(
            int(row.all_present and not row.pairwise_distinct) for row in rows
        )
        projection_counts = {
            role: sum(
                int(line is not None and line.fact.projection_non_positive)
                for line in (getattr(row, role) for row in rows)
            )
            for role in BLIND_ROLE_SET
        }
        current_available = [row.current_valid for row in rows if row.current_valid]
        adverse_count = sum(
            int(line.fact.post_anchor_adverse_body_bar_count != 0)
            for line in current_available
        )
        separations = [
            value
            for value in (_separation_bps(row) for row in rows)
            if value is not None
        ]
        result[f"{asset}:{timeframe}:{side}"] = {
            "cutoff_count": len(rows),
            "availability_count": {
                role: sum(getattr(row, role) is not None for row in rows)
                for role in BLIND_ROLE_SET
            },
            "three_distinct_count": len(distinct),
            "three_distinct_rate": len(distinct) / len(rows) if rows else 0.0,
            "duplicate_geometry_count": duplicate_count,
            "projection_non_positive_count": projection_counts,
            "current_valid_adverse_body_count": adverse_count,
            "current_valid_adverse_body_rate": (
                adverse_count / len(current_available) if current_available else 0.0
            ),
            "secondary_run_facts": _secondary_run_facts(rows),
            "secondary_projected_separation_bps": _distribution(separations),
        }
    return result


def _scope_hash(observation: N3BObservation) -> str:
    return _digest(
        {
            "asset": observation.cutoff.asset,
            "timeframe": observation.cutoff.timeframe,
            "source_position": observation.cutoff.source_position,
            "side": observation.side,
        }
    )


def _role_permutation(scope_hash: str) -> tuple[str, str, str]:
    choices = tuple(permutations(BLIND_ROLE_SET))
    ordinal = int(hashlib.sha256(f"n3b-role-v1|{scope_hash}".encode()).hexdigest(), 16)
    return choices[ordinal % len(choices)]


def _select_cases(measurement: N3BMeasurement) -> tuple[N3BObservation, ...]:
    groups: dict[tuple[str, str, str], list[N3BObservation]] = defaultdict(list)
    for observation in measurement.observations:
        if observation.eligible_for_blind_case:
            groups[
                (
                    observation.cutoff.asset,
                    observation.cutoff.timeframe,
                    observation.side,
                )
            ].append(observation)
    if not groups:
        raise N3BContractError(
            "N3B_INSUFFICIENT_THREE_DISTINCT_GEOMETRY_CASES: empty pool"
        )
    for rows in groups.values():
        rows.sort(key=_scope_hash)
    selected = [rows[0] for _, rows in sorted(groups.items())]
    selected_scopes = {_scope_hash(item) for item in selected}
    target_timeframes = {"1h": 8, "4h": 8}
    target_sides = {"support": 8, "resistance": 8}
    target_assets = {asset: 2 for asset in {asset for asset, _, _, _ in N3B_RANGES}}
    while len(selected) < 16:
        timeframe_counts = Counter(item.cutoff.timeframe for item in selected)
        side_counts = Counter(item.side for item in selected)
        asset_counts = Counter(item.cutoff.asset for item in selected)
        candidates = [
            row
            for rows in groups.values()
            for row in rows
            if _scope_hash(row) not in selected_scopes
        ]
        balanced = [
            row
            for row in candidates
            if timeframe_counts[row.cutoff.timeframe]
            < target_timeframes[row.cutoff.timeframe]
            and side_counts[row.side] < target_sides[row.side]
            and asset_counts[row.cutoff.asset] < target_assets[row.cutoff.asset]
        ]
        if balanced:
            candidates = balanced
        else:
            candidates = [
                row
                for row in candidates
                if timeframe_counts[row.cutoff.timeframe]
                < target_timeframes[row.cutoff.timeframe]
                and side_counts[row.side] < target_sides[row.side]
            ]
        if not candidates:
            raise N3BContractError(
                "N3B_INSUFFICIENT_THREE_DISTINCT_GEOMETRY_CASES: "
                "exact balance cannot be filled"
            )
        chosen = min(candidates, key=_scope_hash)
        selected.append(chosen)
        selected_scopes.add(_scope_hash(chosen))
    selected.sort(key=_scope_hash)
    if len(selected) != 16:
        raise N3BContractError("N3B did not select exactly 16 cases")
    if sum(item.cutoff.timeframe == "1h" for item in selected) != 8:
        raise N3BContractError("N3B case packet is not balanced across 1h")
    if sum(item.cutoff.timeframe == "4h" for item in selected) != 8:
        raise N3BContractError("N3B case packet is not balanced across 4h")
    if sum(item.side == "support" for item in selected) != 8:
        raise N3BContractError("N3B case packet is not balanced across support")
    if sum(item.side == "resistance" for item in selected) != 8:
        raise N3BContractError("N3B case packet is not balanced across resistance")
    if {item.cutoff.asset for item in selected} != {
        asset for asset, _, _, _ in N3B_RANGES
    }:
        raise N3BContractError("N3B packet omitted a frozen asset")
    return tuple(selected)


def _public_line(
    letter: str,
    line: N3BLine,
    display_start: int,
    display_end: int,
) -> dict[str, object]:
    if (
        not display_start <= line.start_index <= display_end
        or not display_start <= line.end_index <= display_end
    ):
        raise N3BContractError("blind case omitted a line anchor")
    return {
        "color": PUBLIC_COLORS[letter],
        "start_anchor": {
            "bar_offset": line.start_index - display_start,
            "price": line.fact.start_anchor_price,
        },
        "end_anchor": {
            "bar_offset": line.end_index - display_start,
            "price": line.fact.end_anchor_price,
        },
        "slope_per_bar": line.fact.slope_per_bar,
        "projected_price": line.fact.projected_price,
        "projection_positive": line.fact.projection_positive,
    }


def _build_public_cases(
    selected: Sequence[N3BObservation],
    streams: Sequence[h0.H0Stream],
) -> tuple[dict[str, object], ...]:
    stream_map = {(stream.asset, stream.timeframe): stream for stream in streams}
    cases: list[dict[str, object]] = []
    for number, observation in enumerate(selected, 1):
        lines = [line for line in observation.lines if line is not None]
        earliest_anchor = min(line.start_index for line in lines)
        display_start = max(0, earliest_anchor - 5)
        display_end = HISTORY_CAPACITY_BARS - 1
        stream = stream_map[(observation.cutoff.asset, observation.cutoff.timeframe)]
        source_start = (
            observation.cutoff.source_position
            + 1
            - HISTORY_CAPACITY_BARS
            + display_start
        )
        source_end = observation.cutoff.source_position + 1
        source_bars = stream.bars[source_start:source_end]
        if len(source_bars) != display_end - display_start + 1:
            raise N3BContractError(
                "blind case does not contain the complete causal display"
            )
        scope_hash = _scope_hash(observation)
        permutation = _role_permutation(scope_hash)
        role_by_letter = dict(zip(PUBLIC_LETTERS, permutation))
        public_lines = {}
        for letter, role in role_by_letter.items():
            line = getattr(observation, role)
            if line is None:
                raise N3BContractError("blind case role unexpectedly absent")
            public_lines[letter] = _public_line(
                letter, line, display_start, display_end
            )
        cases.append(
            {
                "case_id": f"n3b-{number:02d}-{scope_hash[:12]}",
                "asset": observation.cutoff.asset,
                "timeframe": observation.cutoff.timeframe,
                "side": observation.side,
                "source_position": observation.cutoff.source_position,
                "market_as_of": observation.cutoff.market_as_of,
                "display_start_source_position": source_start,
                "display_end_source_position": observation.cutoff.source_position,
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
                "lines": public_lines,
                "anchor_complete": True,
                "causal_cutoff_only": True,
            }
        )
    return tuple(cases)


def _hidden_mapping(
    selected: Sequence[N3BObservation],
) -> list[dict[str, object]]:
    return [
        {
            "case_id": f"n3b-{number:02d}-{_scope_hash(observation)[:12]}",
            "A": _role_permutation(_scope_hash(observation))[0],
            "B": _role_permutation(_scope_hash(observation))[1],
            "C": _role_permutation(_scope_hash(observation))[2],
        }
        for number, observation in enumerate(selected, 1)
    ]


def _svg(case: dict[str, object]) -> str:
    bars = case["bars"]
    lines = case["lines"]
    width = max(2200, 8 * len(bars) + 80)
    height = 720
    left, right, top, bottom = 48, width - 48, 36, 580
    values = [value for bar in bars for value in (bar["high"], bar["low"])]
    for line in lines.values():
        values.append(float(line["projected_price"]))
        anchor_offset = line["start_anchor"]["bar_offset"]
        anchor_price = line["start_anchor"]["price"]
        slope = line["slope_per_bar"]
        values.extend(
            (
                anchor_price - slope * anchor_offset,
                anchor_price + slope * (len(bars) - 1 - anchor_offset),
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
            f'data-case="{html.escape(str(case["case_id"]), quote=True)}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            f'<text x="48" y="22" font-family="sans-serif" font-size="16">'
            f"{html.escape(str(case['asset']))} · {html.escape(str(case['timeframe']))} · "
            f"{html.escape(str(case['side']))} · cutoff {case['source_position']}</text>"
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
    for letter in PUBLIC_LETTERS:
        line = lines[letter]
        start = line["start_anchor"]["bar_offset"]
        slope = line["slope_per_bar"]
        start_price = line["start_anchor"]["price"]
        fragments.append(
            f'<line x1="{x(0):.3f}" '
            f'y1="{y(start_price - slope * start):.3f}" '
            f'x2="{x(len(bars) - 1):.3f}" '
            f'y2="{y(start_price + slope * (len(bars) - 1 - start)):.3f}" '
            f'stroke="{line["color"]}" stroke-width="2.5" '
            f'data-line="{letter}"/>'
        )
        for anchor, point in (
            ("start", line["start_anchor"]),
            ("end", line["end_anchor"]),
        ):
            offset = point["bar_offset"]
            fragments.append(
                f'<circle cx="{x(offset):.3f}" cy="{y(point["price"]):.3f}" '
                f'r="5" fill="{line["color"]}" data-anchor="{letter}-{anchor}">'
                f"<title>{letter} {anchor} anchor</title></circle>"
            )
    fragments.extend(
        [
            (
                f'<line x1="{left}" x2="{right}" y1="{y(bars[-1]["close"]):.3f}" '
                f'y2="{y(bars[-1]["close"]):.3f}" stroke="#555" stroke-dasharray="5 4"/>'
            ),
            (
                '<text x="48" y="620" font-family="sans-serif" font-size="13">'
                "A purple · B orange · C green · anchors are marked</text>"
            ),
            (
                '<text x="48" y="645" font-family="sans-serif" font-size="12">'
                "Use the controls below to record which line(s) are useful as market context or an invalidation/risk reference.</text>"
            ),
            "</svg>",
        ]
    )
    return "".join(fragments)


def _html(cases: Sequence[dict[str, object]]) -> str:
    sections: list[str] = []
    for case in cases:
        case_id = html.escape(str(case["case_id"]), quote=True)
        options = "".join(
            f'<label><input type="checkbox" name="useful-{case_id}" value="{value}">{value}</label>'
            for value in ("A", "B", "C", "A+B", "A+C", "B+C", "A+B+C", "NONE")
        )
        clutter = "".join(
            f'<label><input type="radio" name="clutter-{case_id}" value="{value}">{value}</label>'
            for value in ("CLUTTERED", "NOT_CLUTTERED", "UNSURE")
        )
        sections.append(
            '<section class="case">'
            f"<h2>{case_id} · {html.escape(str(case['asset']))} · "
            f"{html.escape(str(case['timeframe']))} · {html.escape(str(case['side']))}</h2>"
            '<div class="chart-scroll">'
            f"{_svg(case)}"
            "</div>"
            "<fieldset><legend>Useful line(s) for this context</legend>"
            f"{options}</fieldset>"
            "<fieldset><legend>Chart clutter</legend>"
            f"{clutter}</fieldset>"
            "</section>"
        )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Blinded V4 geometry review</title>"
        "<style>body{font-family:sans-serif;margin:24px;background:#f5f5f5;}"
        ".case{background:white;padding:18px;margin:24px 0;border:1px solid #bbb;}"
        ".chart-scroll{overflow-x:auto;border:1px solid #ddd;background:white;}"
        "fieldset{display:inline-block;margin:12px 12px 0 0;border:1px solid #bbb;}"
        "label{margin-right:12px;white-space:nowrap;}</style></head><body>"
        "<h1>Blinded geometry review</h1>"
        "<p>Review all cases before any identity is revealed. Choose useful line(s) "
        "for market context or invalidation/risk reference, then rate clutter separately. "
        "These controls are descriptive only and do not select a preferred line.</p>"
        + "".join(sections)
        + "</body></html>\n"
    )


def _report(measurement: N3BMeasurement) -> dict[str, object]:
    selected = _select_cases(measurement)
    mapping = _hidden_mapping(selected)
    permutation_set = {
        tuple(item[letter] for letter in PUBLIC_LETTERS) for item in mapping
    }
    if len(permutation_set) <= 1:
        raise N3BContractError("N3B role permutation is constant")
    return {
        "schema": "trendlines.v4.n3b.secondary-visual-utility.v1",
        "disposition": "N3B_BLIND_REVIEW_READY",
        "membership": {
            "cutoff_count": 768,
            "stream_count": 8,
            "membership_hash": N3B_MEMBERSHIP_HASH,
            "ranges": membership_payload(),
        },
        "inventory": {
            "cutoff_count": 768,
            "side_observation_count": 1536,
            "eligible_three_distinct_observation_count": measurement.eligible_case_count,
            "selected_case_count": len(selected),
        },
        "parity": measurement.parity,
        "factual_pool_evidence": _fact_pool_report(measurement.observations),
        "blind_review": {
            "case_count": len(selected),
            "one_hour_case_count": sum(
                item.cutoff.timeframe == "1h" for item in selected
            ),
            "four_hour_case_count": sum(
                item.cutoff.timeframe == "4h" for item in selected
            ),
            "support_case_count": sum(item.side == "support" for item in selected),
            "resistance_case_count": sum(
                item.side == "resistance" for item in selected
            ),
            "mapping_commitment": _digest(mapping),
            "mapping_count": len(mapping),
            "role_permutation_distinct_count": len(permutation_set),
            "identity_revealed": False,
            "ratings_recorded": False,
        },
        "h1b": {
            "membership_hash": H1B_MEMBERSHIP_HASH,
            "results_published": False,
            "evaluated_cutoff_count": 0,
        },
    }


def _resource_record(start_wall: float, start_cpu: float) -> dict[str, object]:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak = value if sys.platform == "darwin" else value * 1024
    return {
        "wall_seconds": time.perf_counter() - start_wall,
        "cpu_seconds": time.process_time() - start_cpu,
        "peak_process_rss_bytes": peak,
    }


def _artifact_bytes(
    measurement: N3BMeasurement,
    streams: Sequence[h0.H0Stream],
) -> tuple[dict[str, object], bytes, bytes, bytes]:
    report = _report(measurement)
    selected = _select_cases(measurement)
    public_cases = _build_public_cases(selected, streams)
    if len(public_cases) != 16:
        raise N3BContractError("blind case count is not 16")
    mapping = _hidden_mapping(selected)
    commitment = _digest(mapping)
    blind = {
        "schema": "trendlines.v4.n3b.secondary-visual-utility-blind-cases.v1",
        "case_count": len(public_cases),
        "cases": public_cases,
        "mapping_commitment": commitment,
        "mapping_count": len(mapping),
        "identity_revealed": False,
        "ratings_recorded": False,
    }
    if report["blind_review"]["mapping_commitment"] != commitment:  # type: ignore[index]
        raise N3BContractError("blind mapping commitment is inconsistent")
    html_bytes = _html(public_cases).encode("utf-8")
    return report, _pretty_bytes(report), _pretty_bytes(blind), html_bytes


def _semantic_view(
    measurement: N3BMeasurement,
    streams: Sequence[h0.H0Stream],
) -> tuple[bytes, bytes, bytes, bytes]:
    report, _report_bytes, blind_bytes, html_bytes = _artifact_bytes(
        measurement, streams
    )
    return (
        _canonical_bytes(measurement.semantic_payload()),
        _canonical_bytes(report),
        blind_bytes,
        html_bytes,
    )


def _atomic_write(output_dir: Path, files: dict[str, bytes]) -> None:
    if output_dir.exists():
        raise N3BContractError("N3B output directory already exists")
    temp = output_dir.with_name(output_dir.name + ".tmp")
    if temp.exists():
        raise N3BContractError("N3B temporary output directory already exists")
    try:
        temp.mkdir(parents=True)
        for name, data in files.items():
            (temp / name).write_bytes(data)
        os.replace(temp, output_dir)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise


def run_n3b(output_dir: Path = OUTPUT_DIR) -> dict[str, object]:
    """Run the exact two-pass N3B evaluation and publish only blind artifacts."""

    authority = verify_authorities()
    _assert_membership_contract()
    if output_dir.exists():
        raise N3BContractError("N3B output target must be absent before execution")
    streams = h0.build_streams()
    first_start_wall = time.perf_counter()
    first_start_cpu = time.process_time()
    first = _evaluate(streams)
    first_resources = _resource_record(first_start_wall, first_start_cpu)
    second_start_wall = time.perf_counter()
    second_start_cpu = time.process_time()
    second = _evaluate(streams)
    second_resources = _resource_record(second_start_wall, second_start_cpu)
    first_semantic = _semantic_view(first, streams)
    second_semantic = _semantic_view(second, streams)
    if first_semantic != second_semantic:
        raise N3BContractError("N3B semantic runs are not exactly equal")
    for record in (first_resources, second_resources):
        if int(record["peak_process_rss_bytes"]) > RSS_LIMIT_BYTES:
            raise N3BResourceBlocked("N3B peak RSS exceeded 512 MiB")
    report, report_bytes, blind_bytes, html_bytes = _artifact_bytes(first, streams)
    report = dict(report)
    report["authority"] = authority
    report["determinism"] = {
        "semantic_runs": 2,
        "exact_semantic_equality": True,
        "semantic_digest": hashlib.sha256(
            _canonical_bytes(first.semantic_payload())
        ).hexdigest(),
    }
    report["resource_observation"] = {
        "rss_limit_bytes": RSS_LIMIT_BYTES,
        "first": first_resources,
        "second": second_resources,
    }
    report_bytes = _pretty_bytes(report)
    manifest_body: dict[str, object] = {
        "schema": "trendlines.v4.n3b.secondary-visual-utility-manifest.v1",
        "disposition": "N3B_BLIND_REVIEW_READY",
        "authority": authority,
        "membership_hash": N3B_MEMBERSHIP_HASH,
        "membership_count": 768,
        "h1b_membership_hash": H1B_MEMBERSHIP_HASH,
        "h1b_results_published": False,
        "semantic_runs": 2,
        "semantic_equality": True,
        "mapping_commitment": report["blind_review"]["mapping_commitment"],
        "mapping_count": 16,
        "identity_revealed": False,
        "ratings_recorded": False,
        "resource_observation": report["resource_observation"],
        "files": {
            "report.json": {
                "sha256": hashlib.sha256(report_bytes).hexdigest(),
                "byte_length": len(report_bytes),
            },
            "blind_cases.json": {
                "sha256": hashlib.sha256(blind_bytes).hexdigest(),
                "byte_length": len(blind_bytes),
            },
            "blind_review.html": {
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
            "blind_cases.json": blind_bytes,
            "blind_review.html": html_bytes,
        },
    )
    return {
        "report": report,
        "manifest": manifest,
        "resources": report["resource_observation"],
    }


def main() -> None:
    run_n3b()


__all__ = [
    "AUTHORITY_HASHES",
    "H1B_MEMBERSHIP_HASH",
    "HISTORY_CAPACITY_BARS",
    "N3A_LOCKS",
    "N3B_MEMBERSHIP_HASH",
    "N3B_RANGES",
    "OUTPUT_DIR",
    "PIVOT_WINDOW",
    "PROTECTED_HASHES",
    "N3BContractError",
    "N3BCutoff",
    "N3BLine",
    "N3BObservation",
    "N3BResourceBlocked",
    "_build_cutoffs",
    "_build_public_cases",
    "_canonical_bytes",
    "_digest",
    "_evaluate",
    "_role_permutation",
    "_select_cases",
    "membership_hash",
    "membership_payload",
    "run_n3b",
    "verify_authorities",
]


if __name__ == "__main__":
    main()
