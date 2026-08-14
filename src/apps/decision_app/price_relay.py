"""Bounded canonical price publication for the D9D risk-continuity path.

The relay is deliberately a poll-owned component.  It has no task, queue,
database table, or model dependency: one accepted canonical series bar is
either published under its deterministic close-time ID or remains unresolved.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from apps.decision_app.contracts import PriceRelayPlan, PriceRelayProgress
from apps.decision_app.market_state import (
    MarketSeriesKey,
    TimeframeGrid,
    validate_canonical_bar_geometry,
)
from apps.decision_app.settings import DecisionConfig
from libs.common.stream_keys import price_update_stream_key
from libs.contracts.decision import require_utc
from libs.contracts.schemas import PriceUpdate, valkey_decode, valkey_encode

RelayPublicationOutcome = Literal[
    "PUBLISHED",
    "ALREADY_IDENTICAL",
    "CONFLICT",
    "FAILED",
]


class PriceRelayError(ValueError):
    """Base error for an untrustworthy price-relay contract."""


class PriceRelayTransportError(PriceRelayError):
    """Raised for malformed stream transport evidence."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceRelayPublicationAck:
    """Bounded exact-ID publication evidence for one canonical bar."""

    relay_plan_id: str
    stream_key: str
    stream_entry_id: str
    outcome: RelayPublicationOutcome
    reason: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceRelayResult:
    """Bounded evidence for one relay reconciliation step."""

    relay_plan_id: str
    stream_key: str
    target_market_as_of: datetime | None
    published_market_as_of: datetime | None
    publication_outcome: RelayPublicationOutcome | None
    continuity_status: str
    reason: str | None = None
    backlog_bars: int = 0


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PriceRelayError(f"{field_name} must be non-empty text")
    return value.strip()


def _entry_id(value: object) -> str:
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        normalized = _text(value, "stream_id")
        parts = normalized.split("-")
        if len(parts) != 2 or any(not part.isdigit() for part in parts):
            raise ValueError("stream ID must be <non-negative-ms>-<non-negative-seq>")
        return f"{int(parts[0])}-{int(parts[1])}"
    except (PriceRelayError, TypeError, ValueError) as exc:
        raise PriceRelayTransportError(f"invalid stream entry ID: {exc}") from exc


def _entry_parts(entry: object) -> tuple[str, Mapping[object, object]]:
    if not isinstance(entry, Sequence) or len(entry) != 2:
        raise PriceRelayTransportError("stream entry must be an ID/fields pair")
    entry_id = _entry_id(entry[0])
    fields = entry[1]
    if not isinstance(fields, Mapping):
        raise PriceRelayTransportError("stream entry fields must be a mapping")
    return entry_id, fields


def _bar_ms(value: datetime) -> int:
    return int(require_utc(value, field_name="bar timestamp").timestamp() * 1000)


def price_relay_entry_id(bar: Any) -> str:
    """Return the deterministic completed-bar identity used by Valkey."""

    if not hasattr(bar, "bar_close_at"):
        raise TypeError("bar must expose bar_close_at")
    return f"{_bar_ms(bar.bar_close_at)}-0"


def build_price_update(plan: PriceRelayPlan, bar: Any) -> PriceUpdate:
    """Convert one canonical closed bar to the unchanged risk wire contract."""

    if not isinstance(plan, PriceRelayPlan):
        raise TypeError("plan must be PriceRelayPlan")
    if getattr(bar, "timeframe", None) != plan.timeframe:
        raise PriceRelayError("price bar timeframe does not match relay plan")
    if not getattr(bar, "closed", False):
        raise PriceRelayError("price relay accepts closed canonical bars only")
    opened_at = require_utc(bar.bar_open_at, field_name="bar_open_at")
    closed_at = require_utc(bar.bar_close_at, field_name="bar_close_at")
    if closed_at <= opened_at:
        raise PriceRelayError("price bar close must be after open")
    return PriceUpdate(
        asset=plan.asset,
        timeframe=plan.timeframe,
        timestamp=_bar_ms(opened_at),
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
        volume=float(bar.volume),
    )


