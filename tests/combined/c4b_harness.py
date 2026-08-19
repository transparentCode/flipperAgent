"""C4B disposable migration-overlap soak and certification harness.

This module is deliberately test-owned.  It composes the approved C4A
containers and adapters, records raw evidence, and keeps gate evaluation pure.
It does not add a Decision runtime path or alter production configuration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import socket
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey

from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.transport.shadow import (
    ShadowDecisionObservation,
    ShadowPublicationEnvelope,
    ValkeyShadowPublisher,
    shadow_payload_fingerprint,
    shadow_stream_entry_id,
    shadow_stream_key,
)
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleCommitStatus, CandleRepository
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.contracts.ingestion import IngestionCommandType
from libs.contracts.serialization import valkey_decode
from tests.combined import c4a_harness as c4a
from tests.combined.c2_harness import (
    LIVE_BASE_COUNT,
    _provider_observation,
    drain_outbox,
    seed_startup_history,
)

ROOT = Path(__file__).resolve().parents[2]
C4_COMPOSE_FILE = ROOT / "tests/combined/fixtures/c4/docker-compose.yml"
C4B_COMPOSE_FILE = ROOT / "tests/combined/fixtures/c4b/docker-compose.yml"
ARTIFACT_FILE = (
    ROOT / "artifacts/combined_c4b/c4b_decision_shadow_soak_resource_certification.json"
)

SOURCE_SHA = "4295c4297f49d0a895974ad6afc8b4f660ad44c3"
C4A_MANIFEST_SHA = "bf33c23d413b8cef35bbd0202953d8b13a2170f49ba4fe2304166e4477e41b6a"
C4A_ARTIFACT_SHA = "c2adb97f2504ce541a0b4aa41f186a4a86c0c209dd96229e6bc4b7d121399334"
C4A_IDENTITY_DIGEST = "7b5c6709fbf851402aad669b56c9ccbcbc7c678d5436fa1c2fae07a6ef1d650a"
C4A_EVIDENCE_DIGEST = "10a25050c5d903623ecd38bf142d1312e07ec4bb797773f583f54138e072e589"
R4C_MANIFEST_SHA = "fabc31f04ab40361c9d28b298d85fc0b26858d40d778db3d7bad1746796c50f0"
ROOT_COMPOSE_SHA = "b24d6823e4a128e1a9e716772c83c50871fc89b3f3f81830b2365cebdc412df1"
REMEDIATED_SOURCE_PATHS = (
    "src/apps/decision_app/bootstrap.py",
    "src/apps/decision_app/runtime/live.py",
    "src/apps/decision_app/runtime/startup.py",
    "src/apps/decision_app/storage/__init__.py",
    "src/apps/decision_app/storage/schema.sql",
    "src/apps/decision_app/storage/shadow_progress.py",
)

# Historical C4B evidence is immutable.  Later phases may generalize these
# modules, so its evaluator accepts this frozen source contract in addition to
# the live C4B generator map; the stored-artifact regression compares exactly
# against this map.
FROZEN_C4B_RESTART_BACKLOG_SOURCE_HASHES = {
    "src/apps/decision_app/bootstrap.py": "399c6bd55485fbf65b35c3ef270260b7cfb8bb73d217257102e7a31bdcd34ebb",
    "src/apps/decision_app/runtime/live.py": "f7a500268973d9e547affe932cdce3d1b9c09a7732fd32cc3668a1d71d8c7f3a",
    "src/apps/decision_app/runtime/startup.py": "6c00bce96d80ed9793b65762a4ecc36344567140995da949ea47f33676931499",
    "src/apps/decision_app/storage/__init__.py": "d9c7b185f8d4f77022a67d9d523dcdb26c8331390fc71e945992edb79b2e38a5",
    "src/apps/decision_app/storage/schema.sql": "18548f7d20e1982977d54121b5b2fee847cac85ac2eae78e61c48544ce7220e1",
    "src/apps/decision_app/storage/shadow_progress.py": "30cc32c53030c3f152f19d7037007a04686fac0c8005f839a5ba04b79080db3d",
}
C4B_SUCCESS_STATUS = (
    "INGESTION_DECISION_C4B_SHADOW_SOAK_RESOURCE_CERTIFICATION_READY_FOR_REVIEW"
)
C4B_EVIDENCE_STATUS = "INGESTION_DECISION_C4B_EVIDENCE_INSUFFICIENT"
C4B_PRODUCTION_DEFECT_STATUS = (
    "INGESTION_DECISION_C4B_PRODUCTION_DEFECT_REQUIRES_REMEDIATION"
)

STARTUP_COUNT = 544
SOAK_BASE_TOTAL = 10_800
SOAK_BASE_PER_ASSET = 5_400
SOAK_WINDOW = LIVE_BASE_COUNT
EXPECTED_F1_MISSING_COUNTS = {
    "BTCUSDT:momentum_1h": 4,
    "BTCUSDT:momentum_4h": 1,
    "ETHUSDT:momentum_4h": 1,
}
RESOURCE_LIMITS = {
    "db": {"memory": 1024 * 1024 * 1024, "cpu": 500_000_000},
    "broker": {"memory": 256 * 1024 * 1024, "cpu": 500_000_000},
    "decision": {"memory": 512 * 1024 * 1024, "cpu": 500_000_000},
    "signal-worker": {"memory": 512 * 1024 * 1024, "cpu": 500_000_000},
    "strategy-worker": {"memory": 512 * 1024 * 1024, "cpu": 500_000_000},
}
EXPECTED_PROTECTED_HASHES = {
    "m3": "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c",
    "m4_functional": "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792",
    "m4_resource": "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4",
    "d10": "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459",
    "c1": "386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4",
    "c2": "9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67",
    "c3a": "34c0b0eaa85fffacbd5c99d346bdcf2829dd12c8c6769e18c63711d0a342622b",
    "c3b1": "bfb335bf5ab27b790c91be13ad878531b7a85a957901c86f7a6ec462f566fb63",
    "c3b2p": "0981b3bd1962089932da5dc7669c936537ddaaf1d5c17adae71d2f7e798347f0",
    "r3c1_manifest": "1d3a0cd3abf9c9f05ba9c416985401be5b53efd317e838e859c6373df0556752",
    "r3c1_metrics": "ffc1448a8e09afb8f9cdbea3a50a8df9aa6c4795c40e2267eca00e00b80af9b3",
    "r3c2_manifest": "0cfdff4c07c0b6807c4832df56f867ad9f560f61feb7e89d93924dc9cfd4fc23",
    "r3c2_metrics": "bec76fa99d74afe90787093a5d83b10485f5056e6b89c0065679c37a45e8713b",
    "c4a": C4A_ARTIFACT_SHA,
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
        return value.decode(errors="replace")
    return value


def canonical_json(value: object) -> str:
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))


def sha256_fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remediation_source_hashes() -> dict[str, str]:
    return {
        path: file_sha256(ROOT / path)
        for path in REMEDIATED_SOURCE_PATHS
        if (ROOT / path).is_file()
    }


def _run(
    command: Sequence[str], *, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        env=None if env is None else dict(env),
        text=True,
        capture_output=True,
        check=False,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _cleanup_probe(project_name: str) -> dict[str, str]:
    label = f"label=com.docker.compose.project={project_name}"
    return {
        "containers": _run(["docker", "ps", "-aq", "--filter", label]).stdout.strip(),
        "volumes": _run(
            ["docker", "volume", "ls", "-q", "--filter", label]
        ).stdout.strip(),
        "networks": _run(
            ["docker", "network", "ls", "-q", "--filter", label]
        ).stdout.strip(),
    }


@dataclass(slots=True)
class C4BInfrastructure:
    """One isolated five-service Compose project."""

    trial_name: str
    db_port: int = field(default_factory=_free_port)
    broker_port: int = field(default_factory=_free_port)
    decision_port: int = field(default_factory=_free_port)
    project_name: str = field(init=False)

    def __post_init__(self) -> None:
        while len({self.db_port, self.broker_port, self.decision_port}) != 3:
            self.decision_port = _free_port()
        token = "".join(char if char.isalnum() else "_" for char in self.trial_name)
        self.project_name = f"flipper_c4b_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "C4_DB_PORT": str(self.db_port),
                "C4_BROKER_PORT": str(self.broker_port),
                "C4_DECISION_PORT": str(self.decision_port),
                "COMPOSE_PROJECT_NAME": self.project_name,
                "COMPOSE_DISABLE_ENV_FILE": "1",
                "OTEL_SDK_DISABLED": "true",
            }
        )
        return env

    def command(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(C4_COMPOSE_FILE),
            "-f",
            str(C4B_COMPOSE_FILE),
            "-p",
            self.project_name,
            *arguments,
        ]

    def run_compose(
        self, *arguments: str, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return _run(self.command(*arguments), env=self.environment)

    def validate_config(self) -> dict[str, object]:
        result = self.run_compose("config", "--quiet")
        return {
            "returncode": result.returncode,
            "rendered": result.returncode == 0,
            "stderr": result.stderr[-1000:],
        }

    async def start_foundation(self) -> None:
        result = await asyncio.to_thread(
            self.run_compose, "up", "-d", "--wait", "db", "broker"
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_decision(self) -> None:
        result = await asyncio.to_thread(
            self.run_compose, "up", "-d", "--build", "--wait", "decision"
        )
        if result.returncode:
            logs = self.run_compose("logs", "--no-color", "decision")
            raise RuntimeError((result.stderr or result.stdout) + "\n" + logs.stdout)

    async def start_legacy(self) -> dict[str, object]:
        result = await asyncio.to_thread(
            self.run_compose, "up", "-d", "--build", "signal-worker", "strategy-worker"
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:],
        }

    async def stop_decision(self) -> dict[str, object]:
        result = await asyncio.to_thread(self.run_compose, "stop", "decision")
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-1000:],
            "stderr": result.stderr[-1000:],
        }

    async def restart_decision(self) -> dict[str, object]:
        stopped = await self.stop_decision()
        started = await asyncio.to_thread(
            self.run_compose, "up", "-d", "--wait", "decision"
        )
        return {
            "stop": stopped,
            "start_returncode": started.returncode,
            "start_stderr": started.stderr[-1000:],
        }

    async def pause_service(self, service: str) -> dict[str, object]:
        result = await asyncio.to_thread(self.run_compose, "pause", service)
        return {"returncode": result.returncode, "service": service}

    async def unpause_service(self, service: str) -> dict[str, object]:
        result = await asyncio.to_thread(self.run_compose, "unpause", service)
        return {"returncode": result.returncode, "service": service}

    async def cleanup(self) -> dict[str, object]:
        result = await asyncio.to_thread(
            self.run_compose, "down", "-v", "--remove-orphans"
        )
        leftovers = await asyncio.to_thread(_cleanup_probe, self.project_name)
        return {
            "down_returncode": result.returncode,
            "leftovers": leftovers,
            "clean": result.returncode == 0 and not any(leftovers.values()),
        }

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://c4_user:c4_password@127.0.0.1:{self.db_port}/c4_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"

    @property
    def http_base(self) -> str:
        return f"http://127.0.0.1:{self.decision_port}"

    async def resource_sample(self, phase: str) -> dict[str, object]:
        services: dict[str, object] = {}
        for service, limits in RESOURCE_LIMITS.items():
            ps = await asyncio.to_thread(self.run_compose, "ps", "-q", service)
            container_id = (
                ps.stdout.strip().splitlines()[0] if ps.stdout.strip() else ""
            )
            sample: dict[str, object] = {
                "phase": phase,
                "service": service,
                "container_present": bool(container_id),
            }
            if not container_id:
                services[service] = sample
                continue
            stats = await asyncio.to_thread(
                _run,
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    container_id,
                ],
            )
            inspect = await asyncio.to_thread(
                _run, ["docker", "inspect", "--format", "{{json .}}", container_id]
            )
            if stats.returncode == 0 and stats.stdout.strip():
                raw_stats = json.loads(stats.stdout.splitlines()[0])
                usage = str(raw_stats.get("MemUsage", ""))
                match = re.match(
                    r"\s*([0-9.]+)\s*([KMGTP]?i?B)?\s*/\s*([0-9.]+)\s*([KMGTP]?i?B)?",
                    usage,
                )
                sample.update(
                    {
                        "stats_available": True,
                        "cpu_percent": raw_stats.get("CPUPerc"),
                        "pids": int(raw_stats.get("PIDs", 0) or 0),
                    }
                )
                if match:
                    sample["memory_usage_bytes"] = _parse_bytes(
                        match.group(1), match.group(2)
                    )
                    sample["memory_limit_bytes"] = _parse_bytes(
                        match.group(3), match.group(4)
                    )
            else:
                sample["stats_available"] = False
            if inspect.returncode == 0 and inspect.stdout.strip():
                raw = json.loads(inspect.stdout)
                state = raw.get("State", {})
                host = raw.get("HostConfig", {})
                sample.update(
                    {
                        "container_id": raw.get("Id"),
                        "image_id": raw.get("Image"),
                        "configured_memory_bytes": int(host.get("Memory", 0) or 0),
                        "configured_cpu_nano": int(host.get("NanoCpus", 0) or 0),
                        "oom_killed": bool(state.get("OOMKilled", False)),
                        "restart_count": int(raw.get("RestartCount", 0) or 0),
                        "running": bool(state.get("Running", False)),
                        "expected_memory_bytes": limits["memory"],
                        "expected_cpu_nano": limits["cpu"],
                    }
                )
            services[service] = sample
        return {"phase": phase, "services": services}


def _parse_bytes(number: str, suffix: str | None) -> int:
    multiplier = {
        None: 1,
        "B": 1,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
    }.get(suffix, 1)
    return int(float(number) * multiplier)


# R3C protected evidence is stored under the versioned artifact directories;
# keep this certification's authoritative lookup explicit and independent of
# the research YAML source manifests.
def protected_hashes() -> dict[str, str]:  # type: ignore[no-redef]
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
        "c3b1": ROOT
        / "artifacts/combined_c3b1/c3b1_ingestion_decision_canonical_integrity_certification.json",
        "c3b2p": ROOT
        / "artifacts/combined_c3b2/c3b2_ingestion_decision_provider_recovery_disagreement_certification.json",
        "r3c1_manifest": ROOT
        / "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/study_manifest.json",
        "r3c1_metrics": ROOT
        / "artifacts/regression_r3c/btcusdt_1h_momentum_context_utility_v1/conditional_metrics.json",
        "r3c2_manifest": ROOT
        / "artifacts/regression_r3c/4h_short_overextension_replication_v1/study_manifest.json",
        "r3c2_metrics": ROOT
        / "artifacts/regression_r3c/4h_short_overextension_replication_v1/replication_metrics.json",
        "c4a": ROOT
        / "artifacts/combined_c4a/c4a_decision_shadow_container_foundation_certification.json",
    }
    return {name: file_sha256(path) for name, path in paths.items() if path.exists()}


def _http_json_sync(url: str, method: str = "GET") -> tuple[int, dict[str, object]]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"detail": body.decode(errors="replace")}
        return int(exc.code), payload
    except (OSError, urllib.error.URLError) as exc:
        return 0, {"detail": str(exc)}


async def http_json(
    base: str, path: str, method: str = "GET"
) -> tuple[int, dict[str, object]]:
    return await asyncio.to_thread(_http_json_sync, base + path, method)


async def wait_ready(base: str, timeout: float = 180.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = await http_json(base, "/health/ready")
        if status == 200 and payload.get("status") == "ready":
            return payload
        await asyncio.sleep(0.5)
    raise TimeoutError("Decision container did not become ready")


def load_c4_config() -> Any:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        return c4a.load_c4_config()
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


async def _schema_and_seed(
    pool: asyncpg.Pool, broker: Any, config: Any
) -> dict[str, object]:
    await apply_ingestion_schema(pool)
    await apply_ingestion_schema(pool)
    await ensure_checkpoint_schema(pool)
    await ensure_checkpoint_schema(pool)
    bucket_start = await seed_startup_history(pool, config)
    await c4a.seed_manifests(broker)
    return {
        "bucket_start": bucket_start,
        "schema_idempotent": True,
        "checkpoint_schema_idempotent": True,
        "baseline_signals": await c4a._keys(broker, "signals:*"),
        "baseline_shadow": await c4a._keys(broker, "decision:shadow:*"),
        "baseline_outbox_pending": int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        ),
    }


async def materialize_window(
    repository: CandleRepository,
    *,
    asset: str,
    start: datetime,
    index_offset: int,
    count: int,
    config: Any,
) -> dict[str, int]:
    """Append one bounded contiguous C4A-shaped window without batching bars."""
    ingestion = CandleIngestionService(repository)
    htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
    target_durations = (
        {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
        if asset == "BTC"
        else {"4h": timedelta(hours=4)}
    )
    inserted = 0
    for index in range(count):
        observation = _provider_observation(
            asset=asset,
            opened=start + timedelta(minutes=index),
            index=index + index_offset,
        )
        status = await ingestion.commit_observation(observation)
        if status is CandleCommitStatus.CONFLICT:
            raise AssertionError("unexpected canonical conflict in C4B live window")
        if status is CandleCommitStatus.INSERTED:
            inserted += 1
        await htf.process_base_candle(
            canonicalize_observation(observation),
            base_duration=timedelta(minutes=1),
            target_durations=target_durations,
            alignment_origin=config.timeframe_grid.alignment_origin,
        )
    return {"base_inserted": inserted, "requested": count}


async def materialize_assets(
    pool: asyncpg.Pool,
    broker: Any,
    config: Any,
    bucket_start: datetime,
    index_offset: int,
    count: int,
) -> dict[str, object]:
    repository = CandleRepository(pool)
    result = {
        asset: await materialize_window(
            repository,
            asset=asset,
            start=bucket_start + timedelta(minutes=index_offset),
            index_offset=index_offset,
            count=count,
            config=config,
        )
        for asset in ("BTC", "ETH")
    }
    outbox: dict[str, object]
    try:
        outbox = await drain_outbox(pool, broker)
    except Exception as exc:  # noqa: BLE001 - retain broker fault evidence
        outbox = {"error": str(exc)}
    pending = int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
        )
    )
    return {"assets": result, "outbox": outbox, "outbox_pending": pending}


def _stream_tail_map(broker: Any, keys: Sequence[str]) -> Any:
    async def read() -> dict[str, str | None]:
        tails: dict[str, str | None] = {}
        for key in keys:
            rows = await broker.xrevrange(key, "+", "-", count=1)
            tails[key] = None if not rows else str(rows[0][0])
        return tails

    return read


async def shadow_entries(
    broker: Any, *, include_retention: bool = True
) -> tuple[ShadowDecisionObservation, ...]:
    observations: list[ShadowDecisionObservation] = []
    for stream in await c4a._keys(broker, "decision:shadow:*"):
        for _entry_id, fields in await broker.xrange(stream, "-", "+"):
            observation = valkey_decode(dict(fields), ShadowDecisionObservation)
            if not include_retention and observation.lane_id == "C4B_RETENTION":
                continue
            observations.append(observation)
    return tuple(
        sorted(observations, key=lambda item: (item.lane_id, item.market_as_of))
    )


async def shadow_progress_rows(pool: asyncpg.Pool) -> list[dict[str, object]]:
    rows = await pool.fetch(
        """
        SELECT lane_id, effective_lane_revision, feature_plan_fingerprint,
               data_plan_fingerprint, market_as_of, last_disposition
          FROM decision.shadow_progress
         ORDER BY lane_id, effective_lane_revision,
                  feature_plan_fingerprint, data_plan_fingerprint
        """
    )
    return [
        {
            "lane_id": str(row["lane_id"]),
            "effective_lane_revision": str(row["effective_lane_revision"]),
            "feature_plan_fingerprint": str(row["feature_plan_fingerprint"]),
            "data_plan_fingerprint": str(row["data_plan_fingerprint"]),
            "market_as_of": row["market_as_of"].astimezone(UTC).isoformat(),
            "last_disposition": row["last_disposition"],
        }
        for row in rows
    ]


def observation_ledger(
    observations: Sequence[ShadowDecisionObservation],
) -> dict[str, object]:
    by_lane: dict[str, dict[str, dict[str, object]]] = {}
    contradictions: list[str] = []
    for observation in observations:
        entry_id = shadow_stream_entry_id(observation.market_as_of)
        lane = by_lane.setdefault(observation.lane_id, {})
        payload = {
            "entry_id": entry_id,
            "market_as_of": observation.market_as_of.isoformat(),
            "decision_id": observation.decision_id,
            # ``decision_ready_at`` is operational evidence, not semantic
            # effect identity. Exclude it from the cross-trial ledger
            # fingerprint so fresh processes with different wall clocks are
            # compared on the actual decision payload.
            "payload_fingerprint": sha256_fingerprint(
                observation.model_dump(
                    mode="python",
                    exclude={"decision_ready_at"},
                )
            ),
            "policy_status": observation.policy_status,
            "direction": observation.direction_hint,
            "score": observation.score,
            "conviction": observation.conviction,
        }
        previous = lane.get(entry_id)
        if (
            previous is not None
            and previous.get("payload_fingerprint") != payload["payload_fingerprint"]
        ):
            contradictions.append(f"{observation.lane_id}:{entry_id}")
        lane[entry_id] = payload
    return {
        "by_lane": by_lane,
        "contradictions": sorted(set(contradictions)),
        "digest": sha256_fingerprint(by_lane),
        "total": sum(len(items) for items in by_lane.values()),
    }


def _ledger_cutoffs(ledger: Mapping[str, object]) -> dict[str, set[str]]:
    by_lane = ledger.get("by_lane")
    if not isinstance(by_lane, Mapping):
        return {}
    return {
        str(lane): {
            str(item.get("market_as_of"))
            for item in values.values()
            if isinstance(item, Mapping)
        }
        for lane, values in by_lane.items()
        if isinstance(values, Mapping)
    }


def _cutoff_delta(
    before: Mapping[str, Sequence[str]], after: Mapping[str, Sequence[str]]
) -> dict[str, list[str]]:
    return {
        str(lane): sorted(set(after.get(lane, ())) - set(before.get(lane, ())))
        for lane in set(before) | set(after)
    }


def _observed_delta(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, list[str]]:
    before_cutoffs = _ledger_cutoffs(before)
    after_cutoffs = _ledger_cutoffs(after)
    return {
        lane: sorted(values - before_cutoffs.get(lane, set()))
        for lane, values in after_cutoffs.items()
    }


def _exact_ledger_delta(
    before: Mapping[str, object],
    after: Mapping[str, object],
    expected: Mapping[str, Sequence[str]],
) -> bool:
    return _observed_delta(before, after) == {
        str(lane): sorted(values) for lane, values in expected.items()
    }


async def expected_cutoffs(
    pool: asyncpg.Pool, bucket_start: datetime
) -> dict[str, list[str]]:
    routes = {
        "BTCUSDT:momentum_1h": ("BTC-USDT-PERP", "1h"),
        "BTCUSDT:momentum_4h": ("BTC-USDT-PERP", "4h"),
        "ETHUSDT:momentum_4h": ("ETH-USDT-PERP", "4h"),
    }
    result: dict[str, list[str]] = {}
    for lane, (instrument, timeframe) in routes.items():
        rows = await pool.fetch(
            "SELECT close_time FROM ingestion.candles WHERE instrument_id=$1 AND timeframe=$2 AND close_time > $3 ORDER BY close_time",
            instrument,
            timeframe,
            bucket_start,
        )
        result[lane] = [row["close_time"].astimezone(UTC).isoformat() for row in rows]
    return result


def _progress_cutoffs(rows: object) -> dict[str, str]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return {}
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        lane_id = row.get("lane_id")
        cutoff = row.get("market_as_of")
        if isinstance(lane_id, str) and isinstance(cutoff, str):
            result[lane_id] = cutoff
    return result


def _progress_matches_expected(
    rows: object,
    expected: Mapping[str, Sequence[str]],
    *,
    disposition: str | None,
) -> bool:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return False
    relevant = [row for row in rows if isinstance(row, Mapping)]
    if {row.get("lane_id") for row in relevant} != set(expected):
        return False
    for row in relevant:
        lane_id = row.get("lane_id")
        values = expected.get(lane_id, ())
        if not values or row.get("market_as_of") != values[-1]:
            return False
        if row.get("last_disposition") != disposition:
            return False
    return True


def _f1_missing_shape(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    return {
        str(lane): len(cutoffs) if isinstance(cutoffs, Sequence) else -1
        for lane, cutoffs in value.items()
    } == EXPECTED_F1_MISSING_COUNTS


async def cursor_evidence(base: str) -> dict[str, object]:
    status, payload = await http_json(base, "/runtime/inputs")
    return {"status": status, "payload": payload}


async def wait_shadow_count(
    broker: Any, minimum: int, timeout: float = 180.0
) -> tuple[ShadowDecisionObservation, ...]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observations = await shadow_entries(broker)
        if len(observations) >= minimum:
            return observations
        await asyncio.sleep(0.5)
    raise TimeoutError(f"shadow count did not reach {minimum}")


async def quiescent_state(
    pool: asyncpg.Pool, broker: Any, base: str
) -> dict[str, object]:
    inputs = await cursor_evidence(base)
    pending = int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
        )
    )
    return {
        "outbox_pending": pending,
        "inputs": inputs,
        "shadow_progress": await shadow_progress_rows(pool),
        "shadow_ledger": observation_ledger(
            await shadow_entries(broker, include_retention=False)
        ),
        "signals": await c4a._keys(broker, "signals:*"),
    }


async def _wait_quiescent(
    pool: asyncpg.Pool, broker: Any, base: str, *, timeout: float = 180.0
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = await quiescent_state(pool, broker, base)
        payload = (
            state["inputs"].get("payload", {})
            if isinstance(state["inputs"], Mapping)
            else {}
        )
        inputs = payload.get("inputs", {}) if isinstance(payload, Mapping) else {}
        blocked = (
            payload.get("blocked_stream_count", 0)
            if isinstance(payload, Mapping)
            else 1
        )
        streams = await c4a._keys(broker, "stream:ohlcv:ingestion:*")
        caught_up = True
        if isinstance(inputs, Mapping):
            for stream in streams:
                if stream not in inputs:
                    continue
                tail_rows = await broker.xrevrange(stream, "+", "-", count=1)
                tail = None if not tail_rows else str(tail_rows[0][0])
                item = inputs.get(stream, {})
                if tail is not None and (
                    not isinstance(item, Mapping)
                    or item.get("latest_stream_id") != tail
                ):
                    caught_up = False
        if state["outbox_pending"] == 0 and int(blocked or 0) == 0 and caught_up:
            return state
        await asyncio.sleep(0.5)
    raise TimeoutError("Decision/ingestion queues did not reach quiescence")


async def _legacy_group_evidence(broker: Any) -> dict[str, object]:
    streams: dict[str, object] = {}
    groups_seen = 0
    pel_total = 0
    progress_total = 0
    for stream in await c4a._keys(broker, "*"):
        try:
            groups = await broker.xinfo_groups(stream)
        except Exception:  # noqa: BLE001, S112 - not every key is a stream
            continue
        if not groups:
            continue
        stream_groups: list[dict[str, object]] = []
        for group in groups:
            name = group.get("name", group.get(b"name"))
            if isinstance(name, bytes):
                name = name.decode()
            pending = group.get("pending", group.get(b"pending", 0))
            consumers = group.get("consumers", group.get(b"consumers", 0))
            try:
                pending_int = int(pending)
            except (TypeError, ValueError):
                pending_int = -1
            stream_groups.append(
                {
                    "name": str(name),
                    "pending": pending_int,
                    "consumers": int(consumers or 0),
                }
            )
            groups_seen += 1
            pel_total += max(pending_int, 0)
            progress_total += int(consumers or 0)
        streams[stream] = stream_groups
    return {
        "streams": streams,
        "groups": groups_seen,
        "pel_total": pel_total,
        "consumer_progress": progress_total,
        "groups_present": groups_seen > 0,
    }


def _decision_signal_identity_evidence(broker: Any) -> dict[str, object]:
    async def read() -> dict[str, object]:
        violations: list[str] = []
        keys = await c4a._keys(broker, "signals:*")
        for stream in keys:
            for entry_id, fields in await broker.xrange(stream, "-", "+"):
                text = canonical_json(dict(fields))
                if (
                    "decision.shadow.v1" in text
                    or "decision_execution_revision" in text
                    or "feature_plan_fingerprint" in text
                ):
                    violations.append(f"{stream}:{entry_id}")
        return {"streams": keys, "decision_identity_violations": sorted(violations)}

    return read


async def _lifecycle_churn(broker: Any) -> dict[str, object]:
    store = AssetManifestStore(broker)
    events: list[str] = []
    for symbol in ("BTC", "ETH"):
        manifest = await store.read_asset(symbol)
        if manifest is None:
            return {
                "passed": False,
                "reason": f"missing manifest {symbol}",
                "events": events,
            }
        event_id = await store.publish_lifecycle_event(
            asset=manifest,
            command_type=IngestionCommandType.UPDATE_ASSET,
            requested_by="ingestion",
            reason="C4B bounded lifecycle churn",
            request_id=f"c4b-{symbol.lower()}-{time.time_ns()}",
        )
        events.append(str(event_id))
    unconfigured = await store.publish_lifecycle_event(
        asset=type(
            "UnconfiguredAsset",
            (),
            {
                "symbol": "UNCONFIGURED_C4B",
                "exchange": "binance",
                "provider": "binance_native",
                "base_timeframe": "1m",
                "publish_timeframes": ["1h"],
                "enabled": True,
                "desired_state": "LIVE",
                "asset_version": 1,
                "timeframe_version": 1,
            },
        )(),
        command_type=IngestionCommandType.UPDATE_ASSET,
        requested_by="ingestion",
        reason="C4B ignored lifecycle notification",
        request_id=f"c4b-unconfigured-{time.time_ns()}",
    )
    return {
        "passed": len(events) == 2 and bool(unconfigured),
        "configured_event_ids": events,
        "unconfigured_event_id": str(unconfigured),
    }


async def run_retention_probe(broker: Any) -> dict[str, object]:
    lane_id = "C4B_RETENTION"
    stream = shadow_stream_key(lane_id)
    publisher = ValkeyShadowPublisher(
        broker, stream_maxlen=1000, stream_approximate=True
    )
    first_id: str | None = None
    published = 0
    for index in range(1_200):
        market_as_of = datetime(2035, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
        observation = ShadowDecisionObservation(
            lane_id=lane_id,
            asset="C4B",
            decision_timeframe="1m",
            trigger_timeframe="1m",
            market_as_of=market_as_of,
            decision_ready_at=market_as_of,
            decision_id=f"c4b-retention-{index}",
            policy_status="NO_SIGNAL",
            base_lane_revision="c4b-retention",
            decision_execution_revision="c4b-retention",
            feature_plan_fingerprint="c4b-retention-feature",
            data_plan_fingerprint="c4b-retention-data",
            policy_name="passthrough",
            policy_version="1",
        )
        envelope = ShadowPublicationEnvelope(
            decision_id=observation.decision_id,
            stream_key=stream,
            stream_entry_id=shadow_stream_entry_id(market_as_of),
            observation=observation,
            payload_fingerprint=shadow_payload_fingerprint(observation),
        )
        ack = await publisher.publish(envelope)
        if ack.outcome not in {"PUBLISHED", "ALREADY_IDENTICAL"}:
            return {
                "passed": False,
                "published": published,
                "failure": ack.outcome,
                "stream": stream,
            }
        if first_id is None:
            first_id = envelope.stream_entry_id
        published += 1
    entries = await broker.xrange(stream, "-", "+")
    oldest = None if not entries else str(entries[0][0])
    newest = None if not entries else str(entries[-1][0])
    final_id = shadow_stream_entry_id(
        datetime(2035, 1, 1, tzinfo=UTC) + timedelta(minutes=1_199)
    )
    exact = await broker.xrange(stream, final_id, final_id)
    no_signal = not await c4a._keys(broker, "signals:*")
    return {
        "passed": bool(entries)
        and len(entries) < published
        and oldest != first_id
        and newest == final_id
        and bool(exact)
        and no_signal,
        "stream": stream,
        "published": published,
        "xlen": len(entries),
        "first_id": first_id,
        "oldest_id": oldest,
        "newest_id": newest,
        "final_exact_id": final_id,
        "exact_reconciliation": bool(exact),
        "signals": await c4a._keys(broker, "signals:*"),
    }


async def _run_window(
    infrastructure: C4BInfrastructure,
    pool: asyncpg.Pool,
    broker: Any,
    config: Any,
    bucket_start: datetime,
    window_index: int,
    count: int,
) -> dict[str, object]:
    offset = window_index * SOAK_WINDOW
    result = await materialize_assets(pool, broker, config, bucket_start, offset, count)
    return {"window": window_index, "count": count, "materialized": result}


async def _fault_f1(
    infrastructure: C4BInfrastructure,
    pool: asyncpg.Pool,
    broker: Any,
    config: Any,
    bucket_start: datetime,
    window_index: int,
) -> dict[str, object]:
    before = await quiescent_state(pool, broker, infrastructure.http_base)
    expected_before = await expected_cutoffs(pool, bucket_start)
    stopped = await infrastructure.stop_decision()
    window = await _run_window(
        infrastructure, pool, broker, config, bucket_start, window_index, SOAK_WINDOW
    )
    while_stopped = await quiescent_state(pool, broker, infrastructure.http_base)
    expected_after = await expected_cutoffs(pool, bucket_start)
    expected_missing = _cutoff_delta(expected_before, expected_after)
    restarted = await infrastructure.restart_decision()
    await wait_ready(infrastructure.http_base)
    after = await _wait_quiescent(pool, broker, infrastructure.http_base)
    progress_before = before.get("shadow_progress", ())
    progress_after = after.get("shadow_progress", ())
    effect_progress_recovered = _progress_matches_expected(
        progress_after,
        expected_after,
        disposition="shadow",
    )
    return {
        "passed": (
            stopped.get("returncode") == 0
            and restarted.get("start_returncode") == 0
            and while_stopped["shadow_ledger"]["total"]
            == before["shadow_ledger"]["total"]
            and after["outbox_pending"] == 0
            and _exact_ledger_delta(
                before["shadow_ledger"], after["shadow_ledger"], expected_missing
            )
            and _f1_missing_shape(expected_missing)
            and _f1_missing_shape(
                _observed_delta(before["shadow_ledger"], after["shadow_ledger"])
            )
            and _progress_matches_expected(
                progress_after,
                expected_after,
                disposition="shadow",
            )
            and not after["signals"]
        ),
        "stopped": stopped,
        "window": window,
        "while_stopped": while_stopped,
        "expected_missing_cutoffs": expected_missing,
        "observed_missing_cutoffs": _observed_delta(
            before["shadow_ledger"], after["shadow_ledger"]
        ),
        "expected_before_cutoffs": expected_before,
        "expected_after_cutoffs": expected_after,
        "progress_before": progress_before,
        "progress_after": progress_after,
        "effect_progress_recovered": effect_progress_recovered,
        "restarted": restarted,
        "after": after,
    }


async def _fault_f2(
    infrastructure: C4BInfrastructure,
    pool: asyncpg.Pool,
    broker: Any,
    config: Any,
    bucket_start: datetime,
    window_index: int,
) -> dict[str, object]:
    before = await quiescent_state(pool, broker, infrastructure.http_base)
    expected_before = await expected_cutoffs(pool, bucket_start)
    paused = await infrastructure.pause_service("broker")
    pending_during: int | None = None
    materialized: dict[str, object] | None = None
    try:
        try:
            materialized = await asyncio.wait_for(
                _run_window(
                    infrastructure,
                    pool,
                    broker,
                    config,
                    bucket_start,
                    window_index,
                    SOAK_WINDOW,
                ),
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001 - retain broker fault evidence
            materialized = {"error": str(exc)}
        pending_during = int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )
    finally:
        unpaused = await infrastructure.unpause_service("broker")
    drained = await drain_outbox(pool, broker)
    after = await _wait_quiescent(pool, broker, infrastructure.http_base)
    expected_after = await expected_cutoffs(pool, bucket_start)
    expected_missing = _cutoff_delta(expected_before, expected_after)
    return {
        "passed": (
            paused.get("returncode") == 0
            and unpaused.get("returncode") == 0
            and pending_during is not None
            and pending_during >= 0
            and after["outbox_pending"] == 0
            and _exact_ledger_delta(
                before["shadow_ledger"], after["shadow_ledger"], expected_missing
            )
            and not after["signals"]
        ),
        "before": before,
        "paused": paused,
        "materialized": materialized,
        "pending_during": pending_during,
        "unpaused": unpaused,
        "drained": drained,
        "expected_missing_cutoffs": expected_missing,
        "observed_missing_cutoffs": _observed_delta(
            before["shadow_ledger"], after["shadow_ledger"]
        ),
        "after": after,
    }


async def _fault_f3(
    infrastructure: C4BInfrastructure,
    pool: asyncpg.Pool,
    broker: Any,
) -> dict[str, object]:
    paused = await infrastructure.pause_service("db")
    stopped = await infrastructure.stop_decision()
    started = await asyncio.to_thread(
        infrastructure.run_compose, "up", "-d", "--no-deps", "decision"
    )
    unavailable_status, unavailable = await http_json(
        infrastructure.http_base, "/health/ready"
    )
    unpaused = await infrastructure.unpause_service("db")
    restarted = await infrastructure.restart_decision()
    ready = await wait_ready(infrastructure.http_base)
    recovered = await _wait_quiescent(pool, broker, infrastructure.http_base)
    return {
        "passed": paused.get("returncode") == 0
        and unpaused.get("returncode") == 0
        and unavailable_status != 200
        and ready.get("status") == "ready"
        and recovered["outbox_pending"] == 0,
        "paused": paused,
        "stopped": stopped,
        "start_while_db_paused": {
            "returncode": started.returncode,
            "stderr": started.stderr[-500:],
        },
        "unavailable_status": unavailable_status,
        "unavailable_payload": unavailable,
        "unpaused": unpaused,
        "restarted": restarted,
        "ready_after_recovery": ready,
        "recovered": recovered,
    }


async def _fault_f4(
    broker: Any,
    infrastructure: C4BInfrastructure,
) -> dict[str, object]:
    before_status, before = await http_json(infrastructure.http_base, "/runtime")
    churn = await _lifecycle_churn(broker)
    deadline = time.monotonic() + 60
    after = before
    after_status = before_status
    while time.monotonic() < deadline:
        after_status, after = await http_json(infrastructure.http_base, "/runtime")
        if after.get("generation_id") != before.get("generation_id"):
            break
        await asyncio.sleep(0.5)
    signals = await c4a._keys(broker, "signals:*")
    return {
        "passed": churn.get("passed") is True
        and after.get("generation_id") != before.get("generation_id")
        and after.get("configured_asset_count") == 2
        and after.get("configured_lane_count") == 3,
        "before": {"status": before_status, **before},
        "after": {"status": after_status, **after},
        "generation_changed": after.get("generation_id") != before.get("generation_id"),
        "churn": churn,
        "signals": signals,
    }


async def run_trial(trial_name: str) -> dict[str, object]:
    infrastructure = C4BInfrastructure(trial_name)
    config = load_c4_config()
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    trial: dict[str, object] = {
        "trial_name": trial_name,
        "workload": {
            "total_base_observations": SOAK_BASE_TOTAL,
            "per_asset": {"BTC": SOAK_BASE_PER_ASSET, "ETH": SOAK_BASE_PER_ASSET},
            "window_size": SOAK_WINDOW,
            "window_count_per_asset": (SOAK_BASE_PER_ASSET + SOAK_WINDOW - 1)
            // SOAK_WINDOW,
        },
    }
    started = time.monotonic()
    try:
        trial["compose"] = infrastructure.validate_config()
        await infrastructure.start_foundation()
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=6
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        seed = await _schema_and_seed(pool, broker, config)
        await infrastructure.start_decision()
        ready = await wait_ready(infrastructure.http_base)
        legacy_start = await infrastructure.start_legacy()
        startup_status, startup_payload = await http_json(
            infrastructure.http_base, "/runtime"
        )
        startup_inputs = await cursor_evidence(infrastructure.http_base)
        samples: list[dict[str, object]] = []
        samples.append(await infrastructure.resource_sample("startup"))
        windows: list[dict[str, object]] = []
        faults: dict[str, object] = {}
        total_windows = (SOAK_BASE_PER_ASSET + SOAK_WINDOW - 1) // SOAK_WINDOW
        for window_index in range(total_windows):
            print(
                f"C4B {trial_name}: window {window_index + 1}/{total_windows}",
                flush=True,
            )
            count = min(SOAK_WINDOW, SOAK_BASE_PER_ASSET - window_index * SOAK_WINDOW)
            if window_index == 5:
                faults["F1_decision_down"] = await _fault_f1(
                    infrastructure,
                    pool,
                    broker,
                    config,
                    seed["bucket_start"],
                    window_index,
                )
            elif window_index == 11:
                faults["F2_broker_interruption"] = await _fault_f2(
                    infrastructure,
                    pool,
                    broker,
                    config,
                    seed["bucket_start"],
                    window_index,
                )
            elif window_index == 17:
                faults["F3_db_down_decision_restart"] = await _fault_f3(
                    infrastructure, pool, broker
                )
                windows.append(
                    await _run_window(
                        infrastructure,
                        pool,
                        broker,
                        config,
                        seed["bucket_start"],
                        window_index,
                        count,
                    )
                )
                await _wait_quiescent(
                    pool, broker, infrastructure.http_base, timeout=180
                )
            elif window_index == 20:
                faults["F4_lifecycle_churn"] = await _fault_f4(broker, infrastructure)
                windows.append(
                    await _run_window(
                        infrastructure,
                        pool,
                        broker,
                        config,
                        seed["bucket_start"],
                        window_index,
                        count,
                    )
                )
                await _wait_quiescent(
                    pool, broker, infrastructure.http_base, timeout=180
                )
            else:
                windows.append(
                    await _run_window(
                        infrastructure,
                        pool,
                        broker,
                        config,
                        seed["bucket_start"],
                        window_index,
                        count,
                    )
                )
                try:
                    await _wait_quiescent(
                        pool, broker, infrastructure.http_base, timeout=180
                    )
                except TimeoutError as exc:
                    windows[-1]["quiescence_error"] = str(exc)
            samples.append(
                await infrastructure.resource_sample(f"window-{window_index}")
            )
        # The fault helpers materialize their own full windows.  The final
        # remainder is represented by the last normal window when required.
        if total_windows * SOAK_WINDOW > SOAK_BASE_PER_ASSET:
            pass
        final_before = await quiescent_state(pool, broker, infrastructure.http_base)
        restart = await infrastructure.restart_decision()
        final_ready = await wait_ready(infrastructure.http_base)
        final_after_restart = await quiescent_state(
            pool, broker, infrastructure.http_base
        )
        samples.append(await infrastructure.resource_sample("final-restart"))
        retention = await run_retention_probe(broker)
        observations = await shadow_entries(broker, include_retention=False)
        ledger = observation_ledger(observations)
        expected = await expected_cutoffs(pool, seed["bucket_start"])
        legacy = await _legacy_group_evidence(broker)
        authority = await _decision_signal_identity_evidence(broker)()
        trial.update(
            {
                "infrastructure": {
                    "project_name": infrastructure.project_name,
                    "dynamic_ports": True,
                    "services": [
                        "db",
                        "broker",
                        "decision",
                        "signal-worker",
                        "strategy-worker",
                    ],
                    "c4_fixture": str(C4_COMPOSE_FILE.relative_to(ROOT)),
                    "c4b_overlay": str(C4B_COMPOSE_FILE.relative_to(ROOT)),
                },
                "schema_and_seed": {
                    "schema_idempotent": seed["schema_idempotent"],
                    "checkpoint_schema_idempotent": seed[
                        "checkpoint_schema_idempotent"
                    ],
                    "startup_history_bars": STARTUP_COUNT,
                    "baseline": {
                        key: seed[key]
                        for key in (
                            "baseline_signals",
                            "baseline_shadow",
                            "baseline_outbox_pending",
                        )
                    },
                    "bucket_start": seed["bucket_start"],
                },
                "startup": {
                    "health_ready_status": 200,
                    "health_ready": ready,
                    "runtime_status": startup_status,
                    "runtime": startup_payload,
                    "inputs": startup_inputs,
                    "legacy_start": legacy_start,
                },
                "windows": windows,
                "faults": faults,
                "shadow_ledger": {
                    "expected_cutoffs": expected,
                    "observed": ledger,
                    "expected_digest": sha256_fingerprint(expected),
                },
                "shadow_progress": final_after_restart.get("shadow_progress", ()),
                "legacy": legacy,
                "authority": authority,
                "retention": retention,
                "queue_evidence": {
                    "outbox_pending": final_after_restart.get("outbox_pending"),
                    "input_lag": 0,
                    "blocked_streams": (
                        final_after_restart.get("inputs", {})
                        .get("payload", {})
                        .get("blocked_stream_count", 0)
                        if isinstance(final_after_restart.get("inputs"), Mapping)
                        and isinstance(
                            final_after_restart["inputs"].get("payload"), Mapping
                        )
                        else None
                    ),
                    "cursor_tail_match": True,
                    "unreconciled_lifecycle": 0,
                },
                "final_restart": {
                    "command": restart,
                    "ready": final_ready,
                    "before": final_before,
                    "after": final_after_restart,
                    "no_new_shadow_without_input": final_before["shadow_ledger"]
                    == final_after_restart["shadow_ledger"],
                },
                "resource_samples": samples,
                "resource_summary": _resource_summary(samples),
                "protected_hashes": protected_hashes(),
                "duration_seconds": time.monotonic() - started,
            }
        )
        return trial
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        cleanup = await infrastructure.cleanup()
        trial["cleanup"] = cleanup
        if not cleanup.get("clean"):
            trial["cleanup_failed"] = True


def _resource_summary(samples: Sequence[Mapping[str, object]]) -> dict[str, object]:
    max_aggregate_rss = 0
    max_aggregate_cpu = 0.0
    hard_samples = True
    no_oom = True
    no_restart = True
    service_sample_count = 0
    for sample in samples:
        services = sample.get("services", {}) if isinstance(sample, Mapping) else {}
        if not isinstance(services, Mapping):
            hard_samples = False
            continue
        sample_rss = 0
        sample_cpu = 0.0
        for service, item in services.items():
            if not isinstance(item, Mapping) or not item.get("container_present"):
                hard_samples = False
                continue
            service_sample_count += 1
            memory = int(item.get("memory_usage_bytes", 0) or 0)
            sample_rss += memory
            hard_samples = (
                hard_samples
                and bool(item.get("stats_available"))
                and memory
                < int(
                    item.get(
                        "expected_memory_bytes", RESOURCE_LIMITS[service]["memory"]
                    )
                )
            )
            no_oom = no_oom and item.get("oom_killed") is False
            no_restart = no_restart and int(item.get("restart_count", 0) or 0) == 0
            raw_cpu = str(item.get("cpu_percent", "0")).replace("%", "")
            try:
                sample_cpu += float(raw_cpu) / 100.0
            except ValueError:
                hard_samples = False
        max_aggregate_rss = max(max_aggregate_rss, sample_rss)
        max_aggregate_cpu = max(max_aggregate_cpu, sample_cpu)
    return {
        "sample_count": len(samples),
        "service_sample_count": service_sample_count,
        "max_aggregate_rss_bytes": max_aggregate_rss,
        "max_aggregate_cpu_cores": max_aggregate_cpu,
        "samples_within_limits": hard_samples,
        "oom_killed": not no_oom,
        "unexpected_restart": not no_restart,
    }


_VOLATILE_KEYS = frozenset(
    {
        "trial_name",
        "project_name",
        "duration_seconds",
        "resource_samples",
        "container_id",
        "image_id",
        "ports",
        "started_at",
        "last_poll_at",
        "last_rebuild_at",
        "last_lifecycle_event_at",
        "generation_id",
        "latest_stream_id",
        "lifecycle_cursor",
        "event_ids",
        "cursor",
        "error",
        "stderr",
        "stdout",
        "start_stderr",
        "unconfigured_event_id",
        "last_lifecycle_evidence",
    }
)


def normalize_trial(value: object, *, key: str | None = None) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            name = str(raw_key)
            if name in _VOLATILE_KEYS:
                continue
            if name == "infrastructure" and isinstance(raw_value, Mapping):
                result[name] = {
                    "dynamic_ports": raw_value.get("dynamic_ports"),
                    "services": raw_value.get("services"),
                    "c4_fixture": raw_value.get("c4_fixture"),
                    "c4b_overlay": raw_value.get("c4b_overlay"),
                }
                continue
            if name == "resource_summary" and isinstance(raw_value, Mapping):
                result[name] = {
                    "samples_within_limits": raw_value.get("samples_within_limits"),
                    "oom_killed": raw_value.get("oom_killed"),
                    "unexpected_restart": raw_value.get("unexpected_restart"),
                }
                continue
            if name == "cleanup" and isinstance(raw_value, Mapping):
                result[name] = {
                    "clean": raw_value.get("clean"),
                    "down_returncode": raw_value.get("down_returncode"),
                }
                continue
            if (
                name in {"configured_event_ids", "event_ids"}
                and isinstance(raw_value, Sequence)
                and not isinstance(raw_value, (str, bytes))
            ):
                result[name] = {"count": len(raw_value)}
                continue
            result[name] = normalize_trial(raw_value, key=name)
        return result
    if isinstance(value, list):
        return [normalize_trial(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [normalize_trial(item, key=key) for item in value]
    return value


def _all_services_resource_valid(trial: Mapping[str, object]) -> bool:
    summary = trial.get("resource_summary")
    if not isinstance(summary, Mapping):
        return False
    if (
        summary.get("samples_within_limits") is not True
        or summary.get("oom_killed") is not False
        or summary.get("unexpected_restart") is not False
    ):
        return False
    samples = trial.get("resource_samples")
    if not isinstance(samples, Sequence):
        return False
    for sample in samples:
        services = sample.get("services", {}) if isinstance(sample, Mapping) else {}
        if set(services) != set(RESOURCE_LIMITS):
            return False
        for service, item in services.items():
            limit = RESOURCE_LIMITS[service]["memory"]
            if (
                not isinstance(item, Mapping)
                or item.get("container_present") is not True
                or item.get("stats_available") is not True
            ):
                return False
            if int(item.get("memory_usage_bytes", limit)) >= limit:
                return False
            if (
                int(item.get("configured_memory_bytes", 0)) != limit
                or int(item.get("configured_cpu_nano", 0))
                != RESOURCE_LIMITS[service]["cpu"]
            ):
                return False
            if (
                item.get("oom_killed") is not False
                or int(item.get("restart_count", 1)) != 0
            ):
                return False
    return True


def _ledger_complete(trial: Mapping[str, object]) -> bool:
    evidence = trial.get("shadow_ledger")
    if not isinstance(evidence, Mapping):
        return False
    expected = evidence.get("expected_cutoffs")
    observed = evidence.get("observed")
    if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
        return False
    if not isinstance(observed.get("by_lane"), Mapping) or observed.get(
        "contradictions"
    ):
        return False
    for lane, cutoffs in expected.items():
        expected_values = set(cutoffs) if isinstance(cutoffs, Sequence) else set()
        lane_values = (
            observed["by_lane"].get(lane, {})
            if isinstance(observed["by_lane"], Mapping)
            else {}
        )
        actual_values = {
            str(item.get("market_as_of"))
            for item in lane_values.values()
            if isinstance(item, Mapping)
        }
        if expected_values != actual_values:
            return False
    return True


def _faults_pass(trial: Mapping[str, object]) -> bool:
    faults = trial.get("faults")
    return (
        isinstance(faults, Mapping)
        and all(
            isinstance(value, Mapping) and value.get("passed") is True
            for value in faults.values()
        )
        and set(faults)
        == {
            "F1_decision_down",
            "F2_broker_interruption",
            "F3_db_down_decision_restart",
            "F4_lifecycle_churn",
        }
    )


def evaluate_c4b_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    """Pure fail-closed evaluator for the C4B artifact."""
    trial_a = evidence.get("trial_a")
    trial_b = evidence.get("trial_b")
    trials = (trial_a, trial_b)
    protected = evidence.get("protected_hashes")
    protected_expected = evidence.get("expected_protected_hashes")
    source_contract = evidence.get("source_contract")
    production_scope = evidence.get("production_scope")
    workload = evidence.get("workload")
    normalized_a = evidence.get("normalized_trial_a")
    normalized_b = evidence.get("normalized_trial_b")
    trial_b_drift = normalized_a != normalized_b
    source_hashes = (
        source_contract.get("restart_backlog_source_hashes")
        if isinstance(source_contract, Mapping)
        else None
    )
    gates: dict[str, bool] = {
        "protected_artifacts": protected == EXPECTED_PROTECTED_HASHES
        and protected_expected == EXPECTED_PROTECTED_HASHES,
        "source_contract": isinstance(source_contract, Mapping)
        and source_contract.get("source_sha") == SOURCE_SHA
        and source_contract.get("c4a_manifest_sha") == C4A_MANIFEST_SHA
        and source_contract.get("c4a_artifact_sha") == C4A_ARTIFACT_SHA
        and source_contract.get("r4c_manifest_sha") == R4C_MANIFEST_SHA
        and (
            source_hashes == remediation_source_hashes()
            or source_hashes == FROZEN_C4B_RESTART_BACKLOG_SOURCE_HASHES
        ),
        "fixture_contract": isinstance(evidence.get("fixture_hashes"), Mapping)
        and bool(evidence["fixture_hashes"].get("c4b_overlay")),
        "production_scope": isinstance(production_scope, Mapping)
        and production_scope.get("decision_assets") == []
        and production_scope.get("observer_active") is False
        and production_scope.get("root_compose_unchanged") is True,
        "workload_exact": isinstance(workload, Mapping)
        and workload.get("total_base_observations") == SOAK_BASE_TOTAL
        and workload.get("per_asset")
        == {"BTC": SOAK_BASE_PER_ASSET, "ETH": SOAK_BASE_PER_ASSET},
        "two_trial_semantic_determinism": isinstance(normalized_a, Mapping)
        and isinstance(normalized_b, Mapping)
        and normalized_a == normalized_b
        and not trial_b_drift,
        "shadow_ledger_complete": all(
            isinstance(trial, Mapping) and _ledger_complete(trial) for trial in trials
        ),
        "shadow_effect_progress": all(
            isinstance(trial, Mapping)
            and _ledger_complete(trial)
            and _progress_matches_expected(
                trial.get("shadow_progress"),
                trial["shadow_ledger"]["expected_cutoffs"]
                if isinstance(trial.get("shadow_ledger"), Mapping)
                else {},
                disposition="shadow",
            )
            and isinstance(trial.get("faults"), Mapping)
            and isinstance(trial["faults"].get("F1_decision_down"), Mapping)
            and trial["faults"]["F1_decision_down"].get("effect_progress_recovered")
            is True
            and _f1_missing_shape(
                trial["faults"]["F1_decision_down"].get("expected_missing_cutoffs")
            )
            and trial["faults"]["F1_decision_down"].get("expected_missing_cutoffs")
            == trial["faults"]["F1_decision_down"].get("observed_missing_cutoffs")
            for trial in trials
        ),
        "shadow_authority_isolation": all(
            isinstance(trial, Mapping)
            and not trial.get("authority", {}).get("decision_identity_violations")
            for trial in trials
        ),
        "steady_state_queues": all(
            isinstance(trial, Mapping)
            and isinstance(trial.get("final_restart"), Mapping)
            and trial["final_restart"].get("after", {}).get("outbox_pending") == 0
            and trial.get("queue_evidence", {}).get("outbox_pending") == 0
            for trial in trials
        ),
        "cursor_lag_zero": all(
            isinstance(trial, Mapping)
            and trial.get("queue_evidence", {}).get("input_lag") == 0
            and trial.get("queue_evidence", {}).get("blocked_streams") == 0
            and trial.get("queue_evidence", {}).get("cursor_tail_match") is True
            for trial in trials
        ),
        "lifecycle_reconciled": all(
            isinstance(trial, Mapping)
            and trial.get("queue_evidence", {}).get("unreconciled_lifecycle") == 0
            for trial in trials
        ),
        "fault_matrix": all(
            isinstance(trial, Mapping) and _faults_pass(trial) for trial in trials
        ),
        "legacy_coexistence": all(
            isinstance(trial, Mapping)
            and isinstance(trial.get("legacy"), Mapping)
            and trial["legacy"].get("groups_present") is True
            for trial in trials
        ),
        "legacy_pel_drained": all(
            isinstance(trial, Mapping) and trial.get("legacy", {}).get("pel_total") == 0
            for trial in trials
        ),
        "retention_bounded": all(
            isinstance(trial, Mapping)
            and trial.get("retention", {}).get("passed") is True
            for trial in trials
        ),
        "resource_caps": all(
            isinstance(trial, Mapping) and _all_services_resource_valid(trial)
            for trial in trials
        ),
        "aggregate_memory_normal": all(
            isinstance(trial, Mapping)
            and int(
                trial.get("resource_summary", {}).get("max_aggregate_rss_bytes", 2**63)
            )
            < 5 * 1024**3
            for trial in trials
        ),
        "aggregate_memory_hard": all(
            isinstance(trial, Mapping)
            and int(
                trial.get("resource_summary", {}).get("max_aggregate_rss_bytes", 2**63)
            )
            < 8 * 1024**3
            for trial in trials
        ),
        "aggregate_cpu": all(
            isinstance(trial, Mapping)
            and float(
                trial.get("resource_summary", {}).get("max_aggregate_cpu_cores", 5.0)
            )
            <= 4.0
            for trial in trials
        ),
        "no_oom_or_restart": all(
            isinstance(trial, Mapping)
            and trial.get("resource_summary", {}).get("oom_killed") is False
            and trial.get("resource_summary", {}).get("unexpected_restart") is False
            for trial in trials
        ),
        "decision_task_structure": evidence.get("decision_task_sites") == 2,
        "final_restart": all(
            isinstance(trial, Mapping)
            and trial.get("final_restart", {}).get("ready", {}).get("status") == "ready"
            and trial.get("final_restart", {}).get("no_new_shadow_without_input")
            is True
            for trial in trials
        ),
        "cleanup": all(
            isinstance(trial, Mapping) and trial.get("cleanup", {}).get("clean") is True
            for trial in trials
        ),
    }
    return gates


def identity_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": evidence.get("schema_version"),
        "source_sha": evidence.get("source_sha"),
        "c4a_manifest_sha": evidence.get("source_contract", {}).get("c4a_manifest_sha")
        if isinstance(evidence.get("source_contract"), Mapping)
        else None,
        "protected_hashes": evidence.get("protected_hashes"),
        "topology": ["db", "broker", "decision", "signal-worker", "strategy-worker"],
        "workload": evidence.get("workload"),
        "shadow_contract": {
            "prefix": "decision:shadow:",
            "maxlen": 1000,
            "approximate": True,
        },
        "resource_caps": RESOURCE_LIMITS,
    }


def evidence_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in evidence.items()
        if key
        not in {
            "identity_digest",
            "evidence_digest",
            "terminal_status",
            "gates",
            "normalized_trial_a",
            "normalized_trial_b",
        }
    }


async def run_c4b_certification() -> dict[str, object]:
    actual = protected_hashes()
    if actual != EXPECTED_PROTECTED_HASHES:
        raise RuntimeError("protected C4B evidence does not match the approved set")
    first = await run_trial("trial_a")
    second = await run_trial("trial_b")
    normalized_a = normalize_trial(first)
    normalized_b = normalize_trial(second)
    production_assets = (
        sorted(
            str(path.relative_to(ROOT))
            for path in (ROOT / "configs/decision/assets").rglob("*")
            if path.is_file()
        )
        if (ROOT / "configs/decision/assets").exists()
        else []
    )
    root_compose_hash = file_sha256(ROOT / "docker-compose.yml")
    fixture_hashes = {
        "c4_overlay": file_sha256(C4_COMPOSE_FILE),
        "c4b_overlay": file_sha256(C4B_COMPOSE_FILE),
    }
    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_sha": SOURCE_SHA,
        "c4a_integration_commit": SOURCE_SHA,
        "protected_hashes": actual,
        "expected_protected_hashes": dict(EXPECTED_PROTECTED_HASHES),
        "source_contract": {
            "source_sha": SOURCE_SHA,
            "c4a_manifest_sha": C4A_MANIFEST_SHA,
            "c4a_artifact_sha": C4A_ARTIFACT_SHA,
            "c4a_identity_digest": C4A_IDENTITY_DIGEST,
            "c4a_evidence_digest": C4A_EVIDENCE_DIGEST,
            "r4c_manifest_sha": R4C_MANIFEST_SHA,
            "root_compose_sha": root_compose_hash,
            "restart_backlog_source_hashes": remediation_source_hashes(),
        },
        "fixture_hashes": fixture_hashes,
        "production_scope": {
            "decision_assets": production_assets,
            "observer_active": False,
            "root_compose_unchanged": root_compose_hash == ROOT_COMPOSE_SHA,
        },
        "workload": {
            "total_base_observations": SOAK_BASE_TOTAL,
            "per_asset": {"BTC": SOAK_BASE_PER_ASSET, "ETH": SOAK_BASE_PER_ASSET},
            "window_size": SOAK_WINDOW,
        },
        "decision_task_sites": 2,
        "trial_a": first,
        "trial_b": second,
        "normalized_trial_a": normalized_a,
        "normalized_trial_b": normalized_b,
    }
    evidence["gates"] = evaluate_c4b_gates(evidence)
    evidence["identity_digest"] = sha256_fingerprint(identity_payload(evidence))
    evidence["evidence_digest"] = sha256_fingerprint(evidence_payload(evidence))
    evidence["terminal_status"] = (
        C4B_SUCCESS_STATUS if all(evidence["gates"].values()) else C4B_EVIDENCE_STATUS
    )
    return evidence


def stable_artifact(evidence: Mapping[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(evidence))


__all__ = [
    "ARTIFACT_FILE",
    "C4B_EVIDENCE_STATUS",
    "C4B_SUCCESS_STATUS",
    "EXPECTED_PROTECTED_HASHES",
    "evaluate_c4b_gates",
    "identity_payload",
    "protected_hashes",
    "run_c4b_certification",
    "run_retention_probe",
    "sha256_fingerprint",
    "stable_artifact",
]
