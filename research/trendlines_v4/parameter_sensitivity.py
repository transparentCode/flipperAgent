"""Bounded, outcome-blind H0 parameter-sensitivity measurement for V4."""

from __future__ import annotations

import hashlib
import json
import math
import resource
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Literal

from libs.models.trendlines_v4 import core
from libs.models.trendlines_v4.core import TrendlineGeometry, TrendlineSnapshot
from research.trendlines_v4 import (
    exact_geometry_identity_persistence as n1,
)

ROOT = Path(__file__).parents[2]
PRIMARY_ROOT = Path("/Users/kajukatli/projects/flipperAgent")
OUTPUT_DIR = ROOT / "artifacts/trendlines_v4/h0_parameter_sensitivity_v1"

PIVOT_WINDOWS = (2, 3, 5)
FIXED_BAR_POLICIES = (150, 300, 600)
DURATION_POLICIES_DAYS = (14, 28)
DEVELOPMENT_CUTOFFS_PER_STREAM = 600
HOLDOUT_CUTOFFS_PER_STREAM = 192
MAXIMUM_HISTORY_BARS = 672
PILOT_CUTOFFS_PER_STREAM = 8
PILOT_MAX_RSS_BYTES = 536_870_912
PILOT_MAX_MEDIAN_MULTIPLIER = 10.0
PILOT_MAX_MEDIAN_SECONDS = 0.100
PILOT_MAX_P90_SECONDS = 0.150
PILOT_MAX_CALL_SECONDS = 0.250
BASELINE_KEY = (3, "fixed_bars", 300)
PROFILE_HISTORY_POLICIES = (
    ("fixed_bars", 150),
    ("fixed_bars", 300),
    ("fixed_bars", 600),
    ("fixed_duration", 14),
    ("fixed_duration", 28),
)
ALLOWED_CONCLUSIONS = (
    "PARAMETER_SENSITIVITY_MEASURED",
    "PARAMETER_SENSITIVITY_MEASURED_WITH_PATHOLOGIES",
    "PARAMETER_SENSITIVITY_NUMERICAL_SEMANTICS_BLOCKED",
    "PARAMETER_SENSITIVITY_RESOURCE_BLOCKED",
    "BLOCKED_SOURCE_OR_CONTRACT",
)

H0_AUTHORITY_HASHES = {
    "handoff": (
        PRIMARY_ROOT
        / "plans/architect-to-coder-trendlines-v4-h0-parameter-sensitivity-v1.md",
        "45c86f1fa89f0498e7a0db8133c9c5a10f389d68e0ad1ea27e07ec9c43ca2981",
    ),
    "design": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-h0-parameter-sensitivity-design-v1.md",
        "0bfbceaeb012cd869aa1054a8366b08e533561abcd522f967ed70bbea405bc96",
    ),
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-h0-parameter-sensitivity-design-approval-v1.md",
        "e4844237d948a5e3b4d5ac3e31584ae38d7e92abe67376aba71e1775d8d8fa0d",
    ),
}
N1_AUTHORITY_HASHES = {
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n1-exact-identity-persistence-approval-v1.md",
        "fdf50eeaa9c49653ec2bde542417ae201bf08f3776c747b43c5116e376c4c5be",
    ),
}
N2_AUTHORITY_HASHES = {
    "approval": (
        PRIMARY_ROOT
        / "plans/orchestrator-decision-trendlines-v4-n2-current-relevance-metadata-approval-v1.md",
        "621af2c123c75f6e7c4721b53c77d869a21a5783bd3cae9624c0df6fd5b794cf",
    ),
}
PROTECTED_HASHES = {
    "core": (
        ROOT / "src/libs/models/trendlines_v4/core.py",
        "c92076e72891b222cf8359cba614c8ed969f04d1734a8985abdb0b68ffc9509f",
    ),
    "root_namespace": (
        ROOT / "src/libs/models/trendlines_v4/__init__.py",
        "66ccb45f10ab0c3b530f81919ad172fdde93b51cda04d935a6ce581641d0ac61",
    ),
    "decision_plugin": (
        ROOT / "src/libs/models/trendlines_v4/adapters/decision_plugin.py",
        "9d65b6f1cc0d00bbd60c9f40299f47701a161eadc2d5d0ae29b28747d415e523",
    ),
    "decision_composition": (
        ROOT / "src/apps/decision_app/composition.py",
        "41d9d9562e48c54042b46ce9880247b4ba23769ff80d708c2ee7c15c951ee763",
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
        ROOT
        / "artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/report.json",
        "30045237ff1bd763539addbf5645dadb862665512854731b1fdf3823c5499bd3",
    ),
    "manifest": (
        ROOT
        / "artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1/manifest.json",
        "9e270831b656e13b3df0e8c4cbb90e2ebeec4f24a9c5c56555c71b6d7506d464",
    ),
}
N2_LOCKS = {
    "implementation": (
        ROOT / "research/trendlines_v4/current_relevance_metadata.py",
        "937f27420bafb5e6b01abd9bbb815d496b2af42994e055d914a8dfe2964fa4fd",
    ),
    "tests": (
        ROOT / "tests/research/trendlines_v4/test_current_relevance_metadata.py",
        "65038d1377eaa1581e30f8d8e03d709e1d526feab8094825cdf2a5c93fa90bd5",
    ),
    "report": (
        ROOT / "artifacts/trendlines_v4/n2_current_relevance_metadata_v1/report.json",
        "97ca7bbd5d08004a41026ae45ae7d2437b7dba3dabdc30c70fa204c2a5636dc5",
    ),
    "manifest": (
        ROOT / "artifacts/trendlines_v4/n2_current_relevance_metadata_v1/manifest.json",
        "eb1dd91fd48b9af26fe42d8650acb2b7614ce17d3758adac7abe45c1ff2d4556",
    ),
}
SOURCE_SPECS = n1.SOURCE_SPECS

ROLE_KEYS = tuple((side, role) for side in n1.SIDES for role in n1.ROLES)
METADATA_FIELDS = (
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


class H0ContractError(ValueError):
    """Raised when a frozen H0 contract or source lock is violated."""


class H0ResourceBlocked(RuntimeError):
    """Raised when the mandatory H0 pilot rejects the resource envelope."""


@dataclass(frozen=True, slots=True)
class H0Profile:
    timeframe: Literal["1h", "4h"]
    pivot_window: int
    history_policy_kind: Literal["fixed_bars", "fixed_duration"]
    history_policy_value: int
    effective_history_bars: int
    effective_history_hours: int
    effective_history_days: float
    pivot_confirmation_delay_bars: int
    pivot_confirmation_delay_hours: int
    is_baseline: bool
    profile_id: str

    def as_payload(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "timeframe": self.timeframe,
            "pivot_window": self.pivot_window,
            "history_policy_kind": self.history_policy_kind,
            "history_policy_value": self.history_policy_value,
            "effective_history_bars": self.effective_history_bars,
            "effective_history_hours": self.effective_history_hours,
            "effective_history_days": self.effective_history_days,
            "pivot_confirmation_delay_bars": self.pivot_confirmation_delay_bars,
            "pivot_confirmation_delay_hours": self.pivot_confirmation_delay_hours,
            "is_baseline": self.is_baseline,
        }


@dataclass(frozen=True, slots=True)
class H0Cutoff:
    asset: str
    timeframe: Literal["1h", "4h"]
    window: str
    cutoff: int
    source_position: int
    market_as_of: str
    partition: Literal["development", "holdout"]

    def key(self) -> tuple[object, ...]:
        return (
            self.asset,
            self.timeframe,
            self.window,
            self.cutoff,
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "window": self.window,
            "cutoff": self.cutoff,
            "source_position": self.source_position,
            "market_as_of": self.market_as_of,
            "partition": self.partition,
        }


@dataclass(frozen=True, slots=True)
class H0Stream:
    asset: str
    timeframe: Literal["1h", "4h"]
    bars: tuple[n1.SourceBar, ...]
    development: tuple[H0Cutoff, ...]
    holdout: tuple[H0Cutoff, ...]


@dataclass(frozen=True, slots=True)
class H0LineFact:
    side: Literal["support", "resistance"]
    role: Literal["structural", "current_valid"]
    geometry_id: str
    start_anchor_at: str
    end_anchor_at: str
    start_anchor_price: float
    end_anchor_price: float
    projected_price: float
    projected_price_hex: str
    slope_per_bar: float
    projection_positive: bool
    absolute_close_distance_bps: float
    body_clearance_bps: float
    anchor_span_bars: int
    start_anchor_age_bars: int
    end_anchor_age_bars: int
    start_anchor_headroom_bars: int
    left_pivot_eligibility_margin_bars: int
    slope_bps_per_bar: float
    post_anchor_bar_count: int
    post_anchor_adverse_body_bar_count: int
    post_anchor_adverse_body_bar_rate: float
    bars_since_last_adverse_body_bar: int | None
    current_body_adverse_side: Literal["adverse", "respecting"]
    projection_non_positive: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "side": self.side,
            "role": self.role,
            "geometry_id": self.geometry_id,
            "start_anchor_at": self.start_anchor_at,
            "end_anchor_at": self.end_anchor_at,
            "start_anchor_price": self.start_anchor_price,
            "end_anchor_price": self.end_anchor_price,
            "projected_price": self.projected_price,
            "projected_price_hex": self.projected_price_hex,
            "slope_per_bar": self.slope_per_bar,
            "projection_positive": self.projection_positive,
            "absolute_close_distance_bps": self.absolute_close_distance_bps,
            "body_clearance_bps": self.body_clearance_bps,
            "anchor_span_bars": self.anchor_span_bars,
            "start_anchor_age_bars": self.start_anchor_age_bars,
            "end_anchor_age_bars": self.end_anchor_age_bars,
            "start_anchor_headroom_bars": self.start_anchor_headroom_bars,
            "left_pivot_eligibility_margin_bars": self.left_pivot_eligibility_margin_bars,
            "slope_bps_per_bar": self.slope_bps_per_bar,
            "post_anchor_bar_count": self.post_anchor_bar_count,
            "post_anchor_adverse_body_bar_count": self.post_anchor_adverse_body_bar_count,
            "post_anchor_adverse_body_bar_rate": self.post_anchor_adverse_body_bar_rate,
            "bars_since_last_adverse_body_bar": self.bars_since_last_adverse_body_bar,
            "current_body_adverse_side": self.current_body_adverse_side,
            "projection_non_positive": self.projection_non_positive,
        }


