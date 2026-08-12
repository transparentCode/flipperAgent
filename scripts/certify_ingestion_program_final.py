"""Final, fail-fast certification facade for the ingestion programme.

This module deliberately contains orchestration and read-only evidence helpers
only.  Failure-mode certification remains owned by the phase-specific scripts;
this facade invokes those scripts in isolated subprocesses and records their
results.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

FINAL_STATUS = "READY_FOR_REVIEW"
FINAL_PROGRAM_STATUS = "INGESTION_PROGRAM_FINAL_CERTIFICATION_READY_FOR_REVIEW"
DRY_RUN_STATUS = "DRY_RUN"
FINAL_GUARD = "INGESTION_RUN_FINAL_CERTIFICATION"
ARTIFACT_PATH = REPO_ROOT / "artifacts/ingestion_final/final_certification.json"

EXPECTED_ASSETS = {
    "BTC": "BTC-USDT-PERP",
    "ETH": "ETH-USDT-PERP",
    "XRP": "XRP-USDT-PERP",
    "SOL": "SOL-USDT-PERP",
    "BNB": "BNB-USDT-PERP",
    "DOGE": "DOGE-USDT-PERP",
}
EXPECTED_SIGNAL_PAIRS = {
    ("BNBUSDT", "30m"),
    ("BTCUSDT", "1h"),
    ("BTCUSDT", "4h"),
    ("DOGEUSDT", "1h"),
    ("DOGEUSDT", "4h"),
    ("ETHUSDT", "4h"),
    ("SOLUSDT", "1h"),
    ("XRPUSDT", "1h"),
}
EXPECTED_IMAGE_SERVICES = (
    "ingestion",
    "signal-worker",
    "strategy-worker",
    "risk-worker",
    "execution-worker",
    "portfolio-worker",
    "api-server",
    "alert-worker",
    "alert-api",
    "scraper-service",
    "scraper-tradingview",
)
STATE_SERVICES = (
    "db",
    "broker",
    "ingestion",
    "signal-worker",
    "strategy-worker",
    "risk-worker",
    "execution-worker",
    "portfolio-worker",
    "alert-worker",
    "alert-api",
    "api-server",
    "scraper-service",
    "scraper-tradingview",
    "scheduler",
    "otel-collector",
    "tempo",
    "prometheus",
    "loki",
    "grafana",
)


class FinalCertificationError(RuntimeError):
    """A bounded, handoff-facing FINAL failure."""

    def __init__(
        self,
        status: str,
        message: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.evidence = dict(evidence or {})


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _tail(value: str, limit: int = 12_000) -> str:
    return value if len(value) <= limit else value[-limit:]


def _command_text(args: Sequence[str]) -> str:
    return shlex.join(str(arg) for arg in args)


def _run_command(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update({str(key): str(value) for key, value in env.items()})
    try:
        return subprocess.run(
            [str(arg) for arg in args],
            cwd=REPO_ROOT,
            env=merged_env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            f"command failed to execute: {_command_text(args)}: {exc}",
            evidence={"command": _command_text(args)},
        ) from exc


def _compose(
    *args: str, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return _run_command(("docker", "compose", *args), timeout=timeout)


def _json_from_stdout(stdout: str) -> dict[str, Any] | None:
    """Extract the last JSON object from certifier output that may include logs."""
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    status_objects = [item for item in objects if "status" in item]
    return status_objects[-1] if status_objects else (objects[-1] if objects else None)


def _run_subcert(
    name: str,
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    expected_status: str = FINAL_STATUS,
) -> dict[str, Any]:
    completed = _run_command(args, env=env)
    parsed = _json_from_stdout(completed.stdout)
    evidence: dict[str, Any] = {
        "name": name,
        "command": _command_text(args),
        "return_code": completed.returncode,
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
    }
    if parsed is not None:
        evidence["result"] = parsed

    if completed.returncode != 0:
        raise FinalCertificationError(
            f"BLOCKED_FINAL_{name.upper()}",
            f"{name} returned {completed.returncode}",
            evidence=evidence,
        )
    if expected_status != "pytest_pass":
        actual = parsed.get("status") if parsed else None
        if actual != expected_status:
            raise FinalCertificationError(
                f"BLOCKED_FINAL_{name.upper()}",
                f"{name} did not return {expected_status!r}; got {actual!r}",
                evidence=evidence,
            )
    return evidence


def _compose_config() -> dict[str, Any]:
    completed = _compose("config", "--format", "json")
    if completed.returncode != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "docker compose config failed",
            evidence={
                "stdout": _tail(completed.stdout),
                "stderr": _tail(completed.stderr),
            },
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "docker compose config did not return JSON",
            evidence={"stdout": _tail(completed.stdout)},
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("services"), dict):
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "docker compose config has no services mapping",
        )
    return value


def _service_state(service: str) -> dict[str, Any]:
    listed = _compose("ps", "-a", "-q", service)
    container_id = (
        listed.stdout.strip().splitlines()[0] if listed.stdout.strip() else ""
    )
    if listed.returncode != 0 or not container_id:
        return {"service": service, "exists": False, "running": False}
    inspected = _run_command(("docker", "inspect", container_id))
    if inspected.returncode != 0:
        return {
            "service": service,
            "exists": True,
            "running": False,
            "inspect_error": _tail(inspected.stderr),
        }
    try:
        payload = json.loads(inspected.stdout)[0]
        state = payload.get("State", {})
    except (IndexError, TypeError, json.JSONDecodeError):
        state = {}
    return {
        "service": service,
        "exists": True,
        "running": bool(state.get("Running")),
        "status": state.get("Status"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "health": (state.get("Health") or {}).get("Status"),
        "container_id": container_id,
    }


def _mcp_state() -> dict[str, Any]:
    listed = _run_command(
        (
            "docker",
            "compose",
            "-f",
            "mcp-compose.yml",
            "ps",
            "-a",
            "-q",
            "mcp-proxy",
        )
    )
    container_id = (
        listed.stdout.strip().splitlines()[0] if listed.stdout.strip() else ""
    )
    if not container_id:
        return {"exists": False, "running": False}
    inspected = _run_command(("docker", "inspect", container_id))
    if inspected.returncode != 0:
        return {
            "exists": True,
            "running": False,
            "inspect_error": _tail(inspected.stderr),
        }
    try:
        state = json.loads(inspected.stdout)[0].get("State", {})
    except (IndexError, TypeError, json.JSONDecodeError):
        state = {}
    return {
        "exists": True,
        "running": bool(state.get("Running")),
        "status": state.get("Status"),
        "container_id": container_id,
    }


def _local_postgres_dsn() -> str:
    value = os.getenv("FINAL_POSTGRES_URI") or os.getenv("POSTGRES_URI")
    if not value:
        return "postgresql://flipper:flipperpass@127.0.0.1:5432/flipper_db"
    return value.replace("@db:", "@127.0.0.1:").replace("@db/", "@127.0.0.1/")


async def _read_pending_outbox() -> int:
    import asyncpg

    connection = await asyncpg.connect(_local_postgres_dsn(), timeout=5)
    try:
        value = await connection.fetchval(
            "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
        )
        return int(value or 0)
    finally:
        await connection.close()


def _pending_outbox() -> int:
    try:
        return asyncio.run(_read_pending_outbox())
    except (OSError, TimeoutError, ValueError, RuntimeError) as exc:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            f"could not read pending ingestion outbox: {exc}",
        ) from exc


def _runtime_graph() -> dict[str, Any]:
    from apps.ingestion_app.settings import load_ingestion_settings
    from apps.signal_app.runtime_pairs import build_signal_pairs
    from apps.signal_app.settings import SignalWorkerSettings
    from libs.common.config import ConfigManager

    manager = ConfigManager()
    try:
        settings = load_ingestion_settings(manager)
        signal_settings = SignalWorkerSettings.from_config(manager)
        pairs = build_signal_pairs(manager)
        enabled = sorted(
            asset_name for asset_name, asset in settings.assets.items() if asset.enabled
        )
        owned = sorted(
            asset_name
            for asset_name, asset in settings.assets.items()
            if asset.owns_manifest_lifecycle
        )
        bindings = {
            binding.asset: {
                "source": binding.source,
                "venue": binding.venue,
                "instrument_id": binding.instrument_id,
            }
            for binding in signal_settings.ohlcv_sources
        }
        lane_streams: list[str] = []
        from apps.signal_app.ohlcv_source import (
            OhlcvSourceBinding,
            stream_key_for_binding,
        )

        for asset_name in enabled:
            asset = settings.assets[asset_name]
            for instrument_id, instrument in asset.instruments.items():
                binding = OhlcvSourceBinding(
                    asset=asset_name,
                    source="ingestion",
                    venue=instrument.venue,
                    instrument_id=instrument_id,
                )
                lane_streams.extend(
                    stream_key_for_binding(binding, timeframe)
                    for timeframe in instrument.timeframes
                )
        pair_keys = sorted((pair.asset, pair.timeframe) for pair in pairs)
        return {
            "enabled_assets": enabled,
            "owned_assets": owned,
            "bindings": bindings,
            "pairs": pair_keys,
            "lane_streams": sorted(set(lane_streams)),
            "timeframes": sorted(settings.timeframes),
            "base_timeframe": settings.base_timeframe,
            "finalization_grace_seconds": settings.recovery.rest_finalization_grace_seconds,
            "reconnect_backoff_seconds": settings.runtime.reconnect_backoff_seconds,
            "consumer_group": signal_settings.consumer_group,
            "consumer_name_prefix": signal_settings.consumer_name_prefix,
        }
    finally:
        with contextlib.suppress(Exception):
            manager.shutdown()
        with contextlib.suppress(Exception):
            ConfigManager.reset_singleton()


def _namespace_and_protocol_contract(compose: Mapping[str, Any]) -> dict[str, Any]:
    services = compose["services"]
    ingestion = services.get("ingestion")
    if not isinstance(ingestion, Mapping):
        raise FinalCertificationError(
            "BLOCKED_FINAL_PROTOCOL_DRIFT", "ingestion service is absent"
        )
    command = ingestion.get("command")
    command_text = " ".join(command) if isinstance(command, list) else str(command)
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    global_config = (REPO_ROOT / "configs/ingestion/global.yaml").read_text()
    schema = (REPO_ROOT / "src/apps/ingestion_app/storage/schema.sql").read_text()
    dashboard = (
        REPO_ROOT
        / "configs/observability/grafana/provisioning/dashboards/ingestion.json"
    ).read_text()
    outbox = __import__("apps.ingestion_app.publication.outbox", fromlist=["*"])
    checks = {
        "application_package": (SRC_ROOT / "apps/ingestion_app").is_dir(),
        "old_application_package_absent": not (
            SRC_ROOT / "apps" / ("ingestion_app" + "_" + "v2")
        ).exists(),
        "test_package": (REPO_ROOT / "tests/ingestion").is_dir(),
        "old_test_package_absent": not (
            REPO_ROOT / "tests" / ("ingestion" + "_" + "v2")
        ).exists(),
        "compose_service": "ingestion" in services,
        "compose_command": command_text == "python -m apps.ingestion_app.main",
        "cli_target": 'flipper-ingestion = "apps.ingestion_app.main:main"' in pyproject,
        "db_schema": "ingestion.candles" in schema and "ingestion.outbox" in schema,
        "stream_protocol": "stream:ohlcv:ingestion:"
        in "\n".join(
            path.read_text(errors="replace")
            for path in (REPO_ROOT / "src").rglob("*.py")
            if path.is_file()
        ),
        "config_directory": (REPO_ROOT / "configs/ingestion").is_dir(),
        "config_namespace": "ingestion:" in global_config,
        "otel_service_name": str(
            ingestion.get("environment", {}).get("OTEL_SERVICE_NAME")
        )
        == "ingestion",
        "metric_prefix": "ingestion_"
        in "\n".join(
            path.read_text(errors="replace")
            for path in (REPO_ROOT / "src").rglob("*.py")
            if path.is_file()
        ),
        "grafana_uid": '"uid": "flipper-ingestion"' in dashboard,
        "event_type": getattr(outbox, "CANDLE_COMMITTED_EVENT_TYPE", None)
        == "candle.committed",
        "event_schema_version": getattr(outbox, "CANDLE_COMMITTED_SCHEMA_VERSION", None)
        == 1,
        "event_producer": getattr(outbox, "CANDLE_COMMITTED_PRODUCER", None)
        == "ingestion",
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PROTOCOL_DRIFT",
            f"frozen contract checks failed: {', '.join(failed)}",
            evidence={"checks": checks},
        )
    return {"checks": checks, "compose_command": command_text}


def _active_old_namespace_matches() -> list[str]:
    roots = [REPO_ROOT / name for name in ("src", "tests", "scripts", "configs")]
    matches: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        old_namespace_pattern = "ingestion_app_" + "v2"
        completed = _run_command(
            (
                "rg",
                "-n",
                (
                    rf"from apps\.{old_namespace_pattern}|"
                    rf"import apps\.{old_namespace_pattern}|"
                    rf"apps\.{old_namespace_pattern}\."
                ),
                str(root),
            )
        )
        if completed.returncode == 0:
            matches.extend(
                line for line in completed.stdout.splitlines() if line.strip()
            )
    return matches


def _capture_preflight() -> dict[str, Any]:
    compose = _compose_config()
    protocol = _namespace_and_protocol_contract(compose)
    matches = _active_old_namespace_matches()
    if matches:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "active old Python namespace imports remain",
            evidence={"matches": matches},
        )
    graph = _runtime_graph()
    if graph["enabled_assets"] != sorted(EXPECTED_ASSETS):
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "enabled ingestion asset graph differs from the frozen six-asset graph",
            evidence={"graph": graph},
        )
    if graph["owned_assets"] != sorted(EXPECTED_ASSETS):
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "ingestion manifest ownership graph differs from the frozen six-asset graph",
            evidence={"graph": graph},
        )
    if set(graph["bindings"]) != {f"{asset}USDT" for asset in EXPECTED_ASSETS}:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "signal binding asset set differs from the frozen six-asset graph",
            evidence={"graph": graph},
        )
    if {graph["bindings"][asset]["source"] for asset in graph["bindings"]} != {
        "ingestion"
    }:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "a production signal binding is not ingestion-owned",
            evidence={"bindings": graph["bindings"]},
        )
    if set(graph["pairs"]) != EXPECTED_SIGNAL_PAIRS:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "signal pair graph differs from the frozen eight-pair graph",
            evidence={"actual_pairs": graph["pairs"]},
        )
    if len(graph["lane_streams"]) != 54:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "ingestion lane stream count differs from the frozen 54-lane graph",
            evidence={"stream_count": len(graph["lane_streams"])},
        )
    states = {service: _service_state(service) for service in STATE_SERVICES}
    mcp = _mcp_state()
    if not states["db"].get("running") or states["db"].get("health") not in {
        "healthy",
        "",
    }:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "Timescale must be running and healthy before FINAL",
            evidence={"db": states["db"]},
        )
    active_services = [
        name for name, state in states.items() if name != "db" and state.get("running")
    ]
    if active_services or mcp.get("running"):
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "FINAL requires application, observability, and MCP services to be stopped",
            evidence={"active_services": active_services, "mcp": mcp},
        )
    pending = _pending_outbox()
    if pending != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            "pending outbox must be zero before FINAL",
            evidence={"pending_outbox": pending},
        )
    return {
        "captured_at": _now(),
        "protocol": protocol,
        "graph": graph,
        "service_states": states,
        "mcp": mcp,
        "pending_outbox": pending,
        "active_old_namespace_matches": matches,
    }


def _host_valkey_uri() -> str:
    compose = _compose_config()
    broker = compose["services"].get("broker", {})
    ports = broker.get("ports", []) if isinstance(broker, Mapping) else []
    for entry in ports:
        published: object | None = None
        if isinstance(entry, Mapping):
            published = entry.get("published")
        elif isinstance(entry, str):
            published = entry.split(":")[-2] if ":" in entry else None
        if published:
            return f"redis://127.0.0.1:{published}/0"
    raise FinalCertificationError(
        "BLOCKED_FINAL_PREFLIGHT",
        "broker has no host-published port for DB0 verification",
    )


def _wait_until(
    predicate: Any,
    *,
    timeout: float,
    interval: float = 2.0,
    description: str,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(interval)
    raise FinalCertificationError(
        "BLOCKED_FINAL_PREFLIGHT",
        f"timed out waiting for {description}",
        evidence={"last": str(last)},
    )


def _n3b_verify(label: str) -> dict[str, Any]:
    start = _compose("start", "broker")
    if start.returncode != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_N3B_RETIREMENT_STATE",
            "could not temporarily start broker for N3B verification",
            evidence={"stdout": _tail(start.stdout), "stderr": _tail(start.stderr)},
        )
    try:
        _wait_until(
            lambda: _service_state("broker").get("health") == "healthy",
            timeout=60,
            description="broker health for N3B verification",
        )
        return _run_subcert(
            label,
            (
                sys.executable,
                "scripts/retire_legacy_ingestion_n3b.py",
                "--verify",
            ),
            env={"N3B_VALKEY_URI": _host_valkey_uri()},
        )
    finally:
        _compose("stop", "broker")


def _build_images() -> dict[str, Any]:
    completed = _compose("build", *EXPECTED_IMAGE_SERVICES, timeout=None)
    if completed.returncode != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_BUILD",
            "one or more FINAL production image builds failed",
            evidence={
                "services": EXPECTED_IMAGE_SERVICES,
                "stdout": _tail(completed.stdout),
                "stderr": _tail(completed.stderr),
            },
        )
    return {
        "services": EXPECTED_IMAGE_SERVICES,
        "return_code": completed.returncode,
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
    }


def _phase_gates(evidence: dict[str, Any]) -> None:
    evidence["n3b_pre"] = _n3b_verify("n3b_retirement_pre")
    evidence["n1c"] = _run_subcert(
        "n1c_operations",
        (sys.executable, "scripts/certify_ingestion_operations_n1c.py", "--execute"),
        env={
            "INGESTION_RUN_N1C_OPERATIONS": "1",
            "VALKEY_URI": _host_valkey_uri(),
        },
    )
    evidence["l2b2"] = _run_subcert(
        "db_resilience",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-s",
            "tests/ingestion/integration/test_infrastructure_resilience_l2b2.py",
        ),
        env={
            "INGESTION_RUN_L2B2_CERTIFICATION": "1",
            "POSTGRES_URI": _local_postgres_dsn(),
        },
        expected_status="pytest_pass",
    )
    evidence["n1d"] = _run_subcert(
        "n1d_observability",
        (
            sys.executable,
            "scripts/certify_ingestion_observability_n1d.py",
            "--execute",
        ),
        env={"INGESTION_RUN_N1D_OBSERVABILITY": "1"},
    )
    evidence["n2c"] = _run_subcert(
        "n2c_retention_recovery",
        (
            sys.executable,
            "scripts/certify_ingestion_retention_recovery_n2c.py",
            "--execute",
        ),
        env={"INGESTION_RUN_N2C_RETENTION": "1"},
    )
    evidence["n2c_signal_drain"] = _drain_signal_groups_after_n2c(
        evidence["preflight"]["graph"]
    )
    evidence["n3b_post"] = _n3b_verify("n3b_retirement_post")


def _http_json(path: str, *, method: str = "GET") -> dict[str, Any]:
    request = Request(f"http://127.0.0.1:8003{path}", method=method)
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read().decode()
            payload = json.loads(body)
            return {"http_status": response.status, **payload}
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc


def _wait_ingestion_live() -> dict[str, Any]:
    def ready() -> dict[str, Any] | None:
        try:
            live = _http_json("/health/live")
            health = _http_json("/health/ready")
            runtime = _http_json("/runtime")
        except RuntimeError:
            return None
        if live.get("http_status") != 200 or health.get("http_status") != 200:
            return None
        if str(runtime.get("state", "")).lower() != "live":
            return None
        if runtime.get("enabled_asset_count") != 6:
            return None
        return {"live": live, "ready": health, "runtime": runtime}

    return _wait_until(ready, timeout=300, description="six-asset ingestion LIVE")


def _pause_ingestion_and_wait(*, timeout: float = 180.0) -> dict[str, Any]:
    """Pause producers and prove the publisher drained before process stop."""
    before = {
        "broker": _service_state("broker"),
        "ingestion": _service_state("ingestion"),
    }
    if not before["broker"].get("running") or not before["ingestion"].get("running"):
        raise FinalCertificationError(
            "BLOCKED_FINAL_RESOURCE_RESTORE",
            "cannot establish ingestion quiescence while broker or ingestion is unavailable",
            evidence={"before": before},
        )

    pause_response = _http_json("/runtime/pause", method="POST")
    if pause_response.get("http_status") != 200:
        raise FinalCertificationError(
            "BLOCKED_FINAL_RESOURCE_RESTORE",
            "ingestion runtime pause request failed",
            evidence={"pause_response": pause_response},
        )

    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        current = {
            "broker": _service_state("broker"),
            "ingestion": _service_state("ingestion"),
        }
        if not current["broker"].get("running") or not current["ingestion"].get(
            "running"
        ):
            raise FinalCertificationError(
                "BLOCKED_FINAL_RESOURCE_RESTORE",
                "broker or ingestion stopped before quiescence was proven",
                evidence={"before": before, "current": current, "last": last},
            )
        runtime = _http_json("/runtime")
        pending = _pending_outbox()
        last = {"runtime": runtime, "pending_outbox": pending}
        if (
            runtime.get("http_status") == 200
            and str(runtime.get("desired_state", "")).lower() == "paused"
            and str(runtime.get("state", "")).lower() == "stopped"
            and pending == 0
        ):
            return {
                "proven": True,
                "before": before,
                "pause_response": pause_response,
                "paused_runtime": runtime,
                "pre_stop_outbox": pending,
            }
        time.sleep(2)
    raise FinalCertificationError(
        "BLOCKED_FINAL_RESOURCE_RESTORE",
        "ingestion runtime did not reach paused/stopped with zero pending outbox",
        evidence={"before": before, "last": last},
    )


def _container_namespace_proof() -> dict[str, Any]:
    old_namespace = "apps." + "ingestion_app_" + "v2"
    command = (
        "python",
        "-c",
        (
            "import importlib.util; import apps.ingestion_app.main; "
            f"assert importlib.util.find_spec({old_namespace!r}) is None"
        ),
    )
    completed = _compose("exec", "-T", "ingestion", *command)
    if completed.returncode != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_RUNTIME",
            "canonical package namespace proof failed inside ingestion",
            evidence={
                "stdout": _tail(completed.stdout),
                "stderr": _tail(completed.stderr),
            },
        )
    return {"command": _command_text(command), "return_code": completed.returncode}


async def _db_snapshot(graph: Mapping[str, Any]) -> dict[str, Any]:
    import asyncpg

    connection = await asyncpg.connect(_local_postgres_dsn(), timeout=5)
    try:
        latest: dict[str, dict[str, Any]] = {}
        recent: dict[str, list[dict[str, Any]]] = {}
        for asset, instrument_id in EXPECTED_ASSETS.items():
            row = await connection.fetchrow(
                """
                SELECT open_time, close_time, open, high, low, close, volume,
                       taker_buy_base
                FROM ingestion.candles
                WHERE venue = 'binance'
                  AND instrument_id = $1
                  AND timeframe = '1m'
                ORDER BY open_time DESC
                LIMIT 1
                """,
                instrument_id,
            )
            if row is None:
                raise RuntimeError(f"no latest 1m candle for {asset}")
            latest[asset] = dict(row)
            rows = await connection.fetch(
                """
                SELECT open_time, close_time, open, high, low, close, volume,
                       taker_buy_base
                FROM ingestion.candles
                WHERE venue = 'binance'
                  AND instrument_id = $1
                  AND timeframe = '1m'
                ORDER BY open_time DESC
                LIMIT 120
                """,
                instrument_id,
            )
            recent[asset] = [dict(item) for item in reversed(rows)]
        pending = await connection.fetchval(
            "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
        )
        counts = await connection.fetchrow(
            """
            SELECT (SELECT COUNT(*) FROM ingestion.candles) AS candles,
                   (SELECT COUNT(*) FROM ingestion.outbox) AS outbox
            """
        )
        return {
            "latest": latest,
            "recent": recent,
            "pending_outbox": int(pending or 0),
            "candle_count": int(counts["candles"]),
            "outbox_count": int(counts["outbox"]),
        }
    finally:
        await connection.close()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _validate_recent_base(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for asset, rows in snapshot["recent"].items():
        if len(rows) < 2:
            raise FinalCertificationError(
                "BLOCKED_FINAL_BASE_CONTINUITY",
                f"insufficient recent 1m candles for {asset}",
            )
        previous = None
        for row in rows:
            open_time = row["open_time"]
            close_time = row["close_time"]
            if previous is not None and (open_time - previous).total_seconds() != 60:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_BASE_CONTINUITY",
                    f"1m gap or duplicate in {asset} recent candles",
                )
            if (close_time - open_time).total_seconds() != 60:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_BASE_CONTINUITY",
                    f"invalid 1m close geometry for {asset}",
                )
            low = Decimal(str(row["low"]))
            high = Decimal(str(row["high"]))
            open_value = Decimal(str(row["open"]))
            close_value = Decimal(str(row["close"]))
            volume = Decimal(str(row["volume"]))
            taker = row["taker_buy_base"]
            if not low <= open_value <= high or not low <= close_value <= high:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_TAKER_SEMANTICS",
                    f"invalid OHLC geometry for {asset}",
                )
            if volume < 0 or taker is None:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_TAKER_SEMANTICS",
                    f"missing/negative volume semantics for {asset}",
                )
            if not 0 <= Decimal(str(taker)) <= volume:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_TAKER_SEMANTICS",
                    f"invalid taker-buy-base semantics for {asset}",
                )
            previous = open_time
        evidence[asset] = {
            "rows": len(rows),
            "first_open": rows[0]["open_time"],
            "last_open": rows[-1]["open_time"],
        }
    return _jsonable(evidence)


async def _valkey_tail(client: Any, key: str) -> str | None:
    rows = await client.xrevrange(key, max="+", min="-", count=1)
    if not rows:
        return None
    return str(rows[0][0])


async def _manifest_evidence() -> dict[str, Any]:
    import valkey.asyncio as valkey

    uri = os.getenv("FINAL_VALKEY_URI", "redis://127.0.0.1:6380/0")
    client = valkey.from_url(uri, decode_responses=True)
    try:
        manifests: dict[str, Any] = {}
        for asset in EXPECTED_ASSETS:
            symbol = f"{asset}USDT"
            raw = await client.hgetall(f"asset:{symbol}")
            if not raw:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_SIGNAL_RUNTIME",
                    f"missing production manifest for {symbol}",
                )
            if (
                raw.get("source") != "ingestion"
                or str(raw.get("desired_state", "")).upper() != "LIVE"
                or str(raw.get("enabled", "")).lower() not in {"true", "1"}
            ):
                raise FinalCertificationError(
                    "BLOCKED_FINAL_SIGNAL_RUNTIME",
                    f"manifest is not six-asset ingestion LIVE for {symbol}",
                    evidence={"symbol": symbol, "manifest": raw},
                )
            manifests[symbol] = raw
        lifecycle_length = await client.xlen("asset:lifecycle")
        if lifecycle_length <= 0:
            raise FinalCertificationError(
                "BLOCKED_FINAL_SIGNAL_RUNTIME",
                "asset:lifecycle is absent or empty",
            )
        return {"manifests": manifests, "lifecycle_length": int(lifecycle_length)}
    finally:
        await client.aclose()


async def _valkey_inputs_and_outputs(graph: Mapping[str, Any]) -> dict[str, Any]:
    import valkey.asyncio as valkey

    uri = os.getenv("FINAL_VALKEY_URI", "redis://127.0.0.1:6380/0")
    client = valkey.from_url(uri, decode_responses=True)
    try:
        from apps.signal_app.ohlcv_source import (
            OhlcvSourceBinding,
            stream_key_for_binding,
        )
        from libs.common.stream_keys import feature_stream_key, price_update_stream_key

        bindings = graph["bindings"]
        result: dict[str, Any] = {"inputs": {}, "outputs": {}}
        for asset, timeframe in graph["pairs"]:
            binding = OhlcvSourceBinding(asset=asset, **bindings[asset])
            input_key = stream_key_for_binding(binding, timeframe)
            result["inputs"][f"{asset}:{timeframe}"] = input_key
            result["outputs"][f"{asset}:{timeframe}"] = {
                "feature": await _valkey_tail(
                    client, feature_stream_key(asset, timeframe)
                ),
                "price": await _valkey_tail(
                    client, price_update_stream_key(asset, timeframe)
                ),
            }
        return result
    finally:
        await client.aclose()


async def _signal_evidence(
    graph: Mapping[str, Any],
    baseline: Mapping[str, Any],
    startup_ms: int,
) -> dict[str, Any]:
    import valkey.asyncio as valkey

    from apps.signal_app.observability.runtime_state import runtime_status_key
    from libs.common.stream_keys import feature_stream_key, price_update_stream_key

    uri = os.getenv("FINAL_VALKEY_URI", "redis://127.0.0.1:6380/0")
    client = valkey.from_url(uri, decode_responses=True)
    try:
        expected_names = {
            f"{asset}:{timeframe}": f"{graph['consumer_name_prefix']}_{asset}_{timeframe}"
            for asset, timeframe in graph["pairs"]
        }
        deadline = time.monotonic() + 300
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            statuses: dict[str, Any] = {}
            groups: dict[str, Any] = {}
            outputs: dict[str, Any] = {}
            all_ready = True
            for asset, timeframe in graph["pairs"]:
                pair_key = f"{asset}:{timeframe}"
                raw_status = await client.hgetall(runtime_status_key(asset, timeframe))
                state = str(raw_status.get("state", "")).lower()
                last_error = raw_status.get("last_error")
                if not state.endswith("live") or last_error not in (
                    None,
                    "",
                    "__NONE__",
                ):
                    all_ready = False
                statuses[pair_key] = {
                    "state": raw_status.get("state"),
                    "last_error": last_error,
                    "last_feature_ts": raw_status.get("last_feature_ts"),
                }
                input_key = baseline["inputs"][pair_key]
                try:
                    group_rows = await client.xinfo_groups(input_key)
                    group = next(
                        (
                            item
                            for item in group_rows
                            if str(item.get("name")) == graph["consumer_group"]
                        ),
                        None,
                    )
                    if (
                        group is None
                        or int(group.get("pending", 0)) != 0
                        or int(group.get("lag", 0)) != 0
                    ):
                        all_ready = False
                    consumers = (
                        await client.xinfo_consumers(input_key, graph["consumer_group"])
                        if group is not None
                        else []
                    )
                    expected_name = expected_names[pair_key]
                    consumer = next(
                        (
                            item
                            for item in consumers
                            if str(item.get("name")) == expected_name
                        ),
                        None,
                    )
                    if consumer is None:
                        all_ready = False
                    if len(consumers) != 1:
                        all_ready = False
                    groups[pair_key] = {
                        "group": group,
                        "consumers": consumers,
                        "expected_consumer": expected_name,
                    }
                except Exception as exc:  # noqa: BLE001
                    all_ready = False
                    groups[pair_key] = {"error": str(exc)}
                feature = await _valkey_tail(
                    client, feature_stream_key(asset, timeframe)
                )
                price = await _valkey_tail(
                    client, price_update_stream_key(asset, timeframe)
                )
                outputs[pair_key] = {"feature": feature, "price": price}
                for output_name, current in (("feature", feature), ("price", price)):
                    previous = baseline["outputs"][pair_key][output_name]
                    if (
                        current is None
                        or current == previous
                        or int(str(current).split("-", 1)[0]) < startup_ms
                    ):
                        all_ready = False
            last = {"statuses": statuses, "groups": groups, "outputs": outputs}
            if all_ready:
                return _jsonable(last)
            await asyncio.sleep(2)
        raise FinalCertificationError(
            "BLOCKED_FINAL_SIGNAL_RUNTIME",
            "eight signal pairs did not reach fresh LIVE/bootstrap state",
            evidence=last,
        )
    finally:
        await client.aclose()


def _drain_signal_groups_after_n2c(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Drain ingestion signal groups left behind by the isolated N2C runtime gate.

    N2C deliberately runs the temporary ingestion runtime with downstream
    services stopped. A final published ingestion event can therefore remain behind
    an existing signal group even after the transactional outbox is quiescent.
    Consume those already-published entries with the normal signal worker
    before the post-retirement protected-state verification. No group is
    repositioned or reset by this certification-only bridge.
    """
    before = {
        "broker": _service_state("broker"),
        "signal-worker": _service_state("signal-worker"),
    }
    broker_started = False
    signal_started = False
    try:
        if not before["broker"].get("running"):
            broker_start = _compose("up", "-d", "broker")
            if broker_start.returncode != 0:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_SIGNAL_GROUPS",
                    "could not start broker for post-N2C signal-group drain",
                    evidence={
                        "stdout": _tail(broker_start.stdout),
                        "stderr": _tail(broker_start.stderr),
                    },
                )
            broker_started = True
        _wait_until(
            lambda: _service_state("broker").get("health") == "healthy",
            timeout=60,
            description="broker health for post-N2C signal-group drain",
        )

        baseline = asyncio.run(_valkey_inputs_and_outputs(graph))
        startup_ms = int(time.time() * 1000)
        if not before["signal-worker"].get("running"):
            signal_start = _compose("up", "-d", "signal-worker")
            if signal_start.returncode != 0:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_SIGNAL_GROUPS",
                    "could not start signal-worker for post-N2C signal-group drain",
                    evidence={
                        "stdout": _tail(signal_start.stdout),
                        "stderr": _tail(signal_start.stderr),
                    },
                )
            signal_started = True
        signal = asyncio.run(_signal_evidence(graph, baseline, startup_ms))
        return {"proven": True, "before": before, "signal": signal}
    finally:
        if signal_started:
            with contextlib.suppress(Exception):
                _compose("stop", "signal-worker")
        if broker_started:
            with contextlib.suppress(Exception):
                _compose("stop", "broker")


