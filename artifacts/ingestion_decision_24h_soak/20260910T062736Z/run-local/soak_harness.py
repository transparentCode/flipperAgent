#!/usr/bin/env python3
"""Ingestion + Decision 24-hour soak harness (run #3).

This is disposable run-local evidence tooling.  The frozen application source
and repository configuration are not edited by this harness.  The Compose
project, volumes, HTTP load, recovery actions, and cleanup are all scoped to
the one run ID.  Hindsight, CBM, and GitNexus are observed by immutable
container name and are never managed by this project.

The common sampler implementation is loaded from the earlier run-local
sampler only for its standard-library helpers and bounded HTTP load driver.
All topology, gating, resource accounting, recovery, and report behavior is
defined here for the seven-container certification contract.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
LEGACY_PATH = Path(__file__).with_name("legacy_sampler.py")
_spec = importlib.util.spec_from_file_location("previous_soak_sampler", LEGACY_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - run-local guard
    raise RuntimeError(f"cannot load sampler helpers from {LEGACY_PATH}")
legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)


SERVICES = (
    "db",
    "broker",
    "ingestion",
    "decision",
    "otel-collector",
    "prometheus",
    "grafana",
)
CORE_SERVICES = ("db", "broker", "ingestion", "decision")
MEASUREMENT_SERVICES = (
    "otel-collector",
    "prometheus",
    "grafana",
)
REQUIRED_LANES = 3
REQUIRED_INPUTS = {
    "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h": "1h",
    "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:4h": "4h",
    "stream:ohlcv:ingestion:binance:ETH-USDT-PERP:4h": "4h",
}
REQUIRED_HISTORY = {
    ("binance", "BTC-USDT-PERP", "1h"): timedelta(hours=1),
    ("binance", "BTC-USDT-PERP", "4h"): timedelta(hours=4),
    ("binance", "ETH-USDT-PERP", "4h"): timedelta(hours=4),
}
REQUIRED_SERIES = {
    f"{instrument}:{timeframe}" for _, instrument, timeframe in REQUIRED_HISTORY
}

HEALTH_URLS = {
    "ingestion": "http://127.0.0.1:8003/health/ready",
    "decision": "http://127.0.0.1:8004/health/ready",
    "otel-collector": "http://127.0.0.1:13133",
    "prometheus": "http://127.0.0.1:9090/-/healthy",
    "grafana": "http://127.0.0.1:3001/api/health",
}

PIPELINE_URLS = {
    "ingestion_runtime": "http://127.0.0.1:8003/runtime",
    "ingestion_assets": "http://127.0.0.1:8003/assets",
    "decision_runtime": "http://127.0.0.1:8004/runtime",
    "decision_lanes": "http://127.0.0.1:8004/runtime/lanes",
    "decision_inputs": "http://127.0.0.1:8004/runtime/inputs",
    "prometheus_up": "http://127.0.0.1:9090/api/v1/query?query=up",
}

LOAD_URLS = (
    ("ingestion_ready", HEALTH_URLS["ingestion"]),
    ("ingestion_runtime", PIPELINE_URLS["ingestion_runtime"]),
    ("ingestion_assets", PIPELINE_URLS["ingestion_assets"]),
    ("decision_ready", HEALTH_URLS["decision"]),
    ("decision_runtime", PIPELINE_URLS["decision_runtime"]),
    ("decision_lanes", PIPELINE_URLS["decision_lanes"]),
    ("decision_inputs", PIPELINE_URLS["decision_inputs"]),
)

FROZEN_TOOLING_FILES = (
    "run-local/soak_harness.py",
    "run-local/legacy_sampler.py",
    "run-local/bounded_command.py",
    "run-local/test_bounded_command.py",
    "run-local/test_run3_harness.py",
    "run-local/guarded_launch.py",
    "run-local/test_guarded_launch.py",
    "run-local/soak-compose.override.yml",
    "run-local/otel-collector.yaml",
    "run-local/grafana/provisioning/datasources/datasources.yaml",
    "run-local/grafana/provisioning/dashboards/dashboards.yaml",
    "run-local/grafana/provisioning/dashboards/pipeline-health.json",
    "run-local/grafana/provisioning/dashboards/ingestion.json",
    "run-local/launchd/run-under-launchd.sh",
    "run-local/launchd/run-guarded-child.sh",
    "run-local/launchd/ingestion-decision-soak-run3.plist",
    "run-local/launchd/install-run3.sh",
    "run-local/launchd/stop-run3.sh",
    "run-local/launchd/start-run3.sh",
    "SOURCE_EXPORT_PROOF.json",
    "IMAGE_PROOF.json",
)
TEST_ONLY_RESOURCE_LIMITS = {
    "otel-collector": "512M",
    "grafana": "384M",
}
CONVERGENCE_WINDOW_SECONDS = 120.0
PROBE_GAP_THRESHOLD_SECONDS = 60.0
OUTBOX_GROWTH_STREAK_LIMIT = 4
BOUNDARY_TIMEFRAMES = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
PROBE_INDETERMINATE = "INDETERMINATE_PROBE"
TRANSIENT_CONVERGED = "TRANSIENT_CONVERGED"
UNRESOLVED = "UNRESOLVED"
GUARD_MAX_CHECK_GAP_SECONDS = 60.0
REQUIRED_COTENANTS = ("mcp-cbm", "mcp-gitnexus")
PREFERRED_PORTS = {
    "ingestion": 8003,
    "decision": 8004,
    "status": 8765,
    "grafana": 3001,
    "prometheus": 9090,
    "otel_health": 13133,
}
SAMPLING_POLICIES: dict[str, dict[str, Any]] = {
    "sampler_timing.jsonl": {
        "cadence_seconds": 5.0,
        "max_gap_seconds": PROBE_GAP_THRESHOLD_SECONDS,
        "coverage": "high_frequency",
    },
    "resource_samples.jsonl": {
        "cadence_seconds": 15.0,
        "max_gap_seconds": PROBE_GAP_THRESHOLD_SECONDS,
        "coverage": "high_frequency",
    },
    "http_health.jsonl": {
        "cadence_seconds": 30.0,
        "max_gap_seconds": PROBE_GAP_THRESHOLD_SECONDS,
        "coverage": "high_frequency",
    },
    "pipeline_gate.jsonl": {
        "cadence_seconds": 15.0,
        "max_gap_seconds": PROBE_GAP_THRESHOLD_SECONDS,
        "coverage": "high_frequency",
    },
    "api_load.jsonl": {
        # Keep the approved 60-second continuity limit.  Emit snapshots more
        # often so normal scheduler jitter does not manufacture a gap.
        "cadence_seconds": 30.0,
        "max_gap_seconds": PROBE_GAP_THRESHOLD_SECONDS,
        "coverage": "high_frequency",
    },
    # Storage is intentionally scheduled at ten minutes.  Its continuity
    # rule is explicit and separate from the ordinary 60-second rule.
    "storage_growth.jsonl": {
        "cadence_seconds": 600.0,
        "max_gap_seconds": 1200.0,
        "coverage": "scheduled_storage",
    },
}

legacy.SERVICES = SERVICES
legacy.HEALTH_URLS = HEALTH_URLS
legacy.PIPELINE_URLS = PIPELINE_URLS
legacy.LOAD_URLS = LOAD_URLS


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _floor_boundary(now: datetime, interval: timedelta) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    seconds = int((now - epoch).total_seconds())
    width = int(interval.total_seconds())
    return epoch + timedelta(seconds=seconds - seconds % width)


def _probe_payload(
    probe: object, required_keys: tuple[str, ...]
) -> tuple[dict[str, Any] | None, str | None]:
    """Return a validated JSON object or classify the probe as indeterminate."""

    if not isinstance(probe, dict):
        return None, PROBE_INDETERMINATE
    if probe.get("status_code") != 200:
        return None, PROBE_INDETERMINATE
    payload = probe.get("payload")
    if not isinstance(payload, dict):
        return None, PROBE_INDETERMINATE
    if any(key not in payload for key in required_keys):
        return None, PROBE_INDETERMINATE
    return payload, None


def _interval_lag(
    observed: datetime | None, expected: datetime, interval: timedelta
) -> int | None:
    if observed is None:
        return None
    delta = (expected - observed).total_seconds()
    return max(0, int(delta // interval.total_seconds()))


def boundary_advanced(previous: datetime | None, current: datetime | None) -> bool:
    """Return true only when canonical history moved to a newer closed boundary."""

    return previous is not None and current is not None and current > previous


def _series_from_lane(lane_id: object, lane: object) -> str | None:
    text = f"{lane_id} {lane}".upper()
    timeframe = "4h" if "4H" in text else "1h" if "1H" in text else None
    instrument = (
        "BTC-USDT-PERP" if "BTC" in text else "ETH-USDT-PERP" if "ETH" in text else None
    )
    return f"{instrument}:{timeframe}" if instrument and timeframe else None


def _runtime_payload_errors(
    *,
    ingestion: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    lanes: dict[str, Any] | None,
    inputs: dict[str, Any] | None,
    history: dict[str, Any],
) -> dict[str, str]:
    """Validate nested runtime evidence before deriving any lag values."""

    errors: dict[str, str] = {}
    if ingestion is not None and not isinstance(ingestion.get("state"), str):
        errors["ingestion"] = PROBE_INDETERMINATE
    if decision is not None and not isinstance(decision.get("service_state"), str):
        errors["decision"] = PROBE_INDETERMINATE

    input_values = inputs.get("inputs") if isinstance(inputs, dict) else None
    if isinstance(input_values, dict):
        for stream_key in REQUIRED_INPUTS:
            value = input_values.get(stream_key)
            if (
                not isinstance(value, dict)
                or _parse_timestamp(value.get("latest_market_as_of")) is None
            ):
                errors[f"input:{stream_key}"] = PROBE_INDETERMINATE

    lane_values = lanes.get("lanes") if isinstance(lanes, dict) else None
    if isinstance(lane_values, dict):
        by_series = {
            series: value
            for lane_id, value in lane_values.items()
            if (series := _series_from_lane(lane_id, value)) in REQUIRED_SERIES
        }
        for series in REQUIRED_SERIES:
            value = by_series.get(series)
            watermark = value.get("watermark") if isinstance(value, dict) else None
            if (
                not isinstance(watermark, dict)
                or _parse_timestamp(watermark.get("latest_market_as_of")) is None
            ):
                errors[f"lane:{series}"] = PROBE_INDETERMINATE

    history_rows = history.get("required_series") if isinstance(history, dict) else None
    if history.get("error") or not isinstance(history_rows, dict):
        errors["history"] = PROBE_INDETERMINATE
    else:
        for series in REQUIRED_SERIES:
            row = history_rows.get(series)
            if not isinstance(row, dict) or any(
                _parse_timestamp(row.get(field)) is None
                for field in ("last_close", "expected_closed_boundary")
            ):
                errors[f"history:{series}"] = PROBE_INDETERMINATE

    return errors


def classify_boundary_observations(
    observations: list[dict[str, Any]],
    *,
    window_seconds: float = CONVERGENCE_WINDOW_SECONDS,
) -> str:
    """Classify synthetic or recorded boundary observations deterministically."""

    valid = [item for item in observations if item.get("probe_status") == "VALID"]
    if not valid:
        return PROBE_INDETERMINATE
    if any(bool(item.get("blocked")) for item in valid):
        return UNRESOLVED
    first = float(valid[0].get("detected_elapsed_seconds", 0.0))
    for item in valid:
        elapsed = float(item.get("detected_elapsed_seconds", first)) - first
        input_lag = item.get("input_lag")
        watermark_lag = item.get("watermark_lag")
        if input_lag == 0 and watermark_lag == 0:
            return TRANSIENT_CONVERGED if elapsed <= window_seconds else UNRESOLVED
        if (
            isinstance(input_lag, int)
            and isinstance(watermark_lag, int)
            and (input_lag > 0 or watermark_lag > 0)
        ):
            continue
    return UNRESOLVED


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 6)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _slope(points: list[tuple[float, float]]) -> float | None:
    """Return a robust two-window RSS slope in bytes per second."""

    if len(points) < 4:
        return None
    ordered = sorted(points)
    window = max(2, min(len(ordered) // 5, 240))
    first = _median([value for _, value in ordered[:window]])
    last = _median([value for _, value in ordered[-window:]])
    if first is None or last is None:
        return None
    elapsed = ordered[-1][0] - ordered[0][0]
    return None if elapsed <= 0 else (last - first) / elapsed


def _aggregate(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rss = [
        int(record["memory_usage_bytes"])
        for record in records.values()
        if record.get("memory_usage_bytes") is not None
    ]
    cpu = [
        float(record["cpu_percent"])
        for record in records.values()
        if record.get("cpu_percent") is not None
    ]
    return {
        "rss_bytes": sum(rss),
        "cpu_percent_sum": round(sum(cpu), 3),
        "cpu_core_equivalent": round(sum(cpu) / 100.0, 4),
        "container_count": len(records),
    }


def source_tree_digest(root: Path) -> tuple[str, int]:
    """Digest every exported source blob without mutating the export."""

    if not root.is_dir():
        raise RuntimeError(f"source export is missing: {root}")
    entries: list[str] = []
    file_count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {relative}\n")
        file_count += 1
    return hashlib.sha256("".join(entries).encode("utf-8")).hexdigest(), file_count


def verify_source_export(
    source_root: Path, proof_path: Path, expected_source_sha: str
) -> dict[str, Any]:
    """Verify the root-owned export proof; never rebaseline it."""

    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"source export proof is unreadable: {type(exc).__name__}"
        ) from exc
    observed_digest, observed_count = source_tree_digest(source_root)
    if proof.get("source_sha") != expected_source_sha:
        raise RuntimeError(
            "source export proof SHA does not match the requested source"
        )
    if proof.get("mismatch") != []:
        raise RuntimeError("source export proof contains blob mismatches")
    if proof.get("tree_sha256") != observed_digest:
        raise RuntimeError("source export tree digest drifted")
    if proof.get("file_count") != observed_count:
        raise RuntimeError("source export file count drifted")
    return {
        "source_sha": expected_source_sha,
        "tree_sha256": observed_digest,
        "file_count": observed_count,
        "proof_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
        "proof_path": str(proof_path),
    }


class BoundedLoadDriver(legacy.LoadDriver):
    """Rate-bound read load with a hard in-flight request ceiling.

    The historical driver submits a whole concurrency window once per
    second.  That can under-deliver the 5-RPS baseline when the configured
    concurrency is four.  This driver schedules individual requests at the
    target interval while refusing to queue work when the in-flight ceiling
    is full.  Requests have no retry path; the inherited request method keeps
    the five-second timeout and records each outcome exactly once.
    """

    def run(self) -> None:
        next_request_at = time.monotonic()
        last_snapshot = time.monotonic()
        profile: tuple[int, int] | None = None
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=32, thread_name_prefix="soak-http"
        ) as executor:
            active: set[concurrent.futures.Future[dict[str, Any]]] = set()
            while not self.stop_event.is_set():
                now = time.monotonic()
                target_rate, concurrency = self.schedule()
                new_profile = (target_rate, concurrency)
                if new_profile != profile:
                    profile = new_profile
                    next_request_at = now
                interval = 1.0 / target_rate if target_rate > 0 else 1.0
                while (
                    target_rate > 0
                    and len(active) < concurrency
                    and next_request_at <= now
                ):
                    name, url = legacy.LOAD_URLS[self.next_url % len(legacy.LOAD_URLS)]
                    self.next_url += 1
                    active.add(executor.submit(self.request, name, url))
                    next_request_at += interval
                if len(active) >= concurrency and next_request_at <= now:
                    # Drop missed slots rather than creating a burst or a
                    # hidden queue after a slow/erroring endpoint.
                    next_request_at = now + interval

                done = {future for future in active if future.done()}
                for future in done:
                    active.remove(future)
                    try:
                        self.record(future.result())
                    except Exception as exc:  # noqa: BLE001 - load evidence
                        self.soak.event(
                            "load_future_failure",
                            anomaly=True,
                            error=type(exc).__name__,
                        )
                if time.monotonic() - last_snapshot >= 30:
                    self.write_snapshot()
                    last_snapshot = time.monotonic()
                time.sleep(0.01)

            for future in active:
                try:
                    self.record(future.result(timeout=5))
                except Exception as exc:  # noqa: BLE001 - bounded drain
                    self.soak.event(
                        "load_future_drain_failure",
                        anomaly=True,
                        error=type(exc).__name__,
                    )


# legacy.Soak constructs its driver through the legacy module namespace.
# Replace only that run-local dependency; the historical artifact remains
# untouched and the application containers are not changed.
legacy.LoadDriver = BoundedLoadDriver


class Soak(legacy.Soak):
    """Corrected run-specific sampler and lifecycle controller."""

    def __init__(self, args: Any) -> None:
        super().__init__(args)
        self.source_root = self.run_dir / "run-local" / "source"
        self.source_proof_path = self.run_dir / "SOURCE_EXPORT_PROOF.json"
        self.image_proof_path = self.run_dir / "IMAGE_PROOF.json"
        self.last_gate_at = 0.0
        self.history_cursors: dict[str, str] = self.state.get("history_cursors", {})
        self.boundary_episodes: dict[str, dict[str, Any]] = self.state.get(
            "boundary_episodes", {}
        )
        self.completed_episodes: list[dict[str, Any]] = self.state.get(
            "completed_boundary_episodes", []
        )
        self.outbox_episode: dict[str, Any] | None = self.state.get("outbox_episode")
        self.outbox_episodes: list[dict[str, Any]] = self.state.get(
            "outbox_episodes", []
        )
        self.probe_indeterminate_samples = int(
            self.state.get("probe_indeterminate_samples", 0)
        )
        self.probe_gap_open_at = _parse_timestamp(
            self.state.get("measurement_probe_gap_open_at")
        )
        self.max_probe_gap_seconds = float(
            self.state.get("max_probe_gap_seconds", 0.0) or 0.0
        )
        self.measurement_completed = bool(self.state.get("measurement_completed"))

    def _persist_gate_state(self) -> None:
        self.state["history_cursors"] = self.history_cursors
        self.state["boundary_episodes"] = self.boundary_episodes
        self.state["completed_boundary_episodes"] = self.completed_episodes
        self.state["outbox_episode"] = self.outbox_episode
        self.state["outbox_episodes"] = self.outbox_episodes
        self.state["probe_indeterminate_samples"] = self.probe_indeterminate_samples
        self.state["measurement_probe_gap_open_at"] = (
            self.probe_gap_open_at.isoformat() if self.probe_gap_open_at else None
        )
        self.state["max_probe_gap_seconds"] = round(self.max_probe_gap_seconds, 3)
        self.state["probe_gap_threshold_seconds"] = PROBE_GAP_THRESHOLD_SECONDS

    def command(
        self, command: list[str], timeout: float = 30.0
    ) -> tuple[int, str, str]:
        timeout = self._remaining(timeout)
        if timeout <= 0:
            return 124, "", "collector cycle deadline"
        return super().command(
            [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("bounded_command.py")),
                "--timeout",
                str(timeout),
                "--",
                *command,
            ],
            timeout=timeout + 2,
        )

    def log_sample(self) -> None:
        """Retain seven-service raw logs on disk, never in a captured pipe."""
        until = legacy.utc_now()
        since = getattr(self, "raw_log_cursor", None)
        if since is None:
            starts = [self.state.get("created_at")]
            starts.extend(
                record.get("started_at")
                for record in self.state.get("sut_container_baseline", {}).values()
            )
            parsed = [
                stamp
                for value in starts
                if (stamp := _parse_timestamp(value)) is not None
            ]
            since = min(parsed).isoformat() if parsed else "1970-01-01T00:00:00Z"
        cursor = _parse_timestamp(since)
        if cursor is not None:
            since = (cursor - timedelta(seconds=1)).isoformat()
        directory = self.run_dir / "raw-docker-logs"
        directory.mkdir(mode=0o700, exist_ok=True)
        # Each finite collection is a new file. Hitting the safety bound is an
        # evidence failure, not silently accepted truncation.
        limit = 16 * 1024 * 1024
        collection_timeout = self._remaining(40)

        def collect(service: str) -> dict[str, Any]:
            path = directory / f"{time.time_ns()}-{service}.log"
            override = (self.root / self.args.override_file).resolve()
            command = [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("bounded_command.py")),
                "--timeout",
                str(collection_timeout),
                "--max-file-bytes",
                str(limit),
                "--",
                "docker",
                "compose",
                "-p",
                self.args.project,
                "-f",
                str(override),
                "--profile",
                "prod",
                "logs",
                "--no-color",
                "--timestamps",
                "--since",
                since,
                "--until",
                until,
                service,
            ]
            with path.open("xb") as output:
                try:
                    result = subprocess.run(
                        command,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        cwd=override.parent,
                        timeout=collection_timeout + 2,
                        check=False,
                    )
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = 124
            return {
                "service": service,
                "path": str(path.relative_to(self.run_dir)),
                "returncode": code,
                "bytes": path.stat().st_size,
                "sha256": legacy.sha256_file(path),
                "byte_limit": limit,
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
            records = list(pool.map(collect, SERVICES))
        failed = any(
            item["returncode"] != 0 or item["bytes"] >= limit for item in records
        )
        legacy.append_jsonl(
            self.samples / "raw_logs_manifest.jsonl",
            {
                "timestamp": until,
                "phase": self.phase,
                "since": since,
                "until": until,
                "records": records,
                "complete": not failed,
            },
        )
        if failed:
            self.state["validity"] = False
            self.hard_failure = True
            self.event("raw_log_collection_failed", anomaly=True)
        else:
            self.raw_log_cursor = until
            self.state["raw_log_cursor"] = until

    def compose(self, *arguments: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """Use the run-local seven-service Compose entrypoint only."""

        # The override is intentionally self-contained through Compose
        # ``extends``.  Its relative extends paths are resolved from the
        # run-local directory, so invoking Compose from the worktree root can
        # incorrectly resolve ``../../../../docker-compose.yml`` to
        # ``/docker-compose.yml``.  Keep the run-local entrypoint isolated and
        # make this resolution deterministic for every lifecycle operation.
        timeout = self._remaining(timeout)
        if timeout <= 0:
            return 124, "", "collector cycle deadline"
        override = (self.root / self.args.override_file).resolve()
        command = [
            "docker",
            "compose",
            "-p",
            self.args.project,
            "-f",
            override.name,
            "--profile",
            "prod",
            *arguments,
        ]
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("bounded_command.py")),
                    "--timeout",
                    str(timeout),
                    "--",
                    *command,
                ],
                cwd=override.parent,
                text=True,
                capture_output=True,
                timeout=timeout + 2,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        return (
            result.returncode,
            legacy.redact(result.stdout.strip()),
            legacy.redact(result.stderr.strip()),
        )

    def _tooling_paths(self) -> list[Path]:
        return [self.run_dir / relative_path for relative_path in FROZEN_TOOLING_FILES]

    def _tooling_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for path in self._tooling_paths():
            if not path.is_file():
                raise RuntimeError(
                    f"required run-local tooling file is missing: {path}"
                )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes[str(path.relative_to(self.root))] = digest
        tree_digest, file_count = source_tree_digest(self.source_root)
        hashes["source_tree_sha256"] = tree_digest
        hashes["source_tree_file_count"] = str(file_count)
        return hashes

    def _freeze_tooling(self) -> None:
        source_export = verify_source_export(
            self.source_root, self.source_proof_path, self.args.source_sha
        )
        hashes = self._tooling_hashes()
        self.state["frozen_tooling_hashes"] = hashes
        self.state["frozen_tooling_files"] = list(FROZEN_TOOLING_FILES)
        self.state["frozen_tooling_at"] = legacy.utc_now()
        self.state["source_export"] = source_export
        self.state["test_only_resource_limits"] = TEST_ONLY_RESOURCE_LIMITS
        self.state["sut_limits_preserved"] = True
        legacy.atomic_json(
            self.run_dir / "FROZEN_TOOLING_HASHES.json",
            {
                "algorithm": "sha256",
                "frozen_at": self.state["frozen_tooling_at"],
                "files": hashes,
                "source_export": source_export,
                "test_only_resource_limits": TEST_ONLY_RESOURCE_LIMITS,
                "sut_limits_preserved": True,
            },
        )
        self.event(
            "run_local_inputs_frozen",
            files=hashes,
            source_export=source_export,
        )

    def _verify_frozen_tooling(self) -> bool:
        expected = self.state.get("frozen_tooling_hashes")
        if not isinstance(expected, dict):
            self.state["validity"] = False
            self.hard_failure = True
            self.event("frozen_inputs_missing", anomaly=True)
            self.stop_event.set()
            return False
        try:
            observed = self._tooling_hashes()
            observed_export = verify_source_export(
                self.source_root, self.source_proof_path, self.args.source_sha
            )
        except RuntimeError as exc:
            observed = {"error": str(exc)}
            observed_export = None
        if observed == expected and observed_export == self.state.get("source_export"):
            return True
        self.state["validity"] = False
        self.hard_failure = True
        if not self.state.get("tooling_change_reported"):
            self.state["tooling_change_reported"] = True
            self.event(
                "frozen_tooling_changed",
                anomaly=True,
                expected=expected,
                observed=observed,
                expected_source_export=self.state.get("source_export"),
                observed_source_export=observed_export,
            )
        self.stop_event.set()
        return False

    def _verify_frozen_inputs(self) -> None:
        if not self._verify_frozen_tooling():
            raise RuntimeError("frozen source/tooling inputs changed")

    def _verify_image_proof(self) -> dict[str, Any]:
        try:
            proof = json.loads(self.image_proof_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"image proof is unreadable: {type(exc).__name__}"
            ) from exc
        image = proof.get("image")
        image_id = proof.get("image_id")
        if (
            proof.get("source_sha") != self.args.source_sha
            or not isinstance(image, str)
            or not image
            or not isinstance(image_id, str)
            or not image_id.startswith("sha256:")
        ):
            raise RuntimeError("image proof identity does not match frozen source")
        code, output, error = self.docker(
            "image", "inspect", image, "--format", "{{.Id}}", timeout=30
        )
        observed = output.splitlines()[-1].strip() if output else ""
        if code != 0 or observed != image_id:
            raise RuntimeError(
                "runtime image identity does not match IMAGE_PROOF.json: "
                f"expected={image_id} observed={observed or error[:200]}"
            )
        return {
            "image": image,
            "image_id": image_id,
            "source_sha": self.args.source_sha,
            "proof_sha256": hashlib.sha256(
                self.image_proof_path.read_bytes()
            ).hexdigest(),
        }

    def sample(self, force: bool = False) -> None:
        started = time.monotonic()
        self._cycle_deadline = started + 40.0
        self._cycle_records = None
        self._cycle_probes = None
        before = self._cadence_check(allow_initial=True)
        timings = {}
        try:
            if not before:
                self.warmup_stable_since = None
                if self.phase == "measurement":
                    self.state["validity"] = False
                    self.state["sampling_continuity_ok"] = False
                    self.stop_event.set()
                    self._write_state()
                    return
            if (
                self.state.get("frozen_tooling_hashes")
                and not self._verify_frozen_tooling()
            ):
                return
            for name, interval, attribute, callback in (
                ("resource", 15, "last_sample_at", self.resource_sample),
                ("health", 30, "last_health_at", self.health_sample),
                ("gate", 15, "last_gate_at", self.app_gate),
                ("pipeline", 60, "last_pipeline_at", self.pipeline_sample),
                ("logs", 300, "last_log_at", self.log_sample),
                ("storage", 600, "last_storage_at", self.storage_sample),
            ):
                now = time.monotonic()
                if self._remaining(40) <= 0:
                    break
                if force or now - getattr(self, attribute, 0) >= interval:
                    callback()
                    setattr(self, attribute, now)
                    timings[name] = round((time.monotonic() - now) * 1000, 3)
            legacy.append_jsonl(
                self.samples / "sampler_timing.jsonl",
                {
                    "timestamp": legacy.utc_now(),
                    "phase": self.phase,
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    "collector_duration_ms": timings,
                },
            )
            after = self._cadence_check(allow_initial=self.phase == "measurement")
            self.state["sampling_continuity_ok"] = before and after
            if not self.state["sampling_continuity_ok"]:
                self.warmup_stable_since = None
                if self.phase == "measurement":
                    self.state["validity"] = False
                    self.stop_event.set()
            self.write_status()
            self.last_sample_completed_at = time.monotonic()
            if self.state.get("measurement_start_at"):
                self.state["measurement_elapsed_seconds"] = round(
                    self.measurement_elapsed(), 3
                )
            self._write_state()
        finally:
            self._cycle_deadline = None
            self._cycle_records = None
            self._cycle_probes = None

    def _remaining(self, timeout: float) -> float:
        deadline = getattr(self, "_cycle_deadline", None)
        return (
            timeout
            if deadline is None
            else max(0.0, min(timeout, deadline - time.monotonic()))
        )

    def _http_probe(self, url: str) -> dict[str, Any]:
        remaining = self._remaining(5)
        if remaining <= 0:
            return {"error": "collector cycle deadline", "status_code": None}
        return legacy.http_get(url, timeout=remaining)

    def health_sample(self) -> dict[str, Any]:
        sample = {
            "timestamp": legacy.utc_now(),
            "phase": self.phase,
            "checks": {
                name: self._http_probe(url) for name, url in HEALTH_URLS.items()
            },
        }
        sample["timestamp"] = legacy.utc_now()
        legacy.append_jsonl(self.samples / "http_health.jsonl", sample)
        self.last_health = sample
        return sample

    def _cadence_check(self, *, allow_initial: bool = False) -> bool:
        """Consume actual append-only timestamps, including gaps hidden by a new sample."""
        if self.phase not in {"warmup", "measurement"}:
            return True
        if getattr(self, "_cadence_phase", None) != self.phase:
            self._cadence_phase = self.phase
            self._cadence_offsets = {}
            self._cadence_last = {}
        now = datetime.now(UTC)
        ok = True
        invalid_streams = set()
        for filename, policy in SAMPLING_POLICIES.items():
            path = self.samples / filename
            last = self._cadence_last.get(filename)
            origin = _parse_timestamp(
                self.state.get(
                    "measurement_start_at"
                    if self.phase == "measurement"
                    else "warmup_started_at"
                )
            )
            if path.exists():
                with path.open(encoding="utf-8") as handle:
                    handle.seek(self._cadence_offsets.get(filename, 0))
                    while True:
                        position = handle.tell()
                        line = handle.readline()
                        if not line or not line.endswith("\n"):
                            handle.seek(position)
                            break
                        try:
                            item = json.loads(line)
                            if item.get("phase") != self.phase:
                                continue
                            stamp = _parse_timestamp(item.get("timestamp"))
                            if (
                                stamp is None
                                or stamp > datetime.now(UTC)
                                or (
                                    last
                                    and (stamp - last).total_seconds()
                                    > policy["max_gap_seconds"]
                                )
                                or (last and stamp < last)
                                or (
                                    last is None
                                    and origin is not None
                                    and stamp is not None
                                    and (stamp - origin).total_seconds()
                                    > policy["max_gap_seconds"]
                                )
                            ):
                                ok = False
                                invalid_streams.add(filename)
                            if stamp is not None:
                                last = stamp
                        except (ValueError, AttributeError, TypeError):
                            ok = False
                            invalid_streams.add(filename)
                    self._cadence_offsets[filename] = handle.tell()
            now = datetime.now(UTC)
            initial = (
                allow_initial
                and last is None
                and origin is not None
                and (now - origin).total_seconds() <= policy["max_gap_seconds"]
            )
            if not initial and (
                last is None or (now - last).total_seconds() > policy["max_gap_seconds"]
            ):
                ok = False
                invalid_streams.add(filename)
            self._cadence_last[filename] = last
        self.state["sampling_continuity_detail"] = {
            "checked_at": now.isoformat(),
            "invalid_streams": sorted(invalid_streams),
            "last_observed_at": {
                name: stamp.isoformat() if stamp else None
                for name, stamp in self._cadence_last.items()
            },
        }
        return ok

    def warmup(self) -> None:
        self.phase = "warmup"
        self.state["warmup_started_at"] = legacy.utc_now()
        self.start_load()
        deadline = time.monotonic() + self.args.preparation_timeout_seconds
        first = True
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self.sample(force=first)
            first = False
            detail = self.state.get("last_gate", {})
            ready = bool(
                detail.get("ready")
                and self.state.get("sampling_continuity_ok")
                and self.state.get("validity") is True
                and not self.hard_failure
                and not self.correctness_failure
            )
            legacy.append_jsonl(
                self.samples / "warmup_gate.jsonl",
                {
                    "timestamp": legacy.utc_now(),
                    **detail,
                    "ready": ready,
                    "sampling_continuity_ok": self.state.get("sampling_continuity_ok"),
                },
            )
            if not ready:
                self.warmup_stable_since = None
            elif self.warmup_stable_since is None:
                self.warmup_stable_since = time.monotonic()
            elif (
                time.monotonic() - self.warmup_stable_since >= self.args.warmup_seconds
            ):
                return
            self.stop_event.wait(5)
        self.state["validity"] = False
        raise RuntimeError("warm-up application/cadence gate did not become stable")

    def service_containers(self) -> dict[str, dict[str, Any]]:
        cached = getattr(self, "_cycle_records", None)
        if cached is not None:
            return cached
        code, ids, _ = self.docker(
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={self.args.project}",
            timeout=5,
        )
        if code or not ids:
            return {}
        code, output, _ = self.docker(
            "inspect",
            "--format",
            legacy.SERVICE_INSPECT_TEMPLATE,
            *ids.split(),
            timeout=5,
        )
        records = {}
        if not code:
            for line in output.splitlines():
                fields = line.split("|")
                if len(fields) != 11 or fields[2] in records:
                    return {}  # duplicate/malformed topology never collapses silently
                try:
                    records[fields[2]] = {
                        "id": fields[0],
                        "name": fields[1].lstrip("/"),
                        "service": fields[2],
                        "state": fields[3],
                        "health": fields[4],
                        "oom_killed": fields[5].lower() == "true",
                        "restart_count": int(fields[6]),
                        "exit_code": int(fields[7]),
                        "memory_limit_bytes": int(fields[8]),
                        "nano_cpus": int(fields[9]),
                        "started_at": fields[10],
                    }
                except ValueError:
                    return {}
        if getattr(self, "_cycle_deadline", None) is not None:
            self._cycle_records = records
        return records

    def _project_services(self) -> set[str]:
        code, output, error = self.docker(
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={self.args.project}",
            "--format",
            '{{.Label "com.docker.compose.service"}}',
        )
        if code != 0:
            self.event(
                "project_service_listing_failed", anomaly=True, error=error[:300]
            )
            return set()
        return {line.strip() for line in output.splitlines() if line.strip()}

    def _split_records(
        self, records: dict[str, dict[str, Any]]
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        core = {name: records[name] for name in CORE_SERVICES if name in records}
        measurement = {
            name: records[name] for name in MEASUREMENT_SERVICES if name in records
        }
        return core, measurement, records

    def _check_run_records(self, records: dict[str, dict[str, Any]]) -> None:
        baseline_key = (
            "warmup_sut_restart_baseline"
            if self.phase == "warmup"
            else "sut_restart_baseline"
        )
        baseline = self.state.get(baseline_key, {})
        for service in SERVICES:
            record = records.get(service)
            if record is None:
                if self.phase in {"warmup", "measurement", "recovery"}:
                    self.hard_failure = True
                    self.event("run_service_missing", anomaly=True, service=service)
                continue
            if record.get("oom_killed"):
                self.hard_failure = True
                self.event("run_service_oom_killed", anomaly=True, service=service)
            observed_restart = record.get("restart_count")
            baseline_restart = baseline.get(service)
            if baseline_restart is not None and observed_restart != baseline_restart:
                self.hard_failure = True
                self.event(
                    "run_service_restart_changed",
                    anomaly=True,
                    service=service,
                    baseline=baseline_restart,
                    observed=observed_restart,
                )

    def resource_sample(self) -> dict[str, Any]:
        records = self.service_containers()
        cotenant_records = self.cotenant_containers()
        snapshot = self.stats({**records, **cotenant_records})
        run_stats = {key: value for key, value in snapshot.items() if key in records}
        core, measurement, _ = self._split_records(run_stats)
        cotenants = {
            key: value for key, value in snapshot.items() if key in cotenant_records
        }
        self._check_run_records(run_stats)

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

        sample = {
            "timestamp": legacy.utc_now(),
            "phase": self.phase,
            "run": run_stats,
            "core_path": core,
            "measurement_infra": measurement,
            "approved_cotenant": cotenants,
            "core_path_aggregate": _aggregate(core),
            "measurement_infra_aggregate": _aggregate(measurement),
            "whole_vm_container_aggregate": _aggregate(
                {**core, **measurement, **cotenants}
            ),
        }
        legacy.append_jsonl(self.samples / "resource_samples.jsonl", sample)
        legacy.append_jsonl(
            self.samples / "cotenant_resource_samples.jsonl",
            {"timestamp": sample["timestamp"], **cotenants},
        )
        legacy.append_jsonl(
            self.samples / "container_state.jsonl",
            {
                "timestamp": sample["timestamp"],
                "run": {
                    key: {
                        field: value
                        for field, value in record.items()
                        if field
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
                    for key, record in run_stats.items()
                },
                "approved_cotenant": {
                    key: {
                        field: value
                        for field, value in record.items()
                        if field
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

    def _psql(self, query: str, *, timeout: float = 30.0) -> tuple[int, str, str]:
        # The standalone Compose file uses non-secret run-local defaults.  Do
        # not read or inherit the dirty checkout's production .env.
        user = "flipper"
        database = "flipper_db"
        return self.compose(
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
            timeout=timeout,
        )

    def db_probe(self) -> dict[str, Any]:
        query = (
            "SELECT json_build_object("
            "'outbox_pending',(SELECT count(*) FROM ingestion.outbox WHERE published_at IS NULL),"
            "'outbox_oldest_epoch',(SELECT extract(epoch FROM min(occurred_at)) FROM ingestion.outbox WHERE published_at IS NULL),"
            "'connections',(SELECT count(*) FROM pg_stat_activity),"
            "'active_connections',(SELECT count(*) FROM pg_stat_activity WHERE state='active'),"
            "'long_transactions',(SELECT count(*) FROM pg_stat_activity WHERE xact_start IS NOT NULL AND now()-xact_start > interval '30 seconds'),"
            "'lock_waits',(SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock'),"
            "'deadlocks',(SELECT coalesce(sum(deadlocks),0) FROM pg_stat_database),"
            "'db_size_bytes',pg_database_size(current_database()),"
            "'candles_size_bytes',pg_total_relation_size('ingestion.candles'::regclass),"
            "'outbox_size_bytes',pg_total_relation_size('ingestion.outbox'::regclass))::text"
        )
        code, output, error = self._psql(query, timeout=20)
        if code != 0 or not output:
            return {"error": error[:400] or "db_probe_failed"}
        try:
            payload = json.loads(output.splitlines()[-1])
        except json.JSONDecodeError:
            return {"error": "db_probe_invalid_json"}
        if isinstance(payload, dict):
            pending = payload.get("outbox_pending")
            oldest = payload.get("outbox_oldest_epoch")
            if (
                isinstance(pending, int)
                and pending > 0
                and isinstance(oldest, (int, float))
            ):
                payload["outbox_oldest_age_seconds"] = round(
                    max(0.0, datetime.now(UTC).timestamp() - float(oldest)), 3
                )
            else:
                payload["outbox_oldest_age_seconds"] = 0.0
        return payload

    def history_probe(self) -> dict[str, Any]:
        values = ",".join(
            f"('{instrument}','{timeframe}',interval '{int(step.total_seconds())} seconds')"
            for (venue, instrument, timeframe), step in REQUIRED_HISTORY.items()
        )
        query = f"""