@dataclass(frozen=True, slots=True)
class H0Snapshot:
    cutoff: H0Cutoff
    lines: tuple[tuple[str, str, H0LineFact | None], ...]

    def line(self, side: str, role: str) -> H0LineFact | None:
        for line_side, line_role, fact in self.lines:
            if line_side == side and line_role == role:
                return fact
        raise H0ContractError("snapshot role inventory is incomplete")


@dataclass(frozen=True, slots=True)
class H0Observation:
    cutoff: H0Cutoff
    fact: H0LineFact


@dataclass(frozen=True, slots=True)
class H0NumericalDiagnostics:
    comparison_count: int = 0
    non_zero_float_delta_count: int = 0
    maximum_float_delta_abs: float = 0.0
    float_hex_mismatch_count: int = 0
    adverse_body_semantic_disagreement_count: int = 0
    projection_positive_disagreement_count: int = 0


@dataclass(slots=True)
class _NumericalAccumulator:
    first_by_key: dict[tuple[object, ...], tuple[float, str, str, bool]] = field(
        default_factory=dict
    )
    comparison_count: int = 0
    non_zero_float_delta_count: int = 0
    maximum_float_delta_abs: float = 0.0
    float_hex_mismatch_count: int = 0
    adverse_body_semantic_disagreement_count: int = 0
    projection_positive_disagreement_count: int = 0

    def observe(self, observation: H0Observation) -> None:
        fact = observation.fact
        key = (
            observation.cutoff.asset,
            observation.cutoff.timeframe,
            observation.cutoff.source_position,
            fact.side,
            fact.role,
            fact.geometry_id,
        )
        value = (
            fact.projected_price,
            fact.projected_price_hex,
            fact.current_body_adverse_side,
            fact.projection_positive,
        )
        previous = self.first_by_key.get(key)
        if previous is None:
            self.first_by_key[key] = value
            return
        self.comparison_count += 1
        delta = abs(value[0] - previous[0])
        self.maximum_float_delta_abs = max(self.maximum_float_delta_abs, delta)
        if delta != 0.0:
            self.non_zero_float_delta_count += 1
        if value[1] != previous[1]:
            self.float_hex_mismatch_count += 1
        if value[2] != previous[2]:
            self.adverse_body_semantic_disagreement_count += 1
        if value[3] != previous[3]:
            self.projection_positive_disagreement_count += 1

    def as_payload(self) -> dict[str, object]:
        return {
            "same_identity_comparison_count": self.comparison_count,
            "same_identity_projection_float_delta_non_zero_count": self.non_zero_float_delta_count,
            "same_identity_projection_float_delta_abs_max": self.maximum_float_delta_abs,
            "same_identity_projection_float_hex_mismatch_count": self.float_hex_mismatch_count,
            "same_identity_adverse_body_semantic_disagreement_count": self.adverse_body_semantic_disagreement_count,
            "same_identity_projection_positive_disagreement_count": self.projection_positive_disagreement_count,
        }