def compile_price_relay_plans(config: DecisionConfig) -> tuple[PriceRelayPlan, ...]:
    """Compile one independent plan per enabled canonical relay series."""

    if not isinstance(config, DecisionConfig):
        raise TypeError("config must be DecisionConfig")
    plans: list[PriceRelayPlan] = []
    for asset in config.active_assets:
        relay = asset.price_relay
        if not relay.enabled:
            continue
        instrument = next(
            (
                item
                for item in config.instruments.values()
                if item.manifest_asset == asset.manifest_asset
                and item.instrument_id == asset.instrument_id
            ),
            None,
        )
        if instrument is None:
            raise PriceRelayError(
                f"no canonical instrument for {asset.manifest_asset}/{asset.instrument_id}"
            )
        for timeframe in relay.timeframes:
            if timeframe not in instrument.timeframes:
                raise PriceRelayError(
                    f"relay timeframe {timeframe} is not canonical for {asset.manifest_asset}"
                )
            config.timeframe_grid.duration(timeframe)
            plan_id = (
                f"{asset.decision_asset}:{asset.venue}:"
                f"{asset.instrument_id}:{timeframe}"
            )
            plans.append(
                PriceRelayPlan(
                    relay_plan_id=plan_id,
                    manifest_asset=asset.manifest_asset,
                    asset=asset.decision_asset,
                    venue=asset.venue,
                    instrument_id=asset.instrument_id,
                    timeframe=timeframe,
                    stream_key=price_update_stream_key(
                        asset.decision_asset,
                        timeframe,
                    ),
                    downstream_risk_compatibility={
                        "wire": "PriceUpdate",
                        "timestamp": "bar_open_epoch_ms",
                        "entry_id": "bar_close_epoch_ms-0",
                    },
                )
            )
    return tuple(sorted(plans, key=lambda item: item.relay_plan_id))


