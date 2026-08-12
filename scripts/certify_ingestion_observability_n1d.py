"""Certify ingestion telemetry wiring against the local observability stack.

The command is read-only by default.  ``--execute`` is required for Compose
service actions and is additionally guarded by
``INGESTION_RUN_N1D_OBSERVABILITY=1``.  It never flushes Valkey, deletes
database rows, removes volumes, or changes broker/database configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INGESTION_BASE_URL = "http://127.0.0.1:8003"
GRAFANA_BASE_URL = "http://127.0.0.1:3001"
OBSERVABILITY_SERVICES = (
    "otel-collector",
    "tempo",
    "prometheus",
    "loki",
    "grafana",
)
CORE_SERVICES = ("db", "broker", "ingestion")
SAFETY_SERVICES = (
    "signal-worker",
    "strategy-worker",
    "risk-worker",
    "execution-worker",
    "portfolio-worker",
)
SERVICE_TIMEOUT = 120.0
TELEMETRY_TIMEOUT = 120.0
OLDEST_PENDING_AGE_EXPRESSION = (
    "(time() - ingestion_outbox_oldest_pending_timestamp_seconds{"
    'service_name="ingestion"}) * '
    '(ingestion_outbox_pending{service_name="ingestion"} > bool 0)'
)


class N1DOperationError(RuntimeError):
    """An observability certification failure with its required status."""

    def __init__(
        self,
        status: str,
        message: str,
        *,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.evidence = evidence or {}
        super().__init__(message)


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise N1DOperationError(
            "BLOCKED_N1D_RESOURCE_RESTORE",
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout={result.stdout[-2000:]}\nstderr={result.stderr[-2000:]}",
        )
    return result


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run("docker", "compose", *args, check=check)


def _container_ids(service: str) -> tuple[str, ...]:
    result = _compose("ps", "-a", "-q", service, check=False)
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _service_state(service: str) -> dict[str, Any]:
    containers: list[dict[str, Any]] = []
    for container_id in _container_ids(service):
        result = _run(
            "docker",
            "inspect",
            "-f",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.State.ExitCode}}|{{.State.OOMKilled}}",
            container_id,
            check=False,
        )
        if result.returncode != 0:
            continue
        state, health, exit_code, oom_killed = (
            result.stdout.strip().split("|", maxsplit=3) + [""] * 4
        )[:4]
        containers.append(
            {
                "id": container_id,
                "state": state,
                "health": health or "not_configured",
                "exit_code": int(exit_code or 0),
                "oom_killed": oom_killed.lower() == "true",
            }
        )
    return {
        "present": bool(containers),
        "running": any(item["state"] == "running" for item in containers),
        "healthy": any(
            item["state"] == "running" and item["health"] == "healthy"
            for item in containers
        ),
        "containers": containers,
    }


def _capture_states() -> dict[str, dict[str, Any]]:
    services = CORE_SERVICES + OBSERVABILITY_SERVICES + SAFETY_SERVICES
    return {service: _service_state(service) for service in services}


def _compose_config() -> dict[str, Any]:
    result = _compose(
        "--profile",
        "prod",
        "config",
        "--format",
        "json",
        check=False,
    )
    if result.returncode != 0:
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            f"docker compose config failed: {result.stderr[-2000:]}",
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            "docker compose config did not return JSON",
        ) from exc


def validate_compose_contract() -> dict[str, Any]:
    config = _compose_config()
    services = config.get("services", {})
    ingestion = services.get("ingestion")
    if not isinstance(ingestion, dict):
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            "ingestion service is absent",
        )
    depends_on = ingestion.get("depends_on", {})
    if "otel-collector" in depends_on:
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_ISOLATION",
            "otel-collector must not be a hard ingestion dependency",
        )
    if (
        not isinstance(depends_on.get("db"), dict)
        or depends_on["db"].get("condition") != "service_healthy"
    ):
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            "ingestion must depend on a healthy DB",
        )
    if not isinstance(ingestion.get("healthcheck"), dict):
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            "ingestion healthcheck is absent",
        )
    environment = ingestion.get("environment", {})
    resource_attributes = (
        environment.get("OTEL_RESOURCE_ATTRIBUTES")
        if isinstance(environment, dict)
        else None
    )
    resource_prefix = "service.instance.id="
    if not isinstance(resource_attributes, str) or not resource_attributes.startswith(
        resource_prefix
    ):
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            "ingestion must configure OTEL_RESOURCE_ATTRIBUTES with service.instance.id",
        )
    otel_instance_id = (
        resource_attributes[len(resource_prefix) :].split(",", 1)[0].strip()
    )
    if not otel_instance_id:
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            "ingestion service.instance.id must not be empty",
        )
    missing = [service for service in OBSERVABILITY_SERVICES if service not in services]
    if missing:
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_BOOTSTRAP",
            f"observability services are absent: {missing}",
        )
    return {
        "ingestion_command": str(ingestion.get("command")),
        "ingestion_healthcheck": ingestion["healthcheck"],
        "broker_hard_dependency": False,
        "otel_instance_id": otel_instance_id,
        "observability_services": list(OBSERVABILITY_SERVICES),
    }


def _wait_sync(predicate: Any, *, timeout: float, description: str) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(2)
    raise N1DOperationError(
        "BLOCKED_N1D_TELEMETRY_ISOLATION",
        f"timed out waiting for {description}: {last}",
    )


def _http_json(url: str) -> tuple[int, Any]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return 0, None


def _wait_ingestion_live() -> dict[str, Any]:
    def ready() -> dict[str, Any] | None:
        live_status, _ = _http_json(f"{INGESTION_BASE_URL}/health/live")
        ready_status, _ = _http_json(f"{INGESTION_BASE_URL}/health/ready")
        runtime_status, runtime = _http_json(f"{INGESTION_BASE_URL}/runtime")
        service = _service_state("ingestion")
        if (
            service["running"]
            and service["healthy"]
            and live_status == 200
            and ready_status == 200
            and runtime_status == 200
            and isinstance(runtime, dict)
            and runtime.get("state") == "live"
        ):
            return {
                "service": service,
                "live_status": live_status,
                "ready_status": ready_status,
                "runtime": runtime,
            }
        return None

    return _wait_sync(ready, timeout=SERVICE_TIMEOUT, description="ingestion LIVE")


def _stop_with_evidence(service: str) -> dict[str, Any]:
    started = time.monotonic()
    _compose("stop", service)
    elapsed = time.monotonic() - started
    state = _service_state(service)
    evidence = {
        "service": state,
        "elapsed_seconds": elapsed,
        "exit_codes": [item["exit_code"] for item in state["containers"]],
        "oom_killed": any(item["oom_killed"] for item in state["containers"]),
    }
    if (
        state["running"]
        or evidence["oom_killed"]
        or any(code != 0 for code in evidence["exit_codes"])
    ):
        raise N1DOperationError(
            "BLOCKED_N1D_TELEMETRY_SHUTDOWN",
            f"{service} did not stop cleanly: {evidence}",
            evidence=evidence,
        )
    return evidence


def _backend_get(service: str, path: str) -> tuple[int, Any]:
    result = _compose(
        "exec",
        "-T",
        service,
        "wget",
        "-qO-",
        f"http://127.0.0.1:{ {'prometheus': 9090, 'tempo': 3200, 'loki': 3100}[service] }{path}",
        check=False,
    )
    if result.returncode != 0:
        return 0, None
    try:
        return 200, json.loads(result.stdout)
    except json.JSONDecodeError:
        return 200, result.stdout


def _prometheus_query(expression: str) -> Any:
    encoded = urllib.parse.quote(expression, safe="")
    _, payload = _backend_get("prometheus", f"/api/v1/query?query={encoded}")
    return payload


def _prometheus_instant_results(expression: str) -> list[dict[str, Any]] | None:
    payload = _prometheus_query(expression)
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return None
    data = payload.get("data", {})
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        return None
    results = data.get("result", [])
    if not isinstance(results, list):
        return None
    return [item for item in results if isinstance(item, dict)]


def _prometheus_series(selector: str, start: float) -> list[dict[str, str]]:
    query = urllib.parse.urlencode(
        {
            "match[]": selector,
            "start": f"{start:.3f}",
            "end": f"{time.time():.3f}",
        }
    )
    _, payload = _backend_get("prometheus", f"/api/v1/series?{query}")
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise N1DOperationError(
            "BLOCKED_N1D_PROMETHEUS_EXPORT",
            f"Prometheus series query failed for {selector}",
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise N1DOperationError(
            "BLOCKED_N1D_PROMETHEUS_EXPORT",
            f"Prometheus series query returned invalid data for {selector}",
        )
    return [
        {str(key): str(value) for key, value in item.items()}
        for item in data
        if isinstance(item, dict)
    ]


def _series_label_key(labels: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (str(key), str(value)) for key, value in labels.items() if key != "__name__"
        )
    )


def _prometheus_identity_evidence(
    started_at: float,
    *,
    expected_base_lane_count: int | None = None,
) -> dict[str, Any]:
    runtime_series = _prometheus_series(
        'ingestion_runtime_live{service_name="ingestion"}',
        started_at,
    )
    freshness_series = _prometheus_series(
        'ingestion_base_last_close_timestamp_seconds{service_name="ingestion"}',
        started_at,
    )
    runtime_instance_ids = sorted(
        {
            labels.get("service_instance_id")
            for labels in runtime_series
            if labels.get("service_instance_id")
        }
    )
    if len(runtime_series) != 1 or len(runtime_instance_ids) != 1:
        raise N1DOperationError(
            "BLOCKED_N1D_CARDINALITY",
            "runtime live identity was not stable across the certification window",
            evidence={
                "runtime_series": runtime_series,
                "runtime_instance_ids": runtime_instance_ids,
            },
        )

    freshness_keys = {_series_label_key(labels) for labels in freshness_series}
    freshness_lanes = {
        (labels.get("venue", ""), labels.get("instrument_id", ""))
        for labels in freshness_series
    }
    if len(freshness_keys) != len(freshness_series) or any(
        not venue or not instrument_id for venue, instrument_id in freshness_lanes
    ):
        raise N1DOperationError(
            "BLOCKED_N1D_CARDINALITY",
            "base freshness series contained duplicate or incomplete lane identities",
            evidence={"freshness_series": freshness_series},
        )
    if (
        expected_base_lane_count is not None
        and len(freshness_series) != expected_base_lane_count
    ):
        raise N1DOperationError(
            "BLOCKED_N1D_CARDINALITY",
            "base freshness series multiplied across ingestion restarts",
            evidence={
                "expected_base_lane_count": expected_base_lane_count,
                "actual_base_lane_count": len(freshness_series),
                "freshness_series": freshness_series,
            },
        )
    return {
        "runtime_series_count": len(runtime_series),
        "runtime_service_instance_ids": runtime_instance_ids,
        "freshness_series_count": len(freshness_series),
        "freshness_lanes": sorted(
            f"{venue}/{instrument_id}" for venue, instrument_id in freshness_lanes
        ),
    }


def _pending_age_evidence() -> dict[str, Any] | None:
    pending_results = _prometheus_instant_results(
        'ingestion_outbox_pending{service_name="ingestion"}'
    )
    age_results = _prometheus_instant_results(OLDEST_PENDING_AGE_EXPRESSION)
    if not pending_results or not age_results:
        return None
    pending_by_key = {
        _series_label_key(item.get("metric", {})): float(item["value"][1])
        for item in pending_results
        if isinstance(item.get("metric"), dict)
        and isinstance(item.get("value"), list)
        and len(item["value"]) == 2
    }
    age_by_key = {
        _series_label_key(item.get("metric", {})): float(item["value"][1])
        for item in age_results
        if isinstance(item.get("metric"), dict)
        and isinstance(item.get("value"), list)
        and len(item["value"]) == 2
    }
    if not pending_by_key or set(pending_by_key) != set(age_by_key):
        return None
    values = []
    for key, pending in pending_by_key.items():
        age = age_by_key[key]
        if pending <= 0 and abs(age) > 1e-9:
            return None
        if pending > 0 and age <= 0:
            return None
        values.append({"labels": dict(key), "pending": pending, "age_seconds": age})
    return {
        "values": values,
        "empty_age_zero": all(
            item["pending"] == 0 and item["age_seconds"] == 0 for item in values
        ),
        "expression": OLDEST_PENDING_AGE_EXPRESSION,
    }


def _wait_pending_age_evidence() -> dict[str, Any]:
    return _wait_sync(
        _pending_age_evidence,
        timeout=TELEMETRY_TIMEOUT,
        description="zero-pending outbox age expression",
    )


def _wait_exported_metrics() -> dict[str, Any]:
    expressions = {
        "base_freshness": 'ingestion_base_last_close_timestamp_seconds{service_name="ingestion"}',
        "runtime_live": 'ingestion_runtime_live{service_name="ingestion"}',
        "websocket_connected": 'ingestion_websocket_connected{service_name="ingestion"}',
        "candle_commit_total": 'ingestion_candle_commit_total{service_name="ingestion"}',
        "outbox_pending": 'ingestion_outbox_pending{service_name="ingestion"}',
    }

    last_missing: list[str] = []

    def exported() -> dict[str, Any] | None:
        nonlocal last_missing
        results: dict[str, Any] = {}
        last_missing = []
        for name, expression in expressions.items():
            payload = _prometheus_query(expression)
            if not isinstance(payload, dict) or payload.get("status") != "success":
                last_missing.append(name)
                return None
            data = payload.get("data", {})
            result = data.get("result", []) if isinstance(data, dict) else []
            if not result:
                last_missing.append(name)
                return None
            results[name] = result
        return results

    deadline = time.monotonic() + TELEMETRY_TIMEOUT
    last_results: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = exported()
        if result is not None:
            return result
        last_results = {
            "missing": list(last_missing),
            "present": [name for name in expressions if name not in last_missing],
        }
        time.sleep(2)
    raise N1DOperationError(
        "BLOCKED_N1D_PROMETHEUS_EXPORT",
        "timed out waiting for required ingestion Prometheus series",
        evidence=last_results,
    )


def _collect_trace_evidence(started_at: float) -> dict[str, Any]:
    start_seconds = max(0, int(started_at) - 5)
    end_seconds = int(time.time()) + 5
    encoded_tags = urllib.parse.quote("service.name=ingestion", safe="")
    search_path = (
        f"/api/search?tags={encoded_tags}&start={start_seconds}"
        f"&end={end_seconds}&limit=50"
    )
    _, payload = _backend_get("tempo", search_path)
    if not isinstance(payload, dict):
        raise N1DOperationError(
            "BLOCKED_N1D_TEMPO_EXPORT",
            "Tempo search did not return JSON",
        )
    traces = payload.get("traces", [])
    start_ns = int(started_at * 1_000_000_000)
    end_ns = int(time.time() * 1_000_000_000) + 5_000_000_000
    traces = [
        item
        for item in traces
        if isinstance(item, dict)
        and start_ns <= int(item.get("startTimeUnixNano", 0)) <= end_ns
    ]
    if not traces:
        raise N1DOperationError(
            "BLOCKED_N1D_TEMPO_EXPORT",
            "Tempo did not contain an ingestion trace",
        )
    names = [
        str(trace.get("rootTraceName", ""))
        for trace in traces
        if isinstance(trace, dict)
    ]
    if any("health/live" in name or "health/ready" in name for name in names):
        raise N1DOperationError(
            "BLOCKED_N1D_TRACE_INSTRUMENTATION",
            f"health endpoint appeared in Tempo traces: {names}",
        )
    return {"trace_count": len(traces), "root_trace_names": names}


def _collect_log_evidence(started_at: float) -> dict[str, Any] | None:
    query = urllib.parse.urlencode(
        {
            "query": '{service_name="ingestion"}',
            "start": str(max(0, int(started_at - 5) * 1_000_000_000)),
            "end": str(int(time.time() * 1_000_000_000) + 5_000_000_000),
            "limit": "10",
            "direction": "backward",
        }
    )
    _, payload = _backend_get("loki", f"/loki/api/v1/query_range?{query}")
    if not isinstance(payload, dict):
        raise N1DOperationError(
            "BLOCKED_N1D_LOKI_EXPORT",
            "Loki query did not return JSON",
        )
    result = payload.get("data", {}).get("result", [])
    if not result:
        return None
    return {
        "stream_count": len(result),
        "entry_count": sum(
            len(stream.get("values", []))
            for stream in result
            if isinstance(stream, dict)
        ),
    }


def _wait_log_evidence(started_at: float) -> dict[str, Any]:
    deadline = time.monotonic() + TELEMETRY_TIMEOUT
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = _collect_log_evidence(started_at)
        if last is not None:
            return last
        time.sleep(2)
    raise N1DOperationError(
        "BLOCKED_N1D_LOKI_EXPORT",
        f"Loki did not contain current-run ingestion logs: {last}",
    )


def _collect_grafana_evidence() -> dict[str, Any]:
    status, payload = _http_json(
        f"{GRAFANA_BASE_URL}/api/search?query=Ingestion%20Operations"
    )
    if status != 200 or not isinstance(payload, list):
        raise N1DOperationError(
            "BLOCKED_N1D_GRAFANA_PROVISIONING",
            f"Grafana dashboard search failed: status={status} payload={payload}",
        )
    matching = [item for item in payload if item.get("uid") == "flipper-ingestion"]
    if not matching:
        raise N1DOperationError(
            "BLOCKED_N1D_GRAFANA_PROVISIONING",
            "provisioned ingestion dashboard is absent",
        )
    return {"dashboards": matching}


def _restore_states(initial: dict[str, dict[str, Any]]) -> None:
    for service in OBSERVABILITY_SERVICES:
        if initial[service]["running"]:
            _compose("--profile", "prod", "up", "-d", service, check=False)
        else:
            _compose("stop", service, check=False)
    for service in ("ingestion", "broker"):
        if initial[service]["running"]:
            _compose("up", "-d", service, check=False)
        else:
            _compose("stop", service, check=False)


def _require_preconditions(states: dict[str, dict[str, Any]]) -> None:
    if not states["db"]["running"] or not states["db"]["healthy"]:
        raise N1DOperationError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            f"Timescale must be running and healthy: {states['db']}",
        )
    active_safety = {
        service: states[service]
        for service in SAFETY_SERVICES
        if states[service]["running"]
    }
    if active_safety:
        raise N1DOperationError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            f"trading/signal services must be stopped: {active_safety}",
        )


def run_execute() -> dict[str, Any]:
    compose_report = validate_compose_contract()
    initial_states = _capture_states()
    _require_preconditions(initial_states)
    if any(initial_states[service]["running"] for service in OBSERVABILITY_SERVICES):
        raise N1DOperationError(
            "ENVIRONMENT_PRECONDITION_CHANGED",
            "observability services must be stopped before collector-down certification",
        )

    report: dict[str, Any] = {
        "status": "READY_FOR_REVIEW",
        "compose": compose_report,
        "initial_states": initial_states,
        "telemetry_non_authoritative": True,
        "health_routes_excluded": ["/health/live", "/health/ready"],
        "custom_spans": [
            "ingestion.recovery",
            "ingestion.outbox.publish_batch",
        ],
        "per_candle_tracing": False,
    }
    telemetry_window_started = time.time()
    report["prometheus_window_start_epoch"] = telemetry_window_started
    try:
        _compose("up", "-d", "db", "broker", "ingestion")
        report["collector_down_startup"] = _wait_ingestion_live()
        report["collector_down_shutdown"] = _stop_with_evidence("ingestion")

        _compose("--profile", "prod", "up", "-d", *OBSERVABILITY_SERVICES)
        _wait_sync(
            lambda: _service_state("otel-collector")["running"],
            timeout=SERVICE_TIMEOUT,
            description="OTel Collector running",
        )
        _compose("up", "-d", "ingestion")
        report["collector_up_first_startup"] = _wait_ingestion_live()
        report["prometheus_first_generation"] = _wait_exported_metrics()
        report["prometheus_first_identity"] = _prometheus_identity_evidence(
            telemetry_window_started
        )
        report["oldest_pending_age_first"] = _wait_pending_age_evidence()
        report["collector_up_first_shutdown"] = _stop_with_evidence("ingestion")

        _compose("up", "-d", "ingestion")
        report["collector_up_second_startup"] = _wait_ingestion_live()
        report["collector_up_startup"] = report["collector_up_second_startup"]
        report["prometheus_second_generation"] = _wait_exported_metrics()
        report["prometheus"] = report["prometheus_second_generation"]
        report["prometheus_identity"] = _prometheus_identity_evidence(
            telemetry_window_started,
            expected_base_lane_count=report["prometheus_first_identity"][
                "freshness_series_count"
            ],
        )
        report["oldest_pending_age"] = _wait_pending_age_evidence()
        _http_json(f"{INGESTION_BASE_URL}/runtime")
        report["tempo"] = _collect_trace_evidence(telemetry_window_started)
        report["loki"] = _wait_log_evidence(telemetry_window_started)
        report["grafana"] = _collect_grafana_evidence()

        _compose("stop", "otel-collector")
        time.sleep(5)
        ready_status, _ = _http_json(f"{INGESTION_BASE_URL}/health/ready")
        runtime_status, runtime = _http_json(f"{INGESTION_BASE_URL}/runtime")
        if (
            ready_status != 200
            or runtime_status != 200
            or not isinstance(runtime, dict)
        ):
            raise N1DOperationError(
                "BLOCKED_N1D_TELEMETRY_ISOLATION",
                f"ingestion degraded while collector was stopped: ready={ready_status} runtime={runtime}",
            )
        report["collector_loss_while_live"] = {
            "health_ready": ready_status,
            "runtime": runtime,
        }
        _compose("start", "otel-collector")
        report["collector_recovery"] = _wait_sync(
            lambda: _service_state("otel-collector")["healthy"],
            timeout=SERVICE_TIMEOUT,
            description="OTel Collector recovery",
        )
    finally:
        try:
            _restore_states(initial_states)
        except Exception as exc:
            raise N1DOperationError(
                "BLOCKED_N1D_RESOURCE_RESTORE",
                f"failed to restore initial service states: {exc}",
            ) from exc
        report["final_states"] = _capture_states()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform the guarded local certification; default is dry-run",
    )
    args = parser.parse_args(argv)

    try:
        compose_report = validate_compose_contract()
        if not args.execute:
            print(
                json.dumps(
                    {
                        "status": "DRY_RUN",
                        "compose": compose_report,
                        "initial_states": _capture_states(),
                        "would_start": [*CORE_SERVICES, *OBSERVABILITY_SERVICES],
                        "would_stop_for_collector_down": ["otel-collector"],
                    },
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
            return 0
        if os.environ.get("INGESTION_RUN_N1D_OBSERVABILITY") != "1":
            raise N1DOperationError(
                "ENVIRONMENT_PRECONDITION_CHANGED",
                "--execute requires INGESTION_RUN_N1D_OBSERVABILITY=1",
            )
        print(json.dumps(run_execute(), indent=2, sort_keys=True, default=str))
        return 0
    except N1DOperationError as exc:
        print(
            json.dumps(
                {
                    "status": exc.status,
                    "message": str(exc),
                    "evidence": exc.evidence,
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
