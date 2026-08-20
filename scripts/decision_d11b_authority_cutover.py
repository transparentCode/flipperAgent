"""Foreground D11B authority handoff/cutback operator.

This module deliberately exposes the pure identity and boundary helpers used
by certification.  The command itself performs one bounded operation and
exits; it is not a supervisor or a runtime service.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import asyncpg

from apps.decision_app.composition import build_production_composition
from apps.decision_app.data.resolver import compile_data_plan
from apps.decision_app.domain.identity import lane_execution_identity
from apps.decision_app.features.planning import compile_feature_plan
from apps.decision_app.planning.planner import compile_decision_plan
from apps.decision_app.settings import load_decision_config
from apps.decision_app.storage.shadow_progress import (
    LaneEffectProgress,
    LaneEffectProgressRepository,
)
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.signal_authority import (
    TARGET_SIGNAL_ROUTES,
    SignalAuthorityConflict,
    SignalAuthorityStore,
    SignalRouteAuthority,
)
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import FeatureVector


def route_for_lane(lane: Any) -> str:
    return f"{lane.asset}:{lane.decision_timeframe}"


def derive_authoritative_lane_identities(
    config_manager: ConfigManager | None = None,
) -> dict[str, Any]:
    """Derive D11B identities through the same D2-D5 compilation path."""

    manager = config_manager or ConfigManager()
    config = load_decision_config(manager)
    composition = build_production_composition(config)
    plan = compile_decision_plan(composition.plugin_catalog, config.lane_specs())
    identities: dict[str, Any] = {}
    for lane in plan.lanes:
        if lane.authority != "authoritative":
            continue
        feature_plan = compile_feature_plan(
            lane,
            composition.feature_catalog,
            composition.feature_policy,
            config.timeframe_grid,
        )
        data_plan = compile_data_plan(
            lane,
            composition.data_policy,
            composition.data_source_catalog,
        )
        route = route_for_lane(lane)
        if route in identities:
            raise ValueError(f"duplicate authoritative route: {route}")
        identities[route] = lane_execution_identity(lane, feature_plan, data_plan)
    if set(identities) != set(TARGET_SIGNAL_ROUTES):
        raise ValueError(
            "production authoritative routes must exactly match D11B targets: "
            f"{sorted(identities)}"
        )
    return identities


def _parse_cutoffs(values: Mapping[str, object]) -> dict[str, datetime]:
    if set(values) != set(TARGET_SIGNAL_ROUTES):
        raise ValueError("cutoffs must cover exactly the three D11B routes")
    result: dict[str, datetime] = {}
    for route, value in values.items():
        if not isinstance(value, str):
            raise TypeError(f"cutoff for {route} must be an ISO datetime")
        cutoff = datetime.fromisoformat(value)
        if cutoff.tzinfo is None or cutoff.utcoffset() != UTC.utcoffset(cutoff):
            raise ValueError(f"cutoff for {route} must be UTC")
        result[route] = cutoff.astimezone(UTC)
    return result


def timeframe_duration_ms(timeframe: str) -> int:
    """Return the fixed-duration milliseconds used by direct target routes."""

    if not isinstance(timeframe, str) or len(timeframe) < 2:
        raise ValueError("timeframe must be a positive fixed-duration token")
    try:
        count = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError(f"invalid timeframe: {timeframe!r}") from exc
    if count <= 0 or timeframe[-1] not in "smhdw":
        raise ValueError(f"invalid timeframe: {timeframe!r}")
    unit_ms = {
        "s": 1_000,
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
        "w": 604_800_000,
    }[timeframe[-1]]
    return count * unit_ms


def feature_close_cutoff_ms(timestamp_ms: int, timeframe: str) -> int:
    """Convert a legacy bar-open timestamp to its exact close boundary."""

    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
        raise TypeError("feature timestamp must be an integer millisecond value")
    if timestamp_ms < 0:
        raise ValueError("feature timestamp must be non-negative")
    return timestamp_ms + timeframe_duration_ms(timeframe)


def signal_head_preflight(
    stream_head_id: str | None,
    *,
    boundary_ms: int,
    trigger_timeframe: str,
) -> bool:
    """Require the legacy signal head to precede the next Decision ID."""

    if stream_head_id is None:
        return True
    if not isinstance(stream_head_id, str) or not stream_head_id.endswith("-0"):
        raise ValueError("signal stream head must be an explicit numeric stream ID")
    try:
        head_ms = int(stream_head_id[:-2])
    except ValueError as exc:
        raise ValueError("signal stream head is not numeric") from exc
    if head_ms < 0:
        raise ValueError("signal stream head must be non-negative")
    if isinstance(boundary_ms, bool) or not isinstance(boundary_ms, int):
        raise TypeError("boundary_ms must be an integer")
    if boundary_ms < 0:
        raise ValueError("boundary_ms must be non-negative")
    return head_ms < boundary_ms + timeframe_duration_ms(trigger_timeframe)


def validate_group_quiescence(*, pel_count: int, lag: int) -> bool:
    """Return true only when a consumer group is fully drained."""

    if isinstance(pel_count, bool) or not isinstance(pel_count, int):
        raise TypeError("pel_count must be an integer")
    if isinstance(lag, bool) or not isinstance(lag, int):
        raise TypeError("lag must be an integer")
    if pel_count < 0 or lag < 0:
        raise ValueError("consumer-group counts must be non-negative")
    return pel_count == 0 and lag == 0


def market_bar_identity_fingerprint(entry: Mapping[str, object]) -> str:
    """Fingerprint only the stable market-bar identity of a feature vector."""

    payload = {
        "asset": entry.get("asset"),
        "timeframe": entry.get("timeframe"),
        "timestamp": entry.get("timestamp_ms", entry.get("timestamp")),
        "bar_data": entry.get("bar_data"),
    }
    if any(payload[key] is None for key in payload):
        raise ValueError("feature entry is missing market-bar identity fields")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _entry_bar_identity(entry: Mapping[str, object]) -> str | None:
    supplied = entry.get("bar_identity_fingerprint")
    identity_fields = ("asset", "timeframe", "bar_data")
    if all(key in entry for key in identity_fields):
        derived = market_bar_identity_fingerprint(entry)
        if supplied is not None:
            if not isinstance(supplied, str) or not supplied:
                raise TypeError("bar_identity_fingerprint must be non-empty text")
            return derived if supplied == derived else None
        return derived
    if supplied is not None:
        if not isinstance(supplied, str) or not supplied:
            raise TypeError("bar_identity_fingerprint must be non-empty text")
        return supplied
    return None


def cutback_fast_forward_boundary(
    feature_entries: Sequence[Mapping[str, object]],
    *,
    progress_cutoff_ms: int,
    timeframe: str,
) -> dict[str, object]:
    """Select the last retained legacy feature entry owned by Decision.

    The caller supplies entries after the current group position.  The helper
    decodes only the canonical millisecond bar-open field and never deletes or
    acknowledges an entry.
    """

    if isinstance(progress_cutoff_ms, bool) or not isinstance(progress_cutoff_ms, int):
        raise TypeError("progress_cutoff_ms must be an integer")
    if progress_cutoff_ms < 0:
        raise ValueError("progress_cutoff_ms must be non-negative")
    duration_ms = timeframe_duration_ms(timeframe)
    last_id: str | None = None
    next_unread_id: str | None = None
    ordered = True
    previous_stream_id: tuple[int, int] | None = None
    oldest_cutoff_ms: int | None = None
    newest_cutoff_ms: int | None = None
    prepared: list[dict[str, object]] = []
    for entry in feature_entries:
        entry_id = entry.get("id")
        timestamp_ms = entry.get("timestamp_ms")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError("feature entry id must be non-empty text")
        stream_id = _numeric_stream_id(entry_id)
        if previous_stream_id is not None and stream_id <= previous_stream_id:
            ordered = False
        previous_stream_id = stream_id
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
            raise TypeError("feature entry timestamp_ms must be an integer")
        cutoff_ms = feature_close_cutoff_ms(timestamp_ms, timeframe)
        if oldest_cutoff_ms is None:
            oldest_cutoff_ms = cutoff_ms
        newest_cutoff_ms = cutoff_ms
        if prepared and cutoff_ms < int(prepared[-1]["cutoff_ms"]):
            ordered = False
        prepared.append(
            {
                "id": entry_id,
                "cutoff_ms": cutoff_ms,
                "bar_identity_fingerprint": _entry_bar_identity(entry),
            }
        )

    logical_runs: list[dict[str, object]] = []
    for entry in prepared:
        cutoff_ms = int(entry["cutoff_ms"])
        if logical_runs and logical_runs[-1]["cutoff_ms"] == cutoff_ms:
            run = logical_runs[-1]
            run["last_id"] = entry["id"]
            run["entry_count"] = int(run["entry_count"]) + 1
            fingerprints = run["_fingerprints"]
            assert isinstance(fingerprints, list)
            fingerprints.append(entry["bar_identity_fingerprint"])
        else:
            logical_runs.append(
                {
                    "cutoff_ms": cutoff_ms,
                    "first_id": entry["id"],
                    "last_id": entry["id"],
                    "entry_count": 1,
                    "_fingerprints": [entry["bar_identity_fingerprint"]],
                }
            )

    decision_owned_duplicate_runs = 0
    decision_owned_duplicate_entry_count = 0
    post_progress_duplicate_run_count = 0
    post_progress_duplicate_entry_count = 0
    progress_cutoff_present = False
    duplicate_identity_consistent = True
    logical_cutoff_continuity = ordered
    for index, run in enumerate(logical_runs):
        cutoff_ms = int(run["cutoff_ms"])
        entry_count = int(run["entry_count"])
        fingerprints = run.pop("_fingerprints")
        if not isinstance(fingerprints, list):
            duplicate_identity_consistent = False
            fingerprints = []
        non_null_fingerprints = [item for item in fingerprints if item is not None]
        if entry_count > 1 and (
            len(non_null_fingerprints) != entry_count
            or len(set(non_null_fingerprints)) != 1
        ):
            duplicate_identity_consistent = False
        if (
            index
            and cutoff_ms != int(logical_runs[index - 1]["cutoff_ms"]) + duration_ms
        ):
            logical_cutoff_continuity = False
        if cutoff_ms == progress_cutoff_ms:
            progress_cutoff_present = True
            last_id = str(run["last_id"])
        if entry_count > 1:
            if cutoff_ms <= progress_cutoff_ms:
                decision_owned_duplicate_runs += 1
                decision_owned_duplicate_entry_count += entry_count
            else:
                post_progress_duplicate_run_count += 1
                post_progress_duplicate_entry_count += entry_count
        if cutoff_ms > progress_cutoff_ms and next_unread_id is None:
            next_unread_id = str(run["first_id"])

    expected_next_cutoff_ms = progress_cutoff_ms + duration_ms
    first_actual_unread_cutoff_ms = None
    if next_unread_id is not None:
        first_actual_unread_cutoff_ms = next(
            int(run["cutoff_ms"])
            for run in logical_runs
            if run["first_id"] == next_unread_id
        )
    no_legacy_cutoff_skipped = (
        ordered
        and logical_cutoff_continuity
        and duplicate_identity_consistent
        and progress_cutoff_present
        and post_progress_duplicate_run_count == 0
        and (
            first_actual_unread_cutoff_ms is None
            or first_actual_unread_cutoff_ms == expected_next_cutoff_ms
        )
    )
    # Derive the public run fingerprint from the prepared entries so the
    # evidence remains bounded and stable.
    public_runs = []
    for run in logical_runs:
        run_entries = [
            entry
            for entry in prepared
            if int(entry["cutoff_ms"]) == int(run["cutoff_ms"])
        ]
        fingerprints = [entry["bar_identity_fingerprint"] for entry in run_entries]
        public_runs.append(
            {
                **run,
                "bar_identity_fingerprint": (
                    fingerprints[0]
                    if fingerprints and len(set(fingerprints)) == 1
                    else None
                ),
            }
        )
    return {
        "last_id_through_progress": last_id,
        "next_unread_id": next_unread_id,
        "no_legacy_cutoff_skipped": no_legacy_cutoff_skipped,
        "oldest_retained_cutoff_ms": oldest_cutoff_ms,
        "newest_retained_cutoff_ms": newest_cutoff_ms,
        "expected_next_cutoff_ms": expected_next_cutoff_ms,
        "first_actual_unread_cutoff_ms": first_actual_unread_cutoff_ms,
        "logical_runs": public_runs,
        "logical_cutoff_count": len(logical_runs),
        "transport_entry_count": len(prepared),
        "decision_owned_duplicate_runs": decision_owned_duplicate_runs,
        "decision_owned_duplicate_entry_count": decision_owned_duplicate_entry_count,
        "post_progress_duplicate_run_count": post_progress_duplicate_run_count,
        "post_progress_duplicate_entry_count": post_progress_duplicate_entry_count,
        "progress_cutoff_present": progress_cutoff_present,
        "logical_cutoff_continuity": logical_cutoff_continuity,
        "market_bar_duplicate_identity_consistent": duplicate_identity_consistent,
    }


def _numeric_stream_id(value: str) -> tuple[int, int]:
    if not isinstance(value, str) or value.count("-") != 1:
        raise ValueError("stream ID must have millisecond-sequence form")
    first, second = value.split("-", 1)
    try:
        result = (int(first), int(second))
    except ValueError as exc:
        raise ValueError("stream ID must have numeric components") from exc
    if min(result) < 0:
        raise ValueError("stream ID components must be non-negative")
    return result


def _group_value(
    group: Mapping[object, object], name: str, default: object = None
) -> object:
    value = group.get(name, default)
    if value is None:
        value = group.get(name.encode(), default)
    if isinstance(value, bytes):
        return value.decode()
    return value


async def cutback_fast_forward_group(
    client: Any,
    *,
    stream_key: str,
    group_name: str,
    progress_cutoff_ms: int,
    timeframe: str,
) -> dict[str, object]:
    """Perform the real bounded legacy-group SETID cutback operation."""

    groups = await client.xinfo_groups(stream_key)
    group = next(
        (item for item in groups if str(_group_value(item, "name", "")) == group_name),
        None,
    )
    if not isinstance(group, Mapping):
        raise TypeError(f"consumer group is missing: {stream_key}/{group_name}")
    pending = int(_group_value(group, "pending", -1))
    lag = int(_group_value(group, "lag", -1))
    if pending != 0:
        raise RuntimeError(
            f"legacy group has PEL during cutback: {stream_key}/{group_name}"
        )
    last_delivered_id = str(_group_value(group, "last-delivered-id", "0-0"))
    _numeric_stream_id(last_delivered_id)
    raw_entries = await client.xrange(stream_key, last_delivered_id, "+")
    if not raw_entries:
        raise RuntimeError("legacy feature retention cannot prove the group anchor")
    first_raw_id = raw_entries[0][0]
    first_entry_id = (
        first_raw_id.decode() if isinstance(first_raw_id, bytes) else str(first_raw_id)
    )
    if first_entry_id != last_delivered_id:
        raise RuntimeError("legacy feature retention cannot prove the group anchor")
    entries: list[dict[str, object]] = []
    for raw_id, fields in raw_entries:
        entry_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
        vector = valkey_decode(dict(fields), FeatureVector)
        timestamp_ms = vector.timestamp
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, (int, float))
            or not float(timestamp_ms).is_integer()
            or timestamp_ms < 0
        ):
            raise RuntimeError(
                f"legacy feature timestamp is not a non-negative epoch millisecond: {entry_id}"
            )
        entries.append(
            {
                "id": entry_id,
                "timestamp_ms": int(timestamp_ms),
                "asset": vector.asset,
                "timeframe": vector.timeframe,
                "bar_data": dict(vector.bar_data),
                "bar_identity_fingerprint": market_bar_identity_fingerprint(
                    {
                        "asset": vector.asset,
                        "timeframe": vector.timeframe,
                        "timestamp_ms": int(timestamp_ms),
                        "bar_data": dict(vector.bar_data),
                    }
                ),
            }
        )
    selected = cutback_fast_forward_boundary(
        entries,
        progress_cutoff_ms=progress_cutoff_ms,
        timeframe=timeframe,
    )
    if not selected["no_legacy_cutoff_skipped"]:
        raise RuntimeError("legacy feature retention gap crosses the cutback boundary")
    setid = selected["last_id_through_progress"]
    if not isinstance(setid, str):
        raise TypeError("legacy feature retention cannot prove Decision progress")
    await client.xgroup_setid(stream_key, group_name, setid)
    after_groups = await client.xinfo_groups(stream_key)
    after = next(
        (
            item
            for item in after_groups
            if str(_group_value(item, "name", "")) == group_name
        ),
        None,
    )
    if not isinstance(after, Mapping):
        raise TypeError("legacy group disappeared after SETID")
    if int(_group_value(after, "pending", -1)) != 0:
        raise RuntimeError("legacy group acquired PEL during SETID")
    if str(_group_value(after, "last-delivered-id", "")) != str(setid):
        raise RuntimeError("legacy group SETID did not reach selected boundary")
    return {
        **selected,
        "stream_key": stream_key,
        "group_name": group_name,
        "setid": str(setid),
        "before_last_delivered_id": last_delivered_id,
        "before_pending": pending,
        "before_lag": lag,
        "anchor_id": last_delivered_id,
        "anchor_retained": first_entry_id == last_delivered_id,
        "anchor_cutoff_ms": feature_close_cutoff_ms(
            entries[0]["timestamp_ms"], timeframe
        ),
        "entries": entries,
        "after_pending": int(_group_value(after, "pending", -1)),
        "after_lag": int(_group_value(after, "lag", -1)),
    }


async def seed_effect_progress_at_boundaries(
    repository: Any,
    identities: Mapping[str, Any],
    boundaries: Mapping[str, datetime],
) -> dict[str, str]:
    """Seed null effect progress without overwriting completed effects."""

    outcomes: dict[str, str] = {}
    now = datetime.now(UTC)
    for route in TARGET_SIGNAL_ROUTES:
        identity = identities[route]
        boundary = boundaries[route]
        current = await repository.load(identity)
        if current is not None:
            if current.identity != identity:
                raise ValueError(f"effect-progress identity mismatch for {route}")
            if current.last_disposition is not None:
                raise ValueError(
                    f"completed effect already exists for {route}: {current.last_disposition}"
                )
            if current.market_as_of > boundary:
                raise ValueError(
                    f"effect progress is ahead of legacy boundary for {route}"
                )
        progress = LaneEffectProgress.create(
            identity=identity,
            market_as_of=boundary,
            last_disposition=None,
            created_at=now,
            updated_at=now,
        )
        result = await repository.save(progress)
        value = result.value if hasattr(result, "value") else str(result)
        if value not in {"INSERTED", "UPDATED", "IDENTICAL"}:
            raise RuntimeError(f"effect progress seed failed for {route}: {value}")
        outcomes[route] = value
    return outcomes


def _route_timeframe(route: str) -> str:
    if not isinstance(route, str) or route.count(":") != 1:
        raise ValueError(f"invalid target route: {route!r}")
    return route.rsplit(":", 1)[1]


async def _group_snapshot(
    client: Any, stream_key: str, group_name: str
) -> dict[str, object]:
    try:
        groups = await client.xinfo_groups(stream_key)
    except Exception as exc:
        raise SignalAuthorityConflict(
            f"consumer group unavailable: {stream_key}/{group_name}"
        ) from exc
    for group in groups:
        if str(_group_value(group, "name", "")) == group_name:
            return {
                "exists": True,
                "pending": int(_group_value(group, "pending", -1)),
                "lag": int(_group_value(group, "lag", -1)),
                "last_delivered_id": str(
                    _group_value(group, "last-delivered-id", "0-0")
                ),
            }
    raise SignalAuthorityConflict(f"consumer group missing: {stream_key}/{group_name}")


async def _feature_boundaries(client: Any) -> dict[str, int]:
    boundaries: dict[str, int] = {}
    for route in TARGET_SIGNAL_ROUTES:
        group = await _group_snapshot(client, f"features:{route}", "strategy_app_group")
        if not validate_group_quiescence(
            pel_count=int(group["pending"]), lag=int(group["lag"])
        ):
            raise SignalAuthorityConflict(
                f"legacy feature group is not quiescent: {route}"
            )
        last_id = str(group["last_delivered_id"])
        entries = await client.xrange(f"features:{route}", last_id, last_id)
        if not entries:
            raise SignalAuthorityConflict(
                f"last delivered feature entry is missing: {route}/{last_id}"
            )
        feature = valkey_decode(dict(entries[0][1]), FeatureVector)
        timestamp = feature.timestamp
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not float(timestamp).is_integer()
            or timestamp < 0
        ):
            raise SignalAuthorityConflict(f"invalid feature timestamp: {route}")
        boundaries[route] = feature_close_cutoff_ms(
            int(timestamp), _route_timeframe(route)
        )
    return boundaries


async def _stable_feature_boundaries(client: Any) -> dict[str, object]:
    first = await _feature_boundaries(client)
    second = await _feature_boundaries(client)
    if first != second:
        raise SignalAuthorityConflict("legacy feature boundaries are not stable")
    return {"first": first, "second": second, "stable": True, "final": second}


async def _risk_groups(client: Any) -> dict[str, dict[str, object]]:
    result = {
        route: await _group_snapshot(client, f"signals:{route}", "risk_app_group")
        for route in TARGET_SIGNAL_ROUTES
    }
    for route, group in result.items():
        if not validate_group_quiescence(
            pel_count=int(group["pending"]), lag=int(group["lag"])
        ):
            raise SignalAuthorityConflict(f"Risk group is not quiescent: {route}")
    return result


async def _progress_cutoffs(
    repository: LaneEffectProgressRepository,
    identities: Mapping[str, Any],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for route in TARGET_SIGNAL_ROUTES:
        progress = await repository.load(identities[route])
        if progress is None:
            raise SignalAuthorityConflict(f"effect progress is missing: {route}")
        result[route] = int(progress.market_as_of.timestamp() * 1000)
    return result


async def _stable_progress_cutoffs(
    repository: LaneEffectProgressRepository,
    identities: Mapping[str, Any],
) -> dict[str, object]:
    first = await _progress_cutoffs(repository, identities)
    second = await _progress_cutoffs(repository, identities)
    if first != second:
        raise SignalAuthorityConflict("Decision effect progress is not stable")
    return {"first": first, "second": second, "stable": True, "final": second}


async def _signal_heads(client: Any) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for route in TARGET_SIGNAL_ROUTES:
        entries = await client.xrevrange(f"signals:{route}", "+", "-", count=1)
        result[route] = None if not entries else str(entries[0][0])
    return result


async def _seed_recutover_progress(
    repository: LaneEffectProgressRepository,
    identities: Mapping[str, Any],
    boundaries_ms: Mapping[str, int],
) -> None:
    now = datetime.now(UTC)
    for route in TARGET_SIGNAL_ROUTES:
        current = await repository.load(identities[route])
        if current is None:
            raise SignalAuthorityConflict(f"effect progress is missing: {route}")
        boundary = datetime.fromtimestamp(boundaries_ms[route] / 1000, tz=UTC)
        if boundary < current.market_as_of:
            raise SignalAuthorityConflict(
                f"recutover boundary rewinds progress: {route}"
            )
        result = await repository.save(
            LaneEffectProgress.create(
                identity=identities[route],
                market_as_of=boundary,
                last_disposition=None,
                created_at=current.created_at or now,
                updated_at=now,
            )
        )
        if result.value not in {"UPDATED", "IDENTICAL"}:
            raise SignalAuthorityConflict(
                f"recutover progress baseline failed: {route}/{result.value}"
            )


class D11BAuthorityController:
    """One-shot authority controller with no background lifecycle."""

    def __init__(
        self,
        authority_store: SignalAuthorityStore,
        *,
        progress_repository: LaneEffectProgressRepository | None = None,
        identities: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(authority_store, SignalAuthorityStore):
            raise TypeError("authority_store must be SignalAuthorityStore")
        self.authority_store = authority_store
        self.progress_repository = progress_repository
        self.identities = dict(identities or {})
        self.last_observation: dict[str, object] = {}

    async def prepare(self) -> tuple[SignalRouteAuthority, ...]:
        return await self.authority_store.seed_strategy(TARGET_SIGNAL_ROUTES)

    async def status(self) -> tuple[SignalRouteAuthority | None, ...]:
        return tuple(
            [await self.authority_store.read(route) for route in TARGET_SIGNAL_ROUTES]
        )

    async def cutover_to_decision(
        self,
        *,
        expected_epochs: Mapping[str, int] | None = None,
        boundary_ms_by_route: Mapping[str, int] | None = None,
    ) -> tuple[SignalRouteAuthority, ...]:
        repository, identities = self._require_progress_context()
        boundaries_snapshot = await _stable_feature_boundaries(
            self.authority_store.client
        )
        boundaries = boundaries_snapshot["final"]
        risk_groups = await _risk_groups(self.authority_store.client)
        signal_heads = await _signal_heads(self.authority_store.client)
        if (
            boundary_ms_by_route is not None
            and dict(boundary_ms_by_route) != boundaries
        ):
            raise SignalAuthorityConflict(
                "caller boundary annotations do not match post-stop feature groups"
            )
        records = await self.status()
        if any(record is None or record.owner != "strategy" for record in records):
            raise SignalAuthorityConflict(
                "cutover requires all target authority records owned by strategy"
            )
        current_epochs = {record.route: record.epoch for record in records if record}
        if expected_epochs is not None and dict(expected_epochs) != current_epochs:
            raise SignalAuthorityConflict(
                "caller epoch annotations do not match current authority records"
            )
        await seed_effect_progress_at_boundaries(
            repository,
            identities,
            {
                route: datetime.fromtimestamp(value / 1000, tz=UTC)
                for route, value in boundaries.items()
            },
        )
        seeded = await _progress_cutoffs(repository, identities)
        if seeded != boundaries:
            raise SignalAuthorityConflict(
                "effect progress does not match final legacy boundary"
            )
        for route in TARGET_SIGNAL_ROUTES:
            if not signal_head_preflight(
                signal_heads[route],
                boundary_ms=boundaries[route],
                trigger_timeframe=_route_timeframe(route),
            ):
                raise SignalAuthorityConflict(f"signal head preflight failed: {route}")
        self.last_observation = {
            "legacy_boundaries": boundaries_snapshot,
            "risk_groups": risk_groups,
            "signal_heads": signal_heads,
            "effect_progress": seeded,
        }
        return await self.authority_store.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="strategy",
            new_owner="decision",
            expected_epochs=current_epochs,
            boundary_ms_by_route=boundaries,
        )

    async def cutback_to_strategy(
        self,
        *,
        expected_epochs: Mapping[str, int] | None = None,
        boundary_ms_by_route: Mapping[str, int] | None = None,
        progress_cutoff_ms_by_route: Mapping[str, int] | None = None,
        timeframe_by_route: Mapping[str, str] | None = None,
    ) -> tuple[SignalRouteAuthority, ...]:
        """Fast-forward legacy groups before the atomic owner handoff."""

        repository, identities = self._require_progress_context()
        progress_snapshot = await _stable_progress_cutoffs(repository, identities)
        progress = progress_snapshot["final"]
        risk_groups = await _risk_groups(self.authority_store.client)
        if (
            progress_cutoff_ms_by_route is not None
            and dict(progress_cutoff_ms_by_route) != progress
        ):
            raise SignalAuthorityConflict(
                "caller progress annotations do not match stable post-stop progress"
            )
        if boundary_ms_by_route is not None and dict(boundary_ms_by_route) != progress:
            raise SignalAuthorityConflict(
                "caller boundary annotations do not match stable post-stop progress"
            )
        if timeframe_by_route is not None and dict(timeframe_by_route) != {
            route: _route_timeframe(route) for route in TARGET_SIGNAL_ROUTES
        }:
            raise SignalAuthorityConflict(
                "caller timeframes do not match target routes"
            )
        records = await self.status()
        if any(record is None or record.owner != "decision" for record in records):
            raise SignalAuthorityConflict(
                "cutback requires all target authority records owned by decision"
            )
        current_epochs = {record.route: record.epoch for record in records if record}
        if expected_epochs is not None and dict(expected_epochs) != current_epochs:
            raise SignalAuthorityConflict(
                "caller epoch annotations do not match current authority records"
            )
        group_results: dict[str, dict[str, object]] = {}
        for route in TARGET_SIGNAL_ROUTES:
            cutoff = progress[route]
            timeframe = _route_timeframe(route)
            if isinstance(cutoff, bool) or not isinstance(cutoff, int):
                raise TypeError("cutback progress cutoffs must be integer milliseconds")
            result = await cutback_fast_forward_group(
                self.authority_store.client,
                stream_key=f"features:{route}",
                group_name="strategy_app_group",
                progress_cutoff_ms=cutoff,
                timeframe=timeframe,
            )
            if result.get("no_legacy_cutoff_skipped") is not True:
                raise SignalAuthorityConflict(
                    f"legacy feature continuity failed before cutback: {route}"
                )
            group_results[route] = result
        self.last_observation = {
            "decision_progress": progress_snapshot,
            "risk_groups": risk_groups,
            "groups": group_results,
        }
        return await self.authority_store.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="decision",
            new_owner="strategy",
            expected_epochs=current_epochs,
            boundary_ms_by_route=progress,
        )

    async def recutover_to_decision(
        self,
        *,
        expected_epochs: Mapping[str, int] | None = None,
        boundary_ms_by_route: Mapping[str, int] | None = None,
    ) -> tuple[SignalRouteAuthority, ...]:
        """Re-enter Decision ownership at epoch 3 after a real cutback."""

        repository, identities = self._require_progress_context()
        boundaries_snapshot = await _stable_feature_boundaries(
            self.authority_store.client
        )
        boundaries = boundaries_snapshot["final"]
        risk_groups = await _risk_groups(self.authority_store.client)
        signal_heads = await _signal_heads(self.authority_store.client)
        if (
            boundary_ms_by_route is not None
            and dict(boundary_ms_by_route) != boundaries
        ):
            raise SignalAuthorityConflict(
                "caller boundary annotations do not match post-stop feature groups"
            )
        records = await self.status()
        if any(record is None or record.owner != "strategy" for record in records):
            raise SignalAuthorityConflict(
                "recutover requires all target authority records owned by strategy"
            )
        current_epochs = {record.route: record.epoch for record in records if record}
        if expected_epochs is not None and dict(expected_epochs) != current_epochs:
            raise SignalAuthorityConflict(
                "caller epoch annotations do not match current authority records"
            )
        await _seed_recutover_progress(repository, identities, boundaries)
        for route in TARGET_SIGNAL_ROUTES:
            if not signal_head_preflight(
                signal_heads[route],
                boundary_ms=boundaries[route],
                trigger_timeframe=_route_timeframe(route),
            ):
                raise SignalAuthorityConflict(f"signal head preflight failed: {route}")
        self.last_observation = {
            "legacy_boundaries": boundaries_snapshot,
            "risk_groups": risk_groups,
            "signal_heads": signal_heads,
        }
        return await self.authority_store.handoff_many(
            routes=TARGET_SIGNAL_ROUTES,
            expected_owner="strategy",
            new_owner="decision",
            expected_epochs=current_epochs,
            boundary_ms_by_route=boundaries,
        )

    def _require_progress_context(
        self,
    ) -> tuple[LaneEffectProgressRepository, Mapping[str, Any]]:
        if not isinstance(self.progress_repository, LaneEffectProgressRepository):
            raise SignalAuthorityConflict(
                "authority mutation requires a live effect-progress repository"
            )
        if set(self.identities) != set(TARGET_SIGNAL_ROUTES):
            raise SignalAuthorityConflict(
                "authority mutation requires exact authoritative lane identities"
            )
        return self.progress_repository, self.identities


async def _run_operation(operation: str, payload: Mapping[str, object]) -> object:
    manager = ConfigManager()
    client = None
    pool = None
    try:
        client = await create_valkey_client(manager)
        if operation == "prepare":
            return await D11BAuthorityController(SignalAuthorityStore(client)).prepare()
        if operation == "status":
            return await D11BAuthorityController(SignalAuthorityStore(client)).status()
        if operation not in {
            "cutover-to-decision",
            "cutback-to-strategy",
            "recutover-to-decision",
        }:
            raise ValueError(f"unsupported operation: {operation}")
        dsn = os.environ.get("POSTGRES_URI")
        if not dsn:
            raise SignalAuthorityConflict(
                "mutating authority operations require POSTGRES_URI"
            )
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
        identities = derive_authoritative_lane_identities(manager)
        authority = D11BAuthorityController(
            SignalAuthorityStore(client),
            progress_repository=LaneEffectProgressRepository(pool),
            identities=identities,
        )
        epochs = payload.get("expected_epochs")
        boundaries = payload.get("boundary_ms_by_route")
        if operation == "cutover-to-decision":
            return await authority.cutover_to_decision(
                expected_epochs=(
                    {str(k): int(v) for k, v in epochs.items()}
                    if isinstance(epochs, Mapping)
                    else None
                ),
                boundary_ms_by_route=(
                    {str(k): int(v) for k, v in boundaries.items()}
                    if isinstance(boundaries, Mapping)
                    else None
                ),
            )
        if operation == "recutover-to-decision":
            return await authority.recutover_to_decision(
                expected_epochs=(
                    {str(k): int(v) for k, v in epochs.items()}
                    if isinstance(epochs, Mapping)
                    else None
                ),
                boundary_ms_by_route=(
                    {str(k): int(v) for k, v in boundaries.items()}
                    if isinstance(boundaries, Mapping)
                    else None
                ),
            )
        return await authority.cutback_to_strategy(
            expected_epochs=(
                {str(k): int(v) for k, v in epochs.items()}
                if isinstance(epochs, Mapping)
                else None
            ),
            boundary_ms_by_route=(
                {str(k): int(v) for k, v in boundaries.items()}
                if isinstance(boundaries, Mapping)
                else None
            ),
            progress_cutoff_ms_by_route=(
                {
                    str(k): int(v)
                    for k, v in (
                        payload.get("progress_cutoff_ms_by_route") or {}
                    ).items()
                }
                if isinstance(payload.get("progress_cutoff_ms_by_route"), Mapping)
                else None
            ),
            timeframe_by_route=(
                {
                    str(k): str(v)
                    for k, v in (payload.get("timeframe_by_route") or {}).items()
                }
                if isinstance(payload.get("timeframe_by_route"), Mapping)
                else None
            ),
        )
    finally:
        if pool is not None:
            await pool.close()
        if client is not None:
            await client.aclose()
        manager.shutdown()


def _record(value: object) -> object:
    if isinstance(value, SignalRouteAuthority):
        return {
            "schema_version": value.schema_version,
            "route": value.route,
            "owner": value.owner,
            "epoch": value.epoch,
            "boundary_ms": value.boundary_ms,
        }
    if isinstance(value, tuple):
        return [_record(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "prepare",
            "cutover-to-decision",
            "cutback-to-strategy",
            "recutover-to-decision",
            "status",
        ),
    )
    parser.add_argument(
        "--payload",
        help="JSON object containing expected_epochs and boundary_ms_by_route",
    )
    args = parser.parse_args()
    payload = json.loads(args.payload) if args.payload else {}
    if not isinstance(payload, Mapping):
        raise SystemExit("--payload must be a JSON object")
    print(
        json.dumps(
            _record(asyncio.run(_run_operation(args.operation, payload))),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()


__all__ = [
    "D11BAuthorityController",
    "cutback_fast_forward_boundary",
    "cutback_fast_forward_group",
    "derive_authoritative_lane_identities",
    "feature_close_cutoff_ms",
    "main",
    "route_for_lane",
    "seed_effect_progress_at_boundaries",
    "signal_head_preflight",
    "timeframe_duration_ms",
    "validate_group_quiescence",
]
