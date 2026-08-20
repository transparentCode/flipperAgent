"""Disposable D12B Decision-only legacy-retirement certification harness."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
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
import yaml

from apps.decision_app.composition import build_production_composition
from apps.decision_app.data.resolver import compile_data_plan
from apps.decision_app.domain.identity import lane_execution_identity
from apps.decision_app.features.planning import compile_feature_plan
from apps.decision_app.planning.planner import compile_decision_plan
from apps.decision_app.settings import DecisionConfig, load_decision_config
from apps.decision_app.storage.bootstrap import ensure_checkpoint_schema
from apps.decision_app.storage.shadow_progress import (
    LaneEffectProgress,
    LaneEffectProgressRepository,
)
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.signal_routes import (
    assets_from_routes,
    decision_authoritative_routes_from_config,
    parse_signal_routes,
)
from tests.combined.c2_harness import _route_keys, _seed_bar
from tests.combined.c4a_harness import _manifest, _materialize_window

ROOT = Path(__file__).resolve().parents[2]
D12_COMPOSE_FILE = ROOT / "tests/combined/fixtures/d12/docker-compose.yml"
D12_FIXTURE_ROOT = D12_COMPOSE_FILE.parent
D12_ARTIFACT_ROOT = ROOT / "artifacts/decision_d12"
D12B_ARTIFACT_FILE = (
    D12_ARTIFACT_ROOT / "d12b_complete_legacy_retirement_certification.json"
)
HISTORICAL_D12A_ARTIFACT_FILE = (
    D12_ARTIFACT_ROOT / "d12_decision_only_topology_certification.json"
)
CURRENT_BASE_D12A_ARTIFACT_FILE = (
    D12_ARTIFACT_ROOT / "d12_current_base_reconciliation_certification.json"
)
D12B_SUCCESS_STATUS = "DECISION_D12B_COMPLETE_LEGACY_RETIREMENT_READY_FOR_REVIEW"
D12B_BLOCKED_STATUS = "DECISION_D12B_COMPLETE_LEGACY_RETIREMENT_BLOCKED"
STARTUP_COUNT = 544
EXPECTED_SERVICES = (
    "db",
    "broker",
    "ingestion",
    "decision",
    "risk-worker",
    "execution-worker",
)
EXPECTED_ROUTES = ("BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h")
EXPECTED_ASSETS = ("BTCUSDT", "ETHUSDT")
OBSOLETE_STRATEGY_ROUTES = (
    "BNBUSDT:30m",
    "DOGEUSDT:1h",
    "DOGEUSDT:4h",
    "SOLUSDT:1h",
    "XRPUSDT:1h",
)
D12B_BASE_SHA = "ad6873a258a898a55bd148ebecba51857648414a"
HISTORICAL_D12A_BASE_SHA = "78a88f9e7db0561d49f261404fb0372de073a65d"
HISTORICAL_D12A_SUCCESS_STATUS = (
    "DECISION_D12_DECISION_ONLY_TOPOLOGY_CERTIFICATION_READY_FOR_REVIEW"
)
HISTORICAL_D12A_SHA256 = (
    "10aef43d41fab96acbb9f21f835a21c3c6e1268eafd7c0ee8e3b7f489a4802fc"
)
HISTORICAL_D12A_IDENTITY_DIGEST = (
    "130f1aff120b8a4dbca5d38a3e8f02e566224a5af9acc3ad4aca7e98a7954101"
)
HISTORICAL_D12A_EVIDENCE_DIGEST = (
    "87e748bd396a570a4612666ecf4d367861f96d1331480b3008caa7c3ab7d3792"
)
HISTORICAL_D12A_SOURCE_LOCK_COUNT = 15
HISTORICAL_D12A_GATE_COUNT = 34
CURRENT_BASE_D12A_SHA256 = (
    "aa1fea5a1bf10a7269fae9dbf69b0e25311dbea106d42314913108586db5a8dc"
)
D11C_SHA256 = "2f4d59eb0059a66bd1d16a619e01ec3541130360fea58404877f8147c1fc7886"
D12B_SOURCE_PATHS = (
    "configs/alerts.yaml",
    "configs/base.yaml",
    "configs/execution.yaml",
    "configs/models.yaml",
    "configs/risk.yaml",
    "docker-compose.yml",
    "docs/docker_topology.md",
    "docs/ingestion_operations.md",
    "scripts/certify_decision_d12_decision_only_topology.py",
    "scripts/certify_decision_runtime_d10.py",
    "scripts/certify_momentum_features_m3.py",
    "src/apps/api_app/app.py",
    "src/apps/decision_app/bootstrap.py",
    "src/apps/decision_app/runtime/startup.py",
    "src/apps/decision_app/transport/signals.py",
    "src/apps/execution_app/bootstrap.py",
    "src/apps/risk_app/api/app.py",
    "src/apps/risk_app/main.py",
    "src/apps/risk_app/observability/service.py",
    "src/libs/common/config_validator.py",
    "src/libs/common/signal_routes.py",
    "src/libs/features/raw_indicator_pipeline.py",
    "src/libs/optim_utils/scoring_feature_pipeline.py",
    "src/libs/regime/optimization/downstream_backtest.py",
    "tests/combined/d12_harness.py",
    "tests/combined/fixtures/d12/configs/execution.yaml",
    "tests/combined/fixtures/d12/configs/ingestion-decision/assets/BTC.yaml",
    "tests/combined/fixtures/d12/configs/ingestion-decision/assets/ETH.yaml",
    "tests/combined/fixtures/d12/configs/ingestion-decision/global.yaml",
    "tests/combined/fixtures/d12/configs/ingestion-runtime/assets/.keep",
    "tests/combined/fixtures/d12/configs/ingestion-runtime/global.yaml",
    "tests/combined/fixtures/d12/configs/models.yaml",
    "tests/combined/fixtures/d12/configs/risk.yaml",
    "tests/combined/fixtures/d12/decision/assets/BTC.yaml",
    "tests/combined/fixtures/d12/decision/assets/ETH.yaml",
    "tests/combined/fixtures/d12/decision/global.yaml",
    "tests/combined/fixtures/d12/docker-compose.yml",
    "tests/combined/integration/test_decision_d12_decision_only_topology.py",
    "tests/decision/certification/test_d10_resource_capacity.py",
    "tests/decision/test_architecture_guardrails.py",
    "tests/decision/test_d12_decision_only_topology.py",
    "tests/decision/test_d9c_api_bootstrap.py",
    "tests/execution/test_execution_bootstrap_routes.py",
    "tests/models/momentum/test_core.py",
    "tests/risk/test_runtime_signal_routes.py",
    "tests/test_raw_indicator_pipeline.py",
    "tests/test_signal_routes.py",
)
D12_RUNTIME_IMPORT_PATHS = (
    "src/apps/ingestion_app",
    "src/apps/decision_app",
    "src/apps/risk_app",
    "src/apps/execution_app",
    "src/apps/api_app",
)
D12_RETAINED_NEUTRAL_PATHS = (
    "src/libs/optim_utils/scoring_feature_pipeline.py",
    "src/libs/regime/optimization/downstream_backtest.py",
)
D12_DELETED_PATHS = (
    "src/apps/signal_app",
    "src/apps/strategy_app",
    "src/apps/api_app/routers/signal.py",
    "src/apps/api_app/routers/strategy.py",
    "src/libs/common/signal_authority.py",
    "scripts/certify_decision_d11a_authority_handoff.py",
    "scripts/certify_decision_d11b_authority_cutover.py",
    "scripts/certify_decision_d11c_default_topology.py",
    "scripts/decision_d11b_authority_cutover.py",
    "tests/combined/integration/test_decision_d11a_authority_handoff.py",
    "tests/combined/integration/test_ingestion_decision_c4b_shadow_soak.py",
    "scripts/certify_ingestion_decision_c4b_shadow_soak.py",
)
FORBIDDEN_PACKAGE_TOKENS = ("apps." + "signal" + "_app", "apps." + "strategy" + "_app")
FORBIDDEN_SERVICE_TOKENS = ("signal" + "-worker", "strategy" + "-worker")
FORBIDDEN_AUTHORITY_TOKEN = "signal:" + "authority:"
D12_RETIRED_COMBINED_MODULES = (
    "tests.combined." + "d11a_harness",
    "tests.combined." + "d11b_harness",
    "tests.combined." + "d11c_harness",
    "tests.combined." + "c4b_harness",
)
_DIGEST_GATE_NAMES = frozenset(
    {"identity_digest_integrity", "evidence_digest_integrity"}
)

PROTECTED_ARTIFACTS = {
    "d11c": (
        "artifacts/decision_d11c/d11c_default_topology_promotion_certification.json",
        D11C_SHA256,
    ),
    "historical_d12a": (
        "artifacts/decision_d12/d12_decision_only_topology_certification.json",
        HISTORICAL_D12A_SHA256,
    ),
    "current_base_d12a": (
        "artifacts/decision_d12/d12_current_base_reconciliation_certification.json",
        CURRENT_BASE_D12A_SHA256,
    ),
    "d11b": (
        "artifacts/decision_d11b/d11b_authority_cutover_certification.json",
        "9bf16504f114eae000fc4006712731e93f15815c0827cf18af8864aa4f74b05d",
    ),
    "d11a": (
        "artifacts/decision_d11a/d11a_authority_handoff_foundation_certification.json",
        "31114ecaae17f52e1d9bdd042e5c2b4ce174c1cabb114eb89894c8f7f4f415e1",
    ),
    "c4b": (
        "artifacts/combined_c4b/c4b_decision_shadow_soak_resource_certification.json",
        "2d047346ced14a72843cc22ea9a2f5eebd9929c4d02edab6f8cadb6d19582af7",
    ),
    "c4a": (
        "artifacts/combined_c4a/c4a_decision_shadow_container_foundation_certification.json",
        "c2adb97f2504ce541a0b4aa41f186a4a86c0c209dd96229e6bc4b7d121399334",
    ),
    "m3": (
        "artifacts/decision_m3/m3_momentum_feature_semantics_certification.json",
        "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c",
    ),
    "m4_functional": (
        "artifacts/decision_m4/m4_momentum_decision_integration_certification.json",
        "3d1339be919e8d176dcd1053cb1c42f46bf6a2dc5f62647114b805faea1e4792",
    ),
    "m4_resource": (
        "artifacts/decision_m4/m4_momentum_resource_certification.json",
        "e11ae8aee717764a3cca9dbfaa0f58d6b4308387ac6b5b264fb4bdf8e5f570c4",
    ),
    "d10": (
        "artifacts/decision_d10/d10_resource_capacity_certification.json",
        "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459",
    ),
    "c1": (
        "artifacts/combined_c1/c1_ingestion_decision_momentum_certification.json",
        "386b9eb33ed38128decade737bb7977cb2861a21b39e3d8cc061838635248ad4",
    ),
    "c2": (
        "artifacts/combined_c2/c2_ingestion_decision_real_infrastructure_certification.json",
        "9745c9631a198d44e081a5916e89d8182c40c09db6fd72ed8d8f237399792f67",
    ),
    "c3a": (
        "artifacts/combined_c3a/c3a_ingestion_decision_infrastructure_resilience_certification.json",
        "34c0b0eaa85fffacbd5c99d346bdcf2829dd12c8c6769e18c63711d0a342622b",
    ),
    "c3b1": (
        "artifacts/combined_c3b1/c3b1_ingestion_decision_canonical_integrity_certification.json",
        "bfb335bf5ab27b790c91be13ad878531b7a85a957901c86f7a6ec462f566fb63",
    ),
    "c3b2p": (
        "artifacts/combined_c3b2/c3b2_ingestion_decision_provider_recovery_disagreement_certification.json",
        "0981b3bd1962089932da5dc7669c936537ddaaf1d5c17adae71d2f7e798347f0",
    ),
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


def _canonical_equal(left: object, right: object) -> bool:
    return canonical_json(left) == canonical_json(right)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(
    command: Sequence[str], *, env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        env=dict(env),
        text=True,
        capture_output=True,
        check=False,
    )


def _cleanup_probe(project_name: str) -> dict[str, str]:
    label = f"label=com.docker.compose.project={project_name}"
    return {
        "containers": subprocess.run(
            ["docker", "ps", "-aq", "--filter", label],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip(),
        "volumes": subprocess.run(
            ["docker", "volume", "ls", "-q", "--filter", label],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip(),
        "networks": subprocess.run(
            ["docker", "network", "ls", "-q", "--filter", label],
            text=True,
            capture_output=True,
            check=False,
        ).stdout.strip(),
    }


@dataclass(slots=True)
class D12Infrastructure:
    trial_name: str
    db_port: int = field(default_factory=_free_port)
    broker_port: int = field(default_factory=_free_port)
    ingestion_port: int = field(default_factory=_free_port)
    decision_port: int = field(default_factory=_free_port)
    project_name: str = field(init=False)

    def __post_init__(self) -> None:
        ports = {
            self.db_port,
            self.broker_port,
            self.ingestion_port,
            self.decision_port,
        }
        while len(ports) != 4:
            self.decision_port = _free_port()
            ports = {
                self.db_port,
                self.broker_port,
                self.ingestion_port,
                self.decision_port,
            }
        token = "".join(char if char.isalnum() else "_" for char in self.trial_name)
        self.project_name = f"flipper_d12_{os.getpid()}_{token}"

    @property
    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "D12_DB_PORT": str(self.db_port),
                "D12_BROKER_PORT": str(self.broker_port),
                "D12_INGESTION_PORT": str(self.ingestion_port),
                "D12_DECISION_PORT": str(self.decision_port),
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
            str(D12_COMPOSE_FILE),
            "-p",
            self.project_name,
            *arguments,
        ]

    def compose(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return _run(self.command(*arguments), env=self.environment)

    def validate_config(self) -> None:
        result = self.compose("config", "--quiet")
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

    async def up(self, *services: str, build: bool = False, wait: bool = True) -> None:
        arguments = ["up", "-d"]
        if build:
            arguments.append("--build")
        if wait:
            arguments.append("--wait")
        arguments.extend(services)
        result = await asyncio.to_thread(self.compose, *arguments)
        if result.returncode != 0:
            logs = await asyncio.to_thread(
                self.compose, "logs", "--no-color", *services
            )
            raise RuntimeError((result.stderr or result.stdout) + "\n" + logs.stdout)

    async def stop(self, *services: str) -> None:
        result = await asyncio.to_thread(self.compose, "stop", *services)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

    async def restart(self, *services: str) -> None:
        result = await asyncio.to_thread(self.compose, "restart", *services)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

    async def container_id(self, service: str) -> str:
        result = await asyncio.to_thread(self.compose, "ps", "-q", service)
        return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""

    async def running(self, service: str) -> bool:
        container_id = await self.container_id(service)
        if not container_id:
            return False
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "inspect", "--format", "{{.State.Status}}", container_id],
            text=True,
            capture_output=True,
            check=False,
        )
        return result.stdout.strip() == "running"

    async def resource_sample(self, phase: str) -> dict[str, object]:
        samples: dict[str, object] = {}
        for service in EXPECTED_SERVICES:
            container_id = await self.container_id(service)
            if not container_id:
                samples[service] = {"present": False, "phase": phase}
                continue
            inspect = await asyncio.to_thread(
                subprocess.run,
                ["docker", "inspect", "--format", "{{json .}}", container_id],
                text=True,
                capture_output=True,
                check=False,
            )
            stats = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    container_id,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            raw = json.loads(inspect.stdout) if inspect.returncode == 0 else {}
            host = raw.get("HostConfig", {})
            state = raw.get("State", {})
            stat = (
                json.loads(stats.stdout.strip().splitlines()[0])
                if stats.stdout.strip()
                else {}
            )
            mem_usage, mem_limit = _parse_memory(str(stat.get("MemUsage", "")))
            samples[service] = {
                "present": True,
                "phase": phase,
                "container_id": container_id,
                "memory_usage_bytes": mem_usage,
                "memory_limit_bytes": mem_limit,
                "configured_memory_bytes": int(host.get("Memory", 0)),
                "configured_cpu_nano": int(host.get("NanoCpus", 0)),
                "cpu_percent": _parse_percent(str(stat.get("CPUPerc", "0%"))),
                "pids": int(stat.get("PIDs", 0) or 0),
                "oom_killed": bool(state.get("OOMKilled", False)),
                "restart_count": int(raw.get("RestartCount", 0)),
                "image": raw.get("Image"),
            }
        return samples

    async def cleanup(self) -> dict[str, object]:
        result = await asyncio.to_thread(self.compose, "down", "-v", "--remove-orphans")
        leftovers = await asyncio.to_thread(_cleanup_probe, self.project_name)
        return {
            "down_returncode": result.returncode,
            "leftovers": leftovers,
            "clean": result.returncode == 0 and not any(leftovers.values()),
        }

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql://d12_user:d12_password@127.0.0.1:{self.db_port}/d12_db"

    @property
    def valkey_uri(self) -> str:
        return f"redis://127.0.0.1:{self.broker_port}/0"

    @property
    def decision_url(self) -> str:
        return f"http://127.0.0.1:{self.decision_port}"


def _parse_percent(value: str) -> float:
    match = re.search(r"([0-9.]+)", value)
    return float(match.group(1)) if match else 0.0


def _parse_memory(value: str) -> tuple[int, int]:
    match = re.fullmatch(
        r"\s*([0-9.]+)\s*([KMGTP]?i?B)?\s*/\s*([0-9.]+)\s*([KMGTP]?i?B)?\s*", value
    )
    if not match:
        return 0, 0

    def convert(number: str, unit: str | None) -> int:
        factor = {
            "B": 1,
            "KiB": 1024,
            "MiB": 1024**2,
            "GiB": 1024**3,
            "KB": 1000,
            "MB": 1000**2,
            "GB": 1000**3,
        }.get(unit or "B", 1)
        return int(float(number) * factor)

    return convert(match.group(1), match.group(2)), convert(
        match.group(3), match.group(4)
    )


def load_d12_config() -> DecisionConfig:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        return load_decision_config(
            manager,
            global_file=D12_FIXTURE_ROOT / "decision/global.yaml",
            assets_directory=D12_FIXTURE_ROOT / "decision/assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


async def _wait_for(predicate: Any, *, label: str, timeout: float = 150.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if inspect.isawaitable(value):
            value = await value
        if value:
            return value
        await asyncio.sleep(0.25)
    raise TimeoutError(f"timed out waiting for {label}")


async def _http_json(url: str, path: str) -> tuple[int, dict[str, object]]:
    import urllib.error
    import urllib.request

    def read() -> tuple[int, dict[str, object]]:
        try:
            with urllib.request.urlopen(url + path, timeout=10) as response:
                return int(response.status), json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"detail": body.decode(errors="replace")}
            return int(exc.code), payload
        except OSError:
            return 0, {}

    return await asyncio.to_thread(read)


async def _decision_ready(infrastructure: D12Infrastructure) -> bool:
    status, payload = await _http_json(infrastructure.decision_url, "/health/ready")
    return status == 200 and payload.get("status") == "ready"


async def _ingestion_ready(infrastructure: D12Infrastructure) -> bool:
    status, payload = await _http_json(
        f"http://127.0.0.1:{infrastructure.ingestion_port}", "/health/ready"
    )
    return status == 200 and payload.get("status") == "ready"


async def _seed_risk_schema(pool: asyncpg.Pool) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS risk_account_snapshots (
            timestamp BIGINT NOT NULL, balance DOUBLE PRECISION NOT NULL,
            equity DOUBLE PRECISION NOT NULL, unrealized_pnl DOUBLE PRECISION NOT NULL,
            realized_pnl DOUBLE PRECISION NOT NULL, drawdown_pct DOUBLE PRECISION NOT NULL,
            peak_equity DOUBLE PRECISION NOT NULL, open_position_count INTEGER NOT NULL,
            daily_pnl DOUBLE PRECISION NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS risk_positions (
            asset TEXT NOT NULL, direction TEXT NOT NULL,
            entry_price DOUBLE PRECISION NOT NULL, current_price DOUBLE PRECISION NOT NULL,
            size DOUBLE PRECISION NOT NULL, unrealized_pnl DOUBLE PRECISION NOT NULL,
            entry_timestamp DOUBLE PRECISION NOT NULL, source_model TEXT,
            source_timeframe TEXT, stop_loss_price DOUBLE PRECISION,
            take_profit_price DOUBLE PRECISION, trailing_stop_distance DOUBLE PRECISION,
            original_size DOUBLE PRECISION, tp_levels JSONB, tp_portions JSONB,
            tp_levels_hit JSONB, original_stop_loss DOUBLE PRECISION,
            trail_to_breakeven BOOLEAN
        )
        """,
    )
    async with pool.acquire() as connection:
        for statement in statements:
            await connection.execute(statement)


