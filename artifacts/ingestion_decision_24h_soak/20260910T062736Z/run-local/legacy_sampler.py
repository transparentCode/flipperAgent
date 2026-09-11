#!/usr/bin/env python3
"""Disposable full-system soak harness.

This file is intentionally run-local evidence tooling. It does not modify
flipperAgent source or production configuration. All Docker commands are
scoped to one explicit Compose project and the three approved MCP containers
are observed by immutable container identity only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.server
import json
import math
import os
import re
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SERVICES = (
    "db",
    "broker",
    "ingestion",
    "scheduler",
    "risk-worker",
    "execution-worker",
    "alert-worker",
    "alert-api",
    "portfolio-worker",
    "scraper-tradingview",
    "scraper-service",
    "api-server",
    "decision",
    "otel-collector",
    "prometheus",
    "grafana",
)

HEALTH_URLS = {
    "ingestion": "http://127.0.0.1:8003/health/ready",
    "decision": "http://127.0.0.1:8004/health/ready",
    "api-server": "http://127.0.0.1:8080/health",
    "alert-api": "http://127.0.0.1:8096/alerts/health",
    "scraper-service": "http://127.0.0.1:8081/health",
    "prometheus": "http://127.0.0.1:9090/-/healthy",
    "otel-collector": "http://127.0.0.1:13133",
    "grafana": "http://127.0.0.1:3001/api/health",
}

PIPELINE_URLS = {
    "ingestion_runtime": "http://127.0.0.1:8003/runtime",
    "ingestion_assets": "http://127.0.0.1:8003/assets",
    "decision_runtime": "http://127.0.0.1:8004/runtime",
    "decision_lanes": "http://127.0.0.1:8004/runtime/lanes",
    "decision_inputs": "http://127.0.0.1:8004/runtime/inputs",
    "risk_health": "http://127.0.0.1:8080/risk/health",
    "risk_summary": "http://127.0.0.1:8080/risk/summary",
    "risk_status": "http://127.0.0.1:8080/risk/status",
    "execution_summary": "http://127.0.0.1:8080/execution/summary",
    "execution_status": "http://127.0.0.1:8080/execution/status",
    "portfolio_health": "http://127.0.0.1:8080/portfolio/health",
    "portfolio_summary": "http://127.0.0.1:8080/portfolio/summary",
    "alert_summary": "http://127.0.0.1:8096/alerts/summary",
    "alert_incidents": "http://127.0.0.1:8096/alerts/incidents?limit=50",
}

LOAD_URLS = (
    ("ingestion_ready", HEALTH_URLS["ingestion"]),
    ("ingestion_runtime", PIPELINE_URLS["ingestion_runtime"]),
    ("ingestion_assets", PIPELINE_URLS["ingestion_assets"]),
    ("decision_ready", HEALTH_URLS["decision"]),
    ("decision_runtime", PIPELINE_URLS["decision_runtime"]),
    ("decision_lanes", PIPELINE_URLS["decision_lanes"]),
    ("decision_inputs", PIPELINE_URLS["decision_inputs"]),
    ("api_health", HEALTH_URLS["api-server"]),
    ("risk_health", PIPELINE_URLS["risk_health"]),
    ("risk_summary", PIPELINE_URLS["risk_summary"]),
    ("risk_status", PIPELINE_URLS["risk_status"]),
    ("execution_summary", PIPELINE_URLS["execution_summary"]),
    ("execution_status", PIPELINE_URLS["execution_status"]),
    ("portfolio_health", PIPELINE_URLS["portfolio_health"]),
    ("portfolio_summary", PIPELINE_URLS["portfolio_summary"]),
    ("alert_health", HEALTH_URLS["alert-api"]),
    ("alert_summary", PIPELINE_URLS["alert_summary"]),
    ("alert_incidents", PIPELINE_URLS["alert_incidents"]),
    ("scraper_health", HEALTH_URLS["scraper-service"]),
)

SERVICE_INSPECT_TEMPLATE = (
    "{{.Id}}|{{.Name}}|"
    '{{index .Config.Labels "com.docker.compose.service"}}|'
    "{{.State.Status}}|"
    '{{if (index .State "Health")}}{{(index .State "Health").Status}}{{else}}none{{end}}|'
    "{{.State.OOMKilled}}|{{.RestartCount}}|{{.State.ExitCode}}|"
    "{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|{{.State.StartedAt}}"
)

SECRET_PATTERN = re.compile(r"(?i)(bearer\s+|sk-)[A-Za-z0-9._~+/=-]{8,}")
UNIT_MULTIPLIERS = {
    "b": 1,
    "kb": 1000,
    "kib": 1024,
    "mb": 1000**2,
    "mib": 1024**2,
    "gb": 1000**3,
    "gib": 1024**3,
    "tb": 1000**4,
    "tib": 1024**4,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def redact(value: str) -> str:
    return SECRET_PATTERN.sub("[REDACTED]", value)


def parse_number(value: str) -> float | None:
    try:
        return float(value.strip().rstrip("%"))
    except (AttributeError, TypeError, ValueError):
        return None


def parse_bytes(value: str) -> int | None:
    if not value:
        return None
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)?", value)
    if not match:
        return None
    unit = (match.group(2) or "b").lower()
    multiplier = UNIT_MULTIPLIERS.get(unit)
    if multiplier is None:
        return None
    return int(float(match.group(1)) * multiplier)


def parse_io_pair(value: str) -> dict[str, int | None]:
    parts = re.split(r"\s*/\s*", value.strip())
    if len(parts) != 2:
        return {"read_or_rx_bytes": None, "write_or_tx_bytes": None}
    return {
        "read_or_rx_bytes": parse_bytes(parts[0]),
        "write_or_tx_bytes": parse_bytes(parts[1]),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def parse_json_or_text(body: bytes) -> Any:
    text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:2000]


def http_get(url: str, timeout: float = 5.0) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(256 * 1024)
            return {
                "status_code": response.status,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "payload": parse_json_or_text(body),
                "error": None,
            }

    except urllib.error.HTTPError as exc:
        body = exc.read(32 * 1024)
        return {
            "status_code": exc.code,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "payload": parse_json_or_text(body),
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001 - probe must survive service faults
        return {
            "status_code": None,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "payload": None,
            "error": type(exc).__name__,
        }


class StatusHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return


class Soak:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = Path(args.worktree).resolve()
        self.run_dir = Path(args.run_dir).resolve()
        self.samples = self.run_dir / "samples"
        self.live = self.run_dir / "live"
        self.events_path = self.run_dir / "events.jsonl"
        self.state_path = self.run_dir / "RUN_STATE.json"
        self.stop_event = threading.Event()
        self.phase = "preflight"
        self.last_health: dict[str, Any] = {}
        self.last_pipeline: dict[str, Any] = {}
        self.last_db_valkey: dict[str, Any] = {}
        self.last_resource: dict[str, Any] = {}
        self.last_cotenant: dict[str, Any] = {}
        self.last_sample_at = 0.0
        self.last_health_at = 0.0
        self.last_pipeline_at = 0.0
        self.last_log_at = 0.0
        self.last_storage_at = 0.0
        self.last_sample_completed_at: float | None = None
        self.last_state_checkpoint = 0.0
        self.measurement_started_monotonic: float | None = None
        self.warmup_stable_since: float | None = None
        self.hard_failure = False
        self.correctness_failure = False
        self.warnings: list[str] = []
        self.cotenant_baseline: dict[str, dict[str, Any]] = {}
        self.load = LoadDriver(self)
        self.status_server: http.server.ThreadingHTTPServer | None = None
        self.status_thread: threading.Thread | None = None
        self.alert_overlay = (self.root / self.args.override_file).with_name(
            "alerts-soak.yaml"
        )

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.samples.mkdir(parents=True, exist_ok=True)
        self.live.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.phase = str(self.state.get("phase", "preflight"))
        else:
            self.state = {
                "run_id": self.run_dir.name,
                "phase": self.phase,
                "source_sha": args.source_sha,
                "project": args.project,
                "harness_pid": os.getpid(),
                "created_at": utc_now(),
                "validity": True,
                "measurement_seconds_required": args.measurement_seconds,
                "warmup_seconds_required": args.warmup_seconds,
                "measurement_elapsed_seconds": 0.0,
                "ports": {
                    "status": args.status_port,
                    "prometheus": 9090,
                    "otel_health": 13133,
                },
                "anomalies": [],
            }
        self._write_state()

    def _write_state(self) -> None:
        self.state["phase"] = self.phase
        self.state["last_update_at"] = utc_now()
        self.state["harness_pid"] = os.getpid()
        atomic_json(self.state_path, self.state)

    def event(self, kind: str, *, anomaly: bool = False, **data: Any) -> None:
        payload = {"timestamp": utc_now(), "kind": kind, **data}
        append_jsonl(self.events_path, payload)
        if anomaly:
            self.state.setdefault("anomalies", []).append(payload)
            self.warnings.append(kind)
            self._write_state()

    def command(
        self, command: list[str], timeout: float = 30.0
    ) -> tuple[int, str, str]:
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        return (
            result.returncode,
            redact(result.stdout.strip()),
            redact(result.stderr.strip()),
        )

    def compose(self, *arguments: str, timeout: float = 30.0) -> tuple[int, str, str]:
        return self.command(
            [
                "docker",
                "compose",
                "-p",
                self.args.project,
                "-f",
                str(self.root / "docker-compose.yml"),
                "-f",
                str(self.root / self.args.override_file),
                "--profile",
                "prod",
                *arguments,
            ],
            timeout=timeout,
        )

    def docker(self, *arguments: str, timeout: float = 30.0) -> tuple[int, str, str]:
        return self.command(["docker", *arguments], timeout=timeout)

    def inspect_container(self, name_or_id: str) -> dict[str, Any] | None:
        code, output, _ = self.docker(
            "inspect", "-f", SERVICE_INSPECT_TEMPLATE, name_or_id
        )
        if code != 0 or not output:
            return None
        fields = output.split("|")
        if len(fields) != 11:
            return None
        return {
            "id": fields[0],
            "name": fields[1].lstrip("/"),
            "service": fields[2],
            "state": fields[3],
            "health": fields[4],
            "oom_killed": fields[5].lower() == "true",
            "restart_count": int(fields[6] or 0),
            "exit_code": int(fields[7] or 0),
            "memory_limit_bytes": int(fields[8] or 0),
            "nano_cpus": int(fields[9] or 0),
            "started_at": fields[10],
        }

    def service_containers(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for service in SERVICES:
            code, output, _ = self.compose("ps", "-q", service)
            container_id = (
                output.splitlines()[-1].strip() if code == 0 and output else ""
            )
            if container_id:
                record = self.inspect_container(container_id)
                if record:
                    records[service] = record
        return records

    def cotenant_containers(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for name in self.args.cotenant:
            record = self.inspect_container(name)
            if record:
                records[name] = record
        return records

    def stats(self, records: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not records:
            return {}
        code, output, error = self.docker(
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *[record["id"] for record in records.values()],
            timeout=30,
        )
        if code != 0:
            self.event("docker_stats_error", anomaly=True, error=error[:300])
            return {}
        by_name: dict[str, dict[str, Any]] = {}
        for line in output.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = str(payload.get("Name", ""))
            by_name[name] = {
                "memory_usage_bytes": parse_bytes(
                    str(payload.get("MemUsage", "")).split(" / ")[0]
                ),
                "memory_percent": parse_number(str(payload.get("MemPerc", ""))),
                "cpu_percent": parse_number(str(payload.get("CPUPerc", ""))),
                "pids": int(parse_number(str(payload.get("PIDs", "0"))) or 0),
                "network_io": parse_io_pair(str(payload.get("NetIO", ""))),
                "block_io": parse_io_pair(str(payload.get("BlockIO", ""))),
                "memory_text": payload.get("MemUsage"),
            }
        merged: dict[str, dict[str, Any]] = {}
        for key, record in records.items():
            sample = by_name.get(record["name"], {})
            merged[key] = {**record, **sample}
        return merged

    def resource_sample(self) -> dict[str, Any]:
        sut_records = self.service_containers()
        cotenant_records = self.cotenant_containers()
        sut = self.stats(sut_records)
        cotenants = self.stats(cotenant_records)
        for name, baseline in self.cotenant_baseline.items():
            current = cotenant_records.get(name)
            if not current or current["id"] != baseline["id"]:
                self.event(
                    "cotenant_identity_change",
                    anomaly=True,
                    name=name,
                    expected_id=baseline["id"],
                    observed_id=current["id"] if current else None,
                )
            elif current["restart_count"] != baseline["restart_count"]:
                self.event(
                    "cotenant_restart_change",
                    anomaly=True,
                    name=name,
                    baseline=baseline["restart_count"],
                    observed=current["restart_count"],
                )
            elif current["oom_killed"] and not baseline["oom_killed"]:
                self.event("cotenant_oom_killed", anomaly=True, name=name)
        if self.phase in {"warmup", "measurement"}:
            baseline_key = (
                "warmup_sut_restart_baseline"
                if self.phase == "warmup"
                else "sut_restart_baseline"
            )
            restart_baseline = self.state.get(baseline_key, {})
            for service, record in sut.items():
                baseline = restart_baseline.get(service)
                if baseline is not None and record["restart_count"] != baseline:
                    self.hard_failure = True
                    self.event(
                        "sut_restart_during_measurement",
                        anomaly=True,
                        service=service,
                        baseline=baseline,
                        observed=record["restart_count"],
                    )
                if record.get("oom_killed"):
                    self.hard_failure = True
                    self.event("sut_oom_killed", anomaly=True, service=service)

        def aggregate(values: dict[str, dict[str, Any]]) -> dict[str, Any]:
            memories = [
                int(item["memory_usage_bytes"])
                for item in values.values()
                if item.get("memory_usage_bytes") is not None
            ]
            cpus = [
                float(item["cpu_percent"])
                for item in values.values()
                if item.get("cpu_percent") is not None
            ]
            return {
                "rss_bytes": sum(memories),
                "cpu_percent_sum": round(sum(cpus), 3),
                "cpu_core_equivalent": round(sum(cpus) / 100.0, 4),
                "container_count": len(values),
            }

        sample = {
            "timestamp": utc_now(),
            "phase": self.phase,
            "sut": sut,
            "approved_cotenant": cotenants,
            "sut_aggregate": aggregate(sut),
            "vm_container_aggregate": aggregate({**sut, **cotenants}),
        }
        append_jsonl(self.samples / "resource_samples.jsonl", sample)
        append_jsonl(
            self.samples / "cotenant_resource_samples.jsonl",
            {"timestamp": sample["timestamp"], **cotenants},
        )
        append_jsonl(
            self.samples / "container_state.jsonl",
            {
                "timestamp": sample["timestamp"],
                "sut": {
                    key: {
                        name: value
                        for name, value in record.items()
                        if name
                        in {
                            "id",
                            "state",
                            "health",
                            "oom_killed",
                            "restart_count",
                            "exit_code",
                            "started_at",
                        }
                    }
                    for key, record in sut.items()
                },
                "approved_cotenant": {
                    key: {
                        name: value
                        for name, value in record.items()
                        if name
                        in {
                            "id",
                            "state",
                            "health",
                            "oom_killed",
                            "restart_count",
                            "exit_code",
                            "started_at",
                        }
                    }
                    for key, record in cotenants.items()
                },
            },
        )
        self.last_resource = sample
        self.last_cotenant = cotenants
        return sample

    def health_sample(self) -> dict[str, Any]:
        payload = {name: http_get(url, timeout=5) for name, url in HEALTH_URLS.items()}
        sample = {"timestamp": utc_now(), "phase": self.phase, "checks": payload}
        append_jsonl(self.samples / "http_health.jsonl", sample)
        self.last_health = sample
        return sample

    def pipeline_sample(self) -> dict[str, Any]:
        payload = {
            name: http_get(url, timeout=5) for name, url in PIPELINE_URLS.items()
        }
        db = self.db_probe()
        valkey = self.valkey_probe()
        sample = {
            "timestamp": utc_now(),
            "phase": self.phase,
            "http": payload,
            "db": db,
            "valkey": valkey,
        }
        append_jsonl(
            self.samples / "pipeline_metrics.jsonl",
            {"timestamp": sample["timestamp"], "http": payload},
        )
        append_jsonl(
            self.samples / "db_valkey.jsonl",
            {"timestamp": sample["timestamp"], "db": db, "valkey": valkey},
        )
        self.last_pipeline = sample
        self.last_db_valkey = {"db": db, "valkey": valkey}
        return sample

    def db_probe(self) -> dict[str, Any]:
        user = load_env_value(self.root / ".env", "POSTGRES_USER") or "flipper"
        database = load_env_value(self.root / ".env", "POSTGRES_DB") or "flipper_db"
        query = (
            "SELECT json_build_object("
            "'outbox_pending',(SELECT count(*) FROM ingestion.outbox WHERE published_at IS NULL),"
            "'outbox_oldest_epoch',(SELECT extract(epoch FROM min(created_at)) FROM ingestion.outbox WHERE published_at IS NULL),"
            "'connections',(SELECT count(*) FROM pg_stat_activity),"
            "'active_connections',(SELECT count(*) FROM pg_stat_activity WHERE state='active'),"
            "'long_transactions',(SELECT count(*) FROM pg_stat_activity WHERE now()-xact_start > interval '30 seconds'),"
            "'db_size_bytes',pg_database_size(current_database()))::text"
        )
        code, output, error = self.compose(
            "exec",
            "-T",
            "db",
            "psql",
            "-X",
            "-A",
            "-t",
            "-U",
            user,
            "-d",
            database,
            "-c",
            query,
            timeout=15,
        )
        if code != 0 or not output:
            return {"error": error[:400] or "db_probe_failed"}
        try:
            return json.loads(output.splitlines()[-1])
        except json.JSONDecodeError:
            return {"error": "db_probe_invalid_json"}

    def valkey_probe(self) -> dict[str, Any]:
        code, info, error = self.compose(
            "exec", "-T", "broker", "valkey-cli", "--raw", "INFO", timeout=15
        )
        if code != 0:
            return {"error": error[:400] or "valkey_probe_failed"}
        result: dict[str, Any] = {}
        for line in info.splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            if key in {
                "used_memory",
                "used_memory_rss",
                "used_memory_peak",
                "connected_clients",
                "blocked_clients",
                "instantaneous_ops_per_sec",
                "rejected_connections",
            }:
                result[key] = (
                    parse_number(value)
                    if value.replace(".", "", 1).isdigit()
                    else value
                )
        code, keys, _ = self.compose(
            "exec", "-T", "broker", "valkey-cli", "--raw", "--scan", timeout=20
        )
        stream_lengths: dict[str, int] = {}
        if code == 0:
            for key in keys.splitlines()[:300]:
                if not any(
                    key.startswith(prefix)
                    for prefix in (
                        "stream:",
                        "orders:",
                        "fills:",
                        "execution:",
                        "price_update:",
                    )
                ):
                    continue
                xcode, length, _ = self.compose(
                    "exec",
                    "-T",
                    "broker",
                    "valkey-cli",
                    "--raw",
                    "XLEN",
                    key,
                    timeout=10,
                )
                if xcode == 0 and length.strip().isdigit():
                    stream_lengths[key] = int(length.strip())
        result["stream_count"] = len(stream_lengths)
        result["stream_lengths"] = stream_lengths
        return result

    def log_sample(self) -> None:
        code, output, error = self.compose(
            "logs", "--no-color", "--since", "5m", timeout=45
        )
        text = output if code == 0 else error
        lines = text.splitlines()
        warnings = sum(
            1 for line in lines if re.search(r"\bWARN(?:ING)?\b", line, re.IGNORECASE)
        )
        errors = sum(
            1
            for line in lines
            if re.search(r"\bERROR\b|Traceback|Exception", line, re.IGNORECASE)
        )
        sample = {
            "timestamp": utc_now(),
            "phase": self.phase,
            "warning_lines": warnings,
            "error_lines": errors,
            "line_count": len(lines),
            "recent_error_samples": [
                redact(line[:500])
                for line in lines
                if re.search(r"\bERROR\b|Traceback|Exception", line, re.IGNORECASE)
            ][-10:],
        }
        append_jsonl(self.samples / "logs_summary.jsonl", sample)

    def storage_sample(self) -> None:
        code, output, error = self.docker(
            "system", "df", "--format", "{{json .}}", timeout=30
        )
        payload: list[Any] = []
        if code == 0:
            for line in output.splitlines():
                try:
                    payload.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        append_jsonl(
            self.samples / "storage_growth.jsonl",
            {
                "timestamp": utc_now(),
                "project": self.args.project,
                "docker_system_df": payload,
                "phase": self.phase,
                "error": error if code else None,
            },
        )

    def measurement_elapsed(self) -> float:
        if self.measurement_started_monotonic is not None:
            return max(0.0, time.monotonic() - self.measurement_started_monotonic)
        return max(0.0, float(self.state.get("measurement_elapsed_seconds", 0.0)))

    def write_status(self) -> None:
        elapsed = self.measurement_elapsed()
        remaining = (
            max(0.0, self.args.measurement_seconds - elapsed)
            if self.state.get("measurement_start_at")
            else None
        )
        status = {
            "run_id": self.run_dir.name,
            "phase": self.phase,
            "elapsed_seconds": round(elapsed, 3),
            "remaining_seconds": round(remaining, 3) if remaining is not None else None,
            "measurement_start_at": self.state.get("measurement_start_at"),
            "measurement_end_at": self.state.get("measurement_end_at"),
            "resource": self.last_resource,
            "cotenants": self.last_cotenant,
            "health": self.last_health,
            "pipeline": self.last_pipeline,
            "state_valid": self.state.get("validity", True),
            "hard_failure": self.hard_failure,
            "correctness_failure": self.correctness_failure,
            "latest_anomalies": self.state.get("anomalies", [])[-10:],
        }
        atomic_json(self.live / "status.json", status)
        html = """<!doctype html><meta charset=utf-8><title>flipperAgent soak</title>
