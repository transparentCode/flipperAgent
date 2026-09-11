"""Verified chart projection and local evidence index for the SR v2 viewer."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from ..domain.identity import canonical_hash, canonical_json

if TYPE_CHECKING:
    from ..research_lab.trace import SRV2ResearchTrace

MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_ITEMS = 250_000
REQUIRED_BUNDLE_FILES = frozenset({"chart_payload.json", "evidence_index.json"})
_TRANSITION_EVENTS = frozenset(
    {
        "CREATED",
        "TOUCH_STARTED",
        "TOUCH_ENDED",
        "BREAK_PENDING",
        "BREAK_CLEARED",
        "BROKEN",
        "EXPIRED",
        "SUPERSEDED",
        "TOMBSTONE_PRUNED",
    }
)
_NON_TERMINAL_LIFECYCLES = frozenset({"ACTIVE", "TOUCHED", "BREAK_PENDING"})


def _plain(value: Any) -> Any:
    """Convert trace values to the viewer's plain JSON contract."""

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("viewer decimals must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("viewer datetimes must be timezone-aware UTC")
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("viewer numbers must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported viewer value: {type(value).__name__}")


def _parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 UTC string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return parsed.astimezone(UTC)


def _parse_decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise ValueError(f"{field} must be a finite decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal string")
    return parsed


def _validate_chart_rows(rows: Any, *, field: str) -> None:
    if not isinstance(rows, list):
        raise TypeError(f"{field} must be a list")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"{field}[{index}] must be an object")
        required = {"bar_close_at", "open", "high", "low", "close"}
        if not required.issubset(row):
            raise ValueError(f"{field}[{index}] is missing chart OHLC fields")
        _parse_utc(row["bar_close_at"], f"{field}[{index}].bar_close_at")
        for name in ("open", "high", "low", "close"):
            if row[name] is None:
                raise ValueError(f"{field}[{index}].{name} must be present")
            _parse_decimal(row[name], f"{field}[{index}].{name}")
        for name in ("volume", "true_range", "atr"):
            if name in row and row[name] is not None:
                _parse_decimal(row[name], f"{field}[{index}].{name}")


def _regular_file(path: Path, field: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{field} must be a regular non-symlink file")
    data = path.read_bytes()
    if len(data) > MAX_BUNDLE_BYTES:
        raise ValueError(f"{field} exceeds viewer bundle size limit")
    return data


def _identity(value: Mapping[str, Any]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("viewer market_identity must be a mapping")
    if set(value) != {"venue", "instrument_id", "asset"}:
        raise ValueError("viewer market_identity must contain venue, instrument_id, and asset")
    result: dict[str, str] = {}
    for name in ("venue", "instrument_id", "asset"):
        item = value[name]
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"viewer market_identity.{name} must be non-empty")
        result[name] = item
    return result


def _normalize_display_policy(value: object) -> Mapping[str, Any]:
    """Use the notebook-owned display contract without an import cycle."""

    from ..research_lab.config import normalize_display_policy

    return normalize_display_policy(value, name="viewer display")


def _interval_overlaps(interval: Any, start: datetime, end: datetime) -> bool:
    return interval.entered_at < end and (interval.exited_at is None or interval.exited_at > start)


def _visible_rows(
    rows: list[Mapping[str, Any]],
    *,
    limit: int | None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], datetime | None]:
    """Select unique close cutoffs, retaining every kernel row at those cutoffs."""

    by_close: dict[datetime, Mapping[str, Any]] = {}
    for row in rows:
        close = row.get("bar_close_at")
        if isinstance(close, datetime):
            by_close.setdefault(close, row)
    closes = sorted(by_close)
    if limit is not None:
        closes = closes[-limit:]
    visible = set(closes)
    selected_rows = [row for row in rows if row.get("bar_close_at") in visible]
    candles = [by_close[close] for close in closes]
    return candles, selected_rows, (closes[0] if closes else None)


