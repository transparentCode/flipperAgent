#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import valkey.asyncio as avalkey

from apps.ingestion_app.control_plane.service import IngestionControlService
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetDesiredState,
    IngestionAssetUpsertRequest,
)
from libs.common.db.pool_manager import DBPoolManager
from libs.contracts.schemas import IngestionCommandType


DEFAULT_STACK_SERVICES = [
    "db",
    "broker",
    "worker-streams",
    "worker-queue",
    "signal-worker",
    "strategy-worker",
    "risk-worker",
    "execution-worker",
    "portfolio-worker",
]
DEFAULT_CONTAINERS = [
    "flipperagent-worker-streams-1",
    "flipperagent-worker-queue-1",
    "flipperagent-broker-1",
    "flipperagent-db-1",
]
DEFAULT_BROKER_CONTAINER = "flipperagent-broker-1"
DEFAULT_STREAM_KEY = "stream:ohlcv:solusdt:1m"
_MEMORY_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*$")


@dataclass
class DockerMemoryPoint:
    timestamp: float
    container: str
    memory_usage_bytes: int
    memory_limit_bytes: int | None
    memory_percent: float | None


class SoakRuntimeConfig:
    def get(self, key_path: str, default: Any = None):
        mapping = {
            "postgres.user": os.getenv("POSTGRES_USER", "flipper"),
            "postgres.password": os.getenv("POSTGRES_PASSWORD", "flipperpass"),
            "postgres.host": os.getenv("POSTGRES_HOST", "localhost"),
            "postgres.port": int(os.getenv("POSTGRES_PORT", "5432")),
            "postgres.database": os.getenv("POSTGRES_DB", "flipper_db"),
            "postgres.pool.min_size": 1,
            "postgres.pool.max_size": 2,
            "valkey.uri": os.getenv("VALKEY_URI", "redis://localhost:6380/0"),
        }
        if key_path in mapping:
            return mapping[key_path]
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded Docker-backed ingestion runtime memory soak.",
    )
    parser.add_argument("--cycles", type=int, default=5, help="Number of add/pause/resume/remove cycles.")
    parser.add_argument("--symbol", default="SOLUSDT", help="Runtime-managed symbol to exercise.")
    parser.add_argument("--base-timeframe", default="1m", help="Base timeframe for ingestion runtime.")
    parser.add_argument(
        "--publish-timeframe",
        action="append",
        dest="publish_timeframes",
        default=["1m"],
        help="Publish timeframe to monitor. May be passed multiple times.",
    )
    parser.add_argument(
        "--historical-backfill-days",
        type=int,
        default=1,
        help="Backfill window used during runtime addition.",
    )
    parser.add_argument(
        "--pause-flat-seconds",
        type=float,
        default=10.0,
        help="How long stream length must stay flat while paused.",
    )
    parser.add_argument(
        "--sample-interval-seconds",
        type=float,
        default=5.0,
        help="Docker memory sampling interval.",
    )
    parser.add_argument(
        "--live-timeout-seconds",
        type=float,
        default=240.0,
        help="Timeout for LIVE transitions and resumed stream growth.",
    )
    parser.add_argument(
        "--remove-timeout-seconds",
        type=float,
        default=180.0,
        help="Timeout for asset removal cleanup.",
    )
    parser.add_argument(
        "--memory-growth-threshold-mib",
        type=float,
        default=128.0,
        help="Maximum peak growth per container over baseline before failing.",
    )
    parser.add_argument(
        "--memory-final-growth-threshold-mib",
        type=float,
        default=96.0,
        help="Maximum final growth per container over baseline before failing.",
    )
    parser.add_argument(
        "--container",
        action="append",
        dest="containers",
        default=None,
        help="Container name to sample. May be passed multiple times.",
    )
    parser.add_argument(
        "--start-stack",
        action="store_true",
        help="Start the Docker stack before running the soak.",
    )
    parser.add_argument(
        "--keep-stack",
        action="store_true",
        help="Leave Docker services running after the soak.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/ingestion_runtime_memory_soak.json"),
        help="Path to write the JSON soak report.",
    )
    return parser.parse_args()


