"""Outcome-blind H1A profile challenge measurement for Trendlines V4."""

from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal

from libs.models.trendlines_v4 import core
from research.trendlines_v4 import exact_geometry_identity_persistence as n1
from research.trendlines_v4 import parameter_sensitivity as h0

ROOT = Path(__file__).parents[2]
PRIMARY_ROOT = Path("/Users/kajukatli/projects/flipperAgent")
OUTPUT_DIR = ROOT / "artifacts/trendlines_v4/h1_profile_challenge_v1"

SELECTION_CUTOFFS_PER_STREAM = 96
CONFIRMATION_CUTOFFS_PER_STREAM = 96
SELECTION_MEMBERSHIP_HASH = (
    "16c0dc0aec55c745c63323e68009f99ed509d7140c72b7097533eca53ccb4968"
)
CONFIRMATION_MEMBERSHIP_HASH = (
    "71bce66333b89f96d093de764f93a954add7c7e9d4f28848767ed8d67697fbda"
)
EXPECTED_SELECTION_EVALUATIONS = 768
EXPECTED_POLICY_EVALUATIONS = 768
EXPECTED_SEMANTIC_EVALUATIONS = 3_840
EXPECTED_POLICY_COUNT = 5
EXPECTED_CASE_COUNT = 16
ALLOWED_CONCLUSIONS = (
    "H1_SELECTION_EVIDENCE_READY_FOR_BLIND_REVIEW",
    "H1_SELECTION_EVIDENCE_INCONCLUSIVE",
    "H1_SELECTION_RESOURCE_BLOCKED",
    "H1_SELECTION_NUMERICAL_SEMANTICS_BLOCKED",
    "BLOCKED_SOURCE_OR_CONTRACT",
)

H1_AUTHORITY_HASHES = {
    "handoff": (
        PRIMARY_ROOT
        / "plans/architect-to-coder-trendlines-v4-h1-profile-challenge-v1.md",
        "f4276aa376788367fd3351639cc39682c42d569f7680c4e86d2f819495602e7e",
    ),
    "design": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-h1-conservative-profile-challenge-design-v1.md",
        "b14f2285ac3d4944ecba3bf9026a9b796ee925d55558d5d8c09a1d97e75d9f9b",
    ),
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-h1-conservative-profile-challenge-design-approval-v1.md",
        "6bfcc6554c66b37a9b19f3262058ea9e2e73f3b86f2ba275d2f29f273108e596",
    ),
}
H0_AUTHORITY_HASHES = {
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-h0-parameter-sensitivity-approval-v1.md",
        "12c65b91da08246de4a066cd47d3721d5424c72b7c1f820961bdbcdf34f77071",
    ),
    "implementation": (
        ROOT / "research/trendlines_v4/parameter_sensitivity.py",
        "8f48a0d7b889058fc6ade20ca875531f4cdd2bb7e2f09a498fad268e3d8e4791",
    ),
    "tests": (
        ROOT / "tests/research/trendlines_v4/test_parameter_sensitivity.py",
        "dea327fcfa887d4293de28e777d314fe90c2cdb420c0d9ea4fb0f9322b257ae0",
    ),
    "report": (
        ROOT / "artifacts/trendlines_v4/h0_parameter_sensitivity_v1/report.json",
        "b34019127c8167a36438a8702ca4ad04376df852784e8f5f1e12157db7ccb6cc",
    ),
    "manifest": (
        ROOT / "artifacts/trendlines_v4/h0_parameter_sensitivity_v1/manifest.json",
        "613e164884f414df025ced5dff485ca5c48476848679beeae8cae7ab654c8437",
    ),
}


class H1ContractError(ValueError):
    """Raised when the frozen H1A contract or source boundary is violated."""


class H1ResourceBlocked(RuntimeError):
    """Raised when an H1A execution resource contract fails."""


class H1NumericalSemanticsBlocked(RuntimeError):
    """Raised when the two H1A semantic runs differ."""


@dataclass(frozen=True, slots=True)
class H1Policy:
    policy_id: Literal["C0", "C1", "C2", "C3", "C4"]
    pivot_window: int
    history_policy_kind: Literal["fixed_bars", "fixed_duration"]
    history_policy_value: int

    def profile(self, timeframe: Literal["1h", "4h"]) -> h0.H0Profile:
        candidates = tuple(
            profile
            for profile in h0.profiles_for_timeframe(timeframe)
            if profile.pivot_window == self.pivot_window
            and profile.history_policy_kind == self.history_policy_kind
            and profile.history_policy_value == self.history_policy_value
        )
        if len(candidates) != 1:
            raise H1ContractError(
                f"{self.policy_id} does not resolve to one H0 profile"
            )
        profile = candidates[0]
        if self.policy_id == "C0" and not profile.is_baseline:
            raise H1ContractError("C0 is not the authenticated H0 baseline")
        if self.policy_id != "C0" and profile.is_baseline:
            raise H1ContractError("challenger unexpectedly resolves to baseline")
        return profile

    def as_payload(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "pivot_window": self.pivot_window,
            "history_policy_kind": self.history_policy_kind,
            "history_policy_value": self.history_policy_value,
        }


POLICIES = (
    H1Policy("C0", 3, "fixed_bars", 300),
    H1Policy("C1", 2, "fixed_bars", 300),
    H1Policy("C2", 5, "fixed_bars", 300),
    H1Policy("C3", 3, "fixed_bars", 600),
    H1Policy("C4", 3, "fixed_duration", 28),
)


@dataclass(slots=True)
class _PolicyRun:
    policy: H1Policy
    reports: dict[str, object]
    snapshots: dict[tuple[object, ...], h0.H0Snapshot]
    rows: tuple[h0.H0Observation, ...]
    resource: dict[str, object]
    snapshot_fingerprint: str


@dataclass(slots=True)
class _SemanticMatrix:
    policy_runs: dict[str, _PolicyRun]
    evaluation_count: int
    resource: dict[str, object]
    semantic_payload: dict[str, object]


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