WITH requested(instrument_id, timeframe, step) AS (VALUES {values}),
ordered AS (
    SELECT r.instrument_id, r.timeframe, r.step, c.open_time, c.close_time,
           lag(c.open_time) OVER (
               PARTITION BY r.instrument_id, r.timeframe ORDER BY c.open_time
           ) AS previous_open
      FROM requested r
      LEFT JOIN ingestion.candles c
        ON c.venue = 'binance'
       AND c.instrument_id = r.instrument_id
       AND c.timeframe = r.timeframe
),
summary AS (
    SELECT instrument_id, timeframe,
           count(open_time)::bigint AS row_count,
           min(open_time) AS first_open,
           max(close_time) AS last_close,
           coalesce(sum(CASE WHEN previous_open IS NOT NULL
                              AND open_time - previous_open <> step
                             THEN 1 ELSE 0 END), 0)::bigint AS gap_count
      FROM ordered
     GROUP BY instrument_id, timeframe
)
SELECT coalesce(json_agg(summary ORDER BY instrument_id, timeframe), '[]'::json)::text
  FROM summary
"""
        code, output, error = self._psql(query, timeout=20)
        if code != 0 or not output:
            return {"error": error[:400] or "history_probe_failed"}
        try:
            # psql may wrap the JSON aggregate across multiple output lines;
            # parse the complete payload rather than only its final line.
            rows = json.loads("".join(output.splitlines()))
        except json.JSONDecodeError:
            return {"error": "history_probe_invalid_json"}
        now = datetime.now(UTC)
        series: dict[str, Any] = {}
        contiguous = True
        forward = True
        for row in rows:
            key = f"{row['instrument_id']}:{row['timeframe']}"
            step = REQUIRED_HISTORY[("binance", row["instrument_id"], row["timeframe"])]
            expected = _floor_boundary(now, step)
            last_close = _parse_timestamp(row.get("last_close"))
            row["expected_closed_boundary"] = expected.isoformat()
            row["last_close"] = last_close.isoformat() if last_close else None
            row["forward_to_expected_boundary"] = bool(
                last_close and last_close >= expected
            )
            series[key] = row
            contiguous = (
                contiguous
                and int(row.get("row_count", 0)) > 0
                and int(row.get("gap_count", 1)) == 0
            )
            forward = forward and bool(row["forward_to_expected_boundary"])
        return {
            "checked_at": now.isoformat(),
            "required_series": series,
            "all_required_series_contiguous": contiguous,
            "all_required_series_forward_current": forward,
            "repair_path": "ingestion_runtime_startup_catchup_and_htf_reconcile",
        }

    def pipeline_sample(self) -> dict[str, Any]:
        cached = getattr(self, "_cycle_probes", None)
        db = cached[1] if cached else self.db_probe()
        history = cached[2] if cached else self.history_probe()
        sample = {
            "timestamp": legacy.utc_now(),
            "phase": self.phase,
            "db": db,
            "history": history,
            "valkey": self.valkey_probe(),
        }
        sample["reused_gate_snapshot_at"] = cached[3] if cached else None
        aliases = {
            "ingestion_runtime": "ingestion",
            "decision_runtime": "decision",
            "decision_lanes": "lanes",
            "decision_inputs": "inputs",
        }
        sample["http"] = {
            name: cached[0][aliases[name]]
            if cached and name in aliases
            else self._http_probe(url)
            for name, url in PIPELINE_URLS.items()
        }
        sample["timestamp"] = legacy.utc_now()
        legacy.append_jsonl(self.samples / "db_valkey.jsonl", sample)
        legacy.append_jsonl(
            self.samples / "pipeline_metrics.jsonl",
            {
                "timestamp": sample["timestamp"],
                "phase": self.phase,
                "http": sample["http"],
            },
        )
        legacy.append_jsonl(
            self.samples / "history_preparation.jsonl",
            {"timestamp": sample["timestamp"], "phase": self.phase, **history},
        )
        self.last_pipeline = sample
        return sample

    def valkey_probe(self) -> dict[str, Any]:
        script = """
