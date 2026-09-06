"""Outcome-blind feasibility measurement for one exact V4 secondary per side."""

from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from libs.models.trendlines_v4 import core
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import parameter_sensitivity as h0

ROOT = Path(__file__).parents[2]
PRIMARY_ROOT = Path("/Users/kajukatli/projects/flipperAgent")
OUTPUT_DIR = ROOT / "artifacts/trendlines_v4/n3a_secondary_candidate_feasibility_v1"

PIVOT_WINDOW = 3
HISTORY_CAPACITY_BARS = 300
DEVELOPMENT_MEMBERSHIP_HASH = (
    "e3104d4cc9822abe23c45f566266b5149107b27d65088e7b4f8fa1739fe555d8"
)
H1B_MEMBERSHIP_HASH = "71bce66333b89f96d093de764f93a954add7c7e9d4f28848767ed8d67697fbda"
N3B_MEMBERSHIP_HASH = "42042794f9db09c8120b67a8c0d70e99c2c7f867d9b87313a22a4e1365b1360c"
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
RSS_LIMIT_BYTES = 512 * 1024 * 1024
ALLOWED_CONCLUSIONS = (
    "SECONDARY_CANDIDATE_FEASIBILITY_MEASURED",
    "SECONDARY_CANDIDATE_SPARSE_OR_REDUNDANT",
    "SECONDARY_CANDIDATE_PATHOLOGICAL",
    "SECONDARY_CANDIDATE_NUMERICAL_SEMANTICS_BLOCKED",
    "BLOCKED_SOURCE_OR_CONTRACT",
)

AUTHORITY_HASHES = {
    "handoff": (
        PRIMARY_ROOT
        / "plans/architect-to-coder-trendlines-v4-n3a-secondary-candidate-feasibility-v1.md",
        "e566f16f658e62e0b00c8cd3e6e6f3a173921556684a9ce4ff8bd724d5774b7a",
    ),
    "design": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n3a-secondary-candidate-feasibility-design-v1.md",
        "5227a0598c314811600b3bf9753d91e999744acd95090c2d3c715857f7919326",
    ),
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n3a-secondary-candidate-feasibility-design-approval-v1.md",
        "cfeec114a9dd5a9c8fd6f630741d2c1e7f9e6aed2765ceec445a7fb543251904",
    ),
    "h1_decision": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-h1-profile-challenge-unblinded-decision-v1.md",
        "c7b3f670f23dbf148fbcafb355f9f50317d4e477e05e37fc5466d0e2ada182a4",
    ),
}


class N3AContractError(ValueError):
    """Raised when a frozen N3A contract or parity invariant fails."""


class N3AResourceBlocked(RuntimeError):
    """Raised when the N3A process exceeds the frozen RSS ceiling."""


@dataclass(frozen=True, slots=True)
class EndpointCandidate:
    """One transient positive-score endpoint and its emitted final segment."""

    endpoint_index: int
    score: int
    path: tuple[core.PathPoint, ...]
    line: object
    geometry: core.TrendlineGeometry
    geometry_id: str


@dataclass(frozen=True, slots=True)
class SideEnumeration:
    pivots: tuple[core.PathPoint, ...]
    scores: tuple[tuple[int, int], ...]
    predecessors: tuple[tuple[int, int], ...]
    endpoints: tuple[EndpointCandidate, ...]
    structural: EndpointCandidate | None
    current_valid: EndpointCandidate | None


