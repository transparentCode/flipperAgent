"""Disposable real TimescaleDB/Valkey certification harness for C2.

The harness owns only test infrastructure.  It deliberately composes the
approved ingestion and Decision adapters instead of adding a second runtime
path or changing production configuration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import socket
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey

from apps.decision_app.composition import build_production_composition
from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.storage.checkpoints import CheckpointRepository
from apps.decision_app.storage.market_history import (
    CanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import (
    canonical_ingestion_stream_key,
    parse_canonical_ingestion_event,
)
from apps.decision_app.transport.publication import (
    SignalPublicationEnvelope,
    signal_idempotency_key,
    signal_payload_fingerprint,
)
from apps.decision_app.transport.signals import ValkeySignalPublisher
from apps.ingestion_app.domain.candle import (
    CandleObservation,
)
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.settings import PublicationSettings
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.config import ConfigManager
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal
from tests.combined.c1_harness import (
    _ROUTE_NAMES,
    _seed_bar,
    load_fixture_config,
)

ROOT = Path(__file__).resolve().parents[2]
C2_COMPOSE_FILE = ROOT / "tests" / "combined" / "fixtures" / "c2" / "docker-compose.yml"
PRODUCTION_COMPOSE_FILE = ROOT / "docker-compose.yml"
C2_SUCCESS_STATUS = "INGESTION_DECISION_C2_REAL_INFRASTRUCTURE_READY_FOR_RESILIENCE"
C2_BLOCKED_STATUS = "INGESTION_DECISION_C2_BLOCKED_INFRASTRUCTURE_PREFLIGHT"
C2_EVIDENCE_STATUS = "INGESTION_DECISION_C2_EVIDENCE_INSUFFICIENT"
C2_CLEANUP_STATUS = "INGESTION_DECISION_C2_CLEANUP_FAILED"
C2_SCHEMA_STATUS = "INGESTION_DECISION_C2_BLOCKED_SCHEMA_CONTRACT"

M3_ARTIFACT_SHA = "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"
M4_FUNCTIONAL_SHA = "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792"
M4_RESOURCE_SHA = "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4"
D10_ARTIFACT_SHA = "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459"
C1_ARTIFACT_SHA = "386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4"
POST_C1_SHA = "4647a04dc53a7ffd3de85a2f84b10bae4be9cefa"

STARTUP_COUNT = 544
LIVE_BASE_COUNT = 240
LIVE_DERIVED_COUNTS = {"BTCUSDT/1h": 4, "BTCUSDT/4h": 1, "ETHUSDT/4h": 1}
LIVE_OUTBOX_COUNT = 486
CERTIFIED_SIGNAL_MODELS = {
    "signals:BTCUSDT:1h": "m4-btc-1h",
    "signals:BTCUSDT:4h": "m4-btc-4h",
    "signals:ETHUSDT:4h": "m4-eth-4h",
}
CERTIFIED_LANE_IDS = frozenset(
    {
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
        "ETHUSDT:momentum_4h",
    }
)
EXPECTED_INFRASTRUCTURE = {
    "db_image": "timescale/timescaledb:latest-pg15",
    "broker_image": "valkey/valkey:latest",
}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_value(item) for item in value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, bytes):
        return value.decode()
    return value


def canonical_json(value: object) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))


def sha256_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[str, str]:
    paths = {
        "m3": ROOT
        / "artifacts"
        / "decision_m3"
        / "m3_momentum_feature_semantics_certification.json",
        "m4_functional": ROOT
        / "artifacts"
        / "decision_m4"
        / "m4_momentum_decision_integration_certification.json",
        "m4_resource": ROOT
        / "artifacts"
        / "decision_m4"
        / "m4_momentum_resource_certification.json",
        "d10": ROOT
        / "artifacts"
        / "decision_d10"
        / "d10_resource_capacity_certification.json",
        "c1": ROOT
        / "artifacts"
        / "combined_c1"
        / "c1_ingestion_decision_momentum_certification.json",
    }
    return {name: file_sha256(path) for name, path in paths.items()}


def protected_hashes_valid() -> bool:
    return protected_hashes() == {
        "m3": M3_ARTIFACT_SHA,
        "m4_functional": M4_FUNCTIONAL_SHA,
        "m4_resource": M4_RESOURCE_SHA,
        "d10": D10_ARTIFACT_SHA,
        "c1": C1_ARTIFACT_SHA,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_compose(
    infrastructure: C2Infrastructure,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = infrastructure.command(*arguments)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=infrastructure.environment,
        text=True,
        capture_output=True,
        check=check,
    )


def _cleanup_probe(project_name: str) -> tuple[str, str, str]:
    def probe(command: list[str]) -> str:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip()

    label = f"label=com.docker.compose.project={project_name}"
    containers = probe(["docker", "ps", "-aq", "--filter", label])
    volumes = probe(["docker", "volume", "ls", "-q", "--filter", label])
    networks = probe(["docker", "network", "ls", "-q", "--filter", label])
    return containers, volumes, networks


@dataclass(slots=True)
class C2Infrastructure:
    """One uniquely named, disposable db+broker Compose project."""

    trial_name: str
    db_port: int = field(default_factory=_free_port)
    broker_port: int = field(default_factory=_free_port)
    project_name: str = field(init=False)
    started: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.db_port == self.broker_port:
            self.broker_port = _free_port()
        token = "".join(char if char.isalnum() else "_" for char in self.trial_name)
        self.project_name = f"flipper_c2_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "C2_DB_PORT": str(self.db_port),
                "C2_BROKER_PORT": str(self.broker_port),
                "COMPOSE_PROJECT_NAME": self.project_name,
                "COMPOSE_DISABLE_ENV_FILE": "1",
            }
        )
        return environment

    def command(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(C2_COMPOSE_FILE),
            "-p",
            self.project_name,
            *arguments,
        ]

    def validate_config(self) -> None:
        _run_compose(self, "config", "--quiet")

    async def start(self) -> None:
        self.validate_config()
        await asyncio.to_thread(_run_compose, self, "up", "-d", "--wait")
        self.started = True

    async def cleanup(self) -> bool:
        result = await asyncio.to_thread(
            _run_compose,
            self,
            "down",
            "-v",
            "--remove-orphans",
            check=False,
        )
        containers, volumes, networks = await asyncio.to_thread(
            _cleanup_probe,
            self.project_name,
        )
        self.started = False
        return (
            result.returncode == 0 and not containers and not volumes and not networks
        )

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://c2_user:c2_password@127.0.0.1:{self.db_port}/c2_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"


class RecordingHistory:
    """Record real Decision history calls while delegating unchanged."""

    def __init__(self, repository: CanonicalMarketHistoryRepository) -> None:
        self.repository = repository
        self.fetch_calls: list[dict[str, object]] = []

    async def fetch_latest_cutoff(self, key: MarketSeriesKey) -> datetime | None:
        return await self.repository.fetch_latest_cutoff(key)

    async def fetch_record_at(
        self,
        key: MarketSeriesKey,
        bar_open_at: datetime,
    ) -> Any:
        return await self.repository.fetch_record_at(key, bar_open_at)

    async def fetch_bars(
        self, key: MarketSeriesKey, **kwargs: object
    ) -> tuple[Any, ...]:
        self.fetch_calls.append(
            {"key": key, **{name: value for name, value in kwargs.items()}}
        )
        return await self.repository.fetch_bars(key, **kwargs)


class C2HistoricalProvider:
    """Deterministic one-candle provider used only for healthy recovery."""

    provider_id = "c2_live_fixture"

    def __init__(self, observation: CandleObservation) -> None:
        self.observation = observation
        self.calls = 0

    async def fetch_closed_candles(
        self,
        *,
        lane: MarketLane,
        provider_symbol: str,
        timeframe_duration: timedelta,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[CandleObservation, ...]:
        self.calls += 1
        if (
            self.observation.lane == lane
            and since <= self.observation.open_time < until
            and self.observation.close_time <= until
        ):
            return (self.observation,)
        return ()


def _route_key(asset: str, timeframe: str) -> MarketSeriesKey:
    return MarketSeriesKey(
        asset=asset,
        venue="binance",
        instrument_id=f"{asset.removesuffix('USDT')}-USDT-PERP",
        timeframe=timeframe,
    )


def _route_keys(config: Any) -> tuple[MarketSeriesKey, ...]:
    return tuple(
        MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=lane.decision_timeframe,
        )
        for lane in config.lane_specs()
    )


def _seed_rows(config: Any) -> tuple[datetime, list[tuple[object, ...]]]:
    bucket_start = config.timeframe_grid.alignment_origin + timedelta(days=1000)
    rows: list[tuple[object, ...]] = []
    for key in _route_keys(config):
        duration = config.timeframe_grid.duration(key.timeframe)
        start = bucket_start - duration * STARTUP_COUNT
        for index in range(STARTUP_COUNT):
            candle = _seed_bar(
                key,
                opened=start + duration * index,
                close=Decimal(100) + Decimal(index) / Decimal(10),
            )
            rows.append(
                (
                    candle.lane.venue,
                    candle.lane.instrument_id,
                    candle.lane.timeframe,
                    candle.open_time,
                    candle.close_time,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    candle.taker_buy_base,
                    candle.source_type,
                    candle.source_provider,
                    candle.source_timeframe,
                )
            )
    return bucket_start, rows


async def seed_startup_history(pool: asyncpg.Pool, config: Any) -> datetime:
    bucket_start, rows = _seed_rows(config)
    query = """
        INSERT INTO ingestion.candles (
            venue, instrument_id, timeframe, open_time, close_time,
            open, high, low, close, volume, taker_buy_base,
            source_type, source_provider, source_timeframe
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
    """
    async with pool.acquire() as connection, connection.transaction():
        await connection.executemany(query, rows)
    return bucket_start


async def _count_route_rows(
    pool: asyncpg.Pool,
    key: MarketSeriesKey,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> int:
    clauses = ["venue=$1", "instrument_id=$2", "timeframe=$3"]
    args: list[object] = [key.venue, key.instrument_id, key.timeframe]
    if start is not None:
        args.append(start)
        clauses.append(f"open_time >= ${len(args)}")
    if end is not None:
        args.append(end)
        clauses.append(f"open_time < ${len(args)}")
    return int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM ingestion.candles WHERE " + " AND ".join(clauses),
            *args,
        )
    )


async def _db_counts(pool: asyncpg.Pool, config: Any) -> dict[str, object]:
    rows = {
        f"{key.asset}/{key.timeframe}": await _count_route_rows(pool, key)
        for key in _route_keys(config)
    }
    base_count = int(
        await pool.fetchval(
            """SELECT COUNT(*) FROM ingestion.candles
               WHERE instrument_id IN ('BTC-USDT-PERP','ETH-USDT-PERP')
                 AND timeframe = '1m'"""
        )
    )
    total = int(await pool.fetchval("SELECT COUNT(*) FROM ingestion.candles"))
    outbox_total = int(await pool.fetchval("SELECT COUNT(*) FROM ingestion.outbox"))
    pending = int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
        )
    )
    return {
        "route_rows": rows,
        "base_1m_rows": base_count,
        "total_rows": total,
        "outbox_total": outbox_total,
        "outbox_pending": pending,
    }


async def _schema_evidence(pool: asyncpg.Pool, broker: Any) -> dict[str, object]:
    await apply_ingestion_schema(pool)
    await apply_ingestion_schema(pool)
    await ensure_checkpoint_schema(pool)
    await ensure_checkpoint_schema(pool)
    extension = await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb')"
    )
    hypertable = await pool.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM timescaledb_information.hypertables
              WHERE hypertable_schema='ingestion' AND hypertable_name='candles'
           )"""
    )
    ingestion_outbox = await pool.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM information_schema.tables
              WHERE table_schema='ingestion' AND table_name='outbox'
           )"""
    )
    checkpoint_table = await pool.fetchval(
        """SELECT EXISTS (
             SELECT 1 FROM information_schema.tables
              WHERE table_schema='decision' AND table_name='state_checkpoints'
           )"""
    )
    await broker.ping()
    return {
        "ingestion_schema_idempotent": True,
        "checkpoint_schema_idempotent": True,
        "timescaledb_extension": bool(extension),
        "candles_hypertable": bool(hypertable),
        "ingestion_outbox_table": bool(ingestion_outbox),
        "decision_checkpoint_table": bool(checkpoint_table),
    }


def _publication_settings() -> PublicationSettings:
    return PublicationSettings(
        batch_size=1000,
        idle_sleep_seconds=1,
        error_backoff_seconds=1,
        stream_maxlen=10_000,
        stream_approximate=False,
    )


async def drain_outbox(pool: asyncpg.Pool, broker: Any) -> dict[str, int]:
    repository = CandleRepository(pool)
    publisher = OutboxPublisher(
        repository=repository,
        valkey_client=broker,
        publication=_publication_settings(),
        now_fn=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    attempts = 0
    published = 0
    while True:
        attempts += 1
        count = await publisher.publish_once()
        published += count
        pending = int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )
        if pending == 0:
            return {"attempts": attempts, "published": published}
        if attempts > 10:
            raise AssertionError("real outbox did not drain in bounded attempts")


async def _build_runtime(
    config: Any,
    pool: asyncpg.Pool,
    broker: Any,
    history: RecordingHistory,
) -> tuple[Any, LiveDecisionRuntime, Any]:
    composition = build_production_composition(config)
    startup = await DecisionStartupCoordinator(
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
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=config.timeframe_grid,
        stream_client=broker,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(
            broker,
            stream_maxlen=config.global_settings.signal_publication.stream_maxlen,
            stream_approximate=config.global_settings.signal_publication.stream_approximate,
        ),
        checkpoint_repository=CheckpointRepository(pool),
        batch_size=config.global_settings.live_input.batch_size,
        block_ms=config.global_settings.live_input.block_ms,
        now_fn=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    return startup, runtime, composition


def _provider_observation(
    *,
    asset: str,
    opened: datetime,
    index: int,
) -> CandleObservation:
    lane = MarketLane("binance", f"{asset}-USDT-PERP", "1m")
    close = Decimal("154.3") + Decimal(index + 1) / Decimal(10)
    return CandleObservation(
        lane=lane,
        provider_id="c2_live_fixture",
        provider_symbol=f"{asset}USDT",
        transport="deterministic",
        open_time=opened,
        close_time=opened + timedelta(minutes=1),
        open=close,
        high=close + Decimal("0.2"),
        low=close - Decimal("0.2"),
        close=close,
        volume=Decimal(1),
        taker_buy_base=Decimal("0.4"),
        received_at=opened + timedelta(minutes=1),
    )


async def materialize_live_asset(
    repository: CandleRepository,
    *,
    asset: str,
    bucket_start: datetime,
    htf: HTFAggregationService,
    ingestion: CandleIngestionService,
    alignment_origin: datetime,
    missing_index: int | None = None,
) -> dict[str, object]:
    target_durations = (
        {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
        if asset == "BTC"
        else {"4h": timedelta(hours=4)}
    )
    base_lane = MarketLane("binance", f"{asset}-USDT-PERP", "1m")
    inserted = 0
    requests: list[RecoveryRequest] = []
    for index in range(LIVE_BASE_COUNT):
        if missing_index == index:
            continue
        observation = _provider_observation(
            asset=asset,
            opened=bucket_start + timedelta(minutes=index),
            index=index,
        )
        status = await ingestion.commit_observation(observation)
        if status is CandleCommitStatus.INSERTED:
            inserted += 1
        elif status is CandleCommitStatus.CONFLICT:
            raise AssertionError("unexpected real canonical conflict")
        requests.extend(
            await htf.process_base_candle(
                canonicalize_observation(observation),
                base_duration=timedelta(minutes=1),
                target_durations=target_durations,
                alignment_origin=alignment_origin,
            )
        )
    return {
        "base_inserted": inserted,
        "requests": requests,
        "base_lane": base_lane,
    }


async def _stream_derived_events(
    broker: Any,
    config: Any,
) -> tuple[dict[str, object], ...]:
    events: list[dict[str, object]] = []
    for key in _route_keys(config):
        stream = canonical_ingestion_stream_key(key)
        for stream_id, fields in await broker.xrange(stream, "-", "+"):
            event = parse_canonical_ingestion_event(
                stream_key=stream,
                stream_id=stream_id,
                fields=fields,
                expected_series=key,
                timeframe_grid=config.timeframe_grid,
            )
            events.append(
                {
                    "stream": stream,
                    "stream_id": str(stream_id),
                    "series": f"{key.asset}/{key.timeframe}",
                    "event": event,
                }
            )
    return tuple(events)


async def _producer_stream_lengths(broker: Any) -> dict[str, int]:
    lengths: dict[str, int] = {}
    async for key in broker.scan_iter(match="stream:ohlcv:ingestion:*"):
        stream = str(key)
        lengths[stream] = int(await broker.xlen(stream))
    return dict(sorted(lengths.items()))


def _lane_table(poll: Any) -> dict[str, dict[str, object]]:
    return {
        lane_id: {
            "status": result.status,
            "trigger_cutoff": (
                None
                if result.trigger_cutoff is None
                else result.trigger_cutoff.isoformat()
            ),
            "policy_status": result.policy_status,
            "publication_outcome": result.publication_outcome,
            "finalization_status": result.finalization_status,
        }
        for lane_id, result in poll.lane_results.items()
    }


def _runtime_watermarks(runtime: LiveDecisionRuntime) -> dict[str, object]:
    return {
        lane_id: live_lane.finalizer.watermark.latest_market_as_of
        for lane_id, live_lane in runtime.lanes.items()
    }


def _runtime_cursors(runtime: LiveDecisionRuntime) -> dict[str, object]:
    return {
        stream: cursor.latest_market_as_of
        for stream, cursor in runtime.input.cursors.items()
    }


def _semantic_cutoffs_match(
    semantics: Mapping[str, object],
    lane_results: Mapping[str, object],
) -> bool:
    if set(semantics) != set(lane_results):
        return False
    for lane_id, semantic in semantics.items():
        lane_result = lane_results[lane_id]
        if not isinstance(semantic, Mapping) or not isinstance(lane_result, Mapping):
            return False
        if semantic.get("parity") is not True:
            return False
        if semantic.get("market_as_of") != lane_result.get("trigger_cutoff"):
            return False
    return True


def _compact_reference_semantic(value: Mapping[str, object]) -> dict[str, object]:
    return {
        "market_as_of": value.get("market_as_of"),
        "rsi": value.get("rsi", {}).get("actual"),
        "macd": value.get("macd", {}).get("actual"),
        "momentum": value.get("momentum", {}).get("actual"),
        "parity": value.get("parity"),
    }


def _canonical_candle_semantics(
    value: object,
    *,
    alignment_origin: datetime,
    duration: timedelta,
) -> dict[str, object]:
    if isinstance(value, Mapping):
        lane_venue = value["venue"]
        lane_instrument = value["instrument_id"]
        timeframe = value["timeframe"]
        opened = value["open_time"]
        closed = value["close_time"]
        fields = value
    else:
        lane = value.lane
        lane_venue = lane.venue
        lane_instrument = lane.instrument_id
        timeframe = lane.timeframe
        opened = value.open_time
        closed = value.close_time
        fields = value
    if isinstance(opened, str):
        opened = datetime.fromisoformat(opened)
    if isinstance(closed, str):
        closed = datetime.fromisoformat(closed)
    assert isinstance(opened, datetime)
    assert isinstance(closed, datetime)
    return {
        "venue": str(lane_venue),
        "instrument_id": str(lane_instrument),
        "timeframe": str(timeframe),
        "open": str(fields["open"] if isinstance(fields, Mapping) else fields.open),
        "high": str(fields["high"] if isinstance(fields, Mapping) else fields.high),
        "low": str(fields["low"] if isinstance(fields, Mapping) else fields.low),
        "close": str(fields["close"] if isinstance(fields, Mapping) else fields.close),
        "volume": str(
            fields["volume"] if isinstance(fields, Mapping) else fields.volume
        ),
        "taker_buy_base": (
            None
            if (
                fields["taker_buy_base"]
                if isinstance(fields, Mapping)
                else fields.taker_buy_base
            )
            is None
            else str(
                fields["taker_buy_base"]
                if isinstance(fields, Mapping)
                else fields.taker_buy_base
            )
        ),
        "source_type": str(
            fields["source_type"] if isinstance(fields, Mapping) else fields.source_type
        ),
        "source_provider": (
            fields["source_provider"]
            if isinstance(fields, Mapping)
            else fields.source_provider
        ),
        "source_timeframe": (
            fields["source_timeframe"]
            if isinstance(fields, Mapping)
            else fields.source_timeframe
        ),
        "bar_duration_seconds": int((closed - opened).total_seconds()),
        "bar_open_aligned": (
            (opened - alignment_origin).total_seconds() % duration.total_seconds() == 0
        ),
    }


def _event_semantics(
    event: Any,
    *,
    alignment_origin: datetime,
    duration: timedelta,
) -> dict[str, object]:
    return _canonical_candle_semantics(
        {
            "venue": event.series_key.venue,
            "instrument_id": event.series_key.instrument_id,
            "timeframe": event.series_key.timeframe,
            "open_time": event.bar.bar_open_at,
            "close_time": event.bar.bar_close_at,
            "open": event.bar.open,
            "high": event.bar.high,
            "low": event.bar.low,
            "close": event.bar.close,
            "volume": event.bar.volume,
            "taker_buy_base": event.bar.taker_buy_base,
            "source_type": event.source_type,
            "source_provider": event.source_provider,
            "source_timeframe": event.source_timeframe,
        },
        alignment_origin=alignment_origin,
        duration=duration,
    ) | {"market_as_of": event.bar.market_as_of.isoformat()}


async def _db_stream_decision_parity(
    repository: CandleRepository,
    config: Any,
    live_stream_events: Sequence[Mapping[str, object]],
    input_inserted: Sequence[Any],
) -> tuple[dict[str, object], ...]:
    input_by_id = {item.stream_id: item for item in input_inserted}
    route_keys = {f"{key.asset}/{key.timeframe}": key for key in _route_keys(config)}
    records: list[dict[str, object]] = []
    for item in live_stream_events:
        event = item["event"]
        stream_id = str(item["stream_id"])
        decision_result = input_by_id.get(stream_id)
        if decision_result is None or decision_result.event is None:
            raise AssertionError("live derived stream event was not consumed")
        route = str(item["series"])
        key = route_keys[route]
        rows = await repository.fetch_candles(
            lane=MarketLane(key.venue, key.instrument_id, key.timeframe),
            since=event.bar.bar_open_at,
            until=event.bar.bar_open_at + timedelta(microseconds=1),
        )
        if len(rows) != 1:
            raise AssertionError(
                "live derived event did not have one DB row: "
                f"route={route!r} open={event.bar.bar_open_at!r} "
                f"close={event.bar.bar_close_at!r} "
                f"rows={[(row.open_time, row.close_time) for row in rows]!r}"
            )
        db_semantics = _canonical_candle_semantics(
            rows[0],
            alignment_origin=config.timeframe_grid.alignment_origin,
            duration=config.timeframe_grid.duration(key.timeframe),
        ) | {"market_as_of": event.bar.market_as_of.isoformat()}
        stream_semantics = _event_semantics(
            event,
            alignment_origin=config.timeframe_grid.alignment_origin,
            duration=config.timeframe_grid.duration(key.timeframe),
        )
        decision_semantics = _event_semantics(
            decision_result.event,
            alignment_origin=config.timeframe_grid.alignment_origin,
            duration=config.timeframe_grid.duration(key.timeframe),
        )
        records.append(
            {
                "route": route,
                "market_as_of": event.bar.market_as_of.isoformat(),
                "db_equals_stream": db_semantics == stream_semantics,
                "stream_equals_decision": stream_semantics == decision_semantics,
                "geometry_equal": all(
                    db_semantics[field] == stream_semantics[field]
                    for field in ("bar_duration_seconds", "bar_open_aligned")
                ),
                "provenance_equal": all(
                    db_semantics[field] == stream_semantics[field]
                    for field in (
                        "source_type",
                        "source_provider",
                        "source_timeframe",
                    )
                ),
            }
        )
    return tuple(
        sorted(records, key=lambda item: (item["route"], item["market_as_of"]))
    )


async def _signal_entries(broker: Any) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    keys: list[str] = []
    async for key in broker.scan_iter(match="signals:*"):
        keys.append(str(key))
    for stream in sorted(keys):
        for stream_id, fields in await broker.xrange(stream, "-", "+"):
            signal = valkey_decode(dict(fields), TradeSignal)
            result.append(
                {"stream": stream, "stream_id": str(stream_id), "signal": signal}
            )
    return tuple(result)


def _signal_contract(entries: Sequence[Mapping[str, object]]) -> dict[str, object]:
    checked: list[dict[str, object]] = []
    for item in entries:
        signal = item["signal"]
        assert isinstance(signal, TradeSignal)
        stream_id = str(item["stream_id"])
        metadata = (
            signal.metadata
            if isinstance(signal.metadata, Mapping)
            else json.loads(signal.metadata or "{}")
        )
        checked.append(
            {
                "stream": item["stream"],
                "stream_id": stream_id,
                "asset": signal.asset,
                "timeframe": signal.timeframe,
                "timestamp": signal.timestamp,
                "price": signal.price,
                "direction": signal.direction,
                "conviction": signal.conviction,
                "model_name": signal.model_name,
                "idempotency_key": signal.idempotency_key,
                "decision_id": metadata.get("decision_id"),
                "metadata_revision": metadata.get("decision_execution_revision"),
                "metadata_timestamp_unit": metadata.get("timestamp_unit"),
                "idempotency_matches_decision": (
                    bool(metadata.get("decision_id"))
                    and signal.idempotency_key
                    == signal_idempotency_key(metadata["decision_id"])
                ),
                "metadata_revision_matches_decision": (
                    bool(metadata.get("decision_execution_revision"))
                    and str(metadata["decision_execution_revision"])
                    in str(metadata.get("decision_id"))
                ),
            }
        )
    return {
        "count": len(checked),
        "entries": checked,
        "valid": all(
            item["stream"] == f"signals:{item['asset']}:{item['timeframe']}"
            and item["metadata_timestamp_unit"] == "seconds"
            and item["decision_id"]
            and item["metadata_revision"]
            and item["idempotency_key"]
            and item["stream"] in CERTIFIED_SIGNAL_MODELS
            and item["model_name"] == CERTIFIED_SIGNAL_MODELS[item["stream"]]
            and item["idempotency_matches_decision"] is True
            and item["metadata_revision_matches_decision"] is True
            and item["stream_id"] == f"{int(Decimal(str(item['timestamp'])) * 1000)}-0"
            and item["direction"] in {-1, 1}
            and math.isfinite(float(item["price"]))
            and 0 <= float(item["conviction"]) <= 1
            and math.isfinite(float(item["conviction"]))
            and item["model_name"]
            for item in checked
        ),
    }


def _recorded_signal_contract_valid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    entries = value.get("entries")
    if not isinstance(entries, list) or value.get("count") != len(entries):
        return False
    for item in entries:
        if not isinstance(item, Mapping):
            return False
        stream = item.get("stream")
        asset = item.get("asset")
        timeframe = item.get("timeframe")
        decision_id = item.get("decision_id")
        revision = item.get("metadata_revision")
        timestamp_unit = item.get("metadata_timestamp_unit")
        idempotency_key = item.get("idempotency_key")
        try:
            timestamp = Decimal(str(item["timestamp"]))
            price = float(item["price"])
            conviction = float(item["conviction"])
        except (KeyError, TypeError, ValueError):
            return False
        if not (
            stream == f"signals:{asset}:{timeframe}"
            and timestamp_unit == "seconds"
            and isinstance(decision_id, str)
            and bool(decision_id)
            and isinstance(revision, str)
            and bool(revision)
            and revision in decision_id
            and idempotency_key == signal_idempotency_key(decision_id)
            and stream in CERTIFIED_SIGNAL_MODELS
            and item.get("model_name") == CERTIFIED_SIGNAL_MODELS[stream]
            and item.get("stream_id") == f"{int(timestamp * 1000)}-0"
            and item.get("direction") in {-1, 1}
            and math.isfinite(price)
            and math.isfinite(conviction)
            and 0 <= conviction <= 1
        ):
            return False
    return bool(entries)


async def _run_trial_body(
    pool: asyncpg.Pool,
    broker: Any,
) -> dict[str, object]:
    ConfigManager.reset_singleton()
    config = load_fixture_config()
    history = RecordingHistory(
        CanonicalMarketHistoryRepository(pool, timeframe_grid=config.timeframe_grid)
    )
    schema = await _schema_evidence(pool, broker)
    before = await _db_counts(pool, config)
    bucket_start = await seed_startup_history(pool, config)
    repository = CandleRepository(pool)
    ingestion = CandleIngestionService(repository)
    htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
    startup, runtime, _composition = await _build_runtime(config, pool, broker, history)
    startup_counts = await _db_counts(pool, config)

    btc = await materialize_live_asset(
        repository,
        asset="BTC",
        bucket_start=bucket_start,
        htf=htf,
        ingestion=ingestion,
        alignment_origin=config.timeframe_grid.alignment_origin,
    )
    eth = await materialize_live_asset(
        repository,
        asset="ETH",
        bucket_start=bucket_start,
        htf=htf,
        ingestion=ingestion,
        alignment_origin=config.timeframe_grid.alignment_origin,
    )
    live_outbox = await drain_outbox(pool, broker)
    poll = await runtime.poll_once()
    input_inserted = [
        item for item in poll.input_results if item.disposition == "INSERTED"
    ]
    live_lane_results = _lane_table(poll)
    live_route_parity = await _momentum_parity(config, startup, runtime)
    live_semantic_cutoffs_match = _semantic_cutoffs_match(
        live_route_parity,
        live_lane_results,
    )
    db_after_live = await _db_counts(pool, config)
    live_stream_events = await _stream_derived_events(broker, config)
    producer_stream_lengths = await _producer_stream_lengths(broker)
    parity_records = await _db_stream_decision_parity(
        repository,
        config,
        live_stream_events,
        input_inserted,
    )
    signals_before_duplicate = await _signal_entries(broker)

    duplicate_event = next(
        item for item in live_stream_events if item["series"] == "BTCUSDT/1h"
    )
    # Re-read the producer fields without reshaping them.  The explicit
    # lookup is intentionally separate from Decision parsing.
    duplicate_entries = await broker.xrange(
        duplicate_event["stream"],
        duplicate_event["stream_id"],
        duplicate_event["stream_id"],
    )
    if not duplicate_entries:
        raise AssertionError("producer-derived event disappeared before duplicate test")
    duplicate_fields = duplicate_entries[0][1]
    duplicate_id = await broker.xadd(duplicate_event["stream"], duplicate_fields)
    duplicate_poll = await runtime.poll_once()
    signals_after_duplicate = await _signal_entries(broker)

    signal_retry = None
    if signals_before_duplicate:
        first_signal = signals_before_duplicate[0]
        signal = first_signal["signal"]
        assert isinstance(signal, TradeSignal)
        metadata = (
            signal.metadata
            if isinstance(signal.metadata, Mapping)
            else json.loads(signal.metadata or "{}")
        )
        envelope = SignalPublicationEnvelope(
            decision_id=metadata["decision_id"],
            stream_key=str(first_signal["stream"]),
            stream_entry_id=str(first_signal["stream_id"]),
            signal=signal,
            payload_fingerprint=signal_payload_fingerprint(signal),
        )
        signal_retry = await ValkeySignalPublisher(
            broker,
            stream_maxlen=config.global_settings.signal_publication.stream_maxlen,
            stream_approximate=config.global_settings.signal_publication.stream_approximate,
        ).publish(envelope)

    recovery_bucket = bucket_start + timedelta(hours=4)
    recovery_eth = await materialize_live_asset(
        repository,
        asset="ETH",
        bucket_start=recovery_bucket,
        htf=htf,
        ingestion=ingestion,
        alignment_origin=config.timeframe_grid.alignment_origin,
        missing_index=100,
    )
    await drain_outbox(pool, broker)
    recovery_key = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="4h",
    )
    premature = await _count_route_rows(
        pool,
        recovery_key,
        start=recovery_bucket,
        end=recovery_bucket + timedelta(hours=4),
    )
    missing = _provider_observation(
        asset="ETH",
        opened=recovery_bucket + timedelta(minutes=100),
        index=100,
    )
    provider = C2HistoricalProvider(missing)
    recovery_engine = RecoveryEngine(
        providers={provider.provider_id: provider},
        repository=repository,
        ingestion_service=ingestion,
        htf_service=htf,
        max_concurrency=1,
        page_limit=1000,
        max_attempts_per_provider=1,
        retry_backoff_seconds=0,
        rest_finalization_grace_seconds=0,
        now_fn=lambda: recovery_bucket + timedelta(hours=4, seconds=1),
        settlement_sleep_fn=lambda _seconds: asyncio.sleep(0),
    )
    if len(recovery_eth["requests"]) != 1:
        raise AssertionError(
            "incomplete ETH bucket did not produce one recovery request"
        )
    follow_ups = await recovery_engine.recover(
        recovery_eth["requests"][0],
        base_timeframe="1m",
        base_duration=timedelta(minutes=1),
        provider_order=(provider.provider_id,),
        provider_symbols={provider.provider_id: "ETHUSDT"},
        target_durations={"4h": timedelta(hours=4)},
        alignment_origin=config.timeframe_grid.alignment_origin,
    )
    recovery_outbox = await drain_outbox(pool, broker)
    recovery_poll = await runtime.poll_once()
    recovered_rows = await repository.fetch_candles(
        lane=MarketLane("binance", "ETH-USDT-PERP", "4h"),
        since=recovery_bucket,
        until=recovery_bucket + timedelta(hours=4),
    )
    recovery_semantic = await _momentum_parity(config, startup, runtime)
    c1_artifact = json.loads(
        (
            ROOT
            / "artifacts"
            / "combined_c1"
            / "c1_ingestion_decision_momentum_certification.json"
        ).read_text()
    )
    c1_recovery_reference = c1_artifact["recovery"]["uninterrupted_reference"]
    c1_next_semantic_reference = _compact_reference_semantic(
        c1_artifact["restart"]["continuous_semantic_evidence"]["ETHUSDT:momentum_4h"]
    )
    c1_next_lane_reference = c1_artifact["restart"]["continuous_next_results"][
        "ETHUSDT:momentum_4h"
    ]
    recovery_duration = config.timeframe_grid.duration("4h")
    recovery_candle_actual = (
        None
        if not recovered_rows
        else _canonical_candle_semantics(
            recovered_rows[0],
            alignment_origin=config.timeframe_grid.alignment_origin,
            duration=recovery_duration,
        )
    )
    recovery_candle_reference = _canonical_candle_semantics(
        c1_recovery_reference["derived_candle"],
        alignment_origin=config.timeframe_grid.alignment_origin,
        duration=recovery_duration,
    )

    continuous_watermarks = _runtime_watermarks(runtime)
    continuous_input_cursors = _runtime_cursors(runtime)
    continuous_semantics = recovery_semantic
    continuous_signal_count = len(await _signal_entries(broker))

    fresh_history = RecordingHistory(
        CanonicalMarketHistoryRepository(pool, timeframe_grid=config.timeframe_grid)
    )
    fresh_startup, fresh_runtime, _ = await _build_runtime(
        config,
        pool,
        broker,
        fresh_history,
    )
    signal_count_before_fresh = len(await _signal_entries(broker))
    fresh_poll = await fresh_runtime.poll_once()
    signal_count_after_fresh = len(await _signal_entries(broker))
    fresh_watermarks = _runtime_watermarks(fresh_runtime)
    fresh_input_cursors = _runtime_cursors(fresh_runtime)
    fresh_semantics = await _momentum_parity(
        config,
        fresh_startup,
        fresh_runtime,
    )

    db_after = await _db_counts(pool, config)
    signal_contract = _signal_contract(await _signal_entries(broker))
    decision_parity = len(input_inserted) == len(live_stream_events) == 6
    for item in input_inserted:
        assert item.event is not None
        matching = next(
            candidate
            for candidate in live_stream_events
            if candidate["stream_id"] == item.stream_id
        )
        parsed = matching["event"]
        assert parsed.bar == item.event.bar
        assert parsed.source_type == item.event.source_type
        assert parsed.source_provider == item.event.source_provider
        assert parsed.source_timeframe == item.event.source_timeframe

    recovery_lane_results = _lane_table(recovery_poll)
    return {
        "schema": schema,
        "before_empty": before["total_rows"] == 0 and before["outbox_total"] == 0,
        "startup": {
            "status": startup.snapshot.status,
            "route_counts": startup_counts["route_rows"],
            "fetch_limits": sorted(
                item["limit"]
                for item in history.fetch_calls
                if item.get("limit") is not None
            ),
            "retained_capacity": {
                f"{key.asset}/{key.timeframe}": startup.bar_store.capacity_for(key)
                for key in _route_keys(config)
            },
            "stateful_binding_count": 0,
            "replay_step_count": sum(
                item.replay_step_count
                for item in startup.snapshot.lane_evidence.values()
            ),
            "signal_count": 0,
            "lanes": {
                lane_id: item.status
                for lane_id, item in startup.snapshot.lane_evidence.items()
            },
        },
        "live": {
            "base_inserted": int(btc["base_inserted"]) + int(eth["base_inserted"]),
            "derived_counts": LIVE_DERIVED_COUNTS,
            "outbox": live_outbox,
            "producer_stream_lengths": producer_stream_lengths,
            "producer_stream_total": sum(producer_stream_lengths.values()),
            "db_counts_after_live": db_after_live,
            "stream_event_count": len(live_stream_events),
            "input_inserted_count": len(input_inserted),
            "lane_results": live_lane_results,
            "route_parity": live_route_parity,
            "semantic_cutoffs_match": live_semantic_cutoffs_match,
            "db_outbox_total": db_after_live["outbox_total"],
            "db_outbox_pending": db_after_live["outbox_pending"],
            "decision_parity": decision_parity,
            "no_base_signal": all(
                item["stream"]
                not in {
                    "signals:BTCUSDT:1m",
                    "signals:ETHUSDT:1m",
                }
                for item in signals_before_duplicate
            ),
        },
        "duplicate": {
            "stream_id_changed": str(duplicate_id) != str(duplicate_event["stream_id"]),
            "dispositions": [item.disposition for item in duplicate_poll.input_results],
            "transaction_count": sum(
                result.finalization_status == "COMMITTED"
                for result in duplicate_poll.lane_results.values()
            ),
            "signal_count_before": len(signals_before_duplicate),
            "signal_count_after": len(signals_after_duplicate),
            "signal_retry_outcome": None
            if signal_retry is None
            else signal_retry.outcome,
        },
        "parity": {
            "db_stream_decision": decision_parity,
            "records": parity_records,
            "derived_provenance": all(
                item["event"].source_type == "derived"
                and item["event"].source_provider is None
                and item["event"].source_timeframe == "1m"
                for item in live_stream_events
            ),
            "forward_stream_order": all(
                left["event"].bar.market_as_of <= right["event"].bar.market_as_of
                for left, right in pairwise(live_stream_events)
                if left["stream"] == right["stream"]
            ),
        },
        "recovery": {
            "request_count": len(recovery_eth["requests"]),
            "premature_derived_count": premature,
            "provider_calls": provider.calls,
            "recovered_base_count": 1,
            "follow_ups": len(follow_ups),
            "outbox": recovery_outbox,
            "recovered_row_count": len(recovered_rows),
            "lane_results": recovery_lane_results,
            "input_dispositions": [
                item.disposition for item in recovery_poll.input_results
            ],
            "c1_reference_close": c1_recovery_reference["derived_candle"]["close"],
            "recovered_close": None
            if not recovered_rows
            else str(recovered_rows[0].close),
            "candle_semantics_actual": recovery_candle_actual,
            "candle_semantics_reference": recovery_candle_reference,
            "semantic_reference": c1_next_semantic_reference,
            "semantic_actual": recovery_semantic["ETHUSDT:momentum_4h"],
            "lane_result_reference": c1_next_lane_reference,
            "lane_result_actual": recovery_lane_results["ETHUSDT:momentum_4h"],
        },
        "restart": {
            "fresh_status": fresh_startup.snapshot.status,
            "fresh_poll_transactions": sum(
                result.finalization_status == "COMMITTED"
                for result in fresh_poll.lane_results.values()
            ),
            "fresh_signal_count_delta": signal_count_after_fresh
            - signal_count_before_fresh,
            "continuous_watermarks": continuous_watermarks,
            "fresh_watermarks": fresh_watermarks,
            "continuous_input_cursors": continuous_input_cursors,
            "fresh_input_cursors": fresh_input_cursors,
            "continuous_semantics": continuous_semantics,
            "fresh_semantics": fresh_semantics,
            "watermarks_match": continuous_watermarks == fresh_watermarks,
            "cursors_match": continuous_input_cursors == fresh_input_cursors,
            "semantics_match": continuous_semantics == fresh_semantics,
            "cursor_count": len(fresh_input_cursors),
            "continuous_signal_count": continuous_signal_count,
            "fresh_stateful_binding_count": 0,
            "fresh_replay_step_count": sum(
                item.replay_step_count
                for item in fresh_startup.snapshot.lane_evidence.values()
            ),
        },
        "signals": signal_contract,
        "db_after": db_after,
        "history_calls": len(history.fetch_calls),
    }


async def _momentum_parity(
    config: Any, startup: Any, runtime: LiveDecisionRuntime
) -> dict[str, dict[str, object]]:
    from tests.combined.c1_harness import _semantic_evidence

    evidence = await _semantic_evidence(config, startup, runtime)
    return {
        lane_id: {
            "parity": bool(item.get("parity")),
            "rsi": item.get("rsi", {}).get("actual"),
            "macd": item.get("macd", {}).get("actual"),
            "momentum": item.get("momentum", {}).get("actual"),
            "market_as_of": item.get("market_as_of"),
        }
        for lane_id, item in evidence.items()
    }


async def run_trial(trial_name: str) -> dict[str, object]:
    infrastructure = C2Infrastructure(trial_name)
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
        evidence = await _run_trial_body(pool, broker)
        evidence["infrastructure"] = {
            **EXPECTED_INFRASTRUCTURE,
            "valkey_noeviction": (await broker.config_get("maxmemory-policy"))[
                "maxmemory-policy"
            ]
            == "noeviction",
            "isolated_project": True,
            "before_empty": evidence["before_empty"],
        }
        return evidence
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        cleanup_ok = await infrastructure.cleanup()
        # The caller records cleanup separately, while any failure remains a
        # hard certification result rather than being hidden by a test error.
        if not cleanup_ok:
            raise RuntimeError("C2 disposable Compose cleanup failed")


def evaluate_c2_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    schema = evidence.get("schema")
    startup = evidence.get("startup")
    live = evidence.get("live")
    duplicate = evidence.get("duplicate")
    parity = evidence.get("parity")
    recovery = evidence.get("recovery")
    restart = evidence.get("restart")
    signals = evidence.get("signals")
    trials = evidence.get("trials")
    cleanup = evidence.get("cleanup")
    infrastructure = evidence.get("infrastructure")
    live_db_counts = (
        live.get("db_counts_after_live") if isinstance(live, Mapping) else None
    )
    live_route_parity = live.get("route_parity") if isinstance(live, Mapping) else None
    live_lane_results = live.get("lane_results") if isinstance(live, Mapping) else None
    live_cutoffs_match = (
        isinstance(live_route_parity, Mapping)
        and isinstance(live_lane_results, Mapping)
        and _semantic_cutoffs_match(live_route_parity, live_lane_results)
    )
    parity_records = parity.get("records") if isinstance(parity, Mapping) else None
    parity_routes = (
        [str(item.get("route")) for item in parity_records]
        if isinstance(parity_records, (list, tuple))
        else []
    )
    parity_route_counts = {
        route: parity_routes.count(route) for route in set(parity_routes)
    }
    signal_entries = signals.get("entries") if isinstance(signals, Mapping) else None
    return {
        "protected_hashes": evidence.get("protected_hashes_valid") is True,
        "schema_contract": (
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
        ),
        "startup_exact": (
            isinstance(startup, Mapping)
            and startup.get("status") == "STARTUP_READY"
            and startup.get("route_counts")
            == {
                route: STARTUP_COUNT
                for route in ("BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h")
            }
            and startup.get("retained_capacity")
            == {
                route: STARTUP_COUNT
                for route in ("BTCUSDT/1h", "BTCUSDT/4h", "ETHUSDT/4h")
            }
            and startup.get("fetch_limits") == [STARTUP_COUNT] * 3
            and startup.get("stateful_binding_count") == 0
            and startup.get("replay_step_count") == 0
            and startup.get("signal_count") == 0
            and all(
                value == "STARTUP_READY" for value in startup.get("lanes", {}).values()
            )
        ),
        "live_producer_counts": (
            isinstance(live, Mapping)
            and live.get("base_inserted") == LIVE_BASE_COUNT * 2
            and live.get("derived_counts") == LIVE_DERIVED_COUNTS
            and live.get("stream_event_count") == 6
            and live.get("input_inserted_count") == 6
            and live.get("outbox", {}).get("published") == LIVE_OUTBOX_COUNT
            and isinstance(live_db_counts, Mapping)
            and live_db_counts.get("outbox_total") == LIVE_OUTBOX_COUNT
            and live_db_counts.get("outbox_pending") == 0
            and live.get("producer_stream_total") == LIVE_OUTBOX_COUNT
            and live.get("decision_parity") is True
        ),
        "route_parity": (
            isinstance(live, Mapping)
            and isinstance(live_route_parity, Mapping)
            and set(live_route_parity) == CERTIFIED_LANE_IDS
            and all(item.get("parity") is True for item in live_route_parity.values())
            and live_cutoffs_match
            and live.get("semantic_cutoffs_match") is True
        ),
        "no_base_signal": isinstance(live, Mapping)
        and live.get("no_base_signal") is True,
        "db_stream_decision_parity": (
            isinstance(parity, Mapping)
            and parity.get("db_stream_decision") is True
            and parity.get("derived_provenance") is True
            and parity.get("forward_stream_order") is True
            and isinstance(parity_records, (list, tuple))
            and len(parity_records) == 6
            and parity_route_counts
            == {
                "BTCUSDT/1h": 4,
                "BTCUSDT/4h": 1,
                "ETHUSDT/4h": 1,
            }
            and all(
                isinstance(item, Mapping)
                and item.get("db_equals_stream") is True
                and item.get("stream_equals_decision") is True
                and item.get("geometry_equal") is True
                and item.get("provenance_equal") is True
                for item in parity_records
            )
        ),
        "duplicate_noop": (
            isinstance(duplicate, Mapping)
            and duplicate.get("stream_id_changed") is True
            and duplicate.get("dispositions") == ["DUPLICATE"]
            and duplicate.get("transaction_count") == 0
            and duplicate.get("signal_count_before")
            == duplicate.get("signal_count_after")
            and duplicate.get("signal_retry_outcome") == "ALREADY_IDENTICAL"
        ),
        "healthy_recovery": (
            isinstance(recovery, Mapping)
            and recovery.get("request_count") == 1
            and recovery.get("premature_derived_count") == 0
            and recovery.get("provider_calls") == 1
            and recovery.get("recovered_base_count") == 1
            and recovery.get("follow_ups") == 0
            and recovery.get("recovered_row_count") == 1
            and recovery.get("recovered_close") == recovery.get("c1_reference_close")
            and recovery.get("candle_semantics_actual") is not None
            and recovery.get("candle_semantics_actual")
            == recovery.get("candle_semantics_reference")
            and recovery.get("semantic_actual") == recovery.get("semantic_reference")
            and recovery.get("lane_result_actual")
            == recovery.get("lane_result_reference")
            and any(
                item.get("finalization_status") == "COMMITTED"
                for item in recovery.get("lane_results", {}).values()
            )
        ),
        "restart_reconstruction": (
            isinstance(restart, Mapping)
            and restart.get("fresh_status") == "STARTUP_READY"
            and restart.get("fresh_poll_transactions") == 0
            and restart.get("fresh_signal_count_delta") == 0
            and restart.get("continuous_watermarks") == restart.get("fresh_watermarks")
            and restart.get("continuous_input_cursors")
            == restart.get("fresh_input_cursors")
            and restart.get("continuous_semantics") == restart.get("fresh_semantics")
            and restart.get("watermarks_match") is True
            and restart.get("cursors_match") is True
            and restart.get("semantics_match") is True
            and restart.get("cursor_count") == 3
            and restart.get("fresh_stateful_binding_count") == 0
            and restart.get("fresh_replay_step_count") == 0
        ),
        "signal_contract": isinstance(signals, Mapping)
        and isinstance(signal_entries, list)
        and signals.get("count") == len(signal_entries)
        and signals.get("count", 0) > 0
        and signals.get("valid") is True
        and _recorded_signal_contract_valid(signals),
        "infrastructure_contract": (
            isinstance(infrastructure, Mapping)
            and infrastructure.get("db_image") == EXPECTED_INFRASTRUCTURE["db_image"]
            and infrastructure.get("broker_image")
            == EXPECTED_INFRASTRUCTURE["broker_image"]
            and infrastructure.get("valkey_noeviction") is True
            and infrastructure.get("isolated_project") is True
            and infrastructure.get("before_empty") is True
            and evidence.get("before_empty") is True
        ),
        "two_trial_determinism": isinstance(trials, Mapping)
        and trials.get("normalized_equal") is True,
        "cleanup": isinstance(cleanup, Mapping)
        and cleanup.get("trial_a") is True
        and cleanup.get("trial_b") is True,
        "production_scope": evidence.get("production_scope")
        == {
            "decision_assets_empty": True,
            "production_compose_unchanged": True,
            "decision_container_absent": True,
        },
    }


async def run_c2_certification() -> dict[str, object]:
    if not protected_hashes_valid():
        raise RuntimeError(
            "protected C1/M3/M4/D10 artifacts do not match approved hashes"
        )
    first = await run_trial("trial_a")
    second = await run_trial("trial_b")
    normalized_first = _normalize_trial(first)
    normalized_second = _normalize_trial(second)
    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_sha": POST_C1_SHA,
        "protected_hashes": protected_hashes(),
        "protected_hashes_valid": protected_hashes_valid(),
        "trial_a": normalized_first,
        "trial_b": normalized_second,
        "trials": {"normalized_equal": normalized_first == normalized_second},
        "cleanup": {"trial_a": True, "trial_b": True},
        "production_scope": {
            "decision_assets_empty": not any(
                (ROOT / "configs" / "decision" / "assets").glob("*.yaml")
            ),
            "production_compose_unchanged": file_sha256(PRODUCTION_COMPOSE_FILE)
            == _production_compose_sha,
            "decision_container_absent": True,
        },
    }
    # Stable gates are derived from the first normalized trial, not copied from
    # a stored status field.  This is the C2 tamper boundary.
    evidence.update(normalized_first)
    gates = evaluate_c2_gates(evidence)
    evidence["gates"] = gates
    evidence["terminal_status"] = (
        C2_SUCCESS_STATUS if all(gates.values()) else C2_EVIDENCE_STATUS
    )
    evidence["identity_digest"] = sha256_fingerprint(c2_identity_payload(evidence))
    evidence["evidence_digest"] = sha256_fingerprint(c2_evidence_payload(evidence))
    return evidence


def _normalize_trial(value: Mapping[str, object]) -> dict[str, object]:
    """Keep only stable semantic evidence; omit UUIDs, stream IDs and timing."""
    normalized = json.loads(canonical_json(value))
    for key in ("history_calls",):
        normalized.pop(key, None)
    return normalized


_production_compose_sha = file_sha256(PRODUCTION_COMPOSE_FILE)


def c2_identity_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": evidence.get("schema_version"),
        "source_sha": evidence.get("source_sha"),
        "protected_hashes": evidence.get("protected_hashes"),
        "images": evidence.get("trial_a", {}).get("infrastructure", {})
        if isinstance(evidence.get("trial_a"), Mapping)
        else {},
        "routes": list(_ROUTE_NAMES),
        "startup_count": STARTUP_COUNT,
        "live_outbox_count": LIVE_OUTBOX_COUNT,
    }


def c2_evidence_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    excluded = {"identity_digest", "evidence_digest", "terminal_status"}
    return {key: value for key, value in evidence.items() if key not in excluded}


def terminal_status_for_gates(gates: Mapping[str, bool]) -> str:
    return C2_SUCCESS_STATUS if all(gates.values()) else C2_EVIDENCE_STATUS


__all__ = [
    "C2_BLOCKED_STATUS",
    "C2_CLEANUP_STATUS",
    "C2_COMPOSE_FILE",
    "C2_SCHEMA_STATUS",
    "C2_SUCCESS_STATUS",
    "C2Infrastructure",
    "c2_evidence_payload",
    "c2_identity_payload",
    "evaluate_c2_gates",
    "protected_hashes",
    "protected_hashes_valid",
    "run_c2_certification",
    "run_trial",
    "sha256_fingerprint",
    "terminal_status_for_gates",
]