@dataclass(frozen=True, slots=True)
class H0ProfileRun:
    profile: H0Profile
    report: dict[str, object]
    baseline_comparison: dict[str, object]


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
            raise H0ContractError(f"missing locked file: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise H0ContractError(f"locked hash mismatch: {name}")
        observed[name] = digest
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


def _duration_bars(timeframe: Literal["1h", "4h"], days: int) -> int:
    bars_per_day = 24 if timeframe == "1h" else 6
    return days * bars_per_day


def _profile_id(payload: dict[str, object]) -> str:
    return _digest(payload)


def profiles_for_timeframe(
    timeframe: Literal["1h", "4h"],
) -> tuple[H0Profile, ...]:
    """Return the exact 15-profile deduplicated grid, baseline first."""

    bar_hours = 1 if timeframe == "1h" else 4
    candidates: dict[tuple[int, str, int], H0Profile] = {}
    for pivot_window in PIVOT_WINDOWS:
        for policy_kind, policy_value in PROFILE_HISTORY_POLICIES:
            effective = (
                policy_value
                if policy_kind == "fixed_bars"
                else _duration_bars(timeframe, policy_value)
            )
            key = (pivot_window, policy_kind, effective)
            payload = {
                "timeframe": timeframe,
                "pivot_window": pivot_window,
                "history_policy_kind": policy_kind,
                "history_policy_value": policy_value,
                "effective_history_bars": effective,
            }
            candidates[key] = H0Profile(
                timeframe=timeframe,
                pivot_window=pivot_window,
                history_policy_kind=policy_kind,
                history_policy_value=policy_value,
                effective_history_bars=effective,
                effective_history_hours=effective * bar_hours,
                effective_history_days=effective * bar_hours / 24,
                pivot_confirmation_delay_bars=pivot_window,
                pivot_confirmation_delay_hours=pivot_window * bar_hours,
                is_baseline=(pivot_window, policy_kind, effective) == BASELINE_KEY,
                profile_id=_profile_id(payload),
            )
    profiles = tuple(candidates.values())
    baseline = tuple(profile for profile in profiles if profile.is_baseline)
    non_baseline = tuple(profile for profile in profiles if not profile.is_baseline)
    if len(profiles) != 15 or len(baseline) != 1:
        raise H0ContractError("H0 profile grid is not the frozen 15-profile matrix")
    return baseline + non_baseline


def all_profiles() -> tuple[H0Profile, ...]:
    profiles = profiles_for_timeframe("1h") + profiles_for_timeframe("4h")
    if len(profiles) != 30:
        raise H0ContractError("H0 must contain 30 timeframe-specific profiles")
    return profiles


def _window_by_key(
    report_windows: Sequence[dict[str, object]],
    asset: str,
    timeframe: str,
    window: str,
) -> dict[str, object]:
    for item in report_windows:
        if (
            item["asset"] == asset
            and item["timeframe"] == timeframe
            and item["window"] == window
        ):
            return item
    raise H0ContractError("N1 window metadata is missing")


def _development_cutoffs(
    *,
    asset: str,
    timeframe: Literal["1h", "4h"],
    window: n1.SelectedWindow,
    series: Sequence[n1.SourceBar],
) -> tuple[H0Cutoff, ...]:
    result: list[H0Cutoff] = []
    for cutoff in range(n1.MEASUREMENT_BARS):
        source_position = window.start_position + cutoff + n1.MEASUREMENT_BARS
        if source_position + 1 < MAXIMUM_HISTORY_BARS:
            continue
        result.append(
            H0Cutoff(
                asset=asset,
                timeframe=timeframe,
                window=window.label,
                cutoff=cutoff,
                source_position=source_position,
                market_as_of=n1._timestamp(series[source_position].closed_at),
                partition="development",
            )
        )
    return tuple(result)


def _holdout_cutoffs(
    *,
    asset: str,
    timeframe: Literal["1h", "4h"],
    development: Sequence[H0Cutoff],
    series: Sequence[n1.SourceBar],
) -> tuple[H0Cutoff, ...]:
    if not development:
        raise H0ContractError("stream has no common development cutoffs")
    first_position = development[-1].source_position + 1
    last_position = first_position + HOLDOUT_CUTOFFS_PER_STREAM - 1
    if last_position >= len(series):
        raise H0ContractError("stream cannot provide the frozen 192-bar holdout")
    result = []
    for offset, source_position in enumerate(range(first_position, last_position + 1)):
        if source_position + 1 < MAXIMUM_HISTORY_BARS:
            raise H0ContractError("holdout cutoff lacks maximum history")
        result.append(
            H0Cutoff(
                asset=asset,
                timeframe=timeframe,
                window="holdout",
                cutoff=offset,
                source_position=source_position,
                market_as_of=n1._timestamp(series[source_position].closed_at),
                partition="holdout",
            )
        )
    return tuple(result)


def build_streams() -> tuple[H0Stream, ...]:
    """Read only the four locked local sources and freeze cutoff membership."""

    _verify_hashes(PROTECTED_HASHES)
    streams: list[H0Stream] = []
    for spec in SOURCE_SPECS:
        asset = str(spec["asset"])
        one_hour = n1.read_source(spec)
        four_hour = n1.derive_4h(one_hour)
        for timeframe, series in (("1h", one_hour), ("4h", four_hour)):
            development = tuple(
                cutoff
                for window in n1.select_windows(series)
                for cutoff in _development_cutoffs(
                    asset=asset,
                    timeframe=timeframe,
                    window=window,
                    series=series,
                )
            )
            holdout = _holdout_cutoffs(
                asset=asset,
                timeframe=timeframe,
                development=development,
                series=series,
            )
            streams.append(
                H0Stream(
                    asset=asset,
                    timeframe=timeframe,
                    bars=tuple(series),
                    development=development,
                    holdout=holdout,
                )
            )
    streams_tuple = tuple(streams)
    counts = {
        (
            stream.asset,
            stream.timeframe,
        ): len(stream.development)
        for stream in streams_tuple
    }
    if len(streams_tuple) != 8:
        raise H0ContractError("H0 must contain eight asset/timeframe streams")
    if sum(counts.values()) != 4638:
        raise H0ContractError("H0 common development corpus is not 4,638 cutoffs")
    if counts[("HYPEUSDT", "4h")] != 438:
        raise H0ContractError("HYPEUSDT 4h development membership is not 438")
    if any(count != 600 for key, count in counts.items() if key != ("HYPEUSDT", "4h")):
        raise H0ContractError("non-HYPE streams do not have 600 development cutoffs")
    if any(
        len(stream.holdout) != HOLDOUT_CUTOFFS_PER_STREAM for stream in streams_tuple
    ):
        raise H0ContractError("holdout membership is not exactly 192 per stream")
    return streams_tuple


def _membership_payload(
    streams: Sequence[H0Stream], partition: str
) -> list[dict[str, object]]:
    return [
        cutoff.as_payload()
        for stream in streams
        for cutoff in (
            stream.development if partition == "development" else stream.holdout
        )
    ]


def development_membership(streams: Sequence[H0Stream]) -> dict[str, object]:
    payload = _membership_payload(streams, "development")
    return {
        "cutoff_count": len(payload),
        "membership_hash": _digest(payload),
        "streams": [
            {
                "asset": stream.asset,
                "timeframe": stream.timeframe,
                "development_cutoff_count": len(stream.development),
                "first_source_position": stream.development[0].source_position,
                "last_source_position": stream.development[-1].source_position,
            }
            for stream in streams
        ],
    }


def holdout_membership(streams: Sequence[H0Stream]) -> dict[str, object]:
    payload = _membership_payload(streams, "holdout")
    return {
        "cutoff_count": len(payload),
        "membership_hash": _digest(payload),
        "results_published": False,
        "streams": [
            {
                "asset": stream.asset,
                "timeframe": stream.timeframe,
                "holdout_cutoff_count": len(stream.holdout),
                "first_source_position": stream.holdout[0].source_position,
                "last_source_position": stream.holdout[-1].source_position,
                "first_market_as_of": stream.holdout[0].market_as_of,
                "last_market_as_of": stream.holdout[-1].market_as_of,
            }
            for stream in streams
        ],
    }


def pilot_cutoffs(stream: H0Stream) -> tuple[H0Cutoff, ...]:
    if len(stream.development) < PILOT_CUTOFFS_PER_STREAM:
        raise H0ContractError("stream cannot provide eight pilot cutoffs")
    indexes = (0, 1, 2, 3, -4, -3, -2, -1)
    return tuple(stream.development[index] for index in indexes)


def _history_for_cutoff(
    stream: H0Stream,
    cutoff: H0Cutoff,
    effective_history_bars: int,
) -> tuple[n1.TrendlineBar, ...]:
    if cutoff.partition != "development":
        raise H0ContractError("H0 evaluator received an unopened holdout cutoff")
    if cutoff.timeframe != stream.timeframe or cutoff.asset != stream.asset:
        raise H0ContractError("cutoff does not belong to its source stream")
    if (
        effective_history_bars < 1
        or cutoff.source_position + 1 < effective_history_bars
    ):
        raise H0ContractError("effective history is unavailable at cutoff")
    source_slice = stream.bars[
        cutoff.source_position + 1 - effective_history_bars : cutoff.source_position + 1
    ]
    if len(source_slice) != effective_history_bars:
        raise H0ContractError("history slice has the wrong length")
    history = n1._core_bars(source_slice)
    if history[-1].closed_at != stream.bars[cutoff.source_position].closed_at:
        raise H0ContractError("history reads beyond the causal cutoff")
    return history


@contextmanager
def _patched_core(profile: H0Profile) -> Iterator[None]:
    original_pivot = core.PIVOT_WINDOW
    original_capacity = core.HISTORY_CAPACITY_BARS
    core.PIVOT_WINDOW = profile.pivot_window
    core.HISTORY_CAPACITY_BARS = profile.effective_history_bars
    try:
        yield
    finally:
        core.PIVOT_WINDOW = original_pivot
        core.HISTORY_CAPACITY_BARS = original_capacity
        if (core.PIVOT_WINDOW, core.HISTORY_CAPACITY_BARS) != (
            original_pivot,
            original_capacity,
        ):
            raise H0ContractError("production core globals were not restored")


def analyze_profile(
    profile: H0Profile,
    history: Sequence[n1.TrendlineBar],
) -> TrendlineSnapshot:
    """Analyze one profile serially and restore production globals in all paths."""

    with _patched_core(profile):
        snapshot = core.analyze_trendlines(history)
    if (core.PIVOT_WINDOW, core.HISTORY_CAPACITY_BARS) != (3, 300):
        raise H0ContractError("production core globals drifted after profile call")
    return snapshot


def _anchor_positions(
    line: TrendlineGeometry,
    history: Sequence[n1.TrendlineBar],
) -> tuple[int, int]:
    try:
        start = n1._anchor_position(history, line.start_anchor_at)
        end = n1._anchor_position(history, line.end_anchor_at)
    except ValueError as exc:
        raise H0ContractError("line anchor is not uniquely present") from exc
    if end <= start:
        raise H0ContractError("line anchor span is not positive")
    expected_slope = (line.end_anchor_price - line.start_anchor_price) / (end - start)
    if line.slope_per_bar != expected_slope:
        raise H0ContractError("line slope does not match its anchors")
    return start, end


def _adverse_indices(
    line: TrendlineGeometry,
    history: Sequence[n1.TrendlineBar],
    end_index: int,
) -> tuple[int, ...]:
    intercept = line.end_anchor_price - line.slope_per_bar * end_index
    adverse: list[int] = []
    for index in range(end_index + 1, len(history)):
        line_value = line.slope_per_bar * index + intercept
        body_top = max(history[index].open, history[index].close)
        body_bottom = min(history[index].open, history[index].close)
        if (line.side == "support" and body_bottom < line_value) or (
            line.side == "resistance" and body_top > line_value
        ):
            adverse.append(index)
    result = tuple(adverse)
    if len(result) != line.post_anchor_body_cross_count:
        raise H0ContractError("P0 adverse-body count parity failed")
    return result


def _line_fact(
    line: TrendlineGeometry,
    history: Sequence[n1.TrendlineBar],
    *,
    profile: H0Profile,
    cutoff: H0Cutoff,
    role: Literal["structural", "current_valid"],
) -> H0LineFact:
    if len(history) != profile.effective_history_bars:
        raise H0ContractError("profile history length differs from its contract")
    start_index, end_index = _anchor_positions(line, history)
    left_margin = start_index - profile.pivot_window
    if left_margin < 0:
        raise H0ContractError("pivot-relative eligibility margin is negative")
    adverse = _adverse_indices(line, history, end_index)
    if role == "current_valid" and adverse:
        raise H0ContractError("current-valid line has an adverse body bar")
    current = history[-1]
    close = current.close
    level = line.projected_price_at_market_as_of
    if close <= 0 or not math.isfinite(close) or not math.isfinite(level):
        raise H0ContractError("line or current close is not finite-positive")
    body_top = max(current.open, current.close)
    body_bottom = min(current.open, current.close)
    if line.side == "support":
        body_clearance = (body_bottom - level) / close * 10_000
        current_adverse = "adverse" if body_bottom < level else "respecting"
    else:
        body_clearance = (level - body_top) / close * 10_000
        current_adverse = "adverse" if body_top > level else "respecting"
    post_anchor_bars = len(history) - 1 - end_index
    if post_anchor_bars < 0:
        raise H0ContractError("anchor is after the history cutoff")
    values = (
        abs(close - level) / close * 10_000,
        body_clearance,
        line.slope_per_bar / close * 10_000,
        len(adverse) / post_anchor_bars if post_anchor_bars else 0.0,
    )
    if not all(math.isfinite(value) for value in values):
        raise H0ContractError("H0 line metadata is not finite")
    final_index = len(history) - 1
    return H0LineFact(
        side=line.side,
        role=role,
        geometry_id=n1.geometry_id(
            n1.identity_payload(
                line,
                history,
                asset=cutoff.asset,
                timeframe=cutoff.timeframe,
            )
        ),
        start_anchor_at=n1._timestamp(line.start_anchor_at),
        end_anchor_at=n1._timestamp(line.end_anchor_at),
        start_anchor_price=line.start_anchor_price,
        end_anchor_price=line.end_anchor_price,
        projected_price=level,
        projected_price_hex=level.hex(),
        slope_per_bar=line.slope_per_bar,
        projection_positive=line.projection_positive,
        absolute_close_distance_bps=values[0],
        body_clearance_bps=values[1],
        anchor_span_bars=end_index - start_index,
        start_anchor_age_bars=final_index - start_index,
        end_anchor_age_bars=final_index - end_index,
        start_anchor_headroom_bars=start_index,
        left_pivot_eligibility_margin_bars=left_margin,
        slope_bps_per_bar=values[2],
        post_anchor_bar_count=post_anchor_bars,
        post_anchor_adverse_body_bar_count=len(adverse),
        post_anchor_adverse_body_bar_rate=values[3],
        bars_since_last_adverse_body_bar=(
            None if not adverse else final_index - adverse[-1]
        ),
        current_body_adverse_side=current_adverse,
        projection_non_positive=not line.projection_positive,
    )


def snapshot_facts(
    snapshot: TrendlineSnapshot,
    history: Sequence[n1.TrendlineBar],
    *,
    profile: H0Profile,
    cutoff: H0Cutoff,
) -> H0Snapshot:
    lines: list[tuple[str, str, H0LineFact | None]] = []
    for side in n1.SIDES:
        side_snapshot = getattr(snapshot, side)
        for role in n1.ROLES:
            line = getattr(side_snapshot, role)
            lines.append(
                (
                    side,
                    role,
                    None
                    if line is None
                    else _line_fact(
                        line,
                        history,
                        profile=profile,
                        cutoff=cutoff,
                        role=role,
                    ),
                )
            )
    return H0Snapshot(cutoff, tuple(lines))


def _source_role_map(
    measurement: n1.Measurement,
) -> dict[tuple[object, ...], str | None]:
    return {
        (
            row.asset,
            row.timeframe,
            row.window,
            row.cutoff,
            row.side,
            row.role,
        ): row.geometry_id
        for row in measurement.observations
    }


def verify_baseline_parity(
    streams: Sequence[H0Stream],
    n1_measurement: n1.Measurement,
) -> dict[str, object]:
    """Compare patched (3,300) output with unpatched P0 on every H0 cutoff."""

    baseline = next(
        profile for profile in profiles_for_timeframe("1h") if profile.is_baseline
    )
    baseline_4h = next(
        profile for profile in profiles_for_timeframe("4h") if profile.is_baseline
    )
    role_map = _source_role_map(n1_measurement)
    snapshot_count = 0
    role_count = 0
    for stream in streams:
        profile = baseline if stream.timeframe == "1h" else baseline_4h
        for cutoff in stream.development:
            history = _history_for_cutoff(stream, cutoff, 300)
            reference = core.analyze_trendlines(history)
            candidate = analyze_profile(profile, history)
            if candidate != reference:
                raise H0ContractError("baseline patched snapshot differs from P0")
            snapshot_count += 1
            for side in n1.SIDES:
                side_snapshot = getattr(candidate, side)
                for role in n1.ROLES:
                    line = getattr(side_snapshot, role)
                    key = (
                        cutoff.asset,
                        cutoff.timeframe,
                        cutoff.window,
                        cutoff.cutoff,
                        side,
                        role,
                    )
                    expected = role_map.get(key)
                    actual = (
                        None
                        if line is None
                        else n1.geometry_id(
                            n1.identity_payload(
                                line,
                                history,
                                asset=cutoff.asset,
                                timeframe=cutoff.timeframe,
                            )
                        )
                    )
                    if expected != actual:
                        raise H0ContractError("baseline geometry ID differs from N1")
                    role_count += 1
    if snapshot_count != 4638:
        raise H0ContractError("baseline parity did not cover every H0 cutoff")
    return {
        "status": "passed",
        "development_cutoff_count": snapshot_count,
        "role_comparison_count": role_count,
        "exact_snapshot_match_count": snapshot_count,
        "exact_n1_role_id_match_count": role_count,
    }


def _fact_without_role(fact: H0LineFact) -> bytes:
    payload = fact.as_payload()
    payload.pop("role")
    return _canonical_bytes(payload)


def _register_unique(
    unique: dict[tuple[object, ...], H0Observation],
    observation: H0Observation,
) -> None:
    key = (
        observation.cutoff.asset,
        observation.cutoff.timeframe,
        observation.cutoff.window,
        observation.cutoff.cutoff,
        observation.fact.geometry_id,
    )
    prior = unique.get(key)
    if prior is not None and _fact_without_role(prior.fact) != _fact_without_role(
        observation.fact
    ):
        raise H0ContractError("duplicate structural/current metadata disagrees")
    unique[key] = observation


def _distribution(values: Sequence[float | int | None]) -> dict[str, object]:
    clean = [float(value) for value in values if value is not None]
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


def _fact_summary(rows: Sequence[H0Observation]) -> dict[str, object]:
    facts = [row.fact for row in rows]
    count = len(facts)
    adverse = sum(fact.current_body_adverse_side == "adverse" for fact in facts)
    non_positive = sum(fact.projection_non_positive for fact in facts)
    return {
        "observation_count": count,
        "unique_geometry_at_cutoff_count": len(
            {
                (
                    row.cutoff.asset,
                    row.cutoff.timeframe,
                    row.cutoff.window,
                    row.cutoff.cutoff,
                    row.fact.geometry_id,
                )
                for row in rows
            }
        ),
        "distributions": {
            field: _distribution([getattr(fact, field) for fact in facts])
            for field in METADATA_FIELDS
        },
        "current_body_adverse_side_counts": {
            "adverse": adverse,
            "respecting": count - adverse,
        },
        "current_body_adverse_side_rate": adverse / count if count else 0.0,
        "projection_non_positive_count": non_positive,
        "projection_non_positive_rate": non_positive / count if count else 0.0,
    }


def _rows_for(
    rows: Sequence[H0Observation],
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    side: str | None = None,
    role: str | None = None,
) -> tuple[H0Observation, ...]:
    return tuple(
        row
        for row in rows
        if (asset is None or row.cutoff.asset == asset)
        and (timeframe is None or row.cutoff.timeframe == timeframe)
        and (side is None or row.fact.side == side)
        and (role is None or row.fact.role == role)
    )


def _metadata_summaries(
    rows: Sequence[H0Observation],
    unique_rows: Sequence[H0Observation],
) -> dict[str, object]:
    role_groups: dict[str, object] = {
        "global": _fact_summary(rows),
        "asset_timeframe": {},
        "timeframe": {},
        "side_role": {},
    }
    for spec in SOURCE_SPECS:
        asset = str(spec["asset"])
        for timeframe in ("1h", "4h"):
            role_groups["asset_timeframe"][f"{asset}:{timeframe}"] = _fact_summary(
                _rows_for(rows, asset=asset, timeframe=timeframe)
            )
    for timeframe in ("1h", "4h"):
        role_groups["timeframe"][timeframe] = _fact_summary(
            _rows_for(rows, timeframe=timeframe)
        )
    for side in n1.SIDES:
        for role in n1.ROLES:
            role_groups["side_role"][f"{side}.{role}"] = _fact_summary(
                _rows_for(rows, side=side, role=role)
            )

    unique_groups: dict[str, object] = {
        "global": _fact_summary(unique_rows),
        "timeframe": {},
        "side": {},
    }
    for timeframe in ("1h", "4h"):
        unique_groups["timeframe"][timeframe] = _fact_summary(
            _rows_for(unique_rows, timeframe=timeframe)
        )
    for side in n1.SIDES:
        unique_groups["side"][side] = _fact_summary(_rows_for(unique_rows, side=side))
    return {
        "role_observations": role_groups,
        "unique_geometry_at_cutoff": unique_groups,
    }


def _run_records(
    ids: Sequence[str | None],
) -> tuple[list[dict[str, object]], int, int, int]:
    runs: list[dict[str, object]] = []
    seen: set[str] = set()
    active: str | None = None
    start = 0
    for index, geometry_id in enumerate((*ids, None)):
        if geometry_id == active:
            continue
        if active is not None:
            end = index - 1
            left = start == 0
            right = end == len(ids) - 1
            reappearance = active in seen
            runs.append(
                {
                    "geometry_id": active,
                    "observed_run_length_bars": end - start + 1,
                    "left_censored": left,
                    "right_censored": right,
                    "reappearance": reappearance,
                }
            )
            seen.add(active)
        if geometry_id is not None:
            active = geometry_id
            start = index
        else:
            active = None
    eligible = 0
    replacements = 0
    for previous, current in pairwise(ids):
        if previous is not None and current is not None:
            eligible += 1
            replacements += previous != current
    reappearances = sum(bool(run["reappearance"]) for run in runs)
    return runs, eligible, replacements, reappearances


def _stability_summary(
    sequences: dict[tuple[str, ...], list[str | None]],
) -> dict[str, object]:
    group_payload: list[dict[str, object]] = []
    all_runs: list[dict[str, object]] = []
    total_eligible = 0
    total_replacements = 0
    total_reappearances = 0
    for key in sorted(sequences):
        runs, eligible, replacements, reappearances = _run_records(sequences[key])
        all_runs.extend(runs)
        total_eligible += eligible
        total_replacements += replacements
        total_reappearances += reappearances
        group_payload.append(
            {
                "asset": key[0],
                "timeframe": key[1],
                "window": key[2],
                "side": key[3],
                "role": key[4],
                "development_cutoff_count": len(sequences[key]),
                **_summarize_runs(runs, eligible, replacements, reappearances),
            }
        )
    return {
        "aggregate": _summarize_runs(
            all_runs,
            total_eligible,
            total_replacements,
            total_reappearances,
        ),
        "groups": group_payload,
    }


def _summarize_runs(
    runs: Sequence[dict[str, object]],
    eligible: int,
    replacements: int,
    reappearances: int,
) -> dict[str, object]:
    lengths = [int(run["observed_run_length_bars"]) for run in runs]
    uncensored = [
        length
        for run, length in zip(runs, lengths)
        if not run["left_censored"] and not run["right_censored"]
    ]
    left = sum(bool(run["left_censored"]) for run in runs)
    right = sum(bool(run["right_censored"]) for run in runs)
    both = sum(bool(run["left_censored"] and run["right_censored"]) for run in runs)
    return {
        "observed_run_count": len(runs),
        "observed_run_length_bars": _distribution(lengths),
        "uncensored_run_length_bars": _distribution(uncensored),
        "left_censored_count": left,
        "right_censored_count": right,
        "both_censored_count": both,
        "left_censored_rate": left / len(runs) if runs else 0.0,
        "right_censored_rate": right / len(runs) if runs else 0.0,
        "both_censored_rate": both / len(runs) if runs else 0.0,
        "uncensored_one_bar_run_fraction": (
            sum(length == 1 for length in uncensored) / len(uncensored)
            if uncensored
            else 0.0
        ),
        "eligible_adjacent_transition_count": eligible,
        "replacement_count": replacements,
        "replacement_rate_per_100_eligible_transitions": (
            replacements / eligible * 100 if eligible else 0.0
        ),
        "reappearance_count": reappearances,
        "reappearance_rate": reappearances / len(runs) if runs else 0.0,
    }


def _compare_snapshots(
    actual: H0Snapshot,
    baseline: H0Snapshot,
) -> dict[str, object]:
    if actual.cutoff.key() != baseline.cutoff.key():
        raise H0ContractError("profile comparison cutoff keys differ")
    role_comparison: dict[str, dict[str, int]] = {}
    for side, role in ROLE_KEYS:
        current = actual.line(side, role)
        reference = baseline.line(side, role)
        key = f"{side}.{role}"
        role_comparison[key] = {
            "slot_count": 1,
            "both_available_count": int(current is not None and reference is not None),
            "exact_geometry_id_match_count": int(
                current is not None
                and reference is not None
                and current.geometry_id == reference.geometry_id
            ),
            "changed_geometry_count": int(
                current is not None
                and reference is not None
                and current.geometry_id != reference.geometry_id
            ),
            "presence_gained_count": int(current is not None and reference is None),
            "presence_lost_count": int(current is None and reference is not None),
        }
    side_sets: dict[str, dict[str, int]] = {}
    for side in n1.SIDES:
        current_set = {
            fact.geometry_id
            for role in n1.ROLES
            if (fact := actual.line(side, role)) is not None
        }
        reference_set = {
            fact.geometry_id
            for role in n1.ROLES
            if (fact := baseline.line(side, role)) is not None
        }
        side_sets[side] = {
            "exact_geometry_set_match_count": int(current_set == reference_set),
            "changed_geometry_set_count": int(current_set != reference_set),
        }
    return {"role": role_comparison, "side": side_sets}


def _merge_comparison(
    aggregate: dict[str, dict[str, int]],
    comparison: dict[str, object],
) -> None:
    for key, values in comparison["role"].items():
        destination = aggregate.setdefault(
            key,
            {
                "slot_count": 0,
                "both_available_count": 0,
                "exact_geometry_id_match_count": 0,
                "changed_geometry_count": 0,
                "presence_gained_count": 0,
                "presence_lost_count": 0,
            },
        )
        for item_name, value in values.items():
            destination[item_name] += value


def _finalize_comparison(
    role_counts: dict[str, dict[str, int]],
    side_counts: dict[str, dict[str, int]],
) -> dict[str, object]:
    result_role = {}
    for key, counts in sorted(role_counts.items()):
        slots = counts["slot_count"]
        result_role[key] = {
            **counts,
            "availability_rate": counts["both_available_count"] / slots
            if slots
            else 0.0,
            "exact_geometry_id_match_rate": counts["exact_geometry_id_match_count"]
            / counts["both_available_count"]
            if counts["both_available_count"]
            else 0.0,
            "changed_geometry_rate": counts["changed_geometry_count"]
            / counts["both_available_count"]
            if counts["both_available_count"]
            else 0.0,
        }
    result_side = {}
    for key, counts in sorted(side_counts.items()):
        result_side[key] = {
            **counts,
            "exact_geometry_set_match_rate": counts["exact_geometry_set_match_count"]
            / counts["comparison_count"]
            if counts["comparison_count"]
            else 0.0,
        }
    return {"role": result_role, "side": result_side}


def _run_profile(
    profile: H0Profile,
    streams: Sequence[H0Stream],
    baseline_snapshots: dict[tuple[object, ...], H0Snapshot],
    numerical: _NumericalAccumulator,
) -> tuple[H0ProfileRun, dict[tuple[object, ...], H0Snapshot], float, float, int]:
    rows: list[H0Observation] = []
    unique: dict[tuple[object, ...], H0Observation] = {}
    sequences: dict[tuple[str, ...], list[str | None]] = {}
    role_slots = {f"{side}.{role}": 0 for side, role in ROLE_KEYS}
    available = {f"{side}.{role}": 0 for side, role in ROLE_KEYS}
    role_comparison: dict[str, dict[str, int]] = {}
    side_comparison: dict[str, dict[str, int]] = {}
    snapshots: dict[tuple[object, ...], H0Snapshot] = {}
    call_count = 0
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    relevant_streams = tuple(
        stream for stream in streams if stream.timeframe == profile.timeframe
    )
    with _patched_core(profile):
        for stream in relevant_streams:
            for cutoff in stream.development:
                history = _history_for_cutoff(
                    stream,
                    cutoff,
                    profile.effective_history_bars,
                )
                snapshot = core.analyze_trendlines(history)
                call_count += 1
                facts = snapshot_facts(
                    snapshot,
                    history,
                    profile=profile,
                    cutoff=cutoff,
                )
                if profile.is_baseline:
                    snapshots[cutoff.key()] = facts
                else:
                    reference = baseline_snapshots.get(cutoff.key())
                    if reference is None:
                        raise H0ContractError("baseline snapshot is missing")
                    comparison = _compare_snapshots(facts, reference)
                    _merge_comparison(role_comparison, comparison)
                    for side, counts in comparison["side"].items():
                        destination = side_comparison.setdefault(
                            side,
                            {
                                "comparison_count": 0,
                                "exact_geometry_set_match_count": 0,
                                "changed_geometry_set_count": 0,
                            },
                        )
                        destination["comparison_count"] += 1
                        destination["exact_geometry_set_match_count"] += counts[
                            "exact_geometry_set_match_count"
                        ]
                        destination["changed_geometry_set_count"] += counts[
                            "changed_geometry_set_count"
                        ]
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
                    observation = H0Observation(cutoff, fact)
                    rows.append(observation)
                    _register_unique(unique, observation)
                    numerical.observe(observation)
    elapsed_wall = time.perf_counter() - wall_start
    elapsed_cpu = time.process_time() - cpu_start
    if call_count != sum(len(stream.development) for stream in relevant_streams):
        raise H0ContractError("profile call count does not match development corpus")
    if (core.PIVOT_WINDOW, core.HISTORY_CAPACITY_BARS) != (3, 300):
        raise H0ContractError("core globals drifted after profile matrix")
    availability = {}
    for key, slot_count in role_slots.items():
        availability[key] = {
            "slot_count": slot_count,
            "available_count": available[key],
            "availability_rate": available[key] / slot_count if slot_count else 0.0,
        }
    unique_rows = tuple(unique[key] for key in sorted(unique))
    profile_report = {
        "profile": profile.as_payload(),
        "evaluation_count": call_count,
        "availability": availability,
        "baseline_comparison": (
            {"not_applicable": True}
            if profile.is_baseline
            else _finalize_comparison(role_comparison, side_comparison)
        ),
        "metadata": _metadata_summaries(rows, unique_rows),
        "censor_aware_stability": _stability_summary(sequences),
    }
    return (
        H0ProfileRun(
            profile=profile,
            report=profile_report,
            baseline_comparison=profile_report["baseline_comparison"],
        ),
        snapshots,
        elapsed_wall,
        elapsed_cpu,
        call_count,
    )


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _pilot_record(
    profile: H0Profile,
    durations: Sequence[float],
    wall_seconds: float,
    cpu_seconds: float,
    peak_rss_bytes: int,
) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "timeframe": profile.timeframe,
        "pivot_window": profile.pivot_window,
        "effective_history_bars": profile.effective_history_bars,
        "call_count": len(durations),
        "wall_seconds": wall_seconds,
        "cpu_seconds": cpu_seconds,
        "median_core_call_seconds": median(durations),
        "p90_core_call_seconds": n1._percentile(durations, 0.90),
        "max_core_call_seconds": max(durations),
        "peak_process_rss_bytes": peak_rss_bytes,
        "failure_count": 0,
    }