@dataclass(frozen=True, slots=True)
class N3AObservation:
    cutoff: h0.H0Cutoff
    side: str
    structural: h0.H0LineFact | None
    current_valid: h0.H0LineFact | None
    secondary: h0.H0LineFact | None
    secondary_score: int | None
    secondary_endpoint_index: int | None
    positive_score_endpoint_count: int
    exact_distinct_endpoint_geometry_count: int
    already_exposed_exact_geometry_count: int
    remaining_alternate_exact_geometry_count: int
    current_close: float

    @property
    def secondary_geometry_id(self) -> str | None:
        return None if self.secondary is None else self.secondary.geometry_id

    @property
    def structural_geometry_id(self) -> str | None:
        return None if self.structural is None else self.structural.geometry_id

    @property
    def current_valid_geometry_id(self) -> str | None:
        return None if self.current_valid is None else self.current_valid.geometry_id

    def as_payload(self) -> dict[str, object]:
        selected = None
        if self.secondary is not None:
            selected = self.secondary.as_payload()
            selected["legacy_score"] = self.secondary_score
            selected["endpoint_index"] = self.secondary_endpoint_index
        return {
            "asset": self.cutoff.asset,
            "timeframe": self.cutoff.timeframe,
            "window": self.cutoff.window,
            "cutoff": self.cutoff.cutoff,
            "source_position": self.cutoff.source_position,
            "market_as_of": self.cutoff.market_as_of,
            "side": self.side,
            "structural_geometry_id": (
                None if self.structural is None else self.structural.geometry_id
            ),
            "current_valid_geometry_id": (
                None if self.current_valid is None else self.current_valid.geometry_id
            ),
            "candidate_pool": {
                "positive_score_endpoint_count": self.positive_score_endpoint_count,
                "exact_distinct_endpoint_geometry_count": self.exact_distinct_endpoint_geometry_count,
                "already_exposed_exact_geometry_count": self.already_exposed_exact_geometry_count,
                "remaining_alternate_exact_geometry_count": self.remaining_alternate_exact_geometry_count,
                "secondary_available": self.secondary is not None,
            },
            "selected_secondary": selected,
        }


