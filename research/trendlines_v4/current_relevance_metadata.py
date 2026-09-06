"""Threshold-free, source-owned current-relevance metadata for V4."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Literal

from libs.models.trendlines_v4 import TrendlineGeometry, TrendlineSnapshot
from research.trendlines_v4 import exact_geometry_identity_persistence as n1

ROOT = Path(__file__).parents[2]
N1_OUTPUT_DIR = (
    ROOT / "artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1"
)
N1_REPORT_PATH = N1_OUTPUT_DIR / "report.json"
N1_MANIFEST_PATH = N1_OUTPUT_DIR / "manifest.json"
OUTPUT_DIR = ROOT / "artifacts/trendlines_v4/n2_current_relevance_metadata_v1"

REPORT_SCHEMA_VERSION = "trendlines_v4_current_relevance_metadata_report_v1"
MANIFEST_SCHEMA_VERSION = "trendlines_v4_current_relevance_metadata_manifest_v1"
IDENTITY_SCHEMA_VERSION = n1.IDENTITY_SCHEMA_VERSION
MEASUREMENT_BARS = n1.MEASUREMENT_BARS
WINDOW_LENGTH = n1.WINDOW_LENGTH
ROLES = n1.ROLES
SIDES = n1.SIDES
TIMEFRAMES = ("1h", "4h")
METRIC_FIELDS = (
    "anchor_span_bars",
    "start_anchor_age_bars",
    "end_anchor_age_bars",
    "start_anchor_headroom_bars",
    "absolute_close_distance_bps",
    "body_clearance_bps",
    "slope_bps_per_bar",
    "post_anchor_bar_count",
    "post_anchor_body_cross_count",
    "post_anchor_body_cross_rate",
    "bars_since_last_body_cross",
)

N2_AUTHORITY_HASHES = {
    "design": (
        ROOT
        / "plans/orchestrator-decision-trendlines-v4-n2-current-relevance-metadata-design-v1.md",
        "fb5d0d336d7e7441f25f8aeab3c1c5eee4f9e822bf6919e7ded0de0a8706f12d",
    ),
    "approval": (
        ROOT
        / "plans/orchestrator-decision-trendlines-v4-n2-current-relevance-metadata-design-approval-v1.md",
        "ff959581b854348f554d1e7bb14e618035d7f1bb0e545af62a17c19dc648c9bb",
    ),
}

N1_AUTHORITY_HASHES = {
    "approval": (
        ROOT
        / "plans/orchestrator-decision-trendlines-v4-n1-exact-identity-persistence-approval-v1.md",
        "fdf50eeaa9c49653ec2bde542417ae201bf08f3776c747b43c5116e376c4c5be",
    ),
}

N1_LOCKS = {
    "implementation": (
        ROOT / "research/trendlines_v4/exact_geometry_identity_persistence.py",
        "30e17266998b445d2fb12d75e0ede590c16ca2fec2d02f0879655f49b41e444d",
    ),
    "tests": (
        ROOT
        / "tests/research/trendlines_v4/test_exact_geometry_identity_persistence.py",
        "f23ad57ae9bc5a958c1bdcc88675d8e0049e90fac53cc714fa4191014a59bf9e",
    ),
    "report": (
        N1_REPORT_PATH,
        "30045237ff1bd763539addbf5645dadb862665512854731b1fdf3823c5499bd3",
    ),
    "manifest": (
        N1_MANIFEST_PATH,
        "9e270831b656e13b3df0e8c4cbb90e2ebeec4f24a9c5c56555c71b6d7506d464",
    ),
}


class N2ContractError(ValueError):
    """Raised when the frozen N2 or authenticated N1 contract is violated."""


@dataclass(frozen=True, slots=True)
class RelevanceObservation:
    """One non-null role observation at one causal cutoff."""

    asset: str
    timeframe: Literal["1h", "4h"]
    window: str
    cutoff: int
    market_as_of: str
    side: Literal["support", "resistance"]
    role: Literal["structural", "current_valid"]
    geometry_id: str
    anchor_span_bars: int
    start_anchor_age_bars: int
    end_anchor_age_bars: int
    start_anchor_headroom_bars: int
    absolute_close_distance_bps: float
    body_clearance_bps: float
    slope_bps_per_bar: float
    post_anchor_bar_count: int
    post_anchor_body_cross_count: int
    post_anchor_body_cross_rate: float
    bars_since_last_body_cross: int | None
    projection_positive: bool


@dataclass(frozen=True, slots=True)
class SnapshotPair:
    """Structural/current-valid IDs for one side and causal cutoff."""

    asset: str
    timeframe: Literal["1h", "4h"]
    window: str
    cutoff: int
    side: Literal["support", "resistance"]
    structural_id: str | None
    current_valid_id: str | None


@dataclass(frozen=True, slots=True)
class N1Reference:
    """Authenticated corrected N1 artifact view."""

    report: dict[str, object]
    manifest: dict[str, object]
    report_bytes: bytes
    manifest_bytes: bytes


@dataclass(frozen=True, slots=True)
class N2Measurement:
    """In-memory source view used to build compact N2 artifacts."""

    source_metadata: tuple[dict[str, object], ...]
    windows: tuple[dict[str, object], ...]
    observations: tuple[RelevanceObservation, ...]
    unique_geometry_observations: tuple[RelevanceObservation, ...]
    pairs: tuple[SnapshotPair, ...]
    n1_geometry_count: int
    n1_role_slot_count: int
    n1_pair_count: int
    n1_episode_count: int


@dataclass(frozen=True, slots=True)
class N2Computation:
    """One complete deterministic computation before publication."""

    measurement: N2Measurement
    report: dict[str, object]
    report_bytes: bytes


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _verify_hashes(
    specifications: dict[str, tuple[Path, str]],
) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, (path, expected) in specifications.items():
        if not path.is_file():
            raise N2ContractError(f"missing locked file: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise N2ContractError(f"locked hash mismatch: {name}")
        observed[name] = digest
    return observed


def _authority_view() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for name, (path, expected) in N2_AUTHORITY_HASHES.items():
        digest = _verify_hashes({name: (path, expected)})[name]
        result[name] = {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}
    return result


def _n1_authority_view() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for name, (path, expected) in N1_AUTHORITY_HASHES.items():
        digest = _verify_hashes({name: (path, expected)})[name]
        result[name] = {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}
    return result


def _load_n1_reference() -> N1Reference:
    locks = _verify_hashes(N1_LOCKS)
    report_bytes = N1_REPORT_PATH.read_bytes()
    manifest_bytes = N1_MANIFEST_PATH.read_bytes()
    try:
        report = json.loads(report_bytes)
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise N2ContractError("N1 artifacts are not valid JSON") from exc
    if (
        _pretty_bytes(report) != report_bytes
        or _pretty_bytes(manifest) != manifest_bytes
    ):
        raise N2ContractError("N1 artifacts are not canonical JSON")
    if report["inventory"] != {
        "episode_count": 2363,
        "measured_snapshot_count": 4800,
        "role_slot_count": 19200,
        "side_snapshot_pair_count": 9600,
        "unique_geometry_count": 1159,
    }:
        raise N2ContractError("N1 inventory changed")
    if manifest["report_sha256"] != locks["report"]:
        raise N2ContractError("N1 manifest report hash is inconsistent")
    if manifest["report_byte_length"] != len(report_bytes):
        raise N2ContractError("N1 manifest report length is inconsistent")
    manifest_id = manifest.get("manifest_id")
    body = dict(manifest)
    body.pop("manifest_id", None)
    if manifest_id != _digest(body):
        raise N2ContractError("N1 manifest identity is inconsistent")
    for window in report["windows"]:
        start = int(window["start_position"])
        if window["measurement_cutoffs"]["source_positions"] != [
            start + 300,
            start + 599,
        ]:
            raise N2ContractError("N1 cutoff metadata is not corrected")
    return N1Reference(report, manifest, report_bytes, manifest_bytes)


def _history_for_cutoff(
    window: n1.SelectedWindow,
    cutoff: int,
) -> tuple[n1.TrendlineBar, ...]:
    """Return only the source-owned 300-bar history for one cutoff."""

    if isinstance(cutoff, bool) or not 0 <= cutoff < n1.MEASUREMENT_BARS:
        raise N2ContractError("cutoff is outside the frozen measurement range")
    source_slice = window.bars[cutoff + 1 : cutoff + 301]
    if len(source_slice) != n1.MEASUREMENT_BARS:
        raise N2ContractError("N2 history is not exactly 300 bars")
    return n1._core_bars(source_slice)


def _anchor_positions(
    line: TrendlineGeometry,
    history: Sequence[n1.TrendlineBar],
) -> tuple[int, int]:
    try:
        start = n1._anchor_position(history, line.start_anchor_at)
        end = n1._anchor_position(history, line.end_anchor_at)
    except ValueError as exc:
        raise N2ContractError("line anchor is not uniquely present") from exc
    span = end - start
    if span <= 0:
        raise N2ContractError("line anchor span is not positive")
    if line.slope_per_bar != (line.end_anchor_price - line.start_anchor_price) / span:
        raise N2ContractError("line slope does not match anchor span")
    final_index = len(history) - 1
    if final_index - start != final_index - end + span:
        raise N2ContractError("anchor age invariant failed")
    return start, end


def _crossing_facts(
    line: TrendlineGeometry,
    history: Sequence[n1.TrendlineBar],
    end_index: int,
) -> tuple[int, int | None]:
    """Recompute the exact P0 body-crossing facts for one line."""

    intercept = line.end_anchor_price - line.slope_per_bar * end_index
    crossing_indices: list[int] = []
    for index in range(end_index + 1, len(history)):
        line_value = line.slope_per_bar * index + intercept
        body_top = max(history[index].open, history[index].close)
        body_bottom = min(history[index].open, history[index].close)
        if (line.side == "support" and body_bottom < line_value) or (
            line.side == "resistance" and body_top > line_value
        ):
            crossing_indices.append(index)
    count = len(crossing_indices)
    if count != line.post_anchor_body_cross_count:
        raise N2ContractError("P0 crossing-count parity failed")
    latest = None if not crossing_indices else len(history) - 1 - crossing_indices[-1]
    return count, latest


def _geometry_identity(
    line: TrendlineGeometry,
    history: Sequence[n1.TrendlineBar],
    *,
    asset: str,
    timeframe: Literal["1h", "4h"],
    n1_geometry_payloads: dict[str, dict[str, object]],
) -> str:
    payload = n1.identity_payload(
        line,
        history,
        asset=asset,
        timeframe=timeframe,
    )
    identifier = n1.geometry_id(payload)
    if identifier not in n1_geometry_payloads:
        raise N2ContractError("N2 geometry ID is absent from the N1 identity set")
    if n1_geometry_payloads[identifier] != payload:
        raise N2ContractError("N2 geometry content disagrees with N1")
    return identifier


def build_observation(
    line: TrendlineGeometry,
    history: Sequence[n1.TrendlineBar],
    *,
    asset: str,
    timeframe: Literal["1h", "4h"],
    window: str,
    cutoff: int,
    role: Literal["structural", "current_valid"],
    n1_geometry_payloads: dict[str, dict[str, object]],
) -> RelevanceObservation:
    """Build factual metadata from one already-authenticated P0 line/history."""

    if len(history) != MEASUREMENT_BARS:
        raise N2ContractError("observation history must contain 300 bars")
    start_index, end_index = _anchor_positions(line, history)
    geometry_identifier = _geometry_identity(
        line,
        history,
        asset=asset,
        timeframe=timeframe,
        n1_geometry_payloads=n1_geometry_payloads,
    )
    crossing_count, bars_since_last = _crossing_facts(line, history, end_index)
    current = history[-1]
    close = current.close
    level = line.projected_price_at_market_as_of
    if not math.isfinite(close) or close <= 0 or not math.isfinite(level):
        raise N2ContractError("current close or projected line is not finite-positive")
    body_bottom = min(current.open, current.close)
    body_top = max(current.open, current.close)
    if line.side == "support":
        body_clearance = (body_bottom - level) / close * 10_000
    else:
        body_clearance = (level - body_top) / close * 10_000
    values = (
        abs(close - level) / close * 10_000,
        body_clearance,
        line.slope_per_bar / close * 10_000,
        crossing_count / (len(history) - 1 - end_index)
        if len(history) - 1 - end_index
        else 0.0,
    )
    if not all(math.isfinite(value) for value in values):
        raise N2ContractError("N2 numeric metadata is not finite")
    final_index = len(history) - 1
    span = end_index - start_index
    return RelevanceObservation(
        asset=asset,
        timeframe=timeframe,
        window=window,
        cutoff=cutoff,
        market_as_of=n1._timestamp(current.closed_at),
        side=line.side,
        role=role,
        geometry_id=geometry_identifier,
        anchor_span_bars=span,
        start_anchor_age_bars=final_index - start_index,
        end_anchor_age_bars=final_index - end_index,
        start_anchor_headroom_bars=start_index,
        absolute_close_distance_bps=values[0],
        body_clearance_bps=values[1],
        slope_bps_per_bar=values[2],
        post_anchor_bar_count=final_index - end_index,
        post_anchor_body_cross_count=crossing_count,
        post_anchor_body_cross_rate=values[3],
        bars_since_last_body_cross=bars_since_last,
        projection_positive=line.projection_positive,
    )


def _observation_key(observation: RelevanceObservation) -> tuple[object, ...]:
    return (
        observation.asset,
        observation.timeframe,
        observation.window,
        observation.cutoff,
        observation.geometry_id,
    )


def _observation_without_role(observation: RelevanceObservation) -> tuple[object, ...]:
    return (
        observation.asset,
        observation.timeframe,
        observation.window,
        observation.cutoff,
        observation.market_as_of,
        observation.side,
        observation.geometry_id,
        *(getattr(observation, field) for field in METRIC_FIELDS),
        observation.projection_positive,
    )


def _register_unique(
    unique: dict[tuple[object, ...], RelevanceObservation],
    observation: RelevanceObservation,
) -> None:
    """Add one geometry-at-cutoff row, rejecting divergent duplicate facts."""

    key = _observation_key(observation)
    prior = unique.get(key)
    if prior is not None and _observation_without_role(prior) != (
        _observation_without_role(observation)
    ):
        raise N2ContractError("shared structural/current metadata disagrees")
    unique[key] = observation


def _n1_observation_key(row: n1.RoleObservation) -> tuple[object, ...]:
    return (
        row.asset,
        row.timeframe,
        row.window,
        row.cutoff,
        row.side,
        row.role,
    )


def _n1_pair_key(row: n1.PairObservation) -> tuple[object, ...]:
    return (row.asset, row.timeframe, row.window, row.cutoff, row.side)


def _same_pair(left: SnapshotPair, right: n1.PairObservation) -> bool:
    return (
        left.asset,
        left.timeframe,
        left.window,
        left.cutoff,
        left.side,
        left.structural_id,
        left.current_valid_id,
    ) == (
        right.asset,
        right.timeframe,
        right.window,
        right.cutoff,
        right.side,
        right.structural_id,
        right.current_valid_id,
    )


def measure_against_n1(
    reference: N1Reference,
    n1_measurement: n1.Measurement,
) -> N2Measurement:
    """Rebuild N2 from the unchanged core and authenticate it against N1."""

    n1_observations = {
        _n1_observation_key(row): row.geometry_id for row in n1_measurement.observations
    }
    n1_pairs = {_n1_pair_key(row): row for row in n1_measurement.pair_observations}
    n2_observations: list[RelevanceObservation] = []
    n2_pairs: list[SnapshotPair] = []
    unique: dict[tuple[object, ...], RelevanceObservation] = {}
    windows = tuple(dict(window) for window in reference.report["windows"])
    window_map = {
        (window["asset"], window["timeframe"], window["window"]): window
        for window in windows
    }
    for spec in n1.SOURCE_SPECS:
        asset = str(spec["asset"])
        one_hour = n1.read_source(spec)
        four_hour = n1.derive_4h(one_hour)
        for timeframe, series in (("1h", one_hour), ("4h", four_hour)):
            for window in n1.select_windows(series):
                expected_window = window_map[(asset, timeframe, window.label)]
                actual_window = n1._window_metadata(asset, timeframe, window)
                if actual_window != expected_window:
                    raise N2ContractError("N2 window corpus differs from N1")
                for cutoff in range(MEASUREMENT_BARS):
                    history = _history_for_cutoff(window, cutoff)
                    snapshot: TrendlineSnapshot = n1.analyze_trendlines(history)
                    ids: dict[str, str | None] = {}
                    for side in SIDES:
                        side_snapshot = getattr(snapshot, side)
                        for role in ROLES:
                            line = getattr(side_snapshot, role)
                            key = (asset, timeframe, window.label, cutoff, side, role)
                            if line is None:
                                if n1_observations[key] is not None:
                                    raise N2ContractError("N2 lost a non-null N1 role")
                                ids[role] = None
                                continue
                            observation = build_observation(
                                line,
                                history,
                                asset=asset,
                                timeframe=timeframe,
                                window=window.label,
                                cutoff=cutoff,
                                role=role,
                                n1_geometry_payloads=n1_measurement.geometry_payloads,
                            )
                            if n1_observations.get(key) != observation.geometry_id:
                                raise N2ContractError("N2 role ID differs from N1")
                            ids[role] = observation.geometry_id
                            n2_observations.append(observation)
                            _register_unique(unique, observation)
                        pair = SnapshotPair(
                            asset=asset,
                            timeframe=timeframe,
                            window=window.label,
                            cutoff=cutoff,
                            side=side,
                            structural_id=ids["structural"],
                            current_valid_id=ids["current_valid"],
                        )
                        expected_pair = n1_pairs[
                            (asset, timeframe, window.label, cutoff, side)
                        ]
                        if not _same_pair(pair, expected_pair):
                            raise N2ContractError(
                                "N2 structural/current pair differs from N1"
                            )
                        n2_pairs.append(pair)
    n2_by_key = {
        (
            row.asset,
            row.timeframe,
            row.window,
            row.cutoff,
            row.side,
            row.role,
        ): row.geometry_id
        for row in n2_observations
    }
    expected_non_null = {
        key: value for key, value in n1_observations.items() if value is not None
    }
    if n2_by_key != expected_non_null:
        raise N2ContractError("N2 non-null role inventory differs from N1")
    if {row.geometry_id for row in unique.values()} != set(
        n1_measurement.geometry_payloads
    ):
        raise N2ContractError("N2 geometry identity set differs from N1")
    if len(n2_pairs) != len(n1_measurement.pair_observations):
        raise N2ContractError("N2 pair inventory differs from N1")
    return N2Measurement(
        source_metadata=tuple(
            dict(source) for source in reference.report["source_metadata"]
        ),
        windows=windows,
        observations=tuple(n2_observations),
        unique_geometry_observations=tuple(unique.values()),
        pairs=tuple(n2_pairs),
        n1_geometry_count=len(n1_measurement.geometry_payloads),
        n1_role_slot_count=len(n1_measurement.observations),
        n1_pair_count=len(n1_measurement.pair_observations),
        n1_episode_count=len(n1_measurement.episodes),
    )


def _scope_match(
    item: RelevanceObservation | SnapshotPair,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    side: str | None = None,
    role: str | None = None,
) -> bool:
    return (
        (asset is None or item.asset == asset)
        and (timeframe is None or item.timeframe == timeframe)
        and (side is None or item.side == side)
        and (role is None or getattr(item, "role", None) == role)
    )


def _distribution(
    rows: Sequence[RelevanceObservation], field: str
) -> dict[str, object]:
    values = [
        float(getattr(row, field)) for row in rows if getattr(row, field) is not None
    ]
    if not values:
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
        "count": len(values),
        "min": min(values),
        "median": median(values),
        "p75": n1._percentile(values, 0.75),
        "p90": n1._percentile(values, 0.90),
        "p95": n1._percentile(values, 0.95),
        "max": max(values),
    }


def summarize_scope(
    rows: Sequence[RelevanceObservation],
    pairs: Sequence[SnapshotPair],
) -> dict[str, object]:
    """Summarize factual metadata without selecting or scoring lines."""

    pair_count = len(pairs)
    shared_count = sum(
        pair.structural_id is not None and pair.structural_id == pair.current_valid_id
        for pair in pairs
    )
    row_count = len(rows)
    negative_count = sum(row.body_clearance_bps < 0 for row in rows)
    zero_count = sum(row.body_clearance_bps == 0.0 for row in rows)
    non_positive_projection_count = sum(not row.projection_positive for row in rows)
    crossed_count = sum(row.post_anchor_body_cross_count > 0 for row in rows)
    headroom_zero_count = sum(row.start_anchor_headroom_bars == 0 for row in rows)
    headroom_first_five_count = sum(row.start_anchor_headroom_bars <= 4 for row in rows)
    recent_cross_count = sum(row.bars_since_last_body_cross is not None for row in rows)
    return {
        "observation_count": row_count,
        "unique_geometry_at_cutoff_count": len({_observation_key(row) for row in rows}),
        "distributions": {field: _distribution(rows, field) for field in METRIC_FIELDS},
        "negative_body_clearance_rate": negative_count / row_count
        if row_count
        else 0.0,
        "exact_zero_body_clearance_count": zero_count,
        "projection_non_positive_rate": non_positive_projection_count / row_count
        if row_count
        else 0.0,
        "any_post_anchor_cross_rate": crossed_count / row_count if row_count else 0.0,
        "no_post_anchor_cross_rate": (
            (row_count - crossed_count) / row_count if row_count else 0.0
        ),
        "start_anchor_headroom_zero_count": headroom_zero_count,
        "start_anchor_headroom_at_most_four_count": headroom_first_five_count,
        "bars_since_last_body_cross_non_null_count": recent_cross_count,
        "shared_structural_current_geometry_count": shared_count,
        "shared_structural_current_geometry_rate": shared_count / pair_count
        if pair_count
        else 0.0,
    }


def _group_rows(
    rows: Sequence[RelevanceObservation],
    pairs: Sequence[SnapshotPair],
    **filters: str,
) -> tuple[tuple[RelevanceObservation, ...], tuple[SnapshotPair, ...]]:
    return (
        tuple(row for row in rows if _scope_match(row, **filters)),
        tuple(pair for pair in pairs if _scope_match(pair, **filters)),
    )


def build_report(measurement: N2Measurement) -> dict[str, object]:
    """Build the compact descriptive report."""

    role_groups: dict[str, dict[str, object]] = {}
    role_groups["global"] = summarize_scope(measurement.observations, measurement.pairs)
    role_groups["asset_timeframe"] = {}
    for spec in n1.SOURCE_SPECS:
        asset = str(spec["asset"])
        for timeframe in TIMEFRAMES:
            rows, pairs = _group_rows(
                measurement.observations,
                measurement.pairs,
                asset=asset,
                timeframe=timeframe,
            )
            role_groups["asset_timeframe"][f"{asset}:{timeframe}"] = summarize_scope(
                rows, pairs
            )
    role_groups["timeframe"] = {}
    for timeframe in TIMEFRAMES:
        rows, pairs = _group_rows(
            measurement.observations, measurement.pairs, timeframe=timeframe
        )
        role_groups["timeframe"][timeframe] = summarize_scope(rows, pairs)
    role_groups["side_role"] = {}
    for side in SIDES:
        for role in ROLES:
            rows, pairs = _group_rows(
                measurement.observations,
                measurement.pairs,
                side=side,
                role=role,
            )
            role_groups["side_role"][f"{side}.{role}"] = summarize_scope(rows, pairs)

    geometry_groups: dict[str, dict[str, object]] = {}
    geometry_groups["global"] = summarize_scope(
        measurement.unique_geometry_observations, measurement.pairs
    )
    geometry_groups["timeframe"] = {}
    for timeframe in TIMEFRAMES:
        rows, pairs = _group_rows(
            measurement.unique_geometry_observations,
            measurement.pairs,
            timeframe=timeframe,
        )
        geometry_groups["timeframe"][timeframe] = summarize_scope(rows, pairs)
    geometry_groups["side"] = {}
    for side in SIDES:
        rows, pairs = _group_rows(
            measurement.unique_geometry_observations,
            measurement.pairs,
            side=side,
        )
        geometry_groups["side"][side] = summarize_scope(rows, pairs)

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "metric_fields": list(METRIC_FIELDS),
        "metric_definitions": {
            "absolute_close_distance_bps": "abs(close - projected_line) / close * 10000",
            "support_body_clearance_bps": "(body_bottom - projected_line) / close * 10000",
            "resistance_body_clearance_bps": "(projected_line - body_top) / close * 10000",
            "slope_bps_per_bar": "slope_per_bar / close * 10000",
            "crossing_semantics": "strict P0 body crossing after the end anchor; equality and wick-only contact do not cross",
            "percentile_definition": "R-7 linear interpolation",
        },
        "inventory": {
            "window_count": len(measurement.windows),
            "measured_snapshot_count": len(measurement.windows) * MEASUREMENT_BARS,
            "role_slot_count": measurement.n1_role_slot_count,
            "side_snapshot_pair_count": measurement.n1_pair_count,
            "non_null_role_observation_count": len(measurement.observations),
            "unique_geometry_at_cutoff_count": len(
                measurement.unique_geometry_observations
            ),
            "n1_unique_geometry_count": measurement.n1_geometry_count,
            "n1_episode_count": measurement.n1_episode_count,
        },
        "n1_consistency": {
            "n1_snapshot_count": 4800,
            "n1_role_slot_count": measurement.n1_role_slot_count,
            "n1_side_snapshot_pair_count": measurement.n1_pair_count,
            "n1_unique_geometry_count": measurement.n1_geometry_count,
            "n1_episode_count": measurement.n1_episode_count,
            "geometry_id_set_reused_exactly": True,
            "window_cutoff_corpus_reused_exactly": True,
            "p0_crossing_semantics_reused": True,
        },
        "role_observations": role_groups,
        "unique_geometry_at_cutoff": geometry_groups,
        "windows": measurement.windows,
        "source_metadata": measurement.source_metadata,
        "conclusion": "CURRENT_RELEVANCE_METADATA_SUPPORTED",
        "interpretation": "Descriptive metadata only; no relevance score, threshold, selection, or production recommendation.",
    }


def _n1_artifact_view() -> dict[str, dict[str, object]]:
    return {
        name: {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": expected,
        }
        for name, (path, expected) in N1_LOCKS.items()
    }


def build_manifest(
    measurement: N2Measurement,
    report: dict[str, object],
    report_bytes: bytes,
    *,
    rerun_evidence: dict[str, object],
) -> dict[str, object]:
    """Build deterministic N2 provenance, excluding only its own ID."""

    protected = n1._protected_hashes()
    body: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "report_schema_version": report["schema_version"],
        "design_scope": "N2 threshold-free current relevance metadata only",
        "n2_authority_hashes": _authority_view(),
        "n1_authority_hashes": _n1_authority_view(),
        "n1_locks": _n1_artifact_view(),
        "production_protected_hashes": protected,
        "source_specs": [dict(spec) for spec in n1.SOURCE_SPECS],
        "source_metadata": measurement.source_metadata,
        "four_hour_aggregation_contract": n1.FOUR_HOUR_AGGREGATION_ID,
        "window_selection": {
            "window_length": WINDOW_LENGTH,
            "measurement_bars": MEASUREMENT_BARS,
            "fractions": list(n1.WINDOW_FRACTIONS),
            "rounding": "floor(fraction * (eligible_start_count - 1))",
            "measurement_slice": "window[cutoff+1:cutoff+301] for cutoff 0..299",
            "source_cutoff_positions": "start_position+300 through start_position+599",
        },
        "metric_fields": list(METRIC_FIELDS),
        "metric_definitions": report["metric_definitions"],
        "expected_inventory": {
            "window_count": 16,
            "snapshot_count": 4800,
            "role_slot_count": 19200,
            "side_snapshot_pair_count": 9600,
        },
        "observed_inventory": report["inventory"],
        "windows": measurement.windows,
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report_byte_length": len(report_bytes),
        "deterministic_rerun": rerun_evidence,
    }
    return {**body, "manifest_id": _digest(body)}


def _compute_n2() -> N2Computation:
    reference = _load_n1_reference()
    n1_measurement = n1.run_measurement()
    measurement = measure_against_n1(reference, n1_measurement)
    report = build_report(measurement)
    return N2Computation(measurement, report, _pretty_bytes(report))


def run_n2(
    output_dir: str | Path = OUTPUT_DIR,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run N2 twice on identical locked inputs and publish exactly two artifacts."""

    first = _compute_n2()
    second = _compute_n2()
    if first.report_bytes != second.report_bytes:
        raise N2ContractError("N2 deterministic report rerun differs")
    rerun_evidence = {
        "run_count": 2,
        "report_bytes_equal": True,
        "manifest_body_equal": True,
    }
    first_manifest = build_manifest(
        first.measurement,
        first.report,
        first.report_bytes,
        rerun_evidence=rerun_evidence,
    )
    second_manifest = build_manifest(
        second.measurement,
        second.report,
        second.report_bytes,
        rerun_evidence=rerun_evidence,
    )
    first_manifest_bytes = _pretty_bytes(first_manifest)
    second_manifest_bytes = _pretty_bytes(second_manifest)
    if first_manifest_bytes != second_manifest_bytes:
        raise N2ContractError("N2 deterministic manifest rerun differs")
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    allowed = {"report.json", "manifest.json"}
    unexpected = {path.name for path in target.iterdir()} - allowed
    if unexpected:
        raise N2ContractError(f"unexpected N2 artifact members: {sorted(unexpected)}")
    (target / "report.json").write_bytes(second.report_bytes)
    (target / "manifest.json").write_bytes(second_manifest_bytes)
    return second.report, second_manifest


def main() -> None:
    report, manifest = run_n2()
    print(
        json.dumps(
            {
                "schema_version": report["schema_version"],
                "manifest_id": manifest["manifest_id"],
                "window_count": report["inventory"]["window_count"],
                "non_null_role_observation_count": report["inventory"][
                    "non_null_role_observation_count"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