async def _seed_execution_schema(pool: asyncpg.Pool) -> None:
    """Create the two persistence tables used by the real paper worker."""

    statements = (
        """
        CREATE TABLE IF NOT EXISTS execution_fills (
            order_id TEXT PRIMARY KEY,
            data JSONB NOT NULL,
            ts DOUBLE PRECISION NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS execution_idempotency_keys (
            key TEXT PRIMARY KEY,
            ts DOUBLE PRECISION NOT NULL
        )
        """,
    )
    async with pool.acquire() as connection:
        for statement in statements:
            await connection.execute(statement)


async def _seed_history(pool: asyncpg.Pool, config: DecisionConfig) -> datetime:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    current_boundary = now.replace(hour=now.hour - (now.hour % 4))
    bucket_start = current_boundary - timedelta(hours=4)
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


async def _seed_manifests(broker: Any) -> None:
    store = AssetManifestStore(broker)
    for symbol in ("BTC", "ETH"):
        manifest, timeframe_manifests = _manifest(symbol, ("1m", "1h", "4h"))
        await store.sync_manifest(manifest, timeframe_manifests)


async def _seed_effect_progress(
    pool: asyncpg.Pool,
    config: DecisionConfig,
    market_as_of: datetime,
) -> list[dict[str, object]]:
    """Explicitly seed effect progress rows for focused D12B failure tests only."""

    composition = build_production_composition(config)
    decision_plan = compile_decision_plan(
        composition.plugin_catalog,
        config.lane_specs(),
    )
    repository = LaneEffectProgressRepository(pool)
    rows: list[dict[str, object]] = []
    for lane in decision_plan.lanes:
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
        identity = lane_execution_identity(lane, feature_plan, data_plan)
        progress = LaneEffectProgress.create(
            identity=identity,
            market_as_of=market_as_of,
            last_disposition=None,
        )
        result = await repository.save(progress)
        result_value = getattr(result, "value", result)
        if result_value not in {"INSERTED", "UPDATED", "IDENTICAL"}:
            raise RuntimeError(f"failed to seed D12 effect progress: {result}")
        rows.append(
            {
                "lane_id": identity.lane_id,
                "effective_lane_revision": identity.effective_lane_revision,
                "feature_plan_fingerprint": identity.feature_plan_fingerprint,
                "data_plan_fingerprint": identity.data_plan_fingerprint,
                "market_as_of": market_as_of,
                "last_disposition": None,
                "save_result": result_value,
            }
        )
    return rows