def _steady_state(graph: Mapping[str, Any]) -> dict[str, Any]:
    started = _compose("up", "-d", "db", "broker", "ingestion")
    if started.returncode != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_RUNTIME",
            "could not start final ingestion steady-state services",
            evidence={"stdout": _tail(started.stdout), "stderr": _tail(started.stderr)},
        )
    _wait_ingestion_live()
    _container_namespace_proof()
    initial = asyncio.run(_db_snapshot(graph))
    baseline = asyncio.run(_valkey_inputs_and_outputs(graph))
    startup_ms = int(time.time() * 1000)
    signal_start = _compose("up", "-d", "signal-worker")
    if signal_start.returncode != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_SIGNAL_RUNTIME",
            "could not start final signal-worker",
            evidence={
                "stdout": _tail(signal_start.stdout),
                "stderr": _tail(signal_start.stderr),
            },
        )
    signal = asyncio.run(_signal_evidence(graph, baseline, startup_ms))

    base_duration = 60
    timeout = max(
        180, base_duration * 4 + int(graph["finalization_grace_seconds"]) + 60
    )

    def advanced() -> dict[str, Any] | None:
        snapshot = asyncio.run(_db_snapshot(graph))
        if all(
            snapshot["latest"][asset]["open_time"]
            > initial["latest"][asset]["open_time"]
            for asset in EXPECTED_ASSETS
        ):
            return snapshot
        return None

    final_snapshot = _wait_until(
        advanced,
        timeout=timeout,
        interval=2,
        description="all six base lanes to advance",
    )
    recent = _validate_recent_base(final_snapshot)
    runtime = _wait_ingestion_live()
    if runtime["runtime"].get("last_error") not in (None, "", "__NONE__"):
        raise FinalCertificationError(
            "BLOCKED_FINAL_RUNTIME",
            "ingestion runtime has a final error",
            evidence={"runtime": runtime},
        )
    if final_snapshot["pending_outbox"] != 0:
        raise FinalCertificationError(
            "BLOCKED_FINAL_OUTBOX",
            "outbox is not empty after final six-asset advancement",
            evidence={"pending_outbox": final_snapshot["pending_outbox"]},
        )
    now = datetime.now(UTC)
    freshness_tolerance = (
        60
        + int(graph["finalization_grace_seconds"])
        + max(60, int(graph["reconnect_backoff_seconds"]) * 2)
    )
    freshness: dict[str, Any] = {}
    for asset, row in final_snapshot["latest"].items():
        close_time = row["close_time"]
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=UTC)
        age_seconds = (now - close_time).total_seconds()
        freshness[asset] = {
            "close_time": close_time,
            "age_seconds": age_seconds,
        }
        if age_seconds < 0 or age_seconds > freshness_tolerance:
            raise FinalCertificationError(
                "BLOCKED_FINAL_BASE_CONTINUITY",
                f"latest {asset} 1m candle is outside freshness tolerance",
                evidence={
                    "asset": asset,
                    "age_seconds": age_seconds,
                    "tolerance_seconds": freshness_tolerance,
                },
            )
    if any(
        final_snapshot["latest"][asset]["close_time"]
        > datetime.now(UTC) + timedelta(minutes=2)
        for asset in EXPECTED_ASSETS
    ):
        raise FinalCertificationError(
            "BLOCKED_FINAL_BASE_CONTINUITY",
            "a final base candle is implausibly in the future",
        )
    return {
        "started_at": datetime.fromtimestamp(startup_ms / 1000, UTC).isoformat(),
        "namespace": {"container": "apps.ingestion_app.main", "old_absent": True},
        "runtime": _jsonable(runtime),
        "initial_snapshot": _jsonable(initial),
        "final_snapshot": _jsonable(final_snapshot),
        "base_continuity": recent,
        "freshness": {
            "tolerance_seconds": freshness_tolerance,
            "lanes": _jsonable(freshness),
        },
        "manifests": _jsonable(asyncio.run(_manifest_evidence())),
        "signals": signal,
        "inputs": baseline["inputs"],
        "output_baseline": baseline["outputs"],
        "advancement_timeout_seconds": timeout,
    }