class PriceRelayPublisher:
    """Exact-ID PriceUpdate transport, local to the D9D relay."""

    def __init__(
        self,
        client: Any,
        *,
        stream_maxlen: int = 200,
        stream_approximate: bool = True,
    ) -> None:
        if client is None:
            raise TypeError("client is required")
        for name in ("xrange", "xrevrange", "xadd"):
            if not callable(getattr(client, name, None)):
                raise TypeError(f"client must provide {name}()")
        if isinstance(stream_maxlen, bool) or not isinstance(stream_maxlen, int):
            raise TypeError("stream_maxlen must be an integer")
        if stream_maxlen <= 0:
            raise ValueError("stream_maxlen must be positive")
        if not isinstance(stream_approximate, bool):
            raise TypeError("stream_approximate must be bool")
        self._client = client
        self._stream_maxlen = stream_maxlen
        self._stream_approximate = stream_approximate

    async def publish(
        self,
        plan: PriceRelayPlan,
        bar: Any,
    ) -> PriceRelayPublicationAck:
        if not isinstance(plan, PriceRelayPlan):
            raise TypeError("plan must be PriceRelayPlan")
        update = build_price_update(plan, bar)
        required_id = price_relay_entry_id(bar)
        existing = await self._exact_entry(plan.stream_key, required_id)
        if existing is not None:
            return self._ack_for_existing(plan, required_id, update, existing)
        head = await self._stream_head(plan.stream_key)
        if head is not None and _compare_stream_ids(head, required_id) > 0:
            return self._ack(
                plan,
                required_id,
                "CONFLICT",
                "stream head advanced past required explicit ID",
            )
        try:
            returned_id = await self._client.xadd(
                plan.stream_key,
                valkey_encode(update),
                id=required_id,
                maxlen=self._stream_maxlen,
                approximate=self._stream_approximate,
            )
            if _entry_id(returned_id) != required_id:
                return self._ack(
                    plan,
                    required_id,
                    "CONFLICT",
                    "Valkey returned a different explicit stream ID",
                )
            return self._ack(plan, required_id, "PUBLISHED", None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            existing = await self._exact_entry(plan.stream_key, required_id)
            if existing is not None:
                return self._ack_for_existing(plan, required_id, update, existing)
            head = await self._stream_head(plan.stream_key)
            if head is not None and _compare_stream_ids(head, required_id) > 0:
                return self._ack(
                    plan,
                    required_id,
                    "CONFLICT",
                    "stream head advanced past required explicit ID",
                )
            return self._ack(
                plan,
                required_id,
                "FAILED",
                f"ambiguous XADD failure: {exc}",
            )

    async def _exact_entry(
        self,
        stream_key: str,
        required_id: str,
    ) -> tuple[str, Mapping[object, object]] | None:
        raw = await self._client.xrange(stream_key, required_id, required_id)
        if not raw:
            return None
        if not isinstance(raw, Sequence):
            raise PriceRelayTransportError("XRANGE result must be a sequence")
        for entry in raw:
            entry_id, fields = _entry_parts(entry)
            if entry_id == required_id:
                return entry_id, fields
        return None

    async def _stream_head(self, stream_key: str) -> str | None:
        raw = await self._client.xrevrange(stream_key, "+", "-", count=1)
        if not raw:
            return None
        if not isinstance(raw, Sequence):
            raise PriceRelayTransportError("XREVRANGE result must be a sequence")
        return _entry_parts(raw[0])[0]

    def _ack_for_existing(
        self,
        plan: PriceRelayPlan,
        required_id: str,
        update: PriceUpdate,
        entry: tuple[str, Mapping[object, object]],
    ) -> PriceRelayPublicationAck:
        entry_id, fields = entry
        try:
            existing = valkey_decode(dict(fields), PriceUpdate)
            identical = existing == update
        except Exception:  # noqa: BLE001
            identical = False
        if identical:
            return self._ack(plan, entry_id, "ALREADY_IDENTICAL", None)
        return self._ack(
            plan,
            required_id,
            "CONFLICT",
            f"existing entry {entry_id} has a different or undecodable PriceUpdate",
        )

    @staticmethod
    def _ack(
        plan: PriceRelayPlan,
        entry_id: str,
        outcome: RelayPublicationOutcome,
        reason: str | None,
    ) -> PriceRelayPublicationAck:
        return PriceRelayPublicationAck(
            relay_plan_id=plan.relay_plan_id,
            stream_key=plan.stream_key,
            stream_entry_id=entry_id,
            outcome=outcome,
            reason=reason,
        )


class PriceRelay:
    """Poll-owned continuity reconciler for independent canonical price plans."""

    def __init__(
        self,
        *,
        plans: Sequence[PriceRelayPlan],
        stream_client: Any,
        history_repository: Any,
        timeframe_grid: TimeframeGrid,
        warm_cutoffs: Mapping[MarketSeriesKey, datetime | None] | None = None,
        stream_maxlen: int = 200,
        stream_approximate: bool = True,
        batch_size: int = 10,
    ) -> None:
        normalized_plans = tuple(plans)
        if not normalized_plans:
            self._plans = {}
        else:
            self._plans = {plan.relay_plan_id: plan for plan in normalized_plans}
        if len(self._plans) != len(normalized_plans):
            raise ValueError("relay plan IDs must be unique")
        if not callable(getattr(history_repository, "fetch_record_at", None)):
            raise TypeError("history_repository must provide fetch_record_at()")
        if not callable(getattr(history_repository, "fetch_bars", None)):
            raise TypeError("history_repository must provide fetch_bars()")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be TimeframeGrid")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
        ):
            raise ValueError("batch_size must be positive")
        self._plans = dict(sorted(self._plans.items()))
        self._history = history_repository
        self._grid = timeframe_grid
        self._batch_size = batch_size
        self._stream_maxlen = stream_maxlen
        self._publisher = PriceRelayPublisher(
            stream_client,
            stream_maxlen=stream_maxlen,
            stream_approximate=stream_approximate,
        )
        self._warm_cutoffs = dict(warm_cutoffs or {})
        self._progress: dict[str, PriceRelayProgress] = {
            plan_id: PriceRelayProgress(relay_plan_id=plan_id)
            for plan_id in self._plans
        }
        # Input acceptance and downstream price publication are independent
        # progress domains.  Keep the highest accepted target separately from
        # ``latest_market_as_of`` so bounded catch-up continues on idle polls.
        self._pending_targets: dict[str, datetime | None] = {
            plan_id: None for plan_id in self._plans
        }
        # A fresh relay with neither a downstream tail nor a startup cutoff
        # may establish its first baseline from the first valid closed bar.
        # Other UNRESOLVED states are terminal until a fresh generation/manual
        # recovery; do not infer this distinction from a reason string.
        self._bootstrap_allowed: set[str] = set()
        # A canonical input failure is terminal for this relay generation.
        # Keep only the latest bounded evidence per relay so a pre-bootstrap
        # failure cannot be overwritten by the first reconciliation.
        self._input_failures: dict[str, tuple[str, datetime | None]] = {}
        self._bootstrapped = False

    @property
    def plans(self) -> Mapping[str, PriceRelayPlan]:
        return dict(self._plans)

    @property
    def progress(self) -> Mapping[str, PriceRelayProgress]:
        return dict(self._progress)

    @property
    def stream_maxlen(self) -> int:
        return self._stream_maxlen

    async def bootstrap(self) -> Mapping[str, PriceRelayProgress]:
        """Validate downstream tails and establish bounded startup baselines."""

        for plan_id, plan in self._plans.items():
            self._pending_targets[plan_id] = None
            self._bootstrap_allowed.discard(plan_id)
            try:
                raw = await self._publisher._client.xrevrange(
                    plan.stream_key,
                    "+",
                    "-",
                    count=1,
                )
                if not raw:
                    self._set_baseline(plan)
                    continue
                entry_id, fields = _entry_parts(raw[0])
                update = valkey_decode(dict(fields), PriceUpdate)
                bar_open = datetime.fromtimestamp(update.timestamp / 1000, tz=UTC)
                record = await self._history.fetch_record_at(
                    plan_series_key(plan),
                    bar_open,
                )
                if record is not None:
                    validate_canonical_bar_geometry(
                        plan_series_key(plan),
                        record.bar,
                        self._grid,
                    )
                if record is None or build_price_update(plan, record.bar) != update:
                    self._set_progress(
                        plan_id,
                        latest=None,
                        status="UNRESOLVED",
                        reason="downstream tail does not match canonical history",
                    )
                    continue
                expected_id = price_relay_entry_id(record.bar)
                if entry_id != expected_id:
                    self._set_progress(
                        plan_id,
                        latest=record.bar.bar_close_at,
                        status="UNRESOLVED",
                        reason="downstream tail ID is not canonical close-time ID",
                    )
                    continue
                warm = self._warm_cutoffs.get(plan_series_key(plan))
                if warm is None or record.bar.bar_close_at == warm:
                    status = "CONTINUOUS"
                    reason = None
                elif record.bar.bar_close_at < warm:
                    status = "GAP_DETECTED"
                    reason = "downstream tail is behind startup canonical cutoff"
                    self._pending_targets[plan_id] = warm
                else:
                    status = "UNRESOLVED"
                    reason = "downstream tail is ahead of startup canonical cutoff"
                self._set_progress(
                    plan_id,
                    latest=record.bar.bar_close_at,
                    status=status,
                    reason=reason,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._set_progress(
                    plan_id,
                    latest=None,
                    status="UNRESOLVED",
                    reason=f"downstream tail validation failed: {exc}",
                )
        for plan_id in self._input_failures:
            self._apply_input_failure(plan_id)
        self._bootstrapped = True
        return self.progress

    def mark_input_failure(
        self,
        series_key: MarketSeriesKey,
        *,
        reason: str,
        observed_target_market_as_of: datetime | None = None,
    ) -> tuple[str, ...]:
        """Mark relay plans for a failed canonical input series.

        Canonical input failure is different from a transient downstream
        publication failure: the current relay generation must not publish or
        claim continuity until a fresh generation revalidates the source.
        """

        if not isinstance(series_key, MarketSeriesKey):
            raise TypeError("series_key must be MarketSeriesKey")
        normalized_reason = _text(reason, "input failure reason")
        if observed_target_market_as_of is not None:
            require_utc(
                observed_target_market_as_of,
                field_name="observed_target_market_as_of",
            )
        affected: list[str] = []
        for plan_id, plan in self._plans.items():
            if plan_series_key(plan) != series_key:
                continue
            affected.append(plan_id)
            self._input_failures[plan_id] = (
                normalized_reason,
                observed_target_market_as_of,
            )
            self._apply_input_failure(plan_id)
        return tuple(affected)

    def result_snapshot(
        self,
        plan_id: str,
        *,
        previous: PriceRelayResult | None = None,
    ) -> PriceRelayResult:
        """Return final in-memory evidence without reconciling or publishing."""

        plan = self._plans.get(plan_id)
        if plan is None:
            raise KeyError(f"unknown relay plan: {plan_id}")
        progress = self._progress[plan_id]
        target = (
            previous.target_market_as_of
            if previous is not None
            else self._pending_targets.get(plan_id)
        )
        outcome = None if previous is None else previous.publication_outcome
        return self._result(
            plan,
            target,
            progress,
            outcome=outcome,
        )

    def _apply_input_failure(self, plan_id: str) -> None:
        reason, observed_target = self._input_failures[plan_id]
        pending_target = self._pending_targets.get(plan_id)
        if observed_target is not None and (
            pending_target is None or observed_target > pending_target
        ):
            self._pending_targets[plan_id] = observed_target
        self._bootstrap_allowed.discard(plan_id)
        evidence: dict[str, Any] = {"input_failure": True}
        if observed_target is not None:
            evidence["observed_target_market_as_of"] = observed_target
        self._set_progress(
            plan_id,
            latest=self._progress[plan_id].latest_market_as_of,
            status="UNRESOLVED",
            reason=reason,
            evidence=evidence,
        )

    async def reconcile_all(
        self,
        accepted_bars: Mapping[MarketSeriesKey, Any] | None = None,
    ) -> Mapping[str, PriceRelayResult]:
        if not self._bootstrapped:
            await self.bootstrap()
        candidates = accepted_bars or {}
        results: dict[str, PriceRelayResult] = {}
        for plan_id, plan in self._plans.items():
            candidate = candidates.get(plan_series_key(plan))
            results[plan_id] = await self._reconcile_one(plan, candidate)
        return dict(results)

    async def reconcile(
        self,
        plan_id: str,
        bar: Any | None = None,
    ) -> PriceRelayResult:
        if not self._bootstrapped:
            await self.bootstrap()
        plan = self._plans.get(plan_id)
        if plan is None:
            raise KeyError(f"unknown relay plan: {plan_id}")
        return await self._reconcile_one(plan, bar)

    async def _reconcile_one(
        self,
        plan: PriceRelayPlan,
        candidate: Any | None,
    ) -> PriceRelayResult:
        plan_id = plan.relay_plan_id
        current = self._progress[plan_id]
        series_key = plan_series_key(plan)
        if candidate is not None:
            try:
                validate_canonical_bar_geometry(series_key, candidate, self._grid)
            except Exception as exc:  # noqa: BLE001
                return self._unresolved(
                    plan,
                    self._pending_targets.get(plan_id),
                    f"invalid relay bar: {exc}",
                )
            observed_target = candidate.market_as_of
            pending_target = self._pending_targets.get(plan_id)
            if pending_target is None or observed_target > pending_target:
                self._pending_targets[plan_id] = observed_target

        target = self._pending_targets.get(plan_id)
        if current.continuity_status == "UNRESOLVED" and (
            plan_id not in self._bootstrap_allowed
        ):
            return self._result(
                plan, target, current, reason=current.gap_evidence.get("reason")
            )
        if target is None:
            return self._result(plan, None, current)
        if (
            current.latest_market_as_of is not None
            and target <= current.latest_market_as_of
        ):
            self._pending_targets[plan_id] = None
            return self._result(plan, target, current)

        duration = self._grid.duration(plan.timeframe)
        if current.latest_market_as_of is None:
            if candidate is not None:
                bars = [candidate]
            else:
                # A first-candle publication failure is retryable.  The
                # accepted candidate is no longer supplied by the input
                # cursor on the next poll, so recover that exact bar from
                # canonical history using the retained target.
                try:
                    fetched = await self._history.fetch_bars(
                        series_key,
                        start=target - duration,
                        through=target,
                        limit=1,
                    )
                except Exception as exc:  # noqa: BLE001
                    return self._gap(
                        plan,
                        target,
                        f"canonical first-bar retry failed: {exc}",
                        1,
                    )
                bars = list(fetched)
        else:
            # Progress is stored at the previous bar close.  That close is
            # the exact open of the next canonical bar; adding one duration
            # would silently skip the first missing interval.
            next_open = current.latest_market_as_of
            backlog = _interval_count(next_open, target, duration)
            if backlog > self._stream_maxlen:
                return self._unresolved(
                    plan,
                    target,
                    f"relay backlog {backlog} exceeds stream retention {self._stream_maxlen}",
                    backlog=backlog,
                )
            try:
                fetched = await self._history.fetch_bars(
                    plan_series_key(plan),
                    start=next_open,
                    through=target,
                    # The repository's bounded ``limit`` returns the newest
                    # rows in its range.  Fetch the already retention-bounded
                    # range, then publish only the oldest batch below so the
                    # exact next interval can never be skipped.
                    limit=backlog,
                )
            except Exception as exc:  # noqa: BLE001
                return self._gap(
                    plan, target, f"canonical catch-up failed: {exc}", backlog
                )
            by_open = {item.bar_open_at: item for item in fetched}
            if candidate is not None:
                by_open[candidate.bar_open_at] = candidate
            bars = []
            for index in range(min(self._batch_size, backlog)):
                expected_open = next_open + index * duration
                item = by_open.get(expected_open)
                if item is None:
                    return self._unresolved(
                        plan,
                        target,
                        f"canonical catch-up missing {expected_open.isoformat()}",
                        backlog=backlog,
                    )
                bars.append(item)
        if not bars:
            return self._unresolved(plan, target, "no canonical bar available")

        outcome: RelayPublicationOutcome | None = None
        for bar in bars:
            try:
                validate_canonical_bar_geometry(plan_series_key(plan), bar, self._grid)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._unresolved(
                    plan,
                    target,
                    f"invalid canonical catch-up bar: {exc}",
                    backlog=self._remaining_backlog(plan, target),
                )
            try:
                ack = await self._publisher.publish(plan, bar)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return self._gap(
                    plan, target, f"price publication failed: {exc}", len(bars)
                )
            outcome = ack.outcome
            if outcome not in {"PUBLISHED", "ALREADY_IDENTICAL"}:
                if outcome == "FAILED":
                    return self._gap(
                        plan,
                        target,
                        ack.reason or "price publication FAILED",
                        self._remaining_backlog(plan, target),
                        outcome="FAILED",
                    )
                return self._unresolved(
                    plan,
                    target,
                    ack.reason or f"price publication {outcome}",
                    backlog=self._remaining_backlog(plan, target),
                    outcome=outcome,
                )
            self._set_progress(
                plan_id,
                latest=bar.bar_close_at,
                status="GAP_DETECTED",
                reason="bounded canonical catch-up remains",
            )

        latest = self._progress[plan_id].latest_market_as_of
        complete = latest is not None and latest >= target
        if complete:
            self._pending_targets[plan_id] = None
            self._bootstrap_allowed.discard(plan_id)
        self._set_progress(
            plan_id,
            latest=latest,
            status="CONTINUOUS" if complete else "GAP_DETECTED",
            reason=None if complete else "bounded canonical catch-up remains",
        )
        return self._result(plan, target, self._progress[plan_id], outcome=outcome)

    def _set_baseline(self, plan: PriceRelayPlan) -> None:
        warm = self._warm_cutoffs.get(plan_series_key(plan))
        if warm is None:
            self._bootstrap_allowed.add(plan.relay_plan_id)
            self._set_progress(
                plan.relay_plan_id,
                latest=None,
                status="UNRESOLVED",
                reason="no downstream tail or canonical startup cutoff",
            )
        else:
            self._set_progress(
                plan.relay_plan_id,
                latest=warm,
                status="CONTINUOUS",
                reason="startup canonical cutoff baseline; no historical replay",
                evidence={
                    "baseline_source": "startup_canonical_cutoff",
                    "downstream_tail_present": False,
                },
            )
            self._pending_targets[plan.relay_plan_id] = warm

    def _set_progress(
        self,
        plan_id: str,
        *,
        latest: datetime | None,
        status: str,
        reason: str | None,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        normalized_evidence = dict(evidence or {})
        if reason is not None:
            normalized_evidence.setdefault("reason", reason)
        pending_target = self._pending_targets.get(plan_id)
        if pending_target is not None:
            normalized_evidence.setdefault(
                "observed_target_market_as_of", pending_target
            )
            if latest is not None and pending_target > latest:
                plan = self._plans[plan_id]
                try:
                    normalized_evidence.setdefault(
                        "backlog_bars",
                        _interval_count(
                            latest,
                            pending_target,
                            self._grid.duration(plan.timeframe),
                        ),
                    )
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
        self._progress[plan_id] = PriceRelayProgress(
            relay_plan_id=plan_id,
            latest_market_as_of=latest,
            continuity_status=status,  # type: ignore[arg-type]
            gap_evidence=normalized_evidence,
        )

    def _result(
        self,
        plan: PriceRelayPlan,
        target: datetime | None,
        progress: PriceRelayProgress,
        *,
        reason: str | None = None,
        outcome: RelayPublicationOutcome | None = None,
    ) -> PriceRelayResult:
        backlog = self._remaining_backlog(plan, target)
        return PriceRelayResult(
            relay_plan_id=plan.relay_plan_id,
            stream_key=plan.stream_key,
            target_market_as_of=target,
            published_market_as_of=progress.latest_market_as_of,
            publication_outcome=outcome,
            continuity_status=progress.continuity_status,
            reason=reason or progress.gap_evidence.get("reason"),
            backlog_bars=backlog,
        )

    def _gap(
        self,
        plan: PriceRelayPlan,
        target: datetime | None,
        reason: str,
        backlog: int,
        outcome: RelayPublicationOutcome = "FAILED",
    ) -> PriceRelayResult:
        self._set_progress(
            plan.relay_plan_id,
            latest=self._progress[plan.relay_plan_id].latest_market_as_of,
            status="GAP_DETECTED",
            reason=reason,
        )
        remaining = self._remaining_backlog(plan, target)
        if remaining == 0 and backlog > 0:
            remaining = backlog
        result = self._result(
            plan, target, self._progress[plan.relay_plan_id], reason=reason
        )
        return PriceRelayResult(
            relay_plan_id=result.relay_plan_id,
            stream_key=result.stream_key,
            target_market_as_of=result.target_market_as_of,
            published_market_as_of=result.published_market_as_of,
            publication_outcome=outcome,
            continuity_status=result.continuity_status,
            reason=result.reason,
            backlog_bars=remaining,
        )

    def _unresolved(
        self,
        plan: PriceRelayPlan,
        target: datetime | None,
        reason: str,
        *,
        backlog: int = 0,
        outcome: RelayPublicationOutcome | None = None,
    ) -> PriceRelayResult:
        self._bootstrap_allowed.discard(plan.relay_plan_id)
        self._set_progress(
            plan.relay_plan_id,
            latest=self._progress[plan.relay_plan_id].latest_market_as_of,
            status="UNRESOLVED",
            reason=reason,
        )
        remaining = self._remaining_backlog(plan, target)
        if remaining == 0 and backlog > 0:
            remaining = backlog
        return PriceRelayResult(
            relay_plan_id=plan.relay_plan_id,
            stream_key=plan.stream_key,
            target_market_as_of=target,
            published_market_as_of=self._progress[
                plan.relay_plan_id
            ].latest_market_as_of,
            publication_outcome=outcome,
            continuity_status="UNRESOLVED",
            reason=reason,
            backlog_bars=remaining,
        )

    def _remaining_backlog(
        self,
        plan: PriceRelayPlan,
        target: datetime | None,
    ) -> int:
        latest = self._progress[plan.relay_plan_id].latest_market_as_of
        if latest is None or target is None or target <= latest:
            return 0
        try:
            return _interval_count(latest, target, self._grid.duration(plan.timeframe))
        except (TypeError, ValueError, ZeroDivisionError):
            return 0


def plan_series_key(plan: PriceRelayPlan) -> MarketSeriesKey:
    return MarketSeriesKey(
        asset=plan.manifest_asset,
        venue=plan.venue,
        instrument_id=plan.instrument_id,
        timeframe=plan.timeframe,
    )


def _compare_stream_ids(left: object, right: object) -> int:
    left_parts = tuple(int(part) for part in _entry_id(left).split("-"))
    right_parts = tuple(int(part) for part in _entry_id(right).split("-"))
    return (left_parts > right_parts) - (left_parts < right_parts)


def _interval_count(start: datetime, target: datetime, duration: timedelta) -> int:
    if target < start:
        return 0
    seconds = (target - start).total_seconds() / duration.total_seconds()
    if not math.isclose(seconds, round(seconds)):
        raise PriceRelayError("target cutoff is not aligned to relay timeframe")
    # ``start`` is the open of the next bar and ``target`` is the close of
    # the final bar.  Equal spacing therefore yields one bar per duration,
    # without the inclusive ``+1`` used by point-sample ranges.
    return round(seconds)


__all__ = [
    "PriceRelay",
    "PriceRelayError",
    "PriceRelayPublicationAck",
    "PriceRelayPublisher",
    "PriceRelayResult",
    "PriceRelayTransportError",
    "build_price_update",
    "compile_price_relay_plans",
    "plan_series_key",
    "price_relay_entry_id",
]
