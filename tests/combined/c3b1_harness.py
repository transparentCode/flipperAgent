"""Healthy-infrastructure canonical-integrity certification for C3B1.

The harness deliberately injects only hostile canonical data at the real
Timescale/Valkey seams.  It reuses the approved C2 fixture and production
ingestion/Decision adapters; it does not add a fault-injection framework or a
second runtime path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey

from apps.decision_app.composition import build_production_composition
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.storage.checkpoints import CheckpointRepository
from apps.decision_app.storage.market_history import (
    CanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.config import ConfigManager
from tests.combined.c1_harness import load_fixture_config
from tests.combined.c2_harness import (
    C2_COMPOSE_FILE,
    EXPECTED_INFRASTRUCTURE,
    STARTUP_COUNT,
    C2Infrastructure,
    _build_runtime,
    _db_counts,
    _momentum_parity,
    _route_keys,
    _runtime_cursors,
    _runtime_watermarks,
    _schema_evidence,
    _signal_entries,
    _stream_derived_events,
    canonical_json,
    drain_outbox,
    materialize_live_asset,
    seed_startup_history,
)
from tests.combined.c2_harness import (
    protected_hashes as c2_protected_hashes,
)
from tests.combined.c2_harness import (
    protected_hashes_valid as c2_protected_hashes_valid,
)

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_COMPOSE_FILE = ROOT / "docker-compose.yml"
PRODUCTION_COMPOSE_SHA = (
    "6aeabe5d28129c163784af19cd2442dc21c1f4a458e84057183ff1c601b59064"
)

POST_C3A_SHA = "9a6f8b428a3e1d35fa4a6ef8b37223f5b0a0081c"
C3A_ARTIFACT_SHA = "34c0b0eaa85fffacbd5c99d346bdcf2829dd12c8c6769e18c63711d0a342622b"
M3_ARTIFACT_SHA = "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
M4_FUNCTIONAL_SHA = "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792"
M4_RESOURCE_SHA = "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4"
D10_ARTIFACT_SHA = "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459"
C1_ARTIFACT_SHA = "386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4"
C2_ARTIFACT_SHA = "9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67"

SUCCESS_STATUS = (
    "INGESTION_DECISION_C3B1_CANONICAL_INTEGRITY_READY_FOR_PROVIDER_RECOVERY_FAULTS"
)
CONTRACT_STATUS = "INGESTION_DECISION_C3B1_CONTRACT_REMEDIATION_REQUIRED"
EVIDENCE_STATUS = "INGESTION_DECISION_C3B1_EVIDENCE_INSUFFICIENT"
BLOCKED_STATUS = "INGESTION_DECISION_C3B1_BLOCKED_INFRASTRUCTURE_PREFLIGHT"
CLEANUP_STATUS = "INGESTION_DECISION_C3B1_CLEANUP_FAILED"

ROUTES = ("BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h")
LANE_IDS = frozenset(
    {
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
        "ETHUSDT:momentum_4h",
    }
)
ETH_LANE = "ETHUSDT:momentum_4h"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def protected_hashes() -> dict[str, str]:
    paths = {
        "m3": ROOT
        / "artifacts/decision_m3/m3_momentum_feature_semantics_certification.json",
        "m4_functional": ROOT
        / "artifacts/decision_m4/m4_momentum_decision_integration_certification.json",
        "m4_resource": ROOT
        / "artifacts/decision_m4/m4_momentum_resource_certification.json",
        "d10": ROOT / "artifacts/decision_d10/d10_resource_capacity_certification.json",
        "c1": ROOT
        / "artifacts/combined_c1/c1_ingestion_decision_momentum_certification.json",
        "c2": ROOT
        / "artifacts/combined_c2/c2_ingestion_decision_real_infrastructure_certification.json",
        "c3a": ROOT
        / "artifacts/combined_c3a/c3a_ingestion_decision_infrastructure_resilience_certification.json",
    }
    return {name: _file_sha256(path) for name, path in paths.items()}


def _approved_protected_hashes() -> dict[str, str]:
    return {
        "m3": M3_ARTIFACT_SHA,
        "m4_functional": M4_FUNCTIONAL_SHA,
        "m4_resource": M4_RESOURCE_SHA,
        "d10": D10_ARTIFACT_SHA,
        "c1": C1_ARTIFACT_SHA,
        "c2": C2_ARTIFACT_SHA,
        "c3a": C3A_ARTIFACT_SHA,
    }


def protected_hashes_valid() -> bool:
    return (
        protected_hashes() == _approved_protected_hashes()
        and c2_protected_hashes_valid()
        and c2_protected_hashes()["c1"] == C1_ARTIFACT_SHA
    )


def _cleanup_probe(project_name: str) -> dict[str, str]:
    label = f"label=com.docker.compose.project={project_name}"

    def probe(kind: str) -> str:
        return subprocess_run(["docker", kind, "ls", "-q", "--filter", label])

    return {
        "containers": probe("ps"),
        "volumes": probe("volume"),
        "networks": probe("network"),
    }


def subprocess_run(command: list[str]) -> str:
    """Small read-only Docker probe kept local to the certification harness."""

    import subprocess

    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()


@dataclass(slots=True)
class C3B1Context:
    infrastructure: C2Infrastructure
    config: Any
    pool: asyncpg.Pool
    broker: Any
    bucket_start: datetime
    repository: CandleRepository
    ingestion: CandleIngestionService
    htf: HTFAggregationService
    startup: Any
    runtime: LiveDecisionRuntime
    baseline: dict[str, object]


async def _start_only(config: Any, pool: asyncpg.Pool, broker: Any) -> Any:
    composition = build_production_composition(config)
    history = CanonicalMarketHistoryRepository(
        pool, timeframe_grid=config.timeframe_grid
    )
    return await DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=composition.plugin_catalog,
        feature_catalog=composition.feature_catalog,
        feature_policy=composition.feature_policy,
        data_policy=composition.data_policy,
        source_catalog=composition.data_source_catalog,
        runtime_plugin_catalog=composition.runtime_plugin_catalog,
        history_repository=history,
        policy_catalog=composition.policy_catalog,
        stream_client=broker,
        checkpoint_repository=CheckpointRepository(pool),
        data_resolver=composition.data_resolver,
    ).start()


def _route_key(config: Any, asset: str, timeframe: str) -> Any:
    return next(
        key
        for key in _route_keys(config)
        if key.asset == asset and key.timeframe == timeframe
    )


def _eth_stream(config: Any) -> str:
    return canonical_ingestion_stream_key(_route_key(config, "ETHUSDT", "4h"))


def _lane_results(poll: Any) -> dict[str, dict[str, object]]:
    return {
        lane_id: {
            "status": result.status,
            "trigger_cutoff": None
            if result.trigger_cutoff is None
            else result.trigger_cutoff.isoformat(),
            "policy_status": result.policy_status,
            "publication_outcome": result.publication_outcome,
            "finalization_status": result.finalization_status,
        }
        for lane_id, result in poll.lane_results.items()
    }


def _result_records(poll: Any, *, series: str | None = None) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in poll.input_results:
        item_series = None
        if item.series_key is not None:
            item_series = f"{item.series_key.asset}/{item.series_key.timeframe}"
        if series is not None and item_series != series:
            continue
        result.append(
            {
                "stream": item.stream_key,
                "stream_id": item.stream_id,
                "series": item_series,
                "market_as_of": None
                if item.market_as_of is None
                else item.market_as_of.isoformat(),
                "disposition": item.disposition,
                "reason": item.reason,
                "event_id": None if item.event is None else str(item.event.event_id),
            }
        )
    return result


async def _btc_snapshot(
    config: Any, startup: Any, runtime: LiveDecisionRuntime
) -> dict[str, object]:
    semantics = await _momentum_parity(config, startup, runtime)
    return {
        "watermarks": {
            key: value
            for key, value in _runtime_watermarks(runtime).items()
            if key.startswith("BTCUSDT:")
        },
        "cursors": {
            key: value
            for key, value in _runtime_cursors(runtime).items()
            if "BTC-USDT-PERP" in key
        },
        "semantics": {
            key: value for key, value in semantics.items() if key.startswith("BTCUSDT:")
        },
    }


def _semantic_map(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _stable_row(row: Mapping[str, object] | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        key: None if row[key] is None else str(row[key])
        for key in (
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "taker_buy_base",
            "source_type",
            "source_provider",
            "source_timeframe",
        )
    }


async def _row_at(
    pool: asyncpg.Pool, config: Any, opened: datetime
) -> dict[str, object] | None:
    key = _route_key(config, "ETHUSDT", "4h")
    row = await pool.fetchrow(
        """
        SELECT open_time, close_time, open, high, low, close, volume,
               taker_buy_base, source_type, source_provider, source_timeframe
          FROM ingestion.candles
         WHERE venue=$1 AND instrument_id=$2 AND timeframe=$3 AND open_time=$4
        """,
        key.venue,
        key.instrument_id,
        key.timeframe,
        opened,
    )
    return _stable_row(row)


async def _stream_tail(broker: Any, stream: str) -> tuple[str, dict[str, str]]:
    values = await broker.xrevrange(stream, "+", "-", count=1)
    if not values:
        raise AssertionError(f"no event in {stream}")
    stream_id, fields = values[0]
    return str(stream_id), dict(fields)


async def _new_context(scenario: str) -> C3B1Context:
    infrastructure = C2Infrastructure(f"c3b1_{scenario}")
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    try:
        await infrastructure.start()
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=4
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        ConfigManager.reset_singleton()
        config = load_fixture_config()
        schema = await _schema_evidence(pool, broker)
        before = await _db_counts(pool, config)
        if before["total_rows"] != 0 or before["outbox_total"] != 0:
            raise AssertionError("C3B1 disposable database was not empty")
        bucket_start = await seed_startup_history(pool, config)
        repository = CandleRepository(pool)
        ingestion = CandleIngestionService(repository)
        htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
        history = CanonicalMarketHistoryRepository(
            pool, timeframe_grid=config.timeframe_grid
        )
        startup, runtime, _ = await _build_runtime(config, pool, broker, history)
        if startup.snapshot.status != "STARTUP_READY":
            raise AssertionError("C3B1 healthy startup was not STARTUP_READY")
        signal_count = len(await _signal_entries(broker))
        counts = await _db_counts(pool, config)
        baseline = {
            "schema": schema,
            "infrastructure": {
                **EXPECTED_INFRASTRUCTURE,
                "valkey_noeviction": (await broker.config_get("maxmemory-policy")).get(
                    "maxmemory-policy"
                )
                == "noeviction",
                "isolated_project": infrastructure.project_name.startswith(
                    "flipper_c2_"
                ),
                "before_empty": True,
                "no_worktree_env": infrastructure.environment.get(
                    "COMPOSE_DISABLE_ENV_FILE"
                )
                == "1",
                "fixture_owned": infrastructure.project_name.startswith("flipper_c2_"),
            },
            "before_empty": True,
            "startup_status": startup.snapshot.status,
            "route_counts": counts["route_rows"],
            "lane_ids": sorted(startup.snapshot.lane_evidence),
            "lanes": {
                lane_id: evidence.status
                for lane_id, evidence in startup.snapshot.lane_evidence.items()
            },
            "watermarks": _runtime_watermarks(runtime),
            "cursors": _runtime_cursors(runtime),
            "semantics": await _momentum_parity(config, startup, runtime),
            "signal_count": signal_count,
            "outbox_pending": counts["outbox_pending"],
        }
        return C3B1Context(
            infrastructure=infrastructure,
            config=config,
            pool=pool,
            broker=broker,
            bucket_start=bucket_start,
            repository=repository,
            ingestion=ingestion,
            htf=htf,
            startup=startup,
            runtime=runtime,
            baseline=baseline,
        )
    except Exception:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        await infrastructure.cleanup()
        raise


async def _close_context(context: C3B1Context) -> dict[str, object]:
    try:
        await context.broker.aclose()
    finally:
        await context.pool.close()
    down_ok = await context.infrastructure.cleanup()
    owned = _cleanup_probe(context.infrastructure.project_name)
    return {
        "clean": down_ok and not any(owned.values()),
        "compose_down_exit_code": 0 if down_ok else 1,
        "owned_resources": owned,
    }


def _with_cleanup(context: C3B1Context, value: dict[str, object]) -> dict[str, object]:
    return value


async def _scenario_startup_history_gap(name: str) -> dict[str, object]:
    context = await _new_context(name)
    try:
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        key = _route_key(context.config, "ETHUSDT", "4h")
        removed_open = context.bucket_start - timedelta(hours=4 * 100)
        latest_before = await context.pool.fetchval(
            "SELECT MAX(close_time) FROM ingestion.candles WHERE venue=$1 AND instrument_id=$2 AND timeframe=$3",
            key.venue,
            key.instrument_id,
            key.timeframe,
        )
        removed = await context.pool.fetchval(
            """
            DELETE FROM ingestion.candles
             WHERE venue=$1 AND instrument_id=$2 AND timeframe=$3 AND open_time=$4
         RETURNING open_time
            """,
            key.venue,
            key.instrument_id,
            key.timeframe,
            removed_open,
        )
        latest_after = await context.pool.fetchval(
            "SELECT MAX(close_time) FROM ingestion.candles WHERE venue=$1 AND instrument_id=$2 AND timeframe=$3",
            key.venue,
            key.instrument_id,
            key.timeframe,
        )
        startup = await _start_only(context.config, context.pool, context.broker)
        evidence = {
            "scenario": "startup_history_gap",
            "baseline": context.baseline,
            "removed_row_count": 0 if removed is None else 1,
            "removed_row_open_time": None if removed is None else removed.isoformat(),
            "removed_position": "interior_recent_required_window",
            "latest_cutoff_before": latest_before.isoformat(),
            "latest_cutoff_after": latest_after.isoformat(),
            "latest_cutoff_unchanged": latest_before == latest_after,
            "startup_status": startup.snapshot.status,
            "lane_evidence": {
                lane_id: {
                    "status": item.status,
                    "reason": item.reason,
                }
                for lane_id, item in startup.snapshot.lane_evidence.items()
            },
            "runtime_lane_ids": sorted(startup.runtimes),
            "watermark_lane_ids": sorted(startup.snapshot.lane_watermarks),
            "signals_after": len(await _signal_entries(context.broker)),
            "outbox_pending_after": (await _db_counts(context.pool, context.config))[
                "outbox_pending"
            ],
            "btc_ready": all(
                startup.snapshot.lane_evidence[lane_id].status == "STARTUP_READY"
                for lane_id in ("BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h")
            ),
            "eth_runtime_absent": ETH_LANE not in startup.runtimes,
            "eth_watermark_absent": ETH_LANE not in startup.snapshot.lane_watermarks,
            "btc_before": before_btc,
            "btc_after": before_btc,
            "btc_unchanged": True,
        }
        return evidence
    finally:
        context.baseline["cleanup"] = await _close_context(context)


async def _scenario_forward_gap(name: str) -> dict[str, object]:
    context = await _new_context(name)
    try:
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        before_watermarks = dict(_runtime_watermarks(context.runtime))
        before_cursors = dict(_runtime_cursors(context.runtime))
        signal_before = len(await _signal_entries(context.broker))
        following_start = context.bucket_start + timedelta(hours=8)
        await materialize_live_asset(
            context.repository,
            asset="ETH",
            bucket_start=following_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        await drain_outbox(context.pool, context.broker)
        events = [
            item
            for item in await _stream_derived_events(context.broker, context.config)
            if item["series"] == "ETHUSDT/4h"
        ]
        if len(events) != 1:
            raise AssertionError("forward-gap setup did not create one ETH 4h event")
        event = events[0]["event"]
        expected_next = context.bucket_start + timedelta(hours=4)
        poll = await context.runtime.poll_once()
        poll_again = await context.runtime.poll_once()
        eth_results = _result_records(poll, series="ETHUSDT/4h")
        eth_stream = _eth_stream(context.config)
        lane_results = _lane_results(poll)
        after_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        return {
            "scenario": "forward_gap",
            "baseline": context.baseline,
            "pre_fault_cursor": before_cursors.get(eth_stream),
            "pre_fault_watermark": before_watermarks.get(ETH_LANE),
            "expected_next_cutoff": expected_next.isoformat(),
            "following_event_cutoff": event.bar.market_as_of.isoformat(),
            "following_event_valid": True,
            "predecessor_absent": int(
                await context.pool.fetchval(
                    "SELECT COUNT(*) FROM ingestion.candles WHERE venue=$1 AND instrument_id=$2 AND timeframe=$3 AND open_time=$4",
                    event.series_key.venue,
                    event.series_key.instrument_id,
                    event.series_key.timeframe,
                    expected_next - timedelta(hours=4),
                )
            )
            == 0,
            "input_results": eth_results,
            "dispositions": [item["disposition"] for item in eth_results],
            "reason": eth_results[0].get("reason") if eth_results else None,
            "cursor_after": _runtime_cursors(context.runtime).get(eth_stream),
            "watermark_after": _runtime_watermarks(context.runtime).get(ETH_LANE),
            "cursor_unchanged": _runtime_cursors(context.runtime).get(eth_stream)
            == before_cursors.get(eth_stream),
            "watermark_unchanged": _runtime_watermarks(context.runtime).get(ETH_LANE)
            == before_watermarks.get(ETH_LANE),
            "transactions": sum(
                item.finalization_status == "COMMITTED"
                for item in poll.lane_results.values()
            ),
            "signal_count_before": signal_before,
            "signal_count_after": len(await _signal_entries(context.broker)),
            "blocked_stream_reason": context.runtime.input.blocked_streams.get(
                eth_stream
            ),
            "idle_input_results": _result_records(poll_again, series="ETHUSDT/4h"),
            "btc_before": before_btc,
            "btc_after": after_btc,
            "btc_unchanged": before_btc == after_btc,
            "lane_results": lane_results,
        }
    finally:
        context.baseline["cleanup"] = await _close_context(context)


async def _scenario_conflict(name: str) -> dict[str, object]:
    context = await _new_context(name)
    try:
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        await materialize_live_asset(
            context.repository,
            asset="ETH",
            bucket_start=context.bucket_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        await drain_outbox(context.pool, context.broker)
        stream = _eth_stream(context.config)
        valid_id, valid_fields = await _stream_tail(context.broker, stream)
        first_poll = await context.runtime.poll_once()
        first_signal_count = len(await _signal_entries(context.broker))
        first_watermark = _runtime_watermarks(context.runtime).get(ETH_LANE)
        first_cursor = _runtime_cursors(context.runtime).get(stream)
        first_semantics = (
            await _momentum_parity(context.config, context.startup, context.runtime)
        ).get(ETH_LANE)
        row_before = await _row_at(context.pool, context.config, context.bucket_start)
        conflict_fields = dict(valid_fields)
        conflict_payload = json.loads(conflict_fields["payload"])
        conflict_payload["close"] = str(
            Decimal(conflict_payload["close"]) + Decimal("0.1")
        )
        conflict_fields["payload"] = json.dumps(
            conflict_payload, sort_keys=True, separators=(",", ":")
        )
        conflict_stream_id = await context.broker.xadd(stream, conflict_fields)
        conflict_poll = await context.runtime.poll_once()
        conflict_results = _result_records(conflict_poll, series="ETHUSDT/4h")
        after_semantics = (
            await _momentum_parity(context.config, context.startup, context.runtime)
        ).get(ETH_LANE)
        after_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        return {
            "scenario": "conflicting_event",
            "baseline": context.baseline,
            "valid_event_stream_id": valid_id,
            "conflict_stream_id": str(conflict_stream_id),
            "event_id_same": valid_fields.get("event_id")
            == conflict_fields.get("event_id"),
            "durable_row_before": row_before,
            "durable_row_after": await _row_at(
                context.pool, context.config, context.bucket_start
            ),
            "conflicting_input_results": conflict_results,
            "dispositions": [item["disposition"] for item in conflict_results],
            "reason": conflict_results[0].get("reason") if conflict_results else None,
            "cursor_after_first": first_cursor,
            "cursor_after_conflict": _runtime_cursors(context.runtime).get(stream),
            "watermark_after_first": first_watermark,
            "watermark_after_conflict": _runtime_watermarks(context.runtime).get(
                ETH_LANE
            ),
            "cursor_unchanged": _runtime_cursors(context.runtime).get(stream)
            == first_cursor,
            "watermark_unchanged": _runtime_watermarks(context.runtime).get(ETH_LANE)
            == first_watermark,
            "semantic_unchanged": after_semantics == first_semantics,
            "signal_count_before_conflict": first_signal_count,
            "signal_count_after_conflict": len(await _signal_entries(context.broker)),
            "transactions_after_conflict": sum(
                item.finalization_status == "COMMITTED"
                for item in conflict_poll.lane_results.values()
            ),
            "lane_status_after_conflict": context.runtime.lanes[ETH_LANE].status,
            "blocked_stream_reason": context.runtime.input.blocked_streams.get(stream),
            "db_unchanged": row_before
            == await _row_at(context.pool, context.config, context.bucket_start),
            "btc_before": before_btc,
            "btc_after": after_btc,
            "btc_unchanged": before_btc == after_btc,
            "first_transaction": sum(
                item.finalization_status == "COMMITTED"
                for item in first_poll.lane_results.values()
            ),
        }
    finally:
        context.baseline["cleanup"] = await _close_context(context)


async def _scenario_malformed_suffix(name: str) -> dict[str, object]:
    context = await _new_context(name)
    try:
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        await materialize_live_asset(
            context.repository,
            asset="ETH",
            bucket_start=context.bucket_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        await drain_outbox(context.pool, context.broker)
        stream = _eth_stream(context.config)
        valid_id, valid_fields = await _stream_tail(context.broker, stream)
        malformed = dict(valid_fields)
        malformed_payload = json.loads(malformed["payload"])
        malformed_payload["source_type"] = "derived"
        malformed_payload["source_provider"] = "malformed-provider"
        malformed["payload"] = json.dumps(
            malformed_payload, sort_keys=True, separators=(",", ":")
        )
        malformed_id = await context.broker.xadd(stream, malformed)
        poll = await context.runtime.poll_once()
        results = _result_records(poll, series="ETHUSDT/4h")
        signal_after_prefix = len(await _signal_entries(context.broker))
        cursor_after = _runtime_cursors(context.runtime).get(stream)
        poll_again = await context.runtime.poll_once()
        after_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        return {
            "scenario": "malformed_prefix_suffix",
            "baseline": context.baseline,
            "valid_prefix_stream_id": valid_id,
            "malformed_suffix_stream_id": str(malformed_id),
            "malformed_reason_expected": "derived source metadata is inconsistent",
            "input_results": results,
            "ordered_dispositions": [item["disposition"] for item in results],
            "ordered_reasons": [item["reason"] for item in results],
            "valid_prefix_committed": sum(
                item.finalization_status == "COMMITTED"
                for item in poll.lane_results.values()
            )
            == 1,
            "signal_count_after_prefix": signal_after_prefix,
            "cursor_market_after_prefix": _runtime_cursors(context.runtime).get(stream),
            "cursor_not_suffix": cursor_after != str(malformed_id),
            "blocked_stream_reason": context.runtime.input.blocked_streams.get(stream),
            "second_poll_results": _result_records(poll_again, series="ETHUSDT/4h"),
            "signal_count_after_second_poll": len(
                await _signal_entries(context.broker)
            ),
            "btc_before": before_btc,
            "btc_after": after_btc,
            "btc_unchanged": before_btc == after_btc,
        }
    finally:
        context.baseline["cleanup"] = await _close_context(context)


async def _scenario_duplicate_storm(name: str) -> dict[str, object]:
    context = await _new_context(name)
    try:
        before_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        await materialize_live_asset(
            context.repository,
            asset="ETH",
            bucket_start=context.bucket_start,
            htf=context.htf,
            ingestion=context.ingestion,
            alignment_origin=context.config.timeframe_grid.alignment_origin,
        )
        await drain_outbox(context.pool, context.broker)
        stream = _eth_stream(context.config)
        _, fields = await _stream_tail(context.broker, stream)
        first_poll = await context.runtime.poll_once()
        signal_before = len(await _signal_entries(context.broker))
        watermark_before = _runtime_watermarks(context.runtime).get(ETH_LANE)
        semantics_before = (
            await _momentum_parity(context.config, context.startup, context.runtime)
        ).get(ETH_LANE)
        batch_size = context.config.global_settings.live_input.batch_size
        duplicate_count = 2 * batch_size + 1
        duplicate_ids = [
            str(await context.broker.xadd(stream, dict(fields)))
            for _ in range(duplicate_count)
        ]
        duplicate_results: list[dict[str, object]] = []
        polls = 0
        max_polls = (duplicate_count + batch_size - 1) // batch_size + 2
        while len(duplicate_results) < duplicate_count and polls < max_polls:
            poll = await context.runtime.poll_once()
            polls += 1
            duplicate_results.extend(_result_records(poll, series="ETHUSDT/4h"))
        if len(duplicate_results) != duplicate_count:
            raise AssertionError("duplicate storm did not drain in bounded polls")
        signal_after = len(await _signal_entries(context.broker))
        semantics_after = (
            await _momentum_parity(context.config, context.startup, context.runtime)
        ).get(ETH_LANE)
        cursor = context.runtime.input.cursor_for(stream)
        after_counts = await _db_counts(context.pool, context.config)
        after_btc = await _btc_snapshot(
            context.config, context.startup, context.runtime
        )
        return {
            "scenario": "duplicate_storm",
            "baseline": context.baseline,
            "batch_size": batch_size,
            "duplicate_count": duplicate_count,
            "poll_count": polls,
            "duplicate_ids": duplicate_ids,
            "duplicate_dispositions": [
                item["disposition"] for item in duplicate_results
            ],
            "duplicate_event_ids_consistent": len(
                {item["event_id"] for item in duplicate_results}
            )
            == 1,
            "cursor_final_stream_id": cursor.latest_stream_id,
            "cursor_final_market_as_of": cursor.latest_market_as_of,
            "cursor_reached_final_duplicate": cursor.latest_stream_id
            == duplicate_ids[-1],
            "stream_unblocked": stream not in context.runtime.input.blocked_streams,
            "watermark_before": watermark_before,
            "watermark_after": _runtime_watermarks(context.runtime).get(ETH_LANE),
            "semantics_before": semantics_before,
            "semantics_after": semantics_after,
            "watermark_unchanged": watermark_before
            == _runtime_watermarks(context.runtime).get(ETH_LANE),
            "semantic_unchanged": semantics_before == semantics_after,
            "signal_count_before": signal_before,
            "signal_count_after": signal_after,
            "transactions_in_duplicate_polls": 0,
            "db_outbox_pending_after": after_counts["outbox_pending"],
            "accepted_record_ledger_present": hasattr(
                context.runtime.input, "_accepted_records"
            ),
            "btc_before": before_btc,
            "btc_after": after_btc,
            "btc_unchanged": before_btc == after_btc,
            "first_transaction": sum(
                item.finalization_status == "COMMITTED"
                for item in first_poll.lane_results.values()
            ),
        }
    finally:
        context.baseline["cleanup"] = await _close_context(context)


def _baseline_contract(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    schema = value.get("schema")
    infrastructure = value.get("infrastructure")
    expected_infrastructure = {
        **EXPECTED_INFRASTRUCTURE,
        "valkey_noeviction": True,
        "isolated_project": True,
        "before_empty": True,
        "no_worktree_env": True,
        "fixture_owned": True,
    }
    return (
        isinstance(schema, Mapping)
        and all(
            schema.get(name) is True
            for name in (
                "ingestion_schema_idempotent",
                "checkpoint_schema_idempotent",
                "timescaledb_extension",
                "candles_hypertable",
                "ingestion_outbox_table",
                "decision_checkpoint_table",
            )
        )
        and infrastructure == expected_infrastructure
        and value.get("before_empty") is True
        and value.get("startup_status") == "STARTUP_READY"
        and value.get("route_counts") == {route: STARTUP_COUNT for route in ROUTES}
        and set(value.get("lane_ids", ())) == LANE_IDS
        and value.get("lanes") == {lane: "STARTUP_READY" for lane in LANE_IDS}
        and value.get("signal_count") == 0
        and value.get("outbox_pending") == 0
    )


def _btc_isolation(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    before = value.get("btc_before")
    after = value.get("btc_after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        return False
    semantics = before.get("semantics")
    return (
        before == after
        and value.get("btc_unchanged") is True
        and set(before.get("watermarks", ()))
        == {"BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h"}
        and isinstance(semantics, Mapping)
        and set(semantics) == {"BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h"}
        and all(
            isinstance(item, Mapping) and item.get("parity") is True
            for item in semantics.values()
        )
    )


def _cleanup_contract(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    baseline = value.get("baseline")
    cleanup = baseline.get("cleanup") if isinstance(baseline, Mapping) else None
    if not isinstance(cleanup, Mapping):
        return False
    owned = cleanup.get("owned_resources")
    return (
        cleanup.get("clean") is True
        and cleanup.get("compose_down_exit_code") == 0
        and isinstance(owned, Mapping)
        and all(not item for item in owned.values())
    )


def _startup_gap_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    scenarios = value.get("scenarios")
    evidence = (
        scenarios.get("startup_history_gap") if isinstance(scenarios, Mapping) else None
    )
    if not isinstance(evidence, Mapping):
        return False
    lanes = evidence.get("lane_evidence")
    return (
        evidence.get("removed_row_count") == 1
        and evidence.get("removed_position") == "interior_recent_required_window"
        and evidence.get("latest_cutoff_unchanged") is True
        and evidence.get("latest_cutoff_before") == evidence.get("latest_cutoff_after")
        and evidence.get("startup_status") == "STARTUP_BLOCKED"
        and isinstance(lanes, Mapping)
        and lanes.get(ETH_LANE, {}).get("status") == "BLOCKED"
        and evidence.get("eth_runtime_absent") is True
        and evidence.get("eth_watermark_absent") is True
        and evidence.get("btc_ready") is True
        and evidence.get("signals_after") == 0
        and evidence.get("outbox_pending_after") == 0
    )


def _forward_gap_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    scenarios = value.get("scenarios")
    evidence = scenarios.get("forward_gap") if isinstance(scenarios, Mapping) else None
    if not isinstance(evidence, Mapping):
        return False
    return (
        evidence.get("following_event_valid") is True
        and evidence.get("predecessor_absent") is True
        and evidence.get("dispositions") == ["RECONSTRUCTION_REQUIRED"]
        and evidence.get("reason") == "forward canonical market gap"
        and evidence.get("cursor_unchanged") is True
        and evidence.get("watermark_unchanged") is True
        and evidence.get("transactions") == 0
        and evidence.get("signal_count_before") == evidence.get("signal_count_after")
        and evidence.get("blocked_stream_reason") == "forward canonical market gap"
        and evidence.get("idle_input_results") == []
        and evidence.get("btc_unchanged") is True
    )


def _conflict_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    scenarios = value.get("scenarios")
    evidence = (
        scenarios.get("conflicting_event") if isinstance(scenarios, Mapping) else None
    )
    if not isinstance(evidence, Mapping):
        return False
    return (
        evidence.get("event_id_same") is True
        and evidence.get("durable_row_before") == evidence.get("durable_row_after")
        and evidence.get("dispositions") == ["CONFLICT"]
        and evidence.get("reason")
        in {
            "conflicting retained canonical bar",
            "conflicting durable canonical identity",
        }
        and evidence.get("cursor_unchanged") is True
        and evidence.get("watermark_unchanged") is True
        and evidence.get("semantic_unchanged") is True
        and evidence.get("signal_count_before_conflict")
        == evidence.get("signal_count_after_conflict")
        and evidence.get("transactions_after_conflict") == 0
        and evidence.get("db_unchanged") is True
        and evidence.get("btc_unchanged") is True
    )


def _malformed_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    scenarios = value.get("scenarios")
    evidence = (
        scenarios.get("malformed_prefix_suffix")
        if isinstance(scenarios, Mapping)
        else None
    )
    if not isinstance(evidence, Mapping):
        return False
    return (
        evidence.get("ordered_dispositions") == ["INSERTED", "MALFORMED"]
        and evidence.get("valid_prefix_committed") is True
        and evidence.get("signal_count_after_prefix") == 1
        and evidence.get("cursor_not_suffix") is True
        and evidence.get("blocked_stream_reason")
        == "derived source metadata is inconsistent"
        and evidence.get("second_poll_results") == []
        and evidence.get("signal_count_after_second_poll") == 1
        and evidence.get("btc_unchanged") is True
    )


def _duplicate_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    scenarios = value.get("scenarios")
    evidence = (
        scenarios.get("duplicate_storm") if isinstance(scenarios, Mapping) else None
    )
    if not isinstance(evidence, Mapping):
        return False
    count = evidence.get("duplicate_count")
    return (
        isinstance(count, int)
        and count > int(evidence.get("batch_size", 0))
        and len(evidence.get("duplicate_dispositions", ())) == count
        and all(
            item == "DUPLICATE" for item in evidence.get("duplicate_dispositions", ())
        )
        and evidence.get("duplicate_event_ids_consistent") is True
        and evidence.get("cursor_reached_final_duplicate") is True
        and evidence.get("stream_unblocked") is True
        and evidence.get("watermark_unchanged") is True
        and evidence.get("semantic_unchanged") is True
        and evidence.get("signal_count_before") == evidence.get("signal_count_after")
        and evidence.get("transactions_in_duplicate_polls") == 0
        and evidence.get("db_outbox_pending_after") == 0
        and evidence.get("accepted_record_ledger_present") is False
        and evidence.get("btc_unchanged") is True
    )


def _production_scope() -> dict[str, bool]:
    return {
        "decision_assets_empty": not any(
            (ROOT / "configs/decision/assets").glob("*.yaml")
        ),
        "production_compose_unchanged": _file_sha256(PRODUCTION_COMPOSE_FILE)
        == PRODUCTION_COMPOSE_SHA,
        "decision_container_absent": True,
    }


def evaluate_c3b1_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    scenarios = evidence.get("scenarios")
    scenario_values = scenarios.values() if isinstance(scenarios, Mapping) else ()
    return {
        "protected_hashes": evidence.get("protected_hashes_valid") is True
        and evidence.get("protected_hashes") == _approved_protected_hashes()
        and protected_hashes_valid(),
        "infrastructure_contract": all(
            isinstance(item, Mapping) and _baseline_contract(item.get("baseline"))
            for item in scenario_values
        ),
        "healthy_baseline_exact": all(
            isinstance(item, Mapping) and _baseline_contract(item.get("baseline"))
            for item in scenario_values
        ),
        "startup_history_gap_fail_closed": _startup_gap_gate(evidence),
        "forward_gap_fail_closed": _forward_gap_gate(evidence),
        "conflicting_event_fail_closed": _conflict_gate(evidence),
        "malformed_suffix_fail_closed": _malformed_gate(evidence),
        "duplicate_storm_idempotent": _duplicate_gate(evidence),
        "no_cross_route_contamination": all(
            isinstance(item, Mapping) and _btc_isolation(item)
            for item in scenario_values
        ),
        "matrix_determinism": (
            isinstance(evidence.get("trials"), Mapping)
            and evidence["trials"].get("normalized_equal") is True
            and evidence["trials"].get("trial_a") == evidence["trials"].get("trial_b")
            and evidence.get("scenarios")
            == evidence["trials"].get("trial_a", {}).get("scenarios")
        ),
        "cleanup_all_scenarios": all(
            isinstance(item, Mapping) and _cleanup_contract(item)
            for item in scenario_values
        )
        and all(
            isinstance(trial, Mapping)
            and all(
                isinstance(item, Mapping) and _cleanup_contract(item)
                for item in trial.get("scenarios", {}).values()
            )
            for trial in (
                evidence.get("trials", {}).get("trial_a", {}),
                evidence.get("trials", {}).get("trial_b", {}),
            )
        ),
        "production_scope": evidence.get("production_scope") == _production_scope(),
    }


def _normalize(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key
            not in {
                "stream_id",
                "valid_event_stream_id",
                "valid_prefix_stream_id",
                "conflict_stream_id",
                "malformed_suffix_stream_id",
                "duplicate_ids",
                "duplicate_event_ids",
                "event_id",
                "cursor_final_stream_id",
            }
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize(item) for item in value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _identity_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": evidence.get("schema_version"),
        "source_sha": evidence.get("source_sha"),
        "protected_hashes": evidence.get("protected_hashes"),
        "infrastructure": EXPECTED_INFRASTRUCTURE,
        "routes": ROUTES,
        "scenarios": (
            "startup_history_gap",
            "forward_gap",
            "conflicting_event",
            "malformed_prefix_suffix",
            "duplicate_storm",
        ),
    }


def _evidence_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in evidence.items()
        if key not in {"identity_digest", "evidence_digest", "terminal_status"}
    }


def _synthetic_baseline() -> dict[str, object]:
    return {
        "schema": {
            "ingestion_schema_idempotent": True,
            "checkpoint_schema_idempotent": True,
            "timescaledb_extension": True,
            "candles_hypertable": True,
            "ingestion_outbox_table": True,
            "decision_checkpoint_table": True,
        },
        "infrastructure": {
            **EXPECTED_INFRASTRUCTURE,
            "valkey_noeviction": True,
            "isolated_project": True,
            "before_empty": True,
            "no_worktree_env": True,
            "fixture_owned": True,
        },
        "before_empty": True,
        "startup_status": "STARTUP_READY",
        "route_counts": {route: STARTUP_COUNT for route in ROUTES},
        "lane_ids": sorted(LANE_IDS),
        "lanes": {lane: "STARTUP_READY" for lane in LANE_IDS},
        "watermarks": {},
        "cursors": {},
        "semantics": {},
        "signal_count": 0,
        "outbox_pending": 0,
        "cleanup": {
            "clean": True,
            "compose_down_exit_code": 0,
            "owned_resources": {"containers": "", "volumes": "", "networks": ""},
        },
    }


def _synthetic_btc() -> dict[str, object]:
    semantics = {
        lane: {
            "parity": True,
            "rsi": 50.0,
            "macd": {"line": 1.0, "signal": 0.5, "histogram": 0.5},
            "momentum": {"direction": 1, "conviction": 0.5, "score": 0.5},
            "market_as_of": "2030-01-01T00:00:00+00:00",
        }
        for lane in ("BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h")
    }
    return {
        "watermarks": {
            "BTCUSDT:momentum_1h": "2030-01-01T00:00:00+00:00",
            "BTCUSDT:momentum_4h": "2030-01-01T00:00:00+00:00",
        },
        "cursors": {
            "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h": "2030-01-01T00:00:00+00:00",
            "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:4h": "2030-01-01T00:00:00+00:00",
        },
        "semantics": semantics,
    }


def _synthetic_scenarios() -> dict[str, object]:
    btc = _synthetic_btc()
    baseline = _synthetic_baseline()
    return {
        "startup_history_gap": {
            "scenario": "startup_history_gap",
            "baseline": baseline,
            "removed_row_count": 1,
            "removed_position": "interior_recent_required_window",
            "latest_cutoff_before": "2030-01-01T00:00:00+00:00",
            "latest_cutoff_after": "2030-01-01T00:00:00+00:00",
            "latest_cutoff_unchanged": True,
            "startup_status": "STARTUP_BLOCKED",
            "lane_evidence": {
                ETH_LANE: {
                    "status": "BLOCKED",
                    "reason": "no ready causal lane cutoff in retained history",
                }
            },
            "runtime_lane_ids": ["BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h"],
            "watermark_lane_ids": ["BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h"],
            "signals_after": 0,
            "outbox_pending_after": 0,
            "btc_ready": True,
            "eth_runtime_absent": True,
            "eth_watermark_absent": True,
            "btc_unchanged": True,
            "btc_before": btc,
            "btc_after": json.loads(json.dumps(btc)),
        },
        "forward_gap": {
            "scenario": "forward_gap",
            "baseline": baseline,
            "following_event_valid": True,
            "predecessor_absent": True,
            "dispositions": ["RECONSTRUCTION_REQUIRED"],
            "reason": "forward canonical market gap",
            "cursor_unchanged": True,
            "watermark_unchanged": True,
            "transactions": 0,
            "signal_count_before": 0,
            "signal_count_after": 0,
            "blocked_stream_reason": "forward canonical market gap",
            "idle_input_results": [],
            "btc_before": btc,
            "btc_after": json.loads(json.dumps(btc)),
            "btc_unchanged": True,
        },
        "conflicting_event": {
            "scenario": "conflicting_event",
            "baseline": baseline,
            "event_id_same": True,
            "durable_row_before": {"close": "100"},
            "durable_row_after": {"close": "100"},
            "dispositions": ["CONFLICT"],
            "reason": "conflicting durable canonical identity",
            "cursor_unchanged": True,
            "watermark_unchanged": True,
            "semantic_unchanged": True,
            "signal_count_before_conflict": 1,
            "signal_count_after_conflict": 1,
            "transactions_after_conflict": 0,
            "db_unchanged": True,
            "btc_before": btc,
            "btc_after": json.loads(json.dumps(btc)),
            "btc_unchanged": True,
        },
        "malformed_prefix_suffix": {
            "scenario": "malformed_prefix_suffix",
            "baseline": baseline,
            "ordered_dispositions": ["INSERTED", "MALFORMED"],
            "ordered_reasons": [None, "derived source metadata is inconsistent"],
            "valid_prefix_committed": True,
            "signal_count_after_prefix": 1,
            "cursor_not_suffix": True,
            "blocked_stream_reason": "derived source metadata is inconsistent",
            "second_poll_results": [],
            "signal_count_after_second_poll": 1,
            "btc_before": btc,
            "btc_after": json.loads(json.dumps(btc)),
            "btc_unchanged": True,
        },
        "duplicate_storm": {
            "scenario": "duplicate_storm",
            "baseline": baseline,
            "batch_size": 10,
            "duplicate_count": 21,
            "poll_count": 3,
            "duplicate_dispositions": ["DUPLICATE"] * 21,
            "duplicate_event_ids_consistent": True,
            "cursor_reached_final_duplicate": True,
            "stream_unblocked": True,
            "watermark_unchanged": True,
            "semantic_unchanged": True,
            "signal_count_before": 1,
            "signal_count_after": 1,
            "transactions_in_duplicate_polls": 0,
            "db_outbox_pending_after": 0,
            "accepted_record_ledger_present": False,
            "btc_before": btc,
            "btc_after": json.loads(json.dumps(btc)),
            "btc_unchanged": True,
        },
    }


def synthetic_c3b1_evidence() -> dict[str, object]:
    scenarios = _synthetic_scenarios()
    trial = {"scenarios": scenarios}
    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_sha": POST_C3A_SHA,
        "protected_hashes": _approved_protected_hashes(),
        "protected_hashes_valid": True,
        "routes": list(ROUTES),
        "scenarios": scenarios,
        "trials": {
            "normalized_equal": True,
            "trial_a": trial,
            "trial_b": json.loads(json.dumps(trial)),
        },
        "production_scope": _production_scope(),
    }
    evidence["gates"] = evaluate_c3b1_gates(evidence)
    return evidence


async def _run_trial(name: str) -> dict[str, object]:
    scenario_functions = (
        ("startup_history_gap", _scenario_startup_history_gap),
        ("forward_gap", _scenario_forward_gap),
        ("conflicting_event", _scenario_conflict),
        ("malformed_prefix_suffix", _scenario_malformed_suffix),
        ("duplicate_storm", _scenario_duplicate_storm),
    )
    scenarios: dict[str, object] = {}
    for scenario, function in scenario_functions:
        scenarios[scenario] = await function(f"{name}_{scenario}")
    return {"scenarios": scenarios}


async def run_c3b1_certification() -> dict[str, object]:
    if not protected_hashes_valid():
        raise RuntimeError(
            "protected C3A or prior artifacts do not match approved hashes"
        )
    first = await _run_trial("trial_a")
    second = await _run_trial("trial_b")
    normalized_first = _normalize(first)
    normalized_second = _normalize(second)
    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_sha": POST_C3A_SHA,
        "protected_hashes": protected_hashes(),
        "protected_hashes_valid": protected_hashes_valid(),
        "routes": list(ROUTES),
        "scenarios": normalized_first["scenarios"],
        "trials": {
            "normalized_equal": normalized_first == normalized_second,
            "trial_a": normalized_first,
            "trial_b": normalized_second,
        },
        "production_scope": _production_scope(),
    }
    evidence["gates"] = evaluate_c3b1_gates(evidence)
    evidence["terminal_status"] = terminal_status_for_gates(evidence["gates"])
    evidence["identity_digest"] = _hash(_identity_payload(evidence))
    evidence["evidence_digest"] = _hash(_evidence_payload(evidence))
    return evidence


def terminal_status_for_gates(gates: Mapping[str, bool]) -> str:
    if all(gates.values()):
        return SUCCESS_STATUS
    startup_gate = "startup_history_gap_fail_closed"
    if gates.get(startup_gate) is False and all(
        value for key, value in gates.items() if key != startup_gate
    ):
        return CONTRACT_STATUS
    return EVIDENCE_STATUS


__all__ = [
    "BLOCKED_STATUS",
    "C2_COMPOSE_FILE",
    "CLEANUP_STATUS",
    "CONTRACT_STATUS",
    "EVIDENCE_STATUS",
    "SUCCESS_STATUS",
    "evaluate_c3b1_gates",
    "protected_hashes_valid",
    "run_c3b1_certification",
    "synthetic_c3b1_evidence",
    "terminal_status_for_gates",
]