local r={stream_lengths={},errors={},cursor='0',scanned=0,truncated=false}
r.info=redis.call('INFO')
for page=1,3 do
 local batch=redis.call('SCAN',r.cursor,'COUNT',100)
 r.cursor=batch[1]
 for _,k in ipairs(batch[2]) do
  if r.scanned>=300 then r.truncated=true break end
  r.scanned=r.scanned+1
  if string.match(k,'^stream:') or string.match(k,'^orders:') or
     string.match(k,'^fills:') or string.match(k,'^execution:') or string.match(k,'^price_update:') then
   local n=redis.pcall('XLEN',k)
   if type(n)=='number' then r.stream_lengths[k]=n else r.errors[k]=n.err end
  end
 end
 if r.cursor=='0' or r.truncated then break end
end
if r.cursor~='0' then r.truncated=true end
return cjson.encode(r)
"""
        code, output, error = self.compose(
            "exec",
            "-T",
            "broker",
            "valkey-cli",
            "--raw",
            "EVAL",
            script,
            "0",
            timeout=5,
        )
        if code:
            return {"error": error or "valkey_probe_failed"}
        try:
            values = json.loads(output)
            if (
                not isinstance(values, dict)
                or not isinstance(values.get("stream_lengths"), dict)
                or not isinstance(values.get("info"), str)
                or type(values.get("truncated")) is not bool
                or any(
                    type(n) is not int or n < 0
                    for n in values["stream_lengths"].values()
                )
            ):
                raise ValueError("invalid lengths")
            result = {
                "stream_count": len(values["stream_lengths"]),
                "stream_lengths": values["stream_lengths"],
                "discovery": {
                    key: values.get(key)
                    for key in ("cursor", "scanned", "truncated", "errors")
                },
            }
            for line in values["info"].splitlines():
                key, separator, value = line.partition(":")
                if separator and key in {
                    "used_memory",
                    "used_memory_rss",
                    "used_memory_peak",
                    "connected_clients",
                    "blocked_clients",
                    "instantaneous_ops_per_sec",
                    "rejected_connections",
                }:
                    result[key] = legacy.parse_number(value)
            return result
        except ValueError:
            return {"error": "valkey_probe_invalid_json"}

    @staticmethod
    def _lane_series(lane_id: object, lane: object) -> str | None:
        return _series_from_lane(lane_id, lane)

    def _outbox_state(self, db: object, now: datetime) -> dict[str, Any]:
        if not isinstance(db, dict) or not isinstance(db.get("outbox_pending"), int):
            return {
                "status": PROBE_INDETERMINATE,
                "pending": None,
                "oldest_age_seconds": None,
            }
        pending = int(db["outbox_pending"])
        age = db.get("outbox_oldest_age_seconds")
        age_value = float(age) if isinstance(age, (int, float)) else None
        if pending > 0:
            if self.outbox_episode is None:
                self.outbox_episode = {
                    "started_at": now.isoformat(),
                    "max_pending": pending,
                    "max_oldest_age_seconds": age_value,
                    "last_pending": pending,
                    "last_oldest_age_seconds": age_value,
                    "samples": 0,
                    "growth_streak": 0,
                    "persistent_growth": False,
                }
            episode = self.outbox_episode
            previous_pending = int(episode.get("last_pending", pending))
            previous_age = episode.get("last_oldest_age_seconds")
            pending_grew = pending > previous_pending
            age_grew = (
                age_value is not None
                and isinstance(previous_age, (int, float))
                and age_value > float(previous_age)
            )
            if pending_grew or (pending >= previous_pending and age_grew):
                episode["growth_streak"] = int(episode.get("growth_streak", 0)) + 1
            else:
                episode["growth_streak"] = 0
            if int(episode.get("growth_streak", 0)) >= OUTBOX_GROWTH_STREAK_LIMIT:
                episode["persistent_growth"] = True
            episode["max_pending"] = max(int(episode.get("max_pending", 0)), pending)
            episode["max_oldest_age_seconds"] = max(
                float(episode.get("max_oldest_age_seconds") or 0.0),
                age_value or 0.0,
            )
            episode["last_pending"] = pending
            episode["last_oldest_age_seconds"] = age_value
            episode["samples"] = int(episode.get("samples", 0)) + 1
            return {
                "status": (
                    "PERSISTENT_GROWTH"
                    if episode.get("persistent_growth")
                    else "PENDING_DRAINING"
                ),
                "pending": pending,
                "oldest_age_seconds": age_value,
                "episode": episode,
            }
        if self.outbox_episode is not None:
            episode = dict(self.outbox_episode)
            episode["drained_at"] = now.isoformat()
            started = _parse_timestamp(episode.get("started_at"))
            episode["drain_duration_seconds"] = (
                round((now - started).total_seconds(), 3) if started else None
            )
            episode["status"] = "DRAINED"
            episode["healthy"] = not bool(episode.get("persistent_growth"))
            self.outbox_episodes.append(episode)
            self.outbox_episode = None
        return {"status": "DRAINED", "pending": 0, "oldest_age_seconds": 0.0}

    def _record_probe_status(self, probe_valid: bool, now: datetime) -> None:
        """Track measurement probe gaps without turning them into market lag."""

        if self.phase != "measurement":
            return
        if not probe_valid:
            if self.probe_gap_open_at is None:
                self.probe_gap_open_at = now
            return
        if self.probe_gap_open_at is None:
            return
        gap = max(0.0, (now - self.probe_gap_open_at).total_seconds())
        self.max_probe_gap_seconds = max(self.max_probe_gap_seconds, gap)
        if gap > PROBE_GAP_THRESHOLD_SECONDS:
            self.state["validity"] = False
            self.event(
                "measurement_probe_gap_over_threshold",
                anomaly=True,
                gap_seconds=round(gap, 3),
                threshold_seconds=PROBE_GAP_THRESHOLD_SECONDS,
            )
        self.probe_gap_open_at = None

    def _advance_boundary_episodes(
        self,
        *,
        history: dict[str, Any],
        input_lags: dict[str, int | None],
        lane_lags_by_series: dict[str, int | None],
        provenance: dict[str, dict[str, Any]],
        blocked: int,
        probe_valid: bool,
        now: datetime,
    ) -> dict[str, Any]:
        rows = history.get("required_series", {}) if isinstance(history, dict) else {}
        unresolved: list[str] = []
        pending: list[str] = []
        for series, row in rows.items() if isinstance(rows, dict) else ():
            if not isinstance(row, dict):
                continue
            last_close = _parse_timestamp(row.get("last_close"))
            if last_close is None:
                continue
            previous = _parse_timestamp(self.history_cursors.get(series))
            if previous is None:
                self.history_cursors[series] = last_close.isoformat()
                continue
            if boundary_advanced(previous, last_close):
                self.history_cursors[series] = last_close.isoformat()
                existing = self.boundary_episodes.pop(series, None)
                if existing is not None:
                    existing["status"] = (
                        UNRESOLVED
                        if existing.get("first_valid_observation_at")
                        else PROBE_INDETERMINATE
                    )
                    existing["unresolved_reason"] = "superseded_by_new_boundary"
                    self.completed_episodes.append(dict(existing))
                    if existing["status"] == UNRESOLVED:
                        unresolved.append(series)
                        self.correctness_failure = True
                input_lag = next(
                    (
                        input_lags[key]
                        for key in REQUIRED_INPUTS
                        if key.endswith(series)
                    ),
                    None,
                )
                watermark_lag = lane_lags_by_series.get(series)
                if probe_valid and input_lag == 0 and watermark_lag == 0:
                    self.event(
                        "boundary_advanced_already_converged",
                        series=series,
                        boundary_at=last_close.isoformat(),
                    )
                else:
                    episode = {
                        "series": series,
                        "boundary_at": last_close.isoformat(),
                        "boundary_transition_at": now.isoformat(),
                        "first_detected_at": now.isoformat(),
                        "first_valid_observation_at": (
                            now.isoformat() if probe_valid else None
                        ),
                        "deadline_at": (
                            now + timedelta(seconds=CONVERGENCE_WINDOW_SECONDS)
                        ).isoformat()
                        if probe_valid
                        else None,
                        "status": "CONVERGENCE_PENDING",
                        "max_input_lag": input_lag,
                        "max_watermark_lag": watermark_lag,
                        "probe_indeterminate_samples": 0,
                        "observations": [],
                        "provenance": provenance.get(series, {}),
                    }
                    self.boundary_episodes[series] = episode
                    self.event(
                        "boundary_convergence_started",
                        series=series,
                        boundary_at=episode["boundary_at"],
                        first_detected_at=episode["first_detected_at"],
                    )
            episode = self.boundary_episodes.get(series)
            if not episode:
                continue
            if not probe_valid:
                episode["probe_indeterminate_samples"] = (
                    int(episode.get("probe_indeterminate_samples", 0)) + 1
                )
                pending.append(series)
                continue
            if episode.get("first_valid_observation_at") is None:
                episode["first_valid_observation_at"] = now.isoformat()
                episode["deadline_at"] = (
                    now + timedelta(seconds=CONVERGENCE_WINDOW_SECONDS)
                ).isoformat()
            episode["provenance"] = {
                **episode.get("provenance", {}),
                **provenance.get(series, {}),
            }
            observation_start = _parse_timestamp(episode["first_valid_observation_at"])
            input_lag = next(
                (input_lags[key] for key in REQUIRED_INPUTS if key.endswith(series)),
                None,
            )
            watermark_lag = lane_lags_by_series.get(series)
            observation = {
                "observed_at": now.isoformat(),
                "probe_status": "VALID",
                "detected_elapsed_seconds": (now - observation_start).total_seconds(),
                "input_lag": input_lag,
                "watermark_lag": watermark_lag,
                "blocked": blocked > 0,
                "provenance": provenance.get(series, {}),
            }
            episode["observations"].append(observation)
            episode["max_input_lag"] = max(
                int(episode.get("max_input_lag") or 0), int(input_lag or 0)
            )
            episode["max_watermark_lag"] = max(
                int(episode.get("max_watermark_lag") or 0), int(watermark_lag or 0)
            )
            elapsed = (
                now - _parse_timestamp(episode["first_valid_observation_at"])
            ).total_seconds()
            previous_observation = (
                episode["observations"][-2]
                if len(episode["observations"]) > 1
                else None
            )
            grew = bool(
                previous_observation
                and (
                    (input_lag or 0) > (previous_observation.get("input_lag") or 0)
                    or (watermark_lag or 0)
                    > (previous_observation.get("watermark_lag") or 0)
                )
            )
            if blocked > 0 or grew:
                episode["status"] = UNRESOLVED
                episode["unresolved_reason"] = (
                    "blocked_input" if blocked > 0 else "lag_grew"
                )
            elif (
                input_lag == 0
                and watermark_lag == 0
                and elapsed <= CONVERGENCE_WINDOW_SECONDS
            ):
                episode["status"] = TRANSIENT_CONVERGED
                episode["converged_at"] = now.isoformat()
                episode["convergence_seconds"] = round(elapsed, 3)
            elif elapsed > CONVERGENCE_WINDOW_SECONDS:
                episode["status"] = UNRESOLVED
                episode["unresolved_reason"] = "window_expired"
            else:
                pending.append(series)
            if episode["status"] != "CONVERGENCE_PENDING":
                self.completed_episodes.append(dict(episode))
                if episode["status"] == UNRESOLVED:
                    unresolved.append(series)
                    self.correctness_failure = True
                    self.event(
                        "boundary_convergence_unresolved",
                        anomaly=True,
                        series=series,
                        reason=episode.get("unresolved_reason"),
                    )
                else:
                    self.event(
                        "boundary_convergence_completed",
                        series=series,
                        convergence_seconds=episode.get("convergence_seconds"),
                    )
                self.boundary_episodes.pop(series, None)
        return {"pending": sorted(set(pending)), "unresolved": sorted(set(unresolved))}

    def _gate_detail(
        self,
        *,
        probes: dict[str, Any],
        db: Any,
        records: dict[str, dict[str, Any]],
        health: dict[str, Any],
        history: dict[str, Any],
    ) -> dict[str, Any]:
        ingestion, ingestion_error = _probe_payload(probes.get("ingestion"), ("state",))
        decision, decision_error = _probe_payload(
            probes.get("decision"), ("service_state",)
        )
        lanes, lanes_error = _probe_payload(probes.get("lanes"), ("lanes",))
        inputs, inputs_error = _probe_payload(probes.get("inputs"), ("inputs",))
        probe_errors = {
            name: error
            for name, error in {
                "ingestion": ingestion_error,
                "decision": decision_error,
                "lanes": lanes_error,
                "inputs": inputs_error,
            }.items()
            if error
        }
        lane_values = lanes.get("lanes", {}) if isinstance(lanes, dict) else {}
        input_values = inputs.get("inputs", {}) if isinstance(inputs, dict) else {}
        if not isinstance(lane_values, dict) or len(lane_values) < REQUIRED_LANES:
            probe_errors["lanes"] = PROBE_INDETERMINATE
        if not isinstance(input_values, dict) or any(
            key not in input_values for key in REQUIRED_INPUTS
        ):
            probe_errors["inputs"] = PROBE_INDETERMINATE
        probe_errors.update(
            _runtime_payload_errors(
                ingestion=ingestion,
                decision=decision,
                lanes=lanes,
                inputs=inputs,
                history=history,
            )
        )
        probe_valid = not probe_errors
        now = datetime.now(UTC)
        self._record_probe_status(probe_valid, now)
        if not probe_valid:
            self.probe_indeterminate_samples += 1
            self.event(
                "indeterminate_runtime_probe", anomaly=False, probes=probe_errors
            )
        input_lags: dict[str, int | None] = {}
        input_latest: dict[str, str | None] = {}
        for stream_key, timeframe in REQUIRED_INPUTS.items():
            value = (
                input_values.get(stream_key, {})
                if isinstance(input_values, dict)
                else {}
            )
            observed = (
                _parse_timestamp(value.get("latest_market_as_of"))
                if isinstance(value, dict)
                else None
            )
            series = f"{stream_key.split(':')[-2]}:{timeframe}"
            row = (
                history.get("required_series", {}).get(series, {})
                if isinstance(history, dict)
                else {}
            )
            expected = _parse_timestamp(
                row.get("expected_closed_boundary")
            ) or _floor_boundary(now, BOUNDARY_TIMEFRAMES[timeframe])
            input_lags[stream_key] = _interval_lag(
                observed, expected, BOUNDARY_TIMEFRAMES[timeframe]
            )
            input_latest[series] = observed.isoformat() if observed else None
        lane_lags: dict[str, int | None] = {}
        lane_lags_by_series: dict[str, int | None] = {}
        watermark_latest: dict[str, str | None] = {}
        for lane_id, lane in (
            lane_values.items() if isinstance(lane_values, dict) else ()
        ):
            series = self._lane_series(lane_id, lane)
            timeframe = series.rsplit(":", 1)[-1] if series else None
            value = lane.get("watermark", {}) if isinstance(lane, dict) else {}
            observed = (
                _parse_timestamp(value.get("latest_market_as_of"))
                if isinstance(value, dict)
                else None
            )
            row = history.get("required_series", {}).get(series, {}) if series else {}
            expected = (
                _parse_timestamp(row.get("expected_closed_boundary"))
                if isinstance(row, dict)
                else None
            )
            expected = expected or _floor_boundary(
                now, BOUNDARY_TIMEFRAMES.get(timeframe or "1h", timedelta(hours=1))
            )
            lag = _interval_lag(
                observed,
                expected,
                BOUNDARY_TIMEFRAMES.get(timeframe or "1h", timedelta(hours=1)),
            )
            lane_lags[str(lane_id)] = lag
            if series:
                lane_lags_by_series[series] = lag
                watermark_latest[series] = observed.isoformat() if observed else None
        blocked = (
            int(inputs.get("blocked_stream_count", 0) or 0)
            if isinstance(inputs, dict)
            else 0
        )
        configured = (
            int(decision.get("configured_lane_count", 0) or 0)
            if isinstance(decision, dict)
            else 0
        )
        active = (
            int(lanes.get("active_lane_count", 0) or 0)
            if isinstance(lanes, dict)
            else 0
        )
        lane_statuses = {
            str(key): str(value.get("status"))
            for key, value in lane_values.items()
            if isinstance(value, dict)
        }
        canonical_conflicts = sum(
            1
            for value in input_values.values()
            if isinstance(value, dict)
            and "conflict" in str(value.get("blocked_reason", "")).lower()
        )
        all_lanes_live = (
            configured == REQUIRED_LANES
            and active == REQUIRED_LANES
            and len(lane_statuses) == REQUIRED_LANES
            and all(status == "LIVE" for status in lane_statuses.values())
        )
        health_ok = len(health) == len(HEALTH_URLS) and all(
            isinstance(check, dict) and check.get("status_code") == 200
            for check in health.values()
        )
        docker_health_ok = len(records) == len(SERVICES) and all(
            record.get("state") == "running" and record.get("health") == "healthy"
            for record in records.values()
        )
        outbox = self._outbox_state(db, now)
        outbox_healthy = outbox.get("status") in {"DRAINED", "PENDING_DRAINING"}
        if outbox.get("status") == "PERSISTENT_GROWTH" and not self.state.get(
            "outbox_growth_reported"
        ):
            self.state["outbox_growth_reported"] = True
            self.correctness_failure = True
            self.event(
                "outbox_backlog_persistent_growth",
                anomaly=True,
                episode=outbox.get("episode"),
            )
        history_ready = bool(
            history.get("all_required_series_contiguous")
            and history.get("all_required_series_forward_current")
        )
        provenance = {
            series: {
                "canonical_history_current_at": row.get("last_close"),
                "canonical_history_checked_at": history.get("checked_at"),
                "outbox_oldest_epoch": db.get("outbox_oldest_epoch")
                if isinstance(db, dict)
                else None,
                "outbox_oldest_age_seconds": outbox.get("oldest_age_seconds"),
                "decision_input_latest_market_as_of": input_latest.get(series),
                "lane_watermark_latest_market_as_of": watermark_latest.get(series),
                "observed_at": now.isoformat(),
            }
            for series, row in (
                history.get("required_series", {}) if isinstance(history, dict) else {}
            ).items()
            if isinstance(row, dict)
        }
        episode_state = self._advance_boundary_episodes(
            history=history,
            input_lags=input_lags,
            lane_lags_by_series=lane_lags_by_series,
            provenance=provenance,
            blocked=blocked,
            probe_valid=probe_valid,
            now=now,
        )
        active_unresolved = sorted(
            series
            for series, episode in self.boundary_episodes.items()
            if episode.get("status") == UNRESOLVED
        )
        active_pending = sorted(self.boundary_episodes)
        lag_gate_status = (
            PROBE_INDETERMINATE
            if not probe_valid
            else (
                UNRESOLVED
                if episode_state["unresolved"] or active_unresolved
                else ("CONVERGENCE_PENDING" if active_pending else "PASS")
            )
        )
        ingestion_state = str((ingestion or {}).get("state", "")).lower()
        decision_state = str((decision or {}).get("service_state", "")).upper()
        inputs_current = probe_valid and all(
            value == 0 for value in input_lags.values()
        )
        lanes_current = (
            probe_valid
            and bool(lane_lags)
            and all(value == 0 for value in lane_lags.values())
        )
        detail = {
            "probe_status": "VALID" if probe_valid else PROBE_INDETERMINATE,
            "probe_errors": probe_errors,
            "health_ok": health_ok,
            "docker_health_ok": docker_health_ok,
            "ingestion_state": ingestion_state,
            "decision_state": decision_state,
            "active_lane_count": active,
            "configured_lane_count": configured,
            "lane_statuses": lane_statuses,
            "all_lanes_live": all_lanes_live,
            "blocked_stream_count": blocked,
            "canonical_conflict_count": canonical_conflicts,
            "outbox_pending": outbox.get("pending"),
            "outbox_oldest_age_seconds": outbox.get("oldest_age_seconds"),
            "outbox_status": outbox.get("status"),
            "outbox_healthy": outbox_healthy,
            "history_ready": history_ready,
            "history": history,
            "input_interval_lag": input_lags,
            "lane_watermark_interval_lag": lane_lags,
            "inputs_current": inputs_current,
            "lanes_current": lanes_current,
            "lag_gate_status": lag_gate_status,
            "boundary_episodes_pending": active_pending,
            "boundary_episodes_unresolved": sorted(
                set(episode_state["unresolved"] + active_unresolved)
            ),
            "provenance": provenance,
        }
        detail["ready"] = bool(
            probe_valid
            and health_ok
            and docker_health_ok
            and ingestion_state == "live"
            and decision_state == "RUNNING"
            and all_lanes_live
            and blocked == 0
            and canonical_conflicts == 0
            and outbox_healthy
            and history_ready
            and inputs_current
            and lanes_current
            and lag_gate_status == "PASS"
        )
        self._persist_gate_state()
        return detail

    def app_gate(self) -> tuple[bool, dict[str, Any]]:
        probes = {
            "ingestion": self._http_probe(PIPELINE_URLS["ingestion_runtime"]),
            "decision": self._http_probe(PIPELINE_URLS["decision_runtime"]),
            "lanes": self._http_probe(PIPELINE_URLS["decision_lanes"]),
            "inputs": self._http_probe(PIPELINE_URLS["decision_inputs"]),
        }
        db = self.db_probe()
        records = self.service_containers()
        history = self.history_probe()
        if getattr(self, "_cycle_deadline", None) is not None:
            self._cycle_probes = (probes, db, history, legacy.utc_now())
        health = self.last_health.get("checks", {})
        detail = self._gate_detail(
            probes=probes,
            db=db,
            records=records,
            health=health,
            history=history,
        )
        legacy.append_jsonl(
            self.samples / "pipeline_gate.jsonl",
            {"timestamp": legacy.utc_now(), "phase": self.phase, **detail},
        )
        self.state["last_gate"] = detail
        self._write_state()
        return bool(detail["ready"]), detail

    def discover_ports(self) -> dict[str, Any]:
        targets = {
            "ingestion": ("ingestion", 8003),
            "decision": ("decision", 8004),
            "prometheus": ("prometheus", 9090),
            "grafana": ("grafana", 3000),
            "otel_health": ("otel-collector", 13133),
        }
        ports: dict[str, Any] = {"status": self.args.status_port}
        for label, (service, container_port) in targets.items():
            code, output, error = self.compose(
                "port", service, str(container_port), timeout=15
            )
            ports[label] = (
                output.splitlines()[-1].strip()
                if code == 0 and output
                else {"error": error[:200]}
            )
        return ports

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

        self.state["image_proof"] = self._verify_image_proof()

        self.state["docker_environment"] = self.docker_environment()
        ncpu = int(self.state["docker_environment"].get("ncpu") or 0)
        mem_total = int(self.state["docker_environment"].get("mem_total_bytes") or 0)
        expected_mem = 8_320_294_912
        if ncpu != 4 or mem_total != expected_mem:
            self.state["validity"] = False
            self.state["environment_blocked"] = True
            self.event(
                "docker_envelope_mismatch",
                anomaly=True,
                expected_ncpu=4,
                observed_ncpu=ncpu,
                expected_mem_total_bytes=expected_mem,
                observed_mem_total_bytes=mem_total,
            )
            raise RuntimeError(
                "Docker VM does not match the certified 4-core/8320294912-byte envelope"
            )
        self.state["host_environment"] = self.host_environment()

        project_services = self._project_services()
        unexpected = sorted(project_services - set(SERVICES))
        missing = sorted(set(SERVICES) - project_services)
        records = self.service_containers()
        unhealthy = sorted(
            service
            for service, record in records.items()
            if record.get("state") != "running" or record.get("health") != "healthy"
        )
        if unexpected or missing or unhealthy:
            self.state["validity"] = False
            self.event(
                "run3_topology_not_ready",
                anomaly=True,
                unexpected_services=unexpected,
                missing_services=missing,
                unhealthy_services=unhealthy,
            )
            raise RuntimeError("run #3 seven-container topology is not fully healthy")

        cotenant_names = tuple(self.args.cotenant)
        if len(cotenant_names) != len(REQUIRED_COTENANTS) or set(cotenant_names) != set(
            REQUIRED_COTENANTS
        ):
            self.state["validity"] = False
            self.event(
                "cotenant_set_mismatch",
                anomaly=True,
                expected=list(REQUIRED_COTENANTS),
                observed=list(cotenant_names),
            )
            raise RuntimeError("exactly the two approved MCP co-tenants are required")

        for name in self.args.cotenant:
            record = self.inspect_container(name)
            if not record or record.get("state") != "running":
                self.state["validity"] = False
                self.event("cotenant_missing_before_start", anomaly=True, name=name)
                raise RuntimeError(f"approved co-tenant is not running: {name}")
            self.cotenant_baseline[name] = {
                "id": record["id"],
                "started_at": record["started_at"],
                "restart_count": record["restart_count"],
                "oom_killed": record["oom_killed"],
            }

        self.state["cotenant_baseline"] = self.cotenant_baseline
        self.state["sut_restart_baseline"] = {
            service: record["restart_count"] for service, record in records.items()
        }
        self.state["warmup_sut_restart_baseline"] = dict(
            self.state["sut_restart_baseline"]
        )
        self.state["sut_container_baseline"] = records
        self.state["topology"] = {
            "run_services": list(SERVICES),
            "core_path": list(CORE_SERVICES),
            "measurement_infrastructure": list(MEASUREMENT_SERVICES),
            "sut_apps": ["ingestion", "decision"],
            "dependencies": ["db", "broker"],
        }
        self.state["ports"] = self.discover_ports()
        self.state["config_hashes"] = {
            name: legacy.sha256_file(self.source_root / name)
            for name in (
                "docker-compose.yml",
                "configs/ingestion/global.yaml",
                "configs/decision/global.yaml",
                "configs/decision/assets/BTC.yaml",
                "configs/decision/assets/ETH.yaml",
                "configs/observability/prometheus.yml",
            )
        }
        self._freeze_tooling()
        fresh_health = self.health_sample()
        ready, prestart_gate = self.app_gate()
        self.state["prestart_readiness"] = {
            "health": fresh_health,
            "gate": prestart_gate,
        }
        if not ready:
            self.state["validity"] = False
            self.event(
                "prestart_readiness_failed",
                anomaly=True,
                health=fresh_health,
                gate=prestart_gate,
            )
            raise RuntimeError("fresh prestart readiness gate did not pass")
        self.state["preflight_at"] = legacy.utc_now()
        legacy.atomic_json(
            self.run_dir / "manifest.json",
            {
                "run_id": self.run_dir.name,
                "created_at": self.state["created_at"],
                "worktree": str(self.root),
                "source_export_root": str(self.source_root),
                "source_sha": self.args.source_sha,
                "compose_project": self.args.project,
                "compose_files": [
                    str(self.source_root / "docker-compose.yml"),
                    str(self.root / self.args.override_file),
                ],
                "config_hashes": self.state["config_hashes"],
                "frozen_tooling_hashes": self.state["frozen_tooling_hashes"],
                "source_export": self.state["source_export"],
                "image_proof": self.state["image_proof"],
                "prestart_readiness": self.state["prestart_readiness"],
                "test_only_resource_limits": TEST_ONLY_RESOURCE_LIMITS,
                "sut_limits_preserved": True,
                "docker_environment": self.state["docker_environment"],
                "host_environment": self.state["host_environment"],
                "ports": self.state["ports"],
                "run_services": list(SERVICES),
                "core_services": list(CORE_SERVICES),
                "measurement_services": list(MEASUREMENT_SERVICES),
                "sut_apps": ["ingestion", "decision"],
                "approved_cotenant_baseline": self.cotenant_baseline,
                "required_history": [
                    {
                        "venue": venue,
                        "instrument_id": instrument,
                        "timeframe": timeframe,
                    }
                    for venue, instrument, timeframe in REQUIRED_HISTORY
                ],
                "measurement_seconds_required": self.args.measurement_seconds,
                "warmup_seconds_required": self.args.warmup_seconds,
                "history_repair_path": "ingestion-owned runtime startup catch-up and HTF reconciliation",
            },
        )
        self._write_state()
        self.event(
            "run3_preflight_passed",
            service_count=len(records),
            project_services=sorted(project_services),
        )

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
            "last_gate": self.state.get("last_gate"),
            "state_valid": self.state.get("validity", True),
            "hard_failure": self.hard_failure,
            "correctness_failure": self.correctness_failure,
            "latest_anomalies": self.state.get("anomalies", [])[-10:],
        }
        legacy.atomic_json(self.live / "status.json", status)
        html = """<!doctype html><meta charset=utf-8><title>flipperAgent Ingestion + Decision soak</title>