async def _keys(broker: Any, pattern: str) -> tuple[str, ...]:
    result: list[str] = []
    async for key in broker.scan_iter(match=pattern):
        result.append(str(key))
    return tuple(sorted(result))


async def _stream_count(broker: Any, stream: str) -> int:
    return int(await broker.xlen(stream))


async def _signal_inventory(broker: Any) -> dict[str, object]:
    inventory: dict[str, object] = {}
    for stream in await _keys(broker, "signals:*"):
        entries = await broker.xrange(stream, "-", "+")
        inventory[stream] = {
            "count": len(entries),
            "ids": [str(entry_id) for entry_id, _fields in entries],
            "payloads": [dict(fields) for _entry_id, fields in entries],
        }
    return inventory


async def _groups(broker: Any, streams: Sequence[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for stream in streams:
        try:
            groups = await broker.xinfo_groups(stream)
        except Exception:  # noqa: BLE001
            groups = []
        result[stream] = [
            {
                "name": str(item.get("name")),
                "pending": int(item.get("pending", 0)),
                "lag": int(item.get("lag", 0) or 0),
                "last_delivered_id": str(item.get("last-delivered-id", "")),
            }
            for item in groups
        ]
    return result


async def _progress_rows(pool: asyncpg.Pool) -> list[dict[str, object]]:
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
            "lane_id": str(row["lane_id"]),
            "effective_lane_revision": str(row["effective_lane_revision"]),
            "feature_plan_fingerprint": str(row["feature_plan_fingerprint"]),
            "data_plan_fingerprint": str(row["data_plan_fingerprint"]),
            "market_as_of": row["market_as_of"].isoformat(),
            "last_disposition": row["last_disposition"],
        }
        for row in rows
    ]