def run_cmd(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def broker_cli(*args: str) -> str:
    result = run_cmd(["docker", "exec", DEFAULT_BROKER_CONTAINER, "valkey-cli", *args])
    return result.stdout.strip()


def parse_memory_bytes(raw: str) -> int | None:
    unit_scale = {
        "b": 1,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
    }
    match = _MEMORY_PATTERN.match(raw.strip())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    scale = unit_scale.get(unit)
    if scale is None:
        return None
    return int(value * scale)


def sample_docker_memory(containers: list[str]) -> list[DockerMemoryPoint]:
    cmd = ["docker", "stats", "--no-stream", "--format", "{{ json . }}", *containers]
    result = run_cmd(cmd)
    now = time.time()
    points: list[DockerMemoryPoint] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        memory_cell = str(payload.get("MemUsage", ""))
        used_raw, _, limit_raw = memory_cell.partition("/")
        memory_usage_bytes = parse_memory_bytes(used_raw) or 0
        memory_limit_bytes = parse_memory_bytes(limit_raw) if limit_raw else None
        memory_percent_raw = str(payload.get("MemPerc", "")).strip().rstrip("%")
        memory_percent = float(memory_percent_raw) if memory_percent_raw else None
        points.append(
            DockerMemoryPoint(
                timestamp=now,
                container=str(payload["Name"]),
                memory_usage_bytes=memory_usage_bytes,
                memory_limit_bytes=memory_limit_bytes,
                memory_percent=memory_percent,
            )
        )
    return points


def compose_up() -> None:
    run_cmd(["docker-compose", "up", "-d", "--build", *DEFAULT_STACK_SERVICES])


def compose_down() -> None:
    run_cmd(["docker-compose", "down", "-v"])


def wait_for_container_health(container: str, *, timeout_seconds: float = 120.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = run_cmd(["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", container], check=False)
        status = result.stdout.strip()
        if status in {"healthy", "running"}:
            return
        time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for container health: {container}")


def wait_for_stack_ready() -> None:
    wait_for_container_health("flipperagent-db-1")
    wait_for_container_health("flipperagent-broker-1")
    for container in [
        "flipperagent-worker-streams-1",
        "flipperagent-worker-queue-1",
        "flipperagent-signal-worker-1",
        "flipperagent-strategy-worker-1",
        "flipperagent-risk-worker-1",
        "flipperagent-execution-worker-1",
        "flipperagent-portfolio-worker-1",
    ]:
        wait_for_container_health(container)
    time.sleep(15.0)


async def wait_until(predicate, *, timeout_seconds: float, interval_seconds: float, description: str):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(interval_seconds)
    raise TimeoutError(f"Timed out waiting for {description}")


async def fetch_asset_flags(symbol: str) -> tuple[str, bool] | None:
    pool = DBPoolManager.get_reader_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT desired_state, enabled FROM ingestion_assets WHERE symbol = $1",
            symbol,
        )
    if row is None:
        return None
    return str(row["desired_state"]), bool(row["enabled"])


async def ingestion_asset_exists(symbol: str) -> bool:
    pool = DBPoolManager.get_reader_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1 FROM ingestion_assets WHERE symbol = $1", symbol)
    return row is not None


async def asset_flags_match(symbol: str, desired_state: str, enabled: bool):
    flags = await fetch_asset_flags(symbol)
    if flags == (desired_state, enabled):
        return flags
    return None


def _normalize_snapshot_state(snapshot: dict[str, Any]) -> str | None:
    state = snapshot.get("state")
    if state is None:
        return None
    if isinstance(state, bytes):
        return state.decode()
    return str(state)


async def broker_observability_snapshot(symbol: str, timeframe: str) -> dict[str, Any]:
    state_key = IngestionCoordinator._state_key(symbol, timeframe)
    disconnect_key = IngestionCoordinator._disconnect_ts_key(symbol, timeframe)
    live_key = IngestionCoordinator._last_live_ts_key(symbol, timeframe)
    count_key = IngestionCoordinator._disconnect_count_key(symbol, timeframe)

    def _read_snapshot() -> dict[str, Any]:
        state_raw = broker_cli("GET", state_key)
        disconnect_ts_raw = broker_cli("GET", disconnect_key)
        last_live_ts_raw = broker_cli("GET", live_key)
        count_raw = broker_cli("GET", count_key)
        return {
            "state": state_raw or IngestionState.COLD.value,
            "last_live_ts": int(last_live_ts_raw) if last_live_ts_raw else None,
            "last_disconnect_ts": int(disconnect_ts_raw) if disconnect_ts_raw else None,
            "disconnects_in_window": int(count_raw) if count_raw else 0,
        }

    return await asyncio.to_thread(_read_snapshot)


async def active_state_snapshot(_coordinator: IngestionCoordinator, symbol: str, timeframe: str):
    snapshot = await broker_observability_snapshot(symbol, timeframe)
    state = _normalize_snapshot_state(snapshot)
    if snapshot["last_live_ts"] and state in {
        IngestionState.WARMING.value,
        IngestionState.LIVE.value,
    }:
        return snapshot
    return None


async def live_state_snapshot(_coordinator: IngestionCoordinator, symbol: str, timeframe: str):
    snapshot = await broker_observability_snapshot(symbol, timeframe)
    state = _normalize_snapshot_state(snapshot)
    if snapshot["last_live_ts"] and state == IngestionState.LIVE.value:
        return snapshot
    return None


async def cold_state_snapshot(_coordinator: IngestionCoordinator, symbol: str, timeframe: str):
    snapshot = await broker_observability_snapshot(symbol, timeframe)
    state = _normalize_snapshot_state(snapshot)
    if state == IngestionState.COLD.value:
        return snapshot
    return None


async def stream_len_greater_than(valkey_client: Any, stream_key: str, previous_len: int):
    del valkey_client

    def _read_stream_len() -> int:
        raw = broker_cli("XLEN", stream_key)
        return int(raw) if raw else 0

    current_len = await asyncio.to_thread(_read_stream_len)
    if current_len > previous_len:
        return current_len
    return None


async def read_stream_len(stream_key: str) -> int:
    def _read_stream_len() -> int:
        raw = broker_cli("XLEN", stream_key)
        return int(raw) if raw else 0

    return await asyncio.to_thread(_read_stream_len)


async def monitor_docker_memory(
    containers: list[str],
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
    sink: list[DockerMemoryPoint],
) -> None:
    while not stop_event.is_set():
        sink.extend(sample_docker_memory(containers))
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
    sink.extend(sample_docker_memory(containers))


async def run_cycle(
    *,
    cycle_index: int,
    service: IngestionControlService,
    coordinator: IngestionCoordinator,
    valkey_client: Any,
    symbol: str,
    base_timeframe: str,
    publish_timeframes: list[str],
    historical_backfill_days: int,
    live_timeout_seconds: float,
    remove_timeout_seconds: float,
    pause_flat_seconds: float,
) -> dict[str, Any]:
    stream_key = f"stream:ohlcv:{symbol.lower()}:{publish_timeframes[0]}"
    warnings: list[str] = []
    print(f"[cycle {cycle_index}] upsert {symbol}")
    result = await service.upsert_asset(
        IngestionAssetUpsertRequest(
            symbol=symbol,
            base_timeframe=base_timeframe,
            publish_timeframes=publish_timeframes,
            historical_backfill_days=historical_backfill_days,
            desired_state=IngestionAssetDesiredState.LIVE,
            requested_by="scripts.qa.ingestion_runtime_memory_soak",
            reason=f"soak cycle {cycle_index} add",
        ),
        command_type=IngestionCommandType.UPSERT_ASSET,
    )

    cycle_summary: dict[str, Any] = {
        "cycle_index": cycle_index,
        "stream_key": stream_key,
        "warnings": warnings,
    }
    remove_requested = False
    active_asset = result.asset

    try:
        print(f"[cycle {cycle_index}] waiting for active state")
        await wait_until(
            lambda: active_state_snapshot(coordinator, symbol, base_timeframe),
            timeout_seconds=live_timeout_seconds,
            interval_seconds=1.0,
            description=f"{symbol} active state",
        )
        print(f"[cycle {cycle_index}] waiting for initial stream entries")
        initial_stream_len = await wait_until(
            lambda: stream_len_greater_than(valkey_client, stream_key, -1),
            timeout_seconds=live_timeout_seconds,
            interval_seconds=2.0,
            description=f"{stream_key} initial entries",
        )
        cycle_summary["initial_stream_len"] = initial_stream_len

        print(f"[cycle {cycle_index}] pause")
        pause_result = await service.apply_action(
            active_asset,
            desired_state=IngestionAssetDesiredState.PAUSED,
            enabled=True,
            action=IngestionCommandType.PAUSE_ASSET,
            body=IngestionAssetActionRequest(
                requested_by="scripts.qa.ingestion_runtime_memory_soak",
                reason=f"soak cycle {cycle_index} pause",
            ),
        )
        active_asset = pause_result.asset

        print(f"[cycle {cycle_index}] waiting for PAUSED flags and COLD state")
        await wait_until(
            lambda: asset_flags_match(symbol, IngestionAssetDesiredState.PAUSED.value, True),
            timeout_seconds=60.0,
            interval_seconds=1.0,
            description=f"{symbol} paused asset flags",
        )
        paused_snapshot = await wait_until(
            lambda: cold_state_snapshot(coordinator, symbol, base_timeframe),
            timeout_seconds=120.0,
            interval_seconds=1.0,
            description=f"{symbol} COLD state",
        )
        paused_stream_len = await read_stream_len(stream_key)
        await asyncio.sleep(pause_flat_seconds)
        paused_stream_len_after_wait = await read_stream_len(stream_key)
        if paused_stream_len_after_wait != paused_stream_len:
            raise AssertionError(
                f"Stream grew while paused: before={paused_stream_len}, after={paused_stream_len_after_wait}"
            )
        cycle_summary["paused_disconnects_in_window"] = paused_snapshot["disconnects_in_window"]
        cycle_summary["paused_stream_len"] = paused_stream_len

        print(f"[cycle {cycle_index}] resume")
        resume_result = await service.apply_action(
            active_asset,
            desired_state=IngestionAssetDesiredState.LIVE,
            enabled=True,
            action=IngestionCommandType.RESUME_ASSET,
            body=IngestionAssetActionRequest(
                requested_by="scripts.qa.ingestion_runtime_memory_soak",
                reason=f"soak cycle {cycle_index} resume",
            ),
        )
        active_asset = resume_result.asset

        print(f"[cycle {cycle_index}] waiting for resumed flags and stream growth")
        await wait_until(
            lambda: asset_flags_match(symbol, IngestionAssetDesiredState.LIVE.value, True),
            timeout_seconds=60.0,
            interval_seconds=1.0,
            description=f"{symbol} resumed asset flags",
        )
        resumed_stream_len = await wait_until(
            lambda: stream_len_greater_than(valkey_client, stream_key, paused_stream_len),
            timeout_seconds=live_timeout_seconds,
            interval_seconds=2.0,
            description=f"{stream_key} resumed entries",
        )
        cycle_summary["resumed_stream_len"] = resumed_stream_len
        try:
            print(f"[cycle {cycle_index}] waiting for resumed LIVE confirmation")
            resumed_snapshot = await wait_until(
                lambda: live_state_snapshot(coordinator, symbol, base_timeframe),
                timeout_seconds=30.0,
                interval_seconds=1.0,
                description=f"{symbol} resumed LIVE state",
            )
            cycle_summary["resumed_disconnects_in_window"] = resumed_snapshot["disconnects_in_window"]
            cycle_summary["resumed_live_state_confirmed"] = True
        except TimeoutError:
            warnings.append(
                f"{symbol} resumed stream activity without confirming LIVE state inside soak timeout window"
            )
            cycle_summary["resumed_live_state_confirmed"] = False
    finally:
        if await ingestion_asset_exists(symbol):
            remove_requested = True
            print(f"[cycle {cycle_index}] remove")
            await service.apply_action(
                active_asset,
                desired_state=IngestionAssetDesiredState.REMOVING,
                enabled=False,
                action=IngestionCommandType.REMOVE_ASSET,
                body=IngestionAssetActionRequest(
                    requested_by="scripts.qa.ingestion_runtime_memory_soak",
                    reason=f"soak cycle {cycle_index} cleanup",
                ),
            )
        if remove_requested:
            print(f"[cycle {cycle_index}] waiting for removal cleanup")
            await wait_until(
                lambda: asset_cleanup_completed(
                    symbol,
                    base_timeframe=base_timeframe,
                    publish_timeframes=publish_timeframes,
                ),
                timeout_seconds=remove_timeout_seconds,
                interval_seconds=2.0,
                description=f"{symbol} removal cleanup",
            )

    return cycle_summary


async def asset_removed(symbol: str) -> bool:
    return not await ingestion_asset_exists(symbol)


async def symbol_count_zero(table: str, symbol: str) -> bool:
    pool = DBPoolManager.get_reader_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE symbol = $1", symbol)
    return int(count or 0) == 0


async def broker_key_absent(key: str) -> bool:
    def _exists() -> bool:
        raw = broker_cli("EXISTS", key)
        return raw == "0"

    return await asyncio.to_thread(_exists)


async def asset_cleanup_completed(
    symbol: str,
    *,
    base_timeframe: str,
    publish_timeframes: list[str],
) -> bool:
    flags = await fetch_asset_flags(symbol)
    tombstoned = flags == (IngestionAssetDesiredState.STOPPED.value, False)
    deleted = flags is None
    if not tombstoned and not deleted:
        return False

    runtime_timeframes: list[str] = []
    for timeframe in [base_timeframe, *publish_timeframes]:
        normalized = str(timeframe).strip()
        if normalized and normalized not in runtime_timeframes:
            runtime_timeframes.append(normalized)

    storage_ok = all(
        await asyncio.gather(
            symbol_count_zero("ohlcv", symbol),
            symbol_count_zero("ticks", symbol),
            symbol_count_zero("open_interest", symbol),
            symbol_count_zero("funding_rate", symbol),
            symbol_count_zero("l2_depth_features", symbol),
        )
    )
    if not storage_ok:
        return False

    broker_tasks: list[asyncio.Future] = []
    for timeframe in runtime_timeframes:
        broker_tasks.extend(
            [
                broker_key_absent(f"stream:ohlcv:{symbol.lower()}:{timeframe}"),
                broker_key_absent(f"features:{symbol}:{timeframe}"),
                broker_key_absent(f"price_update:{symbol}:{timeframe}"),
                broker_key_absent(f"signals:{symbol}:{timeframe}"),
                broker_key_absent(IngestionCoordinator._state_key(symbol, timeframe)),
                broker_key_absent(IngestionCoordinator._disconnect_ts_key(symbol, timeframe)),
                broker_key_absent(IngestionCoordinator._last_live_ts_key(symbol, timeframe)),
                broker_key_absent(IngestionCoordinator._disconnect_count_key(symbol, timeframe)),
            ]
        )
    broker_tasks.extend(
        [
            broker_key_absent(f"derivatives:latest:{symbol}:oi"),
            broker_key_absent(f"derivatives:latest:{symbol}:funding"),
        ]
    )
    return all(await asyncio.gather(*broker_tasks))


def summarize_memory(
    points: list[DockerMemoryPoint],
    *,
    peak_growth_threshold_bytes: int,
    final_growth_threshold_bytes: int,
) -> dict[str, Any]:
    grouped: dict[str, list[DockerMemoryPoint]] = {}
    for point in points:
        grouped.setdefault(point.container, []).append(point)

    summary: dict[str, Any] = {}
    failures: list[str] = []
    for container, container_points in grouped.items():
        baseline = container_points[0].memory_usage_bytes
        peak = max(point.memory_usage_bytes for point in container_points)
        final = container_points[-1].memory_usage_bytes
        peak_growth = peak - baseline
        final_growth = final - baseline
        summary[container] = {
            "baseline_memory_bytes": baseline,
            "peak_memory_bytes": peak,
            "final_memory_bytes": final,
            "peak_growth_bytes": peak_growth,
            "final_growth_bytes": final_growth,
            "peak_memory_percent": max(
                (point.memory_percent for point in container_points if point.memory_percent is not None),
                default=None,
            ),
        }
        if peak_growth > peak_growth_threshold_bytes:
            failures.append(
                f"{container} peak growth {peak_growth} exceeded threshold {peak_growth_threshold_bytes}"
            )
        if final_growth > final_growth_threshold_bytes:
            failures.append(
                f"{container} final growth {final_growth} exceeded threshold {final_growth_threshold_bytes}"
            )
    summary["_failures"] = failures
    return summary


async def async_main(args: argparse.Namespace) -> int:
    containers = args.containers or list(DEFAULT_CONTAINERS)
    publish_timeframes = list(dict.fromkeys(args.publish_timeframes))
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    started_stack = False
    if args.start_stack:
        compose_up()
        started_stack = True
        wait_for_stack_ready()

    runtime_config = SoakRuntimeConfig()
    await DBPoolManager.init_pools(config_manager=runtime_config)
    valkey_client = avalkey.Valkey.from_url(runtime_config.get("valkey.uri"), decode_responses=True)
    service = IngestionControlService(
        pool=DBPoolManager.get_writer_pool(),
        valkey_client=valkey_client,
    )
    coordinator = IngestionCoordinator(valkey_client, runtime_config)

    memory_points: list[DockerMemoryPoint] = []
    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(
        monitor_docker_memory(
            containers,
            interval_seconds=args.sample_interval_seconds,
            stop_event=stop_event,
            sink=memory_points,
        )
    )

    started_at = time.time()
    cycle_summaries: list[dict[str, Any]] = []
    exit_code = 0
    failure_message: str | None = None

    try:
        for cycle_index in range(1, args.cycles + 1):
            cycle_summary = await run_cycle(
                cycle_index=cycle_index,
                service=service,
                coordinator=coordinator,
                valkey_client=valkey_client,
                symbol=args.symbol,
                base_timeframe=args.base_timeframe,
                publish_timeframes=publish_timeframes,
                historical_backfill_days=args.historical_backfill_days,
                live_timeout_seconds=args.live_timeout_seconds,
                remove_timeout_seconds=args.remove_timeout_seconds,
                pause_flat_seconds=args.pause_flat_seconds,
            )
            cycle_summaries.append(cycle_summary)
    except Exception as exc:
        exit_code = 1
        failure_message = str(exc)
    finally:
        stop_event.set()
        await monitor_task
        await valkey_client.aclose()
        await DBPoolManager.close_pools()
        DBPoolManager._writer_pool = None
        DBPoolManager._reader_pool = None
        if started_stack and not args.keep_stack:
            compose_down()

    memory_summary = summarize_memory(
        memory_points,
        peak_growth_threshold_bytes=int(args.memory_growth_threshold_mib * 1024 * 1024),
        final_growth_threshold_bytes=int(args.memory_final_growth_threshold_mib * 1024 * 1024),
    )
    if memory_summary["_failures"]:
        exit_code = 1
        failure_message = failure_message or "; ".join(memory_summary["_failures"])

    report = {
        "started_at_epoch": started_at,
        "finished_at_epoch": time.time(),
        "exit_code": exit_code,
        "failure_message": failure_message,
        "config": {
            "cycles": args.cycles,
            "symbol": args.symbol,
            "base_timeframe": args.base_timeframe,
            "publish_timeframes": publish_timeframes,
            "historical_backfill_days": args.historical_backfill_days,
            "pause_flat_seconds": args.pause_flat_seconds,
            "sample_interval_seconds": args.sample_interval_seconds,
            "live_timeout_seconds": args.live_timeout_seconds,
            "remove_timeout_seconds": args.remove_timeout_seconds,
            "memory_growth_threshold_mib": args.memory_growth_threshold_mib,
            "memory_final_growth_threshold_mib": args.memory_final_growth_threshold_mib,
            "containers": containers,
            "start_stack": args.start_stack,
            "keep_stack": args.keep_stack,
        },
        "cycles": cycle_summaries,
        "memory_summary": memory_summary,
        "memory_points": [asdict(point) for point in memory_points],
    }
    output_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["memory_summary"], indent=2))
    print(f"Wrote soak report to {output_path}")
    if failure_message:
        print(f"Soak failure: {failure_message}")
    return exit_code


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