def _stop_final_services(*, best_effort: bool = False) -> dict[str, Any]:
    """Stop FINAL services only after proving producer/publisher quiescence."""
    evidence: dict[str, Any] = {
        "best_effort": best_effort,
        "shutdown_order": [],
        "commands": [],
    }

    def stop_service(service: str) -> None:
        try:
            stopped = _compose("stop", service)
        except Exception as exc:
            if not best_effort:
                raise FinalCertificationError(
                    "BLOCKED_FINAL_RESOURCE_RESTORE",
                    f"failed to stop {service}",
                    evidence={"service": service, "error": repr(exc)},
                ) from exc
            evidence.setdefault("errors", []).append(
                {"service": service, "error": repr(exc)}
            )
            return
        evidence["commands"].append(
            {
                "service": service,
                "return_code": stopped.returncode,
                "stdout": _tail(stopped.stdout),
                "stderr": _tail(stopped.stderr),
            }
        )
        if stopped.returncode != 0 and not best_effort:
            raise FinalCertificationError(
                "BLOCKED_FINAL_RESOURCE_RESTORE",
                f"failed to stop {service}",
                evidence=evidence,
            )

    stop_service("signal-worker")
    evidence["shutdown_order"].append("signal-worker")

    before = {
        "broker": _service_state("broker"),
        "ingestion": _service_state("ingestion"),
    }
    if before["broker"].get("running") and before["ingestion"].get("running"):
        try:
            evidence["quiescence"] = _pause_ingestion_and_wait()
            evidence["shutdown_order"].extend(("runtime_pause", "pending_outbox_zero"))
        except Exception as exc:
            if not best_effort:
                raise
            evidence["quiescence"] = {
                "proven": False,
                "before": before,
                "error": repr(exc),
            }
    elif best_effort:
        evidence["quiescence"] = {
            "proven": False,
            "before": before,
            "skipped": "broker_or_ingestion_unavailable",
        }
    else:
        raise FinalCertificationError(
            "BLOCKED_FINAL_RESOURCE_RESTORE",
            "cannot establish ingestion quiescence while broker or ingestion is unavailable",
            evidence={"before": before},
        )

    stop_service("ingestion")
    evidence["shutdown_order"].append("ingestion")
    stop_service("broker")
    evidence["shutdown_order"].append("broker")

    try:
        states = {
            service: _service_state(service)
            for service in ("broker", "ingestion", "signal-worker", "db")
        }
    except Exception as exc:
        if not best_effort:
            raise FinalCertificationError(
                "BLOCKED_FINAL_RESOURCE_RESTORE",
                "could not inspect final service state",
                evidence={"error": repr(exc)},
            ) from exc
        evidence["errors"] = evidence.get("errors", []) + [
            {"state_inspection": repr(exc)}
        ]
        return evidence

    evidence["states"] = states
    bad = {
        service: state
        for service, state in states.items()
        if service != "db" and state.get("running")
    }
    if (
        bad
        or not states["db"].get("running")
        or states["db"].get("health") not in {"healthy", ""}
    ) and not best_effort:
        raise FinalCertificationError(
            "BLOCKED_FINAL_RESOURCE_RESTORE",
            "final services were not restored to the required state",
            evidence={"states": states, "bad": bad},
        )
    if (
        any(
            states[service].get("exit_code") not in (0, None)
            or states[service].get("oom_killed")
            for service in ("broker", "ingestion", "signal-worker")
        )
        and not best_effort
    ):
        raise FinalCertificationError(
            "BLOCKED_FINAL_RESOURCE_RESTORE",
            "a final service stopped non-cleanly",
            evidence={"states": states},
        )

    try:
        pending = _pending_outbox()
    except Exception as exc:
        if not best_effort:
            raise
        evidence["errors"] = evidence.get("errors", []) + [
            {"pending_outbox": repr(exc)}
        ]
        return evidence
    evidence["pending_outbox"] = pending
    if pending != 0 and not best_effort:
        raise FinalCertificationError(
            "BLOCKED_FINAL_RESOURCE_RESTORE",
            "pending outbox is non-zero after final shutdown",
            evidence={
                "pending_outbox": pending,
                "quiescence": evidence.get("quiescence"),
            },
        )
    return evidence