async def _authority_keys(broker: Any) -> tuple[str, ...]:
    return await _keys(broker, FORBIDDEN_AUTHORITY_TOKEN + "*")


async def _execution_status(broker: Any) -> dict[str, object]:
    result: dict[str, object] = {}
    for asset in EXPECTED_ASSETS:
        key = f"execution:status:{asset}"
        result[asset] = dict(await broker.hgetall(key))
    return result


async def _wait_groups(broker: Any) -> bool:
    signal_streams = [
        f"signals:{route.split(':', 1)[0]}:{route.split(':', 1)[1]}"
        for route in EXPECTED_ROUTES
    ]
    order_streams = [f"orders:{asset}" for asset in EXPECTED_ASSETS]
    groups = await _groups(broker, [*signal_streams, *order_streams])
    return all(groups.get(stream) for stream in [*signal_streams, *order_streams])


async def _wait_outbox_empty(pool: asyncpg.Pool) -> bool:
    return (
        int(
            await pool.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )
        == 0
    )


async def _signals_nonempty(broker: Any) -> dict[str, object] | None:
    inventory = await _signal_inventory(broker)
    return (
        inventory
        if sum(int(value["count"]) for value in inventory.values()) > 0
        else None
    )


async def run_trial(trial_name: str) -> dict[str, object]:
    infrastructure = D12Infrastructure(trial_name)
    pool: asyncpg.Pool | None = None
    broker: Any | None = None
    evidence: dict[str, object] = {}
    try:
        config = load_d12_config()
        infrastructure.validate_config()
        await infrastructure.up("db", "broker", build=True)
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=6
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        await broker.ping()
        await apply_ingestion_schema(pool)
        await ensure_checkpoint_schema(pool)
        await _seed_risk_schema(pool)
        await _seed_execution_schema(pool)
        bucket_start = await _seed_history(pool, config)
        await _seed_manifests(broker)
        startup_progress_before = await _progress_rows(pool)
        baseline_signals = await _keys(broker, "signals:*")
        baseline_legacy = await _keys(broker, "features:*")
        baseline_authority = await _authority_keys(broker)
        production_decision_routes = _production_decision_routes()
        production_risk_routes = _production_risk_routes()
        production_execution_assets = _production_execution_assets()

        await infrastructure.up(
            "ingestion", "risk-worker", "execution-worker", build=True, wait=False
        )
        await _wait_for(
            lambda: _ingestion_ready(infrastructure), label="ingestion readiness"
        )
        await _wait_for(
            lambda: infrastructure.running("risk-worker"), label="Risk worker running"
        )
        await _wait_for(
            lambda: infrastructure.running("execution-worker"),
            label="Execution worker running",
        )
        await _wait_for(
            lambda: _wait_groups(broker), label="Risk and Execution consumer groups"
        )
        await infrastructure.up("decision", build=True)
        await _wait_for(
            lambda: _decision_ready(infrastructure), label="Decision readiness"
        )
        startup_progress = await _progress_rows(pool)
        startup_authority = await _authority_keys(broker)
        startup_resource = await infrastructure.resource_sample("startup")

        repository = CandleRepository(pool)
        materialized: dict[str, object] = {}
        for asset in ("BTC", "ETH"):
            materialized[asset] = await _materialize_window(
                repository,
                asset=asset,
                start=bucket_start,
                index_offset=0,
                config=config,
            )
        await _wait_for(
            lambda: _wait_outbox_empty(pool), label="ingestion outbox drain"
        )
        signal_inventory = await _wait_for(
            lambda: _signals_nonempty(broker),
            label="Decision signal publication",
            timeout=180,
        )
        signal_count = sum(int(value["count"]) for value in signal_inventory.values())
        if signal_count <= 0:
            raise AssertionError(
                "Decision did not publish a signal in the certified live window"
            )
        await _wait_for(
            lambda: _keys_nonempty(broker, "fills:*"),
            label="paper execution fill",
            timeout=90,
        )
        orders = await _keys(broker, "orders:*")
        fills = await _keys(broker, "fills:*")
        live_signal_inventory = await _signal_inventory(broker)
        live_groups = await _groups(
            broker,
            [
                *[f"signals:{route.replace(':', ':', 1)}" for route in EXPECTED_ROUTES],
                *[f"orders:{asset}" for asset in EXPECTED_ASSETS],
            ],
        )
        live_execution = await _execution_status(broker)
        live_progress = await _progress_rows(pool)
        live_resource = await infrastructure.resource_sample("live")

        before_decision_restart = live_signal_inventory
        await infrastructure.restart("decision")
        await _wait_for(
            lambda: _decision_ready(infrastructure), label="Decision restart readiness"
        )
        after_decision_restart = await _signal_inventory(broker)
        decision_restart = {
            "ready": True,
            "authority_keys_absent": (await _authority_keys(broker))
            == startup_authority,
            "effect_progress_restored": bool(await _progress_rows(pool)),
            "signals_before": before_decision_restart,
            "signals_after": after_decision_restart,
            "duplicate_free": _signal_ids_unique(after_decision_restart),
        }
        decision_restart_resource = await infrastructure.resource_sample(
            "decision_restart"
        )

        await infrastructure.restart("broker")
        await _wait_for(lambda: _broker_ready(broker), label="broker restart")
        await infrastructure.restart("decision", "risk-worker", "execution-worker")
        await _wait_for(
            lambda: _decision_ready(infrastructure),
            label="broker recovery Decision readiness",
        )
        broker_recovery = {
            "ready": True,
            "authority_keys_absent": (await _authority_keys(broker))
            == startup_authority,
            "signals_unchanged": await _signal_inventory(broker)
            == after_decision_restart,
            "groups_restored": await _wait_groups(broker),
        }
        broker_resource = await infrastructure.resource_sample("broker_restart")

        await pool.close()
        pool = None
        await infrastructure.restart("db")
        await infrastructure.restart("decision", "risk-worker", "execution-worker")
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=6
        )
        await _wait_for(
            lambda: _decision_ready(infrastructure),
            label="database recovery Decision readiness",
        )
        db_recovery = {
            "ready": True,
            "effect_progress_restored": bool(await _progress_rows(pool)),
            "authority_keys_absent": (await _authority_keys(broker))
            == startup_authority,
            "signals_unchanged": await _signal_inventory(broker)
            == after_decision_restart,
        }
        db_resource = await infrastructure.resource_sample("database_restart")

        await broker.aclose()
        broker = None
        await pool.close()
        pool = None
        await infrastructure.stop(*reversed(EXPECTED_SERVICES))
        await infrastructure.up("db", "broker")
        await infrastructure.up("ingestion")
        await infrastructure.up("decision")
        await infrastructure.up("risk-worker", "execution-worker", wait=False)
        pool = await asyncpg.create_pool(
            infrastructure.postgres_dsn, min_size=1, max_size=6
        )
        broker = valkey.Valkey.from_url(
            infrastructure.valkey_uri, decode_responses=True
        )
        await _wait_for(
            lambda: _ingestion_ready(infrastructure),
            label="full restart ingestion readiness",
        )
        await _wait_for(
            lambda: _decision_ready(infrastructure),
            label="full restart Decision readiness",
        )
        await _wait_for(
            lambda: infrastructure.running("risk-worker"),
            label="full restart Risk worker running",
        )
        await _wait_for(
            lambda: infrastructure.running("execution-worker"),
            label="full restart Execution worker running",
        )
        full_restart = {
            "ready": True,
            "authority_keys_absent": (await _authority_keys(broker))
            == startup_authority,
            "effect_progress_restored": bool(await _progress_rows(pool)),
            "signals_unchanged": await _signal_inventory(broker)
            == after_decision_restart,
            "no_duplicate_signals": _signal_ids_unique(await _signal_inventory(broker)),
        }
        full_resource = await infrastructure.resource_sample("full_restart")

        signal_inventory_final = await _signal_inventory(broker)
        groups_final = await _groups(
            broker,
            [
                *[f"signals:{route}" for route in EXPECTED_ROUTES],
                *[f"orders:{asset}" for asset in EXPECTED_ASSETS],
            ],
        )
        evidence = {
            "trial_name": trial_name,
            "topology": {
                "services": list(EXPECTED_SERVICES),
                "legacy_services_absent": True,
                "dynamic_ports": True,
                "disposable_project": infrastructure.project_name,
            },
            "configuration": {
                "fixture_decision_routes": list(EXPECTED_ROUTES),
                "production_decision_routes": list(production_decision_routes),
                "production_risk_routes": list(production_risk_routes),
                "production_execution_assets": list(production_execution_assets),
                "execution_mode": _production_execution_mode(),
                "decision_assets_fixture_only": True,
            },
            "startup": {
                "decision_ready": True,
                "ingestion_ready": True,
                "risk_ready": await infrastructure.running("risk-worker"),
                "execution_ready": await infrastructure.running("execution-worker"),
                "authority_keys_before": baseline_authority,
                "authority_keys_after": startup_authority,
                "effect_progress_before": startup_progress_before,
                "effect_progress": startup_progress,
                "baseline_signals": baseline_signals,
                "baseline_legacy_streams": baseline_legacy,
                "startup_history_bars": STARTUP_COUNT,
            },
            "flow": {
                "bucket_start": bucket_start,
                "materialized": materialized,
                "outbox_pending": int(
                    await pool.fetchval(
                        "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
                    )
                ),
                "signals": live_signal_inventory,
                "signal_count": sum(
                    int(value["count"]) for value in live_signal_inventory.values()
                ),
                "groups": live_groups,
                "orders_streams": orders,
                "fills_streams": fills,
                "execution_status": live_execution,
                "effect_progress": live_progress,
            },
            "recovery": {
                "decision_restart": decision_restart,
                "broker_restart": broker_recovery,
                "database_restart": db_recovery,
                "full_topology_restart": full_restart,
            },
            "final": {
                "signals": signal_inventory_final,
                "groups": groups_final,
                "effect_progress": await _progress_rows(pool),
                "authority_keys": await _authority_keys(broker),
                "no_legacy_streams": not bool(
                    await _keys(broker, "features:*")
                    or await _keys(broker, "decision:shadow:legacy*")
                ),
                "shadow_streams": await _keys(broker, "decision:shadow:*"),
                "paper_execution_status": await _execution_status(broker),
            },
            "resource_samples": {
                "startup": startup_resource,
                "live": live_resource,
                "decision_restart": decision_restart_resource,
                "broker_restart": broker_resource,
                "database_restart": db_resource,
                "full_restart": full_resource,
            },
            "historical_d12a_archive": _historical_d12a_archive_status(),
            "current_base_d12a_reconciliation": _current_base_d12a_status(),
            "current_d11c_proof": _current_d11c_status(),
            "deleted_paths": _deleted_paths_absent(),
            "root_compose": _root_compose_status(),
            "surviving_runtime_import_boundary": _surviving_runtime_import_boundary(),
            "retired_harness_imports": _retired_harness_import_scan(),
            "decision_authority_seam": _decision_authority_seam_scan(),
            "live_reference_scan": _live_reference_scan(),
            "source_inventory": list(D12B_SOURCE_PATHS),
            "source_locks": source_locks(),
            "protected_hashes": protected_hashes(),
        }
        return evidence
    finally:
        if broker is not None:
            await broker.aclose()
        if pool is not None:
            await pool.close()
        cleanup = await infrastructure.cleanup()
        evidence["cleanup"] = cleanup
        if not cleanup["clean"]:
            raise RuntimeError(f"D12 disposable cleanup failed: {cleanup}")