def _project_zone_ids(
    trace: SRV2ResearchTrace,
    timeframe: str,
    *,
    window_start: datetime,
    window_end: datetime,
) -> set[str]:
    """Keep display-window evidence plus one-hop lineage context."""

    records = {
        zone_id: zone
        for zone_id, zone in trace.lineage_records.items()
        if getattr(zone.lineage, "source_timeframe", None) == timeframe
    }
    relevant: set[str] = {
        interval.zone_id
        for interval in trace.lifecycle_intervals
        if interval.source_timeframe == timeframe
        and interval.lifecycle in _NON_TERMINAL_LIFECYCLES
        and (
            _interval_overlaps(interval, window_start, window_end)
            or (
                interval.entered_at < trace.analysis_start
                and (interval.exited_at is None or interval.exited_at > trace.analysis_start)
            )
        )
    }
    visible_candidate_keys = {
        row["candidate_key"]
        for row in trace.candidate_rows
        if row.get("timeframe") == timeframe
        and isinstance(row.get("cutoff"), datetime)
        and window_start <= row["cutoff"] <= window_end
        and row.get("candidate_key") is not None
    }
    visible_source_evidence_ids = {
        row["source_evidence_id"]
        for row in trace.candidate_rows
        if row.get("timeframe") == timeframe
        and isinstance(row.get("cutoff"), datetime)
        and window_start <= row["cutoff"] <= window_end
        and row.get("source_evidence_id") is not None
    }
    relevant.update(
        zone_id
        for zone_id, zone in records.items()
        if zone.lineage.source_evidence_id in visible_source_evidence_ids
        or zone.lineage.source_candidate_key in visible_source_evidence_ids
        or zone.lineage.source_candidate_key in visible_candidate_keys
    )
    relevant.update(
        transition.zone_id
        for transition in trace.transitions
        if isinstance(transition.event_at, datetime)
        and window_start <= transition.event_at <= window_end
        and transition.zone_id in records
    )
    predecessor_by_zone = {
        transition.zone_id: transition.predecessor_id
        for transition in trace.transitions
        if transition.predecessor_id is not None
    }
    successor_by_zone = {
        transition.zone_id: transition.successor_id
        for transition in trace.transitions
        if transition.successor_id is not None
    }
    seeds = tuple(relevant)
    for zone_id in seeds:
        record = records.get(zone_id)
        lineage_predecessor = record.lineage.predecessor_id if record is not None else None
        for neighbor in (
            lineage_predecessor,
            predecessor_by_zone.get(zone_id),
            successor_by_zone.get(zone_id),
        ):
            neighbor_record = records.get(neighbor) if neighbor is not None else None
            if neighbor_record is None or neighbor in relevant:
                continue
            if neighbor_record.lineage.formed_at < trace.reconstruction_start:
                continue
            relevant.add(neighbor)
    return relevant & set(records)


def _zone_payload(zone: Any) -> Mapping[str, Any]:
    lineage = zone.lineage
    return {
        "zone_id": lineage.zone_id,
        "source_timeframe": lineage.source_timeframe,
        "venue": lineage.venue,
        "instrument_id": lineage.instrument_id,
        "asset": lineage.asset,
        "kernel_id": lineage.kernel_id,
        "kernel_version": lineage.kernel_version,
        "side": lineage.side.value,
        "center": _plain(lineage.center),
        "lower": _plain(lineage.lower),
        "upper": _plain(lineage.upper),
        "geometry": {
            "center": _plain(lineage.center),
            "lower": _plain(lineage.lower),
            "upper": _plain(lineage.upper),
        },
        "formed_at": _plain(lineage.formed_at),
        "available_at": _plain(lineage.available_at),
        "source_evidence_id": lineage.source_evidence_id,
        "source_candidate_key": lineage.source_candidate_key,
        "predecessor_id": lineage.predecessor_id,
    }