def _verify_hashes(
    locks: dict[str, tuple[Path, str]],
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, (path, expected) in locks.items():
        if not path.is_file():
            raise H1ContractError(f"missing locked file: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise H1ContractError(f"locked hash mismatch: {name}")
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


def verify_authorities() -> dict[str, object]:
    """Authenticate H1A, H0, and all previously protected V4 evidence."""

    prior = h0.verify_prior_artifacts()
    return {
        "h1_authority_hashes": _authority_view(H1_AUTHORITY_HASHES),
        "h0_authority_hashes": _authority_view(H0_AUTHORITY_HASHES),
        "prior_authority_evidence": prior,
    }


def _simple_membership(
    streams: Sequence[h0.H0Stream],
    offset: int,
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    count = (
        SELECTION_CUTOFFS_PER_STREAM if offset == 0 else CONFIRMATION_CUTOFFS_PER_STREAM
    )
    for stream in streams:
        cutoffs = stream.holdout[offset : offset + count]
        if len(cutoffs) != 96:
            raise H1ContractError("frozen H1 membership does not contain 96 cutoffs")
        first = cutoffs[0].source_position
        last = cutoffs[-1].source_position
        if last - first + 1 != 96:
            raise H1ContractError("H1 membership is not contiguous")
        records.append(
            {
                "asset": stream.asset,
                "timeframe": stream.timeframe,
                "first_source_position": first,
                "last_source_position": last,
                "cutoff_count": 96,
            }
        )
    return tuple(records)


def build_membership(streams: Sequence[h0.H0Stream]) -> dict[str, object]:
    """Freeze open selection and sealed confirmation membership without analysis."""

    selection_records = _simple_membership(streams, 0)
    confirmation_records = _simple_membership(streams, 96)
    selection_hash = _digest(selection_records)
    confirmation_hash = _digest(confirmation_records)
    if selection_hash != SELECTION_MEMBERSHIP_HASH:
        raise H1ContractError("H1A selection membership hash changed")
    if confirmation_hash != CONFIRMATION_MEMBERSHIP_HASH:
        raise H1ContractError("H1B confirmation membership hash changed")
    return {
        "selection": {
            "cutoff_count": EXPECTED_SELECTION_EVALUATIONS,
            "membership_hash": selection_hash,
            "streams": list(selection_records),
            "results_published": True,
        },
        "confirmation": {
            "cutoff_count": EXPECTED_SELECTION_EVALUATIONS,
            "membership_hash": confirmation_hash,
            "streams": list(confirmation_records),
            "results_published": False,
        },
    }


def _selection_cutoffs(
    streams: Sequence[h0.H0Stream],
    membership: dict[str, object] | None = None,
) -> tuple[h0.H0Cutoff, ...]:
    cutoffs = tuple(
        cutoff
        for stream in streams
        for cutoff in stream.holdout[:SELECTION_CUTOFFS_PER_STREAM]
    )
    if len(cutoffs) != EXPECTED_SELECTION_EVALUATIONS:
        raise H1ContractError("H1A selection does not contain exactly 768 cutoffs")
    allowed = {
        (stream.asset, stream.timeframe, cutoff.source_position)
        for stream in streams
        for cutoff in stream.holdout[:SELECTION_CUTOFFS_PER_STREAM]
    }
    if any(
        (cutoff.asset, cutoff.timeframe, cutoff.source_position) not in allowed
        for cutoff in cutoffs
    ):
        raise H1ContractError("selection cutoff is outside frozen membership")
    if membership is not None:
        selection = membership.get("selection")
        if not isinstance(selection, dict):
            raise H1ContractError("selection membership is missing")
        if selection.get("membership_hash") != SELECTION_MEMBERSHIP_HASH:
            raise H1ContractError("selection membership was relabeled")
    return cutoffs


def _stream_map(
    streams: Sequence[h0.H0Stream],
) -> dict[tuple[str, str], h0.H0Stream]:
    result = {(stream.asset, stream.timeframe): stream for stream in streams}
    if len(result) != len(streams):
        raise H1ContractError("duplicate H1 stream identity")
    return result


def _selection_history(
    stream: h0.H0Stream,
    cutoff: h0.H0Cutoff,
    effective_history_bars: int,
    selection_positions: frozenset[tuple[object, ...]],
) -> tuple[n1.TrendlineBar, ...]:
    if cutoff.partition != "holdout":
        raise H1ContractError("H1A evaluator received a non-holdout cutoff")
    if _cutoff_key(cutoff) not in selection_positions:
        raise H1ContractError("H1A evaluator received a sealed confirmation cutoff")
    if (
        effective_history_bars < 1
        or cutoff.source_position + 1 < effective_history_bars
    ):
        raise H1ContractError("H1A history is unavailable at the selection cutoff")
    source_slice = stream.bars[
        cutoff.source_position + 1 - effective_history_bars : cutoff.source_position + 1
    ]
    if len(source_slice) != effective_history_bars:
        raise H1ContractError("H1A history slice has the wrong length")
    history = n1._core_bars(source_slice)
    if history[-1].closed_at != stream.bars[cutoff.source_position].closed_at:
        raise H1ContractError("H1A history reads beyond its cutoff")
    return history


def _cutoff_key(cutoff: h0.H0Cutoff) -> tuple[object, ...]:
    return (cutoff.asset, cutoff.timeframe, cutoff.source_position)


def _snapshot_fingerprint(
    snapshots: dict[tuple[object, ...], h0.H0Snapshot],
) -> str:
    payload = []
    for key in sorted(snapshots):
        snapshot = snapshots[key]
        payload.append(
            {
                "key": list(key),
                "lines": [
                    None if fact is None else fact.as_payload()
                    for _, _, fact in snapshot.lines
                ],
            }
        )
    return _digest(payload)


def _merge_comparison(
    role_counts: dict[str, dict[str, int]],
    side_counts: dict[str, dict[str, int]],
    comparison: dict[str, object],
) -> None:
    roles = comparison.get("role")
    sides = comparison.get("side")
    if not isinstance(roles, dict) or not isinstance(sides, dict):
        raise H1ContractError("snapshot comparison has the wrong shape")
    for key, values in roles.items():
        if not isinstance(values, dict):
            raise H1ContractError("role comparison has the wrong shape")
        destination = role_counts.setdefault(
            str(key),
            {
                "slot_count": 0,
                "both_available_count": 0,
                "exact_geometry_id_match_count": 0,
                "changed_geometry_count": 0,
                "presence_gained_count": 0,
                "presence_lost_count": 0,
            },
        )
        for name, value in values.items():
            destination[str(name)] += int(value)
    for key, values in sides.items():
        if not isinstance(values, dict):
            raise H1ContractError("side comparison has the wrong shape")
        destination = side_counts.setdefault(
            str(key),
            {
                "comparison_count": 0,
                "exact_geometry_set_match_count": 0,
                "changed_geometry_set_count": 0,
            },
        )
        destination["comparison_count"] += 1
        destination["exact_geometry_set_match_count"] += int(
            values["exact_geometry_set_match_count"]
        )
        destination["changed_geometry_set_count"] += int(
            values["changed_geometry_set_count"]
        )


def _selection_position_keys(
    cutoffs: Sequence[h0.H0Cutoff],
) -> frozenset[tuple[object, ...]]:
    return frozenset(_cutoff_key(cutoff) for cutoff in cutoffs)


def _selection_stream_map(
    streams: Sequence[h0.H0Stream],
) -> dict[tuple[str, str], h0.H0Stream]:
    return _stream_map(streams)


def _rows_and_sequences(
    facts: h0.H0Snapshot,
    rows: list[h0.H0Observation],
    unique: dict[tuple[object, ...], h0.H0Observation],
    sequences: dict[tuple[str, ...], list[str | None]],
    role_slots: dict[str, int],
    available: dict[str, int],
    numerical: h0._NumericalAccumulator,
) -> None:
    cutoff = facts.cutoff
    for side, role, fact in facts.lines:
        sequence_key = (
            cutoff.asset,
            cutoff.timeframe,
            cutoff.window,
            side,
            role,
        )
        sequences.setdefault(sequence_key, []).append(
            None if fact is None else fact.geometry_id
        )
        role_key = f"{side}.{role}"
        role_slots[role_key] += 1
        if fact is None:
            continue
        available[role_key] += 1
        observation = h0.H0Observation(cutoff, fact)
        rows.append(observation)
        h0._register_unique(unique, observation)
        numerical.observe(observation)


def _evaluate_policy(
    policy: H1Policy,
    streams: Sequence[h0.H0Stream],
    baseline_snapshots: dict[tuple[object, ...], h0.H0Snapshot],
    selection_positions: frozenset[tuple[object, ...]],
) -> _PolicyRun:
    cutoffs = tuple(
        cutoff
        for stream in streams
        for cutoff in stream.holdout[:SELECTION_CUTOFFS_PER_STREAM]
    )
    if len(cutoffs) != EXPECTED_POLICY_EVALUATIONS:
        raise H1ContractError("policy did not receive the exact selection set")
    streams_by_key = _selection_stream_map(streams)
    rows: list[h0.H0Observation] = []
    unique: dict[tuple[object, ...], h0.H0Observation] = {}
    sequences: dict[tuple[str, ...], list[str | None]] = {}
    role_slots = {f"{side}.{role}": 0 for side, role in h0.ROLE_KEYS}
    available = {f"{side}.{role}": 0 for side, role in h0.ROLE_KEYS}
    role_comparison: dict[str, dict[str, int]] = {}
    side_comparison: dict[str, dict[str, int]] = {}
    snapshots: dict[tuple[object, ...], h0.H0Snapshot] = {}
    numerical = h0._NumericalAccumulator()
    call_count = 0
    oracle_count = 0
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    for cutoff in cutoffs:
        stream = streams_by_key.get((cutoff.asset, cutoff.timeframe))
        if stream is None:
            raise H1ContractError("selection cutoff has no source stream")
        profile = policy.profile(cutoff.timeframe)
        history = _selection_history(
            stream,
            cutoff,
            profile.effective_history_bars,
            selection_positions,
        )
        snapshot = h0.analyze_profile(profile, history)
        call_count += 1
        facts = h0.snapshot_facts(
            snapshot,
            history,
            profile=profile,
            cutoff=cutoff,
        )
        snapshots[cutoff.key()] = facts
        if policy.policy_id == "C0":
            oracle = core.analyze_trendlines(history)
            oracle_count += 1
            if oracle != snapshot:
                raise H1ContractError("C0 profile differs from unpatched P0 oracle")
        else:
            baseline = baseline_snapshots.get(cutoff.key())
            if baseline is None:
                raise H1ContractError("C0 baseline snapshot is missing")
            _merge_comparison(
                role_comparison,
                side_comparison,
                h0._compare_snapshots(facts, baseline),
            )
        _rows_and_sequences(
            facts,
            rows,
            unique,
            sequences,
            role_slots,
            available,
            numerical,
        )
    if call_count != EXPECTED_POLICY_EVALUATIONS:
        raise H1ContractError("policy call count is not exactly 768")
    if policy.policy_id == "C0" and oracle_count != EXPECTED_POLICY_EVALUATIONS:
        raise H1ContractError("C0 oracle did not cover every selection cutoff")
    if (core.PIVOT_WINDOW, core.HISTORY_CAPACITY_BARS) != (3, 300):
        raise H1ContractError("production core globals drifted after H1 policy")
    unique_rows = tuple(unique[key] for key in sorted(unique))
    availability = {
        key: {
            "slot_count": role_slots[key],
            "available_count": available[key],
            "availability_rate": (
                available[key] / role_slots[key] if role_slots[key] else 0.0
            ),
        }
        for key in sorted(role_slots)
    }
    comparison = (
        {"not_applicable": True}
        if policy.policy_id == "C0"
        else h0._finalize_comparison(role_comparison, side_comparison)
    )
    report = {
        "policy": policy.as_payload(),
        "profiles_by_timeframe": {
            timeframe: policy.profile(timeframe).as_payload()
            for timeframe in ("1h", "4h")
        },
        "evaluation_count": call_count,
        "selection_only": True,
        "baseline_parity": (
            {
                "status": "passed",
                "exact_snapshot_match_count": oracle_count,
                "exact_policy_call_count": call_count,
            }
            if policy.policy_id == "C0"
            else {"not_applicable": False, "reference": "C0"}
        ),
        "baseline_comparison": comparison,
        "availability": availability,
        "metadata": h0._metadata_summaries(rows, unique_rows),
        "censor_aware_stability": h0._stability_summary(sequences),
        "numerical_diagnostics": numerical.as_payload(),
        "invariants": {
            "current_valid_post_anchor_adverse_body_count": 0,
            "selection_only": True,
            "outcome_blind": True,
            "confirmation_results_published": False,
        },
    }
    resource_record = {
        "policy_id": policy.policy_id,
        "evaluation_count": call_count,
        "wall_seconds": time.perf_counter() - wall_start,
        "cpu_seconds": time.process_time() - cpu_start,
        "peak_process_rss_bytes": _peak_rss_bytes(),
    }
    return _PolicyRun(
        policy=policy,
        reports=report,
        snapshots=snapshots,
        rows=tuple(rows),
        resource=resource_record,
        snapshot_fingerprint=_snapshot_fingerprint(snapshots),
    )


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _run_semantic_matrix(
    streams: Sequence[h0.H0Stream],
    membership: dict[str, object],
) -> _SemanticMatrix:
    cutoffs = _selection_cutoffs(streams, membership)
    selection_positions = _selection_position_keys(cutoffs)
    policy_runs: dict[str, _PolicyRun] = {}
    baseline_snapshots: dict[tuple[object, ...], h0.H0Snapshot] = {}
    matrix_wall_start = time.perf_counter()
    matrix_cpu_start = time.process_time()
    for policy in POLICIES:
        result = _evaluate_policy(
            policy,
            streams,
            baseline_snapshots,
            selection_positions,
        )
        policy_runs[policy.policy_id] = result
        if policy.policy_id == "C0":
            baseline_snapshots = dict(result.snapshots)
    if set(policy_runs) != {policy.policy_id for policy in POLICIES}:
        raise H1ContractError("semantic matrix policy inventory is incomplete")
    evaluation_count = sum(
        int(result.reports["evaluation_count"]) for result in policy_runs.values()
    )
    if evaluation_count != EXPECTED_SEMANTIC_EVALUATIONS:
        raise H1ContractError("semantic matrix did not execute exactly 3,840 calls")
    semantic_payload = {
        "selection_membership": membership["selection"],
        "confirmation_membership": membership["confirmation"],
        "policies": {
            policy_id: result.reports for policy_id, result in policy_runs.items()
        },
        "snapshot_fingerprints": {
            policy_id: result.snapshot_fingerprint
            for policy_id, result in policy_runs.items()
        },
        "evaluation_count": evaluation_count,
    }
    return _SemanticMatrix(
        policy_runs=policy_runs,
        evaluation_count=evaluation_count,
        resource={
            "evaluation_count": evaluation_count,
            "wall_seconds": time.perf_counter() - matrix_wall_start,
            "cpu_seconds": time.process_time() - matrix_cpu_start,
            "peak_process_rss_bytes": _peak_rss_bytes(),
            "policy_resources": [
                policy_runs[policy.policy_id].resource for policy in POLICIES
            ],
            "execution": "one serial process; resource values are observational",
        },
        semantic_payload=semantic_payload,
    )


def _assert_semantic_rerun_equal(
    first: _SemanticMatrix,
    second: _SemanticMatrix,
) -> None:
    if first.evaluation_count != EXPECTED_SEMANTIC_EVALUATIONS:
        raise H1NumericalSemanticsBlocked("first semantic matrix count is not exact")
    if second.evaluation_count != EXPECTED_SEMANTIC_EVALUATIONS:
        raise H1NumericalSemanticsBlocked("second semantic matrix count is not exact")
    if first.semantic_payload != second.semantic_payload:
        raise H1NumericalSemanticsBlocked("two H1A semantic runs are not exactly equal")


def _bar_payload(bar: n1.SourceBar) -> dict[str, object]:
    return {
        "open_at": n1._timestamp(bar.open_at),
        "close_at": n1._timestamp(bar.closed_at),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
    }


def _blind_line(fact: h0.H0LineFact) -> dict[str, object]:
    """Expose geometry only; do not leak the H0 metadata used by selection."""

    return {
        "start_anchor_at": fact.start_anchor_at,
        "end_anchor_at": fact.end_anchor_at,
        "start_anchor_price": fact.start_anchor_price,
        "end_anchor_price": fact.end_anchor_price,
        "slope_per_bar": fact.slope_per_bar,
        "projected_price": fact.projected_price,
    }


def _eligible_cases(
    challenger_id: str,
    baseline_run: _PolicyRun,
    challenger_run: _PolicyRun,
    streams: Sequence[h0.H0Stream],
    selection: Sequence[h0.H0Cutoff],
) -> tuple[dict[str, object], ...]:
    streams_by_key = _stream_map(streams)
    candidates: list[dict[str, object]] = []
    for cutoff in selection:
        baseline = baseline_run.snapshots.get(cutoff.key())
        challenger = challenger_run.snapshots.get(cutoff.key())
        if baseline is None or challenger is None:
            raise H1ContractError("blind case source snapshot is missing")
        stream = streams_by_key.get((cutoff.asset, cutoff.timeframe))
        if stream is None:
            raise H1ContractError("blind case source stream is missing")
        for side in n1.SIDES:
            for role in n1.ROLES:
                baseline_fact = baseline.line(side, role)
                challenger_fact = challenger.line(side, role)
                if baseline_fact is None or challenger_fact is None:
                    continue
                if baseline_fact.geometry_id == challenger_fact.geometry_id:
                    continue
                scope = (
                    f"{challenger_id}|{cutoff.asset}|{cutoff.timeframe}|"
                    f"{cutoff.source_position}|{side}|{role}"
                )
                context_start = max(0, cutoff.source_position - 119)
                bars = stream.bars[context_start : cutoff.source_position + 1]
                if not bars:
                    raise H1ContractError("blind case context is empty")
                candidates.append(
                    {
                        "challenger_id": challenger_id,
                        "asset": cutoff.asset,
                        "timeframe": cutoff.timeframe,
                        "source_position": cutoff.source_position,
                        "market_as_of": cutoff.market_as_of,
                        "side": side,
                        "role": role,
                        "scope": scope,
                        "scope_hash": _digest(scope),
                        "bars": tuple(_bar_payload(bar) for bar in bars),
                        "baseline_line": _blind_line(baseline_fact),
                        "challenger_line": _blind_line(challenger_fact),
                    }
                )
    return tuple(sorted(candidates, key=lambda item: str(item["scope_hash"])))


def _choose_case(
    candidates: Sequence[dict[str, object]],
    timeframe: str,
    side: str,
    used_assets: set[str],
    used_roles: set[str],
) -> dict[str, object]:
    pool = [
        candidate
        for candidate in candidates
        if candidate["timeframe"] == timeframe and candidate["side"] == side
    ]
    if not pool:
        raise H1ContractError(f"no eligible blinded case for {timeframe}/{side}")
    ordered = sorted(
        pool,
        key=lambda candidate: (
            str(candidate["asset"]) in used_assets,
            str(candidate["role"]) in used_roles,
            str(candidate["scope_hash"]),
        ),
    )
    chosen = ordered[0]
    used_assets.add(str(chosen["asset"]))
    used_roles.add(str(chosen["role"]))
    return chosen


def _build_blind_packet(
    first: _SemanticMatrix,
    streams: Sequence[h0.H0Stream],
    membership: dict[str, object],
) -> dict[str, object]:
    selection = _selection_cutoffs(streams, membership)
    baseline_run = first.policy_runs.get("C0")
    if baseline_run is None:
        raise H1ContractError("C0 run is missing from blind packet source")
    all_cases: list[dict[str, object]] = []
    mapping: list[dict[str, object]] = []
    used_assets: set[str] = set()
    used_roles: set[str] = set()
    for policy in POLICIES[1:]:
        challenger_run = first.policy_runs.get(policy.policy_id)
        if challenger_run is None:
            raise H1ContractError("challenger run is missing from blind packet source")
        candidates = _eligible_cases(
            policy.policy_id,
            baseline_run,
            challenger_run,
            streams,
            selection,
        )
        for timeframe, side in (
            ("1h", "support"),
            ("1h", "resistance"),
            ("4h", "support"),
            ("4h", "resistance"),
        ):
            chosen = _choose_case(
                candidates,
                timeframe,
                side,
                used_assets,
                used_roles,
            )
            scope_hash = str(chosen["scope_hash"])
            swap = (
                int(hashlib.sha256(f"{scope_hash}|panel".encode()).hexdigest()[0], 16)
                % 2
            )
            baseline_label = "B" if swap else "A"
            challenger_label = "A" if swap else "B"
            case_id = f"case-{len(all_cases) + 1:02d}"
            public_case = {
                "case_id": case_id,
                "asset": chosen["asset"],
                "timeframe": chosen["timeframe"],
                "source_position": chosen["source_position"],
                "market_as_of": chosen["market_as_of"],
                "side": chosen["side"],
                "role": chosen["role"],
                "selection_scope_sha256": scope_hash,
                "bars": list(chosen["bars"]),
                "panels": [
                    {
                        "label": "A",
                        "line": chosen[
                            "baseline_line"
                            if baseline_label == "A"
                            else "challenger_line"
                        ],
                    },
                    {
                        "label": "B",
                        "line": chosen[
                            "baseline_line"
                            if baseline_label == "B"
                            else "challenger_line"
                        ],
                    },
                ],
            }
            all_cases.append(public_case)
            mapping.append(
                {
                    "case_id": case_id,
                    "challenger_id": policy.policy_id,
                    "scope_sha256": scope_hash,
                    "baseline_panel": baseline_label,
                    "challenger_panel": challenger_label,
                }
            )
    if len(all_cases) != EXPECTED_CASE_COUNT:
        raise H1ContractError("blind packet does not contain exactly 16 cases")
    challenger_counts = {
        policy.policy_id: sum(
            item["challenger_id"] == policy.policy_id for item in mapping
        )
        for policy in POLICIES[1:]
    }
    if set(challenger_counts.values()) != {4}:
        raise H1ContractError("blind packet challenger allocation is incomplete")
    baseline_assignments = [item["baseline_panel"] for item in mapping]
    if len(set(baseline_assignments)) != 2:
        raise H1ContractError("blind panel assignment is constant")
    mapping.sort(key=lambda item: str(item["case_id"]))
    return {
        "payload": {
            "schema": "trendlines.v4.h1a.blind-cases.v1",
            "case_count": len(all_cases),
            "cases": all_cases,
            "identity_revealed": False,
            "ratings_recorded": False,
            "selection_only": True,
        },
        "mapping_commitment": _digest(mapping),
        "mapping_count": len(mapping),
        "assignment_counts": {
            "baseline_A": baseline_assignments.count("A"),
            "baseline_B": baseline_assignments.count("B"),
        },
    }


def _price_y(value: float, low: float, high: float, height: float) -> float:
    if high <= low:
        return height / 2
    return height - ((value - low) / (high - low)) * height


def _case_svg(case: dict[str, object]) -> str:
    bars = case.get("bars")
    panels = case.get("panels")
    if not isinstance(bars, list) or not isinstance(panels, list) or len(panels) != 2:
        raise H1ContractError("blind case cannot be rendered")
    values = [float(value) for bar in bars for value in (bar["low"], bar["high"])]
    low = min(values)
    high = max(values)
    width = 520
    height = 220
    left = 42
    top = 22
    chart_width = width - left - 12
    chart_height = height - top - 22
    denominator = max(1, len(bars) - 1)
    candle_width = max(1.0, chart_width / max(1, len(bars)) * 0.55)
    content: list[str] = []
    for index, bar in enumerate(bars):
        x = left + chart_width * index / denominator
        y_high = top + _price_y(float(bar["high"]), low, high, chart_height)
        y_low = top + _price_y(float(bar["low"]), low, high, chart_height)
        y_open = top + _price_y(float(bar["open"]), low, high, chart_height)
        y_close = top + _price_y(float(bar["close"]), low, high, chart_height)
        color = "#79c0ff" if float(bar["close"]) >= float(bar["open"]) else "#ff7b72"
        body_top = min(y_open, y_close)
        body_height = max(1.0, abs(y_close - y_open))
        content.append(
            f'<line x1="{x:.2f}" y1="{y_high:.2f}" x2="{x:.2f}" y2="{y_low:.2f}" '
            f'stroke="#8b949e" stroke-width="1"/><rect x="{x - candle_width / 2:.2f}" '
            f'y="{body_top:.2f}" width="{candle_width:.2f}" height="{body_height:.2f}" '
            f'fill="{color}" opacity="0.75"/>'
        )
    for panel_index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise H1ContractError("blind panel is malformed")
        line = panel.get("line")
        if not isinstance(line, dict):
            continue
        slope = float(line["slope_per_bar"])
        terminal = float(line["projected_price"])
        start_value = terminal - slope * (len(bars) - 1)
        y_start = top + _price_y(start_value, low, high, chart_height)
        y_terminal = top + _price_y(terminal, low, high, chart_height)
        color = "#d2a8ff" if panel_index == 0 else "#ffa657"
        content.append(
            f'<line x1="{left:.2f}" y1="{y_start:.2f}" '
            f'x2="{left + chart_width:.2f}" y2="{y_terminal:.2f}" '
            f'stroke="{color}" stroke-width="2"/>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Blinded geometry case {escape(str(case["case_id"]))}">'
        f'<rect width="100%" height="100%" fill="#0d1117"/>'
        f'<text x="12" y="16" fill="#f0f6fc" font-size="12">'
        f"{escape(str(case['case_id']))} · {escape(str(case['asset']))} "
        f"{escape(str(case['timeframe']))} · panel lines A/B</text>"
        + "".join(content)
        + "</svg>"
    )


def _build_blind_html(blind_payload: dict[str, object]) -> bytes:
    cases = blind_payload.get("cases")
    if not isinstance(cases, list):
        raise H1ContractError("blind HTML source is malformed")
    sections = []
    for case in cases:
        sections.append(
            f"<section><h2>{escape(str(case['case_id']))}</h2>"
            f"<p>{escape(str(case['asset']))} · {escape(str(case['timeframe']))} · "
            f"{escape(str(case['side']))} · {escape(str(case['role']))}</p>"
            f"{_case_svg(case)}</section>"
        )
    html = (
        '<!doctype html><html><head><meta charset="utf-8"><title>'
        "Trendlines V4 blinded geometry review</title>"
        "<style>body{background:#161b22;color:#f0f6fc;font:14px system-ui;"
        "margin:24px}section{display:inline-block;vertical-align:top;margin:8px;"
        "padding:10px;background:#21262d;border-radius:8px}svg{width:520px;"
        "max-width:90vw}h1{font-size:20px}p{color:#8b949e}</style></head><body>"
        "<h1>Blinded geometry review</h1>"
        "<p>Rate panel A and panel B for current geometric usefulness."
        " Identity is withheld until ratings are recorded.</p>"
        + "".join(sections)
        + "</body></html>"
    )
    return html.encode("utf-8")


def _build_report(
    authority: dict[str, object],
    membership: dict[str, object],
    first: _SemanticMatrix,
    second: _SemanticMatrix,
    blind: dict[str, object],
) -> dict[str, object]:
    if first.semantic_payload != second.semantic_payload:
        raise H1NumericalSemanticsBlocked("report source matrices are not equal")
    first_runs = first.policy_runs
    return {
        "schema": "trendlines.v4.h1a.profile-challenge.v1",
        "conclusion": "H1_SELECTION_EVIDENCE_READY_FOR_BLIND_REVIEW",
        "authority": authority,
        "selection": membership["selection"],
        "sealed_confirmation": membership["confirmation"],
        "policies": [
            {
                "policy": policy.as_payload(),
                "evaluation_count": first_runs[policy.policy_id].reports[
                    "evaluation_count"
                ],
                "report": first_runs[policy.policy_id].reports,
                "first_run_resource": first_runs[policy.policy_id].resource,
                "snapshot_fingerprint": first_runs[
                    policy.policy_id
                ].snapshot_fingerprint,
            }
            for policy in POLICIES
        ],
        "semantic_runs": {
            "run_count": 2,
            "evaluation_count_per_run": first.evaluation_count,
            "exact_semantic_equality": True,
            "first_run_resource": first.resource,
            "second_run_resource": second.resource,
        },
        "baseline_parity": first_runs["C0"].reports["baseline_parity"],
        "blinded_review": {
            "case_count": EXPECTED_CASE_COUNT,
            "mapping_commitment_sha256": blind["mapping_commitment"],
            "mapping_count": blind["mapping_count"],
            "identity_revealed": False,
            "ratings_recorded": False,
        },
        "allowed_conclusions": list(ALLOWED_CONCLUSIONS),
        "interpretation": {
            "scope": "descriptive profile challenge on selection cutoffs only",
            "descriptive_only": True,
            "resource_values_are_observational": True,
        },
    }


def _build_manifest(
    report: dict[str, object],
    report_bytes: bytes,
    blind_bytes: bytes,
    html_bytes: bytes,
    authority: dict[str, object],
    membership: dict[str, object],
    first: _SemanticMatrix,
    blind: dict[str, object],
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "trendlines.v4.h1a.profile-challenge-manifest.v1",
        "scope": "H1A selection-only five-policy profile challenge",
        "authority": authority,
        "selection_membership_hash": membership["selection"]["membership_hash"],
        "sealed_confirmation_membership_hash": membership["confirmation"][
            "membership_hash"
        ],
        "selection_cutoff_count": EXPECTED_SELECTION_EVALUATIONS,
        "confirmation_cutoff_count": EXPECTED_SELECTION_EVALUATIONS,
        "policy_count": EXPECTED_POLICY_COUNT,
        "evaluations_per_semantic_run": EXPECTED_SEMANTIC_EVALUATIONS,
        "semantic_run_count": 2,
        "blind_case_count": EXPECTED_CASE_COUNT,
        "blind_mapping_commitment_sha256": blind["mapping_commitment"],
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
        "report_conclusion": report["conclusion"],
        "semantic_payload_sha256": _digest(first.semantic_payload),
        "identity_revealed": False,
        "results_published": True,
    }
    body["manifest_id"] = _digest(body)
    return body


def _write_outputs(
    output_dir: Path,
    report_bytes: bytes,
    manifest_bytes: bytes,
    blind_bytes: bytes,
    html_bytes: bytes,
) -> None:
    if output_dir.exists():
        if any(output_dir.iterdir()):
            raise H1ContractError("H1A output directory is not empty")
    else:
        output_dir.mkdir(parents=True)
    files = {
        "report.json": report_bytes,
        "manifest.json": manifest_bytes,
        "blind_cases.json": blind_bytes,
        "blind_review.html": html_bytes,
    }
    for name, data in files.items():
        path = output_dir / name
        if path.exists():
            raise H1ContractError("H1A output path already exists")
        path.write_bytes(data)


def run_h1(output_dir: Path = OUTPUT_DIR) -> dict[str, object]:
    """Execute H1A exactly once over the open selection membership."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise H1ContractError("H1A output directory must be absent or empty")
    authority = verify_authorities()
    streams = h0.build_streams()
    membership = build_membership(streams)
    first = _run_semantic_matrix(streams, membership)
    second = _run_semantic_matrix(streams, membership)
    _assert_semantic_rerun_equal(first, second)
    if first.evaluation_count != EXPECTED_SEMANTIC_EVALUATIONS:
        raise H1ContractError("first H1A matrix count is not exact")
    if second.evaluation_count != EXPECTED_SEMANTIC_EVALUATIONS:
        raise H1ContractError("second H1A matrix count is not exact")
    blind = _build_blind_packet(first, streams, membership)
    payload = blind["payload"]
    if not isinstance(payload, dict):
        raise H1ContractError("blind packet payload is malformed")
    blind_bytes = _pretty_bytes(payload)
    html_bytes = _build_blind_html(payload)
    report = _build_report(authority, membership, first, second, blind)
    report_bytes = _pretty_bytes(report)
    manifest = _build_manifest(
        report,
        report_bytes,
        blind_bytes,
        html_bytes,
        authority,
        membership,
        first,
        blind,
    )
    manifest_bytes = _pretty_bytes(manifest)
    _write_outputs(output_dir, report_bytes, manifest_bytes, blind_bytes, html_bytes)
    return {
        "output_dir": output_dir.as_posix(),
        "report": report,
        "manifest": manifest,
        "blind_cases": payload,
        "resource": first.resource,
    }


REMEDIATION_OUTPUT_DIR = ROOT / "artifacts/trendlines_v4/h1_blind_review_remediation_v1"
ORIGINAL_H1A_ARTIFACT_HASHES = {
    "report.json": "4a71464de03f55a778a03243e799b45fad306f93473cd8d374902924da37226f",
    "manifest.json": "1948c89e9cbb52d7db7309c15af759500160605726638fcb8eeb13b87e49d5f5",
    "blind_cases.json": "45957cbf5486079e39922f4f471838e3197e2ebf99e730b01333e3353f828b65",
    "blind_review.html": "9c2f5b6f2a8c5ed957aed85d0b830f36dace3cab0af787f5cb36d32089213deb",
}


def _original_scope_hashes() -> frozenset[str]:
    original_dir = ROOT / "artifacts/trendlines_v4/h1_profile_challenge_v1"
    for name, expected in ORIGINAL_H1A_ARTIFACT_HASHES.items():
        path = original_dir / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise H1ContractError(f"original H1A artifact changed: {name}")
    try:
        payload = json.loads((original_dir / "blind_cases.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise H1ContractError("original H1A blind packet is unreadable") from exc
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        raise H1ContractError("original H1A blind case inventory is not exact")
    scopes = {case.get("selection_scope_sha256") for case in cases}
    if len(scopes) != EXPECTED_CASE_COUNT or not all(
        isinstance(scope, str) for scope in scopes
    ):
        raise H1ContractError("original H1A blind scope inventory is not exact")
    return frozenset(str(scope) for scope in scopes)


def _anchor_source_position(
    stream: h0.H0Stream,
    anchor_at: str,
) -> int:
    matches = [
        index
        for index, bar in enumerate(stream.bars)
        if n1._timestamp(bar.closed_at) == anchor_at
    ]
    if len(matches) != 1:
        raise H1ContractError("replacement anchor is not uniquely source-owned")
    return matches[0]


def _replacement_eligible_cases(
    challenger_id: str,
    baseline_run: _PolicyRun,
    challenger_run: _PolicyRun,
    streams: Sequence[h0.H0Stream],
    selection: Sequence[h0.H0Cutoff],
    excluded_scope_hashes: frozenset[str],
) -> tuple[dict[str, object], ...]:
    streams_by_key = _stream_map(streams)
    candidates: list[dict[str, object]] = []
    for cutoff in selection:
        baseline = baseline_run.snapshots.get(cutoff.key())
        challenger = challenger_run.snapshots.get(cutoff.key())
        stream = streams_by_key.get((cutoff.asset, cutoff.timeframe))
        if baseline is None or challenger is None or stream is None:
            raise H1ContractError("replacement disagreement source is incomplete")
        for side in n1.SIDES:
            for role in n1.ROLES:
                baseline_fact = baseline.line(side, role)
                challenger_fact = challenger.line(side, role)
                if baseline_fact is None or challenger_fact is None:
                    continue
                if baseline_fact.geometry_id == challenger_fact.geometry_id:
                    continue
                scope = (
                    f"{challenger_id}|{cutoff.asset}|{cutoff.timeframe}|"
                    f"{cutoff.source_position}|{side}|{role}"
                )
                scope_hash = _digest(scope)
                if scope_hash in excluded_scope_hashes:
                    continue
                baseline_positions = {
                    "start": _anchor_source_position(
                        stream, baseline_fact.start_anchor_at
                    ),
                    "end": _anchor_source_position(stream, baseline_fact.end_anchor_at),
                }
                challenger_positions = {
                    "start": _anchor_source_position(
                        stream, challenger_fact.start_anchor_at
                    ),
                    "end": _anchor_source_position(
                        stream, challenger_fact.end_anchor_at
                    ),
                }
                anchor_positions = {
                    "A": baseline_positions,
                    "B": challenger_positions,
                }
                all_positions = tuple(
                    position
                    for member in anchor_positions.values()
                    for position in member.values()
                )
                if any(position > cutoff.source_position for position in all_positions):
                    raise H1ContractError("replacement anchor is after the cutoff")
                display_start = max(0, min(all_positions) - 5)
                display_end = cutoff.source_position
                display_bars = stream.bars[display_start : display_end + 1]
                if len(display_bars) != display_end - display_start + 1:
                    raise H1ContractError("replacement display slice is incomplete")
                if any(
                    not display_start <= position <= display_end
                    for position in all_positions
                ):
                    raise H1ContractError("replacement display omits an anchor")
                candidates.append(
                    {
                        "challenger_id": challenger_id,
                        "asset": cutoff.asset,
                        "timeframe": cutoff.timeframe,
                        "source_position": cutoff.source_position,
                        "market_as_of": cutoff.market_as_of,
                        "side": side,
                        "role": role,
                        "scope": scope,
                        "scope_hash": scope_hash,
                        "display_start": display_start,
                        "display_end": display_end,
                        "bars": tuple(_bar_payload(bar) for bar in display_bars),
                        "anchor_positions": {
                            label: {
                                kind: position - display_start
                                for kind, position in positions.items()
                            }
                            for label, positions in anchor_positions.items()
                        },
                        "anchor_times": {
                            "A": {
                                "start": baseline_fact.start_anchor_at,
                                "end": baseline_fact.end_anchor_at,
                            },
                            "B": {
                                "start": challenger_fact.start_anchor_at,
                                "end": challenger_fact.end_anchor_at,
                            },
                        },
                        "baseline_line": _blind_line(baseline_fact),
                        "challenger_line": _blind_line(challenger_fact),
                    }
                )
    return tuple(sorted(candidates, key=lambda item: str(item["scope_hash"])))


def _build_replacement_blind_packet(
    first: _SemanticMatrix,
    streams: Sequence[h0.H0Stream],
    membership: dict[str, object],
    excluded_scope_hashes: frozenset[str],
) -> dict[str, object]:
    selection = _selection_cutoffs(streams, membership)
    baseline_run = first.policy_runs.get("C0")
    if baseline_run is None:
        raise H1ContractError("replacement packet is missing C0")
    public_cases: list[dict[str, object]] = []
    mapping: list[dict[str, object]] = []
    used_assets: set[str] = set()
    used_roles: set[str] = set()
    for policy in POLICIES[1:]:
        challenger_run = first.policy_runs.get(policy.policy_id)
        if challenger_run is None:
            raise H1ContractError("replacement packet is missing a challenger")
        candidates = _replacement_eligible_cases(
            policy.policy_id,
            baseline_run,
            challenger_run,
            streams,
            selection,
            excluded_scope_hashes,
        )
        for timeframe, side in (
            ("1h", "support"),
            ("1h", "resistance"),
            ("4h", "support"),
            ("4h", "resistance"),
        ):
            chosen = _choose_case(
                candidates,
                timeframe,
                side,
                used_assets,
                used_roles,
            )
            scope_hash = str(chosen["scope_hash"])
            swap = (
                int(hashlib.sha256(f"{scope_hash}|panel".encode()).hexdigest()[0], 16)
                % 2
            )
            baseline_panel = "B" if swap else "A"
            challenger_panel = "A" if swap else "B"
            case_id = f"review2-case-{len(public_cases) + 1:02d}"
            panels = []
            for label in ("A", "B"):
                source_label = "A" if label == baseline_panel else "B"
                line_key = "baseline_line" if source_label == "A" else "challenger_line"
                panels.append(
                    {
                        "label": label,
                        "line": chosen[line_key],
                        "anchors": [
                            {
                                "kind": kind,
                                "index": chosen["anchor_positions"][source_label][kind],
                                "at": chosen["anchor_times"][source_label][kind],
                            }
                            for kind in ("start", "end")
                        ],
                    }
                )
            public_cases.append(
                {
                    "case_id": case_id,
                    "asset": chosen["asset"],
                    "timeframe": chosen["timeframe"],
                    "source_position": chosen["source_position"],
                    "market_as_of": chosen["market_as_of"],
                    "side": chosen["side"],
                    "role": chosen["role"],
                    "selection_scope_sha256": scope_hash,
                    "display_start_source_position": chosen["display_start"],
                    "display_end_source_position": chosen["display_end"],
                    "display_bar_count": len(chosen["bars"]),
                    "bars": list(chosen["bars"]),
                    "panels": panels,
                }
            )
            mapping.append(
                {
                    "case_id": case_id,
                    "challenger_id": policy.policy_id,
                    "scope_sha256": scope_hash,
                    "baseline_panel": baseline_panel,
                    "challenger_panel": challenger_panel,
                }
            )
    if len(public_cases) != EXPECTED_CASE_COUNT:
        raise H1ContractError("replacement packet does not contain 16 cases")
    if len({case["selection_scope_sha256"] for case in public_cases}) != 16:
        raise H1ContractError("replacement packet contains duplicate scopes")
    if any(
        case["selection_scope_sha256"] in excluded_scope_hashes for case in public_cases
    ):
        raise H1ContractError("replacement packet reused an original scope")
    if sum(case["timeframe"] == "1h" for case in public_cases) != 8:
        raise H1ContractError("replacement packet is not balanced across 1h")
    if sum(case["timeframe"] == "4h" for case in public_cases) != 8:
        raise H1ContractError("replacement packet is not balanced across 4h")
    if sum(case["side"] == "support" for case in public_cases) != 8:
        raise H1ContractError("replacement packet is not balanced across support")
    if sum(case["side"] == "resistance" for case in public_cases) != 8:
        raise H1ContractError("replacement packet is not balanced across resistance")
    mapping.sort(key=lambda item: str(item["case_id"]))
    baseline_panels = [item["baseline_panel"] for item in mapping]
    if len(set(baseline_panels)) != 2:
        raise H1ContractError("replacement panel assignment is constant")
    challenger_counts = {
        policy.policy_id: sum(
            item["challenger_id"] == policy.policy_id for item in mapping
        )
        for policy in POLICIES[1:]
    }
    if set(challenger_counts.values()) != {4}:
        raise H1ContractError("replacement challenger allocation is incomplete")
    return {
        "payload": {
            "schema": "trendlines.v4.h1a.blind-review-remediation.v1",
            "case_namespace": "review2",
            "case_count": len(public_cases),
            "cases": public_cases,
            "identity_revealed": False,
            "ratings_recorded": False,
            "selection_only": True,
            "confirmation_results_published": False,
        },
        "mapping_commitment": _digest(mapping),
        "mapping_count": len(mapping),
        "assignment_counts": {
            "baseline_A": baseline_panels.count("A"),
            "baseline_B": baseline_panels.count("B"),
        },
        "challenger_counts": challenger_counts,
    }


def _replacement_case_svg(case: dict[str, object]) -> str:
    bars = case.get("bars")
    panels = case.get("panels")
    if not isinstance(bars, list) or not isinstance(panels, list) or len(panels) != 2:
        raise H1ContractError("replacement case is not renderable")
    values = [float(value) for bar in bars for value in (bar["low"], bar["high"])]
    low, high = min(values), max(values)
    width = max(900, 90 + len(bars) * 3)
    height = 300
    left, top = 58, 28
    chart_width, chart_height = width - left - 20, height - top - 30
    denominator = max(1, len(bars) - 1)
    candle_width = 1.8
    content: list[str] = []
    for index, bar in enumerate(bars):
        x = left + chart_width * index / denominator
        y_high = top + _price_y(float(bar["high"]), low, high, chart_height)
        y_low = top + _price_y(float(bar["low"]), low, high, chart_height)
        y_open = top + _price_y(float(bar["open"]), low, high, chart_height)
        y_close = top + _price_y(float(bar["close"]), low, high, chart_height)
        color = "#79c0ff" if float(bar["close"]) >= float(bar["open"]) else "#ff7b72"
        body_top = min(y_open, y_close)
        body_height = max(1.0, abs(y_close - y_open))
        content.append(
            f'<line x1="{x:.2f}" y1="{y_high:.2f}" x2="{x:.2f}" y2="{y_low:.2f}" '
            f'stroke="#8b949e" stroke-width="1"/><rect x="{x - candle_width / 2:.2f}" '
            f'y="{body_top:.2f}" width="{candle_width:.2f}" height="{body_height:.2f}" '
            f'fill="{color}" opacity="0.75"/>'
        )
    for panel in panels:
        if not isinstance(panel, dict):
            raise H1ContractError("replacement panel is malformed")
        label = str(panel["label"])
        line = panel.get("line")
        anchors = panel.get("anchors")
        if (
            not isinstance(line, dict)
            or not isinstance(anchors, list)
            or len(anchors) != 2
        ):
            raise H1ContractError("replacement panel lacks anchor markers")
        color = "#d2a8ff" if label == "A" else "#ffa657"
        slope = float(line["slope_per_bar"])
        terminal = float(line["projected_price"])
        start_value = terminal - slope * (len(bars) - 1)
        y_start = top + _price_y(start_value, low, high, chart_height)
        y_terminal = top + _price_y(terminal, low, high, chart_height)
        content.append(
            f'<line data-panel="{escape(label)}" x1="{left:.2f}" y1="{y_start:.2f}" '
            f'x2="{left + chart_width:.2f}" y2="{y_terminal:.2f}" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        for anchor in anchors:
            index = int(anchor["index"])
            if not 0 <= index < len(bars):
                raise H1ContractError("replacement anchor marker is outside display")
            x = left + chart_width * index / denominator
            value = start_value + slope * index
            y = top + _price_y(value, low, high, chart_height)
            content.append(
                f'<circle data-anchor="{escape(label)}-{escape(str(anchor["kind"]))}" '
                f'cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}" '
                f'stroke="#f0f6fc" stroke-width="1"/>'
            )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Anchor-complete blinded case '
        f'{escape(str(case["case_id"]))}">'
        f'<rect width="100%" height="100%" fill="#0d1117"/>'
        f'<text x="16" y="20" fill="#f0f6fc" font-size="13">'
        f"{escape(str(case['case_id']))} · panel A purple · panel B orange</text>"
        + "".join(content)
        + "</svg>"
    )


def _build_replacement_blind_html(payload: dict[str, object]) -> bytes:
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        raise H1ContractError("replacement HTML inventory is not exact")
    sections = []
    for case in cases:
        sections.append(
            f"<section><h2>{escape(str(case['case_id']))}</h2>"
            f"<p>{escape(str(case['asset']))} · {escape(str(case['timeframe']))} · "
            f"{escape(str(case['side']))} · {escape(str(case['role']))}</p>"
            f'<div class="chart-scroll">{_replacement_case_svg(case)}</div></section>'
        )
    html = (
        '<!doctype html><html><head><meta charset="utf-8"><title>'
        "Trendlines V4 replacement blinded geometry review</title>"
        "<style>body{background:#161b22;color:#f0f6fc;font:14px system-ui;"
        "margin:24px}section{margin:16px 0;padding:12px;background:#21262d;"
        "border-radius:8px}.chart-scroll{overflow-x:auto;border:1px solid #30363d;"
        "background:#0d1117}svg{display:block;min-width:900px}h1{font-size:20px}"
        "p{color:#8b949e}.legend{color:#8b949e}</style></head><body>"
        "<h1>Replacement blinded geometry review</h1>"
        '<p class="legend">A is purple and B is orange. Both line anchors are marked. '
        "Rate A or B, BOTH, or NEITHER only after reviewing the complete context.</p>"
        + "".join(sections)
        + "</body></html>"
    )
    return html.encode("utf-8")


def _current_h1_implementation_hashes() -> dict[str, str]:
    return {
        "research/trendlines_v4/h1_profile_challenge.py": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "tests/research/trendlines_v4/test_h1_profile_challenge.py": hashlib.sha256(
            ROOT.joinpath(
                "tests/research/trendlines_v4/test_h1_profile_challenge.py"
            ).read_bytes()
        ).hexdigest(),
    }


def run_blind_review_remediation(
    output_dir: Path = REMEDIATION_OUTPUT_DIR,
) -> dict[str, object]:
    """Build only the fresh anchor-complete replacement packet."""

    if output_dir.exists() and any(output_dir.iterdir()):
        raise H1ContractError("replacement output directory is not empty")
    excluded = _original_scope_hashes()
    authority = verify_authorities()
    streams = h0.build_streams()
    membership = build_membership(streams)
    if membership["confirmation"]["results_published"] is not False:
        raise H1ContractError("confirmation results are not sealed")
    first = _run_semantic_matrix(streams, membership)
    replacement = _build_replacement_blind_packet(
        first,
        streams,
        membership,
        excluded,
    )
    payload = replacement["payload"]
    if not isinstance(payload, dict):
        raise H1ContractError("replacement payload is malformed")
    blind_bytes = _pretty_bytes(payload)
    html_bytes = _build_replacement_blind_html(payload)
    body: dict[str, object] = {
        "schema": "trendlines.v4.h1a.blind-review-remediation-manifest.v1",
        "scope": "fresh anchor-complete H1A selection-only blind review",
        "authority": authority,
        "original_h1a_artifact_hashes": dict(ORIGINAL_H1A_ARTIFACT_HASHES),
        "original_scope_exclusion_count": len(excluded),
        "selection_membership_hash": membership["selection"]["membership_hash"],
        "confirmation_membership_hash": membership["confirmation"]["membership_hash"],
        "confirmation_results_published": False,
        "case_count": EXPECTED_CASE_COUNT,
        "case_namespace": "review2",
        "mapping_commitment_sha256": replacement["mapping_commitment"],
        "mapping_count": replacement["mapping_count"],
        "panel_counts": {
            "A": replacement["assignment_counts"]["baseline_A"],
            "B": replacement["assignment_counts"]["baseline_B"],
        },
        "implementation_hashes": _current_h1_implementation_hashes(),
        "files": {
            "blind_cases.json": {
                "sha256": hashlib.sha256(blind_bytes).hexdigest(),
                "byte_length": len(blind_bytes),
            },
            "blind_review.html": {
                "sha256": hashlib.sha256(html_bytes).hexdigest(),
                "byte_length": len(html_bytes),
            },
        },
        "results_published": True,
        "identity_revealed": False,
    }
    body["manifest_id"] = _digest(body)
    manifest_bytes = _pretty_bytes(body)
    if output_dir.exists():
        if any(output_dir.iterdir()):
            raise H1ContractError("replacement output directory is not empty")
    else:
        output_dir.mkdir(parents=True)
    (output_dir / "blind_cases.json").write_bytes(blind_bytes)
    (output_dir / "blind_review.html").write_bytes(html_bytes)
    (output_dir / "manifest.json").write_bytes(manifest_bytes)
    return {
        "output_dir": output_dir.as_posix(),
        "manifest": body,
        "blind_cases": payload,
        "resource": first.resource,
    }


def main() -> int:
    try:
        result = run_h1()
    except (H1ContractError, H1ResourceBlocked, H1NumericalSemanticsBlocked) as exc:
        print(f"H1A_BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "conclusion": result["report"]["conclusion"],
                "selection_cutoff_count": EXPECTED_SELECTION_EVALUATIONS,
                "policy_count": EXPECTED_POLICY_COUNT,
                "evaluations_per_semantic_run": EXPECTED_SEMANTIC_EVALUATIONS,
                "blind_case_count": EXPECTED_CASE_COUNT,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