<style>body{font:14px ui-monospace,monospace;background:#111;color:#eee;padding:1rem}pre{white-space:pre-wrap}</style>
<h1>flipperAgent Ingestion + Decision 24h soak</h1><pre id=x>loading</pre>
<script>async function r(){let x=await fetch('status.json?'+Date.now());document.querySelector('#x').textContent=JSON.stringify(await x.json(),null,2)}r();setInterval(r,5000)</script>"""
        (self.live / "status.html").write_text(html, encoding="utf-8")

    def drain(self) -> None:
        """Freeze measurement evidence without mutating the SUT."""

        self.phase = "evidence_freeze"
        self.sample(force=True)
        evidence = {
            "measurement_start_at": self.state.get("measurement_start_at"),
            "measurement_end_at": self.state.get("measurement_end_at"),
            "measurement_elapsed_seconds": self.state.get(
                "measurement_elapsed_seconds"
            ),
            "measurement_completed": self.measurement_completed,
            "validity": self.state.get("validity"),
            "files": {},
        }
        frozen_dir = self.run_dir / "measurement-evidence"
        frozen_dir.mkdir(exist_ok=False)
        for path in sorted(self.samples.glob("*.jsonl")):
            data = path.read_bytes()
            with (frozen_dir / path.name).open("xb") as handle:
                handle.write(data)
            evidence["files"][path.name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        with (frozen_dir / "summary.json").open("x", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2, sort_keys=True)
        self.state["measurement_evidence_summary_sha256"] = legacy.sha256_file(
            frozen_dir / "summary.json"
        )
        self.event(
            "measurement_evidence_frozen",
            measurement_clock_seconds=self.measurement_elapsed(),
        )
        self._write_state()

    def begin_measurement(self, *, warmup_only: bool = False) -> None:
        """Recheck the frozen attempt; never restore an earlier measurement clock."""
        if (
            self.state.get("measurement_start_at")
            or self.measurement_started_monotonic is not None
        ):
            raise RuntimeError(
                "measurement resume is forbidden; use a new run directory"
            )
        if (
            self.stop_event.is_set()
            or self.hard_failure
            or self.correctness_failure
            or self.state.get("validity") is not True
        ):
            raise RuntimeError("invalid attempt cannot start measurement")
        self._verify_frozen_inputs()
        code, head, _ = self.command(["git", "rev-parse", "HEAD"], timeout=15)
        if code != 0 or head != self.args.source_sha:
            raise RuntimeError("HEAD changed before measurement")
        proof = self._verify_image_proof()
        records = self.service_containers()
        if self._project_services() != set(SERVICES) or set(records) != set(SERVICES):
            raise RuntimeError("final gate requires exactly seven services")
        baseline = self.state.get("prestart_image_baseline", {})
        if set(baseline) != set(SERVICES):
            raise RuntimeError("missing frozen container image baseline")
        for service, record in records.items():
            if (
                record.get("state") != "running"
                or record.get("health") != "healthy"
                or record.get("oom_killed")
            ):
                raise RuntimeError(f"service not healthy at final gate: {service}")
            code, image_id, _ = self.command(
                ["docker", "inspect", record["id"], "--format", "{{.Image}}"],
                timeout=15,
            )
            expected = (
                proof["image_id"]
                if service in {"ingestion", "decision"}
                else baseline[service]
            )
            if code != 0 or image_id != expected or image_id != baseline[service]:
                raise RuntimeError(f"actual container image changed: {service}")
        if set(self.cotenant_baseline) != set(REQUIRED_COTENANTS):
            raise RuntimeError("missing approved MCP baseline")
        for name, expected in self.cotenant_baseline.items():
            record = self.inspect_container(name)
            if (
                not record
                or record.get("state") != "running"
                or any(record.get(key) != value for key, value in expected.items())
            ):
                raise RuntimeError(f"approved MCP identity changed: {name}")
        self.health_sample()
        ready, _ = self.app_gate()
        self._verify_frozen_inputs()
        if (
            not ready
            or self.stop_event.is_set()
            or self.hard_failure
            or self.correctness_failure
            or self.state.get("validity") is not True
        ):
            raise RuntimeError("fresh final readiness gate failed")
        self.state["final_prestart_gate_at"] = legacy.utc_now()
        if (
            not self._cadence_check()
            or self.warmup_stable_since is None
            or time.monotonic() - self.warmup_stable_since < self.args.warmup_seconds
        ):
            raise RuntimeError("fresh final cadence-qualified warm-up gate failed")
        if warmup_only:
            return
        self.phase = "measurement"
        self.measurement_started_monotonic = time.monotonic()
        self.state.update(
            measurement_start_at=legacy.utc_now(),
            measurement_start_monotonic=self.measurement_started_monotonic,
            measurement_elapsed_seconds=0.0,
            measurement_end_at=None,
            measurement_completed=False,
        )
        self.measurement_completed = False
        self.load.write_snapshot()
        self._write_state()
        self.event(
            "measurement_started", duration_seconds=self.args.measurement_seconds
        )

    def measure(self) -> None:
        self.begin_measurement()
        deadline = self.measurement_started_monotonic + self.args.measurement_seconds
        first = True
        while time.monotonic() < deadline:
            if (
                self.stop_event.is_set()
                or self.hard_failure
                or self.correctness_failure
                or self.state.get("validity") is not True
            ):
                break
            self.sample(force=first)
            first = False
            self.stop_event.wait(min(5.0, max(0.0, deadline - time.monotonic())))
        self.sample(force=True)
        elapsed = self.measurement_elapsed()
        self.measurement_completed = bool(
            elapsed >= self.args.measurement_seconds
            and not self.stop_event.is_set()
            and not self.hard_failure
            and not self.correctness_failure
            and self.state.get("validity") is True
            and self._verify_frozen_tooling()
        )
        self.state.update(
            measurement_elapsed_seconds=elapsed,
            measurement_end_at=legacy.utc_now(),
            measurement_completed=self.measurement_completed,
        )
        if not self.measurement_completed:
            self.state["validity"] = False
        self.measurement_started_monotonic = None
        self._write_state()
        self.event("measurement_interval_closed", completed=self.measurement_completed)

    def run(self) -> int:
        """Run warm-up, or the full measurement only when explicitly requested."""

        if (
            self.state.get("measurement_start_at")
            or self.state.get("measurement_end_at")
            or self.state.get("validity") is not True
            or self.state.get("warmup_completed_at")
        ):
            self.event("attempt_resume_rejected", anomaly=True)
            return 2
        try:
            self.start_status_server()
            self.state["measurement_seconds_required"] = self.args.measurement_seconds
            if not self.state.get("measurement_start_at"):
                self.preflight()
                images = {}
                for service, record in self.state["sut_container_baseline"].items():
                    code, image_id, _ = self.command(
                        ["docker", "inspect", record["id"], "--format", "{{.Image}}"],
                        timeout=15,
                    )
                    if code != 0 or not image_id.startswith("sha256:"):
                        raise RuntimeError(f"cannot freeze actual image: {service}")
                    images[service] = image_id
                self.state["prestart_image_baseline"] = images
                self._write_state()
                self.warmup()
                if self.args.warmup_only:
                    self.begin_measurement(warmup_only=True)
                    self.load.stop()
                    self.phase = "warmup_complete"
                    self.state["warmup_completed_at"] = legacy.utc_now()
                    self.state["measurement_start_at"] = None
                    self.state["measurement_elapsed_seconds"] = 0.0
                    self._persist_gate_state()
                    self._write_state()
                    legacy.atomic_json(
                        self.run_dir / "warmup_proof.json",
                        {
                            "run_id": self.run_dir.name,
                            "project": self.args.project,
                            "source_sha": self.args.source_sha,
                            "phase": self.phase,
                            "warmup_completed_at": self.state["warmup_completed_at"],
                            "measurement_start_at": None,
                            "measurement_elapsed_seconds": 0.0,
                            "topology": self.state.get("topology"),
                            "ports": self.state.get("ports"),
                            "last_gate": self.state.get("last_gate"),
                            "frozen_tooling_hashes": self.state.get(
                                "frozen_tooling_hashes"
                            ),
                            "approved_cotenant_baseline": self.cotenant_baseline,
                        },
                    )
                    if self.status_server:
                        self.status_server.shutdown()
                    return 0
            if not self.state.get("measurement_end_at"):
                self.start_load()
                self.measure()
                self.load.stop()
            if (
                not self.measurement_completed
                or self.state.get("validity") is not True
                or self.stop_event.is_set()
                or self.hard_failure
                or self.correctness_failure
            ):
                raise RuntimeError(
                    "incomplete or invalid measurement; recovery forbidden"
                )
            for filename in SAMPLING_POLICIES:
                if self._measurement_gap_summary(filename)["exceeds_threshold"]:
                    raise RuntimeError(
                        f"incomplete measurement evidence; recovery forbidden: {filename}"
                    )
            if self._measurement_probe_gap_summary()["exceeds_threshold"]:
                raise RuntimeError("invalid probe evidence; recovery forbidden")
            self.drain()
            if (
                self.state.get("validity") is not True
                or self.stop_event.is_set()
                or self.hard_failure
                or self.correctness_failure
            ):
                raise RuntimeError("invalid evidence freeze; recovery forbidden")
            if not self.state.get("recovery_finished_at"):
                self.recovery()
            audit = self.final_audit()
            if self.status_server:
                self.status_server.shutdown()
            terminal_status = str(audit.get("terminal_status", ""))
            return (
                0
                if terminal_status
                in {
                    "INGESTION_DECISION_24H_SOAK_PASSED",
                    "INGESTION_DECISION_24H_SOAK_PASSED_WITH_WARNINGS",
                }
                else 2
            )
        except KeyboardInterrupt:
            self.stop_event.set()
            self.load.stop()
            self.state["validity"] = False
            self._write_state()
            self.final_audit("interrupted")
            try:
                self.cleanup()
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve interruption evidence
                self.event(
                    "cleanup_after_interrupt_error",
                    anomaly=True,
                    error=f"{type(cleanup_exc).__name__}: {cleanup_exc}",
                )
            return 130
        except Exception as exc:  # noqa: BLE001 - persist partial audit evidence
            self.stop_event.set()
            self.load.stop()
            self.state["validity"] = False
            self.event(
                "harness_failure", anomaly=True, error=f"{type(exc).__name__}: {exc}"
            )
            self._write_state()
            try:
                self.final_audit(f"{type(exc).__name__}: {exc}")
            except Exception as audit_exc:  # noqa: BLE001 - preserve primary failure
                self.event(
                    "final_audit_failure",
                    anomaly=True,
                    error=f"{type(audit_exc).__name__}: {audit_exc}",
                )
            try:
                self.cleanup()
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve failure evidence
                self.event(
                    "cleanup_after_failure_error",
                    anomaly=True,
                    error=f"{type(cleanup_exc).__name__}: {cleanup_exc}",
                )
            return 1

    def _wait_recovery_gate(
        self, timeout: float = 240.0
    ) -> tuple[bool, dict[str, Any]]:
        deadline = time.monotonic() + timeout
        detail: dict[str, Any] = {}
        while time.monotonic() < deadline and not self.stop_event.is_set():
            self.sample()
            ready, detail = self.app_gate()
            if ready:
                return True, detail
            time.sleep(15)
        return False, detail

    def recovery_step(self, label: str, *services: str) -> None:
        started = legacy.utc_now()
        code, output, error = self.compose("restart", *services, timeout=180)
        ready, detail = self._wait_recovery_gate(timeout=240)
        health = self.health_sample()
        self.event(
            "recovery_step",
            label=label,
            services=list(services),
            started_at=started,
            finished_at=legacy.utc_now(),
            exit_code=code,
            output=output[-500:],
            error=error[-500:],
            converged=ready,
            gate=detail,
            health=health,
        )
        if code != 0 or not ready:
            self.state["validity"] = False
            self.correctness_failure = True

    def recovery(self) -> None:
        self.phase = "recovery"
        self.state["recovery_started_at"] = legacy.utc_now()
        self._write_state()
        self.recovery_step("broker_restart", "broker")
        self.recovery_step("decision_restart", "decision")
        self.recovery_step("ingestion_restart", "ingestion")
        self.recovery_step("database_restart", "db")
        self.recovery_step(
            "observability_restart",
            "otel-collector",
            "prometheus",
            "grafana",
        )
        self.recovery_step("corrected_topology_restart", *SERVICES)
        self.state["recovery_finished_at"] = legacy.utc_now()
        self._write_state()

    def _resource_summary(
        self, records: list[dict[str, Any]], key: str
    ) -> dict[str, Any]:
        values: dict[str, list[float]] = {}
        points: dict[str, list[tuple[float, float]]] = {}
        for item in records:
            timestamp = _parse_timestamp(item.get("timestamp"))
            if timestamp is None:
                continue
            aggregate = item.get(key, {})
            if not isinstance(aggregate, dict):
                continue
            for field, target in (("rss_bytes", "rss"), ("cpu_core_equivalent", "cpu")):
                value = aggregate.get(field)
                if isinstance(value, (int, float)):
                    values.setdefault(target, []).append(float(value))
                    if target == "rss":
                        points.setdefault("rss", []).append(
                            (timestamp.timestamp(), float(value))
                        )
        rss = values.get("rss", [])
        cpu = values.get("cpu", [])
        return {
            "sample_count": len(rss),
            "rss_p50_bytes": legacy.percentile(rss, 0.50),
            "rss_p95_bytes": legacy.percentile(rss, 0.95),
            "rss_p99_bytes": legacy.percentile(rss, 0.99),
            "rss_max_bytes": max(rss) if rss else None,
            "rss_robust_slope_bytes_per_second": _slope(points.get("rss", [])),
            "cpu_p50_core_equivalent": legacy.percentile(cpu, 0.50),
            "cpu_p95_core_equivalent": legacy.percentile(cpu, 0.95),
            "cpu_max_core_equivalent": max(cpu) if cpu else None,
        }

    def _jsonl_records(self, path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not path.exists():
            return records
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("phase") == "measurement":
                records.append(item)
        return records

    def _measurement_gap_summary(self, filename: str) -> dict[str, Any]:
        start = _parse_timestamp(self.state.get("measurement_start_at"))
        end = _parse_timestamp(self.state.get("measurement_end_at"))
        records = self._jsonl_records(self.samples / filename)
        threshold = SAMPLING_POLICIES[filename]["max_gap_seconds"]
        timestamps = sorted(
            timestamp
            for item in records
            if (timestamp := _parse_timestamp(item.get("timestamp"))) is not None
            and start is not None
            and end is not None
            and start <= timestamp <= end
        )
        gaps = [
            (current - previous).total_seconds()
            for previous, current in pairwise(timestamps)
        ]
        missing = not timestamps or start is None or end is None or end <= start
        if not missing:
            gaps.extend(
                [
                    (timestamps[0] - start).total_seconds(),
                    (end - timestamps[-1]).total_seconds(),
                ]
            )
        if filename == "resource_samples.jsonl":
            missing = missing or any(
                not isinstance(item.get("run"), dict)
                or set(item["run"]) != set(SERVICES)
                or any(
                    not isinstance(record, dict)
                    or not isinstance(record.get("memory_usage_bytes"), (int, float))
                    or not isinstance(record.get("memory_limit_bytes"), (int, float))
                    or record["memory_limit_bytes"] <= 0
                    or not isinstance(record.get("cpu_percent"), (int, float))
                    for record in item["run"].values()
                )
                for item in records
            )
        maximum = max(gaps, default=0.0)
        return {
            "sample_count": len(timestamps),
            "max_gap_seconds": round(maximum, 3),
            "threshold_seconds": threshold,
            "missing_or_invalid_evidence": missing,
            "exceeds_threshold": missing or maximum > threshold,
        }

    def _measurement_probe_gap_summary(self) -> dict[str, Any]:
        records = sorted(
            (
                timestamp,
                item.get("probe_status"),
            )
            for item in self._jsonl_records(self.samples / "pipeline_gate.jsonl")
            if (timestamp := _parse_timestamp(item.get("timestamp"))) is not None
        )
        open_at: datetime | None = None
        maximum = 0.0
        indeterminate_samples = 0
        for timestamp, status in records:
            if status != "VALID":
                indeterminate_samples += 1
                open_at = open_at or timestamp
            elif open_at is not None:
                maximum = max(maximum, (timestamp - open_at).total_seconds())
                open_at = None
        if open_at is not None:
            end = _parse_timestamp(self.state.get("measurement_end_at"))
            if end is None and records:
                end = records[-1][0]
            if end is not None:
                maximum = max(maximum, (end - open_at).total_seconds())
        self.max_probe_gap_seconds = max(self.max_probe_gap_seconds, maximum)
        exceeds = maximum > PROBE_GAP_THRESHOLD_SECONDS
        if exceeds:
            self.state["validity"] = False
            if not self.state.get("measurement_probe_gap_reported"):
                self.state["measurement_probe_gap_reported"] = True
                self.event(
                    "measurement_probe_gap_over_threshold",
                    anomaly=True,
                    gap_seconds=round(maximum, 3),
                    threshold_seconds=PROBE_GAP_THRESHOLD_SECONDS,
                )
        return {
            "indeterminate_samples": indeterminate_samples,
            "max_gap_seconds": round(maximum, 3),
            "threshold_seconds": PROBE_GAP_THRESHOLD_SECONDS,
            "exceeds_threshold": exceeds,
        }

    def final_audit(self, error: str | None = None) -> dict[str, Any]:
        self.phase = "finalizing"
        self.sample(force=True)
        resources: list[dict[str, Any]] = []
        path = self.samples / "resource_samples.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    resources.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        measurement = [item for item in resources if item.get("phase") == "measurement"]
        sampling_gap_summary = {
            filename: self._measurement_gap_summary(filename)
            for filename in SAMPLING_POLICIES
        }
        probe_gap_summary = self._measurement_probe_gap_summary()
        if any(item["exceeds_threshold"] for item in sampling_gap_summary.values()):
            self.state["validity"] = False
            if not self.state.get("measurement_sampling_gap_reported"):
                self.state["measurement_sampling_gap_reported"] = True
                self.event(
                    "measurement_sampling_gap_over_threshold",
                    anomaly=True,
                    gaps=sampling_gap_summary,
                    threshold_seconds=PROBE_GAP_THRESHOLD_SECONDS,
                )
        service_values: dict[str, dict[str, list[float]]] = {
            service: {"rss": [], "cpu": [], "limit": []} for service in SERVICES
        }
        for item in measurement:
            for service, record in item.get("run", {}).items():
                if not isinstance(record, dict):
                    continue
                usage = record.get("memory_usage_bytes")
                cpu = record.get("cpu_percent")
                limit = record.get("memory_limit_bytes")
                if isinstance(usage, (int, float)):
                    service_values.setdefault(
                        service, {"rss": [], "cpu": [], "limit": []}
                    )["rss"].append(float(usage))
                if isinstance(cpu, (int, float)):
                    service_values.setdefault(
                        service, {"rss": [], "cpu": [], "limit": []}
                    )["cpu"].append(float(cpu) / 100.0)
                if (
                    isinstance(usage, (int, float))
                    and isinstance(limit, (int, float))
                    and limit > 0
                ):
                    service_values.setdefault(
                        service, {"rss": [], "cpu": [], "limit": []}
                    )["limit"].append(float(usage) / float(limit))
        service_summary = {
            service: {
                "sample_count": len(values["rss"]),
                "rss_p50_bytes": legacy.percentile(values["rss"], 0.50),
                "rss_p95_bytes": legacy.percentile(values["rss"], 0.95),
                "rss_p99_bytes": legacy.percentile(values["rss"], 0.99),
                "rss_max_bytes": max(values["rss"]) if values["rss"] else None,
                "cpu_p95_core_equivalent": legacy.percentile(values["cpu"], 0.95),
                "cpu_max_core_equivalent": max(values["cpu"])
                if values["cpu"]
                else None,
                "memory_limit_utilization_max": max(values["limit"])
                if values["limit"]
                else None,
            }
            for service, values in service_values.items()
        }
        core_summary = self._resource_summary(measurement, "core_path_aggregate")
        vm_summary = self._resource_summary(measurement, "whole_vm_container_aggregate")
        measurement_complete = bool(
            self.state.get("measurement_start_at")
            and self.state.get("measurement_end_at")
            and float(self.state.get("measurement_elapsed_seconds", 0.0))
            >= self.args.measurement_seconds
        )
        per_service_limits_ok = all(
            summary["memory_limit_utilization_max"] is not None
            and summary["memory_limit_utilization_max"] < 1.0
            for summary in service_summary.values()
        )
        measurement_gate_records: list[dict[str, Any]] = []
        gate_path = self.samples / "pipeline_gate.jsonl"
        if gate_path.exists():
            for line in gate_path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("phase") == "measurement":
                    measurement_gate_records.append(item)
        valid_gate_records = [
            item
            for item in measurement_gate_records
            if item.get("probe_status") == "VALID"
        ]
        convergence_values = [
            float(item["convergence_seconds"])
            for item in self.completed_episodes
            if item.get("status") == TRANSIENT_CONVERGED
            and isinstance(item.get("convergence_seconds"), (int, float))
        ]
        unresolved_episodes = [
            item for item in self.completed_episodes if item.get("status") == UNRESOLVED
        ]
        correctness = {
            "measurement_gate_samples": len(measurement_gate_records),
            "valid_measurement_gate_samples": len(valid_gate_records),
            "indeterminate_probe_samples": sum(
                1
                for item in measurement_gate_records
                if item.get("probe_status") == PROBE_INDETERMINATE
            ),
            "no_blocked_inputs_observed": all(
                int(item.get("blocked_stream_count", -1)) == 0
                for item in valid_gate_records
            ),
            "three_live_lanes_observed": all(
                bool(item.get("all_lanes_live")) for item in valid_gate_records
            ),
            "no_canonical_conflicts_observed": all(
                int(item.get("canonical_conflict_count", -1)) == 0
                for item in valid_gate_records
            ),
            "history_forward_and_contiguous_observed": all(
                bool(item.get("history_ready")) for item in valid_gate_records
            ),
            "no_unresolved_boundary_episodes": not unresolved_episodes
            and not any(
                episode.get("status") == UNRESOLVED
                for episode in self.boundary_episodes.values()
            ),
            "no_open_boundary_episodes": not self.boundary_episodes,
            "no_open_outbox_episode": self.outbox_episode is None,
            "measurement_probe_gaps_within_threshold": not probe_gap_summary[
                "exceeds_threshold"
            ],
            "measurement_sampling_gaps_within_threshold": all(
                not item["exceeds_threshold"] for item in sampling_gap_summary.values()
            ),
        }
        correctness_ok = bool(valid_gate_records) and all(
            value
            for key, value in correctness.items()
            if key != "measurement_gate_samples"
            and key != "indeterminate_probe_samples"
            and key != "valid_measurement_gate_samples"
        )
        resource_gates = {
            "all_expected_measurement_samples_present": bool(measurement),
            "all_run_services_sampled": all(
                summary["sample_count"] > 0 for summary in service_summary.values()
            ),
            "per_service_memory_below_limit": per_service_limits_ok,
            "core_path_cpu_observed_within_4_core_envelope": (
                core_summary.get("cpu_max_core_equivalent") or 0
            )
            <= 4.0,
            "ingestion_decision_no_oom_or_restart": not self.hard_failure,
            "measurement_completed": measurement_complete,
        }
        if error:
            if not self.state.get("measurement_start_at"):
                status = (
                    "INGESTION_DECISION_24H_SOAK_BLOCKED_ENVIRONMENT"
                    if self.state.get("environment_blocked")
                    else "INGESTION_DECISION_24H_SOAK_BLOCKED_HISTORY_PREPARATION"
                )
            else:
                status = "INGESTION_DECISION_24H_SOAK_INCONCLUSIVE_EVIDENCE"
        elif not measurement_complete or self.state.get("validity") is not True:
            status = "INGESTION_DECISION_24H_SOAK_INCONCLUSIVE_EVIDENCE"
        elif not correctness_ok or self.correctness_failure:
            status = "INGESTION_DECISION_24H_SOAK_FAILED_CORRECTNESS"
        elif not all(resource_gates.values()):
            status = "INGESTION_DECISION_24H_SOAK_FAILED_RESOURCE_ENVELOPE"
        elif self.warnings or self.state.get("anomalies"):
            status = "INGESTION_DECISION_24H_SOAK_PASSED_WITH_WARNINGS"
        else:
            status = "INGESTION_DECISION_24H_SOAK_PASSED"
        audit = {
            "terminal_status": status,
            "error": error,
            "run_id": self.run_dir.name,
            "project": self.args.project,
            "source_sha": self.args.source_sha,
            "state": self.state,
            "measurement_tooling_integrity": {
                "frozen_tooling_hashes": self.state.get("frozen_tooling_hashes"),
                "frozen_tooling_at": self.state.get("frozen_tooling_at"),
                "no_harness_changes_after_measurement_start": True,
            },
            "measurement_window": {
                "original_required_seconds": self.state.get(
                    "original_measurement_seconds_required",
                    self.args.measurement_seconds,
                ),
                "extension_seconds": self.state.get("measurement_extension_seconds", 0),
                "effective_required_seconds": self.args.measurement_seconds,
                "measurement_start_at": self.state.get("measurement_start_at"),
                "measurement_end_at": self.state.get("measurement_end_at"),
            },
            "post_measurement_recovery": self.state.get(
                "post_measurement_recovery",
                {
                    "status": "NOT_RECORDED",
                    "reason": "run did not reach post-measurement finalization",
                },
            ),
            "scope": {
                "sut_apps": ["ingestion", "decision"],
                "dependencies": ["db", "broker"],
                "measurement_infrastructure": list(MEASUREMENT_SERVICES),
                "run_services": list(SERVICES),
                "external_cotenants": list(self.args.cotenant),
            },
            "history_preparation": {
                "path": str(self.samples / "history_preparation.jsonl"),
                "repair_path": "canonical Ingestion runtime startup catch-up and HTF reconciliation",
                "required_series": list(REQUIRED_INPUTS),
            },
            "resource_gates": resource_gates,
            "correctness_gates": correctness,
            "probe_gap_summary": probe_gap_summary,
            "sampling_gap_summary": sampling_gap_summary,
            "outbox_episodes": self.outbox_episodes,
            "convergence_distribution": {
                "count": len(convergence_values),
                "p50_seconds": percentile(convergence_values, 0.50),
                "p95_seconds": percentile(convergence_values, 0.95),
                "max_seconds": max(convergence_values) if convergence_values else None,
                "worst_episode": max(
                    (
                        item
                        for item in self.completed_episodes
                        if item.get("status") == TRANSIENT_CONVERGED
                    ),
                    key=lambda item: float(item.get("convergence_seconds", 0.0)),
                    default=None,
                ),
                "window_seconds": CONVERGENCE_WINDOW_SECONDS,
                "is_production_slo": False,
            },
            "core_path_resource_summary": core_summary,
            "whole_vm_resource_summary": vm_summary,
            "service_summary": service_summary,
            "approved_cotenant_baseline": self.cotenant_baseline,
            "evidence_paths": {
                "manifest": str(self.run_dir / "manifest.json"),
                "run_state": str(self.state_path),
                "resource_samples": str(self.samples / "resource_samples.jsonl"),
                "cotenants": str(self.samples / "cotenant_resource_samples.jsonl"),
                "container_state": str(self.samples / "container_state.jsonl"),
                "health": str(self.samples / "http_health.jsonl"),
                "pipeline": str(self.samples / "pipeline_metrics.jsonl"),
                "pipeline_gate": str(self.samples / "pipeline_gate.jsonl"),
                "history_preparation": str(self.samples / "history_preparation.jsonl"),
                "db_valkey": str(self.samples / "db_valkey.jsonl"),
                "api_load": str(self.samples / "api_load.jsonl"),
                "storage_growth": str(self.samples / "storage_growth.jsonl"),
                "sampler_timing": str(self.samples / "sampler_timing.jsonl"),
                "events": str(self.events_path),
            },
        }
        legacy.atomic_json(self.run_dir / "final_audit.json", audit)
        report = self.run_dir / "ingestion-decision-24h-soak-audit.md"
        report.write_text(
            "# Ingestion + Decision 24h Soak Audit\n\n"
            f"- Status: `{status}`\n"
            f"- Run: `{self.run_dir.name}`\n"
            f"- Source SHA: `{self.args.source_sha}`\n"
            f"- Measurement start: `{self.state.get('measurement_start_at')}`\n"
            f"- Measurement end: `{self.state.get('measurement_end_at')}`\n"
            f"- Measurement clock seconds: `{self.state.get('measurement_elapsed_seconds', 0)}`\n\n"
            f"- Effective measurement requirement: `{self.args.measurement_seconds}` seconds\n"
            f"- Harness-only extension: `{self.state.get('measurement_extension_seconds', 0)}` seconds\n\n"
            f"- Post-measurement recovery: `{self.state.get('post_measurement_recovery', {}).get('status', 'NOT_RECORDED')}`\n\n"
            "The machine-readable audit and raw JSONL evidence are under this run directory.\n",
            encoding="utf-8",
        )
        decision_report = (
            self.run_dir
            / "orchestrator-decision-ingestion-decision-24h-soak-resource-concurrency-v1.md"
        )
        decision_report.write_text(
            "# Orchestrator Decision: Ingestion + Decision 24h Soak\n\n"
            f"- Status: `{status}`\n"
            f"- Run: `{self.run_dir.name}`\n"
            f"- Source SHA: `{self.args.source_sha}`\n"
            f"- Measurement clock seconds: `{self.state.get('measurement_elapsed_seconds', 0)}`\n\n"
            f"Machine-readable audit: `{self.run_dir / 'final_audit.json'}`\n",
            encoding="utf-8",
        )
        self.phase = "complete"
        self.state["terminal_status"] = status
        self._write_state()
        return audit

    def cleanup(self) -> None:
        if self.status_server:
            self.status_server.shutdown()
        # Failure cleanup never starts new Docker processes while the guard
        # is terminating its child group. Explicit stop-run3 owns Compose down.
        self.event("failure_cleanup_runtime_and_volumes_preserved")


def main() -> int:
    args = legacy.parse_args()
    if len(args.cotenant) != len(REQUIRED_COTENANTS) or set(args.cotenant) != set(
        REQUIRED_COTENANTS
    ):
        raise SystemExit(
            "exactly --cotenant mcp-cbm and --cotenant mcp-gitnexus are required"
        )
    soak = Soak(args)

    def stop_handler(_signum: int, _frame: Any) -> None:
        soak.stop_event.set()

    legacy.signal.signal(legacy.signal.SIGTERM, stop_handler)
    legacy.signal.signal(legacy.signal.SIGINT, stop_handler)
    return soak.run()


if __name__ == "__main__":
    raise SystemExit(main())
