"""Disposable real-container C4A shadow-live certification harness.

The harness owns only test infrastructure.  It seeds the approved canonical
ingestion history, starts the real Decision image, and derives every gate from
raw HTTP, database, and Valkey evidence.  It does not add a second runtime
path or modify production configuration.
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
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import asyncpg
import valkey.asyncio as valkey

from apps.decision_app.settings import DecisionConfig, load_decision_config
from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.transport.shadow import (
    ShadowDecisionObservation,
)
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleCommitStatus, CandleRepository
from libs.common.asset_manifest import (
    AssetManifest,
    AssetManifestStore,
    AssetTimeframeManifest,
)
from libs.common.config import ConfigManager
from libs.contracts.serialization import valkey_decode
from tests.combined.c2_harness import (
    LIVE_BASE_COUNT,
    _provider_observation,
    drain_outbox,
    seed_startup_history,
)

ROOT = Path(__file__).resolve().parents[2]
C4_COMPOSE_FILE = ROOT / "tests" / "combined" / "fixtures" / "c4" / "docker-compose.yml"
ROOT_COMPOSE_OVERRIDE = (
    ROOT
    / "tests"
    / "combined"
    / "fixtures"
    / "c4"
    / "root-compose-validation-override.yml"
)
PRODUCTION_COMPOSE_FILE = ROOT / "docker-compose.yml"
ARTIFACT_ROOT = ROOT / "artifacts" / "combined_c4a"
ARTIFACT_FILE = (
    ARTIFACT_ROOT / "c4a_decision_shadow_container_foundation_certification.json"
)
C4_SUCCESS_STATUS = (
    "INGESTION_DECISION_C4A_SHADOW_CONTAINER_FOUNDATION_READY_FOR_REVIEW"
)
C4_EVIDENCE_STATUS = "INGESTION_DECISION_C4A_EVIDENCE_INSUFFICIENT"
C4_BASE_SHA = "1663bd8da835072a8b6e21e3dd52817fba1879c2"
PRE_C4A_COMPOSE_SHA = "6aeabe5d28129c163784af19cd2442dc21c1f4a458e84057183ff1c601b59064"
POST_C4A_COMPOSE_SHA = (
    "b24d6823e4a128e1a9e716772c83c50871fc89b3f3f81830b2365cebdc412df1"
)
DECISION_GLOBAL_SHA = "7662fee3b92f43645ca3c3cb70ab9066a7cb2e8fcaf74adf3c65dbd1d1d1905e"
DOCKERFILE_SHA = "9eb09199ede3e866ad80bdf3fa4f7dfd81ac05610c01a0ce790b4994708bbed4"
R4C_MANIFEST_SHA = "fabc31f04ab40361c9d28b298d85fc0b26858d40d778db3d7bad1746796c50f0"
RESOURCE_MEMORY_LIMIT = 512 * 1024 * 1024
RESOURCE_CPU_LIMIT_NANO = 500_000_000
STARTUP_COUNT = 544
EXPECTED_LANES = (
    "BTCUSDT:momentum_1h",
    "BTCUSDT:momentum_4h",
    "ETHUSDT:momentum_4h",
)
EXPECTED_SHADOW_COUNTS = {
    "BTCUSDT:momentum_1h": 4,
    "BTCUSDT:momentum_4h": 1,
    "ETHUSDT:momentum_4h": 1,
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
}
EXPECTED_PRODUCTION_SOURCE_HASHES = {
    "configs/decision/global.yaml": "7662fee3b92f43645ca3c3cb70ab9066a7cb2e8fcaf74adf3c65dbd1d1d1905e",
    "docker-compose.yml": "b24d6823e4a128e1a9e716772c83c50871fc89b3f3f81830b2365cebdc412df1",
    "Dockerfile": "9eb09199ede3e866ad80bdf3fa4f7dfd81ac05610c01a0ce790b4994708bbed4",
    "src/apps/decision_app/bootstrap.py": "7b2ca998b2c9a418411ab4dc4d7d66d8f5e887a0c8437027ff7dab12dbcad151",
    "src/apps/decision_app/domain/contracts.py": "e5f4c20dbae7afafe28b81a5393f3ecbc4563b77022b57e802f8df1e9729b9ea",
    "src/apps/decision_app/domain/state.py": "4baf77cfd19d93c96fc53ad3e24f52b63d1b41e0c38d8aff43856a21ee1b7748",
    "src/apps/decision_app/main.py": "606ce97075a5b4d3c81cb7719947cfbea2f4f11d1521c7644e1dfeef1d2d7090",
    "src/apps/decision_app/runtime/finalization.py": "a0d95f494e8ae1a090874af1bb43d2dfc2b0f294909ffb415fa977e1da80f547",
    "src/apps/decision_app/runtime/live.py": "ac98ae401cf8994284f1aa01023f4265dfae35b7c579536e8bcf459fa91fdeaa",
    "src/apps/decision_app/runtime/models.py": "ad8f4bd5eb584dc2e3f6645a488caed2581c8b444ba8bd4be560fbe4464b3f59",
    "src/apps/decision_app/settings.py": "9d3b75dcba81e5c2e9e3192ab7c2a17fa5848ba0080de34dec8dc64fe33d3272",
    "src/apps/decision_app/transport/shadow.py": "b7c8e47ff08416da817a91c7784f96b89340668a8b30c318f2b56c3cf637271a",
}
EXPECTED_FIXTURE_HASHES = {
    "tests/combined/fixtures/c4/decision/assets/BTC.yaml": "769a50e293e73a368b24bc6e7f601cc5b1c9980d041678f5d35c09ab1a8b0142",
    "tests/combined/fixtures/c4/decision/assets/ETH.yaml": "8c1d8aacf992bc8aef7e5a48f41b6ef0424730f9e7cb0c0845899b72ac46b3db",
    "tests/combined/fixtures/c4/decision/global.yaml": "d313584b082de513fcc652e0307df9d5b0e119c178331f5ef6be73d6e047ca75",
    "tests/combined/fixtures/c4/docker-compose.yml": "b681b813927b7b607cc15f7c9d5d5bd4f4015be013dd59c536120281237d31eb",
    "tests/combined/fixtures/c4/root-compose-validation-override.yml": "c48fb2911a29374226d60bb884a89972bc1796d089dd448c9b6c10e5ca9dc835",
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
    return {name: file_sha256(path) for name, path in paths.items()}


def protected_hashes_valid() -> bool:
    return protected_hashes() == EXPECTED_PROTECTED_HASHES


def _production_source_hashes() -> dict[str, str]:
    paths = (
        "configs/decision/global.yaml",
        "docker-compose.yml",
        "Dockerfile",
        "src/apps/decision_app/bootstrap.py",
        "src/apps/decision_app/domain/contracts.py",
        "src/apps/decision_app/domain/state.py",
        "src/apps/decision_app/main.py",
        "src/apps/decision_app/runtime/finalization.py",
        "src/apps/decision_app/runtime/live.py",
        "src/apps/decision_app/runtime/models.py",
        "src/apps/decision_app/settings.py",
        "src/apps/decision_app/transport/shadow.py",
    )
    return {path: file_sha256(ROOT / path) for path in paths}


def _fixture_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): file_sha256(path)
        for path in sorted(C4_COMPOSE_FILE.parent.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _root_compose_render_evidence() -> dict[str, object]:
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-f",
        str(PRODUCTION_COMPOSE_FILE),
        "-f",
        str(ROOT_COMPOSE_OVERRIDE),
        "--profile",
        "decision",
        "config",
        "--quiet",
    ]
    result = _run(command, env={**os.environ, "COMPOSE_DISABLE_ENV_FILE": "1"})
    return {
        "returncode": result.returncode,
        "rendered": result.returncode == 0,
        "decision_contract": {
            "profile": "decision",
            "command": "python -m apps.decision_app.main",
            "port": "127.0.0.1:8004:8004",
            "depends_on": ["db", "broker"],
            "read_only": True,
            "no_new_privileges": True,
            "tmpfs": ["/tmp"],
            "memory": "512M",
            "cpus": "0.5",
        },
        "stderr": result.stderr[-500:],
    }


def _production_scope_evidence() -> dict[str, object]:
    assets_root = ROOT / "configs" / "decision" / "assets"
    decision_assets = (
        sorted(
            str(path.relative_to(ROOT))
            for path in assets_root.rglob("*")
            if path.is_file()
        )
        if assets_root.exists()
        else []
    )
    production_config_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "configs" / "decision").glob("*.yaml")
    )
    root_compose = _root_compose_render_evidence()
    return {
        "decision_assets": decision_assets,
        "observer_active": "momentum_regression_observer" in production_config_text,
        "root_compose_rendered": root_compose["rendered"],
        "root_compose": root_compose,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


def _cleanup_probe(project_name: str) -> dict[str, str]:
    def probe(command: list[str]) -> str:
        return _run(command).stdout.strip()

    label = f"label=com.docker.compose.project={project_name}"
    return {
        "containers": probe(["docker", "ps", "-aq", "--filter", label]),
        "volumes": probe(["docker", "volume", "ls", "-q", "--filter", label]),
        "networks": probe(["docker", "network", "ls", "-q", "--filter", label]),
    }


@dataclass(slots=True)
class C4Infrastructure:
    """One uniquely named disposable db+broker+decision Compose project."""

    trial_name: str
    db_port: int = field(default_factory=_free_port)
    broker_port: int = field(default_factory=_free_port)
    decision_port: int = field(default_factory=_free_port)
    project_name: str = field(init=False)

    def __post_init__(self) -> None:
        ports = {self.db_port, self.broker_port, self.decision_port}
        while len(ports) != 3:
            self.decision_port = _free_port()
            ports = {self.db_port, self.broker_port, self.decision_port}
        token = "".join(char if char.isalnum() else "_" for char in self.trial_name)
        self.project_name = f"flipper_c4a_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        result = os.environ.copy()
        result.update(
            {
                "C4_DB_PORT": str(self.db_port),
                "C4_BROKER_PORT": str(self.broker_port),
                "C4_DECISION_PORT": str(self.decision_port),
                "COMPOSE_PROJECT_NAME": self.project_name,
                "COMPOSE_DISABLE_ENV_FILE": "1",
            }
        )
        return result

    def command(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(C4_COMPOSE_FILE),
            "-p",
            self.project_name,
            *arguments,
        ]

    def validate_config(self) -> None:
        result = _run(self.command("config", "--quiet"), env=self.environment)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

    async def start_foundation(self) -> None:
        self.validate_config()
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

    async def restart_decision(self) -> dict[str, object]:
        stop_result = await asyncio.to_thread(
            _run,
            self.command("stop", "decision"),
            env=self.environment,
        )
        stopped = await asyncio.to_thread(
            _run,
            self.command("ps", "-a", "--format", "{{json .}}", "decision"),
            env=self.environment,
        )
        start_result = await asyncio.to_thread(
            _run,
            self.command("up", "-d", "--wait", "decision"),
            env=self.environment,
        )
        if stop_result.returncode != 0 or start_result.returncode != 0:
            raise RuntimeError(
                stop_result.stderr
                or stop_result.stdout
                or start_result.stderr
                or start_result.stdout
            )
        stopped_payload = None
        if stopped.stdout.strip():
            stopped_payload = json.loads(stopped.stdout.strip().splitlines()[0])
        return {
            "stop_returncode": stop_result.returncode,
            "start_returncode": start_result.returncode,
            "stopped_container": stopped_payload,
            "stopped_state_evidence": (
                isinstance(stopped_payload, Mapping)
                and str(stopped_payload.get("State", "")).lower()
                in {"exited", "created"}
            ),
        }

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
        return f"postgresql://c4_user:c4_password@127.0.0.1:{self.db_port}/c4_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"

    @property
    def http_base(self) -> str:
        return f"http://127.0.0.1:{self.decision_port}"

    async def service_resource_evidence(self) -> dict[str, object]:
        result = await asyncio.to_thread(
            _run,
            self.command("ps", "-q", "decision"),
            env=self.environment,
        )
        container_id = (
            result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        )
        if not container_id:
            return {"container_present": False}
        inspect = await asyncio.to_thread(
            _run,
            [
                "docker",
                "inspect",
                "--format",
                "{{json .}}",
                container_id,
            ],
        )
        if inspect.returncode != 0:
            return {"container_present": False}
        raw = json.loads(inspect.stdout)
        host_config = raw.get("HostConfig", {})
        state = raw.get("State", {})
        memory = int(host_config.get("Memory", 0))
        nano_cpus = int(host_config.get("NanoCpus", 0))
        return {
            "container_present": True,
            "memory_limit_bytes": memory,
            "cpu_limit_nano": nano_cpus,
            "expected_memory_limit_bytes": RESOURCE_MEMORY_LIMIT,
            "expected_cpu_limit_nano": RESOURCE_CPU_LIMIT_NANO,
            "oom_killed": bool(state.get("OOMKilled", False)),
            "restart_count": int(raw.get("RestartCount", 0)),
            "read_only": bool(host_config.get("ReadonlyRootfs", False)),
            "no_new_privileges": bool(host_config.get("SecurityOpt"))
            and "no-new-privileges:true" in host_config.get("SecurityOpt", []),
            "image_id": raw.get("Image"),
            "repo_digests": raw.get("RepoDigests", []),
        }

    async def service_stats_sample(self, phase: str) -> dict[str, object]:
        ps = await asyncio.to_thread(
            _run,
            self.command("ps", "-q", "decision"),
            env=self.environment,
        )
        container_id = ps.stdout.strip().splitlines()[0] if ps.stdout.strip() else ""
        if not container_id:
            return {"phase": phase, "container_present": False}
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
        if stats.returncode != 0 or not stats.stdout.strip():
            return {
                "phase": phase,
                "container_present": True,
                "stats_available": False,
            }
        raw = json.loads(stats.stdout.strip().splitlines()[0])
        memory_match = re.match(
            r"\s*([^/]+)\s*/\s*([^ ]+)", str(raw.get("MemUsage", ""))
        )

        def _bytes(value: str) -> int:
            match = re.fullmatch(r"([0-9.]+)\s*([KMGTP]?i?B)?", value.strip())
            if not match:
                return 0
            multiplier = {
                "B": 1,
                "KiB": 1024,
                "MiB": 1024**2,
                "GiB": 1024**3,
                "KB": 1000,
                "MB": 1000**2,
                "GB": 1000**3,
            }.get(match.group(2) or "B", 1)
            return int(float(match.group(1)) * multiplier)

        return {
            "phase": phase,
            "container_present": True,
            "stats_available": True,
            "memory_usage_bytes": _bytes(memory_match.group(1)) if memory_match else 0,
            "memory_limit_bytes": _bytes(memory_match.group(2)) if memory_match else 0,
            "cpu_percent": str(raw.get("CPUPerc", "")),
            "pids": int(raw.get("PIDs", 0) or 0),
        }


def load_c4_config() -> DecisionConfig:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        return load_decision_config(
            manager,
            global_file=ROOT / "tests/combined/fixtures/c4/decision/global.yaml",
            assets_directory=ROOT / "tests/combined/fixtures/c4/decision/assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


async def _wait_for(predicate: Any, *, timeout: float = 120.0, label: str) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {label}")


def _http_json_sync(url: str, method: str = "GET") -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return int(response.status), json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"detail": body.decode(errors="replace")}
        return int(exc.code), payload


async def http_json(
    base: str, path: str, method: str = "GET"
) -> tuple[int, dict[str, object]]:
    return await asyncio.to_thread(_http_json_sync, base + path, method)


async def _ready_probe(base: str) -> tuple[int, dict[str, object]] | None:
    try:
        value = await http_json(base, "/health/ready")
    except (OSError, urllib.error.URLError):
        return None
    if value[0] == 200 and value[1].get("status") == "ready":
        return value
    return None


async def _wait_ready(base: str) -> dict[str, object]:
    _status, payload = await _wait_for(
        lambda: _ready_probe(base), label="Decision readiness"
    )
    return payload


def _manifest(
    symbol: str, timeframes: Sequence[str]
) -> tuple[AssetManifest, tuple[AssetTimeframeManifest, ...]]:
    now = 1_893_456_000.0
    asset = AssetManifest(
        symbol=symbol,
        exchange="binance",
        provider="binance_native",
        base_timeframe="1m",
        publish_timeframes=list(timeframes),
        timeframes=list(timeframes),
        historical_backfill_days=90,
        retention_days=90,
        enabled=True,
        desired_state="LIVE",
        asset_version=1,
        timeframe_version=1,
        updated_at=now,
        source="ingestion",
    )
    return asset, tuple(
        AssetTimeframeManifest(
            symbol=symbol,
            timeframe=timeframe,
            exchange="binance",
            provider="binance_native",
            base_timeframe="1m",
            is_base_timeframe=timeframe == "1m",
            historical_backfill_days=90,
            retention_days=90,
            enabled=True,
            desired_state="LIVE",
            asset_version=1,
            timeframe_version=1,
            updated_at=now,
            source="ingestion",
        )
        for timeframe in timeframes
    )


async def seed_manifests(broker: Any) -> None:
    store = AssetManifestStore(broker)
    for symbol in ("BTC", "ETH"):
        manifest, timeframe_manifests = _manifest(symbol, ("1m", "1h", "4h"))
        await store.sync_manifest(manifest, timeframe_manifests)


async def _keys(broker: Any, pattern: str) -> tuple[str, ...]:
    values: list[str] = []
    async for key in broker.scan_iter(match=pattern):
        values.append(str(key))
    return tuple(sorted(values))


async def shadow_entries(broker: Any) -> tuple[ShadowDecisionObservation, ...]:
    observations: list[ShadowDecisionObservation] = []
    for stream in await _keys(broker, "decision:shadow:*"):
        for _entry_id, fields in await broker.xrange(stream, "-", "+"):
            observations.append(valkey_decode(dict(fields), ShadowDecisionObservation))
    return tuple(
        sorted(observations, key=lambda item: (item.lane_id, item.market_as_of))
    )


async def _shadow_count(
    broker: Any, minimum_count: int
) -> tuple[ShadowDecisionObservation, ...] | None:
    observations = await shadow_entries(broker)
    return observations if len(observations) >= minimum_count else None


def _observation_payload(observation: ShadowDecisionObservation) -> dict[str, object]:
    return {
        "lane_id": observation.lane_id,
        "asset": observation.asset,
        "decision_timeframe": observation.decision_timeframe,
        "trigger_timeframe": observation.trigger_timeframe,
        "market_as_of": observation.market_as_of.isoformat(),
        "decision_id": observation.decision_id,
        "policy_status": observation.policy_status,
        "selected_binding_id": observation.selected_binding_id,
        "direction": observation.direction_hint,
        "score": observation.score,
        "conviction": observation.conviction,
        "decision_execution_revision": observation.decision_execution_revision,
        "feature_plan_fingerprint": observation.feature_plan_fingerprint,
        "data_plan_fingerprint": observation.data_plan_fingerprint,
    }


def _reference_semantics() -> dict[str, dict[str, object]]:
    artifact = json.loads(
        (
            ROOT
            / "artifacts/combined_c1/c1_ingestion_decision_momentum_certification.json"
        ).read_text()
    )
    baseline = artifact["cross_route_isolation"]["baseline"]
    result: dict[str, dict[str, object]] = {}
    for lane_id, value in baseline.items():
        semantic = value["semantic"]
        momentum = semantic["momentum"]["actual"]
        result[lane_id] = {
            "market_as_of": semantic["market_as_of"],
            "direction": momentum["direction"],
            "score": momentum["score"],
            "conviction": momentum["conviction"],
        }
    m4_artifact = json.loads(
        (
            ROOT
            / "artifacts/decision_m4/m4_momentum_decision_integration_certification.json"
        ).read_text()
    )
    m4_signal = m4_artifact["live_path"]["signal"]
    final_market_as_of = result["BTCUSDT:momentum_1h"]["market_as_of"]
    result["ETHUSDT:momentum_4h"] = {
        "market_as_of": final_market_as_of,
        "direction": m4_signal["direction"],
        "score": 1.0,
        "conviction": m4_signal["conviction"],
    }
    return result


def _semantic_evidence(
    observations: Sequence[ShadowDecisionObservation],
) -> dict[str, object]:
    reference = _reference_semantics()
    by_lane: dict[str, list[ShadowDecisionObservation]] = {}
    for observation in observations:
        by_lane.setdefault(observation.lane_id, []).append(observation)
    lane_evidence: dict[str, object] = {}
    for lane_id in EXPECTED_LANES:
        values = sorted(by_lane.get(lane_id, ()), key=lambda item: item.market_as_of)
        expected = reference.get(lane_id, {})
        latest = values[-1] if values else None
        lane_evidence[lane_id] = {
            "count": len(values),
            "observations": [_observation_payload(item) for item in values],
            "reference": expected,
            "parity": (
                latest is not None
                and latest.market_as_of.isoformat() == expected.get("market_as_of")
                and latest.direction_hint == expected.get("direction")
                and latest.score == expected.get("score")
                and latest.conviction == expected.get("conviction")
                and len(values) == EXPECTED_SHADOW_COUNTS[lane_id]
                and all(
                    earlier.market_as_of < later.market_as_of
                    for earlier, later in pairwise(values)
                )
            ),
        }
    return lane_evidence


async def _schema_and_seed(
    pool: asyncpg.Pool, broker: Any, config: DecisionConfig
) -> dict[str, object]:
    await apply_ingestion_schema(pool)
    await apply_ingestion_schema(pool)
    await ensure_checkpoint_schema(pool)
    await ensure_checkpoint_schema(pool)
    bucket_start = await seed_startup_history(pool, config)
    await seed_manifests(broker)
    return {
        "bucket_start": bucket_start,
        "schema_idempotent": True,
        "checkpoint_schema_idempotent": True,
        "baseline_signals": await _keys(broker, "signals:*"),
        "baseline_shadow": await _keys(broker, "decision:shadow:*"),
        "baseline_outbox_pending": int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        ),
    }


async def _materialize_window(
    repository: CandleRepository,
    *,
    asset: str,
    start: datetime,
    index_offset: int,
    config: DecisionConfig,
) -> dict[str, int]:
    ingestion = CandleIngestionService(repository)
    htf = HTFAggregationService(repository=repository, ingestion_service=ingestion)
    target_durations = (
        {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
        if asset == "BTC"
        else {"4h": timedelta(hours=4)}
    )
    inserted = 0
    for index in range(LIVE_BASE_COUNT):
        observation = _provider_observation(
            asset=asset,
            opened=start + timedelta(minutes=index),
            index=index + index_offset,
        )
        status = await ingestion.commit_observation(observation)
        if status is CandleCommitStatus.CONFLICT:
            raise AssertionError("unexpected canonical conflict in C4A live window")
        if status is CandleCommitStatus.INSERTED:
            inserted += 1
        await htf.process_base_candle(
            canonicalize_observation(observation),
            base_duration=timedelta(minutes=1),
            target_durations=target_durations,
            alignment_origin=config.timeframe_grid.alignment_origin,
        )
    return {"base_inserted": inserted}


async def _publish_initial_live(
    pool: asyncpg.Pool,
    broker: Any,
    config: DecisionConfig,
    bucket_start: datetime,
) -> dict[str, object]:
    repository = CandleRepository(pool)
    counts = {
        asset: await _materialize_window(
            repository,
            asset=asset,
            start=bucket_start,
            index_offset=0,
            config=config,
        )
        for asset in ("BTC", "ETH")
    }
    outbox = await drain_outbox(pool, broker)
    return {"assets": counts, "outbox": outbox}


async def _publish_next_live(
    pool: asyncpg.Pool,
    broker: Any,
    config: DecisionConfig,
    bucket_start: datetime,
) -> dict[str, object]:
    repository = CandleRepository(pool)
    counts = {
        asset: await _materialize_window(
            repository,
            asset=asset,
            start=bucket_start + timedelta(hours=4),
            index_offset=LIVE_BASE_COUNT,
            config=config,
        )
        for asset in ("BTC", "ETH")
    }
    outbox = await drain_outbox(pool, broker)
    return {"assets": counts, "outbox": outbox}


async def _runtime_snapshot(base: str) -> dict[str, object]:
    status, payload = await http_json(base, "/runtime")
    if status != 200:
        raise AssertionError(f"runtime endpoint returned {status}: {payload}")
    return payload


async def _runtime_snapshot_with_cursor(
    base: str, stream: str, expected_stream_id: str
) -> dict[str, object] | None:
    snapshot = await _runtime_snapshot(base)
    cursor = _input_cursor(snapshot, stream)
    return snapshot if cursor.get("latest_stream_id") == expected_stream_id else None


async def _redeliver_canonical_event(broker: Any) -> dict[str, object]:
    streams = await _keys(
        broker,
        "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
    )
    if len(streams) != 1:
        raise AssertionError(f"expected one BTC 1h canonical stream, got {streams}")
    stream = streams[0]
    entries = await broker.xrange(stream, "-", "+", count=1)
    if not entries:
        raise AssertionError("canonical stream has no event to redeliver")
    original_id, fields = entries[0]
    latest_entries = await broker.xrevrange(stream, "+", "-", count=1)
    if not latest_entries:
        raise AssertionError("canonical stream has no tail for redelivery")
    latest_id = str(latest_entries[0][0])
    try:
        latest_ms, latest_sequence = (
            int(part) for part in latest_id.split("-", maxsplit=1)
        )
    except (ValueError, TypeError) as exc:
        raise AssertionError(f"invalid canonical stream tail ID: {latest_id}") from exc
    redelivery_id_value = f"{latest_ms + 1}-{latest_sequence}"
    redelivery_id = await broker.xadd(stream, fields, id=redelivery_id_value)
    if str(redelivery_id) != redelivery_id_value:
        raise AssertionError(
            "canonical redelivery did not receive the requested forward stream ID"
        )
    return {
        "stream": stream,
        "original_id": str(original_id),
        "redelivery_id": str(redelivery_id),
        "field_fingerprint": sha256_fingerprint(dict(fields)),
    }


def _input_cursor(snapshot: Mapping[str, object], stream: str) -> Mapping[str, object]:
    inputs = snapshot.get("inputs")
    if not isinstance(inputs, Mapping):
        return {}
    value = inputs.get(stream)
    return value if isinstance(value, Mapping) else {}


async def run_trial(trial_name: str) -> dict[str, object]:
    infrastructure = C4Infrastructure(trial_name)
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    trial_result: dict[str, object] = {}
    try:
        config = load_c4_config()
        await infrastructure.start_foundation()
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=4
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        seed = await _schema_and_seed(pool, broker, config)
        before = {
            "signals": seed["baseline_signals"],
            "shadow": seed["baseline_shadow"],
            "outbox_pending": seed["baseline_outbox_pending"],
        }
        await infrastructure.start_decision()
        live_status, live_health = await _wait_for(
            lambda: _ready_probe(infrastructure.http_base),
            label="container health/readiness",
        )
        live_probe_status, _ = await http_json(infrastructure.http_base, "/health/live")
        initial_runtime = await _runtime_snapshot(infrastructure.http_base)
        initial_lanes = await http_json(infrastructure.http_base, "/runtime/lanes")
        initial_inputs = await http_json(infrastructure.http_base, "/runtime/inputs")
        startup_stats = await infrastructure.service_stats_sample("startup")
        live_publish = await _publish_initial_live(
            pool, broker, config, seed["bucket_start"]
        )
        observations = await _wait_for(
            lambda: _shadow_count(broker, 6),
            timeout=150.0,
            label="six shadow observations",
        )
        first_semantics = _semantic_evidence(observations)
        stream_counts = {
            lane_id: len([item for item in observations if item.lane_id == lane_id])
            for lane_id in EXPECTED_LANES
        }
        live_runtime_snapshot = await _runtime_snapshot(infrastructure.http_base)
        live_stats = await infrastructure.service_stats_sample("live")
        live_inputs = await http_json(infrastructure.http_base, "/runtime/inputs")
        watermarks = {
            lane_id: live_runtime_snapshot.get("lanes", {})
            .get(lane_id, {})
            .get("watermark", {})
            for lane_id in EXPECTED_LANES
        }
        signal_keys_before = await _keys(broker, "signals:*")
        redelivery_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
        input_before_duplicate = _input_cursor(
            await _runtime_snapshot(infrastructure.http_base),
            redelivery_stream,
        )
        redelivery = await _redeliver_canonical_event(broker)
        if redelivery["stream"] != redelivery_stream:
            raise AssertionError("redelivery stream does not match captured cursor")
        duplicate_runtime = await _wait_for(
            lambda: _runtime_snapshot_with_cursor(
                infrastructure.http_base,
                redelivery_stream,
                str(redelivery["redelivery_id"]),
            ),
            timeout=30.0,
            label="canonical duplicate redelivery cursor",
        )
        count_after_duplicate = len(await shadow_entries(broker))
        duplicate_watermarks = {
            lane_id: duplicate_runtime.get("lanes", {})
            .get(lane_id, {})
            .get("watermark", {})
            for lane_id in EXPECTED_LANES
        }

        restart_command = await infrastructure.restart_decision()
        restarted_health = await _wait_ready(infrastructure.http_base)
        count_after_restart = len(await shadow_entries(broker))
        restart_runtime = await _runtime_snapshot(infrastructure.http_base)
        restart_inputs = await http_json(infrastructure.http_base, "/runtime/inputs")
        observations_after_restart = await shadow_entries(broker)
        restart_stats = await infrastructure.service_stats_sample("restart")
        next_live = await _publish_next_live(pool, broker, config, seed["bucket_start"])
        all_after_next = await _wait_for(
            lambda: _shadow_count(broker, count_after_restart + 6),
            timeout=150.0,
            label="post-restart shadow observations",
        )
        delta_after_restart = len(all_after_next) - count_after_restart

        shadow_count_before_controls = len(await shadow_entries(broker))
        signals_before_controls = await _keys(broker, "signals:*")
        paused_status, paused = await http_json(
            infrastructure.http_base, "/runtime/pause", method="POST"
        )
        paused_ready_status, _ = await http_json(
            infrastructure.http_base, "/health/ready"
        )
        shadow_count_after_pause = len(await shadow_entries(broker))
        signals_after_pause = await _keys(broker, "signals:*")
        resumed_status, resumed = await http_json(
            infrastructure.http_base, "/runtime/resume", method="POST"
        )
        resumed_ready = await _wait_ready(infrastructure.http_base)
        shadow_count_after_resume = len(await shadow_entries(broker))
        signals_after_resume = await _keys(broker, "signals:*")
        before_reconnect_generation = resumed.get("generation_id")
        reconnect_status, reconnected = await http_json(
            infrastructure.http_base, "/runtime/reconnect", method="POST"
        )
        final_ready = await _wait_ready(infrastructure.http_base)
        shadow_count_after_reconnect = len(await shadow_entries(broker))
        signals_after_reconnect = await _keys(broker, "signals:*")
        final_runtime = await _runtime_snapshot(infrastructure.http_base)
        final_inputs = await http_json(infrastructure.http_base, "/runtime/inputs")
        resource = await infrastructure.service_resource_evidence()
        trial_result = {
            "trial_name": trial_name,
            "infrastructure": {
                "isolated_project": True,
                "services": ["db", "broker", "decision"],
                "dynamic_ports": True,
                "decision_image": "repository-Dockerfile",
            },
            "schema_and_seed": {
                "schema_idempotent": seed["schema_idempotent"],
                "checkpoint_schema_idempotent": seed["checkpoint_schema_idempotent"],
                "startup_history_bars": STARTUP_COUNT,
                "manifest_assets": ["BTC", "ETH"],
                "required_timeframes": {
                    "BTC": ["1m", "1h", "4h"],
                    "ETH": ["1m", "1h", "4h"],
                },
                "baseline": before,
            },
            "startup": {
                "health_live_status": live_probe_status,
                "health_ready_status": live_status,
                "health_ready_payload": live_health,
                "runtime": initial_runtime,
                "lanes": initial_lanes[1],
                "inputs": initial_inputs[1],
            },
            "live": {
                "materialized": live_publish,
                "shadow_counts": stream_counts,
                "expected_shadow_counts": EXPECTED_SHADOW_COUNTS,
                "observations": [_observation_payload(item) for item in observations],
                "semantics": first_semantics,
                "watermarks": watermarks,
                "runtime": live_runtime_snapshot,
                "inputs": live_inputs[1],
                "signals_after_live": signal_keys_before,
                "total_shadow_observations": len(observations),
            },
            "duplicate": {
                "redelivery": redelivery,
                "input_cursor_before": input_before_duplicate,
                "input_cursor_after": _input_cursor(
                    duplicate_runtime, redelivery_stream
                ),
                "input_cursor_evidence": {
                    "stream": redelivery_stream,
                    "before_stream_id": input_before_duplicate.get("latest_stream_id"),
                    "after_stream_id": _input_cursor(
                        duplicate_runtime, redelivery_stream
                    ).get("latest_stream_id"),
                    "redelivery_id": redelivery["redelivery_id"],
                    "advanced": input_before_duplicate.get("latest_stream_id")
                    != _input_cursor(duplicate_runtime, redelivery_stream).get(
                        "latest_stream_id"
                    ),
                },
                "count_before": len(observations),
                "count_after": count_after_duplicate,
                "watermarks_before": watermarks,
                "watermarks_after": duplicate_watermarks,
                "watermarks_unchanged": duplicate_watermarks == watermarks,
                "signals": await _keys(broker, "signals:*"),
            },
            "restart": {
                "command": restart_command,
                "health": restarted_health,
                "generation_before": initial_runtime.get("generation_id"),
                "generation_after": restart_runtime.get("generation_id"),
                "shadow_count_before": count_after_restart,
                "observations_before": [
                    _observation_payload(item) for item in observations
                ],
                "observations_after_restart": [
                    _observation_payload(item) for item in observations_after_restart
                ],
                "inputs": restart_inputs[1],
                "next_live": next_live,
                "shadow_count_after": len(all_after_next),
                "next_delta": delta_after_restart,
                "observations_after": [
                    _observation_payload(item) for item in all_after_next
                ],
            },
            "controls": {
                "pause_status": paused_status,
                "pause_state": paused,
                "pause_ready_status": paused_ready_status,
                "resume_status": resumed_status,
                "resume_state": resumed,
                "resume_ready": resumed_ready,
                "shadow_count_before": shadow_count_before_controls,
                "shadow_count_after_pause": shadow_count_after_pause,
                "shadow_count_after_resume": shadow_count_after_resume,
                "shadow_count_after_reconnect": shadow_count_after_reconnect,
                "signals_before": signals_before_controls,
                "signals_after_pause": signals_after_pause,
                "signals_after_resume": signals_after_resume,
                "signals_after_reconnect": signals_after_reconnect,
                "reconnect_status": reconnect_status,
                "reconnect_state": reconnected,
                "reconnect_generation_changed": reconnected.get("generation_id")
                != before_reconnect_generation,
                "final_ready": final_ready,
                "final_runtime": final_runtime,
                "final_inputs": final_inputs[1],
                "signals": signals_after_reconnect,
            },
            "resource": resource,
            "resource_samples": {
                "startup": startup_stats,
                "live": live_stats,
                "restart": restart_stats,
            },
            "protected_hashes": protected_hashes(),
        }
        return trial_result
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        cleanup = await infrastructure.cleanup()
        trial_result["cleanup"] = cleanup
        if not cleanup.get("clean"):
            raise RuntimeError("C4A disposable Compose cleanup failed")


def _lane_statuses(runtime: Mapping[str, object]) -> dict[str, str]:
    lanes = runtime.get("lanes", {})
    if not isinstance(lanes, Mapping):
        return {}
    return {
        str(lane_id): str(value.get("status"))
        for lane_id, value in lanes.items()
        if isinstance(value, Mapping)
    }


_VOLATILE_TRIAL_KEYS = frozenset(
    {
        "started_at",
        "last_poll_at",
        "last_rebuild_at",
        "last_lifecycle_event_at",
        "latest_stream_id",
        "project_name",
        "resource_samples",
    }
)
_EMPTY_LIFECYCLE_EVIDENCE = {
    "cursor": "0-0",
    "event_ids": [],
    "ignored_symbols": [],
    "malformed_ids": [],
    "reason": None,
    "relevant_count": 0,
}


def _normalize_trial(value: object) -> object:
    """Remove operational run identity while retaining semantic evidence."""
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            key = str(key)
            if key in _VOLATILE_TRIAL_KEYS or key == "trial_name":
                continue
            if key == "redelivery" and isinstance(item, Mapping):
                normalized[key] = {
                    "stream": item.get("stream"),
                    "fields_present": bool(item.get("field_fingerprint")),
                }
                continue
            if key == "resource" and isinstance(item, Mapping):
                normalized[key] = {
                    str(resource_key): (
                        "present"
                        if resource_key == "image_id"
                        else _normalize_trial(resource_value)
                    )
                    for resource_key, resource_value in item.items()
                }
                continue
            if key == "command" and isinstance(item, Mapping):
                normalized[key] = {
                    "stop_returncode": item.get("stop_returncode"),
                    "start_returncode": item.get("start_returncode"),
                    "stopped_state_evidence": item.get("stopped_state_evidence"),
                    "stopped_exit_code": item.get("stopped_container", {}).get(
                        "ExitCode"
                    )
                    if isinstance(item.get("stopped_container"), Mapping)
                    else None,
                    "stopped_state": item.get("stopped_container", {}).get("State")
                    if isinstance(item.get("stopped_container"), Mapping)
                    else None,
                }
                continue
            if key == "input_cursor_evidence" and isinstance(item, Mapping):
                normalized[key] = {
                    "stream": item.get("stream"),
                    "advanced": item.get("advanced"),
                }
                continue
            normalized[key] = _normalize_trial(item)
        if "service_state" in normalized and (
            "last_lifecycle_evidence" not in normalized
            or not normalized.get("last_lifecycle_evidence")
        ):
            normalized["last_lifecycle_evidence"] = dict(_EMPTY_LIFECYCLE_EVIDENCE)
        return normalized
    if isinstance(value, list):
        return [_normalize_trial(item) for item in value]
    return value


def evaluate_c4a_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    """Derive C4A readiness solely from the supplied raw evidence."""
    startup = evidence.get("startup")
    live = evidence.get("live")
    duplicate = evidence.get("duplicate")
    restart = evidence.get("restart")
    controls = evidence.get("controls")
    resource = evidence.get("resource")
    protected = evidence.get("protected_hashes")
    expected_protected = evidence.get("expected_protected_hashes")
    schema_and_seed = evidence.get("schema_and_seed")
    startup_runtime = startup.get("runtime") if isinstance(startup, Mapping) else {}
    startup_lanes_payload = startup.get("lanes") if isinstance(startup, Mapping) else {}
    startup_lanes = (
        startup_lanes_payload.get("lanes")
        if isinstance(startup_lanes_payload, Mapping)
        else {}
    )
    startup_inputs = startup.get("inputs") if isinstance(startup, Mapping) else {}
    live_semantics = live.get("semantics") if isinstance(live, Mapping) else {}
    live_watermarks = live.get("watermarks") if isinstance(live, Mapping) else {}
    observations = live.get("observations") if isinstance(live, Mapping) else []
    expected_lanes = set(EXPECTED_LANES)
    live_inputs = live.get("inputs") if isinstance(live, Mapping) else {}
    live_observations = live.get("observations") if isinstance(live, Mapping) else []
    startup_baseline = (
        schema_and_seed.get("baseline", {})
        if isinstance(schema_and_seed, Mapping)
        else {}
    )
    trial_a = evidence.get("trial_a")
    trial_b = evidence.get("trial_b")
    projection_keys = (
        "infrastructure",
        "schema_and_seed",
        "startup",
        "live",
        "duplicate",
        "restart",
        "controls",
        "resource",
        "protected_hashes",
    )
    projection_matches = isinstance(trial_a, Mapping) and all(
        evidence.get(key) == trial_a.get(key) for key in projection_keys
    )
    resource_samples = evidence.get("resource_samples")
    raw_resource = evidence.get("raw_resource")
    raw_resource_valid = isinstance(raw_resource, Mapping) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("image_id"), str)
        and bool(item.get("image_id"))
        for item in raw_resource.values()
    )
    samples_valid = True
    if not isinstance(resource_samples, Mapping):
        samples_valid = False
    else:
        for trial_samples in resource_samples.values():
            if not isinstance(trial_samples, Mapping):
                samples_valid = False
                continue
            if set(trial_samples) != {"startup", "live", "restart"}:
                samples_valid = False
                continue
            for phase, sample in trial_samples.items():
                samples_valid = samples_valid and (
                    isinstance(sample, Mapping)
                    and sample.get("phase") == phase
                    and sample.get("container_present") is True
                    and sample.get("stats_available") is True
                    and isinstance(sample.get("memory_usage_bytes"), int)
                    and 0 <= sample["memory_usage_bytes"] < RESOURCE_MEMORY_LIMIT
                    and sample.get("memory_limit_bytes") == RESOURCE_MEMORY_LIMIT
                )
    cleanup_valid = all(
        isinstance(trial, Mapping)
        and isinstance(trial.get("cleanup"), Mapping)
        and trial["cleanup"].get("clean") is True
        for trial in (trial_a, trial_b)
    )
    source_contract = evidence.get("source_contract")
    production_scope = evidence.get("production_scope")
    raw_cursor_evidence = evidence.get("raw_input_cursor_evidence")
    cursor_evidence_valid = True
    if not isinstance(raw_cursor_evidence, Mapping):
        cursor_evidence_valid = False
    else:
        for item in raw_cursor_evidence.values():
            cursor_evidence_valid = cursor_evidence_valid and (
                isinstance(item, Mapping)
                and item.get("before_stream_id") != item.get("after_stream_id")
                and item.get("after_stream_id") == item.get("redelivery_id")
                and item.get("advanced") is True
            )
    raw_redelivery = evidence.get("raw_redelivery")
    raw_redelivery_valid = isinstance(raw_redelivery, Mapping) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("stream"), str)
        and isinstance(item.get("field_fingerprint"), str)
        and bool(item.get("field_fingerprint"))
        for item in raw_redelivery.values()
    )
    return {
        "protected_hashes": (
            protected == EXPECTED_PROTECTED_HASHES
            and expected_protected == EXPECTED_PROTECTED_HASHES
        ),
        "source_contract": (
            isinstance(source_contract, Mapping)
            and source_contract.get("source_base_sha") == C4_BASE_SHA
            and source_contract.get("pre_c4a_compose_sha") == PRE_C4A_COMPOSE_SHA
            and source_contract.get("post_c4a_compose_sha") == POST_C4A_COMPOSE_SHA
            and source_contract.get("decision_global_sha") == DECISION_GLOBAL_SHA
            and source_contract.get("dockerfile_sha") == DOCKERFILE_SHA
            and source_contract.get("r4c_manifest_sha") == R4C_MANIFEST_SHA
            and source_contract.get("production_source_hashes")
            == EXPECTED_PRODUCTION_SOURCE_HASHES
            and source_contract.get("expected_production_source_hashes")
            == EXPECTED_PRODUCTION_SOURCE_HASHES
            and evidence.get("fixture_hashes") == EXPECTED_FIXTURE_HASHES
        ),
        "production_scope": (
            isinstance(production_scope, Mapping)
            and production_scope.get("decision_assets") == []
            and production_scope.get("observer_active") is False
            and production_scope.get("root_compose_rendered") is True
        ),
        "startup_health": (
            isinstance(startup, Mapping)
            and startup.get("health_live_status") == 200
            and startup.get("health_ready_status") == 200
            and isinstance(startup.get("health_ready_payload"), Mapping)
            and startup["health_ready_payload"].get("status") == "ready"
        ),
        "startup_scope": (
            isinstance(startup_runtime, Mapping)
            and startup_runtime.get("service_state") == "RUNNING"
            and startup_runtime.get("desired_state") == "RUNNING"
            and startup_runtime.get("configured_asset_count") == 2
            and startup_runtime.get("configured_lane_count") == 3
            and startup_runtime.get("active_lane_count") == 3
            and isinstance(startup_lanes, Mapping)
            and set(startup_lanes) == set(EXPECTED_LANES)
            and all(
                _lane_statuses(startup_runtime).get(lane) == "LIVE"
                for lane in EXPECTED_LANES
            )
            and isinstance(startup_inputs, Mapping)
            and startup_inputs.get("blocked_stream_count") == 0
            and isinstance(live_inputs, Mapping)
            and set(live_inputs.get("inputs", {}))
            == set(startup_inputs.get("inputs", {}))
        ),
        "startup_empty_outputs": (
            isinstance(startup_baseline, Mapping)
            and not startup_baseline.get("signals")
            and not startup_baseline.get("shadow")
            and startup_baseline.get("outbox_pending") == 0
        ),
        "shadow_counts_exact": (
            isinstance(live, Mapping)
            and live.get("shadow_counts") == EXPECTED_SHADOW_COUNTS
            and len(observations) == 6
        ),
        "shadow_semantic_parity": (
            isinstance(live_semantics, Mapping)
            and set(live_semantics) == set(EXPECTED_LANES)
            and all(
                isinstance(value, Mapping) and value.get("parity") is True
                for value in live_semantics.values()
            )
        ),
        "shadow_commit_disposition": (
            isinstance(live_watermarks, Mapping)
            and set(live_watermarks) == expected_lanes
            and all(
                isinstance(value, Mapping) and value.get("last_disposition") == "shadow"
                for value in live_watermarks.values()
            )
        ),
        "no_authoritative_signals": (
            isinstance(live, Mapping)
            and not live.get("signals_after_live")
            and isinstance(duplicate, Mapping)
            and not duplicate.get("signals")
            and isinstance(controls, Mapping)
            and not controls.get("signals")
        ),
        "duplicate_idempotency": (
            isinstance(duplicate, Mapping)
            and isinstance(duplicate.get("redelivery"), Mapping)
            and duplicate["redelivery"].get("fields_present") is True
            and raw_redelivery_valid
            and isinstance(duplicate.get("input_cursor_evidence"), Mapping)
            and duplicate["input_cursor_evidence"].get("advanced") is True
            and cursor_evidence_valid
            and duplicate.get("count_before") == duplicate.get("count_after")
            and duplicate.get("watermarks_before") == duplicate.get("watermarks_after")
            and duplicate.get("watermarks_unchanged") is True
        ),
        "restart_exactly_once": (
            isinstance(restart, Mapping)
            and isinstance(restart.get("health"), Mapping)
            and restart["health"].get("status") == "ready"
            and restart.get("command", {}).get("stop_returncode") == 0
            and restart.get("command", {}).get("start_returncode") == 0
            and restart.get("command", {}).get("stopped_state_evidence") is True
            and restart.get("shadow_count_before") == 6
            and restart.get("observations_before") == live_observations
            and restart.get("observations_after_restart")
            == restart.get("observations_before")
            and restart.get("shadow_count_after")
            == restart.get("shadow_count_before") + 6
            and restart.get("next_delta") == 6
        ),
        "controls": (
            isinstance(controls, Mapping)
            and controls.get("pause_status") == 200
            and controls.get("pause_ready_status") == 503
            and controls.get("pause_state", {}).get("service_state") == "PAUSED"
            and controls.get("pause_state", {}).get("desired_state") == "PAUSED"
            and controls.get("resume_status") == 200
            and controls.get("resume_ready", {}).get("status") == "ready"
            and controls.get("resume_state", {}).get("service_state") == "RUNNING"
            and controls.get("reconnect_status") == 200
            and controls.get("reconnect_generation_changed") is True
            and controls.get("final_ready", {}).get("status") == "ready"
            and controls.get("shadow_count_before")
            == controls.get("shadow_count_after_pause")
            == controls.get("shadow_count_after_resume")
            == controls.get("shadow_count_after_reconnect")
            and controls.get("signals_before")
            == controls.get("signals_after_pause")
            == controls.get("signals_after_resume")
            == controls.get("signals_after_reconnect")
        ),
        "two_trial_determinism": (
            isinstance(trial_a, Mapping)
            and isinstance(trial_b, Mapping)
            and trial_a == trial_b
            and evidence.get("trials_equal") is True
            and projection_matches
        ),
        "cleanup": cleanup_valid,
        "resource_samples": samples_valid,
        "resource_structure": (
            isinstance(resource, Mapping)
            and resource.get("container_present") is True
            and resource.get("memory_limit_bytes") == RESOURCE_MEMORY_LIMIT
            and resource.get("cpu_limit_nano") == RESOURCE_CPU_LIMIT_NANO
            and resource.get("read_only") is True
            and resource.get("no_new_privileges") is True
            and resource.get("oom_killed") is False
            and resource.get("restart_count") == 0
            and isinstance(resource.get("image_id"), str)
            and bool(resource.get("image_id"))
            and raw_resource_valid
        ),
    }


def identity_payload(evidence: Mapping[str, object]) -> dict[str, object]:
    source_contract = evidence.get("source_contract")
    return {
        "schema_version": evidence.get("schema_version"),
        "source_base_sha": source_contract.get("source_base_sha")
        if isinstance(source_contract, Mapping)
        else None,
        "source_sha": evidence.get("source_sha"),
        "protected_hashes": evidence.get("protected_hashes"),
        "routes": EXPECTED_LANES,
        "shadow_stream_prefix": "decision:shadow:",
        "shadow_schema_version": "decision.shadow.v1",
        "shadow_stream_maxlen": 1000,
        "shadow_stream_approximate": True,
        "resource_limit": {
            "memory": RESOURCE_MEMORY_LIMIT,
            "cpu": RESOURCE_CPU_LIMIT_NANO,
        },
        "fixture_hashes": evidence.get("fixture_hashes"),
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
            "trial_name",
            "resource_samples",
            "raw_input_cursor_evidence",
            "raw_redelivery",
            "raw_resource",
        }
    }


async def run_c4a_certification() -> dict[str, object]:
    actual_protected = protected_hashes()
    if actual_protected != EXPECTED_PROTECTED_HASHES:
        raise RuntimeError("C4A protected artifacts do not match approved hashes")
    first = await run_trial("trial_a")
    second = await run_trial("trial_b")
    normalized_first = _normalize_trial(json.loads(canonical_json(first)))
    normalized_second = _normalize_trial(json.loads(canonical_json(second)))
    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_base_sha": C4_BASE_SHA,
        "source_sha": C4_BASE_SHA,
        "protected_hashes": actual_protected,
        "expected_protected_hashes": dict(EXPECTED_PROTECTED_HASHES),
        "source_contract": {
            "source_base_sha": C4_BASE_SHA,
            "pre_c4a_compose_sha": PRE_C4A_COMPOSE_SHA,
            "post_c4a_compose_sha": POST_C4A_COMPOSE_SHA,
            "decision_global_sha": DECISION_GLOBAL_SHA,
            "dockerfile_sha": DOCKERFILE_SHA,
            "r4c_manifest_sha": R4C_MANIFEST_SHA,
            "production_source_hashes": _production_source_hashes(),
            "expected_production_source_hashes": dict(
                EXPECTED_PRODUCTION_SOURCE_HASHES
            ),
        },
        "fixture_hashes": _fixture_hashes(),
        "shadow_contract": {
            "schema_version": "decision.shadow.v1",
            "stream_prefix": "decision:shadow:",
            "entry_id": "int(market_as_of.timestamp() * 1000)-0",
            "maxlen": 1000,
            "approximate": True,
        },
        "production_scope": _production_scope_evidence(),
        "trial_a": normalized_first,
        "trial_b": normalized_second,
        "resource_samples": {
            "trial_a": first.get("resource_samples"),
            "trial_b": second.get("resource_samples"),
        },
        "raw_input_cursor_evidence": {
            "trial_a": first.get("duplicate", {}).get("input_cursor_evidence"),
            "trial_b": second.get("duplicate", {}).get("input_cursor_evidence"),
        },
        "raw_redelivery": {
            "trial_a": first.get("duplicate", {}).get("redelivery"),
            "trial_b": second.get("duplicate", {}).get("redelivery"),
        },
        "raw_resource": {
            "trial_a": first.get("resource"),
            "trial_b": second.get("resource"),
        },
        "trials_equal": normalized_first == normalized_second,
    }
    evidence.update(normalized_first)
    evidence["gates"] = evaluate_c4a_gates(evidence)
    evidence["identity_digest"] = sha256_fingerprint(identity_payload(evidence))
    evidence["evidence_digest"] = sha256_fingerprint(evidence_payload(evidence))
    evidence["terminal_status"] = (
        C4_SUCCESS_STATUS if all(evidence["gates"].values()) else C4_EVIDENCE_STATUS
    )
    return evidence


def stable_artifact(evidence: Mapping[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(evidence))


__all__ = [
    "ARTIFACT_FILE",
    "C4_SUCCESS_STATUS",
    "EXPECTED_PROTECTED_HASHES",
    "evaluate_c4a_gates",
    "protected_hashes",
    "run_c4a_certification",
    "stable_artifact",
]
