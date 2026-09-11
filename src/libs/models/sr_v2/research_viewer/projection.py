"""Pure, point-in-time projections for the local SR v2 viewer.

The replay trace is authoritative, while the browser receives only a compact
chart projection.  The server-only evidence index is intentionally bounded to
the display window.  :class:`ProjectionIndex` parses and orders that bounded
evidence once when the server starts; request-time projections then walk the
relevant ordered event streams once instead of scanning every interval for
every zone.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

_NON_TERMINAL_LIFECYCLES = frozenset({"ACTIVE", "TOUCHED", "BREAK_PENDING"})
_TERMINAL_LIFECYCLES = frozenset({"BROKEN", "EXPIRED", "SUPERSEDED"})


def parse_utc(value: Any, field: str) -> datetime:
    """Parse one canonical viewer UTC timestamp."""

    if not isinstance(value, str):
        raise TypeError(f"{field} must be an ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 UTC string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return parsed.astimezone(UTC)


def format_utc(value: datetime) -> str:
    """Return the timestamp form used by the viewer JSON contract."""

    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("viewer timestamps must use UTC")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _time(row: Mapping[str, Any], *names: str) -> datetime | None:
    for name in names:
        value = row.get(name)
        if value is not None:
            return parse_utc(value, name)
    return None


def _projected_zone(
    zone: Mapping[str, Any],
    interval: Mapping[str, Any],
    state: Mapping[str, Any],
    cutoff: datetime,
) -> dict[str, Any]:
    interval_end = _time(interval, "exited_at")
    return {
        "zone_id": str(zone["zone_id"]),
        "source_timeframe": zone.get("source_timeframe"),
        "side": zone.get("side"),
        "center": zone.get("center"),
        "lower": zone.get("lower"),
        "upper": zone.get("upper"),
        "geometry": dict(zone.get("geometry", {})),
        "formed_at": zone.get("formed_at"),
        "available_at": zone.get("available_at"),
        "source_evidence_id": zone.get("source_evidence_id"),
        "kernel_id": zone.get("kernel_id"),
        "kernel_version": zone.get("kernel_version"),
        "source_candidate_key": zone.get("source_candidate_key"),
        "predecessor_id": zone.get("predecessor_id"),
        "successor_id": None,
        "entered_at": interval.get("entered_at"),
        "exited_at": interval.get("exited_at") if interval_end is not None and interval_end <= cutoff else None,
        "lifecycle": state.get("lifecycle"),
        "touch_count": state.get("touch_count", 0),
        "break_pending_count": state.get("break_pending_count", 0),
        "was_overlapping": state.get("was_overlapping", False),
        "last_touch_at": state.get("last_touch_at"),
        "last_transition_at": state.get("last_transition_at"),
    }


def _censor_transition(
    transition: Mapping[str, Any],
    known_zone_ids: set[str],
) -> dict[str, Any]:
    result = dict(transition)
    for name in ("predecessor_id", "successor_id"):
        target = result.get(name)
        if target is not None and target not in known_zone_ids:
            result[name] = None
    return result


def _merge_chart_candles(
    evidence: Mapping[str, Any],
    payload: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """Overlay chart pane candles onto sidecar panes without changing evidence.

    Candle arrays are already required by the chart payload.  Keeping them out
    of the sidecar avoids duplicating the largest rows, while the server index
    still has one authoritative set of exposed cutoffs for causal validation.
    """

    if payload is None:
        return evidence
    evidence_panes = evidence.get("panes")
    payload_panes = payload.get("panes")
    if not isinstance(evidence_panes, Mapping) or not isinstance(payload_panes, Mapping):
        return evidence
    merged = dict(evidence)
    panes: dict[str, Mapping[str, Any]] = {}
    for timeframe, source_pane in evidence_panes.items():
        if not isinstance(source_pane, Mapping):
            panes[timeframe] = source_pane
            continue
        pane = dict(source_pane)
        payload_pane = payload_panes.get(timeframe)
        if isinstance(payload_pane, Mapping):
            for group_name in ("formation", "lifecycle"):
                group = pane.get(group_name)
                payload_group = payload_pane.get(group_name)
                if not isinstance(group, Mapping):
                    continue
                group_copy = dict(group)
                if "candles" not in group_copy and isinstance(payload_group, Mapping):
                    group_copy["candles"] = list(payload_group.get("candles", ()))
                pane[group_name] = group_copy
        panes[timeframe] = pane
    merged["panes"] = panes
    return merged


class _TimeframeProjectionIndex:
    """Parsed ordered evidence for one source timeframe."""

    def __init__(self, timeframe: str, pane: Mapping[str, Any]):
        self.timeframe = timeframe
        self.pane = pane
        self.formation = pane.get("formation", {})
        self.lifecycle = pane.get("lifecycle", {})

        self._candle_by_close: dict[datetime, Mapping[str, Any]] = {}
        for group in (self.formation, self.lifecycle):
            for row in group.get("candles", ()):
                if isinstance(row, Mapping):
                    close = _time(row, "bar_close_at")
                    if close is not None:
                        self._candle_by_close.setdefault(close, row)
        self.cutoffs = tuple(sorted(self._candle_by_close))
        if not self.cutoffs:
            self.cutoffs = tuple(
                sorted(
                    parse_utc(value, "exposed_cutoff")
                    for value in self.lifecycle.get("inspection", {}).get("available_cutoffs", ())
                )
            )
        self._cutoff_set = frozenset(self.cutoffs)

        features: dict[datetime, list[Mapping[str, Any]]] = {}
        for row in self.formation.get("features", ()):
            if not isinstance(row, Mapping):
                continue
            close = _time(row, "bar_close_at")
            if close is not None:
                features.setdefault(close, []).append(row)
        self._features_by_close = {
            close: tuple(rows) for close, rows in features.items()
        }

        candidate_rows = self.formation.get("candidates", ())
        candidates: dict[datetime, list[tuple[int, Mapping[str, Any]]]] = {}
        untimed_candidates: list[tuple[int, Mapping[str, Any]]] = []
        candidates_by_source: dict[Any, list[tuple[int, Mapping[str, Any]]]] = {}
        for ordinal, row in enumerate(candidate_rows):
            if not isinstance(row, Mapping):
                continue
            available = _time(row, "available_at", "formed_at", "cutoff")
            entry = (ordinal, row)
            if available is None:
                untimed_candidates.append(entry)
            else:
                candidates.setdefault(available, []).append(entry)
            source_evidence_id = row.get("source_evidence_id")
            candidates_by_source.setdefault(source_evidence_id, []).append(entry)
        self._candidates_by_time = {key: tuple(value) for key, value in candidates.items()}
        self._untimed_candidates = tuple(untimed_candidates)
        self._candidates_by_source = {
            key: tuple(value) for key, value in candidates_by_source.items()
        }

        self._zones_by_id: dict[str, Mapping[str, Any]] = {}
        self._zone_order: list[str] = []
        availability: list[tuple[datetime, int, str]] = []
        for ordinal, zone in enumerate(self.lifecycle.get("zones", ())):
            if not isinstance(zone, Mapping):
                continue
            zone_id = str(zone["zone_id"])
            if zone_id not in self._zones_by_id:
                self._zones_by_id[zone_id] = zone
                self._zone_order.append(zone_id)
            available_at = _time(zone, "available_at", "formed_at")
            if available_at is not None:
                availability.append((available_at, ordinal, zone_id))
        availability.sort(key=lambda item: (item[0], item[1]))
        self._availability_times = tuple(item[0] for item in availability)
        self._availability_ids = tuple(item[2] for item in availability)

        self._intervals_by_zone: dict[str, list[tuple[datetime, datetime | None, int, Mapping[str, Any]]]] = {}
        interval_events: list[tuple[datetime, int, int, str, Mapping[str, Any]]] = []
        self._interval_by_sequence: dict[int, tuple[str, Mapping[str, Any]]] = {}
        for sequence, interval in enumerate(self.lifecycle.get("intervals", ())):
            if not isinstance(interval, Mapping):
                continue
            entered = _time(interval, "entered_at")
            if entered is None:
                continue
            exited = _time(interval, "exited_at")
            zone_id = str(interval.get("zone_id"))
            entry = (entered, exited, sequence, interval)
            self._intervals_by_zone.setdefault(zone_id, []).append(entry)
            self._interval_by_sequence[sequence] = (zone_id, interval)
            if interval.get("lifecycle") in _NON_TERMINAL_LIFECYCLES:
                # End events sort before start events at one cutoff.  This is
                # the explicit half-open [entered_at, exited_at) rule.
                if exited is None or exited > entered:
                    interval_events.append((entered, 1, sequence, zone_id, interval))
                if exited is not None and exited > entered:
                    interval_events.append((exited, 0, sequence, zone_id, interval))
        self._interval_events = tuple(sorted(interval_events, key=lambda item: (item[0], item[1], item[2])))

        self._episodes_by_zone: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
        episode_events: list[tuple[datetime, int, int, str, Mapping[str, Any]]] = []
        for sequence, episode in enumerate(self.lifecycle.get("touch_episodes", ())):
            if not isinstance(episode, Mapping):
                continue
            started = _time(episode, "started_at")
            if started is None:
                continue
            ended = _time(episode, "ended_at")
            zone_id = str(episode.get("zone_id"))
            self._episodes_by_zone.setdefault(zone_id, []).append((sequence, episode))
            if ended is None or ended > started:
                episode_events.append((started, 1, sequence, zone_id, episode))
            if ended is not None and ended > started:
                episode_events.append((ended, 0, sequence, zone_id, episode))
        self._episode_events = tuple(sorted(episode_events, key=lambda item: (item[0], item[1], item[2])))

        ordered_transitions: list[tuple[datetime, int, int, Mapping[str, Any]]] = []
        transitions_by_time: dict[datetime, list[tuple[int, Mapping[str, Any]]]] = {}
        transitions_by_zone: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
        for sequence, transition in enumerate(self.lifecycle.get("transitions", ())):
            if not isinstance(transition, Mapping):
                continue
            event_at = _time(transition, "event_at")
            if event_at is None:
                continue
            ordinal = int(transition.get("ordinal", 0))
            ordered_transitions.append((event_at, ordinal, sequence, transition))
            transitions_by_time.setdefault(event_at, []).append((sequence, transition))
            transitions_by_zone.setdefault(str(transition.get("zone_id")), []).append((sequence, transition))
        self._ordered_transitions = tuple(
            sorted(ordered_transitions, key=lambda item: (item[0], item[1], item[2]))
        )
        self._transitions_by_time = {
            key: tuple(value) for key, value in transitions_by_time.items()
        }
        self._transitions_by_zone = {
            key: tuple(value) for key, value in transitions_by_zone.items()
        }
        terminal_by_zone: dict[str, list[tuple[datetime, int, int, Mapping[str, Any]]]] = {}
        for event_at, ordinal, sequence, transition in self._ordered_transitions:
            if (
                transition.get("event") in _TERMINAL_LIFECYCLES
                or transition.get("after_lifecycle") in _TERMINAL_LIFECYCLES
            ):
                terminal_by_zone.setdefault(str(transition.get("zone_id")), []).append(
                    (event_at, ordinal, sequence, transition)
                )
        self._terminal_by_zone = {
            key: tuple(value) for key, value in terminal_by_zone.items()
        }

    def _validate_cutoff(self, cutoff: str | datetime, as_of: datetime) -> datetime:
        parsed = cutoff if isinstance(cutoff, datetime) else parse_utc(cutoff, "cutoff")
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("cutoff must be UTC")
        parsed = parsed.astimezone(UTC)
        if parsed > as_of:
            raise ValueError("cutoff cannot follow the payload as-of")
        if parsed not in self._cutoff_set:
            raise ValueError("cutoff must be an exposed formation or lifecycle candle close")
        return parsed

    def known_zone_ids(self, cutoff: datetime) -> set[str]:
        end = bisect_right(self._availability_times, cutoff)
        return set(self._availability_ids[:end])

    def _states_at(self, cutoff: datetime) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for event_at, _ordinal, _sequence, transition in self._ordered_transitions:
            if event_at > cutoff:
                break
            zone_id = str(transition["zone_id"])
            event = dict(states.get(zone_id, {}))
            event.update(
                {
                    "lifecycle": transition.get("after_lifecycle"),
                    "touch_count": transition.get("after_touch_count", event.get("touch_count", 0)),
                    "break_pending_count": transition.get(
                        "after_break_pending_count",
                        event.get("break_pending_count", 0),
                    ),
                    "was_overlapping": transition.get(
                        "after_overlapping",
                        event.get("was_overlapping", False),
                    ),
                    "last_transition_at": transition.get("event_at"),
                }
            )
            if transition.get("event") == "TOUCH_STARTED":
                event["last_touch_at"] = transition.get("event_at")
            states[zone_id] = event
        return states

    def _active_intervals(self, cutoff: datetime) -> dict[str, Mapping[str, Any]]:
        active_sequences: set[int] = set()
        for event_at, priority, sequence, _zone_id, _interval in self._interval_events:
            if event_at > cutoff:
                break
            if priority == 0:
                active_sequences.discard(sequence)
            else:
                active_sequences.add(sequence)

        selected: dict[str, tuple[datetime, int, Mapping[str, Any]]] = {}
        for sequence in active_sequences:
            zone_id, interval = self._interval_by_sequence[sequence]
            entered = _time(interval, "entered_at")
            if entered is None:
                continue
            current = selected.get(zone_id)
            if current is None or (entered, sequence) >= (current[0], current[1]):
                selected[zone_id] = (entered, sequence, interval)
        return {zone_id: interval for zone_id, (_entered, _sequence, interval) in selected.items()}

    def _active_episode_sequences(self, cutoff: datetime) -> set[int]:
        active: set[int] = set()
        for event_at, priority, sequence, _zone_id, _episode in self._episode_events:
            if event_at > cutoff:
                break
            if priority == 0:
                active.discard(sequence)
            else:
                active.add(sequence)
        return active

    def _project_inspection(self, evidence: Mapping[str, Any], cutoff: datetime) -> Mapping[str, Any]:
        known_zone_ids = self.known_zone_ids(cutoff)
        features = [dict(row) for row in self._features_by_close.get(cutoff, ())]

        candidate_entries = list(self._candidates_by_time.get(cutoff, ()))
        candidate_entries.extend(self._untimed_candidates)
        candidates = [dict(row) for _sequence, row in sorted(candidate_entries, key=lambda item: item[0])]

        states = self._states_at(cutoff)
        active_intervals = self._active_intervals(cutoff)
        active_zones: list[dict[str, Any]] = []
        for zone_id in self._zone_order:
            if zone_id not in known_zone_ids:
                continue
            interval = active_intervals.get(zone_id)
            if interval is None:
                continue
            zone = self._zones_by_id[zone_id]
            state = dict(states.get(zone_id, {}))
            state["lifecycle"] = interval.get("lifecycle", state.get("lifecycle"))
            active_zones.append(_projected_zone(zone, interval, state, cutoff))

        active_episode_sequences = self._active_episode_sequences(cutoff)
        touch_episodes: list[dict[str, Any]] = []
        for zone_id in self._zone_order:
            if zone_id not in known_zone_ids:
                continue
            for sequence, episode in self._episodes_by_zone.get(zone_id, ()):
                if sequence not in active_episode_sequences:
                    continue
                value = dict(episode)
                ended = _time(episode, "ended_at")
                if ended is None or ended > cutoff:
                    value["ended_at"] = None
                    value["close_reason"] = None
                touch_episodes.append(value)

        exact_transitions = [
            _censor_transition(transition, known_zone_ids)
            for _sequence, transition in sorted(
                self._transitions_by_time.get(cutoff, ()), key=lambda item: item[0]
            )
            if str(transition.get("zone_id")) in known_zone_ids
        ]
        candle_row = self._candle_by_close.get(cutoff)
        candle = None if candle_row is None else dict(candle_row)
        lifecycle_timeframe = self.lifecycle["timeframe"]
        return {
            "schema_version": 2,
            "trace_id": evidence["trace_id"],
            "source_timeframe": self.timeframe,
            "lifecycle_timeframe": lifecycle_timeframe,
            "cutoff": format_utc(cutoff),
            "candle": candle,
            "features": features,
            "new_candidates": candidates,
            "active_zones": active_zones,
            "touch_episodes": touch_episodes,
            "transitions": exact_transitions,
            "identity_mode": evidence["identity_mode"],
        }

    def _known_successor(
        self,
        zone_id: str,
        known_zone_ids: set[str],
        cutoff: datetime,
    ) -> str | None:
        values = [
            transition.get("successor_id")
            for _sequence, transition in self._transitions_by_zone.get(zone_id, ())
            if transition.get("successor_id") in known_zone_ids
            and (_time(transition, "event_at") or cutoff) <= cutoff
        ]
        return values[-1] if values else None

    def _immutable_zone_projection(
        self,
        zone: Mapping[str, Any],
        known_zone_ids: set[str],
        cutoff: datetime,
    ) -> dict[str, Any]:
        immutable = {
            key: zone.get(key)
            for key in (
                "zone_id",
                "source_timeframe",
                "side",
                "center",
                "lower",
                "upper",
                "geometry",
                "formed_at",
                "available_at",
                "source_evidence_id",
                "kernel_id",
                "kernel_version",
                "source_candidate_key",
                "predecessor_id",
            )
        }
        if immutable["predecessor_id"] not in known_zone_ids:
            immutable["predecessor_id"] = None
        immutable["successor_id"] = self._known_successor(
            str(zone["zone_id"]),
            known_zone_ids,
            cutoff,
        )
        return immutable

    def _first_terminal_at(self, zone_id: str, cutoff: datetime) -> datetime | None:
        for event_at, _ordinal, _sequence, _transition in self._terminal_by_zone.get(zone_id, ()):
            if event_at > cutoff:
                break
            return event_at
        return None

    def _project_zone_detail(
        self,
        evidence: Mapping[str, Any],
        zone_id: str,
        cutoff: datetime,
    ) -> Mapping[str, Any]:
        zone = self._zones_by_id.get(zone_id)
        if zone is None:
            raise ValueError("zone_id is not in the selected source timeframe")
        known_zone_ids = self.known_zone_ids(cutoff)
        available_at = _time(zone, "available_at", "formed_at")
        if available_at is None or available_at > cutoff:
            raise ValueError("zone_id is not known at the requested cutoff")

        states = self._states_at(cutoff)
        state = dict(states.get(zone_id, {}))
        immutable = self._immutable_zone_projection(zone, known_zone_ids, cutoff)

        history_intervals: list[dict[str, Any]] = []
        for _entered, _exited, _sequence, item in self._intervals_by_zone.get(zone_id, ()):
            entered = _time(item, "entered_at")
            if entered is None or entered > cutoff:
                continue
            value = dict(item)
            exited = _time(item, "exited_at")
            if exited is None or exited > cutoff:
                value["exited_at"] = None
            history_intervals.append(value)

        history_episodes: list[dict[str, Any]] = []
        for _sequence, item in self._episodes_by_zone.get(zone_id, ()):
            started = _time(item, "started_at")
            if started is None or started > cutoff:
                continue
            value = dict(item)
            ended = _time(item, "ended_at")
            if ended is None or ended > cutoff:
                value["ended_at"] = None
                value["close_reason"] = None
            history_episodes.append(value)

        history_transitions = [
            _censor_transition(item, known_zone_ids)
            for _sequence, item in self._transitions_by_zone.get(zone_id, ())
            if (_time(item, "event_at") or cutoff) <= cutoff
        ]
        source_candidates = [
            dict(item)
            for _sequence, item in self._candidates_by_source.get(zone.get("source_evidence_id"), ())
            if (_time(item, "available_at", "formed_at", "cutoff") or cutoff) <= cutoff
        ]
        return {
            "schema_version": 2,
            "trace_id": evidence["trace_id"],
            "source_timeframe": self.timeframe,
            "lifecycle_timeframe": self.lifecycle["timeframe"],
            "cutoff": format_utc(cutoff),
            "zone": immutable,
            "state": state,
            "lifecycle_intervals": history_intervals,
            "touch_episodes": history_episodes,
            "transitions": history_transitions,
            "source_candidates": source_candidates,
            "navigation": {
                "predecessor_id": immutable["predecessor_id"],
                "successor_id": immutable["successor_id"],
                "predecessor_known": immutable["predecessor_id"] is not None,
                "successor_known": immutable["successor_id"] is not None,
            },
            "identity_mode": evidence["identity_mode"],
        }

    def _project_lineage_history(
        self,
        evidence: Mapping[str, Any],
        cutoff: datetime,
    ) -> Mapping[str, Any]:
        inspection = self.lifecycle.get("inspection", {})
        window_start = _time(inspection, "window_start")
        if window_start is None:
            window_start = self.cutoffs[0] if self.cutoffs else cutoff
        known_zone_ids = self.known_zone_ids(cutoff)
        interval_rows: list[tuple[datetime, str, int, dict[str, Any]]] = []
        zone_ids: set[str] = set()
        for zone_id in self._zone_order:
            if zone_id not in known_zone_ids:
                continue
            zone = self._zones_by_id[zone_id]
            available_at = _time(zone, "available_at", "formed_at")
            if available_at is None or available_at > cutoff:
                continue
            terminal_at = self._first_terminal_at(zone_id, cutoff)
            for entered, exited, sequence, interval in self._intervals_by_zone.get(zone_id, ()):
                lifecycle = interval.get("lifecycle")
                if lifecycle not in _NON_TERMINAL_LIFECYCLES or entered > cutoff:
                    continue
                segment_start = max(available_at, entered)
                if segment_start > cutoff:
                    continue
                known_end = exited
                if terminal_at is not None and (known_end is None or terminal_at < known_end):
                    known_end = terminal_at
                if known_end is not None and known_end <= segment_start:
                    continue
                visible_end = cutoff if known_end is None or known_end > cutoff else known_end
                if visible_end <= window_start and segment_start < window_start:
                    continue
                if visible_end == segment_start and segment_start < cutoff:
                    continue
                exposed_exit = known_end if known_end is not None and known_end <= cutoff else None
                row = {
                    "zone_id": zone_id,
                    "source_timeframe": self.timeframe,
                    "lifecycle": lifecycle,
                    "entered_at": format_utc(entered),
                    "exited_at": None if exposed_exit is None else format_utc(exposed_exit),
                }
                interval_rows.append((entered, zone_id, sequence, row))
                zone_ids.add(zone_id)

        interval_rows.sort(key=lambda item: (item[0], item[1], item[2]))
        zones = [
            self._immutable_zone_projection(self._zones_by_id[zone_id], known_zone_ids, cutoff)
            for zone_id in sorted(
                zone_ids,
                key=lambda item: (
                    _time(self._zones_by_id[item], "available_at", "formed_at") or cutoff,
                    item,
                ),
            )
        ]
        return {
            "schema_version": 2,
            "trace_id": evidence["trace_id"],
            "source_timeframe": self.timeframe,
            "lifecycle_timeframe": self.lifecycle["timeframe"],
            "cutoff": format_utc(cutoff),
            "window_start": format_utc(window_start),
            "zones": zones,
            "lifecycle_intervals": [row for _entered, _zone_id, _sequence, row in interval_rows],
            "identity_mode": evidence["identity_mode"],
        }


class ProjectionIndex:
    """Reusable causal projection index for a validated viewer artifact."""

    def __init__(
        self,
        evidence: Mapping[str, Any],
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.evidence = _merge_chart_candles(evidence, payload)
        configured = tuple(self.evidence.get("configured_timeframes", ()))
        self._as_of = parse_utc(self.evidence["as_of"], "evidence.as_of")
        panes = self.evidence.get("panes")
        if not isinstance(panes, Mapping):
            raise TypeError("viewer evidence panes must be an object")
        self.timeframes = configured
        self._panes = {
            timeframe: _TimeframeProjectionIndex(timeframe, panes[timeframe])
            for timeframe in configured
            if isinstance(panes.get(timeframe), Mapping)
        }

    def _pane_index(self, timeframe: str) -> _TimeframeProjectionIndex:
        if timeframe not in self.timeframes:
            raise ValueError("source_timeframe is not configured")
        try:
            return self._panes[timeframe]
        except KeyError as exc:
            raise TypeError("selected source timeframe is unavailable") from exc

    def project_inspection(self, timeframe: str, cutoff: str | datetime) -> Mapping[str, Any]:
        pane = self._pane_index(timeframe)
        parsed = pane._validate_cutoff(cutoff, self._as_of)
        return pane._project_inspection(self.evidence, parsed)

    def project_zone_detail(
        self,
        timeframe: str,
        zone_id: str,
        cutoff: str | datetime,
    ) -> Mapping[str, Any]:
        if not isinstance(zone_id, str) or not zone_id.strip():
            raise ValueError("zone_id must be non-empty")
        pane = self._pane_index(timeframe)
        parsed = pane._validate_cutoff(cutoff, self._as_of)
        return pane._project_zone_detail(self.evidence, zone_id, parsed)

    def project_lineage_history(self, timeframe: str, cutoff: str | datetime) -> Mapping[str, Any]:
        pane = self._pane_index(timeframe)
        parsed = pane._validate_cutoff(cutoff, self._as_of)
        return pane._project_lineage_history(self.evidence, parsed)


__all__ = [
    "ProjectionIndex",
    "format_utc",
    "parse_utc",
]