async def _broker_ready(broker: Any) -> bool:
    try:
        return bool(await broker.ping())
    except Exception:  # noqa: BLE001
        return False


async def _keys_nonempty(broker: Any, pattern: str) -> tuple[str, ...] | None:
    keys = await _keys(broker, pattern)
    return keys or None


def _signal_ids_unique(inventory: Mapping[str, object]) -> bool:
    ids_by_stream: dict[str, list[str]] = {}
    for stream, value in inventory.items():
        ids_by_stream[str(stream)] = [str(item) for item in value.get("ids", [])]
    return all(len(ids) == len(set(ids)) for ids in ids_by_stream.values())


def source_locks() -> dict[str, str]:
    return {path: file_sha256(ROOT / path) for path in D12B_SOURCE_PATHS}


def _production_decision_routes() -> tuple[str, ...]:
    manager = ConfigManager(config_dir=str(ROOT))
    try:
        config = load_decision_config(manager)
        return decision_authoritative_routes_from_config(config.assets)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _production_risk_routes() -> tuple[str, ...]:
    manager = ConfigManager(config_dir=str(ROOT))
    try:
        manager.register_file("configs/risk.yaml")
        return parse_signal_routes(manager.get("risk.runtime.signal_routes", ()))
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _production_execution_assets() -> tuple[str, ...]:
    return tuple(assets_from_routes(_production_risk_routes()))