<style>body{font:14px ui-monospace,monospace;background:#111;color:#eee;padding:1rem}pre{white-space:pre-wrap}</style>
<h1>flipperAgent full-system soak</h1><pre id=x>loading</pre>
<script>async function r(){let x=await fetch('status.json?'+Date.now());document.querySelector('#x').textContent=JSON.stringify(await x.json(),null,2)}r();setInterval(r,5000)</script>"""
        (self.live / "status.html").write_text(html, encoding="utf-8")

    def start_status_server(self) -> None:
        handler = lambda *args, **kwargs: StatusHandler(
            *args, directory=str(self.live), **kwargs
        )
        self.status_server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", self.args.status_port), handler
        )
        self.status_thread = threading.Thread(
            target=self.status_server.serve_forever, daemon=True
        )
        self.status_thread.start()
        self.event(
            "status_server_started",
            url=f"http://127.0.0.1:{self.args.status_port}/status.html",
        )

    def sample(self, force: bool = False) -> None:
        started = time.monotonic()
        if self.last_sample_completed_at is not None:
            gap_seconds = started - self.last_sample_completed_at
            if gap_seconds > 60:
                self.event(
                    "sampler_gap_over_60_seconds",
                    anomaly=True,
                    gap_seconds=round(gap_seconds, 3),
                )
        now = started
        resource_sampled = False
        if force or now - self.last_sample_at >= 15:
            self.resource_sample()
            self.last_sample_at = now
            resource_sampled = True
        health_sampled = False
        if force or now - self.last_health_at >= 30:
            self.health_sample()
            self.last_health_at = now
            health_sampled = True
        pipeline_sampled = False
        if force or now - self.last_pipeline_at >= 60:
            self.pipeline_sample()
            self.last_pipeline_at = now
            pipeline_sampled = True
        log_sampled = False
        if force or now - self.last_log_at >= 300:
            self.log_sample()
            self.last_log_at = now
            log_sampled = True
        storage_sampled = False
        if force or now - self.last_storage_at >= 600:
            self.storage_sample()
            self.last_storage_at = now
            storage_sampled = True
        completed = time.monotonic()
        append_jsonl(
            self.samples / "sampler_timing.jsonl",
            {
                "timestamp": utc_now(),
                "phase": self.phase,
                "duration_ms": round((completed - started) * 1000, 3),
                "resource_sampled": resource_sampled,
                "health_sampled": health_sampled,
                "pipeline_sampled": pipeline_sampled,
                "log_sampled": log_sampled,
                "storage_sampled": storage_sampled,
            },
        )
        self.last_sample_completed_at = completed
        if self.state.get("measurement_start_at"):
            self.state["measurement_elapsed_seconds"] = round(
                self.measurement_elapsed(), 3
            )
            if completed - self.last_state_checkpoint >= 60:
                self.last_state_checkpoint = completed
                self._write_state()
        self.write_status()

    def discover_ports(self) -> dict[str, Any]:
        port_targets = {
            "ingestion": 8003,
            "decision": 8004,
            "api-server": 8080,
            "alert-api": 8096,
            "scraper-service": 8081,
            "broker": 6379,
            "db": 5432,
            "prometheus": 9090,
            "otel_health": 13133,
            "grafana": 3000,
        }
        ports: dict[str, Any] = {"status": self.args.status_port}
        for service, container_port in port_targets.items():
            if service == "otel_health":
                service_name = "otel-collector"
            else:
                service_name = service
            code, output, error = self.compose(
                "port", service_name, str(container_port), timeout=15
            )
            if code == 0 and output:
                ports[service] = output.splitlines()[-1].strip()
            else:
                ports[service] = {"error": error[:200] or "not_published"}
        return ports

    def host_environment(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for label, command in (
            ("power", ["pmset", "-g", "batt"]),
            ("memory_pressure", ["vm_stat"]),
            ("disk", ["df", "-k", str(self.run_dir)]),
        ):
            code, output, error = self.command(command, timeout=15)
            snapshot[label] = {
                "exit_code": code,
                "output": output[-4000:],
                "error": error[-1000:] if error else None,
            }
        try:
            snapshot["load_average"] = list(os.getloadavg())
        except OSError as exc:
            snapshot["load_average"] = {"error": type(exc).__name__}
        return snapshot

    def docker_environment(self) -> dict[str, Any]:
        code, output, error = self.docker("info", "--format", "{{json .}}", timeout=30)
        if code != 0:
            raise RuntimeError(f"docker info failed: {error[:300]}")
        try:
            raw = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError("docker info returned invalid JSON") from exc
        return {
            "server_version": raw.get("ServerVersion"),
            "operating_system": raw.get("OperatingSystem"),
            "architecture": raw.get("Architecture"),
            "ncpu": raw.get("NCPU"),
            "mem_total_bytes": raw.get("MemTotal"),
            "name": raw.get("Name"),
        }

    def preflight(self) -> None:
        self.phase = "preflight"
        code, head, error = self.command(["git", "rev-parse", "HEAD"])
        if code != 0 or head != self.args.source_sha:
            self.state["validity"] = False
            self.event(
                "source_sha_mismatch",
                anomaly=True,
                expected=self.args.source_sha,
                observed=head or error[:200],
            )
            raise RuntimeError("worktree HEAD does not match frozen source SHA")
        self.state["docker_environment"] = self.docker_environment()
        ncpu = int(self.state["docker_environment"].get("ncpu") or 0)
        mem_total = int(self.state["docker_environment"].get("mem_total_bytes") or 0)
        if ncpu != 4 or mem_total < 7 * 1024**3:
            self.state["validity"] = False
            self.event(
                "docker_envelope_mismatch",
                anomaly=True,
                expected_ncpu=4,
                observed_ncpu=ncpu,
                minimum_mem_total_bytes=7 * 1024**3,
                observed_mem_total_bytes=mem_total,
            )
            raise RuntimeError(
                "Docker VM does not meet the approved 4-core/8-GB envelope"
            )
        self.state["host_environment"] = self.host_environment()
        self.state["source_sha"] = self.args.source_sha
        self.state["config_hashes"] = {
            name: sha256_file(self.root / name)
            for name in (
                "docker-compose.yml",
                "configs/execution.yaml",
                "configs/alerts.yaml",
            )
        }
        self.state["run_local_hashes"] = {
            name: sha256_file(self.root / name)
            for name in (
                self.args.override_file,
                str(self.alert_overlay.relative_to(self.root)),
            )
        }
        execution = (self.root / "configs/execution.yaml").read_text(encoding="utf-8")
        if not re.search(r"(?m)^\s*mode:\s*paper\s*(?:#.*)?$", execution):
            self.correctness_failure = True
            self.state["validity"] = False
            self.event("execution_mode_not_paper", anomaly=True)
            raise RuntimeError("execution mode is not paper")
        sut_records = self.service_containers()
        missing_services = sorted(set(SERVICES) - set(sut_records))
        unhealthy_services = sorted(
            service
            for service, record in sut_records.items()
            if record["state"] != "running"
            or record["health"] not in {"none", "healthy"}
        )
        if missing_services or unhealthy_services:
            self.state["validity"] = False
            self.event(
                "sut_topology_not_ready",
                anomaly=True,
                missing_services=missing_services,
                unhealthy_services=unhealthy_services,
            )
            raise RuntimeError("SUT topology is not fully running and healthy")
        for name in self.args.cotenant:
            record = self.inspect_container(name)
            if not record:
                self.state["validity"] = False
                self.event("cotenant_missing_before_start", anomaly=True, name=name)
                raise RuntimeError(f"approved co-tenant is missing: {name}")
            self.cotenant_baseline[name] = {
                "id": record["id"],
                "started_at": record["started_at"],
                "restart_count": record["restart_count"],
                "oom_killed": record["oom_killed"],
            }
        self.state["cotenant_baseline"] = self.cotenant_baseline
        self.state["sut_restart_baseline"] = {
            service: record["restart_count"] for service, record in sut_records.items()
        }
        self.state["warmup_sut_restart_baseline"] = dict(
            self.state["sut_restart_baseline"]
        )
        self.state["sut_container_baseline"] = sut_records
        self.state["ports"] = self.discover_ports()
        self.state["preflight_at"] = utc_now()
        atomic_json(
            self.run_dir / "manifest.json",
            {
                "run_id": self.run_dir.name,
                "created_at": self.state["created_at"],
                "worktree": str(self.root),
                "source_sha": self.args.source_sha,
                "compose_project": self.args.project,
                "compose_files": [
                    str(self.root / "docker-compose.yml"),
                    str(self.root / self.args.override_file),
                ],
                "config_hashes": self.state["config_hashes"],
                "run_local_hashes": self.state["run_local_hashes"],
                "docker_environment": self.state["docker_environment"],
                "host_environment": self.state["host_environment"],
                "ports": self.state["ports"],
                "sut_services": list(SERVICES),
                "sut_container_baseline": sut_records,
                "approved_cotenant_baseline": self.cotenant_baseline,
                "measurement_seconds_required": self.args.measurement_seconds,
                "warmup_seconds_required": self.args.warmup_seconds,
            },
        )
        self._write_state()
        self.event(
            "preflight_passed", service_count=len(self.state["sut_restart_baseline"])
        )

    def app_gate(self) -> tuple[bool, dict[str, Any]]:
        ingestion = http_get(PIPELINE_URLS["ingestion_runtime"], timeout=5).get(
            "payload"
        )
        decision = http_get(PIPELINE_URLS["decision_runtime"], timeout=5).get("payload")
        lanes = http_get(PIPELINE_URLS["decision_lanes"], timeout=5).get("payload")
        inputs = http_get(PIPELINE_URLS["decision_inputs"], timeout=5).get("payload")
        db = self.db_probe()
        sut_records = self.service_containers()
        health_ok = all(
            check.get("status_code") == 200
            for check in self.last_health.get("checks", {}).values()
        )
        active = (
            int((lanes or {}).get("active_lane_count", 0) or 0)
            if isinstance(lanes, dict)
            else 0
        )
        configured = (
            int((decision or {}).get("configured_lane_count", 0) or 0)
            if isinstance(decision, dict)
            else 0
        )
        blocked = (
            int((inputs or {}).get("blocked_stream_count", 0) or 0)
            if isinstance(inputs, dict)
            else 0
        )
        ingestion_state = (
            str((ingestion or {}).get("state", "")).lower()
            if isinstance(ingestion, dict)
            else ""
        )
        decision_state = (
            str((decision or {}).get("service_state", "")).upper()
            if isinstance(decision, dict)
            else ""
        )
        outbox_pending = (
            int(db.get("outbox_pending", -1))
            if isinstance(db, dict)
            and str(db.get("outbox_pending", "")).lstrip("-").isdigit()
            else -1
        )
        lane_values = (lanes or {}).get("lanes", {}) if isinstance(lanes, dict) else {}
        lane_statuses = (
            {
                str(lane_id): str(value.get("status"))
                for lane_id, value in lane_values.items()
                if isinstance(value, dict)
            }
            if isinstance(lane_values, dict)
            else {}
        )
        canonical_conflicts = sum(
            1
            for value in (
                (inputs or {}).get("inputs", {}) if isinstance(inputs, dict) else {}
            ).values()
            if isinstance(value, dict)
            and "conflict" in str(value.get("blocked_reason", "")).lower()
        )
        docker_health_ok = len(sut_records) == len(SERVICES) and all(
            record["state"] == "running" and record["health"] in {"none", "healthy"}
            for record in sut_records.values()
        )
        consumer_checks = {
            "risk_health": self.last_pipeline.get("http", {}).get("risk_health", {}),
            "execution_status": self.last_pipeline.get("http", {}).get(
                "execution_status", {}
            ),
            "portfolio_health": self.last_pipeline.get("http", {}).get(
                "portfolio_health", {}
            ),
        }
        consumers_ok = all(
            check.get("status_code") == 200 for check in consumer_checks.values()
        )
        detail = {
            "health_ok": health_ok,
            "docker_health_ok": docker_health_ok,
            "ingestion_state": ingestion_state,
            "decision_state": decision_state,
            "active_lane_count": active,
            "configured_lane_count": configured,
            "lane_statuses": lane_statuses,
            "all_lanes_live": len(lane_statuses) == configured
            and all(status == "LIVE" for status in lane_statuses.values()),
            "blocked_stream_count": blocked,
            "canonical_conflict_count": canonical_conflicts,
            "outbox_pending": outbox_pending,
            "consumers_ok": consumers_ok,
            "consumer_checks": consumer_checks,
        }
        ready = (
            health_ok
            and docker_health_ok
            and ingestion_state in {"live", "running"}
            and decision_state == "RUNNING"
            and configured > 0
            and active == configured
            and len(lane_statuses) == configured
            and all(status == "LIVE" for status in lane_statuses.values())
            and blocked == 0
            and canonical_conflicts == 0
            and outbox_pending == 0
            and consumers_ok
        )
        return ready, detail

    def start_load(self) -> None:
        if not self.load.thread:
            self.load.start()

    def warmup(self) -> None:
        self.phase = "warmup"
        self.state["warmup_started_at"] = self.state.get("warmup_started_at", utc_now())
        self._write_state()
        self.start_load()
        deadline = time.monotonic() + self.args.preparation_timeout_seconds
        first_sample = True
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self.sample(force=first_sample)
            first_sample = False
            ready, detail = self.app_gate()
            append_jsonl(
                self.samples / "warmup_gate.jsonl",
                {"timestamp": utc_now(), **detail, "ready": ready},
            )
            if ready:
                if self.warmup_stable_since is None:
                    self.warmup_stable_since = time.monotonic()
                    self.event("warmup_gate_first_satisfied", **detail)
                elif (
                    time.monotonic() - self.warmup_stable_since
                    >= self.args.warmup_seconds
                ):
                    self.event(
                        "warmup_gate_stable",
                        stable_seconds=self.args.warmup_seconds,
                        **detail,
                    )
                    return
            else:
                if self.warmup_stable_since is not None:
                    self.event("warmup_gate_lost", anomaly=True, **detail)
                self.warmup_stable_since = None
            time.sleep(15)
        self.state["validity"] = False
        self.event(
            "warmup_timeout",
            anomaly=True,
            timeout_seconds=self.args.preparation_timeout_seconds,
        )
        raise RuntimeError("warm-up gate did not become stable")

    def begin_measurement(self) -> None:
        self.phase = "measurement"
        self.measurement_started_monotonic = time.monotonic()
        self.state["measurement_start_at"] = utc_now()
        self.state["measurement_start_monotonic"] = self.measurement_started_monotonic
        self.state["measurement_elapsed_seconds"] = 0.0
        self.state["measurement_end_at"] = None
        self.state["sut_restart_baseline"] = {
            service: record["restart_count"]
            for service, record in self.service_containers().items()
        }
        self._write_state()
        self.event(
            "measurement_started", duration_seconds=self.args.measurement_seconds
        )

    def measure(self) -> None:
        if self.measurement_started_monotonic is None:
            if self.state.get("measurement_start_at"):
                elapsed = float(self.state.get("measurement_elapsed_seconds", 0.0))
                self.phase = "measurement"
                self.measurement_started_monotonic = time.monotonic() - elapsed
                self.event("measurement_resumed", elapsed_seconds=elapsed)
            else:
                self.begin_measurement()
        deadline = self.measurement_started_monotonic + self.args.measurement_seconds  # type: ignore[operator]
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self.sample()
            time.sleep(5)
        self.state["measurement_elapsed_seconds"] = round(self.measurement_elapsed(), 3)
        self.state["measurement_end_at"] = utc_now()
        self._write_state()
        self.event("measurement_evidence_frozen")

    def post_json(self, url: str) -> dict[str, Any]:
        started = time.monotonic()
        request = urllib.request.Request(
            url, method="POST", data=b"{}", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return {
                    "status_code": response.status,
                    "latency_ms": round((time.monotonic() - started) * 1000, 3),
                    "payload": parse_json_or_text(response.read(128 * 1024)),
                }
        except Exception as exc:  # noqa: BLE001
            return {
                "status_code": None,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "error": type(exc).__name__,
            }

    def drain(self) -> None:
        self.phase = "drain"
        pause = self.post_json("http://127.0.0.1:8003/runtime/pause")
        self.event("ingestion_paused_for_drain", response=pause)
        drain_deadline = time.monotonic() + 180
        while time.monotonic() < drain_deadline and not self.stop_event.is_set():
            self.sample(force=True)
            db = self.last_db_valkey.get("db", {})
            if isinstance(db, dict) and db.get("outbox_pending") == 0:
                break
            time.sleep(10)
        self.event("drain_complete", db_valkey=self.last_db_valkey)
        self._write_state()

    def recovery_step(self, label: str, *services: str) -> None:
        started = utc_now()
        code, output, error = self.compose("restart", *services, timeout=180)
        self.sample(force=True)
        health = self.health_sample()
        self.event(
            "recovery_step",
            label=label,
            services=list(services),
            started_at=started,
            finished_at=utc_now(),
            exit_code=code,
            output=output[-500:],
            error=error[-500:],
            health=health,
        )
        if code != 0:
            self.state["validity"] = False

    def recovery(self) -> None:
        self.phase = "recovery"
        self.state["recovery_started_at"] = utc_now()
        self._write_state()
        resume = self.post_json("http://127.0.0.1:8003/runtime/resume")
        self.event("ingestion_resumed_for_recovery", response=resume)
        time.sleep(15)
        self.recovery_step("broker_restart", "broker")
        self.recovery_step("decision_restart", "decision")
        self.recovery_step("database_restart", "db")
        self.recovery_step(
            "observability_restart", "otel-collector", "prometheus", "grafana"
        )
        self.recovery_step("full_stack_restart", *SERVICES)
        self.sample(force=True)
        self.state["recovery_finished_at"] = utc_now()
        self._write_state()

    def final_audit(self, error: str | None = None) -> dict[str, Any]:
        self.phase = "finalizing"
        self.sample(force=True)
        resources: list[dict[str, Any]] = []
        resource_path = self.samples / "resource_samples.jsonl"
        if resource_path.exists():
            for line in resource_path.read_text(encoding="utf-8").splitlines():
                try:
                    resources.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        sut_rss = [
            float(item.get("sut_aggregate", {}).get("rss_bytes", 0))
            for item in resources
        ]
        vm_rss = [
            float(item.get("vm_container_aggregate", {}).get("rss_bytes", 0))
            for item in resources
        ]
        sut_cpu = [
            float(item.get("sut_aggregate", {}).get("cpu_core_equivalent", 0))
            for item in resources
        ]
        service_values: dict[str, dict[str, list[float]]] = {
            service: {"rss": [], "cpu_cores": [], "limit_utilization": []}
            for service in SERVICES
        }
        for item in resources:
            for service, record in item.get("sut", {}).items():
                if record.get("memory_usage_bytes") is not None:
                    service_values.setdefault(
                        service,
                        {"rss": [], "cpu_cores": [], "limit_utilization": []},
                    )["rss"].append(float(record["memory_usage_bytes"]))
                if record.get("cpu_percent") is not None:
                    service_values.setdefault(
                        service,
                        {"rss": [], "cpu_cores": [], "limit_utilization": []},
                    )["cpu_cores"].append(float(record["cpu_percent"]) / 100.0)
                limit = int(record.get("memory_limit_bytes") or 0)
                usage = record.get("memory_usage_bytes")
                if limit > 0 and usage is not None:
                    service_values.setdefault(
                        service,
                        {"rss": [], "cpu_cores": [], "limit_utilization": []},
                    )["limit_utilization"].append(float(usage) / limit)
        service_summary = {
            service: {
                "samples": len(values["rss"]),
                "first_rss_bytes": values["rss"][0] if values["rss"] else None,
                "last_rss_bytes": values["rss"][-1] if values["rss"] else None,
                "max_rss_bytes": max(values["rss"]) if values["rss"] else None,
                "growth_bytes": (
                    values["rss"][-1] - values["rss"][0]
                    if len(values["rss"]) >= 2
                    else None
                ),
                "cpu_core_p50": percentile(values["cpu_cores"], 0.50),
                "cpu_core_p95": percentile(values["cpu_cores"], 0.95),
                "cpu_core_max": max(values["cpu_cores"])
                if values["cpu_cores"]
                else None,
                "memory_limit_utilization_max": max(values["limit_utilization"])
                if values["limit_utilization"]
                else None,
            }
            for service, values in service_values.items()
        }
        service_samples_complete = all(
            service_summary[service]["samples"] > 0 for service in SERVICES
        )
        per_service_limits_ok = all(
            summary["memory_limit_utilization_max"] is None
            or summary["memory_limit_utilization_max"] < 1.0
            for summary in service_summary.values()
        )
        resource_gates = {
            "sut_aggregate_rss_p95_lt_5_gib": (percentile(sut_rss, 0.95) or 0)
            < 5 * 1024**3,
            "sut_aggregate_rss_max_lt_8_gib_reference": (max(sut_rss) if sut_rss else 0)
            < 8 * 1024**3,
            "sut_cpu_observed_within_4_core_envelope": (max(sut_cpu) if sut_cpu else 0)
            <= 4.0,
            "all_sut_services_sampled": service_samples_complete,
            "per_service_memory_below_limit": per_service_limits_ok,
            "sut_no_oom_or_restart": not self.hard_failure,
        }
        status = "FULL_SYSTEM_24H_SOAK_PASSED"
        if error or not self.state.get("validity", True):
            status = (
                "FULL_SYSTEM_24H_SOAK_BLOCKED_ENVIRONMENT"
                if not self.state.get("measurement_start_at")
                else "FULL_SYSTEM_24H_SOAK_INCONCLUSIVE_EVIDENCE"
            )
        elif self.correctness_failure:
            status = "FULL_SYSTEM_24H_SOAK_FAILED_CORRECTNESS"
        elif not all(resource_gates.values()) or self.hard_failure:
            status = "FULL_SYSTEM_24H_SOAK_FAILED_RESOURCE_ENVELOPE"
        elif self.warnings or self.state.get("anomalies"):
            status = "FULL_SYSTEM_24H_SOAK_PASSED_WITH_WARNINGS"
        audit = {
            "terminal_status": status,
            "error": error,
            "run_id": self.run_dir.name,
            "source_sha": self.args.source_sha,
            "project": self.args.project,
            "phase": self.phase,
            "state": self.state,
            "resource_gates": resource_gates,
            "resource_summary": {
                "sut_rss_p50_bytes": percentile(sut_rss, 0.50),
                "sut_rss_p95_bytes": percentile(sut_rss, 0.95),
                "sut_rss_max_bytes": max(sut_rss) if sut_rss else None,
                "vm_rss_p50_bytes": percentile(vm_rss, 0.50),
                "vm_rss_p95_bytes": percentile(vm_rss, 0.95),
                "vm_rss_max_bytes": max(vm_rss) if vm_rss else None,
                "sut_cpu_max_core_equivalent": max(sut_cpu) if sut_cpu else None,
                "sample_count": len(resources),
            },
            "service_summary": service_summary,
            "approved_cotenant_baseline": self.cotenant_baseline,
            "intentional_deviations": [
                "external Telegram/webhook routes disabled through run-local alert overlay",
                "OTel host metrics port 8888 not exposed because Hindsight owns 8888; internal OTel listeners unchanged",
                "TV image used run-local recovered wheel build after package-index transfer failure",
                "two legacy ingestion_v2 alert incidents removed from the disposable DB clone before warm-up",
            ],
            "evidence_paths": {
                "manifest": str(self.run_dir / "manifest.json"),
                "run_state": str(self.state_path),
                "resource_samples": str(self.samples / "resource_samples.jsonl"),
                "cotenants": str(self.samples / "cotenant_resource_samples.jsonl"),
                "health": str(self.samples / "http_health.jsonl"),
                "pipeline": str(self.samples / "pipeline_metrics.jsonl"),
                "db_valkey": str(self.samples / "db_valkey.jsonl"),
                "api_load": str(self.samples / "api_load.jsonl"),
                "sampler_timing": str(self.samples / "sampler_timing.jsonl"),
                "events": str(self.events_path),
            },
        }
        atomic_json(self.run_dir / "final_audit.json", audit)
        run_report = self.run_dir / "full-system-24h-soak-audit.md"
        run_report.write_text(
            "# Full-System 24h Soak Audit\n\n"
            f"- Status: `{status}`\n"
            f"- Run: `{self.run_dir.name}`\n"
            f"- Source SHA: `{self.args.source_sha}`\n"
            f"- Measurement start: `{self.state.get('measurement_start_at')}`\n"
            f"- Measurement end: `{self.state.get('measurement_end_at')}`\n\n"
            "Machine-readable evidence is in `final_audit.json`; raw samples are under `samples/`.\n",
            encoding="utf-8",
        )
        report = (
            self.root
            / "plans"
            / "orchestrator-decision-full-system-24h-soak-resource-concurrency-v1.md"
        )
        report.write_text(
            "# Full-System 24h Soak Decision\n\n"
            f"- Status: `{status}`\n- Run: `{self.run_dir.name}`\n- Source SHA: `{self.args.source_sha}`\n"
            f"- Measurement start: `{self.state.get('measurement_start_at')}`\n"
            f"- Measurement end: `{self.state.get('measurement_end_at')}`\n\n"
            "## Evidence\n\n"
            f"Machine-readable audit: `{self.run_dir / 'final_audit.json'}`\n\n"
            "The raw JSONL evidence is listed in `final_audit.json`. This report is generated by the disposable run-local harness; it is not a production-source change.\n",
            encoding="utf-8",
        )
        self.phase = "complete"
        self.state["terminal_status"] = status
        self._write_state()
        return audit

    def cleanup(self) -> None:
        if self.status_server:
            self.status_server.shutdown()
        self.compose("down", "-v", "--remove-orphans", timeout=180)
        self.event("isolated_compose_cleaned")

    def run(self) -> int:
        try:
            self.start_status_server()
            if not self.state.get("measurement_start_at"):
                self.preflight()
            if not self.state.get("measurement_start_at"):
                self.warmup()
                self.measure()
            else:
                # A resumed measurement continues without restarting SUT.
                self.measure()
            self.load.stop()
            self.drain()
            self.recovery()
            audit = self.final_audit()
            self.cleanup()
            terminal_status = str(audit.get("terminal_status", ""))
            return 0 if "PASSED" in terminal_status else 2
        except KeyboardInterrupt:
            self.stop_event.set()
            self.load.stop()
            self.state["validity"] = False
            self._write_state()
            self.final_audit("interrupted")
            return 130
        except Exception as exc:  # noqa: BLE001 - persist partial audit before exit
            self.stop_event.set()
            self.load.stop()
            self.state["validity"] = False
            self._write_state()
            self.event(
                "harness_failure",
                anomaly=True,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.final_audit(f"{type(exc).__name__}: {exc}")
            try:
                self.cleanup()
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve primary failure
                self.event(
                    "cleanup_after_failure_error",
                    anomaly=True,
                    error=f"{type(cleanup_exc).__name__}: {cleanup_exc}",
                )
            return 1


class LoadDriver:
    def __init__(self, soak: Soak) -> None:
        self.soak = soak
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.total: dict[str, dict[str, Any]] = {}
        self.interval: dict[str, dict[str, Any]] = {}
        self.next_url = 0

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self.run, name="bounded-read-load", daemon=True
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
        self.write_snapshot()

    def schedule(self) -> tuple[int, int]:
        if self.soak.measurement_started_monotonic is None:
            return 5, 4
        elapsed = time.monotonic() - self.soak.measurement_started_monotonic
        hour = int(elapsed // 3600)
        offset = elapsed % 3600
        if hour in {6, 12, 18, 23} and offset < 60:
            return 50, 32
        if elapsed >= 3600 and offset < 120:
            return 25, 16
        return 5, 4

    def request(self, name: str, url: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, method="GET"), timeout=5
            ) as response:
                response.read(4096)
                result = {"status_code": response.status, "error": None}
        except urllib.error.HTTPError as exc:
            result = {"status_code": exc.code, "error": f"HTTP {exc.code}"}
        except Exception as exc:  # noqa: BLE001 - load result is evidence
            result = {"status_code": None, "error": type(exc).__name__}
        result["name"] = name
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        return result

    def record(self, result: dict[str, Any]) -> None:
        name = str(result["name"])
        with self.lock:
            for bucket in (self.total, self.interval):
                item = bucket.setdefault(
                    name,
                    {
                        "requests": 0,
                        "success": 0,
                        "errors": 0,
                        "timeouts": 0,
                        "latencies_ms": [],
                    },
                )
                item["requests"] += 1
                if result.get("status_code") == 200:
                    item["success"] += 1
                else:
                    item["errors"] += 1
                    if result.get("error") in {"TimeoutError", "URLError"}:
                        item["timeouts"] += 1
                if len(item["latencies_ms"]) < 10000:
                    item["latencies_ms"].append(result["latency_ms"])

    def write_snapshot(self) -> None:
        with self.lock:
            interval = self.interval
            self.interval = {}
        normalized: dict[str, Any] = {}
        for name, item in interval.items():
            latencies = item.pop("latencies_ms", [])
            normalized[name] = {
                **item,
                "latency_p50_ms": percentile(latencies, 0.50),
                "latency_p95_ms": percentile(latencies, 0.95),
                "latency_p99_ms": percentile(latencies, 0.99),
            }
        append_jsonl(
            self.soak.samples / "api_load.jsonl",
            {
                "timestamp": utc_now(),
                "phase": self.soak.phase,
                "schedule": self.schedule(),
                "interval": normalized,
            },
        )

    def run(self) -> None:
        next_second = time.monotonic()
        last_snapshot = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=32, thread_name_prefix="soak-http"
        ) as executor:
            active: set[concurrent.futures.Future[dict[str, Any]]] = set()
            while not self.stop_event.is_set():
                now = time.monotonic()
                target_rate, concurrency = self.schedule()
                while (
                    len(active) < concurrency and target_rate > 0 and now >= next_second
                ):
                    for _ in range(target_rate):
                        if len(active) >= concurrency:
                            break
                        name, url = LOAD_URLS[self.next_url % len(LOAD_URLS)]
                        self.next_url += 1
                        active.add(executor.submit(self.request, name, url))
                    next_second += 1.0
                    now = time.monotonic()
                done = {future for future in active if future.done()}
                for future in done:
                    active.remove(future)
                    try:
                        self.record(future.result())
                    except Exception as exc:  # noqa: BLE001
                        self.soak.event(
                            "load_future_failure",
                            anomaly=True,
                            error=type(exc).__name__,
                        )
                if time.monotonic() - last_snapshot >= 60:
                    self.write_snapshot()
                    last_snapshot = time.monotonic()
                time.sleep(0.05)
            for future in active:
                try:
                    self.record(future.result(timeout=5))
                except Exception as exc:  # noqa: BLE001 - drain is best effort
                    self.soak.event(
                        "load_future_drain_failure",
                        anomaly=True,
                        error=type(exc).__name__,
                    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--override-file", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--status-port", type=int, default=8765)
    parser.add_argument("--warmup-seconds", type=int, default=900)
    parser.add_argument("--preparation-timeout-seconds", type=int, default=3600)
    parser.add_argument("--measurement-seconds", type=int, default=86400)
    parser.add_argument("--warmup-only", action="store_true")
    parser.add_argument(
        "--guard-child",
        action="store_true",
        help="internal: this worker is supervised by the run-local sleep guard",
    )
    parser.add_argument(
        "--guard-max-check-gap",
        type=float,
        default=60.0,
        help="internal guard contract recorded in the pre-start evidence",
    )
    parser.add_argument("--cotenant", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if len(args.cotenant) != 3:
        raise SystemExit("exactly three --cotenant names are required")
    soak = Soak(args)

    def stop_handler(_signum: int, _frame: Any) -> None:
        soak.stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    return soak.run()


if __name__ == "__main__":
    raise SystemExit(main())