def _write_artifact(payload: Mapping[str, Any]) -> tuple[str, str]:
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(_jsonable(dict(payload)), indent=2, sort_keys=True) + "\n"
    ARTIFACT_PATH.write_text(rendered)
    read_back = json.loads(ARTIFACT_PATH.read_text())
    required = {"schema_version", "starting_sha", "started_at", "status", "preflight"}
    missing = sorted(required - set(read_back))
    if missing:
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            f"final artifact is missing required fields: {missing}",
        )
    digest = hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest()
    with contextlib.suppress(ValueError):
        return str(ARTIFACT_PATH.relative_to(REPO_ROOT)), digest
    return str(ARTIFACT_PATH), digest


def _starting_sha() -> str:
    result = _run_command(("git", "rev-parse", "HEAD"))
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def run_final(*, execute: bool) -> dict[str, Any]:
    started_at = _now()
    preflight = _capture_preflight()
    base: dict[str, Any] = {
        "schema_version": 1,
        "starting_sha": _starting_sha(),
        "started_at": started_at,
        "preflight": preflight,
        "frozen_contracts": preflight["protocol"],
    }
    if not execute:
        return {**base, "status": DRY_RUN_STATUS, "completed_at": _now()}
    if os.getenv(FINAL_GUARD) != "1":
        raise FinalCertificationError(
            "BLOCKED_FINAL_PREFLIGHT",
            f"--execute requires {FINAL_GUARD}=1",
        )

    evidence = dict(base)
    try:
        graph = preflight["graph"]
        evidence["builds"] = _build_images()
        _phase_gates(evidence)
        evidence["steady_state"] = _steady_state(graph)
        evidence["resource_restore"] = _stop_final_services()
        evidence["completed_at"] = _now()
        evidence["status"] = FINAL_PROGRAM_STATUS
        artifact_path, artifact_sha = _write_artifact(evidence)
        evidence["artifact_path"] = artifact_path
        evidence["artifact_sha256"] = artifact_sha
        return evidence
    except FinalCertificationError as exc:
        evidence["completed_at"] = _now()
        evidence["status"] = exc.status
        evidence["failure"] = {"message": str(exc), "evidence": exc.evidence}
        with contextlib.suppress(Exception):
            evidence["resource_restore"] = _stop_final_services(best_effort=True)
        with contextlib.suppress(Exception):
            evidence["artifact_path"], evidence["artifact_sha256"] = _write_artifact(
                evidence
            )
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        evidence["completed_at"] = _now()
        evidence["status"] = "BLOCKED_FINAL_PREFLIGHT"
        evidence["failure"] = {"message": str(exc)}
        with contextlib.suppress(Exception):
            evidence["resource_restore"] = _stop_final_services()
        with contextlib.suppress(Exception):
            evidence["artifact_path"], evidence["artifact_sha256"] = _write_artifact(
                evidence
            )
        raise FinalCertificationError("BLOCKED_FINAL_PREFLIGHT", str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_final(execute=args.execute)
    except FinalCertificationError as exc:
        result = {
            "status": exc.status,
            "message": str(exc),
            "evidence": exc.evidence,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
