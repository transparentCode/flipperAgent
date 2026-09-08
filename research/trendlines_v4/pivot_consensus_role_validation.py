"""F1C role persistence, native-4h provenance, and clutter evidence.

This module is research-only.  It reuses the authenticated F1A candidate tape
and F1B selectors, freezes one native Binance 4h source bundle, then performs
bounded rolling measurements over the frozen 1h and 4h streams.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import html
import inspect
import json
import math
import os
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

import pandas as pd

from libs.market_data import BINANCE_KLINE_PAGE_LIMIT, BinanceNativeAdapter
from libs.models.trendlines_v4.core_v2 import analyze_trendlines_v2
from libs.models.trendlines_v4.engine.types import Side, TrendlineBar
from research.trendlines_v4 import pivot_consensus_candidate_tape as f1a
from research.trendlines_v4 import pivot_consensus_selector_challenge as f1b

ROOT = Path(__file__).parents[2]
PRIMARY_ROOT = Path("/Users/kajukatli/projects/flipperAgent")
SCHEMA_VERSION = "trendlines_v4_f1c_role_validation_v1"
NATIVE_4H_SCHEMA_VERSION = "trendlines_v4_f1c_native_4h_manifest_v1"
ARTIFACT_DIR = ROOT / "artifacts/trendlines_v4/f1c_pivot_consensus_role_validation_v1"
NATIVE_4H_TERMINAL = datetime(2026, 3, 1, 0, 59, 59, 999000, tzinfo=UTC)
NATIVE_4H_LENGTH = 491
ROLLING_CUTOFF_COUNT = 192
HISTORY_LENGTH = 300
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT")
SIDES: tuple[Side, ...] = ("support", "resistance")
PIVOT_ROLES = ("structural", "local")
V4_ROLES = ("structural", "current_valid", "secondary")
NATIVE_FREEZE_NAMES = (
    "native_4h_manifest.json",
    *(f"native_4h_{asset}.csv" for asset in ASSETS),
)
ANALYTICAL_NAMES = (
    "report.json",
    "combined_cases.json",
    "combined_review.html",
    "manifest.json",
)

F1C_HANDOFF = (
    PRIMARY_ROOT
    / "plans/architect-to-coder-trendlines-v4-f1c-role-persistence-native4h-clutter-v1.md",
    "d12cdcec2f2c4d279bed401222daa490f57fce61a1f5953b485071a0a54a13c5",
)
F1C_DESIGN = (
    PRIMARY_ROOT
    / "plans/orchestrator-decision-trendlines-v4-f1c-role-persistence-native4h-clutter-design-v1.md",
    "71719251358221aa0bbc6eaced6f1f704f386513f873ffa988b08d6b8d98138f",
)
F1A_APPROVAL = (
    PRIMARY_ROOT
    / "plans/orchestrator-decision-trendlines-v4-f1a-pivot-consensus-approval-v1.md",
    "80cfa9e76a62e4e2caf7e9633d705f815dc497015cf51e7cf497928fbfbe16ad",
)
F1B_RATINGS = (
    PRIMARY_ROOT / "plans/orchestrator-decision-trendlines-v4-f1b-blind-ratings-v1.md",
    "501cc249f5bb885048a7c8a79f98eff76c80f13bee584269fd2e6f8eb5daabea",
)
F1B_UNBLINDED = (
    PRIMARY_ROOT
    / "plans/orchestrator-decision-trendlines-v4-f1b-unblinded-decision-v1.md",
    "0b1aaf3ad9597cca3fc73d9477742e4593af988e19f235b3953adc4e7d606427",
)
F1B_SOURCE = (
    ROOT / "research/trendlines_v4/pivot_consensus_selector_challenge.py",
    "3a4efdfea86818e681b99d03f029c5e1219275e5ed0120a743ce1762ed426a47",
)
F1B_TEST = (
    ROOT / "tests/research/trendlines_v4/test_pivot_consensus_selector_challenge.py",
    "7b189056b0469f5cc1c27e5bdb4a1cad8fd53aa3827bf13fbc4fd5ee165833e8",
)
F1B_PUBLIC_LOCKS = {
    "holdout_manifest": (
        ROOT
        / "artifacts/trendlines_v4/f1b_pivot_consensus_selector_challenge_v1/holdout_manifest.json",
        "0a77ac09b9da8a72c937471539c100ae9047e6e54a467c145abd594b014ae401",
    ),
    "blind_cases": (
        ROOT
        / "artifacts/trendlines_v4/f1b_pivot_consensus_selector_challenge_v1/blind_cases.json",
        "bed744ab3a46900b50cd1d5cebad6436e00c2edd68740273b26a0c1596913e97",
    ),
    "mapping_commitment": (
        ROOT
        / "artifacts/trendlines_v4/f1b_pivot_consensus_selector_challenge_v1/mapping_commitment.json",
        "c945d7784ebb8b7b8f2ac84d727f7c1880462b2359d02fdbe4cc98ceb2079361",
    ),
    "blind_review": (
        ROOT
        / "artifacts/trendlines_v4/f1b_pivot_consensus_selector_challenge_v1/blind_review.html",
        "e3bc3625e35fa2b7cd9f8bf8537c7f9aff350ea330b432371e5671ab3bd5ef39",
    ),
}


class Native4HBlocked(RuntimeError):
    """The single native-4h acquisition cannot be authenticated safely."""


@dataclass(frozen=True, slots=True)
class FrozenStream:
    asset: str
    timeframe: str
    bars: tuple[TrendlineBar, ...]
    source_path: str
    source_sha256: str
    source_row_count: int
    source_kind: str

    @property
    def terminal(self) -> datetime:
        return self.bars[-1].closed_at

    def as_payload(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_row_count": self.source_row_count,
            "retained_row_count": len(self.bars),
            "terminal_close": _timestamp(self.terminal),
            "source_kind": self.source_kind,
        }


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


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _finite(value: object, name: str) -> float:
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


def authenticate_frozen_inputs() -> dict[str, str]:
    """Authenticate F1C, F1A, F1B, and the frozen 1h authority chain."""

    observed = {
        "f1c_handoff": _verify_lock("F1C handoff", F1C_HANDOFF),
        "f1c_design": _verify_lock("F1C design", F1C_DESIGN),
        "f1a_approval": _verify_lock("F1A approval", F1A_APPROVAL),
        "f1b_ratings": _verify_lock("F1B ratings", F1B_RATINGS),
        "f1b_unblinded": _verify_lock("F1B unblinded decision", F1B_UNBLINDED),
        "f1b_source": _verify_lock("F1B source", F1B_SOURCE),
        "f1b_test": _verify_lock("F1B test", F1B_TEST),
    }
    for name, lock in F1B_PUBLIC_LOCKS.items():
        observed[f"f1b_{name}"] = _verify_lock(f"F1B {name}", lock)
    f1b.validate_artifact_bundle(
        ROOT / "artifacts/trendlines_v4/f1b_pivot_consensus_selector_challenge_v1"
    )
    observed.update(
        {
            f"f1a_chain_{name}": value
            for name, value in f1b.verify_frozen_inputs().items()
        }
    )
    return observed


def _validate_bars(
    bars: Sequence[TrendlineBar], *, name: str, spacing: timedelta | None = None
) -> tuple[TrendlineBar, ...]:
    result = tuple(bars)
    if not result:
        raise ValueError(f"{name} has no bars")
    previous: datetime | None = None
    for bar in result:
        if not isinstance(bar, TrendlineBar):
            raise TypeError(f"{name} contains a non-TrendlineBar")
        if previous is not None:
            delta = bar.closed_at - previous
            if delta <= timedelta(0):
                raise ValueError(f"{name} close times are not strictly increasing")
            if spacing is not None and delta != spacing:
                raise ValueError(f"{name} close spacing is not native {spacing}")
        previous = bar.closed_at
    return result


def _full_1h_streams() -> tuple[FrozenStream, ...]:
    manifest = json.loads(f1b.G6_MANIFEST[0].read_text(encoding="utf-8"))
    if tuple(item.get("asset") for item in manifest["sources"]) != ASSETS:
        raise ValueError("F1B 1h asset order changed")
    streams: list[FrozenStream] = []
    for source in manifest["sources"]:
        path = Path(source["path"])
        if _sha256(path) != source["sha256"]:
            raise ValueError(f"F1B 1h source hash mismatch: {source['asset']}")
        rows, _ = f1b._read_source(path)
        if len(rows) != source["data_row_count"]:
            raise ValueError(f"F1B 1h row count mismatch: {source['asset']}")
        bars = _validate_bars(
            tuple(f1b._bar_from_row(row) for row in rows),
            name=f"{source['asset']} 1h",
            spacing=timedelta(hours=1),
        )
        streams.append(
            FrozenStream(
                asset=source["asset"],
                timeframe="1h",
                bars=bars,
                source_path=str(path),
                source_sha256=source["sha256"],
                source_row_count=len(bars),
                source_kind="frozen_f1b_1h",
            )
        )
    return tuple(streams)


def _native_frame_to_bars(frame: pd.DataFrame, asset: str) -> tuple[TrendlineBar, ...]:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("native Binance response must be a pandas DataFrame")
    required = {"open", "high", "low", "close", "close_time"}
    if not required.issubset(frame.columns):
        raise Native4HBlocked(f"{asset} native response lacks close_time/OHLC columns")
    raw_close = frame["close_time"]
    if pd.api.types.is_numeric_dtype(raw_close):
        close_times = pd.to_datetime(raw_close, unit="ms", utc=True, errors="raise")
    else:
        close_times = pd.to_datetime(raw_close, utc=True, errors="raise")
    bars = []
    for row, close_time in zip(frame.itertuples(index=False), close_times, strict=True):
        values = row._asdict()
        bars.append(
            TrendlineBar(
                closed_at=close_time.to_pydatetime(),
                open=_finite(values["open"], f"{asset} open"),
                high=_finite(values["high"], f"{asset} high"),
                low=_finite(values["low"], f"{asset} low"),
                close=_finite(values["close"], f"{asset} close"),
            )
        )
    return _validate_bars(
        bars, name=f"{asset} native 4h response", spacing=timedelta(hours=4)
    )


async def acquire_native_4h_once(
    adapter: BinanceNativeAdapter | None = None,
    *,
    adapter_factory: type[BinanceNativeAdapter] = BinanceNativeAdapter,
) -> tuple[tuple[FrozenStream, ...], tuple[dict[str, object], ...]]:
    """Perform the single authorized native-4h acquisition, without retry."""

    source = adapter if adapter is not None else adapter_factory()
    until_ms = int(NATIVE_4H_TERMINAL.timestamp() * 1000)
    streams: list[FrozenStream] = []
    ledger: list[dict[str, object]] = []
    for asset in ASSETS:
        ledger.append(
            {
                "asset": asset,
                "timeframe": "4h",
                "include_close_time": True,
                "limit": BINANCE_KLINE_PAGE_LIMIT,
                "until_ms": until_ms,
                "provider": "libs.market_data.binance_native.BinanceNativeAdapter",
            }
        )
        try:
            response = source.get_historical_ohlcv(
                asset,
                "4h",
                until=until_ms,
                limit=BINANCE_KLINE_PAGE_LIMIT,
                include_close_time=True,
            )
            if inspect.isawaitable(response):
                response = await response
            bars = _native_frame_to_bars(response, asset)
        except Native4HBlocked:
            raise
        except Exception as exc:
            raise Native4HBlocked(
                f"native 4h acquisition failed for {asset}: {exc}"
            ) from exc
        eligible = tuple(bar for bar in bars if bar.closed_at <= NATIVE_4H_TERMINAL)
        if len(eligible) < NATIVE_4H_LENGTH:
            raise Native4HBlocked(
                f"native 4h acquisition returned only {len(eligible)} eligible rows for {asset}"
            )
        retained = eligible[-NATIVE_4H_LENGTH:]
        if retained[-1].closed_at > NATIVE_4H_TERMINAL:
            raise Native4HBlocked(
                f"native 4h terminal exceeds F1B boundary for {asset}"
            )
        streams.append(
            FrozenStream(
                asset=asset,
                timeframe="4h",
                bars=_validate_bars(
                    retained,
                    name=f"{asset} retained native 4h",
                    spacing=timedelta(hours=4),
                ),
                source_path="",
                source_sha256="",
                source_row_count=len(retained),
                source_kind="native_binance_4h",
            )
        )
    terminals = {stream.terminal for stream in streams}
    if len(terminals) != 1:
        raise Native4HBlocked("native 4h streams do not share one terminal close")
    return tuple(streams), tuple(ledger)


def acquire_native_4h_once_sync(
    adapter: BinanceNativeAdapter | None = None,
    *,
    adapter_factory: type[BinanceNativeAdapter] = BinanceNativeAdapter,
) -> tuple[tuple[FrozenStream, ...], tuple[dict[str, object], ...]]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            acquire_native_4h_once(adapter, adapter_factory=adapter_factory)
        )
    raise RuntimeError("native 4h acquisition requires a non-running event loop")


def _native_csv_bytes(bars: Sequence[TrendlineBar]) -> bytes:
    lines = ["closed_at,open,high,low,close"]
    lines.extend(
        ",".join(
            (
                _timestamp(bar.closed_at),
                repr(float(bar.open)),
                repr(float(bar.high)),
                repr(float(bar.low)),
                repr(float(bar.close)),
            )
        )
        for bar in bars
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def freeze_native_4h_sources(
    streams: Sequence[FrozenStream],
    ledger: Sequence[dict[str, object]],
    output_dir: str | Path,
    authority: Mapping[str, str],
) -> dict[str, bytes]:
    """Write and authenticate the native-4h source freeze before analysis."""

    if tuple(stream.asset for stream in streams) != ASSETS:
        raise Native4HBlocked("native 4h source order changed")
    if any(len(stream.bars) != NATIVE_4H_LENGTH for stream in streams):
        raise Native4HBlocked("native 4h source is not exactly 491 rows")
    terminals = {stream.terminal for stream in streams}
    if len(terminals) != 1 or next(iter(terminals)) > NATIVE_4H_TERMINAL:
        raise Native4HBlocked("native 4h terminal provenance mismatch")
    directory = Path(output_dir)
    if directory.exists():
        raise FileExistsError(f"F1C output directory already exists: {directory}")
    directory.mkdir(parents=True)
    source_payloads = []
    csv_bytes_by_name: dict[str, bytes] = {}
    try:
        for stream in streams:
            name = f"native_4h_{stream.asset}.csv"
            content = _native_csv_bytes(stream.bars)
            csv_bytes_by_name[name] = content
            (directory / name).write_bytes(content)
            source_payloads.append(
                {
                    "asset": stream.asset,
                    "timeframe": "4h",
                    "file": name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "row_count": len(stream.bars),
                    "terminal_close": _timestamp(stream.terminal),
                    "spacing_seconds": 4 * 60 * 60,
                    "provider": "libs.market_data.binance_native.BinanceNativeAdapter",
                    "include_close_time": True,
                    "native_not_aggregated": True,
                }
            )
        body = {
            "schema_version": NATIVE_4H_SCHEMA_VERSION,
            "f1c_handoff_sha256": F1C_HANDOFF[1],
            "f1c_design_sha256": F1C_DESIGN[1],
            "f1b_terminal_close": _timestamp(NATIVE_4H_TERMINAL),
            "eligible_terminal_close": _timestamp(next(iter(terminals))),
            "source_count": len(source_payloads),
            "sources": source_payloads,
            "provider_call_ledger": list(ledger),
            "authority": dict(authority),
            "source_implementation_sha256": _sha256(Path(__file__)),
            "source_test_sha256": _sha256(
                ROOT
                / "tests/research/trendlines_v4/test_pivot_consensus_role_validation.py"
            ),
        }
        manifest = {**body, "manifest_id": _digest(body)}
        manifest_bytes = _canonical_bytes(manifest)
        (directory / "native_4h_manifest.json").write_bytes(manifest_bytes)
        return {**csv_bytes_by_name, "native_4h_manifest.json": manifest_bytes}
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def _load_native_4h_sources(
    output_dir: str | Path,
) -> tuple[tuple[FrozenStream, ...], dict[str, object]]:
    directory = Path(output_dir)
    manifest_path = directory / "native_4h_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != _digest(body):
        raise ValueError("native 4h manifest identity mismatch")
    streams: list[FrozenStream] = []
    for source in manifest.get("sources", []):
        path = directory / source["file"]
        if _sha256(path) != source["sha256"]:
            raise ValueError(f"native 4h frozen hash mismatch: {source['asset']}")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = tuple(csv.DictReader(handle))
        if len(rows) != NATIVE_4H_LENGTH:
            raise ValueError("native 4h frozen row count mismatch")
        bars = tuple(
            TrendlineBar(
                closed_at=_parse_timestamp(row["closed_at"]),
                open=_finite(float(row["open"]), "open"),
                high=_finite(float(row["high"]), "high"),
                low=_finite(float(row["low"]), "low"),
                close=_finite(float(row["close"]), "close"),
            )
            for row in rows
        )
        bars = _validate_bars(
            bars,
            name=f"{source['asset']} frozen native 4h",
            spacing=timedelta(hours=4),
        )
        if _timestamp(bars[-1].closed_at) != source["terminal_close"]:
            raise ValueError("native 4h terminal close mismatch")
        streams.append(
            FrozenStream(
                asset=source["asset"],
                timeframe="4h",
                bars=bars,
                source_path=str(path),
                source_sha256=source["sha256"],
                source_row_count=len(bars),
                source_kind="native_binance_4h",
            )
        )
    if tuple(stream.asset for stream in streams) != ASSETS:
        raise ValueError("native 4h asset order mismatch")
    if len({stream.terminal for stream in streams}) != 1:
        raise ValueError("native 4h terminal closes are not shared")
    return tuple(streams), manifest


def rolling_cutoff_indices(stream: FrozenStream) -> tuple[int, ...]:
    if stream.timeframe == "1h":
        if len(stream.bars) < HISTORY_LENGTH + ROLLING_CUTOFF_COUNT - 1:
            raise ValueError("1h stream is too short for F1C membership")
        return tuple(range(len(stream.bars) - ROLLING_CUTOFF_COUNT, len(stream.bars)))
    if stream.timeframe == "4h":
        if len(stream.bars) != NATIVE_4H_LENGTH:
            raise ValueError("4h stream must contain exactly 491 rows")
        return tuple(range(HISTORY_LENGTH - 1, NATIVE_4H_LENGTH))
    raise ValueError(f"unsupported F1C timeframe: {stream.timeframe}")


def rolling_histories(
    stream: FrozenStream,
) -> Iterable[tuple[int, tuple[TrendlineBar, ...]]]:
    for cutoff in rolling_cutoff_indices(stream):
        start = cutoff - HISTORY_LENGTH + 1
        history = stream.bars[start : cutoff + 1]
        if len(history) != HISTORY_LENGTH:
            raise ValueError("F1C rolling history is not exactly 300 bars")
        yield cutoff, history


def _candidate_preflight(
    history: Sequence[TrendlineBar],
) -> tuple[f1a.PivotConsensusTape, dict[str, int]]:
    support = f1a._confirmed_pivots(history, "support")
    resistance = f1a._confirmed_pivots(history, "resistance")
    preflight = f1a.candidate_cardinality_preflight(len(support), len(resistance))
    tape = f1a.build_candidate_tape(history)
    if len(tape.candidates) != preflight["total_candidate_count"]:
        raise ValueError("F1A candidate preflight does not match bounded iteration")
    return tape, preflight


def _candidate_payload(
    candidate: f1a.PivotConsensusCandidate | None,
) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "candidate_id": candidate.candidate_id,
        "geometry_id": candidate.geometry_id,
        "side": candidate.side,
        "anchor_mode": candidate.anchor_mode,
        "start_index": candidate.start_pivot.index,
        "end_index": candidate.end_pivot.index,
        "start_anchor_at": _timestamp(candidate.start_pivot.at),
        "end_anchor_at": _timestamp(candidate.end_pivot.at),
        "start_anchor_price": candidate.start_price,
        "end_anchor_price": candidate.end_price,
        "slope_per_bar": candidate.slope_per_bar,
        "projected_price": candidate.projected_price_at_market_as_of,
        "projection_positive": candidate.projection_positive,
        "anchor_span_bars": candidate.anchor_span_bars,
        "observable_from_at": _timestamp(candidate.observable_from_at),
        "observable_from_index": candidate.observable_from_index,
        "observable_age_bars": HISTORY_LENGTH - 1 - candidate.observable_from_index,
        "non_anchor_evidence_count": len(candidate.non_anchor_evidence),
        "anchor_body_intersection_count": candidate.anchor_body_intersection_count,
        "anchor_full_range_intersection_count": candidate.anchor_full_range_intersection_count,
        "body_intersection_count": candidate.body_intersection_count,
        "full_range_intersection_count": candidate.full_range_intersection_count,
        "median_non_anchor_residual_bps": candidate.median_non_anchor_nearest_residual_bps,
    }


def _v4_payload(
    role: str, line: object | None, history: Sequence[TrendlineBar]
) -> dict[str, object] | None:
    if line is None:
        return None
    index_by_time = {
        _timestamp(bar.closed_at): index for index, bar in enumerate(history)
    }
    start_at = _timestamp(line.start_anchor_at)
    end_at = _timestamp(line.end_anchor_at)
    if start_at not in index_by_time or end_at not in index_by_time:
        raise ValueError("V4 anchor is outside the F1C 300-bar history")
    return {
        "role": role,
        "side": line.side,
        "start_index": index_by_time[start_at],
        "end_index": index_by_time[end_at],
        "start_anchor_at": start_at,
        "end_anchor_at": end_at,
        "start_anchor_price": line.start_anchor_price,
        "end_anchor_price": line.end_anchor_price,
        "slope_per_bar": line.slope_per_bar,
        "projected_price": line.projected_price_at_market_as_of,
        "projection_positive": line.projection_positive,
        "post_anchor_body_cross_count": line.post_anchor_body_cross_count,
    }


def _line_identity(line: dict[str, object] | None) -> tuple[object, ...] | None:
    if line is None:
        return None
    return tuple(
        line[key]
        for key in (
            "side",
            "start_anchor_at",
            "start_anchor_price",
            "end_anchor_at",
            "end_anchor_price",
            "slope_per_bar",
            "projected_price",
        )
    )


def _bps_difference(left: float, right: float) -> float | None:
    if left <= 0 or right <= 0:
        return None
    return abs(left - right) / abs(right) * 10_000.0


def _line_comparison(
    left: dict[str, object] | None, right: dict[str, object] | None
) -> dict[str, object]:
    if left is None or right is None:
        return {
            "left_present": left is not None,
            "right_present": right is not None,
            "exact_geometry": False,
            "projected_price_difference_bps": None,
            "slope_difference": None,
            "start_anchor_equal": False,
            "end_anchor_equal": False,
            "anchor_time_overlap": False,
        }
    left_interval = (
        _parse_timestamp(left["start_anchor_at"]),
        _parse_timestamp(left["end_anchor_at"]),
    )
    right_interval = (
        _parse_timestamp(right["start_anchor_at"]),
        _parse_timestamp(right["end_anchor_at"]),
    )
    return {
        "left_present": True,
        "right_present": True,
        "exact_geometry": _line_identity(left) == _line_identity(right),
        "projected_price_difference_bps": _bps_difference(
            float(left["projected_price"]), float(right["projected_price"])
        ),
        "slope_difference": float(left["slope_per_bar"])
        - float(right["slope_per_bar"]),
        "start_anchor_equal": left["start_anchor_at"] == right["start_anchor_at"],
        "end_anchor_equal": left["end_anchor_at"] == right["end_anchor_at"],
        "anchor_time_overlap": max(left_interval[0], right_interval[0])
        <= min(left_interval[1], right_interval[1]),
    }


def _distribution(values: Iterable[float | int]) -> dict[str, object]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "p90": None,
            "p95": None,
            "maximum": None,
            "mean": None,
        }

    def percentile(q: float) -> float:
        position = (len(ordered) - 1) * q
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] + weight * (ordered[upper] - ordered[lower])

    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "median": float(median(ordered)),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "maximum": ordered[-1],
        "mean": math.fsum(ordered) / len(ordered),
    }


def _comparison_summary(records: Sequence[dict[str, object]]) -> dict[str, object]:
    total = len(records)
    present = [
        item for item in records if item["left_present"] and item["right_present"]
    ]
    present_count = len(present)
    return {
        "observation_count": total,
        "both_present_count": present_count,
        "both_present_rate": present_count / total if total else 0.0,
        "exact_geometry_count": sum(bool(item["exact_geometry"]) for item in present),
        "exact_geometry_rate": (
            sum(bool(item["exact_geometry"]) for item in present) / present_count
            if present_count
            else 0.0
        ),
        "start_anchor_equal_count": sum(
            bool(item["start_anchor_equal"]) for item in present
        ),
        "end_anchor_equal_count": sum(
            bool(item["end_anchor_equal"]) for item in present
        ),
        "anchor_time_overlap_count": sum(
            bool(item["anchor_time_overlap"]) for item in present
        ),
        "projected_price_difference_bps": _distribution(
            item["projected_price_difference_bps"]
            for item in present
            if item["projected_price_difference_bps"] is not None
        ),
        "slope_difference": _distribution(
            item["slope_difference"]
            for item in present
            if item["slope_difference"] is not None
        ),
    }


def _run_lengths(candidate_ids: Sequence[str | None]) -> list[int]:
    runs: list[int] = []
    previous: str | None = None
    length = 0
    for candidate_id in candidate_ids:
        if candidate_id is None:
            if length:
                runs.append(length)
            previous = None
            length = 0
            continue
        if previous == candidate_id:
            length += 1
        else:
            if length:
                runs.append(length)
            previous = candidate_id
            length = 1
    if length:
        runs.append(length)
    return runs


def _role_summary(observations: Sequence[dict[str, object]]) -> dict[str, object]:
    candidate_ids = [item["candidate_id"] for item in observations]
    available = [item for item in observations if item["candidate_id"] is not None]
    replacements = 0
    previous: str | None = None
    for candidate_id in candidate_ids:
        if candidate_id is None:
            previous = None
        elif previous is not None and candidate_id != previous:
            replacements += 1
        previous = candidate_id
    runs = _run_lengths(candidate_ids)
    return {
        "observation_count": len(observations),
        "availability_count": len(available),
        "availability_rate": len(available) / len(observations)
        if observations
        else 0.0,
        "candidate_id_sequence": candidate_ids,
        "candidate_id_sequence_sha256": _digest(candidate_ids),
        "replacement_count": replacements,
        "observed_episode_count": len(runs),
        "observed_episode_run_lengths": _distribution(runs),
        "bars_since_observable": _distribution(
            item["observable_age_bars"] for item in available
        ),
        "anchor_span_bars": _distribution(
            item["anchor_span_bars"] for item in available
        ),
        "non_anchor_evidence_count": _distribution(
            item["non_anchor_evidence_count"] for item in available
        ),
        "anchor_mode_counts": dict(
            sorted(Counter(item["anchor_mode"] for item in available).items())
        ),
        "projection_positive_count": sum(
            bool(item["projection_positive"]) for item in available
        ),
        "projection_positive_rate": (
            sum(bool(item["projection_positive"]) for item in available)
            / len(available)
            if available
            else 0.0
        ),
    }


def _analyze_cutoff(
    history: Sequence[TrendlineBar], cutoff_position: int
) -> dict[str, object]:
    tape, preflight = _candidate_preflight(history)
    snapshot = analyze_trendlines_v2(tuple(history))
    selected: dict[Side, dict[str, f1a.PivotConsensusCandidate | None]] = {}
    v4_context: dict[Side, dict[str, dict[str, object] | None]] = {}
    role_records: list[dict[str, object]] = []
    role_comparisons: list[dict[str, object]] = []
    for side in SIDES:
        candidates = tape.candidates_for_side(side)
        span = f1b.select_span_first(candidates) if candidates else None
        local = f1b.select_consensus_first(candidates) if candidates else None
        selected[side] = {"structural": span, "local": local}
        side_snapshot = getattr(snapshot, side)
        context = {
            role: _v4_payload(role, getattr(side_snapshot, role), history)
            for role in V4_ROLES
        }
        v4_context[side] = context
        selected_payload = {
            role: _candidate_payload(candidate)
            for role, candidate in selected[side].items()
        }
        for role in PIVOT_ROLES:
            candidate_payload = selected_payload[role]
            role_records.append(
                {
                    "cutoff_position": cutoff_position,
                    "cutoff_at": _timestamp(history[-1].closed_at),
                    "side": side,
                    "role": role,
                    "candidate_id": candidate_payload["candidate_id"]
                    if candidate_payload
                    else None,
                    "geometry_id": candidate_payload["geometry_id"]
                    if candidate_payload
                    else None,
                    "anchor_mode": candidate_payload["anchor_mode"]
                    if candidate_payload
                    else None,
                    "anchor_span_bars": candidate_payload["anchor_span_bars"]
                    if candidate_payload
                    else None,
                    "non_anchor_evidence_count": candidate_payload[
                        "non_anchor_evidence_count"
                    ]
                    if candidate_payload
                    else None,
                    "projection_positive": candidate_payload["projection_positive"]
                    if candidate_payload
                    else None,
                    "observable_age_bars": candidate_payload["observable_age_bars"]
                    if candidate_payload
                    else None,
                    "start_anchor_at": candidate_payload["start_anchor_at"]
                    if candidate_payload
                    else None,
                    "end_anchor_at": candidate_payload["end_anchor_at"]
                    if candidate_payload
                    else None,
                    "slope_per_bar": candidate_payload["slope_per_bar"]
                    if candidate_payload
                    else None,
                    "projected_price": candidate_payload["projected_price"]
                    if candidate_payload
                    else None,
                }
            )
            role_comparisons.append(
                {
                    "cutoff_position": cutoff_position,
                    "side": side,
                    "role": role,
                    "comparison": _line_comparison(
                        selected_payload[role],
                        selected_payload["structural" if role == "local" else "local"],
                    ),
                    "v4": {
                        v4_role: _line_comparison(
                            selected_payload[role], context[v4_role]
                        )
                        for v4_role in V4_ROLES
                    },
                }
            )
        role_comparisons[-2]["role_pair"] = {
            "same_candidate": (
                selected[side]["structural"] is not None
                and selected[side]["local"] is not None
                and selected[side]["structural"].candidate_id
                == selected[side]["local"].candidate_id
            ),
            "same_geometry": (
                selected[side]["structural"] is not None
                and selected[side]["local"] is not None
                and selected[side]["structural"].geometry_id
                == selected[side]["local"].geometry_id
            ),
        }
        role_comparisons[-1]["role_pair"] = role_comparisons[-2]["role_pair"]
    return {
        "cutoff_position": cutoff_position,
        "cutoff_at": _timestamp(history[-1].closed_at),
        "preflight": preflight,
        "selected": selected,
        "v4_context": v4_context,
        "role_records": role_records,
        "role_comparisons": role_comparisons,
    }


def _role_comparison_summary(records: Sequence[dict[str, object]]) -> dict[str, object]:
    summary: dict[str, object] = {}
    pair_records = [item for item in records if "role_pair" in item]
    summary["structural_local"] = {
        "same_candidate_count": sum(
            bool(item["role_pair"]["same_candidate"]) for item in pair_records
        ),
        "same_geometry_count": sum(
            bool(item["role_pair"]["same_geometry"]) for item in pair_records
        ),
    }
    for role in PIVOT_ROLES:
        role_records = [item for item in records if item["role"] == role]
        summary[role] = {
            "v4": {
                v4_role: _comparison_summary(
                    [item["v4"][v4_role] for item in role_records]
                )
                for v4_role in V4_ROLES
            }
        }
    return summary


def _stream_measurement(
    stream: FrozenStream,
) -> tuple[dict[str, object], dict[str, object]]:
    observations: dict[tuple[Side, str], list[dict[str, object]]] = {
        (side, role): [] for side in SIDES for role in PIVOT_ROLES
    }
    comparisons: dict[tuple[Side, str], list[dict[str, object]]] = {
        (side, role): [] for side in SIDES for role in PIVOT_ROLES
    }
    max_candidate_count = 0
    max_evidence_rows = 0
    last: dict[str, object] | None = None
    for cutoff_position, history in rolling_histories(stream):
        analysis = _analyze_cutoff(history, cutoff_position)
        max_candidate_count = max(
            max_candidate_count, analysis["preflight"]["total_candidate_count"]
        )
        max_evidence_rows = max(
            max_evidence_rows,
            analysis["preflight"]["total_potential_pivot_evidence_rows"],
        )
        for record in analysis["role_records"]:
            observations[(record["side"], record["role"])].append(record)
        for record in analysis["role_comparisons"]:
            comparisons[(record["side"], record["role"])].append(record)
        last = analysis
    if last is None:
        raise ValueError("F1C stream produced no cutoffs")
    role_summaries = []
    for side in SIDES:
        for role in PIVOT_ROLES:
            role_summaries.append(
                {
                    "side": side,
                    "role": role,
                    **_role_summary(observations[(side, role)]),
                    "comparisons": _role_comparison_summary(comparisons[(side, role)]),
                }
            )
    result = {
        **stream.as_payload(),
        "cutoff_count": sum(1 for _ in rolling_cutoff_indices(stream)),
        "cutoff_start": rolling_cutoff_indices(stream)[0],
        "cutoff_end_exclusive": rolling_cutoff_indices(stream)[-1] + 1,
        "role_observation_count": sum(len(items) for items in observations.values()),
        "role_summaries": role_summaries,
        "max_candidate_preflight": max_candidate_count,
        "max_potential_pivot_evidence_rows": max_evidence_rows,
    }
    return result, last


def _candle_payload(bars: Sequence[TrendlineBar]) -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "closed_at": _timestamp(bar.closed_at),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
        }
        for index, bar in enumerate(bars)
    ]


def _dedupe_v4_context(
    context: Mapping[str, dict[str, object] | None],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    by_identity: dict[tuple[object, ...], int] = {}
    for role in V4_ROLES:
        line = context[role]
        if line is None:
            continue
        identity = _line_identity(line)
        if identity in by_identity:
            index = by_identity[identity]
            result[index] = {**result[index], "role": f"{result[index]['role']}+{role}"}
        else:
            by_identity[identity] = len(result)
            result.append(dict(line))
    return result


def _build_combined_cases(
    streams: Sequence[FrozenStream],
    terminal_analyses: Mapping[tuple[str, str], dict[str, object]],
) -> dict[str, object]:
    cases = []
    case_number = 0
    for stream in streams:
        analysis = terminal_analyses[(stream.asset, stream.timeframe)]
        terminal_bars = stream.bars[-HISTORY_LENGTH:]
        for side in SIDES:
            case_number += 1
            selected = analysis["selected"][side]
            pivot_lines = {
                role: _candidate_payload(selected[role]) for role in PIVOT_ROLES
            }
            context = analysis["v4_context"][side]
            cases.append(
                {
                    "case_number": case_number,
                    "asset": stream.asset,
                    "timeframe": stream.timeframe,
                    "side": side,
                    "cutoff_position": analysis["cutoff_position"],
                    "market_as_of": analysis["cutoff_at"],
                    "candles": _candle_payload(terminal_bars),
                    "v4_context": _dedupe_v4_context(context),
                    "pivot_consensus": pivot_lines,
                    "pivot_vs_v4": {
                        role: {
                            v4_role: _line_comparison(
                                pivot_lines[role], context[v4_role]
                            )
                            for v4_role in V4_ROLES
                        }
                        for role in PIVOT_ROLES
                    },
                }
            )
    if len(cases) != 16:
        raise ValueError("F1C combined case inventory must contain 16 cases")
    return {
        "schema_version": "trendlines_v4_f1c_combined_cases_v1",
        "case_count": len(cases),
        "cases": cases,
        "ratings_collected": False,
    }


def _svg_case(case: Mapping[str, object]) -> str:
    bars = case["candles"]
    lines: list[dict[str, object]] = []
    for line in case["v4_context"]:
        lines.append(
            {
                **line,
                "label": f"V4 {line['role']}",
                "color": "#b91c1c" if case["side"] == "resistance" else "#15803d",
                "dash": "5 4"
                if "current_valid" in line["role"]
                else ("2 3" if "secondary" in line["role"] else ""),
            }
        )
    for role, line in case["pivot_consensus"].items():
        if line is not None:
            lines.append(
                {
                    **line,
                    "label": f"pivot_consensus.{role}",
                    "color": "#7c3aed" if role == "local" else "#0369a1",
                    "dash": "6 3" if role == "local" else "",
                }
            )
    values = [float(item[key]) for item in bars for key in ("low", "high")]
    for line in lines:
        values.extend(
            float(line["slope_per_bar"]) * index
            + (
                float(line["end_anchor_price"])
                - float(line["slope_per_bar"]) * int(line["end_index"])
            )
            for index in range(int(line["start_index"]), len(bars))
        )
    low, high = min(values), max(values)
    pad = (high - low) * 0.05 or max(abs(high) * 0.01, 1e-9)
    low -= pad
    high += pad
    width, height, top, bottom = 1440, 520, 42, 400

    def x(index: int) -> float:
        return 32 + index * (width - 64) / max(1, len(bars) - 1)

    def y(value: float) -> float:
        return top + (high - value) * (bottom - top) / (high - low)

    fragments = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" data-candle-count="300">',
        f'<text x="20" y="24" font-family="sans-serif" font-size="16">{html.escape(str(case["asset"]))} · {html.escape(str(case["timeframe"]))} · {html.escape(str(case["side"]))}</text>',
    ]
    for index, bar in enumerate(bars):
        cx = x(index)
        color = "#15803d" if float(bar["close"]) >= float(bar["open"]) else "#b91c1c"
        fragments.append(
            f'<line x1="{cx:.3f}" x2="{cx:.3f}" y1="{y(float(bar["high"])):.3f}" y2="{y(float(bar["low"])):.3f}" stroke="{color}" stroke-width="1"/><rect x="{cx - 1.4:.3f}" y="{y(max(float(bar["open"]), float(bar["close"]))):.3f}" width="2.8" height="{max(1.0, y(min(float(bar["open"]), float(bar["close"]))) - y(max(float(bar["open"]), float(bar["close"])))):.3f}" fill="{color}"/>'
        )
    for line in lines:
        slope = float(line["slope_per_bar"])
        intercept = float(line["end_anchor_price"]) - slope * int(line["end_index"])
        dash = f' stroke-dasharray="{line["dash"]}"' if line["dash"] else ""
        fragments.append(
            f'<line x1="{x(int(line["start_index"])):.3f}" x2="{x(len(bars) - 1):.3f}" y1="{y(slope * int(line["start_index"]) + intercept):.3f}" y2="{y(slope * (len(bars) - 1) + intercept):.3f}" stroke="{line["color"]}" stroke-width="3"{dash}/>'
        )
    legend = " · ".join(str(line["label"]) for line in lines)
    fragments.append(
        f'<text x="20" y="438" font-family="sans-serif" font-size="12">{html.escape(legend)}</text><text x="20" y="460" font-family="sans-serif" font-size="11">market_as_of={html.escape(str(case["market_as_of"]))}</text></svg>'
    )
    return "".join(fragments)


def _combined_review_html(combined: Mapping[str, object]) -> bytes:
    fragments = [
        '<!doctype html><html><head><meta charset="utf-8"><title>Trendlines V4 F1C role validation</title><style>body{font-family:sans-serif;background:#f3f4f6;color:#111827;margin:24px}section{background:#fff;border:1px solid #d1d5db;margin:0 0 24px;padding:16px}svg{max-width:100%;height:auto}h1{margin-top:0}</style></head><body>',
        "<h1>Trendlines V4 F1C role persistence and clutter review</h1><p>These are factual, non-blinded terminal geometry cases. No forward outcomes or ratings are included.</p>",
    ]
    for case in combined["cases"]:
        fragments.append(
            f'<section data-case-number="{case["case_number"]}"><h2>Case {case["case_number"]} · {html.escape(str(case["asset"]))} · {html.escape(str(case["timeframe"]))} · {html.escape(str(case["side"]))}</h2>{_svg_case(case)}</section>'
        )
    fragments.append("</body></html>\n")
    return "".join(fragments).encode("utf-8")


def _analyze_frozen_streams(
    streams: Sequence[FrozenStream], native_manifest: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    stream_reports = []
    terminal_analyses: dict[tuple[str, str], dict[str, object]] = {}
    max_candidate_count = 0
    max_evidence_rows = 0
    total_cutoffs = 0
    for stream in streams:
        stream_report, terminal = _stream_measurement(stream)
        stream_reports.append(stream_report)
        terminal_analyses[(stream.asset, stream.timeframe)] = terminal
        max_candidate_count = max(
            max_candidate_count, stream_report["max_candidate_preflight"]
        )
        max_evidence_rows = max(
            max_evidence_rows, stream_report["max_potential_pivot_evidence_rows"]
        )
        total_cutoffs += stream_report["cutoff_count"]
    if total_cutoffs != 1536:
        raise ValueError(f"F1C cutoff inventory mismatch: {total_cutoffs}")
    role_slots = total_cutoffs * len(SIDES) * len(PIVOT_ROLES)
    report_body = {
        "schema_version": SCHEMA_VERSION,
        "f1c_handoff_sha256": F1C_HANDOFF[1],
        "f1c_design_sha256": F1C_DESIGN[1],
        "f1a_approval_sha256": F1A_APPROVAL[1],
        "f1b_ratings_sha256": F1B_RATINGS[1],
        "f1b_unblinded_sha256": F1B_UNBLINDED[1],
        "f1b_source_sha256": F1B_SOURCE[1],
        "f1b_test_sha256": F1B_TEST[1],
        "native_4h_manifest_id": native_manifest["manifest_id"],
        "native_4h_manifest_sha256": _sha256(Path(native_manifest["_path"])),
        "historical_h0_n4_derived_4h_excluded": True,
        "frozen_geometry": {"pivot_window": 3, "history": 300},
        "stream_count": len(stream_reports),
        "cutoff_count": total_cutoffs,
        "side_cutoff_count": total_cutoffs * len(SIDES),
        "role_observation_slots": role_slots,
        "max_candidate_preflight": max_candidate_count,
        "max_potential_pivot_evidence_rows": max_evidence_rows,
        "streams": stream_reports,
        "timeframe_inventory": {
            timeframe: {
                "stream_count": sum(
                    item["timeframe"] == timeframe for item in stream_reports
                ),
                "cutoff_count": sum(
                    item["cutoff_count"]
                    for item in stream_reports
                    if item["timeframe"] == timeframe
                ),
                "side_cutoff_count": sum(
                    item["cutoff_count"]
                    for item in stream_reports
                    if item["timeframe"] == timeframe
                )
                * len(SIDES),
                "role_observation_slots": sum(
                    item["cutoff_count"]
                    for item in stream_reports
                    if item["timeframe"] == timeframe
                )
                * len(SIDES)
                * len(PIVOT_ROLES),
            }
            for timeframe in ("1h", "4h")
        },
        "no_threshold_or_quality_score": True,
        "no_forward_return_or_pnl": True,
    }
    report = {**report_body, "report_id": _digest(report_body)}
    return report, terminal_analyses


def _build_manifest(
    output_dir: Path,
    report: Mapping[str, object],
    combined: Mapping[str, object],
    analytical_payloads: Mapping[str, bytes],
) -> dict[str, object]:
    expected_analytical = set(ANALYTICAL_NAMES) - {"manifest.json"}
    if set(analytical_payloads) != expected_analytical:
        raise ValueError("F1C analytical payload inventory is not exact")
    inventory = {name: _sha256(output_dir / name) for name in NATIVE_FREEZE_NAMES}
    inventory.update(
        {
            name: hashlib.sha256(content).hexdigest()
            for name, content in analytical_payloads.items()
        }
    )
    body = {
        "schema_version": "trendlines_v4_f1c_artifact_manifest_v1",
        "f1c_handoff_sha256": F1C_HANDOFF[1],
        "f1c_design_sha256": F1C_DESIGN[1],
        "f1b_source_sha256": F1B_SOURCE[1],
        "f1b_test_sha256": F1B_TEST[1],
        "native_4h_manifest_id": json.loads(
            (output_dir / "native_4h_manifest.json").read_text()
        )["manifest_id"],
        "report_id": report["report_id"],
        "combined_case_count": combined["case_count"],
        "artifact_inventory": inventory,
        "ratings_collected": False,
    }
    return {**body, "manifest_id": _digest(body)}


def build_local_payloads(
    output_dir: str | Path = ARTIFACT_DIR,
) -> dict[str, bytes]:
    """Rebuild all post-freeze analytical payloads without network access."""

    directory = Path(output_dir)
    native_streams, native_manifest = _load_native_4h_sources(directory)
    native_manifest = {
        **native_manifest,
        "_path": str(directory / "native_4h_manifest.json"),
    }
    streams = (*_full_1h_streams(), *native_streams)
    report, terminal = _analyze_frozen_streams(streams, native_manifest)
    combined = _build_combined_cases(streams, terminal)
    report_bytes = _canonical_bytes(report)
    combined_bytes = _canonical_bytes(combined)
    html_bytes = _combined_review_html(combined)
    analytical_payloads = {
        "report.json": report_bytes,
        "combined_cases.json": combined_bytes,
        "combined_review.html": html_bytes,
    }
    manifest = _build_manifest(
        directory,
        report,
        combined,
        analytical_payloads,
    )
    return {
        **analytical_payloads,
        "manifest.json": _canonical_bytes(manifest),
    }


def validate_artifact_bundle(
    output_dir: str | Path = ARTIFACT_DIR,
) -> dict[str, object]:
    directory = Path(output_dir)
    expected = {
        "native_4h_manifest.json",
        *{f"native_4h_{asset}.csv" for asset in ASSETS},
        "report.json",
        "combined_cases.json",
        "combined_review.html",
        "manifest.json",
    }
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    if actual != expected:
        raise ValueError(f"F1C artifact inventory mismatch: {sorted(actual)}")
    manifest = json.loads((directory / "manifest.json").read_text())
    body = {key: value for key, value in manifest.items() if key != "manifest_id"}
    if manifest.get("manifest_id") != _digest(body):
        raise ValueError("F1C artifact manifest identity mismatch")
    for name, expected_hash in manifest["artifact_inventory"].items():
        if _sha256(directory / name) != expected_hash:
            raise ValueError(f"F1C artifact hash mismatch: {name}")
    report = json.loads((directory / "report.json").read_text())
    if report.get("report_id") != _digest(
        {key: value for key, value in report.items() if key != "report_id"}
    ):
        raise ValueError("F1C report identity mismatch")
    combined = json.loads((directory / "combined_cases.json").read_text())
    if combined.get("case_count") != 16 or len(combined.get("cases", ())) != 16:
        raise ValueError("F1C combined case inventory mismatch")
    native_manifest = json.loads((directory / "native_4h_manifest.json").read_text())
    if native_manifest.get("source_count") != 4:
        raise ValueError("F1C native source inventory mismatch")
    return {
        "manifest_id": manifest["manifest_id"],
        "report_id": report["report_id"],
        "case_count": combined["case_count"],
        "native_manifest_id": native_manifest["manifest_id"],
    }


def write_analytical_artifacts(
    output_dir: str | Path = ARTIFACT_DIR,
) -> dict[str, object]:
    directory = Path(output_dir)
    if not directory.is_dir():
        raise FileNotFoundError(
            "F1C native source freeze must exist before analytical publication"
        )
    if {path.name for path in directory.iterdir() if path.is_file()} != set(
        NATIVE_FREEZE_NAMES
    ):
        raise ValueError("F1C native source freeze inventory is not exact")
    native_hashes = {name: _sha256(directory / name) for name in NATIVE_FREEZE_NAMES}
    temp_dir: Path | None = None
    try:
        payloads = build_local_payloads(directory)
        if set(payloads) != set(ANALYTICAL_NAMES):
            raise ValueError("F1C analytical payload inventory is not exact")
        temp_dir = Path(tempfile.mkdtemp(prefix=".f1c-analytical-", dir=directory))
        for name, content in payloads.items():
            (temp_dir / name).write_bytes(content)
        for name in ANALYTICAL_NAMES:
            os.replace(temp_dir / name, directory / name)
        temp_dir.rmdir()
        temp_dir = None
        return validate_artifact_bundle(directory)
    except Exception:
        for name in ANALYTICAL_NAMES:
            (directory / name).unlink(missing_ok=True)
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
        observed_native = {
            name: _sha256(directory / name) for name in NATIVE_FREEZE_NAMES
        }
        if observed_native != native_hashes:
            raise ValueError("F1C native source freeze changed during publication")
        raise


def execute_f1c(output_dir: str | Path = ARTIFACT_DIR) -> dict[str, object]:
    """Run F1C once: authenticate, acquire native 4h, freeze, then measure."""

    authority = authenticate_frozen_inputs()
    directory = Path(output_dir)
    if directory.exists():
        raise FileExistsError(f"F1C output directory already exists: {directory}")
    started = time.perf_counter()
    native_streams, ledger = acquire_native_4h_once_sync()
    freeze_native_4h_sources(native_streams, ledger, directory, authority)
    # The source freeze is now the only 4h input to all downstream work.
    write_analytical_artifacts(directory)
    rebuilt = build_local_payloads(directory)
    for name, content in rebuilt.items():
        if content != (directory / name).read_bytes():
            raise ValueError(f"F1C deterministic rebuild mismatch: {name}")
    elapsed = time.perf_counter() - started
    result = validate_artifact_bundle(directory)
    result.update(
        {
            "elapsed_seconds": elapsed,
            "native_call_count": len(ledger),
            "native_provider": "libs.market_data.binance_native.BinanceNativeAdapter",
            "cutoff_count": 1536,
            "side_cutoff_count": 3072,
            "role_observation_slots": 6144,
        }
    )
    return result


__all__ = [
    "ARTIFACT_DIR",
    "ASSETS",
    "F1C_DESIGN",
    "F1C_HANDOFF",
    "HISTORY_LENGTH",
    "NATIVE_4H_LENGTH",
    "NATIVE_4H_TERMINAL",
    "FrozenStream",
    "Native4HBlocked",
    "acquire_native_4h_once",
    "acquire_native_4h_once_sync",
    "authenticate_frozen_inputs",
    "build_local_payloads",
    "execute_f1c",
    "freeze_native_4h_sources",
    "rolling_cutoff_indices",
    "rolling_histories",
    "validate_artifact_bundle",
    "write_analytical_artifacts",
]