def _production_execution_mode() -> str | None:
    manager = ConfigManager(config_dir=str(ROOT))
    try:
        manager.register_file("configs/execution.yaml")
        value = manager.get("execution.mode", None)
        return value if isinstance(value, str) else None
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _deleted_paths_absent() -> dict[str, bool]:
    return {path: not (ROOT / path).exists() for path in D12_DELETED_PATHS}


def _root_compose_status() -> dict[str, object]:
    document = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = document.get("services", {}) if isinstance(document, Mapping) else {}
    return {
        "services": tuple(services) if isinstance(services, Mapping) else (),
        "legacy_services_absent": not any(
            token in services for token in FORBIDDEN_SERVICE_TOKENS
        )
        if isinstance(services, Mapping)
        else False,
    }


def _surviving_runtime_import_boundary() -> dict[str, object]:
    forbidden = FORBIDDEN_PACKAGE_TOKENS
    inspected: list[str] = []
    matches: list[dict[str, object]] = []
    for relative_root in (*D12_RUNTIME_IMPORT_PATHS, *D12_RETAINED_NEUTRAL_PATHS):
        path_root = ROOT / relative_root
        if path_root.is_dir():
            paths = sorted(path_root.rglob("*.py"))
        elif path_root.is_file():
            paths = [path_root]
        else:
            continue
        inspected.append(relative_root)
        for path in paths:
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if any(token in line for token in forbidden):
                    matches.append(
                        {
                            "path": str(path.relative_to(ROOT)),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
    return {
        "paths": [*D12_RUNTIME_IMPORT_PATHS, *D12_RETAINED_NEUTRAL_PATHS],
        "forbidden_modules": list(forbidden),
        "inspected": inspected,
        "matches": matches,
        "clean": inspected == [*D12_RUNTIME_IMPORT_PATHS, *D12_RETAINED_NEUTRAL_PATHS]
        and not matches,
    }


def _retired_harness_import_scan() -> dict[str, object]:
    matches: list[dict[str, object]] = []
    import_pattern = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)")
    for relative_root in ("src", "scripts", "tests"):
        root = ROOT / relative_root
        for path in sorted(root.rglob("*.py")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                matches.append(
                    {
                        "path": str(path.relative_to(ROOT)),
                        "line": 0,
                        "text": f"cannot inspect import surface: {exc}",
                    }
                )
                continue
            for line_number, line in enumerate(lines, start=1):
                import_match = import_pattern.match(line)
                if import_match is None:
                    continue
                module = import_match.group(1)
                if any(
                    module == retired or module.startswith(retired + ".")
                    for retired in D12_RETIRED_COMBINED_MODULES
                ):
                    matches.append(
                        {
                            "path": str(path.relative_to(ROOT)),
                            "line": line_number,
                            "module": module,
                        }
                    )
    return {
        "modules": list(D12_RETIRED_COMBINED_MODULES),
        "matches": matches,
        "clean": not matches,
    }


def _decision_authority_seam_scan() -> dict[str, object]:
    matches: list[dict[str, object]] = []
    forbidden_fields = ("authority" + "_records", "authority" + "_record")
    for relative_root in ("src/apps/decision_app", "tests/decision"):
        root = ROOT / relative_root
        for path in sorted(root.rglob("*.py")):
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if any(field_name in line for field_name in forbidden_fields):
                    matches.append(
                        {
                            "path": str(path.relative_to(ROOT)),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
    return {
        "paths": ["src/apps/decision_app", "tests/decision"],
        "matches": matches,
        "clean": not matches,
    }


def _live_reference_scan() -> dict[str, object]:
    targets: tuple[Path, ...] = (
        ROOT / "src",
        ROOT / "scripts",
        ROOT / "tests",
        ROOT / "docs",
        ROOT / "configs",
        ROOT / "docker-compose.yml",
    )
    matches: list[dict[str, object]] = []
    for target in targets:
        paths = [target] if target.is_file() else sorted(target.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix in {
                ".pyc",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".svg",
            }:
                continue
            relative = str(path.relative_to(ROOT))
            if relative.startswith(("artifacts/", "plans/")):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(
                    token in line
                    for token in (
                        *FORBIDDEN_PACKAGE_TOKENS,
                        *FORBIDDEN_SERVICE_TOKENS,
                        FORBIDDEN_AUTHORITY_TOKEN,
                    )
                ):
                    matches.append(
                        {
                            "path": relative,
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
    return {
        "matches": matches,
        "clean": not matches,
    }


def _historical_d12a_archive_status() -> dict[str, object]:
    artifact = json.loads(HISTORICAL_D12A_ARTIFACT_FILE.read_text(encoding="utf-8"))
    gates = artifact.get("gates", {})
    status = {
        "artifact_sha256_exact": file_sha256(HISTORICAL_D12A_ARTIFACT_FILE)
        == HISTORICAL_D12A_SHA256,
        "identity_digest_exact": artifact.get("identity_digest")
        == HISTORICAL_D12A_IDENTITY_DIGEST,
        "evidence_digest_exact": artifact.get("evidence_digest")
        == HISTORICAL_D12A_EVIDENCE_DIGEST,
        "source_sha_exact": artifact.get("source_sha") == HISTORICAL_D12A_BASE_SHA,
        "terminal_status_exact": artifact.get("terminal_status")
        == HISTORICAL_D12A_SUCCESS_STATUS,
        "gate_count_exact": len(gates) == HISTORICAL_D12A_GATE_COUNT,
        "stored_gates_true": bool(gates)
        and all(bool(value) for value in gates.values()),
        "source_lock_count_exact": len(artifact.get("source_locks", {}))
        == HISTORICAL_D12A_SOURCE_LOCK_COUNT,
    }
    status["valid"] = all(status.values())
    return status


def _current_base_d12a_status() -> dict[str, object]:
    artifact = json.loads(CURRENT_BASE_D12A_ARTIFACT_FILE.read_text(encoding="utf-8"))
    status = {
        "artifact_sha256_exact": file_sha256(CURRENT_BASE_D12A_ARTIFACT_FILE)
        == CURRENT_BASE_D12A_SHA256,
        "source_sha_exact": artifact.get("source_sha") == D12B_BASE_SHA,
        "terminal_status_exact": artifact.get("terminal_status")
        == "DECISION_D12A_CURRENT_BASE_RECONCILIATION_READY_FOR_REVIEW",
    }
    status["valid"] = all(status.values())
    return status


def _current_d11c_status() -> dict[str, object]:
    artifact_path = (
        ROOT
        / "artifacts/decision_d11c/d11c_default_topology_promotion_certification.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    status = {
        "artifact_sha256_exact": file_sha256(artifact_path) == D11C_SHA256,
        "terminal_status_exact": artifact.get("terminal_status")
        == "DECISION_D11C_DEFAULT_TOPOLOGY_PROMOTION_READY_FOR_REVIEW",
        "trial_semantic_parity_matches": bool(
            artifact.get("raw_evidence", {})
            .get("trial_semantic_parity", {})
            .get("matches")
        ),
    }
    status["valid"] = all(status.values())
    return status


def _identity_payload(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": artifact.get("schema_version", 1),
        "source_sha": artifact.get("source_sha"),
        "topology": artifact.get("topology"),
        "configuration": artifact.get("configuration"),
        "source_locks": artifact.get("source_locks"),
        "protected_hashes": artifact.get("protected_hashes"),
    }


def _content_evidence_payload(
    artifact: Mapping[str, object], content_gates: Mapping[str, bool]
) -> dict[str, object]:
    excluded = {
        "identity_digest",
        "evidence_digest",
        "gates",
        "terminal_status",
    }
    payload = {
        str(key): value for key, value in artifact.items() if key not in excluded
    }
    payload["gates"] = dict(content_gates)
    return payload


def recompute_identity_digest(artifact: Mapping[str, object]) -> str:
    return sha256_fingerprint(_identity_payload(artifact))


def recompute_evidence_digest(artifact: Mapping[str, object]) -> str:
    return sha256_fingerprint(
        _content_evidence_payload(artifact, _derive_content_gates(artifact))
    )


def protected_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for name, (path, _expected) in PROTECTED_ARTIFACTS.items():
        result[name] = file_sha256(ROOT / path)
    return result


def protected_hashes_valid(value: Mapping[str, str] | None = None) -> bool:
    actual = dict(value or protected_hashes())
    expected = {
        name: expected for name, (_path, expected) in PROTECTED_ARTIFACTS.items()
    }
    return actual == expected


def _current_state_matches(evidence: Mapping[str, object]) -> dict[str, bool]:
    configuration = evidence.get("configuration")
    if not isinstance(configuration, Mapping):
        return {
            "current_deleted_paths_match": False,
            "current_root_compose_match": False,
            "current_decision_routes_match": False,
            "current_risk_routes_match": False,
            "current_execution_assets_match": False,
            "current_execution_mode_match": False,
            "current_survivor_import_boundary_match": False,
            "current_live_reference_scan_match": False,
            "current_retired_harness_imports_match": False,
            "current_decision_authority_seam_match": False,
            "current_source_inventory_match": False,
            "current_source_locks_match": False,
        }
    try:
        current_source_locks = source_locks()
        current_source_inventory = list(D12B_SOURCE_PATHS)
        current_deleted_paths = _deleted_paths_absent()
        current_root_compose = _root_compose_status()
        current_decision_routes = _production_decision_routes()
        current_risk_routes = _production_risk_routes()
        current_execution_assets = _production_execution_assets()
        current_execution_mode = _production_execution_mode()
        current_survivor_import_boundary = _surviving_runtime_import_boundary()
        current_live_reference_scan = _live_reference_scan()
        current_retired_harness_imports = _retired_harness_import_scan()
        current_decision_authority_seam = _decision_authority_seam_scan()
    except Exception:  # noqa: BLE001
        return {
            "current_deleted_paths_match": False,
            "current_root_compose_match": False,
            "current_decision_routes_match": False,
            "current_risk_routes_match": False,
            "current_execution_assets_match": False,
            "current_execution_mode_match": False,
            "current_survivor_import_boundary_match": False,
            "current_live_reference_scan_match": False,
            "current_retired_harness_imports_match": False,
            "current_decision_authority_seam_match": False,
            "current_source_inventory_match": False,
            "current_source_locks_match": False,
        }
    return {
        "current_deleted_paths_match": _canonical_equal(
            evidence.get("deleted_paths"), current_deleted_paths
        ),
        "current_root_compose_match": _canonical_equal(
            evidence.get("root_compose"), current_root_compose
        ),
        "current_decision_routes_match": _canonical_equal(
            configuration.get("production_decision_routes"), current_decision_routes
        ),
        "current_risk_routes_match": _canonical_equal(
            configuration.get("production_risk_routes"), current_risk_routes
        ),
        "current_execution_assets_match": _canonical_equal(
            configuration.get("production_execution_assets"), current_execution_assets
        ),
        "current_execution_mode_match": configuration.get("execution_mode")
        == current_execution_mode,
        "current_survivor_import_boundary_match": _canonical_equal(
            evidence.get("surviving_runtime_import_boundary"),
            current_survivor_import_boundary,
        ),
        "current_live_reference_scan_match": _canonical_equal(
            evidence.get("live_reference_scan"), current_live_reference_scan
        ),
        "current_retired_harness_imports_match": _canonical_equal(
            evidence.get("retired_harness_imports"), current_retired_harness_imports
        ),
        "current_decision_authority_seam_match": _canonical_equal(
            evidence.get("decision_authority_seam"), current_decision_authority_seam
        ),
        "current_source_inventory_match": _canonical_equal(
            evidence.get("source_inventory"), current_source_inventory
        ),
        "current_source_locks_match": _canonical_equal(
            evidence.get("source_locks"), current_source_locks
        ),
    }


def _resource_gates(samples: Mapping[str, object]) -> dict[str, bool]:
    phase_map = {
        str(phase): value
        for phase, value in samples.items()
        if isinstance(value, Mapping)
    }
    exact_phase_services = bool(phase_map) and all(
        set(phase_value) == set(EXPECTED_SERVICES) for phase_value in phase_map.values()
    )
    flat = [item for phase in phase_map.values() for item in phase.values()]
    service_items = [item for item in flat if isinstance(item, Mapping)]
    all_present = bool(service_items) and all(
        bool(item.get("present")) for item in service_items
    )
    memory_ok = all(
        int(item.get("memory_usage_bytes", 0))
        < int(item.get("configured_memory_bytes", 0) or 1)
        for item in service_items
        if int(item.get("configured_memory_bytes", 0)) > 0
    )
    aggregate = sum(int(item.get("memory_usage_bytes", 0)) for item in service_items)
    cpu = sum(float(item.get("cpu_percent", 0.0)) for item in service_items) / 100.0
    return {
        "resource_phase_services_exact": exact_phase_services,
        "resource_samples_all_present": all_present,
        "service_rss_within_limits": memory_ok,
        "aggregate_rss_under_5_gib": aggregate < 5 * 1024**3,
        "aggregate_rss_under_8_gib": aggregate < 8 * 1024**3,
        "aggregate_cpu_under_4_cores": cpu <= 4.0,
        "oom_killed_false": all(
            not item.get("oom_killed", False) for item in service_items
        ),
        "unexpected_restart_false": all(
            int(item.get("restart_count", 0)) == 0 for item in service_items
        ),
    }


def _derive_content_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    topology = evidence.get("topology", {})
    configuration = evidence.get("configuration", {})
    startup = evidence.get("startup", {})
    flow = evidence.get("flow", {})
    recovery = evidence.get("recovery", {})
    final = evidence.get("final", {})
    historical_archive = evidence.get("historical_d12a_archive", {})
    current_base_archive = evidence.get("current_base_d12a_reconciliation", {})
    current_d11c = evidence.get("current_d11c_proof", {})
    if not isinstance(topology, Mapping):
        topology = {}
    if not isinstance(configuration, Mapping):
        configuration = {}
    if not isinstance(startup, Mapping):
        startup = {}
    if not isinstance(flow, Mapping):
        flow = {}
    if not isinstance(recovery, Mapping):
        recovery = {}
    if not isinstance(final, Mapping):
        final = {}
    if not isinstance(historical_archive, Mapping):
        historical_archive = {}
    if not isinstance(current_base_archive, Mapping):
        current_base_archive = {}
    if not isinstance(current_d11c, Mapping):
        current_d11c = {}
    signals = flow.get("signals", {})
    groups = flow.get("groups", {})
    execution_status = flow.get("execution_status", {})
    if not isinstance(signals, Mapping):
        signals = {}
    if not isinstance(groups, Mapping):
        groups = {}
    if not isinstance(execution_status, Mapping):
        execution_status = {}
    services = set(topology.get("services", []))
    signal_streams = tuple(f"signals:{route}" for route in EXPECTED_ROUTES)
    order_streams = tuple(f"orders:{asset}" for asset in EXPECTED_ASSETS)
    signal_groups_ok = all(
        any(
            item.get("name") == "risk_app_group" and item.get("pending") == 0
            for item in groups.get(stream, [])
        )
        for stream in signal_streams
    )
    order_groups_ok = all(
        any(
            item.get("name") == "execution_app_group" and item.get("pending") == 0
            for item in groups.get(stream, [])
        )
        for stream in order_streams
    )
    paper_ok = bool(execution_status) and all(
        str(value.get("mode", "")) == "paper" for value in execution_status.values()
    )
    execution_live = (
        bool(execution_status)
        and all(
            str(value.get("state", "")) == "LIVE" for value in execution_status.values()
        )
        and any(
            int(value.get("processed_count", 0) or 0) > 0
            for value in execution_status.values()
        )
    )
    recovery_ok = all(
        bool(recovery.get(name, {}).get("ready"))
        and bool(recovery.get(name, {}).get("authority_keys_absent"))
        for name in (
            "decision_restart",
            "broker_restart",
            "database_restart",
            "full_topology_restart",
        )
    )
    resource = _resource_gates(evidence.get("resource_samples", {}))
    boundary = evidence.get("surviving_runtime_import_boundary", {})
    deleted_paths = evidence.get("deleted_paths", {})
    root_compose = evidence.get("root_compose", {})
    live_reference_scan = evidence.get("live_reference_scan", {})
    retired_harness_imports = evidence.get("retired_harness_imports", {})
    decision_authority_seam = evidence.get("decision_authority_seam", {})
    current_state = _current_state_matches(evidence)
    final_signal_streams = tuple(sorted(signals))
    production_decision_routes = tuple(
        configuration.get("production_decision_routes", ())
    )
    production_risk_routes = tuple(configuration.get("production_risk_routes", ()))
    production_execution_assets = tuple(
        configuration.get("production_execution_assets", ())
    )
    gates = {
        "historical_d12a_archive_valid": bool(historical_archive.get("valid")),
        "current_base_d12a_archive_valid": bool(current_base_archive.get("valid")),
        "current_d11c_protected_exact": bool(current_d11c.get("valid")),
        "topology_exact": services == set(EXPECTED_SERVICES),
        "legacy_services_absent": all(
            service not in services for service in FORBIDDEN_SERVICE_TOKENS
        ),
        "root_compose_legacy_services_absent": bool(
            root_compose.get("legacy_services_absent")
        ),
        "production_decision_routes_exact": production_decision_routes
        == EXPECTED_ROUTES,
        "production_risk_routes_exact": production_risk_routes == EXPECTED_ROUTES,
        "decision_risk_route_agreement": production_decision_routes
        == production_risk_routes
        == EXPECTED_ROUTES,
        "production_execution_assets_exact": production_execution_assets
        == EXPECTED_ASSETS,
        "obsolete_strategy_routes_absent": not any(
            route in production_risk_routes or route in production_decision_routes
            for route in OBSOLETE_STRATEGY_ROUTES
        ),
        "execution_mode_paper": configuration.get("execution_mode") == "paper"
        and paper_ok,
        "startup_ready": all(
            bool(startup.get(key))
            for key in (
                "decision_ready",
                "ingestion_ready",
                "risk_ready",
                "execution_ready",
            )
        ),
        "no_authority_keys_before_startup": not startup.get("authority_keys_before"),
        "no_authority_keys_after_startup": not startup.get("authority_keys_after"),
        "effect_progress_baselined": not startup.get("effect_progress_before")
        and len(startup.get("effect_progress", [])) == len(EXPECTED_ROUTES)
        and all(
            row.get("last_disposition") is None
            for row in startup.get("effect_progress", [])
        ),
        "no_historical_signals": not startup.get("baseline_signals"),
        "real_signal_flow": int(flow.get("signal_count", 0)) > 0,
        "signal_stream_routes_canonical": set(final_signal_streams).issubset(
            set(signal_streams)
        ),
        "risk_consumes_decision_signals": signal_groups_ok,
        "execution_consumes_paper_orders": order_groups_ok
        and bool(flow.get("fills_streams"))
        and execution_live,
        "decision_signal_ids_unique": _signal_ids_unique(signals),
        "no_shadow_output": not bool(final.get("shadow_streams")),
        "decision_restart_recovered": recovery_ok
        and recovery.get("decision_restart", {}).get("duplicate_free", False),
        "broker_restart_recovered": bool(
            recovery.get("broker_restart", {}).get("groups_restored")
        ),
        "database_restart_recovered": bool(
            recovery.get("database_restart", {}).get("effect_progress_restored")
        ),
        "full_topology_recovered": bool(
            recovery.get("full_topology_restart", {}).get("no_duplicate_signals")
        ),
        "no_required_legacy_streams": bool(final.get("no_legacy_streams")),
        "no_authority_keys_final": not final.get("authority_keys"),
        "protected_artifacts_exact": protected_hashes_valid(
            evidence.get("protected_hashes")
        ),
        "deleted_paths_absent": bool(deleted_paths)
        and all(bool(value) for value in deleted_paths.values()),
        "source_sha_exact": evidence.get("source_sha") == D12B_BASE_SHA,
        "source_inventory_exact": _canonical_equal(
            evidence.get("source_inventory"), list(D12B_SOURCE_PATHS)
        ),
        "source_locks_present": bool(evidence.get("source_locks")),
        "source_locks_exact": _source_locks_exact(evidence),
        "surviving_runtime_import_boundary": bool(boundary.get("clean"))
        and tuple(boundary.get("paths", ()))
        == (*D12_RUNTIME_IMPORT_PATHS, *D12_RETAINED_NEUTRAL_PATHS)
        and not boundary.get("matches"),
        "live_reference_scan_clean": bool(live_reference_scan.get("clean"))
        and not live_reference_scan.get("matches"),
        "retired_harness_imports_clean": bool(retired_harness_imports.get("clean"))
        and not retired_harness_imports.get("matches"),
        "decision_authority_seam_clean": bool(decision_authority_seam.get("clean"))
        and not decision_authority_seam.get("matches"),
        **current_state,
        **resource,
        "cleanup_complete": bool(evidence.get("cleanup", {}).get("clean", False)),
    }
    return gates


def _source_locks_exact(evidence: Mapping[str, object]) -> bool:
    stored = evidence.get("source_locks")
    if not isinstance(stored, Mapping):
        return False
    try:
        current = source_locks()
    except OSError:
        return False
    return (
        bool(current)
        and set(stored) == set(D12B_SOURCE_PATHS)
        and dict(stored) == current
    )


def derive_gates(evidence: Mapping[str, object]) -> dict[str, bool]:
    gates = _derive_content_gates(evidence)
    gates.update(
        {
            "identity_digest_integrity": evidence.get("identity_digest")
            == recompute_identity_digest(evidence),
            "evidence_digest_integrity": evidence.get("evidence_digest")
            == recompute_evidence_digest(evidence),
        }
    )
    return gates


def stored_artifact_valid(artifact: Mapping[str, object]) -> bool:
    try:
        gates = derive_gates(artifact)
        expected_status = (
            D12B_SUCCESS_STATUS if all(gates.values()) else D12B_BLOCKED_STATUS
        )
        return (
            artifact.get("gates") == gates
            and artifact.get("terminal_status") == expected_status
            and all(gates.values())
        )
    except (TypeError, ValueError, OSError):
        return False


def build_artifact(evidence: Mapping[str, object]) -> dict[str, object]:
    canonical = _json_value(evidence)
    if not isinstance(canonical, Mapping):
        raise TypeError("D12 evidence must be a mapping")
    artifact = dict(canonical)
    artifact["schema_version"] = 1
    artifact["identity_digest"] = recompute_identity_digest(artifact)
    artifact["evidence_digest"] = recompute_evidence_digest(artifact)
    gates = derive_gates(artifact)
    artifact["gates"] = gates
    artifact["terminal_status"] = (
        D12B_SUCCESS_STATUS if all(gates.values()) else D12B_BLOCKED_STATUS
    )
    return artifact