def _enforce_pilot_resource_gates(
    records: list[dict[str, object]],
    evaluation_count: int,
) -> None:
    if evaluation_count != 960 or len(records) != 30:
        raise H0ResourceBlocked("pilot did not execute the exact 960-call matrix")
    baseline_medians: dict[str, float] = {}
    for record in records:
        if record["pivot_window"] == 3 and record["effective_history_bars"] == 300:
            baseline_medians[str(record["timeframe"])] = float(
                record["median_core_call_seconds"]
            )
    if set(baseline_medians) != {"1h", "4h"}:
        raise H0ResourceBlocked("pilot baseline records are incomplete")
    for record in records:
        if int(record["failure_count"]) != 0:
            raise H0ResourceBlocked("pilot contains an evaluation failure")
        if int(record["peak_process_rss_bytes"]) > PILOT_MAX_RSS_BYTES:
            raise H0ResourceBlocked("H0 pilot peak RSS exceeded 512 MiB")
        median_seconds = float(record["median_core_call_seconds"])
        p90_seconds = float(record["p90_core_call_seconds"])
        max_seconds = float(record["max_core_call_seconds"])
        if median_seconds > PILOT_MAX_MEDIAN_SECONDS:
            raise H0ResourceBlocked("H0 pilot median call time exceeded 100 ms")
        if p90_seconds > PILOT_MAX_P90_SECONDS:
            raise H0ResourceBlocked("H0 pilot p90 call time exceeded 150 ms")
        if max_seconds > PILOT_MAX_CALL_SECONDS:
            raise H0ResourceBlocked("H0 pilot maximum call time exceeded 250 ms")
        baseline_median = baseline_medians[str(record["timeframe"])]
        record["baseline_median_core_call_seconds"] = baseline_median
        record["median_call_time_ratio_to_baseline"] = (
            median_seconds / baseline_median if baseline_median else None
        )


