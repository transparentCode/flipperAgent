"""Exact geometry identity and observational persistence measurements for V4."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Literal

from libs.models.trendlines_v4 import (
    HISTORY_CAPACITY_BARS,
    TrendlineBar,
    TrendlineGeometry,
    analyze_trendlines,
)

ROOT = Path(__file__).parents[2]
WINDOW_LENGTH = 600
MEASUREMENT_BARS = 300
WINDOW_FRACTIONS = (0.20, 0.80)
WINDOW_ROLES = ("early", "late")
ROLES = ("structural", "current_valid")
SIDES = ("support", "resistance")
IDENTITY_SCHEMA_VERSION = "trendlines_v4_exact_geometry_identity_v1"
REPORT_SCHEMA_VERSION = "trendlines_v4_exact_geometry_identity_persistence_v1"
MANIFEST_SCHEMA_VERSION = (
    "trendlines_v4_exact_geometry_identity_persistence_manifest_v1"
)
FOUR_HOUR_AGGREGATION_ID = "utc_four_hour_contiguous_groups_v1"
PERCENTILE_DEFINITION = "R-7 linear interpolation"
DEFAULT_OUTPUT_DIR = (
    ROOT / "artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1"
)

SOURCE_SPECS = (
    {
        "asset": "BTCUSDT",
        "path": "src/libs/regime/optimization/results/BTCUSDT_1h_2022-01-01_2026-03-01.csv",
        "sha256": "3061187fd7092131e7df221fb1c23ea4427ba9754284910d79d47872858c0f66",
        "row_count": 36481,
    },
    {
        "asset": "ETHUSDT",
        "path": "src/libs/models/trendlines/optimization/results/ETHUSDT_1h_2023-01-01_2026-03-01.csv",
        "sha256": "96bc7f72e56a4ad70048a17caaa0013dd9ef854b11e7ba6aafc2681ce21d3e77",
        "row_count": 27721,
    },
    {
        "asset": "SOLUSDT",
        "path": "src/libs/models/trendlines/optimization/results/SOLUSDT_1h_2023-01-01_2026-03-01.csv",
        "sha256": "0711849c9e665c8b5bdba85ffee4cda0eb16f9aa30f7b74678bf09d17bf19c46",
        "row_count": 27721,
    },
    {
        "asset": "HYPEUSDT",
        "path": "src/libs/models/trendlines/optimization/results/HYPEUSDT_1h_2022-01-01_2026-03-01.csv",
        "sha256": "26e7f4276c60ea4c4d3dbe196383c1ef63c1c58d6db1b6280b821490d694d050",
        "row_count": 6591,
    },
)

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

N1_AUTHORITY_HASHES = {
    "design": (
        ROOT
        / "plans/orchestrator-decision-trendlines-v4-n1-exact-identity-persistence-design-v1.md",
        "4dd495773fa430a018e5ad3a9c5b3dd01b52c4d982278767819c482c399afa87",
    ),
    "approval": (
        ROOT
        / "plans/orchestrator-decision-trendlines-v4-n1-exact-identity-persistence-design-approval-v1.md",
        "6f6af736c528e5b9fd5dd44fb8f2a02e42a162eeb296e1e956464f6aa9193642",
    ),
}


class N1ContractError(ValueError):
    """Raised when the frozen N1 source or measurement contract is violated."""


@dataclass(frozen=True, slots=True)
class SourceBar:
    """One validated source OHLC bar with explicit UTC open and close times."""

    open_at: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        for name in ("open_at", "closed_at"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise TypeError(f"{name} must be timezone-aware")
            if value.utcoffset() != timedelta(0):
                raise ValueError(f"{name} must be UTC")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.closed_at <= self.open_at:
            raise ValueError("closed_at must be later than open_at")
        try:
            TrendlineBar(
                closed_at=self.closed_at,
                open=self.open,
                high=self.high,
                low=self.low,
                close=self.close,
            )
        except (TypeError, ValueError) as exc:
            raise N1ContractError("source OHLC is not a valid TrendlineBar") from exc


@dataclass(frozen=True, slots=True)
class SelectedWindow:
    """One deterministic 600-bar source window."""

    label: str
    start_position: int
    bars: tuple[SourceBar, ...]

    def __post_init__(self) -> None:
        if self.label not in WINDOW_ROLES:
            raise ValueError("unknown window label")
        if len(self.bars) != WINDOW_LENGTH:
            raise ValueError("selected window must contain exactly 600 bars")


@dataclass(frozen=True, slots=True)
class RoleObservation:
    """One role value at one source-owned measurement cutoff."""

    asset: str
    timeframe: Literal["1h", "4h"]
    window: str
    cutoff: int
    side: str
    role: str
    geometry_id: str | None


@dataclass(frozen=True, slots=True)
class PairObservation:
    """Structural/current-valid IDs for one side and cutoff."""

    asset: str
    timeframe: Literal["1h", "4h"]
    window: str
    cutoff: int
    side: str
    structural_id: str | None
    current_valid_id: str | None


@dataclass(frozen=True, slots=True)
class Episode:
    """One maximal consecutive exact-ID run for a role."""

    asset: str
    timeframe: Literal["1h", "4h"]
    window: str
    side: str
    role: str
    geometry_id: str
    start_cutoff: int
    end_cutoff: int
    lifetime_bars: int
    event: Literal["BIRTH", "REAPPEAR"]
    episode_id: str


@dataclass(frozen=True, slots=True)
class Measurement:
    """Compact N1 observation tape retained for report construction."""

    source_metadata: tuple[dict[str, object], ...]
    windows: tuple[dict[str, object], ...]
    observations: tuple[RoleObservation, ...]
    pair_observations: tuple[PairObservation, ...]
    episodes: tuple[Episode, ...]
    geometry_payloads: dict[str, dict[str, object]]
    identity_collision_count: int
    identity_content_mismatch_count: int
    source_gap_failure_count: int
    aggregation_failure_count: int

    @property
    def snapshot_count(self) -> int:
        return len(self.windows) * MEASUREMENT_BARS


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timestamp must be timezone-aware")
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise N1ContractError(f"{field_name} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise N1ContractError(f"invalid {field_name}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed.utcoffset() != timedelta(0):
        raise N1ContractError(f"{field_name} must be UTC")
    return parsed.astimezone(UTC)


def _source_path(spec: dict[str, object]) -> Path:
    return ROOT / str(spec["path"])


def read_source(spec: dict[str, object]) -> tuple[SourceBar, ...]:
    """Read and fully validate one frozen local 1h source."""

    path = _source_path(spec)
    if not path.is_file():
        raise N1ContractError(f"missing frozen source: {path}")
    observed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed_hash != spec["sha256"]:
        raise N1ContractError(f"source hash mismatch for {spec['asset']}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        required = {"open_time", "open", "high", "low", "close", "close_time"}
        if rows.fieldnames is None or not required.issubset(rows.fieldnames):
            raise N1ContractError("source schema does not contain frozen OHLC fields")
        bars: list[SourceBar] = []
        for index, row in enumerate(rows):
            try:
                bar = SourceBar(
                    open_at=_parse_timestamp(row["open_time"], field_name="open_time"),
                    closed_at=_parse_timestamp(
                        row["close_time"], field_name="close_time"
                    ),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise N1ContractError(f"invalid source row {index}") from exc
            if bars:
                previous = bars[-1]
                if bar.open_at - previous.open_at != timedelta(hours=1):
                    raise N1ContractError("1h source contains a gap or overlap")
                if bar.closed_at <= previous.closed_at:
                    raise N1ContractError("source close times must increase")
            bars.append(bar)
    if len(bars) != spec["row_count"]:
        raise N1ContractError(
            f"source row count mismatch for {spec['asset']}: {len(bars)}"
        )
    return tuple(bars)


def derive_4h(bars: Sequence[SourceBar]) -> tuple[SourceBar, ...]:
    """Aggregate exact contiguous UTC four-bar groups without bridging gaps."""

    source = tuple(bars)
    if not source:
        raise N1ContractError("cannot aggregate an empty source")
    aligned = next(
        (
            index
            for index, bar in enumerate(source)
            if bar.open_at.minute == 0
            and bar.open_at.second == 0
            and bar.open_at.microsecond == 0
            and bar.open_at.hour % 4 == 0
        ),
        None,
    )
    if aligned is None:
        raise N1ContractError("source has no aligned 4h bucket")
    result: list[SourceBar] = []
    index = aligned
    while index + 4 <= len(source):
        group = source[index : index + 4]
        expected_opens = tuple(
            group[0].open_at + timedelta(hours=offset) for offset in range(4)
        )
        if (
            group[0].open_at.hour % 4 != 0
            or tuple(bar.open_at for bar in group) != expected_opens
        ):
            raise N1ContractError("incomplete or misaligned interior 4h bucket")
        result.append(
            SourceBar(
                open_at=group[0].open_at,
                closed_at=group[-1].closed_at,
                open=group[0].open,
                high=max(bar.high for bar in group),
                low=min(bar.low for bar in group),
                close=group[-1].close,
            )
        )
        index += 4
    if not result:
        raise N1ContractError("source has no complete 4h buckets")
    for previous, current in pairwise(result):
        if current.open_at - previous.open_at != timedelta(hours=4):
            raise N1ContractError("derived 4h bars are not contiguous")
    return tuple(result)


def select_windows(bars: Sequence[SourceBar]) -> tuple[SelectedWindow, ...]:
    """Select the frozen early/late 600-bar windows by source position."""

    source = tuple(bars)
    eligible_count = len(source) - WINDOW_LENGTH + 1
    if eligible_count < 2:
        raise N1ContractError("source cannot provide two 600-bar windows")
    starts = tuple(
        math.floor(fraction * (eligible_count - 1)) for fraction in WINDOW_FRACTIONS
    )
    if starts[0] == starts[1]:
        raise N1ContractError("frozen window starts are not distinct")
    return tuple(
        SelectedWindow(label, start, source[start : start + WINDOW_LENGTH])
        for label, start in zip(WINDOW_ROLES, starts)
    )


def _anchor_position(history: Sequence[TrendlineBar], timestamp: datetime) -> int:
    matches = [index for index, bar in enumerate(history) if bar.closed_at == timestamp]
    if len(matches) != 1:
        raise N1ContractError("anchor timestamp is not uniquely present in history")
    return matches[0]


def identity_payload(
    line: TrendlineGeometry,
    history: Sequence[TrendlineBar],
    *,
    asset: str,
    timeframe: Literal["1h", "4h"],
) -> dict[str, object]:
    """Return the exact role-independent identity payload for one emitted line."""

    start_position = _anchor_position(history, line.start_anchor_at)
    end_position = _anchor_position(history, line.end_anchor_at)
    span = end_position - start_position
    if span <= 0:
        raise N1ContractError("anchor span must be positive")
    expected_slope = (line.end_anchor_price - line.start_anchor_price) / span
    if line.slope_per_bar != expected_slope:
        raise N1ContractError("line slope does not match exact anchor span")
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "asset": asset,
        "timeframe": timeframe,
        "side": line.side,
        "start_anchor_at": _timestamp(line.start_anchor_at),
        "start_anchor_price": line.start_anchor_price.hex(),
        "end_anchor_at": _timestamp(line.end_anchor_at),
        "end_anchor_price": line.end_anchor_price.hex(),
        "anchor_span_bars": span,
    }


def geometry_id(payload: dict[str, object]) -> str:
    """Hash one validated identity payload."""

    if payload.get("schema_version") != IDENTITY_SCHEMA_VERSION:
        raise N1ContractError("identity payload has the wrong schema")
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _core_bars(window_bars: Sequence[SourceBar]) -> tuple[TrendlineBar, ...]:
    return tuple(
        TrendlineBar(
            closed_at=bar.closed_at,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in window_bars
    )


def _episode_id(
    asset: str,
    timeframe: str,
    window: str,
    side: str,
    role: str,
    geometry: str,
    start_cutoff: int,
) -> str:
    return _digest(
        {
            "asset": asset,
            "timeframe": timeframe,
            "window": window,
            "side": side,
            "role": role,
            "geometry_id": geometry,
            "start_cutoff": start_cutoff,
        }
    )


def reconstruct_episodes(
    observations: Sequence[RoleObservation],
) -> tuple[Episode, ...]:
    """Build independent exact-ID episodes without carrying state across windows."""

    grouped: dict[tuple[str, str, str, str, str], list[RoleObservation]] = {}
    for observation in observations:
        key = (
            observation.asset,
            observation.timeframe,
            observation.window,
            observation.side,
            observation.role,
        )
        grouped.setdefault(key, []).append(observation)
    episodes: list[Episode] = []
    for key, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: row.cutoff)
        if [row.cutoff for row in ordered] != list(range(MEASUREMENT_BARS)):
            raise N1ContractError("role observations do not cover every cutoff")
        seen: set[str] = set()
        current_id: str | None = None
        current_start: int | None = None

        reappearance_starts: set[int] = set()

        def close(
            end_cutoff: int,
            *,
            scope_key: tuple[str, str, str, str, str] = key,
            reappearances: set[int] = reappearance_starts,
        ) -> None:
            nonlocal current_id, current_start
            if current_id is None or current_start is None:
                return
            episode_id = _episode_id(*scope_key, current_id, current_start)
            episodes.append(
                Episode(
                    asset=scope_key[0],
                    timeframe=scope_key[1],
                    window=scope_key[2],
                    side=scope_key[3],
                    role=scope_key[4],
                    geometry_id=current_id,
                    start_cutoff=current_start,
                    end_cutoff=end_cutoff,
                    lifetime_bars=end_cutoff - current_start + 1,
                    event="REAPPEAR" if current_start in reappearances else "BIRTH",
                    episode_id=episode_id,
                )
            )
            current_id = None
            current_start = None

        for row in ordered:
            geometry = row.geometry_id
            if geometry == current_id:
                continue
            if current_id is not None:
                close(row.cutoff - 1)
            if geometry is None:
                continue
            if geometry in seen:
                reappearance_starts.add(row.cutoff)
            seen.add(geometry)
            current_id = geometry
            current_start = row.cutoff
        close(MEASUREMENT_BARS - 1)
    return tuple(sorted(episodes, key=lambda item: item.episode_id))


def _observation_value(
    line: TrendlineGeometry | None,
    history: Sequence[TrendlineBar],
    *,
    asset: str,
    timeframe: Literal["1h", "4h"],
    content: dict[str, dict[str, object]],
) -> str | None:
    if line is None:
        return None
    payload = identity_payload(
        line,
        history,
        asset=asset,
        timeframe=timeframe,
    )
    identifier = geometry_id(payload)
    previous = content.get(identifier)
    if previous is not None and previous != payload:
        raise N1ContractError("geometry identity content collision")
    content[identifier] = payload
    return identifier


def measure_window(
    asset: str,
    timeframe: Literal["1h", "4h"],
    window: SelectedWindow,
    content: dict[str, dict[str, object]],
) -> tuple[tuple[RoleObservation, ...], tuple[PairObservation, ...]]:
    """Measure exactly 300 explicit 300-bar core calls for one window."""

    observations: list[RoleObservation] = []
    pairs: list[PairObservation] = []
    for cutoff in range(MEASUREMENT_BARS):
        source_slice = window.bars[cutoff + 1 : cutoff + 1 + MEASUREMENT_BARS]
        if len(source_slice) != MEASUREMENT_BARS:
            raise N1ContractError("measurement slice is not exactly 300 bars")
        history = _core_bars(source_slice)
        snapshot = analyze_trendlines(history)
        for side in SIDES:
            side_snapshot = getattr(snapshot, side)
            ids: dict[str, str | None] = {}
            for role in ROLES:
                identifier = _observation_value(
                    getattr(side_snapshot, role),
                    history,
                    asset=asset,
                    timeframe=timeframe,
                    content=content,
                )
                ids[role] = identifier
                observations.append(
                    RoleObservation(
                        asset=asset,
                        timeframe=timeframe,
                        window=window.label,
                        cutoff=cutoff,
                        side=side,
                        role=role,
                        geometry_id=identifier,
                    )
                )
            pairs.append(
                PairObservation(
                    asset=asset,
                    timeframe=timeframe,
                    window=window.label,
                    cutoff=cutoff,
                    side=side,
                    structural_id=ids["structural"],
                    current_valid_id=ids["current_valid"],
                )
            )
    return tuple(observations), tuple(pairs)


def _source_metadata(
    spec: dict[str, object], bars: Sequence[SourceBar]
) -> dict[str, object]:
    return {
        "asset": spec["asset"],
        "timeframe": "1h",
        "path": spec["path"],
        "sha256": spec["sha256"],
        "row_count": len(bars),
        "first_open_at": _timestamp(bars[0].open_at),
        "last_close_at": _timestamp(bars[-1].closed_at),
    }


def _window_metadata(
    asset: str,
    timeframe: Literal["1h", "4h"],
    window: SelectedWindow,
) -> dict[str, object]:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "window": window.label,
        "start_position": window.start_position,
        "end_position_exclusive": window.start_position + WINDOW_LENGTH,
        "first_open_at": _timestamp(window.bars[0].open_at),
        "last_close_at": _timestamp(window.bars[-1].closed_at),
        "measurement_cutoffs": {
            "source_positions": [
                window.start_position + MEASUREMENT_BARS,
                window.start_position + WINDOW_LENGTH - 1,
            ],
            "core_slice": "window[cutoff+1:cutoff+301] for cutoff 0..299",
            "core_bar_count": MEASUREMENT_BARS,
        },
    }


def run_measurement() -> Measurement:
    """Execute the complete locked 4-asset × 2-timeframe N1 measurement."""

    sources: list[dict[str, object]] = []
    window_metadata: list[dict[str, object]] = []
    observations: list[RoleObservation] = []
    pairs: list[PairObservation] = []
    content: dict[str, dict[str, object]] = {}
    for spec in SOURCE_SPECS:
        one_hour = read_source(spec)
        four_hour = derive_4h(one_hour)
        sources.append(_source_metadata(spec, one_hour))
        for timeframe, series in (("1h", one_hour), ("4h", four_hour)):
            windows = select_windows(series)
            for window in windows:
                window_metadata.append(
                    _window_metadata(spec["asset"], timeframe, window)
                )
                measured, measured_pairs = measure_window(
                    spec["asset"], timeframe, window, content
                )
                observations.extend(measured)
                pairs.extend(measured_pairs)
    if len(window_metadata) != 16:
        raise N1ContractError("expected exactly 16 windows")
    if len(observations) != 19200:
        raise N1ContractError("expected exactly 19,200 role observations")
    if len(pairs) != 9600:
        raise N1ContractError("expected exactly 9,600 side snapshot pairs")
    episodes = reconstruct_episodes(observations)
    return Measurement(
        source_metadata=tuple(sources),
        windows=tuple(window_metadata),
        observations=tuple(observations),
        pair_observations=tuple(pairs),
        episodes=episodes,
        geometry_payloads=content,
        identity_collision_count=0,
        identity_content_mismatch_count=0,
        source_gap_failure_count=0,
        aggregation_failure_count=0,
    )


def _percentile(values: Sequence[int | float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if not 0 <= fraction <= 1:
        raise ValueError("percentile fraction must be within [0, 1]")
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _scope_match(
    item: RoleObservation | PairObservation | Episode,
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


def _replacement_statistics(
    rows: Sequence[RoleObservation],
) -> tuple[int, int]:
    """Count replacements and eligible transitions across each role stream."""

    grouped: dict[tuple[str, str, str, str, str], list[RoleObservation]] = {}
    for row in rows:
        key = (row.asset, row.timeframe, row.window, row.side, row.role)
        grouped.setdefault(key, []).append(row)
    replacements = 0
    transitions = 0
    for scoped_rows in grouped.values():
        ordered = sorted(scoped_rows, key=lambda row: row.cutoff)
        for previous, current in pairwise(ordered):
            if current.cutoff != previous.cutoff + 1:
                continue
            transitions += 1
            if (
                previous.geometry_id is not None
                and current.geometry_id is not None
                and previous.geometry_id != current.geometry_id
            ):
                replacements += 1
    return replacements, transitions


def _group_metrics(
    measurement: Measurement,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    side: str | None = None,
    role: str | None = None,
) -> dict[str, object]:
    rows = tuple(
        row
        for row in measurement.observations
        if _scope_match(row, asset=asset, timeframe=timeframe, side=side, role=role)
    )
    episode_rows = tuple(
        episode
        for episode in measurement.episodes
        if _scope_match(episode, asset=asset, timeframe=timeframe, side=side, role=role)
    )
    pair_rows = tuple(
        pair
        for pair in measurement.pair_observations
        if _scope_match(pair, asset=asset, timeframe=timeframe, side=side)
    )
    available = tuple(row.geometry_id for row in rows if row.geometry_id is not None)
    lifetimes = [episode.lifetime_bars for episode in episode_rows]
    first_appearances = sum(episode.event == "BIRTH" for episode in episode_rows)
    reappearance_episodes = tuple(
        episode for episode in episode_rows if episode.event == "REAPPEAR"
    )
    pair_count = len(pair_rows)
    shared = sum(
        pair.structural_id is not None and pair.structural_id == pair.current_valid_id
        for pair in pair_rows
    )
    divergence = sum(
        pair.structural_id is not None
        and pair.current_valid_id is not None
        and pair.structural_id != pair.current_valid_id
        for pair in pair_rows
    )
    cutoff_count = len(
        {(row.asset, row.timeframe, row.window, row.cutoff) for row in rows}
    )
    denominator = len(rows) or 1
    cutoff_denominator = cutoff_count or 1
    replacement_count, replacement_denominator = _replacement_statistics(rows)
    replacement_rate_denominator = replacement_denominator or 1
    return {
        "measured_snapshot_count": cutoff_count,
        "role_slot_count": len(rows),
        "role_availability_rate": len(available) / denominator,
        "unique_geometry_count": len(set(available)),
        "shared_structural_current_geometry_count": shared,
        "shared_structural_current_geometry_rate": shared / (pair_count or 1),
        "structural_current_divergence_count": divergence,
        "structural_current_divergence_rate": divergence / (pair_count or 1),
        "role_episode_count": len(episode_rows),
        "episode_lifetime_bars": {
            "min": min(lifetimes) if lifetimes else 0,
            "median": median(lifetimes) if lifetimes else 0,
            "p75": _percentile(lifetimes, 0.75),
            "p90": _percentile(lifetimes, 0.90),
            "p95": _percentile(lifetimes, 0.95),
            "max": max(lifetimes) if lifetimes else 0,
        },
        "replacement_count": replacement_count,
        "replacement_rate_per_100_cutoffs": (
            replacement_count / replacement_rate_denominator * 100
        ),
        "first_appearance_count": first_appearances,
        "first_appearance_rate_per_100_cutoffs": first_appearances
        / cutoff_denominator
        * 100,
        "reappearing_geometry_count": len(
            {episode.geometry_id for episode in reappearance_episodes}
        ),
        "reappearance_episode_count": len(reappearance_episodes),
        "one_bar_episode_count": sum(
            episode.lifetime_bars == 1 for episode in episode_rows
        ),
        "one_bar_episode_fraction": (
            sum(episode.lifetime_bars == 1 for episode in episode_rows)
            / (len(episode_rows) or 1)
        ),
        "identity_collision_count": measurement.identity_collision_count,
        "identity_content_mismatch_count": measurement.identity_content_mismatch_count,
        "source_gap_failure_count": measurement.source_gap_failure_count,
        "aggregation_failure_count": measurement.aggregation_failure_count,
    }


def build_report(measurement: Measurement) -> dict[str, object]:
    """Build the compact deterministic N1 report from measured observations."""

    asset_timeframes = tuple(
        (spec["asset"], timeframe)
        for spec in SOURCE_SPECS
        for timeframe in ("1h", "4h")
    )
    groups: dict[str, dict[str, object]] = {
        "global": _group_metrics(measurement),
        "asset_timeframe": {
            f"{asset}:{timeframe}": _group_metrics(
                measurement, asset=asset, timeframe=timeframe
            )
            for asset, timeframe in asset_timeframes
        },
        "timeframe": {
            timeframe: _group_metrics(measurement, timeframe=timeframe)
            for timeframe in ("1h", "4h")
        },
        "side_role": {
            f"{side}.{role}": _group_metrics(measurement, side=side, role=role)
            for side in SIDES
            for role in ROLES
        },
    }
    longest = sorted(
        (
            {
                "episode_id": episode.episode_id,
                "geometry_id": episode.geometry_id,
                "asset": episode.asset,
                "timeframe": episode.timeframe,
                "window": episode.window,
                "side": episode.side,
                "role": episode.role,
                "start_cutoff": episode.start_cutoff,
                "end_cutoff": episode.end_cutoff,
                "lifetime_bars": episode.lifetime_bars,
                "event": episode.event,
            }
            for episode in measurement.episodes
        ),
        key=lambda item: (-int(item["lifetime_bars"]), str(item["episode_id"])),
    )[:5]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "conclusion": "EXACT_IDENTITY_PERSISTENCE_SUPPORTED",
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "percentile_definition": PERCENTILE_DEFINITION,
        "measurement_contract": {
            "asset_count": 4,
            "timeframe_count": 2,
            "window_count": 16,
            "measured_snapshot_count": 4800,
            "role_slot_count": 19200,
            "core_history_bar_count": 300,
            "measurement_cutoffs_per_window": 300,
            "source_cutoff_range": "window positions 300..599 inclusive",
            "core_input_slice": "window[cutoff+1:cutoff+301] for measurement cutoff 0..299",
            "shared_pair_rates_denominator": "all structural/current side snapshot pairs",
            "replacement_rate_denominator": "consecutive role cutoffs per scope",
        },
        "inventory": {
            "measured_snapshot_count": measurement.snapshot_count,
            "role_slot_count": len(measurement.observations),
            "side_snapshot_pair_count": len(measurement.pair_observations),
            "unique_geometry_count": len(measurement.geometry_payloads),
            "episode_count": len(measurement.episodes),
        },
        "groups": groups,
        "longest_lived_examples": longest,
        "windows": measurement.windows,
        "source_metadata": measurement.source_metadata,
    }


def _protected_hashes() -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, (path, expected) in PROTECTED_HASHES.items():
        if not path.is_file():
            raise N1ContractError(f"missing protected file: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise N1ContractError(f"protected hash mismatch: {name}")
        observed[name] = digest
    return observed


def _authority_hashes() -> dict[str, dict[str, str]]:
    observed: dict[str, dict[str, str]] = {}
    for name, (path, expected) in N1_AUTHORITY_HASHES.items():
        if not path.is_file():
            raise N1ContractError(f"missing N1 authority file: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise N1ContractError(f"N1 authority hash mismatch: {name}")
        observed[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": digest,
        }
    return observed


def build_manifest(
    measurement: Measurement,
    report: dict[str, object],
    report_bytes: bytes,
    protected: dict[str, str],
    authority: dict[str, dict[str, str]],
) -> dict[str, object]:
    """Build the deterministic manifest, excluding only its own identity field."""

    body: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "design_scope": "N1 exact identity and observational persistence only",
        "n1_authority_hashes": authority,
        "production_protected_hashes": protected,
        "source_specs": [dict(spec) for spec in SOURCE_SPECS],
        "source_metadata": measurement.source_metadata,
        "algorithm_constants": {
            "pivot_window": 3,
            "history_capacity_bars": HISTORY_CAPACITY_BARS,
        },
        "four_hour_aggregation_contract": FOUR_HOUR_AGGREGATION_ID,
        "window_selection": {
            "window_length": WINDOW_LENGTH,
            "fractions": list(WINDOW_FRACTIONS),
            "rounding": "floor(fraction * (eligible_start_count - 1))",
            "labels": list(WINDOW_ROLES),
        },
        "windows": measurement.windows,
        "expected_inventory": {
            "window_count": 16,
            "snapshot_count": 4800,
            "role_slot_count": 19200,
        },
        "observed_inventory": {
            "window_count": len(measurement.windows),
            "snapshot_count": measurement.snapshot_count,
            "role_slot_count": len(measurement.observations),
            "unique_geometry_count": len(measurement.geometry_payloads),
            "episode_count": len(measurement.episodes),
        },
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report_byte_length": len(report_bytes),
        "report_schema_version": report["schema_version"],
    }
    return {**body, "manifest_id": _digest(body)}


def _pretty_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def run_n1(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run N1 once and atomically publish the compact report and manifest."""

    protected = _protected_hashes()
    authority = _authority_hashes()
    measurement = run_measurement()
    report = build_report(measurement)
    report_bytes = _pretty_json_bytes(report)
    manifest = build_manifest(measurement, report, report_bytes, protected, authority)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    report_path = target / "report.json"
    manifest_path = target / "manifest.json"
    report_path.write_bytes(report_bytes)
    manifest_path.write_bytes(_pretty_json_bytes(manifest))
    return report, manifest


def main() -> None:
    report, manifest = run_n1()
    print(
        json.dumps(
            {
                "conclusion": report["conclusion"],
                "manifest_id": manifest["manifest_id"],
                "window_count": len(report["windows"]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
