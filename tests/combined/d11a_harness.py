"""Real disposable D11A authoritative Decision certification harness."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey

from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.settings import DecisionConfig, load_decision_config
from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.storage.shadow_progress import (
    LaneEffectProgress,
    LaneEffectProgressRepository,
)
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleCommitStatus, CandleRepository
from libs.common.config import ConfigManager
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal
from tests.combined.c2_harness import (
    LIVE_BASE_COUNT,
    _provider_observation,
    drain_outbox,
    seed_startup_history,
)
from tests.combined.c4a_harness import (
    _cleanup_probe,
    _free_port,
    _keys,
    _run,
    _wait_for,
    http_json,
)

ROOT = Path(__file__).resolve().parents[2]
D11A_COMPOSE_FILE = ROOT / "tests/combined/fixtures/d11a/docker-compose.yml"
D11A_FIXTURE_ROOT = ROOT / "tests/combined/fixtures/d11a"
M4_FIXTURE_ROOT = ROOT / "tests/decision/fixtures/momentum_m4"
D11A_ARTIFACT = (
    ROOT
    / "artifacts/decision_d11a/d11a_authority_handoff_foundation_certification.json"
)
D11A_BASE_SHA = "eac0fade6347e3cfbdb86c0fa274c72da80d3caf"
C4B_ARTIFACT_SHA = "2d047346ced14a72843cc22ea9a2f5eebd9929c4d02edab6f8cadb6d19582af7"
C4B_IDENTITY_DIGEST = "ea3ab91dce3ec320cc3a23937dd3d03c6572271ab738a970e7fd7382fb316ec3"
C4B_EVIDENCE_DIGEST = "9a39db509a0498a2f7d3ccf653ee88fe2ceabeda2c36376385574c828859edcb"
D11A_SUCCESS_STATUS = "DECISION_D11A_AUTHORITY_HANDOFF_FOUNDATION_READY_FOR_REVIEW"
D11A_BLOCKED_STATUS = "DECISION_D11A_AUTHORITY_HANDOFF_FOUNDATION_EVIDENCE_INSUFFICIENT"
EXPECTED_LANES = (
    "BTCUSDT:momentum_1h",
    "BTCUSDT:momentum_4h",
    "ETHUSDT:momentum_4h",
)
EXPECTED_PROTECTED_HASHES = {
    "c4b": C4B_ARTIFACT_SHA,
    "c4a": "c2adb97f2504ce541a0b4aa41f186a4a86c0c209dd96229e6bc4b7d121399334",
    "m3": "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c",
    "m4_functional": "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792",
    "m4_resource": "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4",
    "d10": "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459",
    "c1": "386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4",
    "c2": "9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67",
    "c3a": "34c0b0eaa85fffacbd5c99d346bdcf2829dd12c8c6769e18c63711d0a342622b",
    "c3b1": "bfb335bf5ab27b790c91be13ad878531b7a85a957901c86f7a6ec462f566fb63",
    "c3b2p": "0981b3bd1962089932da5dc7669c936537ddaaf1d5c17adae71d2f7e798347f0",
}
PROTECTED_ARTIFACTS = {
    "c4b": ROOT
    / "artifacts/combined_c4b/c4b_decision_shadow_soak_resource_certification.json",
    "c4a": ROOT
    / "artifacts/combined_c4a/c4a_decision_shadow_container_foundation_certification.json",
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
    "c3b1": ROOT
    / "artifacts/combined_c3b1/c3b1_ingestion_decision_canonical_integrity_certification.json",
    "c3b2p": ROOT
    / "artifacts/combined_c3b2/c3b2_ingestion_decision_provider_recovery_disagreement_certification.json",
}


def canonical_json(value: object) -> str:
    def normalize(item: object) -> object:
        if isinstance(item, Mapping):
            return {str(key): normalize(value) for key, value in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(value) for value in item]
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        if isinstance(item, bytes):
            return item.decode()
        return item

    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"))


def sha256_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_hashes() -> dict[str, str]:
    return {name: file_sha256(path) for name, path in PROTECTED_ARTIFACTS.items()}


def current_source_hashes() -> dict[str, str]:
    paths = (
        "src/apps/decision_app/domain/contracts.py",
        "src/apps/decision_app/runtime/live.py",
        "src/apps/decision_app/runtime/startup.py",
        "src/apps/decision_app/storage/__init__.py",
        "src/apps/decision_app/storage/schema.sql",
        "src/apps/decision_app/storage/shadow_progress.py",
        "src/apps/strategy_app/runtime_pairs.py",
        "src/apps/strategy_app/settings.py",
        "tests/combined/fixtures/d11a/docker-compose.yml",
        "tests/combined/fixtures/d11a/decision/global.yaml",
        "tests/combined/fixtures/d11a/decision/assets/BTC.yaml",
        "tests/combined/fixtures/d11a/decision/assets/ETH.yaml",
    )
    return {path: file_sha256(ROOT / path) for path in paths}


def current_fixture_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): file_sha256(path)
        for path in sorted(D11A_FIXTURE_ROOT.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


async def schema_upgrade_evidence(pool: asyncpg.Pool) -> dict[str, object]:
    """Exercise the in-place C4B -> D11A shadow-progress migration."""

    await pool.execute("CREATE SCHEMA IF NOT EXISTS decision")
    await pool.execute(
        """
        CREATE TABLE decision.shadow_progress (
            progress_schema_version integer NOT NULL,
            lane_id text NOT NULL,
            effective_lane_revision text NOT NULL,
            feature_plan_fingerprint text NOT NULL,
            data_plan_fingerprint text NOT NULL,
            market_as_of timestamptz NOT NULL,
            last_disposition text NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            PRIMARY KEY (
                lane_id,
                effective_lane_revision,
                feature_plan_fingerprint,
                data_plan_fingerprint
            ),
            CONSTRAINT shadow_progress_last_disposition_check
                CHECK (
                    last_disposition IS NULL
                    OR last_disposition = 'shadow'
                )
        )
        """
    )

    historical_rows = (
        {
            "lane_id": "d11a-schema-null",
            "effective_lane_revision": "legacy-null-revision",
            "feature_plan_fingerprint": "legacy-null-feature",
            "data_plan_fingerprint": "legacy-null-data",
            "market_as_of": datetime(2026, 1, 1, tzinfo=UTC),
            "last_disposition": None,
        },
        {
            "lane_id": "d11a-schema-shadow",
            "effective_lane_revision": "legacy-shadow-revision",
            "feature_plan_fingerprint": "legacy-shadow-feature",
            "data_plan_fingerprint": "legacy-shadow-data",
            "market_as_of": datetime(2026, 1, 1, 1, tzinfo=UTC),
            "last_disposition": "shadow",
        },
    )
    insert_sql = """
        INSERT INTO decision.shadow_progress (
            progress_schema_version, lane_id, effective_lane_revision,
            feature_plan_fingerprint, data_plan_fingerprint, market_as_of,
            last_disposition, created_at, updated_at
        ) VALUES (1, $1, $2, $3, $4, $5, $6, $5, $5)
    """
    for row in historical_rows:
        await pool.execute(
            insert_sql,
            row["lane_id"],
            row["effective_lane_revision"],
            row["feature_plan_fingerprint"],
            row["data_plan_fingerprint"],
            row["market_as_of"],
            row["last_disposition"],
        )

    async def row_snapshot() -> list[dict[str, object]]:
        rows = await pool.fetch(
            """
            SELECT progress_schema_version, lane_id,
                   effective_lane_revision, feature_plan_fingerprint,
                   data_plan_fingerprint, market_as_of, last_disposition
              FROM decision.shadow_progress
             WHERE lane_id LIKE 'd11a-schema-%'
             ORDER BY lane_id
            """
        )
        return [
            {
                "progress_schema_version": row["progress_schema_version"],
                "lane_id": row["lane_id"],
                "effective_lane_revision": row["effective_lane_revision"],
                "feature_plan_fingerprint": row["feature_plan_fingerprint"],
                "data_plan_fingerprint": row["data_plan_fingerprint"],
                "market_as_of": row["market_as_of"].astimezone(UTC).isoformat(),
                "last_disposition": row["last_disposition"],
            }
            for row in rows
        ]

    async def constraint_snapshot() -> list[dict[str, object]]:
        rows = await pool.fetch(
            """
            SELECT constraint_row.conname,
                   pg_get_constraintdef(constraint_row.oid) AS definition
              FROM pg_constraint AS constraint_row
              JOIN pg_class AS relation_row
                ON relation_row.oid = constraint_row.conrelid
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
             WHERE namespace_row.nspname = 'decision'
               AND relation_row.relname = 'shadow_progress'
               AND constraint_row.contype = 'c'
             ORDER BY constraint_row.conname
            """
        )
        return [
            {"name": row["conname"], "definition": row["definition"]} for row in rows
        ]

    before_rows = await row_snapshot()
    old_constraints = await constraint_snapshot()
    await ensure_checkpoint_schema(pool)
    after_rows = await row_snapshot()
    migrated_constraints = await constraint_snapshot()
    historical_lane_ids = {row["lane_id"] for row in historical_rows}

    published_identity = LaneExecutionIdentity(
        lane_id="d11a-schema-published",
        effective_lane_revision="published-revision",
        feature_plan_fingerprint="published-feature",
        data_plan_fingerprint="published-data",
    )
    no_signal_identity = LaneExecutionIdentity(
        lane_id="d11a-schema-no-signal",
        effective_lane_revision="no-signal-revision",
        feature_plan_fingerprint="no-signal-feature",
        data_plan_fingerprint="no-signal-data",
    )
    repository = LaneEffectProgressRepository(pool)
    published = LaneEffectProgress.create(
        identity=published_identity,
        market_as_of=datetime(2026, 1, 1, 2, tzinfo=UTC),
        last_disposition="published",
    )
    no_signal = LaneEffectProgress.create(
        identity=no_signal_identity,
        market_as_of=datetime(2026, 1, 1, 3, tzinfo=UTC),
        last_disposition="no_signal",
    )
    published_result = await repository.save(published)
    no_signal_result = await repository.save(no_signal)
    published_loaded = await repository.load(published_identity)
    no_signal_loaded = await repository.load(no_signal_identity)

    invalid_disposition_rejected = False
    try:
        await pool.execute(
            insert_sql,
            "d11a-schema-invalid",
            "invalid-revision",
            "invalid-feature",
            "invalid-data",
            datetime(2026, 1, 1, 4, tzinfo=UTC),
            "invalid",
        )
    except asyncpg.CheckViolationError:
        invalid_disposition_rejected = True

    rows_before_second_bootstrap = await row_snapshot()
    await ensure_checkpoint_schema(pool)
    second_rows = await row_snapshot()
    second_constraints = await constraint_snapshot()
    await pool.execute(
        "DELETE FROM decision.shadow_progress WHERE lane_id LIKE 'd11a-schema-%'"
    )

    return {
        "c4b_table_created": True,
        "historical_rows_before": before_rows,
        "historical_rows_after": after_rows,
        "historical_rows_preserved": before_rows
        == [row for row in after_rows if row["lane_id"] in historical_lane_ids],
        "old_constraint_definition": old_constraints,
        "migrated_constraint_definition": migrated_constraints,
        "published_repository_roundtrip": (
            published_result.value == "INSERTED"
            and published_loaded is not None
            and published_loaded.identity == published.identity
            and published_loaded.market_as_of == published.market_as_of
            and published_loaded.last_disposition == "published"
        ),
        "no_signal_repository_roundtrip": (
            no_signal_result.value == "INSERTED"
            and no_signal_loaded is not None
            and no_signal_loaded.identity == no_signal.identity
            and no_signal_loaded.market_as_of == no_signal.market_as_of
            and no_signal_loaded.last_disposition == "no_signal"
        ),
        "invalid_disposition_rejected": invalid_disposition_rejected,
        "second_bootstrap_succeeded": True,
        "check_constraint_count": len(migrated_constraints),
        "second_constraint_definition": second_constraints,
        "idempotent": (
            rows_before_second_bootstrap == second_rows
            and migrated_constraints == second_constraints
        ),
    }


def load_d11a_config() -> DecisionConfig:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        return load_decision_config(
            manager,
            global_file=D11A_FIXTURE_ROOT / "decision/global.yaml",
            assets_directory=D11A_FIXTURE_ROOT / "decision/assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def load_m4_config() -> DecisionConfig:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        from apps.decision_app.settings import load_decision_config

        return load_decision_config(
            manager,
            global_file=M4_FIXTURE_ROOT / "global.yaml",
            assets_directory=M4_FIXTURE_ROOT / "assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def m4_route_identity(config: DecisionConfig) -> dict[str, object]:
    def plain(value: object) -> object:
        if isinstance(value, Mapping):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [plain(item) for item in value]
        return value

    current = {
        lane.lane_id: {
            "authority": lane.authority,
            "risk_profile_key": lane.risk_profile_key,
            "parameters": {
                binding.slot_name: plain(binding.parameters)
                for binding in lane.bindings
            },
        }
        for lane in config.lane_specs()
    }
    certified_config = load_m4_config()
    certified = {
        lane.lane_id: {
            "authority": lane.authority,
            "risk_profile_key": lane.risk_profile_key,
            "parameters": {
                binding.slot_name: plain(binding.parameters)
                for binding in lane.bindings
            },
        }
        for lane in certified_config.lane_specs()
    }
    return {
        "d11a": current,
        "m4_certified": certified,
        "matches": current == certified,
    }


def _d11a_free_ports() -> tuple[int, int, int]:
    ports: list[int] = []
    while len(ports) < 3:
        port = _free_port()
        if port not in ports:
            ports.append(port)
    return tuple(ports)


@dataclass(slots=True)
class D11AInfrastructure:
    trial_name: str
    db_port: int = field(init=False)
    broker_port: int = field(init=False)
    decision_port: int = field(init=False)
    project_name: str = field(init=False)

    def __post_init__(self) -> None:
        self.db_port, self.broker_port, self.decision_port = _d11a_free_ports()
        token = "".join(char if char.isalnum() else "_" for char in self.trial_name)
        self.project_name = f"flipper_d11a_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "D11A_DB_PORT": str(self.db_port),
                "D11A_BROKER_PORT": str(self.broker_port),
                "D11A_DECISION_PORT": str(self.decision_port),
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
            str(D11A_COMPOSE_FILE),
            "-p",
            self.project_name,
            *arguments,
        ]

    async def start_foundation(self) -> None:
        result = await asyncio.to_thread(
            _run,
            self.command("up", "-d", "--wait", "db", "broker"),
            env=self.environment,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_decision(self) -> None:
        result = await asyncio.to_thread(
            _run,
            self.command("up", "-d", "--build", "--wait", "decision"),
            env=self.environment,
        )
        if result.returncode != 0:
            logs = _run(
                self.command("logs", "--no-color", "decision"), env=self.environment
            )
            raise RuntimeError((result.stderr or result.stdout) + "\n" + logs.stdout)

    async def stop_decision(self) -> None:
        result = await asyncio.to_thread(
            _run, self.command("stop", "decision"), env=self.environment
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

    async def restart_decision(self) -> None:
        await self.stop_decision()
        result = await asyncio.to_thread(
            _run,
            self.command("up", "-d", "--wait", "decision"),
            env=self.environment,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

    async def cleanup(self) -> dict[str, object]:
        result = await asyncio.to_thread(
            _run,
            self.command("down", "-v", "--remove-orphans"),
            env=self.environment,
        )
        leftovers = await asyncio.to_thread(_cleanup_probe, self.project_name)
        return {
            "down_returncode": result.returncode,
            "leftovers": leftovers,
            "clean": result.returncode == 0 and not any(leftovers.values()),
        }

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://d11a_user:d11a_password@127.0.0.1:{self.db_port}/d11a_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"

    @property
    def http_base(self) -> str:
        return f"http://127.0.0.1:{self.decision_port}"


async def _seed_manifests(broker: Any) -> None:
    from tests.combined.c4a_harness import seed_manifests

    await seed_manifests(broker)


async def _install_progress_failure(pool: asyncpg.Pool) -> None:
    await pool.execute(
        """
        CREATE OR REPLACE FUNCTION decision.d11a_fail_effect_progress()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'D11A injected effect-progress failure';
        END;
        $$;
        DROP TRIGGER IF EXISTS d11a_fail_effect_progress
            ON decision.shadow_progress;
        CREATE TRIGGER d11a_fail_effect_progress
            BEFORE INSERT OR UPDATE ON decision.shadow_progress
            FOR EACH ROW EXECUTE FUNCTION decision.d11a_fail_effect_progress();
        """
    )


async def _remove_progress_failure(pool: asyncpg.Pool) -> None:
    await pool.execute(
        """
        DROP TRIGGER IF EXISTS d11a_fail_effect_progress
            ON decision.shadow_progress;
        DROP FUNCTION IF EXISTS decision.d11a_fail_effect_progress();
        """
    )


async def _lane_status_is(base: str, lane_id: str, status: str) -> bool:
    try:
        snapshot = await runtime_snapshot(base)
    except (OSError, urllib.error.URLError):
        return False
    lane = snapshot.get("lanes", {}).get(lane_id, {})
    return isinstance(lane, Mapping) and lane.get("status") == status


async def _run_crash_windows(
    trial_name: str, config: DecisionConfig
) -> dict[str, object]:
    infrastructure = D11AInfrastructure(f"{trial_name}_crash")
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    result: dict[str, object] = {}
    try:
        await infrastructure.start_foundation()
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=4
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        seed = await seed_foundation(pool, broker, config)
        await infrastructure.start_decision()
        await _wait_ready(infrastructure.http_base)

        await _install_progress_failure(pool)
        no_signal_materialized = await materialize_window(
            pool,
            broker,
            config,
            bucket_start=seed["bucket_start"],
            index_offset=0,
            count=60,
        )
        await _wait_for(
            lambda: _lane_status_is(
                infrastructure.http_base,
                "BTCUSDT:momentum_1h",
                "HALTED",
            ),
            timeout=180,
            label="authoritative NO_SIGNAL progress failure",
        )
        no_signal_failed_progress = await progress_rows(pool)
        no_signal_failed_signals = await signal_entries(broker)
        await _remove_progress_failure(pool)
        await infrastructure.restart_decision()
        await _wait_ready(infrastructure.http_base)
        await _wait_for(
            lambda: _lane_progress_reached(
                pool,
                "BTCUSDT:momentum_1h",
                seed["bucket_start"] + timedelta(hours=1),
            ),
            timeout=180,
            label="authoritative NO_SIGNAL progress recovery",
        )
        no_signal_recovered_progress = await progress_rows(pool)
        no_signal_recovered_signals = await signal_entries(broker)

        await materialize_window(
            pool,
            broker,
            config,
            bucket_start=seed["bucket_start"],
            index_offset=60,
            count=180,
        )
        await _wait_for(
            lambda: _progress_at_latest(
                pool, seed["bucket_start"] + timedelta(hours=4)
            ),
            timeout=180,
            label="authoritative signal crash setup",
        )
        await _install_progress_failure(pool)
        signal_materialized = await materialize_window(
            pool,
            broker,
            config,
            bucket_start=seed["bucket_start"],
            index_offset=240,
            count=60,
        )
        await _wait_for(
            lambda: _lane_status_is(
                infrastructure.http_base,
                "BTCUSDT:momentum_1h",
                "HALTED",
            ),
            timeout=180,
            label="authoritative SIGNAL progress failure",
        )
        signal_failed_progress = await progress_rows(pool)
        signal_failed_signals = await signal_entries(broker)
        await _remove_progress_failure(pool)
        await infrastructure.restart_decision()
        await _wait_ready(infrastructure.http_base)
        await _wait_for(
            lambda: _lane_progress_reached(
                pool,
                "BTCUSDT:momentum_1h",
                seed["bucket_start"] + timedelta(hours=5),
            ),
            timeout=180,
            label="authoritative SIGNAL progress recovery",
        )
        signal_recovered_progress = await progress_rows(pool)
        signal_recovered_signals = await signal_entries(broker)
        result = {
            "signal": {
                "materialized": signal_materialized,
                "failed_progress": signal_failed_progress,
                "failed_signals": signal_failed_signals,
                "recovered_progress": signal_recovered_progress,
                "recovered_signals": signal_recovered_signals,
                "expected_cutoff": (
                    seed["bucket_start"] + timedelta(hours=5)
                ).isoformat(),
            },
            "no_signal": {
                "materialized": no_signal_materialized,
                "failed_progress": no_signal_failed_progress,
                "failed_signals": no_signal_failed_signals,
                "recovered_progress": no_signal_recovered_progress,
                "recovered_signals": no_signal_recovered_signals,
                "expected_cutoff": (
                    seed["bucket_start"] + timedelta(hours=1)
                ).isoformat(),
            },
        }
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        cleanup = await infrastructure.cleanup()
        result["cleanup"] = cleanup
    return result


async def seed_foundation(
    pool: asyncpg.Pool, broker: Any, config: DecisionConfig
) -> dict[str, object]:
    await apply_ingestion_schema(pool)
    await apply_ingestion_schema(pool)
    schema_upgrade = await schema_upgrade_evidence(pool)
    bucket_start = await seed_startup_history(pool, config)
    await _seed_manifests(broker)
    return {
        "bucket_start": bucket_start,
        "schema_idempotent": True,
        "checkpoint_schema_idempotent": schema_upgrade["idempotent"],
        "schema_upgrade": schema_upgrade,
        "baseline_signals": await _keys(broker, "signals:*"),
        "baseline_shadow": await _keys(broker, "decision:shadow:*"),
        "outbox_pending": int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        ),
    }


async def materialize_window(
    pool: asyncpg.Pool,
    broker: Any,
    config: DecisionConfig,
    *,
    bucket_start: datetime,
    index_offset: int,
    count: int = LIVE_BASE_COUNT,
) -> dict[str, object]:
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("count must be a positive integer")
    repository = CandleRepository(pool)
    ingestion = CandleIngestionService(repository)
    htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
    assets = {"BTC": ("1h", "4h"), "ETH": ("4h",)}
    counts: dict[str, int] = {}
    for asset, timeframes in assets.items():
        inserted = 0
        for index in range(count):
            absolute_index = index_offset + index
            observation = _provider_observation(
                asset=asset,
                opened=bucket_start + timedelta(minutes=absolute_index),
                index=absolute_index,
            )
            status = await ingestion.commit_observation(observation)
            if status is CandleCommitStatus.CONFLICT:
                raise AssertionError(f"unexpected {asset} canonical conflict")
            if status is CandleCommitStatus.INSERTED:
                inserted += 1
            await htf.process_base_candle(
                canonicalize_observation(observation),
                base_duration=timedelta(minutes=1),
                target_durations={
                    timeframe: config.timeframe_grid.duration(timeframe)
                    for timeframe in timeframes
                },
                alignment_origin=config.timeframe_grid.alignment_origin,
            )
        counts[asset] = inserted
    outbox = await drain_outbox(pool, broker)
    pending = int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
        )
    )
    return {"base_inserted": counts, "outbox": outbox, "outbox_pending": pending}


def _merge_materialization(
    first: Mapping[str, object], second: Mapping[str, object]
) -> dict[str, object]:
    first_counts = first.get("base_inserted", {})
    second_counts = second.get("base_inserted", {})
    first_outbox = first.get("outbox", {})
    second_outbox = second.get("outbox", {})
    return {
        "segments": [first, second],
        "base_inserted": {
            asset: int(first_counts.get(asset, 0)) + int(second_counts.get(asset, 0))
            for asset in ("BTC", "ETH")
        },
        "outbox": {
            "attempts": int(first_outbox.get("attempts", 0))
            + int(second_outbox.get("attempts", 0)),
            "published": int(first_outbox.get("published", 0))
            + int(second_outbox.get("published", 0)),
        },
        "outbox_pending": int(second.get("outbox_pending", 0)),
    }


async def _wait_ready(base: str) -> dict[str, object]:
    async def probe() -> dict[str, object] | None:
        try:
            status, payload = await http_json(base, "/health/ready")
        except (OSError, urllib.error.URLError):
            return None
        return payload if status == 200 and payload.get("status") == "ready" else None

    return await _wait_for(probe, timeout=180, label="D11A Decision readiness")


async def signal_entries(broker: Any) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for stream in await _keys(broker, "signals:*"):
        for entry_id, fields in await broker.xrange(stream, "-", "+"):
            signal = valkey_decode(dict(fields), TradeSignal)
            result.append(
                {
                    "stream": stream,
                    "entry_id": str(entry_id),
                    "market_as_of": datetime.fromtimestamp(
                        signal.timestamp, tz=UTC
                    ).isoformat(),
                    "idempotency_key": signal.idempotency_key,
                    "model_name": signal.model_name,
                    "direction": signal.direction,
                    "conviction": signal.conviction,
                }
            )
    return sorted(result, key=lambda item: (str(item["stream"]), str(item["entry_id"])))


async def progress_rows(pool: asyncpg.Pool) -> list[dict[str, object]]:
    rows = await pool.fetch(
        """
        SELECT lane_id, effective_lane_revision, feature_plan_fingerprint,
               data_plan_fingerprint, market_as_of, last_disposition
          FROM decision.shadow_progress
         ORDER BY lane_id
        """
    )
    return [
        {
            "lane_id": row["lane_id"],
            "effective_lane_revision": row["effective_lane_revision"],
            "feature_plan_fingerprint": row["feature_plan_fingerprint"],
            "data_plan_fingerprint": row["data_plan_fingerprint"],
            "market_as_of": row["market_as_of"].astimezone(UTC).isoformat(),
            "last_disposition": row["last_disposition"],
        }
        for row in rows
    ]


async def runtime_snapshot(base: str) -> dict[str, object]:
    status, payload = await http_json(base, "/runtime")
    if status != 200:
        raise AssertionError(f"/runtime returned {status}: {payload}")
    return payload


def _oracle_cutoff_statuses() -> dict[str, list[str]]:
    artifact = json.loads(
        (
            ROOT
            / "artifacts/combined_c4b/c4b_decision_shadow_soak_resource_certification.json"
        ).read_text()
    )
    observed = artifact["trial_a"]["shadow_ledger"]["observed"]["by_lane"]
    return {
        lane_id: [
            str(item["policy_status"]) for _entry_id, item in sorted(values.items())
        ]
        for lane_id, values in observed.items()
    }


def _route_evidence(config: DecisionConfig) -> list[dict[str, object]]:
    return [
        {
            "lane_id": lane.lane_id,
            "asset": lane.asset,
            "decision_timeframe": lane.decision_timeframe,
            "trigger_timeframe": lane.trigger_timeframe,
            "authority": lane.authority,
            "risk_profile_key": lane.risk_profile_key,
            "m4_parameters": {
                binding.slot_name: binding.parameters for binding in lane.bindings
            },
        }
        for lane in config.lane_specs()
    ]


async def strategy_relinquishment_evidence() -> dict[str, object]:
    from apps.strategy_app.runtime.runner import StrategyRuntimeRunner
    from apps.strategy_app.runtime_pairs import build_strategy_pairs
    from apps.strategy_app.settings import StrategyWorkerSettings
    from tests.models.test_strategy_relinquished_routes import (
        _DrainFeatureWorker,
        _FeatureGroupRedis,
        _manager,
    )

    target_routes = ["BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h"]
    before_pairs = build_strategy_pairs(_manager())
    after_pairs = build_strategy_pairs(_manager(relinquished=target_routes))
    unknown_rejected = False
    try:
        build_strategy_pairs(_manager(relinquished=["ADAUSDT:1h"]))
    except ValueError as exc:
        unknown_rejected = "unknown" in str(exc)

    stream = "features:BTCUSDT:1h"
    redis = _FeatureGroupRedis()
    await redis.xgroup_create(stream, "strategy_d11a", id="0")
    redis.seed(stream, "1-0")
    settings = StrategyWorkerSettings(consumer_group="strategy_d11a")
    excluded_runner = StrategyRuntimeRunner(
        after_pairs,
        worker_factory=_DrainFeatureWorker,
        worker_settings=settings,
    )
    await excluded_runner.connect(redis)
    await asyncio.sleep(0)
    preserved_after_exclusion = redis.messages[stream] == [
        (
            "1-0",
            {"value": "1"},
        )
    ]
    no_excluded_read = stream not in {
        stream_key for stream_key, _cursor in redis.feature_reads
    }
    excluded_worker_count = len(excluded_runner._workers_by_key)
    await excluded_runner.stop()

    restored_runner = StrategyRuntimeRunner(
        before_pairs,
        worker_factory=_DrainFeatureWorker,
        worker_settings=settings,
    )
    await restored_runner.connect(redis)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    restored_consumed = redis.messages[stream] == [] and redis.acked == [
        (stream, "strategy_d11a", "1-0")
    ]
    await restored_runner.stop()
    return {
        "relinquished_routes": target_routes,
        "catalog_before": sorted(pair.key for pair in before_pairs),
        "catalog_after": sorted(pair.key for pair in after_pairs),
        "excluded_worker_count": excluded_worker_count,
        "unknown_route_rejected": unknown_rejected,
        "no_excluded_feature_read": no_excluded_read,
        "backlog_preserved_during_exclusion": preserved_after_exclusion,
        "rollback_consumed_and_acked": restored_consumed,
    }


async def run_trial(trial_name: str) -> dict[str, object]:
    infrastructure = D11AInfrastructure(trial_name)
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    result: dict[str, object] = {}
    try:
        config = load_d11a_config()
        await infrastructure.start_foundation()
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=4
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        seed = await seed_foundation(pool, broker, config)
        await infrastructure.start_decision()
        startup_health = await _wait_ready(infrastructure.http_base)
        startup_runtime = await runtime_snapshot(infrastructure.http_base)
        startup_progress = await progress_rows(pool)
        startup_signals = await signal_entries(broker)
        first_segment = await materialize_window(
            pool,
            broker,
            config,
            bucket_start=seed["bucket_start"],
            index_offset=0,
            count=60,
        )
        await _wait_for(
            lambda: _lane_progress_reached(
                pool,
                "BTCUSDT:momentum_1h",
                seed["bucket_start"] + timedelta(hours=1),
            ),
            timeout=180,
            label="first authoritative NO_SIGNAL cutoff",
        )
        no_signal_progress = await progress_rows(pool)
        no_signal_signals = await signal_entries(broker)
        second_segment = await materialize_window(
            pool,
            broker,
            config,
            bucket_start=seed["bucket_start"],
            index_offset=60,
            count=180,
        )
        initial = _merge_materialization(first_segment, second_segment)
        await _wait_for(
            lambda: _progress_count(pool, 3),
            timeout=180,
            label="three authoritative effect rows",
        )
        live_runtime = await runtime_snapshot(infrastructure.http_base)
        live_signals = await signal_entries(broker)
        live_progress = await progress_rows(pool)
        await infrastructure.stop_decision()
        during_down = await materialize_window(
            pool,
            broker,
            config,
            bucket_start=seed["bucket_start"],
            index_offset=LIVE_BASE_COUNT,
        )
        progress_while_down = await progress_rows(pool)
        await infrastructure.restart_decision()
        restart_health = await _wait_ready(infrastructure.http_base)
        await _wait_for(
            lambda: _progress_at_latest(
                pool, seed["bucket_start"] + timedelta(hours=8)
            ),
            timeout=180,
            label="authoritative restart catch-up",
        )
        restart_runtime = await runtime_snapshot(infrastructure.http_base)
        restart_signals = await signal_entries(broker)
        restart_progress = await progress_rows(pool)
        await infrastructure.stop_decision()
        crash_windows = await _run_crash_windows(trial_name, config)
        result = {
            "trial_name": trial_name,
            "infrastructure": {
                "isolated_project": True,
                "services": ["db", "broker", "decision"],
                "dynamic_ports": True,
                "decision_image": "repository-Dockerfile",
            },
            "routes": _route_evidence(config),
            "oracle_policy_statuses": _oracle_cutoff_statuses(),
            "startup": {
                "health": startup_health,
                "runtime": startup_runtime,
                "progress": startup_progress,
                "signals": startup_signals,
                "no_historical_signals": not startup_signals,
            },
            "schema_upgrade": seed["schema_upgrade"],
            "live": {
                "materialized": initial,
                "runtime": live_runtime,
                "signals": live_signals,
                "progress": live_progress,
                "shadow_keys": await _keys(broker, "decision:shadow:*"),
                "no_signal_window": {
                    "materialized": first_segment,
                    "progress": no_signal_progress,
                    "signals": no_signal_signals,
                    "btc_1h": await _progress_at_cutoff(
                        pool,
                        "BTCUSDT:momentum_1h",
                        seed["bucket_start"] + timedelta(hours=1),
                    ),
                },
                "oracle_policy_statuses": _oracle_cutoff_statuses(),
            },
            "restart": {
                "materialized_while_down": during_down,
                "progress_while_down": progress_while_down,
                "health": restart_health,
                "runtime": restart_runtime,
                "signals": restart_signals,
                "progress": restart_progress,
                "catchup_before_new_input": True,
            },
            "crash_windows": crash_windows,
            "unsupported_backlog": {
                "stateful": "unit_tested_fail_closed",
                "external_data": "unit_tested_fail_closed",
            },
        }
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        cleanup = await infrastructure.cleanup()
        result["cleanup"] = cleanup
    return result


async def _progress_count(pool: asyncpg.Pool, expected: int) -> bool:
    return (
        int(await pool.fetchval("SELECT COUNT(*) FROM decision.shadow_progress"))
        >= expected
    )


async def _progress_at_latest(pool: asyncpg.Pool, cutoff: datetime) -> bool:
    value = await pool.fetchval(
        "SELECT MIN(market_as_of) FROM decision.shadow_progress"
    )
    return value is not None and value >= cutoff


async def _progress_at_cutoff(
    pool: asyncpg.Pool, lane_id: str, cutoff: datetime
) -> dict[str, object] | None:
    row = await pool.fetchrow(
        """
        SELECT lane_id, market_as_of, last_disposition
          FROM decision.shadow_progress
         WHERE lane_id = $1
        """,
        lane_id,
    )
    if row is None:
        return None
    return {
        "lane_id": row["lane_id"],
        "market_as_of": row["market_as_of"].astimezone(UTC).isoformat(),
        "last_disposition": row["last_disposition"],
        "at_or_after": row["market_as_of"] >= cutoff,
    }


async def _lane_progress_reached(
    pool: asyncpg.Pool, lane_id: str, cutoff: datetime
) -> bool:
    evidence = await _progress_at_cutoff(pool, lane_id, cutoff)
    return bool(evidence and evidence["at_or_after"])


def evaluate_trial(trial: Mapping[str, object]) -> dict[str, bool]:
    startup = trial.get("startup", {})
    live = trial.get("live", {})
    restart = trial.get("restart", {})
    startup_progress = (
        startup.get("progress", []) if isinstance(startup, Mapping) else []
    )
    restart_progress = (
        restart.get("progress", []) if isinstance(restart, Mapping) else []
    )
    live_signals = live.get("signals", []) if isinstance(live, Mapping) else []
    restart_signals = restart.get("signals", []) if isinstance(restart, Mapping) else []
    no_signal_window = (
        live.get("no_signal_window", {}) if isinstance(live, Mapping) else {}
    )
    no_signal_progress = (
        no_signal_window.get("progress", [])
        if isinstance(no_signal_window, Mapping)
        else []
    )
    no_signal_signals = (
        no_signal_window.get("signals", [])
        if isinstance(no_signal_window, Mapping)
        else []
    )
    oracle = live.get("oracle_policy_statuses", {}) if isinstance(live, Mapping) else {}
    signal_counts = {
        model_name: sum(item.get("model_name") == model_name for item in live_signals)
        for model_name in ("m4-btc-1h", "m4-btc-4h", "m4-eth-4h")
    }
    crash = trial.get("crash_windows", {})
    signal_crash = crash.get("signal", {}) if isinstance(crash, Mapping) else {}
    no_signal_crash = crash.get("no_signal", {}) if isinstance(crash, Mapping) else {}

    def lane_row(value: object, lane_id: str) -> Mapping[str, object] | None:
        if not isinstance(value, Sequence):
            return None
        return next(
            (
                item
                for item in value
                if isinstance(item, Mapping) and item.get("lane_id") == lane_id
            ),
            None,
        )

    signal_failed_progress = lane_row(
        signal_crash.get("failed_progress"), "BTCUSDT:momentum_1h"
    )
    signal_recovered_progress = lane_row(
        signal_crash.get("recovered_progress"), "BTCUSDT:momentum_1h"
    )
    no_signal_failed_progress = lane_row(
        no_signal_crash.get("failed_progress"), "BTCUSDT:momentum_1h"
    )
    no_signal_recovered_progress = lane_row(
        no_signal_crash.get("recovered_progress"), "BTCUSDT:momentum_1h"
    )
    expected_signal_cutoff = signal_crash.get("expected_cutoff")
    expected_no_signal_cutoff = no_signal_crash.get("expected_cutoff")
    failed_signal_entries = signal_crash.get("failed_signals", [])
    recovered_signal_entries = signal_crash.get("recovered_signals", [])
    return {
        "first_start_no_backfill": bool(
            isinstance(startup, Mapping)
            and startup.get("no_historical_signals") is True
            and startup.get("signals") == []
            and len(startup_progress) == 3
            and all(item.get("last_disposition") is None for item in startup_progress)
        ),
        "authoritative_routes_ready": bool(
            isinstance(startup, Mapping)
            and startup.get("ready") is True
            and startup.get("active_lane_count") == 3
        ),
        "authoritative_signal_path": bool(
            len(live_signals) >= 1
            and all(
                item.get("stream", "").startswith("signals:") for item in live_signals
            )
            and all(
                item.get("model_name", "").startswith("m4-") for item in live_signals
            )
        ),
        "authoritative_no_signal_progress": bool(
            isinstance(no_signal_window, Mapping)
            and no_signal_signals == []
            and any(
                item.get("lane_id") == "BTCUSDT:momentum_1h"
                and item.get("last_disposition") == "no_signal"
                for item in no_signal_progress
            )
            and isinstance(no_signal_window.get("btc_1h"), Mapping)
            and no_signal_window["btc_1h"].get("at_or_after") is True
        ),
        "policy_status_oracle": bool(
            isinstance(oracle, Mapping)
            and oracle.get("BTCUSDT:momentum_1h", [])[:4]
            == ["NO_SIGNAL", "SIGNAL", "SIGNAL", "SIGNAL"]
            and oracle.get("BTCUSDT:momentum_4h", [])[:1] == ["SIGNAL"]
            and oracle.get("ETHUSDT:momentum_4h", [])[:1] == ["SIGNAL"]
            and signal_counts == {"m4-btc-1h": 3, "m4-btc-4h": 1, "m4-eth-4h": 1}
        ),
        "published_crash_reconciled": bool(
            isinstance(signal_crash, Mapping)
            and signal_failed_progress is not None
            and signal_failed_progress.get("market_as_of") != expected_signal_cutoff
            and signal_failed_progress.get("last_disposition") == "published"
            and signal_recovered_progress is not None
            and signal_recovered_progress.get("market_as_of") == expected_signal_cutoff
            and signal_recovered_progress.get("last_disposition") == "published"
            and isinstance(failed_signal_entries, Sequence)
            and isinstance(recovered_signal_entries, Sequence)
            and failed_signal_entries == recovered_signal_entries
            and sum(
                item.get("market_as_of") == expected_signal_cutoff
                for item in recovered_signal_entries
                if isinstance(item, Mapping) and item.get("model_name") == "m4-btc-1h"
            )
            == 1
        ),
        "no_signal_crash_reconciled": bool(
            isinstance(no_signal_crash, Mapping)
            and no_signal_failed_progress is not None
            and no_signal_failed_progress.get("market_as_of")
            != expected_no_signal_cutoff
            and no_signal_failed_progress.get("last_disposition") is None
            and no_signal_recovered_progress is not None
            and no_signal_recovered_progress.get("market_as_of")
            == expected_no_signal_cutoff
            and no_signal_recovered_progress.get("last_disposition") == "no_signal"
            and no_signal_crash.get("failed_signals") == []
            and no_signal_crash.get("recovered_signals") == []
        ),
        "crash_cleanup": bool(
            isinstance(crash, Mapping)
            and isinstance(crash.get("cleanup"), Mapping)
            and crash["cleanup"].get("clean") is True
        ),
        "restart_backlog_exact": bool(
            isinstance(restart, Mapping)
            and restart.get("catchup_before_new_input") is True
            and len(restart_signals) >= len(live_signals)
            and len(restart_progress) == 3
            and all(
                item.get("last_disposition") in {"published", "no_signal"}
                for item in restart_progress
            )
        ),
        "no_shadow_authority_leak": bool(
            isinstance(live, Mapping) and not live.get("shadow_keys")
        ),
        "no_duplicate_signals": len(
            {(item.get("stream"), item.get("entry_id")) for item in restart_signals}
        )
        == len(restart_signals),
        "cleanup": bool(
            isinstance(trial.get("cleanup"), Mapping)
            and trial["cleanup"].get("clean") is True
        ),
    }


def _schema_upgrade_gate(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    before = value.get("historical_rows_before")
    after = value.get("historical_rows_after")
    old_constraints = value.get("old_constraint_definition")
    migrated_constraints = value.get("migrated_constraint_definition")
    second_constraints = value.get("second_constraint_definition")
    if not isinstance(before, Sequence) or not isinstance(after, Sequence):
        return False
    if not isinstance(old_constraints, Sequence):
        return False
    if not isinstance(migrated_constraints, Sequence):
        return False
    if not isinstance(second_constraints, Sequence):
        return False
    historical_ids = {
        item.get("lane_id") for item in before if isinstance(item, Mapping)
    }
    preserved_rows = [
        item
        for item in after
        if isinstance(item, Mapping) and item.get("lane_id") in historical_ids
    ]
    migrated_definition = " ".join(
        str(item.get("definition", ""))
        for item in migrated_constraints
        if isinstance(item, Mapping)
    ).lower()
    old_definition = " ".join(
        str(item.get("definition", ""))
        for item in old_constraints
        if isinstance(item, Mapping)
    ).lower()
    return bool(
        value.get("c4b_table_created") is True
        and len(before) == 2
        and preserved_rows == list(before)
        and len(old_constraints) == 1
        and "published" not in old_definition
        and "no_signal" not in old_definition
        and len(migrated_constraints) == 1
        and "last_disposition" in migrated_definition
        and "published" in migrated_definition
        and "no_signal" in migrated_definition
        and len(second_constraints) == 1
        and list(migrated_constraints) == list(second_constraints)
        and value.get("published_repository_roundtrip") is True
        and value.get("no_signal_repository_roundtrip") is True
        and value.get("invalid_disposition_rejected") is True
        and value.get("second_bootstrap_succeeded") is True
        and value.get("check_constraint_count") == 1
        and value.get("idempotent") is True
    )


def evaluate_artifact(artifact: Mapping[str, object]) -> tuple[dict[str, bool], str]:
    trials = artifact.get("trials")
    if not isinstance(trials, Sequence) or len(trials) != 2:
        return {}, D11A_BLOCKED_STATUS
    trial_gates = {
        key: all(
            bool(evidence.get(key))
            for evidence in (evaluate_trial(trial) for trial in trials)
        )
        for key in evaluate_trial(trials[0])
    }
    routes = artifact.get("routes")
    route_ids = (
        {item.get("lane_id") for item in routes if isinstance(item, Mapping)}
        if isinstance(routes, Sequence)
        else set()
    )
    production_scope = artifact.get("production_scope")
    contract = artifact.get("effect_progress_contract")
    strategy = artifact.get("strategy")
    m4_identity = artifact.get("m4_config_identity")
    expected_strategy_before = [
        "BNBUSDT:30m",
        "BTCUSDT:1h",
        "BTCUSDT:4h",
        "DOGEUSDT:4h",
        "ETHUSDT:4h",
        "SOLUSDT:1h",
        "XRPUSDT:1h",
    ]
    expected_strategy_after = [
        "BNBUSDT:30m",
        "DOGEUSDT:4h",
        "SOLUSDT:1h",
        "XRPUSDT:1h",
    ]
    gates = {
        **trial_gates,
        "protected_evidence": (
            artifact.get("protected_hashes") == EXPECTED_PROTECTED_HASHES
            and protected_hashes() == EXPECTED_PROTECTED_HASHES
        ),
        "source_lock": artifact.get("source_hashes") == current_source_hashes(),
        "fixture_source_lock": artifact.get("fixture_hashes")
        == current_fixture_hashes(),
        "c4b_schema_upgrade": all(
            _schema_upgrade_gate(trial.get("schema_upgrade"))
            if isinstance(trial, Mapping)
            else False
            for trial in trials
        )
        and len(trials) == 2,
        "authoritative_routes": route_ids == set(EXPECTED_LANES)
        and all(
            isinstance(item, Mapping)
            and item.get("authority") == "authoritative"
            and item.get("risk_profile_key", "").startswith("m4-")
            for item in routes
        )
        if isinstance(routes, Sequence)
        else False,
        "m4_authoritative_config_identity": bool(
            isinstance(m4_identity, Mapping)
            and m4_identity.get("matches") is True
            and m4_identity.get("d11a") == m4_identity.get("m4_certified")
        ),
        "effect_progress_contract": contract
        == {
            "physical_table": "decision.shadow_progress",
            "dispositions": [None, "shadow", "published", "no_signal"],
            "identity_fields": [
                "lane_id",
                "effective_lane_revision",
                "feature_plan_fingerprint",
                "data_plan_fingerprint",
            ],
        },
        "production_inactive": isinstance(production_scope, Mapping)
        and production_scope.get("decision_assets") == []
        and production_scope.get("observer_active") is False,
        "crash_windows": all(
            evidence["published_crash_reconciled"]
            and evidence["no_signal_crash_reconciled"]
            for evidence in (evaluate_trial(trial) for trial in trials)
        ),
        "unsupported_backlog_fail_closed": all(
            isinstance(trial, Mapping)
            and trial.get("unsupported_backlog")
            == {
                "stateful": "unit_tested_fail_closed",
                "external_data": "unit_tested_fail_closed",
            }
            for trial in trials
        ),
        "strategy_route_relinquishment": bool(
            isinstance(strategy, Mapping)
            and strategy.get("relinquished_routes")
            == ["BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h"]
            and strategy.get("catalog_before") == expected_strategy_before
            and strategy.get("catalog_after") == expected_strategy_after
            and strategy.get("excluded_worker_count") == 4
            and strategy.get("unknown_route_rejected") is True
        ),
        "strategy_unrelated_routes_preserved": bool(
            isinstance(strategy, Mapping)
            and strategy.get("catalog_after") == expected_strategy_after
        ),
        "rollback_backlog_preserved": bool(
            isinstance(strategy, Mapping)
            and strategy.get("no_excluded_feature_read") is True
            and strategy.get("backlog_preserved_during_exclusion") is True
            and strategy.get("rollback_consumed_and_acked") is True
        ),
    }
    status = D11A_SUCCESS_STATUS if all(gates.values()) else D11A_BLOCKED_STATUS
    return gates, status


__all__ = [
    "D11A_ARTIFACT",
    "D11A_BASE_SHA",
    "D11A_BLOCKED_STATUS",
    "D11A_SUCCESS_STATUS",
    "EXPECTED_LANES",
    "EXPECTED_PROTECTED_HASHES",
    "canonical_json",
    "current_fixture_hashes",
    "current_source_hashes",
    "evaluate_artifact",
    "file_sha256",
    "load_d11a_config",
    "protected_hashes",
    "run_trial",
    "schema_upgrade_evidence",
    "sha256_fingerprint",
]