def run_resource_pilot(
    streams: Sequence[H0Stream],
    profiles: Sequence[H0Profile],
) -> dict[str, object]:
    """Run the required 960-call serial pilot and enforce resource gates."""

    if (core.PIVOT_WINDOW, core.HISTORY_CAPACITY_BARS) != (3, 300):
        raise H0ResourceBlocked("production core globals are not at baseline")
    records: list[dict[str, object]] = []
    evaluation_count = 0
    for profile in profiles:
        durations: list[float] = []
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        relevant_streams = tuple(
            stream for stream in streams if stream.timeframe == profile.timeframe
        )
        with _patched_core(profile):
            for stream in relevant_streams:
                for cutoff in pilot_cutoffs(stream):
                    history = _history_for_cutoff(
                        stream,
                        cutoff,
                        profile.effective_history_bars,
                    )
                    call_start = time.perf_counter()
                    snapshot = core.analyze_trendlines(history)
                    durations.append(time.perf_counter() - call_start)
                    evaluation_count += 1
                    if not isinstance(snapshot, TrendlineSnapshot):
                        raise H0ResourceBlocked(
                            "core did not return a TrendlineSnapshot"
                        )
        record = _pilot_record(
            profile,
            durations,
            time.perf_counter() - wall_start,
            time.process_time() - cpu_start,
            _peak_rss_bytes(),
        )
        records.append(record)
    _enforce_pilot_resource_gates(records, evaluation_count)
    return {
        "status": "passed",
        "evaluation_count": evaluation_count,
        "cutoffs_per_stream": PILOT_CUTOFFS_PER_STREAM,
        "cutoff_membership": [
            cutoff.as_payload()
            for stream in streams
            for cutoff in pilot_cutoffs(stream)
        ],
        "records": records,
        "resource_semantics": {
            "wall_seconds": "perf_counter elapsed process wall time",
            "cpu_seconds": "process_time elapsed process CPU time",
            "peak_process_rss_bytes": "resource.getrusage ru_maxrss; bytes on macOS, KiB converted to bytes elsewhere",
            "execution": "one serial process with no concurrent profile calls",
            "baseline_relative_ratio": "descriptive only; not a stop gate",
            "absolute_pilot_limits": {
                "median_core_call_seconds": PILOT_MAX_MEDIAN_SECONDS,
                "p90_core_call_seconds": PILOT_MAX_P90_SECONDS,
                "max_core_call_seconds": PILOT_MAX_CALL_SECONDS,
                "peak_process_rss_bytes": PILOT_MAX_RSS_BYTES,
            },
        },
        "rss_limit_bytes": PILOT_MAX_RSS_BYTES,
        "median_call_time_multiplier_limit_descriptive": PILOT_MAX_MEDIAN_MULTIPLIER,
        "median_call_time_multiplier_limit_is_gate": False,
    }