@dataclass(frozen=True, slots=True)
class N3AMeasurement:
    observations: tuple[N3AObservation, ...]
    baseline_parity: dict[str, object]


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
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_hashes(
    locks: dict[str, tuple[Path, str]],
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, (path, expected) in locks.items():
        if not path.is_file():
            raise N3AContractError(f"missing locked file: {path}")
        actual = _sha256(path)
        if actual != expected:
            raise N3AContractError(f"locked hash mismatch: {name}")
        observed[name] = actual
    return observed


def _authority_view(
    locks: dict[str, tuple[Path, str]],
) -> dict[str, dict[str, str]]:
    return {
        name: {
            "path": path.as_posix(),
            "sha256": _verify_hashes({name: (path, expected)})[name],
        }
        for name, (path, expected) in locks.items()
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _distribution(values: Sequence[float | int]) -> dict[str, object]:
    clean = [float(value) for value in values]
    if not clean:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "max": None,
        }
    return {
        "count": len(clean),
        "min": min(clean),
        "median": median(clean),
        "p75": n1._percentile(clean, 0.75),
        "p90": n1._percentile(clean, 0.90),
        "p95": n1._percentile(clean, 0.95),
        "max": max(clean),
    }


def _baseline_profile(timeframe: str) -> h0.H0Profile:
    profiles = h0.profiles_for_timeframe(timeframe)  # type: ignore[arg-type]
    matches = tuple(profile for profile in profiles if profile.is_baseline)
    if len(matches) != 1 or matches[0].pivot_window != PIVOT_WINDOW:
        raise N3AContractError("baseline profile is not the fixed 3/300 profile")
    if matches[0].effective_history_bars != HISTORY_CAPACITY_BARS:
        raise N3AContractError("baseline history is not exactly 300 bars")
    return matches[0]


def _enumerate_side(
    history: Sequence[core.TrendlineBar],
    side: str,
    *,
    asset: str,
    timeframe: str,
) -> SideEnumeration:
    pivots = tuple(core._pivots(history, side))  # type: ignore[arg-type]
    scores = {index: 0 for index, _ in pivots}
    predecessors = {index: -1 for index, _ in pivots}
    for current_position, (current_index, current_price) in enumerate(pivots):
        for previous_position in range(current_position):
            previous_index, previous_price = pivots[previous_position]
            if not core._segment_is_valid(
                history,
                previous_index,
                previous_price,
                current_index,
                current_price,
                side,  # type: ignore[arg-type]
            ):
                continue
            new_score = scores[previous_index] + current_index - previous_index
            if new_score > scores[current_index]:
                scores[current_index] = new_score
                predecessors[current_index] = previous_index
    positions = {index: position for position, (index, _) in enumerate(pivots)}
    prices = dict(pivots)
    endpoints: list[EndpointCandidate] = []
    for endpoint_index, score in scores.items():
        if score <= 0:
            continue
        path = core._reconstruct_path(endpoint_index, prices, predecessors, positions)
        line = core._build_line(path, len(history) - 1)
        if line is None:
            raise N3AContractError("positive endpoint did not produce a line")
        geometry = core._geometry(history, side, line)  # type: ignore[arg-type]
        if geometry is None:
            raise N3AContractError("positive endpoint geometry is missing")
        geometry_id = n1.geometry_id(
            n1.identity_payload(
                geometry,
                history,
                asset=asset,
                timeframe=timeframe,  # type: ignore[arg-type]
            )
        )
        endpoints.append(
            EndpointCandidate(
                endpoint_index=endpoint_index,
                score=score,
                path=path,
                line=line,
                geometry=geometry,
                geometry_id=geometry_id,
            )
        )
    by_endpoint = {candidate.endpoint_index: candidate for candidate in endpoints}
    structural = None
    if scores:
        best_endpoint = max(scores, key=scores.__getitem__)
        if scores[best_endpoint] > 0:
            structural = by_endpoint[best_endpoint]
    current_valid = None
    for candidate in endpoints:
        if candidate.geometry.post_anchor_body_cross_count != 0:
            continue
        if current_valid is None or candidate.score > current_valid.score:
            current_valid = candidate
    return SideEnumeration(
        pivots=pivots,
        scores=tuple(scores.items()),
        predecessors=tuple(predecessors.items()),
        endpoints=tuple(endpoints),
        structural=structural,
        current_valid=current_valid,
    )


def _select_secondary(
    endpoints: Sequence[EndpointCandidate], exposed_ids: frozenset[str]
) -> EndpointCandidate | None:
    selected = None
    for candidate in endpoints:
        if candidate.geometry_id in exposed_ids:
            continue
        if selected is None or candidate.score > selected.score:
            selected = candidate
    return selected


def _validate_development_cutoff(
    stream: h0.H0Stream,
    cutoff: h0.H0Cutoff,
) -> None:
    if cutoff.partition != "development":
        raise N3AContractError("N3A received a sealed holdout cutoff")
    if cutoff.asset != stream.asset or cutoff.timeframe != stream.timeframe:
        raise N3AContractError("cutoff does not belong to its stream")


def _line_fact(
    candidate: EndpointCandidate | None,
    history: Sequence[core.TrendlineBar],
    profile: h0.H0Profile,
    cutoff: h0.H0Cutoff,
    role: str,
) -> h0.H0LineFact | None:
    if candidate is None:
        return None
    return h0._line_fact(  # type: ignore[arg-type]
        candidate.geometry,
        history,
        profile=profile,
        cutoff=cutoff,
        role=role,
    )


def _assert_baseline_parity(
    snapshot: core.TrendlineSnapshot,
    expected_facts: h0.H0Snapshot,
    enumerations: dict[str, SideEnumeration],
    history: Sequence[core.TrendlineBar],
    profiles: dict[str, h0.H0Profile],
    cutoff: h0.H0Cutoff,
) -> tuple[dict[str, h0.H0LineFact | None], dict[str, int]]:
    actual_facts: dict[str, h0.H0LineFact | None] = {}
    same_geometry_count = 0
    for side in n1.SIDES:
        enumeration = enumerations[side]
        side_snapshot = getattr(snapshot, side)
        structural = _line_fact(
            enumeration.structural,
            history,
            profiles[cutoff.timeframe],
            cutoff,
            "structural",
        )
        current_valid = _line_fact(
            enumeration.current_valid,
            history,
            profiles[cutoff.timeframe],
            cutoff,
            "current_valid",
        )
        for role, candidate, actual in (
            ("structural", enumeration.structural, structural),
            ("current_valid", enumeration.current_valid, current_valid),
        ):
            expected_geometry = getattr(side_snapshot, role)
            actual_geometry = None if candidate is None else candidate.geometry
            expected_fact = expected_facts.line(side, role)
            if actual_geometry != expected_geometry or actual != expected_fact:
                raise N3AContractError(
                    f"P0 exact parity failed at {cutoff.key()} {side}.{role}"
                )
            actual_facts[f"{side}.{role}"] = actual
        expected_same = side_snapshot.same_geometry
        actual_same = (
            structural is not None
            and current_valid is not None
            and structural.geometry_id == current_valid.geometry_id
        )
        if actual_same != expected_same:
            raise N3AContractError(
                f"same-geometry parity failed at {cutoff.key()} {side}"
            )
        same_geometry_count += int(actual_same)
    return actual_facts, {"same_geometry_count": same_geometry_count}


def _measure(streams: Sequence[h0.H0Stream]) -> N3AMeasurement:
    profiles = {timeframe: _baseline_profile(timeframe) for timeframe in ("1h", "4h")}
    observations: list[N3AObservation] = []
    parity = {
        "development_cutoff_count": 0,
        "role_comparison_count": 0,
        "same_geometry_comparison_count": 0,
        "structural_presence_mismatch_count": 0,
        "current_valid_presence_mismatch_count": 0,
        "geometry_field_mismatch_count": 0,
        "exact_n1_geometry_id_mismatch_count": 0,
        "post_anchor_crossing_mismatch_count": 0,
        "projection_positive_mismatch_count": 0,
        "current_valid_adverse_body_count": 0,
    }
    for stream in streams:
        for cutoff in stream.development:
            _validate_development_cutoff(stream, cutoff)
            history = h0._history_for_cutoff(stream, cutoff, HISTORY_CAPACITY_BARS)
            snapshot = h0.analyze_profile(profiles[cutoff.timeframe], history)
            expected_facts = h0.snapshot_facts(
                snapshot,
                history,
                profile=profiles[cutoff.timeframe],
                cutoff=cutoff,
            )
            enumerations = {
                side: _enumerate_side(
                    history,
                    side,
                    asset=stream.asset,
                    timeframe=stream.timeframe,
                )
                for side in n1.SIDES
            }
            actual_facts, same_counts = _assert_baseline_parity(
                snapshot,
                expected_facts,
                enumerations,
                history,
                profiles,
                cutoff,
            )
            parity["development_cutoff_count"] += 1
            parity["role_comparison_count"] += 4
            parity["same_geometry_comparison_count"] += same_counts[
                "same_geometry_count"
            ]
            for side in n1.SIDES:
                enumeration = enumerations[side]
                structural = enumeration.structural
                current_valid = enumeration.current_valid
                exposed = frozenset(
                    candidate.geometry_id
                    for candidate in (structural, current_valid)
                    if candidate is not None
                )
                endpoints = enumeration.endpoints
                distinct_ids = {candidate.geometry_id for candidate in endpoints}
                exposed_count = len(distinct_ids & exposed)
                remaining_count = len(distinct_ids - exposed)
                selected = _select_secondary(endpoints, exposed)
                if selected is not None and selected.geometry_id in exposed:
                    raise N3AContractError("secondary duplicated an exposed geometry")
                secondary = _line_fact(
                    selected,
                    history,
                    profiles[cutoff.timeframe],
                    cutoff,
                    "secondary",
                )
                observations.append(
                    N3AObservation(
                        cutoff=cutoff,
                        side=side,
                        structural=actual_facts[f"{side}.structural"],
                        current_valid=actual_facts[f"{side}.current_valid"],
                        secondary=secondary,
                        secondary_score=None if selected is None else selected.score,
                        secondary_endpoint_index=(
                            None if selected is None else selected.endpoint_index
                        ),
                        positive_score_endpoint_count=len(endpoints),
                        exact_distinct_endpoint_geometry_count=len(distinct_ids),
                        already_exposed_exact_geometry_count=exposed_count,
                        remaining_alternate_exact_geometry_count=remaining_count,
                        current_close=history[-1].close,
                    )
                )
    if parity["development_cutoff_count"] != 4638:
        raise N3AContractError("N3A did not cover exactly 4,638 development cutoffs")
    if len(observations) != 9276:
        raise N3AContractError("N3A did not produce two side observations per cutoff")
    parity["current_valid_adverse_body_count"] = sum(
        int(
            row.current_valid is not None
            and row.current_valid.post_anchor_adverse_body_bar_count != 0
        )
        for row in observations
    )
    if parity["current_valid_adverse_body_count"] != 0:
        raise N3AContractError("current-valid adverse-body invariant failed")
    return N3AMeasurement(tuple(observations), parity)


def _group_rows(
    observations: Sequence[N3AObservation],
    *,
    include_window: bool = False,
) -> dict[tuple[str, ...], tuple[N3AObservation, ...]]:
    groups: dict[tuple[str, ...], list[N3AObservation]] = defaultdict(list)
    for row in observations:
        key = (row.cutoff.asset, row.cutoff.timeframe, row.side)
        if include_window:
            key = (*key, row.cutoff.window)
        groups[key].append(row)
    return {
        key: tuple(sorted(rows, key=lambda row: row.cutoff.cutoff))
        for key, rows in groups.items()
    }


def _pool_summary(rows: Sequence[N3AObservation]) -> dict[str, object]:
    fields = (
        "positive_score_endpoint_count",
        "exact_distinct_endpoint_geometry_count",
        "already_exposed_exact_geometry_count",
        "remaining_alternate_exact_geometry_count",
    )
    available = sum(row.secondary is not None for row in rows)
    return {
        "cutoff_count": len(rows),
        **{
            field: _distribution([getattr(row, field) for row in rows])
            for field in fields
        },
        "secondary_available_count": available,
        "secondary_available_rate": available / len(rows) if rows else 0.0,
        "duplicate_with_exposed_count": sum(
            int(
                row.secondary is not None
                and row.secondary.geometry_id
                in {
                    value
                    for value in (
                        row.structural_geometry_id,
                        row.current_valid_geometry_id,
                    )
                    if value is not None
                }
            )
            for row in rows
        ),
    }


def _distinctness_summary(rows: Sequence[N3AObservation]) -> dict[str, object]:
    selected = tuple(row for row in rows if row.secondary is not None)
    duplicate_count = sum(
        int(
            row.secondary is not None
            and row.secondary.geometry_id
            in {
                value
                for value in (row.structural_geometry_id, row.current_valid_geometry_id)
                if value is not None
            }
        )
        for row in rows
    )
    result: dict[str, object] = {
        "selected_count": len(selected),
        "duplicate_with_exposed_count": duplicate_count,
        "comparators": {},
    }
    for role in ("structural", "current_valid"):
        comparisons = [row for row in selected if getattr(row, role) is not None]
        separations = [
            abs(row.secondary.projected_price - getattr(row, role).projected_price)
            / row.current_close
            * 10_000
            for row in comparisons
        ]
        same_start = sum(
            row.secondary.start_anchor_at == getattr(row, role).start_anchor_at
            for row in comparisons
        )
        same_end = sum(
            row.secondary.end_anchor_at == getattr(row, role).end_anchor_at
            for row in comparisons
        )
        either = sum(
            row.secondary.start_anchor_at == getattr(row, role).start_anchor_at
            or row.secondary.end_anchor_at == getattr(row, role).end_anchor_at
            for row in comparisons
        )
        result["comparators"][role] = {
            "comparator_available_count": len(comparisons),
            "same_start_anchor_count": same_start,
            "same_start_anchor_rate": same_start / len(comparisons)
            if comparisons
            else 0.0,
            "same_end_anchor_count": same_end,
            "same_end_anchor_rate": same_end / len(comparisons) if comparisons else 0.0,
            "shares_either_anchor_count": either,
            "shares_either_anchor_rate": either / len(comparisons)
            if comparisons
            else 0.0,
            "projected_price_separation_bps": _distribution(separations),
        }
    return result


def _metadata_summary(rows: Sequence[N3AObservation]) -> dict[str, object]:
    selected = tuple(row.secondary for row in rows if row.secondary is not None)
    fields = (
        "absolute_close_distance_bps",
        "body_clearance_bps",
        "anchor_span_bars",
        "start_anchor_age_bars",
        "end_anchor_age_bars",
        "left_pivot_eligibility_margin_bars",
        "slope_bps_per_bar",
        "post_anchor_adverse_body_bar_count",
        "post_anchor_adverse_body_bar_rate",
        "bars_since_last_adverse_body_bar",
    )
    return {
        "selected_count": len(selected),
        "distributions": {
            field: _distribution(
                [
                    getattr(fact, field)
                    for fact in selected
                    if getattr(fact, field) is not None
                ]
            )
            for field in fields
        },
        "current_body_adverse_side_counts": {
            "adverse": sum(
                fact.current_body_adverse_side == "adverse" for fact in selected
            ),
            "respecting": sum(
                fact.current_body_adverse_side == "respecting" for fact in selected
            ),
        },
        "projection_positive_count": sum(fact.projection_positive for fact in selected),
        "projection_non_positive_count": sum(
            fact.projection_non_positive for fact in selected
        ),
    }


def _stability_group(rows: Sequence[N3AObservation]) -> dict[str, object]:
    by_window = _group_rows(rows, include_window=True)
    runs: list[dict[str, object]] = []
    replacements = 0
    eligible = 0
    for window_rows in by_window.values():
        first_cutoff = window_rows[0].cutoff.cutoff
        last_cutoff = window_rows[-1].cutoff.cutoff
        if [row.cutoff.cutoff for row in window_rows] != list(
            range(first_cutoff, last_cutoff + 1)
        ):
            raise N3AContractError("secondary stream is not contiguous")
        previous_id = None
        previous_row = None
        current_id = None
        current_start = None
        seen: set[str] = set()

        def close(
            end_cutoff: int,
            *,
            window_rows: tuple[N3AObservation, ...] = window_rows,
            seen: set[str] = seen,
            first_cutoff: int = first_cutoff,
            last_cutoff: int = last_cutoff,
        ) -> None:
            nonlocal current_id, current_start
            if current_id is None or current_start is None:
                return
            left = current_start == first_cutoff
            right = end_cutoff == last_cutoff
            runs.append(
                {
                    "geometry_id": current_id,
                    "observed_run_length_bars": end_cutoff - current_start + 1,
                    "left_censored": left,
                    "right_censored": right,
                    "both_censored": left and right,
                    "uncensored": not left and not right,
                    "event": "REAPPEAR" if current_id in seen else "BIRTH",
                }
            )
            seen.add(current_id)
            current_id = None
            current_start = None

        for row in window_rows:
            geometry_id = row.secondary_geometry_id
            if (
                previous_row is not None
                and previous_id is not None
                and geometry_id is not None
            ):
                eligible += 1
                replacements += int(previous_id != geometry_id)
            if geometry_id == current_id:
                previous_id, previous_row = geometry_id, row
                continue
            if current_id is not None:
                close(row.cutoff.cutoff - 1)
            if geometry_id is not None:
                current_id = geometry_id
                current_start = row.cutoff.cutoff
            previous_id, previous_row = geometry_id, row
        close(last_cutoff)
    lengths = [int(run["observed_run_length_bars"]) for run in runs]
    uncensored = [
        int(run["observed_run_length_bars"]) for run in runs if run["uncensored"]
    ]
    run_count = len(runs)
    return {
        "cutoff_count": len(rows),
        "secondary_available_count": sum(row.secondary is not None for row in rows),
        "secondary_availability_rate": sum(row.secondary is not None for row in rows)
        / len(rows)
        if rows
        else 0.0,
        "eligible_adjacent_transition_count": eligible,
        "replacement_count": replacements,
        "replacement_rate_per_100_eligible_transitions": replacements / eligible * 100
        if eligible
        else 0.0,
        "run_count": run_count,
        "reappearance_count": sum(run["event"] == "REAPPEAR" for run in runs),
        "reappearance_rate": sum(run["event"] == "REAPPEAR" for run in runs) / run_count
        if run_count
        else 0.0,
        "observed_run_length_bars": _distribution(lengths),
        "uncensored_observed_run_length_bars": _distribution(uncensored),
        "left_censored_count": sum(run["left_censored"] for run in runs),
        "right_censored_count": sum(run["right_censored"] for run in runs),
        "both_censored_count": sum(run["both_censored"] for run in runs),
        "uncensored_run_count": len(uncensored),
        "uncensored_one_bar_run_count": sum(length == 1 for length in uncensored),
        "uncensored_one_bar_run_fraction": sum(length == 1 for length in uncensored)
        / len(uncensored)
        if uncensored
        else 0.0,
        "censoring_rates": {
            "left": sum(run["left_censored"] for run in runs) / run_count
            if run_count
            else 0.0,
            "right": sum(run["right_censored"] for run in runs) / run_count
            if run_count
            else 0.0,
            "both": sum(run["both_censored"] for run in runs) / run_count
            if run_count
            else 0.0,
        },
    }


def _stability_summary(observations: Sequence[N3AObservation]) -> dict[str, object]:
    groups = _group_rows(observations)
    return {
        "global": _stability_group(observations),
        "asset_timeframe_side": {
            ":".join(key): _stability_group(rows)
            for key, rows in sorted(groups.items())
        },
    }


def _group_summary(
    observations: Sequence[N3AObservation],
    function,
) -> dict[str, object]:
    groups = _group_rows(observations)
    return {
        "global": function(observations),
        "asset_timeframe_side": {
            ":".join(key): function(rows) for key, rows in sorted(groups.items())
        },
    }


def _report(measurement: N3AMeasurement) -> dict[str, object]:
    observations = measurement.observations
    pool = _group_summary(observations, _pool_summary)
    distinctness = _group_summary(observations, _distinctness_summary)
    metadata = _group_summary(observations, _metadata_summary)
    selected = [row.as_payload() for row in observations if row.secondary is not None]
    return {
        "schema": "trendlines.v4.n3a.secondary-candidate-feasibility.v1",
        "conclusion": "SECONDARY_CANDIDATE_FEASIBILITY_MEASURED",
        "parameters": {
            "pivot_window": PIVOT_WINDOW,
            "history_capacity_bars": HISTORY_CAPACITY_BARS,
            "selector": "highest_legacy_score_distinct_secondary",
            "tie_behavior": "strict_greater_than_preserves_endpoint_order",
        },
        "development_membership": {
            "cutoff_count": 4638,
            "membership_hash": DEVELOPMENT_MEMBERSHIP_HASH,
        },
        "unopened_memberships": {
            "h1b_confirmation": {
                "membership_hash": H1B_MEMBERSHIP_HASH,
                "results_published": False,
            },
            "n3b_visual_review": {
                "membership_hash": N3B_MEMBERSHIP_HASH,
                "cutoff_count": 768,
                "ranges": [
                    {
                        "asset": asset,
                        "timeframe": timeframe,
                        "first_source_position": first,
                        "last_source_position": last,
                    }
                    for asset, timeframe, first, last in N3B_RANGES
                ],
                "results_published": False,
            },
        },
        "inventory": {
            "development_cutoff_count": measurement.baseline_parity[
                "development_cutoff_count"
            ],
            "side_cutoff_count": len(observations),
            "selected_secondary_observation_count": len(selected),
        },
        "baseline_parity": measurement.baseline_parity,
        "candidate_pool": pool,
        "secondary_distinctness": distinctness,
        "secondary_stability": _stability_summary(observations),
        "secondary_metadata": metadata,
        "selected_secondary_observations": selected,
    }


def verify_authorities() -> dict[str, object]:
    prior = h0.verify_prior_artifacts()
    return {
        "n3a_authority_hashes": _authority_view(AUTHORITY_HASHES),
        "prior_authority_and_locks": prior,
    }


def _timed_measure(
    streams: Sequence[h0.H0Stream],
) -> tuple[N3AMeasurement, dict[str, object]]:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    measurement = _measure(streams)
    return measurement, {
        "wall_seconds": time.perf_counter() - wall_start,
        "cpu_seconds": time.process_time() - cpu_start,
        "peak_process_rss_bytes": _peak_rss_bytes(),
    }


def run_n3a(
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, object]:
    """Run the locked development-only N3A measurement and publish two files."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise N3AContractError("N3A output directory is not empty")
    authority = verify_authorities()
    streams = h0.build_streams()
    development = h0.development_membership(streams)
    if (
        development["cutoff_count"] != 4638
        or development["membership_hash"] != DEVELOPMENT_MEMBERSHIP_HASH
    ):
        raise N3AContractError("H0 common development membership changed")
    first, first_resources = _timed_measure(streams)
    second, second_resources = _timed_measure(streams)
    first_report = _report(first)
    second_report = _report(second)
    first_semantic = _canonical_bytes(first_report)
    second_semantic = _canonical_bytes(second_report)
    if first_semantic != second_semantic:
        raise N3AContractError("N3A semantic runs are not exactly equal")
    resources = {
        "sequential": True,
        "semantic_runs": 2,
        "first": first_resources,
        "second": second_resources,
        "rss_limit_bytes": RSS_LIMIT_BYTES,
    }
    for record in (first_resources, second_resources):
        if int(record["peak_process_rss_bytes"]) > RSS_LIMIT_BYTES:
            raise N3AResourceBlocked("N3A peak process RSS exceeded 512 MiB")
    report = dict(first_report)
    report["determinism"] = {
        "semantic_runs": 2,
        "exact_semantic_equality": True,
        "semantic_digest": _digest(first_report),
    }
    report["resource_observation"] = resources
    report["authority"] = authority
    report_bytes = _pretty_bytes(report)
    manifest: dict[str, object] = {
        "schema": "trendlines.v4.n3a.secondary-candidate-feasibility-manifest.v1",
        "scope": "development-only exact secondary feasibility; no N3B/H1B evaluation",
        "authority": authority,
        "parameters": {
            "pivot_window": PIVOT_WINDOW,
            "history_capacity_bars": HISTORY_CAPACITY_BARS,
        },
        "development_membership": development,
        "h1b_membership_hash": H1B_MEMBERSHIP_HASH,
        "n3b_membership_hash": N3B_MEMBERSHIP_HASH,
        "semantic_runs": 2,
        "semantic_equality": True,
        "resource_observation": resources,
        "files": {
            "report.json": {
                "sha256": hashlib.sha256(report_bytes).hexdigest(),
                "byte_length": len(report_bytes),
            }
        },
        "results_published": True,
        "n3b_results_published": False,
        "h1b_results_published": False,
    }
    manifest["manifest_id"] = _digest(manifest)
    manifest_bytes = _pretty_bytes(manifest)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise N3AContractError("N3A output directory became non-empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_bytes(report_bytes)
    (output_dir / "manifest.json").write_bytes(manifest_bytes)
    return {"report": report, "manifest": manifest, "resources": resources}


__all__ = [
    "ALLOWED_CONCLUSIONS",
    "DEVELOPMENT_MEMBERSHIP_HASH",
    "H1B_MEMBERSHIP_HASH",
    "HISTORY_CAPACITY_BARS",
    "N3B_MEMBERSHIP_HASH",
    "OUTPUT_DIR",
    "PIVOT_WINDOW",
    "N3AContractError",
    "N3AResourceBlocked",
    "run_n3a",
    "verify_authorities",
]