def _transition_payload(transition: Any, zone_by_id: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    zone = zone_by_id.get(transition.zone_id)
    return {
        "transition_id": transition.transition_id,
        "ordinal": transition.ordinal,
        "event": transition.transition_type.value,
        "event_at": _plain(transition.event_at),
        "zone_id": transition.zone_id,
        "before_lifecycle": None if transition.before_lifecycle is None else transition.before_lifecycle.value,
        "after_lifecycle": None if transition.after_lifecycle is None else transition.after_lifecycle.value,
        "before_overlapping": transition.before_overlapping,
        "after_overlapping": transition.after_overlapping,
        "causal_bar_id": transition.causal_bar_id,
        "predecessor_id": transition.predecessor_id,
        "successor_id": transition.successor_id,
        "retention_state": transition.retention_state,
        "before_touch_count": transition.before_touch_count,
        "after_touch_count": transition.after_touch_count,
        "before_break_pending_count": transition.before_break_pending_count,
        "after_break_pending_count": transition.after_break_pending_count,
        "side": None if zone is None else zone["side"],
        "source_evidence_id": None if zone is None else zone["source_evidence_id"],
        "geometry": None if zone is None else dict(zone["geometry"]),
    }


def _aggregate_candidates(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    grouped: dict[tuple[str, str, str], int] = {}
    for row in rows:
        available = row.get("available_at") or row.get("formed_at") or row.get("cutoff")
        side = row.get("side")
        kernel = row.get("kernel_id")
        if not isinstance(available, str) or not isinstance(side, str) or not isinstance(kernel, str):
            continue
        key = (available, side, kernel)
        grouped[key] = grouped.get(key, 0) + 1
    return [
        {
            "available_at": available,
            "side": side,
            "kernel_id": kernel,
            "count": count,
        }
        for (available, side, kernel), count in sorted(grouped.items())
    ]


def _build_payload_and_evidence(
    trace: SRV2ResearchTrace,
    *,
    display: Mapping[str, Any],
    market_identity: Mapping[str, str],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    configured = tuple(trace.configured_timeframes)
    if not configured:
        raise ValueError("trace must carry its resolved configured timeframe ladder")
    if set(configured) != set(trace.bars_by_timeframe):
        raise ValueError("trace configured timeframe ladder does not cover raw bar panes")
    lifecycle_timeframe = configured[-1]
    candle_limit = display["candle_limit"]
    panes: dict[str, Mapping[str, Any]] = {}
    evidence_panes: dict[str, Mapping[str, Any]] = {}
    last = trace.snapshots[-1]
    for timeframe in configured:
        raw_formation_rows = [
            {
                "bar_close_at": bar.bar_close_at,
                "bar_open_at": bar.bar_open_at,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in trace.bars_by_timeframe[timeframe]
            if trace.analysis_start <= bar.bar_close_at <= trace.knowledge_cutoff
        ]
        formation_candles_raw, _, formation_start = _visible_rows(
            raw_formation_rows,
            limit=candle_limit,
        )
        raw_lifecycle_rows = [
            {
                "bar_close_at": bar.bar_close_at,
                "bar_open_at": bar.bar_open_at,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in trace.bars_by_timeframe[lifecycle_timeframe]
            if trace.analysis_start <= bar.bar_close_at <= trace.knowledge_cutoff
        ]
        lifecycle_candles_raw, _, lifecycle_start = _visible_rows(raw_lifecycle_rows, limit=candle_limit)
        window_starts = [item for item in (formation_start, lifecycle_start) if item is not None]
        window_start = min(window_starts) if window_starts else trace.analysis_start
        formation_candles = [_plain(row) for row in formation_candles_raw]
        lifecycle_candles = [_plain(row) for row in lifecycle_candles_raw]
        # The chart payload is the authoritative display-window candle store.
        # The server-only sidecar carries only rows needed to inspect that same
        # bounded window; it must not become a second full replay dump.
        displayed_formation_closes = {
            row["bar_close_at"]
            for row in formation_candles_raw
            if isinstance(row.get("bar_close_at"), datetime)
        }
        evidence_formation_rows = [
            _plain(row)
            for row in trace.feature_rows
            if row.get("timeframe") == timeframe
            and isinstance(row.get("bar_close_at"), datetime)
            and row["bar_close_at"] in displayed_formation_closes
            and row["bar_close_at"] <= trace.knowledge_cutoff
        ]
        candidates = [
            _plain(row)
            for row in trace.candidate_rows
            if row.get("timeframe") == timeframe
            and isinstance(row.get("cutoff"), datetime)
            and window_start <= row["cutoff"] <= trace.knowledge_cutoff
        ]
        evidence_candidates = candidates
        kernel_ids = sorted({str(row["kernel_id"]) for row in evidence_formation_rows if row.get("kernel_id")})
        exposed_cutoffs = sorted(
            {
                row["bar_close_at"]
                for row in (*formation_candles_raw, *lifecycle_candles_raw)
                if isinstance(row.get("bar_close_at"), datetime)
            }
        )
        relevant_zone_ids = _project_zone_ids(
            trace,
            timeframe,
            window_start=window_start,
            window_end=trace.knowledge_cutoff,
        )
        zone_records = {
            zone_id: _zone_payload(zone)
            for zone_id, zone in trace.lineage_records.items()
            if zone_id in relevant_zone_ids
        }
        intervals = [
            {
                "zone_id": interval.zone_id,
                "source_timeframe": interval.source_timeframe,
                "lifecycle": interval.lifecycle,
                "entered_at": _plain(interval.entered_at),
                "exited_at": _plain(interval.exited_at),
                "predecessor_id": interval.predecessor_id,
                "successor_id": interval.successor_id,
            }
            for interval in trace.lifecycle_intervals
            if interval.source_timeframe == timeframe
            and interval.zone_id in relevant_zone_ids
            and interval.entered_at <= trace.knowledge_cutoff
            and (interval.exited_at is None or interval.exited_at > window_start)
        ]
        episodes = [
            {
                "zone_id": episode.zone_id,
                "source_timeframe": episode.source_timeframe,
                "episode_number": episode.episode_number,
                "started_at": _plain(episode.started_at),
                "ended_at": _plain(episode.ended_at),
                "close_reason": episode.close_reason,
            }
            for episode in trace.touch_episodes
            if episode.source_timeframe == timeframe
            and episode.zone_id in relevant_zone_ids
            and episode.started_at <= trace.knowledge_cutoff
            and (episode.ended_at is None or episode.ended_at > window_start)
        ]
        transitions = [
            _transition_payload(transition, zone_records)
            for transition in trace.transitions
            if transition.zone_id in relevant_zone_ids
            and transition.event_at >= window_start
            and transition.event_at <= trace.knowledge_cutoff
        ]
        inspection = {
            "as_of": _plain(last.cutoff),
            "analysis_start": _plain(trace.analysis_start),
            "window_start": _plain(window_start),
            "available_cutoffs": [_plain(value) for value in exposed_cutoffs],
            "identity_mode": trace.identity_mode,
            "reconstruction_start": _plain(trace.reconstruction_start),
        }
        panes[timeframe] = {
            "source_timeframe": timeframe,
            "formation": {
                "timeframe": timeframe,
                "candles": formation_candles,
                "candidates": _aggregate_candidates(candidates),
                "kernel_ids": kernel_ids,
            },
            "lifecycle": {
                "timeframe": lifecycle_timeframe,
                "candles": lifecycle_candles,
                "kernel_ids": sorted(
                    {
                        str(row["kernel_id"])
                        for row in raw_lifecycle_rows
                        if row.get("kernel_id")
                    }
                ),
            },
            "inspection": inspection,
        }
        evidence_panes[timeframe] = {
            "source_timeframe": timeframe,
            "formation": {
                "timeframe": timeframe,
                "features": evidence_formation_rows,
                "candidates": evidence_candidates,
            },
            "lifecycle": {
                "timeframe": lifecycle_timeframe,
                "zones": list(zone_records.values()),
                "intervals": intervals,
                "touch_episodes": episodes,
                "transitions": transitions,
                "inspection": {
                    **inspection,
                },
            },
        }
    payload = {
        "schema_version": 2,
        "trace_id": trace.trace_id,
        "replay_id": trace.replay_id,
        "source_manifest_id": trace.source_manifest_id,
        "source_sha256": trace.source_sha256,
        "config_fingerprint": trace.config_fingerprint,
        "identity_mode": trace.identity_mode,
        "market_identity": dict(market_identity),
        "configured_timeframes": list(configured),
        "as_of": _plain(last.cutoff),
        "lineage_identity": {
            "mode": trace.identity_mode,
            "navigation": "predecessor/successor within declared replay identity",
        },
        "panes": panes,
        "attribution": "TradingView Lightweight Charts",
        "display": dict(display),
    }
    payload = {**payload, "payload_id": canonical_hash(payload)}
    evidence = {
        "schema_version": 2,
        "trace_id": trace.trace_id,
        "replay_id": trace.replay_id,
        "source_manifest_id": trace.source_manifest_id,
        "source_sha256": trace.source_sha256,
        "config_fingerprint": trace.config_fingerprint,
        "identity_mode": trace.identity_mode,
        "market_identity": dict(market_identity),
        "configured_timeframes": list(configured),
        "as_of": _plain(last.cutoff),
        "analysis_start": _plain(trace.analysis_start),
        "reconstruction_start": _plain(trace.reconstruction_start),
        "knowledge_cutoff": _plain(trace.knowledge_cutoff),
        "payload_id": payload["payload_id"],
        "panes": evidence_panes,
    }
    evidence = {**evidence, "evidence_id": canonical_hash(evidence)}
    return payload, evidence


def build_viewer_payload(
    trace: SRV2ResearchTrace,
    *,
    display: Mapping[str, Any],
    market_identity: Mapping[str, str],
) -> Mapping[str, Any]:
    """Build the compact, browser-safe chart projection."""

    from ..research_lab.trace import SRV2ResearchTrace

    if not isinstance(trace, SRV2ResearchTrace):
        raise TypeError("trace must be SRV2ResearchTrace")
    return _build_payload_and_evidence(
        trace,
        display=_normalize_display_policy(display),
        market_identity=_identity(market_identity),
    )[0]


def write_viewer_bundle(
    trace: SRV2ResearchTrace,
    path: str | Path,
    *,
    display: Mapping[str, Any],
    market_identity: Mapping[str, str],
) -> Path:
    destination = Path(path)
    if destination.is_symlink():
        raise ValueError("viewer bundle root must not be a symlink")
    if destination.exists() and not destination.is_dir():
        raise ValueError("viewer bundle root must be a directory")
    destination.mkdir(parents=True, exist_ok=True)
    payload, evidence = _build_payload_and_evidence(
        trace,
        display=_normalize_display_policy(display),
        market_identity=_identity(market_identity),
    )
    paths = {name: destination / name for name in REQUIRED_BUNDLE_FILES}
    if any(path_value.exists() for path_value in paths.values()):
        raise FileExistsError("viewer bundle is append-only")
    encoded = {
        "chart_payload.json": canonical_json(payload).encode("utf-8"),
        "evidence_index.json": canonical_json(evidence).encode("utf-8"),
    }
    for name, data in encoded.items():
        if len(data) > MAX_BUNDLE_BYTES:
            raise ValueError(f"{name} exceeds viewer bundle size limit")
    for name, data in encoded.items():
        paths[name].write_bytes(data)
    validate_viewer_bundle(destination)
    return destination


def _validate_identity(value: Any) -> None:
    _identity(value)


def _validate_payload(payload: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "trace_id",
        "replay_id",
        "source_manifest_id",
        "source_sha256",
        "config_fingerprint",
        "identity_mode",
        "market_identity",
        "configured_timeframes",
        "as_of",
        "lineage_identity",
        "panes",
        "attribution",
        "display",
        "payload_id",
    }
    if set(payload) != required:
        raise ValueError("viewer payload schema keys do not match exactly")
    semantic = dict(payload)
    payload_id = semantic.pop("payload_id")
    if payload_id != canonical_hash(semantic):
        raise ValueError("viewer payload ID does not match content")
    if payload["schema_version"] != 2:
        raise ValueError("unsupported viewer payload schema")
    _validate_identity(payload["market_identity"])
    configured_values = payload["configured_timeframes"]
    if not isinstance(configured_values, list) or any(
        not isinstance(timeframe, str) or not timeframe.strip()
        for timeframe in configured_values
    ):
        raise TypeError("viewer configured timeframes must be non-empty strings")
    configured = tuple(configured_values)
    if not configured or len(configured) != len(set(configured)):
        raise ValueError("viewer configured timeframes are invalid")
    if not isinstance(payload["panes"], Mapping) or set(payload["panes"]) != set(configured):
        raise ValueError("viewer payload panes must cover configured timeframes exactly")
    _parse_utc(payload["as_of"], "viewer.as_of")
    if not isinstance(payload["lineage_identity"], Mapping) or payload["lineage_identity"].get("mode") != payload["identity_mode"]:
        raise ValueError("viewer lineage identity mode is inconsistent")
    _normalize_display_policy(payload["display"])
    for timeframe, pane in payload["panes"].items():
        if set(pane) != {"source_timeframe", "formation", "lifecycle", "inspection"} or pane["source_timeframe"] != timeframe:
            raise ValueError("viewer pane identity is invalid")
        formation = pane["formation"]
        lifecycle = pane["lifecycle"]
        if set(formation) != {"timeframe", "candles", "candidates", "kernel_ids"} or formation["timeframe"] != timeframe:
            raise ValueError("viewer formation projection is invalid")
        if set(lifecycle) != {"timeframe", "candles", "kernel_ids"} or lifecycle["timeframe"] != configured[-1]:
            raise ValueError("viewer lifecycle projection is invalid")
        inspection = pane["inspection"]
        if set(inspection) != {"as_of", "analysis_start", "window_start", "available_cutoffs", "identity_mode", "reconstruction_start"}:
            raise ValueError("viewer inspection projection is invalid")
        _validate_chart_rows(formation["candles"], field=f"{timeframe}.formation.candles")
        _validate_chart_rows(lifecycle["candles"], field=f"{timeframe}.lifecycle.candles")
        if not isinstance(formation["candidates"], list) or not isinstance(lifecycle["kernel_ids"], list):
            raise TypeError("viewer compact evidence types are invalid")
        for item in formation["candidates"]:
            if set(item) != {"available_at", "side", "kernel_id", "count"}:
                raise ValueError("viewer candidate aggregate is invalid")
            _parse_utc(item["available_at"], f"{timeframe}.candidate.available_at")
            if isinstance(item["count"], bool) or not isinstance(item["count"], int) or item["count"] <= 0:
                raise ValueError("viewer candidate aggregate count is invalid")
        for name in ("as_of", "analysis_start", "window_start", "reconstruction_start"):
            _parse_utc(inspection[name], f"{timeframe}.inspection.{name}")
        for cutoff in inspection["available_cutoffs"]:
            _parse_utc(cutoff, f"{timeframe}.inspection.available_cutoff")


def _validate_evidence_index(evidence: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "trace_id",
        "replay_id",
        "source_manifest_id",
        "source_sha256",
        "config_fingerprint",
        "identity_mode",
        "market_identity",
        "configured_timeframes",
        "as_of",
        "analysis_start",
        "reconstruction_start",
        "knowledge_cutoff",
        "payload_id",
        "panes",
        "evidence_id",
    }
    if set(evidence) != required:
        raise ValueError("viewer evidence index schema keys do not match exactly")
    semantic = dict(evidence)
    evidence_id = semantic.pop("evidence_id")
    if evidence_id != canonical_hash(semantic):
        raise ValueError("viewer evidence ID does not match content")
    if evidence["schema_version"] != 2 or evidence["payload_id"] != payload["payload_id"]:
        raise ValueError("viewer evidence index identity is inconsistent")
    for name in (
        "trace_id",
        "replay_id",
        "source_manifest_id",
        "source_sha256",
        "config_fingerprint",
        "identity_mode",
        "market_identity",
        "as_of",
    ):
        if evidence[name] != payload[name]:
            raise ValueError(f"viewer evidence {name} is inconsistent")
    _validate_identity(evidence["market_identity"])
    evidence_timeframes = evidence["configured_timeframes"]
    if not isinstance(evidence_timeframes, list) or any(
        not isinstance(timeframe, str) or not timeframe.strip()
        for timeframe in evidence_timeframes
    ):
        raise TypeError("viewer evidence configured timeframes must be non-empty strings")
    if tuple(evidence_timeframes) != tuple(payload["configured_timeframes"]):
        raise ValueError("viewer evidence index timeframe ladder is inconsistent")
    for name in ("as_of", "analysis_start", "reconstruction_start", "knowledge_cutoff"):
        _parse_utc(evidence[name], f"viewer.evidence.{name}")
    if not isinstance(evidence["panes"], Mapping) or set(evidence["panes"]) != set(payload["panes"]):
        raise ValueError("viewer evidence panes are inconsistent")
    total_items = 0
    for timeframe, pane in evidence["panes"].items():
        if set(pane) != {"source_timeframe", "formation", "lifecycle"} or pane["source_timeframe"] != timeframe:
            raise ValueError("viewer evidence pane identity is invalid")
        formation = pane["formation"]
        lifecycle = pane["lifecycle"]
        if set(formation) != {"timeframe", "features", "candidates"} or formation["timeframe"] != timeframe:
            raise ValueError("viewer evidence formation is invalid")
        if set(lifecycle) != {"timeframe", "zones", "intervals", "touch_episodes", "transitions", "inspection"} or lifecycle["timeframe"] != evidence_timeframes[-1]:
            raise ValueError("viewer evidence lifecycle is invalid")
        _validate_chart_rows(formation["features"], field=f"{timeframe}.evidence.formation.features")
        if any(row.get("timeframe") != timeframe for row in formation["features"]):
            raise ValueError("viewer evidence feature timeframe mismatch")
        for zone in lifecycle["zones"]:
            for name in ("center", "lower", "upper"):
                _parse_decimal(zone[name], f"{timeframe}.zone.{name}")
                _parse_decimal(zone["geometry"][name], f"{timeframe}.zone.geometry.{name}")
            for name in ("formed_at", "available_at"):
                _parse_utc(zone[name], f"{timeframe}.zone.{name}")
        for interval in lifecycle["intervals"]:
            _parse_utc(interval["entered_at"], f"{timeframe}.interval.entered_at")
            if interval["exited_at"] is not None:
                _parse_utc(interval["exited_at"], f"{timeframe}.interval.exited_at")
        for episode in lifecycle["touch_episodes"]:
            _parse_utc(episode["started_at"], f"{timeframe}.episode.started_at")
            if episode["ended_at"] is not None:
                _parse_utc(episode["ended_at"], f"{timeframe}.episode.ended_at")
        for transition in lifecycle["transitions"]:
            _parse_utc(transition["event_at"], f"{timeframe}.transition.event_at")
            if transition["event"] not in _TRANSITION_EVENTS:
                raise ValueError("viewer transition event is unsupported")
        total_items += sum(
            len(values)
            for values in (
                formation["features"],
                formation["candidates"],
                lifecycle["zones"],
                lifecycle["intervals"],
                lifecycle["touch_episodes"],
                lifecycle["transitions"],
            )
        )
    if total_items > MAX_BUNDLE_ITEMS:
        raise ValueError("viewer evidence index contains too many evidence items")


def validate_viewer_bundle(path: str | Path) -> Mapping[str, Any]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("viewer bundle root must be a regular directory")
    if {item.name for item in root.iterdir()} != REQUIRED_BUNDLE_FILES:
        raise ValueError("viewer bundle contains an unexpected file")
    payload_path = root / "chart_payload.json"
    evidence_path = root / "evidence_index.json"
    payload = json.loads(_regular_file(payload_path, "chart payload").decode("utf-8"))
    evidence = json.loads(_regular_file(evidence_path, "viewer evidence index").decode("utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(evidence, Mapping):
        raise TypeError("viewer bundle members must be JSON objects")
    _validate_payload(payload)
    _validate_evidence_index(evidence, payload)
    return payload


def select_viewer_payload(payload: Mapping[str, Any], source_timeframe: str) -> Mapping[str, Any]:
    """Return a content-addressed compact payload containing one source pane."""

    _validate_payload(payload)
    configured = tuple(payload.get("configured_timeframes", ()))
    if not isinstance(source_timeframe, str) or source_timeframe not in configured:
        raise ValueError("source_timeframe is not configured")
    selected = dict(payload)
    selected["configured_timeframes"] = [source_timeframe]
    selected["panes"] = {source_timeframe: payload["panes"][source_timeframe]}
    selected.pop("payload_id", None)
    selected["payload_id"] = canonical_hash(selected)
    return selected


def iframe_urls(base_url: str, payload: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Build one isolated URL per configured timeframe in descending order."""

    if not isinstance(base_url, str) or not base_url:
        raise ValueError("base_url must be non-empty")
    return tuple(
        (
            timeframe,
            f"{base_url.rstrip('/')}/?{urlencode({'source_timeframe': timeframe})}",
        )
        for timeframe in payload.get("configured_timeframes", ())
    )


__all__ = [
    "MAX_BUNDLE_BYTES",
    "MAX_BUNDLE_ITEMS",
    "build_viewer_payload",
    "iframe_urls",
    "select_viewer_payload",
    "validate_viewer_bundle",
    "write_viewer_bundle",
]