def _profile_resource(
    profile: H0Profile,
    elapsed_wall: float,
    elapsed_cpu: float,
    call_count: int,
) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "timeframe": profile.timeframe,
        "call_count": call_count,
        "failure_count": 0,
        "wall_seconds": elapsed_wall,
        "cpu_seconds": elapsed_cpu,
    }


def _enforce_full_matrix_resource_gates(
    matrix_resources: dict[str, object],
    expected_calls: int,
) -> None:
    if matrix_resources.get("evaluation_count") != expected_calls:
        raise H0ResourceBlocked("full matrix call count is not exact")
    if int(matrix_resources["peak_process_rss_bytes"]) > PILOT_MAX_RSS_BYTES:
        raise H0ResourceBlocked("full matrix peak RSS exceeded 512 MiB")
    profile_resources = matrix_resources.get("profile_resources")
    if not isinstance(profile_resources, list) or len(profile_resources) != 30:
        raise H0ResourceBlocked("full matrix profile resource inventory is incomplete")
    for resource_record in profile_resources:
        if int(resource_record["failure_count"]) != 0:
            raise H0ResourceBlocked("full matrix contains an evaluation failure")


def _run_full_matrix(
    streams: Sequence[H0Stream],
    profiles: Sequence[H0Profile],
    numerical: _NumericalAccumulator,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    baseline_snapshots: dict[tuple[object, ...], H0Snapshot] = {}
    profile_reports: list[dict[str, object]] = []
    resources: list[dict[str, object]] = []
    matrix_wall_start = time.perf_counter()
    matrix_cpu_start = time.process_time()
    total_calls = 0
    for profile in profiles:
        result, snapshots, elapsed_wall, elapsed_cpu, call_count = _run_profile(
            profile,
            streams,
            baseline_snapshots,
            numerical,
        )
        if profile.is_baseline:
            baseline_snapshots.update(snapshots)
        profile_reports.append(result.report)
        resources.append(
            _profile_resource(profile, elapsed_wall, elapsed_cpu, call_count)
        )
        total_calls += call_count
    expected_calls = sum(len(stream.development) for stream in streams) * 15
    matrix_resources = {
        "evaluation_count": total_calls,
        "wall_seconds": time.perf_counter() - matrix_wall_start,
        "cpu_seconds": time.process_time() - matrix_cpu_start,
        "peak_process_rss_bytes": _peak_rss_bytes(),
        "profile_resources": resources,
    }
    _enforce_full_matrix_resource_gates(matrix_resources, expected_calls)
    return profile_reports, resources, matrix_resources


def _load_locked_json(path: Path, name: str) -> tuple[dict[str, object], bytes]:
    if not path.is_file():
        raise H0ContractError(f"missing locked JSON artifact: {name}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise H0ContractError(f"locked artifact is not JSON: {name}") from exc
    if not isinstance(value, dict):
        raise H0ContractError(f"locked artifact is not an object: {name}")
    if _pretty_bytes(value) != raw:
        raise H0ContractError(f"locked artifact is not canonical JSON: {name}")
    return value, raw


def _validate_locked_artifact(
    *,
    name: str,
    path: Path,
    expected_report_inventory: dict[str, object],
) -> dict[str, object]:
    report, report_bytes = _load_locked_json(path / "report.json", f"{name}.report")
    manifest, manifest_bytes = _load_locked_json(
        path / "manifest.json", f"{name}.manifest"
    )
    if report.get("inventory") != expected_report_inventory:
        raise H0ContractError(f"{name} inventory differs from its locked contract")
    if manifest.get("report_sha256") != hashlib.sha256(report_bytes).hexdigest():
        raise H0ContractError(f"{name} report hash is inconsistent")
    if manifest.get("report_byte_length") != len(report_bytes):
        raise H0ContractError(f"{name} report byte length is inconsistent")
    body = dict(manifest)
    manifest_id = body.pop("manifest_id", None)
    if not isinstance(manifest_id, str) or manifest_id != _digest(body):
        raise H0ContractError(f"{name} manifest identity is inconsistent")
    return {
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report_byte_length": len(report_bytes),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "manifest_byte_length": len(manifest_bytes),
        "manifest_id": manifest_id,
        "inventory": expected_report_inventory,
    }


def verify_prior_artifacts() -> dict[str, object]:
    """Authenticate every prior authority and artifact before H0 evaluation."""

    h0_authority = _authority_view(H0_AUTHORITY_HASHES)
    n1_authority = _authority_view(N1_AUTHORITY_HASHES)
    n2_authority = _authority_view(N2_AUTHORITY_HASHES)
    production_hashes = _verify_hashes(PROTECTED_HASHES)
    n1_locks = _verify_hashes(N1_LOCKS)
    n2_locks = _verify_hashes(N2_LOCKS)
    n1_artifact = _validate_locked_artifact(
        name="N1",
        path=ROOT / "artifacts/trendlines_v4/n1_exact_geometry_identity_persistence_v1",
        expected_report_inventory={
            "episode_count": 2363,
            "measured_snapshot_count": 4800,
            "role_slot_count": 19200,
            "side_snapshot_pair_count": 9600,
            "unique_geometry_count": 1159,
        },
    )
    n2_artifact = _validate_locked_artifact(
        name="N2",
        path=ROOT / "artifacts/trendlines_v4/n2_current_relevance_metadata_v1",
        expected_report_inventory={
            "measured_snapshot_count": 4800,
            "n1_episode_count": 2363,
            "n1_unique_geometry_count": 1159,
            "non_null_role_observation_count": 19091,
            "role_slot_count": 19200,
            "side_snapshot_pair_count": 9600,
            "unique_geometry_at_cutoff_count": 13096,
            "window_count": 16,
        },
    )
    return {
        "h0_authority_hashes": h0_authority,
        "n1_authority_hashes": n1_authority,
        "n2_authority_hashes": n2_authority,
        "production_protected_hashes": production_hashes,
        "n1_locks": n1_locks,
        "n2_locks": n2_locks,
        "n1_artifact": n1_artifact,
        "n2_artifact": n2_artifact,
    }


def _candidate_grid_payload(profiles: Sequence[H0Profile]) -> dict[str, object]:
    by_timeframe = {
        timeframe: [
            profile.as_payload()
            for profile in profiles
            if profile.timeframe == timeframe
        ]
        for timeframe in ("1h", "4h")
    }
    return {
        "pivot_windows": list(PIVOT_WINDOWS),
        "fixed_bar_policies": list(FIXED_BAR_POLICIES),
        "fixed_duration_days": list(DURATION_POLICIES_DAYS),
        "deduplicated_profile_count_per_timeframe": 15,
        "profile_count": len(profiles),
        "profiles_by_timeframe": by_timeframe,
        "duration_conversion": {
            "1h": {
                str(days): _duration_bars("1h", days) for days in DURATION_POLICIES_DAYS
            },
            "4h": {
                str(days): _duration_bars("4h", days) for days in DURATION_POLICIES_DAYS
            },
        },
    }


def _first_resource_view(matrix_resources: dict[str, object]) -> dict[str, object]:
    """Return the first run's measured resources without rerun-dependent fields."""

    profile_resources = matrix_resources.get("profile_resources")
    if not isinstance(profile_resources, list):
        raise H0ContractError("full matrix profile resource evidence is missing")
    return {
        "evaluation_count": matrix_resources["evaluation_count"],
        "wall_seconds": matrix_resources["wall_seconds"],
        "cpu_seconds": matrix_resources["cpu_seconds"],
        "peak_process_rss_bytes": matrix_resources["peak_process_rss_bytes"],
        "profile_resources": profile_resources,
        "reported_run": "first_complete_matrix_run",
    }


def _profile_reports_with_resources(
    profile_reports: Sequence[dict[str, object]],
    matrix_resources: dict[str, object],
) -> list[dict[str, object]]:
    resources = matrix_resources.get("profile_resources")
    if not isinstance(resources, list):
        raise H0ContractError("profile resource inventory is missing")
    resource_by_id = {
        str(item["profile_id"]): item
        for item in resources
        if isinstance(item, dict) and "profile_id" in item
    }
    result: list[dict[str, object]] = []
    for profile_report in profile_reports:
        profile = profile_report.get("profile")
        if not isinstance(profile, dict):
            raise H0ContractError("profile report has no profile payload")
        profile_id = str(profile["profile_id"])
        resource = resource_by_id.get(profile_id)
        if resource is None:
            raise H0ContractError("profile resource evidence is incomplete")
        result.append({**profile_report, "resource": resource})
    return result


def build_report(
    *,
    prior: dict[str, object],
    streams: Sequence[H0Stream],
    profiles: Sequence[H0Profile],
    baseline_parity: dict[str, object],
    pilot: dict[str, object],
    profile_reports: Sequence[dict[str, object]],
    matrix_resources: dict[str, object],
    numerical: _NumericalAccumulator,
    rerun_evidence: dict[str, object],
) -> dict[str, object]:
    """Build the deterministic H0 report from one semantically complete run."""

    diagnostics = numerical.as_payload()
    semantic_disagreements = int(
        diagnostics["same_identity_adverse_body_semantic_disagreement_count"]
    ) + int(diagnostics["same_identity_projection_positive_disagreement_count"])
    non_positive_count = sum(
        int(
            report["metadata"]["role_observations"]["global"][
                "projection_non_positive_count"
            ]
        )
        for report in profile_reports
    )
    conclusion = (
        "PARAMETER_SENSITIVITY_NUMERICAL_SEMANTICS_BLOCKED"
        if semantic_disagreements
        else (
            "PARAMETER_SENSITIVITY_MEASURED_WITH_PATHOLOGIES"
            if non_positive_count
            else "PARAMETER_SENSITIVITY_MEASURED"
        )
    )
    return {
        "schema_version": "trendlines_v4_h0_parameter_sensitivity_report_v1",
        "conclusion": conclusion,
        "candidate_grid": _candidate_grid_payload(profiles),
        "common_development": development_membership(streams),
        "baseline_parity": baseline_parity,
        "resource_pilot": pilot,
        "full_matrix": {
            **_first_resource_view(matrix_resources),
            "profile_count": len(profile_reports),
            "profile_reports": _profile_reports_with_resources(
                profile_reports, matrix_resources
            ),
        },
        "numerical_origin_diagnostics": {
            **diagnostics,
            "semantic_disagreement_count": semantic_disagreements,
        },
        "holdout": holdout_membership(streams),
        "prior_artifact_evidence": prior,
        "deterministic_rerun": rerun_evidence,
        "measurement_interpretation": {
            "selection": "Every fixed profile is measured on the same common development cutoffs.",
            "stability": "Runs are observed contiguous segments with left/right censoring; they are not asserted true lifetimes.",
            "boundary_pressure": "Left-pivot eligibility is measured relative to the profile pivot window.",
            "adverse_body": "Post-anchor adverse-body bars are descriptive side-aware facts, not independent events.",
            "structural_history": "Structural adverse-body history is retained descriptively and is not an objective.",
            "holdout": "Later H1 cutoff membership is frozen as metadata only and has no published evaluation results.",
            "weighting": "Sequential observations are reported descriptively and are not treated as independent samples.",
        },
        "allowed_conclusions": list(ALLOWED_CONCLUSIONS),
    }


def build_manifest(
    *,
    prior: dict[str, object],
    streams: Sequence[H0Stream],
    profiles: Sequence[H0Profile],
    report: dict[str, object],
    report_bytes: bytes,
    pilot: dict[str, object],
    matrix_resources: dict[str, object],
    rerun_evidence: dict[str, object],
) -> dict[str, object]:
    """Build deterministic H0 provenance, excluding only its own identity."""

    body: dict[str, object] = {
        "schema_version": "trendlines_v4_h0_parameter_sensitivity_manifest_v1",
        "report_schema_version": report["schema_version"],
        "design_scope": "H0 parameter sensitivity measurement only; no downstream parameter choice",
        "h0_authority_hashes": prior["h0_authority_hashes"],
        "n1_authority_hashes": prior["n1_authority_hashes"],
        "n2_authority_hashes": prior["n2_authority_hashes"],
        "n1_locks": prior["n1_locks"],
        "n2_locks": prior["n2_locks"],
        "n1_artifact": prior["n1_artifact"],
        "n2_artifact": prior["n2_artifact"],
        "production_protected_hashes": prior["production_protected_hashes"],
        "source_specs": [dict(spec) for spec in SOURCE_SPECS],
        "candidate_grid": _candidate_grid_payload(profiles),
        "duration_conversion": {
            "1h_bars_per_day": 24,
            "4h_bars_per_day": 6,
            "14_days": {"1h": 336, "4h": 84},
            "28_days": {"1h": 672, "4h": 168},
        },
        "common_development": development_membership(streams),
        "unopened_h1_holdout": holdout_membership(streams),
        "pilot_cutoff_membership": pilot["cutoff_membership"],
        "resource_measurement": {
            "pilot": {
                "rss_limit_bytes": pilot["rss_limit_bytes"],
                "median_call_time_multiplier_limit_descriptive": pilot[
                    "median_call_time_multiplier_limit_descriptive"
                ],
                "median_call_time_multiplier_limit_is_gate": pilot[
                    "median_call_time_multiplier_limit_is_gate"
                ],
                "evaluation_count": pilot["evaluation_count"],
                "semantics": pilot["resource_semantics"],
            },
            "full_matrix": _first_resource_view(matrix_resources),
        },
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "report_byte_length": len(report_bytes),
        "allowed_conclusions": list(ALLOWED_CONCLUSIONS),
        "deterministic_rerun": rerun_evidence,
    }
    return {**body, "manifest_id": _digest(body)}


def _assert_matrix_rerun_equal(
    first_reports: Sequence[dict[str, object]],
    second_reports: Sequence[dict[str, object]],
    first_numerical: _NumericalAccumulator,
    second_numerical: _NumericalAccumulator,
) -> None:
    if list(first_reports) != list(second_reports):
        raise H0ContractError("H0 full matrix profile reports differ on rerun")
    if first_numerical.as_payload() != second_numerical.as_payload():
        raise H0ContractError("H0 numerical diagnostics differ on rerun")


def run_h0(
    output_dir: str | Path = OUTPUT_DIR,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run H0 with the mandatory pilot and two complete deterministic matrices."""

    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise H0ContractError("H0 output directory is not absent/empty")
    prior = verify_prior_artifacts()
    streams = build_streams()
    profiles = all_profiles()
    n1_measurement = n1.run_measurement()
    if n1_measurement.snapshot_count != 4800:
        raise H0ContractError("N1 source measurement snapshot count changed")
    baseline_parity = verify_baseline_parity(streams, n1_measurement)
    pilot = run_resource_pilot(streams, profiles)
    if pilot.get("status") != "passed":
        raise H0ResourceBlocked("H0 resource pilot did not pass")

    first_numerical = _NumericalAccumulator()
    first_reports, _, first_matrix_resources = _run_full_matrix(
        streams, profiles, first_numerical
    )
    second_numerical = _NumericalAccumulator()
    second_reports, _, second_matrix_resources = _run_full_matrix(
        streams, profiles, second_numerical
    )
    _assert_matrix_rerun_equal(
        first_reports,
        second_reports,
        first_numerical,
        second_numerical,
    )
    if first_matrix_resources["evaluation_count"] != 69_570:
        raise H0ContractError("H0 full matrix did not execute 69,570 calls")
    if second_matrix_resources["evaluation_count"] != 69_570:
        raise H0ContractError("H0 rerun did not execute 69,570 calls")
    rerun_evidence = {
        "run_count": 2,
        "profile_report_values_equal": True,
        "numerical_diagnostics_equal": True,
        "full_matrix_evaluation_count_each": 69_570,
        "resource_gate_checked_on_both_runs": True,
        "reported_resource_run": "first_complete_matrix_run",
    }
    report = build_report(
        prior=prior,
        streams=streams,
        profiles=profiles,
        baseline_parity=baseline_parity,
        pilot=pilot,
        profile_reports=first_reports,
        matrix_resources=first_matrix_resources,
        numerical=first_numerical,
        rerun_evidence=rerun_evidence,
    )
    second_report = build_report(
        prior=prior,
        streams=streams,
        profiles=profiles,
        baseline_parity=baseline_parity,
        pilot=pilot,
        profile_reports=second_reports,
        matrix_resources=first_matrix_resources,
        numerical=second_numerical,
        rerun_evidence=rerun_evidence,
    )
    report_bytes = _pretty_bytes(report)
    if report_bytes != _pretty_bytes(second_report):
        raise H0ContractError("H0 report bytes differ after deterministic rerun")
    manifest = build_manifest(
        prior=prior,
        streams=streams,
        profiles=profiles,
        report=report,
        report_bytes=report_bytes,
        pilot=pilot,
        matrix_resources=first_matrix_resources,
        rerun_evidence=rerun_evidence,
    )
    second_manifest = build_manifest(
        prior=prior,
        streams=streams,
        profiles=profiles,
        report=second_report,
        report_bytes=report_bytes,
        pilot=pilot,
        matrix_resources=first_matrix_resources,
        rerun_evidence=rerun_evidence,
    )
    manifest_bytes = _pretty_bytes(manifest)
    if manifest_bytes != _pretty_bytes(second_manifest):
        raise H0ContractError("H0 manifest bytes differ after deterministic rerun")
    target.mkdir(parents=True, exist_ok=True)
    allowed = {"report.json", "manifest.json"}
    unexpected = {path.name for path in target.iterdir()} - allowed
    if unexpected:
        raise H0ContractError(f"unexpected H0 artifact members: {sorted(unexpected)}")
    report_path = target / "report.json"
    manifest_path = target / "manifest.json"
    report_path.write_bytes(report_bytes)
    manifest_path.write_bytes(manifest_bytes)
    _verify_hashes(PROTECTED_HASHES)
    if (core.PIVOT_WINDOW, core.HISTORY_CAPACITY_BARS) != (3, 300):
        raise H0ContractError("core globals are not at their production defaults")
    return report, manifest


def main() -> None:
    report, manifest = run_h0()
    print(
        json.dumps(
            {
                "conclusion": report["conclusion"],
                "manifest_id": manifest["manifest_id"],
                "profile_count": report["candidate_grid"]["profile_count"],
                "development_cutoff_count": report["common_development"][
                    "cutoff_count"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
