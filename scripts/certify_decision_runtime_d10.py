"""Offline D10 resource and boundedness certification for decision_app.

The facade exercises the approved D9A-D9D primitives with deterministic,
generated canonical data.  It deliberately does not add a runtime resource
manager, a benchmark dependency, or a second execution architecture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.features.planning import FeatureCatalog, FeaturePolicy
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.runtime.lifecycle import LifecycleReadResult
from apps.decision_app.runtime.live import DecisionPollResult, LiveDecisionRuntime
from apps.decision_app.runtime.plugins import RuntimePluginCatalog
from apps.decision_app.runtime.service import DecisionRuntimeGeneration, DecisionService
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import (
    CanonicalInstrument,
    DecisionConfig,
)
from apps.decision_app.storage.market_history import CanonicalMarketRecord
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_RISK
from libs.common.signal_routes import parse_signal_routes
from libs.contracts.decision import CausalBarView, DecisionContext, FeatureSnapshot

SCHEMA_VERSION = "d10.resource_capacity.v1"
ARTIFACT_PATH = (
    REPOSITORY_ROOT / "artifacts/decision_d10/d10_resource_capacity_certification.json"
)
NORMAL_RSS_TARGET_BYTES = 5 * 1024**3
HARD_RSS_TARGET_BYTES = 8 * 1024**3
CPU_TARGET_CORES = 4.0
LIVE_BATCH_SIZE = 10
BASE_TIME = datetime(2026, 1, 5, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CanonicalInventory:
    """The current canonical ingestion universe used by D10."""

    grid: TimeframeGrid
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    instruments: Mapping[str, CanonicalInstrument]
    series: tuple[MarketSeriesKey, ...]
    decision_symbols: Mapping[str, str]

    @property
    def series_count(self) -> int:
        return len(self.series)


@dataclass(frozen=True, slots=True)
class Measurement:
    """Standard-library resource sample for one ordered scenario."""

    wall_seconds: float
    process_cpu_seconds: float
    cpu_core_equivalent: float
    tracemalloc_peak_bytes: int
    process_peak_rss_bytes: int
    threads_before: int
    threads_after: int
    tasks_before: int | None = None
    tasks_peak: int | None = None
    tasks_after: int | None = None


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _rss_bytes(value: int, *, system: str | None = None) -> int:
    """Normalize ``ru_maxrss`` for macOS bytes and Linux KiB."""

    normalized_system = platform.system() if system is None else system
    if normalized_system == "Darwin":
        return int(value)
    return int(value) * 1024


def _process_peak_rss_bytes() -> int:
    return _rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _task_count() -> int:
    try:
        return sum(
            1 for task in asyncio.all_tasks() if task.get_name().startswith("decision-")
        )
    except RuntimeError:
        return 0


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _parse_utc(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return parsed.astimezone(UTC)


def load_canonical_inventory(root: Path = REPOSITORY_ROOT) -> CanonicalInventory:
    """Derive D10 scale from the live canonical ingestion YAML files."""

    global_path = root / "configs/ingestion/global.yaml"
    raw_global = yaml.safe_load(global_path.read_text(encoding="utf-8"))
    if not isinstance(raw_global, Mapping) or not isinstance(
        raw_global.get("ingestion"), Mapping
    ):
        raise TypeError("canonical ingestion global namespace is missing")
    ingestion = raw_global["ingestion"]
    calendar = ingestion.get("calendar")
    raw_timeframes = ingestion.get("timeframes")
    if not isinstance(calendar, Mapping) or not isinstance(raw_timeframes, Mapping):
        raise TypeError("canonical ingestion calendar/timeframes are missing")
    durations: dict[str, timedelta] = {}
    for timeframe, raw in raw_timeframes.items():
        if not isinstance(raw, Mapping):
            raise TypeError(f"timeframe {timeframe} is not a mapping")
        seconds = raw.get("duration_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ValueError(f"invalid duration for timeframe {timeframe}")
        durations[_text(timeframe, "timeframe")] = timedelta(seconds=seconds)
    grid = TimeframeGrid(
        alignment_origin=_parse_utc(
            calendar.get("alignment_origin"), "alignment_origin"
        ),
        durations=durations,
    )

    assets: list[str] = []
    instruments: dict[str, CanonicalInstrument] = {}
    symbols: dict[str, str] = {}
    for path in sorted((root / "configs/ingestion/assets").glob("*.yaml")):
        raw_asset = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw_asset, Mapping):
            raise TypeError(f"asset file is not a mapping: {path}")
        manifest_asset = _text(raw_asset.get("asset"), "asset")
        if (
            raw_asset.get("enabled") is not True
            or raw_asset.get("owns_manifest_lifecycle") is not True
        ):
            continue
        raw_instruments = raw_asset.get("instruments")
        if not isinstance(raw_instruments, Mapping) or len(raw_instruments) != 1:
            raise ValueError(f"expected one instrument for {manifest_asset}")
        instrument_id, raw_instrument = next(iter(raw_instruments.items()))
        if not isinstance(raw_instrument, Mapping):
            raise TypeError(f"instrument is not a mapping for {manifest_asset}")
        venue = _text(raw_instrument.get("venue"), "venue")
        raw_timeframe_names = raw_instrument.get("timeframes")
        if not isinstance(raw_timeframe_names, Sequence) or isinstance(
            raw_timeframe_names, (str, bytes)
        ):
            raise TypeError(f"instrument timeframes are missing for {manifest_asset}")
        provider_symbols = raw_instrument.get("provider_symbols")
        if not isinstance(provider_symbols, Mapping):
            raise TypeError(f"provider symbols are missing for {manifest_asset}")
        native_symbol = _text(provider_symbols.get("binance_native"), "native symbol")
        assets.append(manifest_asset)
        symbols[manifest_asset] = native_symbol
        instruments[manifest_asset] = CanonicalInstrument(
            manifest_asset=manifest_asset,
            instrument_id=_text(instrument_id, "instrument_id"),
            venue=venue,
            timeframes=tuple(_text(item, "timeframe") for item in raw_timeframe_names),
            provider_symbols={"binance_native": native_symbol},
        )

    assets_tuple = tuple(sorted(assets))
    timeframes_tuple = tuple(sorted(durations, key=lambda item: durations[item]))
    series = tuple(
        MarketSeriesKey(
            asset=asset,
            venue=instruments[asset].venue,
            instrument_id=instruments[asset].instrument_id,
            timeframe=timeframe,
        )
        for asset in assets_tuple
        for timeframe in timeframes_tuple
        if timeframe in instruments[asset].timeframes
    )
    return CanonicalInventory(
        grid=grid,
        assets=assets_tuple,
        timeframes=timeframes_tuple,
        instruments=instruments,
        series=series,
        decision_symbols=symbols,
    )


def _risk_timeframes(
    inventory: CanonicalInventory,
    root: Path = REPOSITORY_ROOT,
) -> Mapping[str, tuple[str, ...]]:
    """Derive the current risk envelope through risk_app's config contract."""

    ConfigManager.reset_singleton()
    config_manager = ConfigManager(config_dir=str(root / "configs"))
    try:
        config_manager.register_file(root / CONFIG_FILE_RISK)
        discovered_routes = parse_signal_routes(
            config_manager.get("risk.runtime.signal_routes", ())
        )
    finally:
        config_manager.shutdown()
        ConfigManager.reset_singleton()

    by_symbol = {
        symbol: manifest for manifest, symbol in inventory.decision_symbols.items()
    }
    result: dict[str, set[str]] = {asset: set() for asset in inventory.assets}
    for route in discovered_routes:
        symbol, timeframe = route.split(":", 1)
        manifest = by_symbol.get(symbol)
        if manifest is None:
            raise ValueError(
                f"risk route asset is absent from canonical inventory: {symbol}"
            )
        if timeframe not in inventory.timeframes:
            raise ValueError(
                "risk route timeframe is absent from canonical inventory: "
                f"{symbol}/{timeframe}"
            )
        result[manifest].add(timeframe)
    return {
        asset: tuple(sorted(values, key=lambda item: inventory.grid.duration(item)))
        for asset, values in result.items()
        if values
    }


def _bar(key: MarketSeriesKey, index: int, grid: TimeframeGrid) -> CausalBarView:
    duration = grid.duration(key.timeframe)
    opened = BASE_TIME + index * duration
    closed = opened + duration
    value = Decimal(100) + Decimal(index)
    return CausalBarView(
        timeframe=key.timeframe,
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=value,
        high=value + Decimal(1),
        low=value - Decimal(1),
        close=value,
        volume=Decimal(10),
        taker_buy_base=Decimal(5),
        closed=True,
    )


def _ingestion_fields(key: MarketSeriesKey, bar: CausalBarView) -> Mapping[str, str]:
    payload = {
        "venue": key.venue,
        "instrument_id": key.instrument_id,
        "timeframe": key.timeframe,
        "open_time": _iso(bar.bar_open_at),
        "close_time": _iso(bar.bar_close_at),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "taker_buy_base": str(bar.taker_buy_base),
        "source_type": "provider",
        "source_provider": "d10",
        "source_timeframe": None,
    }
    return {
        "event_id": f"d10-{key.asset}-{key.timeframe}-{bar.bar_open_at.isoformat()}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": _iso(bar.bar_close_at),
        "payload": json.dumps(payload, sort_keys=True),
    }


class GeneratedHistory:
    """On-demand canonical history with bounded bookkeeping."""

    def __init__(self, grid: TimeframeGrid, keys: Sequence[MarketSeriesKey]) -> None:
        self.grid = grid
        self.latest_indices = {key: 0 for key in keys}
        self.fetch_calls = 0
        self.record_calls = 0
        self.latest_calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.max_materialized_bars = 0

    def advance(self, key: MarketSeriesKey, index: int) -> None:
        if index < self.latest_indices.get(key, -1):
            raise ValueError("generated history cannot move backward")
        self.latest_indices[key] = index

    def latest_index(self, key: MarketSeriesKey) -> int:
        return self.latest_indices[key]

    async def _enter(self) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)

    def _leave(self) -> None:
        self.in_flight -= 1

    def _available_indices(
        self,
        key: MarketSeriesKey,
        *,
        start: datetime | None,
        end: datetime | None,
        through: datetime | None,
    ) -> list[int]:
        duration = self.grid.duration(key.timeframe)
        latest = self.latest_indices.get(key, -1)
        result: list[int] = []
        for index in range(latest + 1):
            bar = _bar(key, index, self.grid)
            if start is not None and bar.bar_open_at < start:
                continue
            if end is not None and bar.bar_open_at >= end:
                continue
            if through is not None and bar.bar_close_at > through:
                continue
            result.append(index)
        del duration
        return result

    async def fetch_latest_cutoff(self, key: MarketSeriesKey) -> datetime | None:
        self.latest_calls += 1
        await self._enter()
        try:
            index = self.latest_indices.get(key, -1)
            return None if index < 0 else _bar(key, index, self.grid).bar_close_at
        finally:
            self._leave()

    async def fetch_record_at(
        self,
        key: MarketSeriesKey,
        bar_open_at: datetime,
    ) -> CanonicalMarketRecord | None:
        self.record_calls += 1
        await self._enter()
        try:
            duration = self.grid.duration(key.timeframe)
            elapsed = bar_open_at - BASE_TIME
            index_float = elapsed.total_seconds() / duration.total_seconds()
            index = int(index_float)
            if (
                index_float != index
                or index < 0
                or index > self.latest_indices.get(key, -1)
            ):
                return None
            bar = _bar(key, index, self.grid)
            return CanonicalMarketRecord(
                series_key=key,
                bar=bar,
                source_type="provider",
                source_provider="d10",
                source_timeframe=None,
            )
        finally:
            self._leave()

    async def fetch_bars(
        self,
        key: MarketSeriesKey,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        through: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[CausalBarView, ...]:
        self.fetch_calls += 1
        await self._enter()
        try:
            indices = self._available_indices(
                key,
                start=start,
                end=end,
                through=through,
            )
            if limit is not None:
                indices = indices[-limit:]
            self.max_materialized_bars = max(self.max_materialized_bars, len(indices))
            return tuple(_bar(key, index, self.grid) for index in indices)
        finally:
            self._leave()


class BoundedStreamClient:
    """Deterministic direct-cursor transport double."""

    def __init__(self, keys: Sequence[MarketSeriesKey], grid: TimeframeGrid) -> None:
        self.grid = grid
        self.ingestion_tails = {
            canonical_ingestion_stream_key(key): (
                "0-0",
                _ingestion_fields(key, _bar(key, 0, grid)),
            )
            for key in keys
        }
        self.pending: dict[str, list[tuple[str, Mapping[str, str]]]] = {}
        self.xread_calls = 0
        self.xrange_calls = 0
        self.xrevrange_calls = 0

    def enqueue(self, key: MarketSeriesKey, index: int) -> None:
        stream = canonical_ingestion_stream_key(key)
        entry = (f"{index}-0", _ingestion_fields(key, _bar(key, index, self.grid)))
        self.pending.setdefault(stream, []).append(entry)
        self.ingestion_tails[stream] = entry

    async def xrevrange(
        self,
        stream: str,
        _start: str = "+",
        _end: str = "-",
        *,
        count: int = 1,
    ) -> list[tuple[str, Mapping[object, object]]]:
        self.xrevrange_calls += 1
        if stream in self.ingestion_tails:
            return [self.ingestion_tails[stream]][:count]
        return []

    async def xrange(
        self,
        stream: str,
        start: str,
        end: str,
    ) -> list[tuple[str, Mapping[object, object]]]:
        self.xrange_calls += 1
        del stream, start, end
        return []

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, Mapping[str, str]]]]]:
        del block
        self.xread_calls += 1
        remaining = count
        result: list[tuple[str, list[tuple[str, Mapping[str, str]]]]] = []
        for stream, cursor in sorted(streams.items()):
            entries = self.pending.get(stream, [])
            selected = [
                entry
                for entry in entries
                if int(entry[0].split("-", 1)[0]) > int(cursor.split("-", 1)[0])
            ][:remaining]
            if not selected:
                continue
            remaining -= len(selected)
            self.pending[stream] = entries[len(selected) :]
            result.append((stream, selected))
            if remaining == 0:
                break
        await asyncio.sleep(0)
        return result


class _LifecycleProbe:
    """Minimal lifecycle reader used only to measure service task ownership."""

    def __init__(self) -> None:
        self.cursor = "0-0"
        self._pending = False

    def request_rebuild(self) -> None:
        self._pending = True

    async def read_once(self) -> LifecycleReadResult:
        if self._pending:
            self._pending = False
            self.cursor = "1-0"
            return LifecycleReadResult(
                cursor=self.cursor,
                event_ids=(self.cursor,),
                relevant_events=(object(),),  # type: ignore[arg-type]
            )
        await asyncio.sleep(0.001)
        return LifecycleReadResult(cursor=self.cursor)


async def build_runtime(
    config: DecisionConfig,
    history: GeneratedHistory,
    stream: BoundedStreamClient,
) -> LiveDecisionRuntime:
    startup = await DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=PluginCatalog([]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=history,
        stream_client=stream,
    ).start()
    return LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=config.timeframe_grid,
        stream_client=stream,
        history_repository=history,
        batch_size=config.global_settings.live_input.batch_size,
        block_ms=config.global_settings.live_input.block_ms,
    )


async def _measure_async(callable_: Any) -> tuple[Any, Measurement]:
    threads_before = threading.active_count()
    tasks_before = _task_count()
    tracemalloc.start()
    peak = 0
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    try:
        value = await callable_()
    finally:
        wall_seconds = max(time.perf_counter() - wall_start, 1e-12)
        cpu_seconds = max(time.process_time() - cpu_start, 0.0)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    threads_after = threading.active_count()
    tasks_after = _task_count()
    measurement = Measurement(
        wall_seconds=wall_seconds,
        process_cpu_seconds=cpu_seconds,
        cpu_core_equivalent=cpu_seconds / wall_seconds,
        tracemalloc_peak_bytes=int(peak),
        process_peak_rss_bytes=_process_peak_rss_bytes(),
        threads_before=threads_before,
        threads_after=threads_after,
        tasks_before=tasks_before,
        tasks_peak=None,
        tasks_after=tasks_after,
    )
    return value, measurement


def _measurement_dict(measurement: Measurement) -> dict[str, Any]:
    return {
        "wall_seconds": measurement.wall_seconds,
        "process_cpu_seconds": measurement.process_cpu_seconds,
        "cpu_core_equivalent": measurement.cpu_core_equivalent,
        "tracemalloc_peak_bytes": measurement.tracemalloc_peak_bytes,
        "process_peak_rss_bytes": measurement.process_peak_rss_bytes,
        "threads_before": measurement.threads_before,
        "threads_after": measurement.threads_after,
        "tasks_before": measurement.tasks_before,
        "tasks_peak": measurement.tasks_peak,
        "tasks_after": measurement.tasks_after,
    }


async def run_service_scenario(
    inventory: CanonicalInventory,
) -> dict[str, Any]:
    lifecycle = _LifecycleProbe()
    generations: list[int] = []
    threads_before = threading.active_count()

    startup = SimpleNamespace(
        decision_plan=SimpleNamespace(lanes=()),
        snapshot=SimpleNamespace(
            active_manifest_assets=(),
            lane_evidence={},
            series_positions={},
        ),
    )

    class _NoLaneRuntime:
        def __init__(self) -> None:
            self.lanes: dict[str, Any] = {}
            self.blocked_lanes: dict[str, Any] = {}
            self.input = SimpleNamespace(
                blocked_streams={},
                cursors={},
                stream_keys=(),
                has_unblocked_streams=False,
            )

        async def poll_once(self, *, evaluate_lanes: bool = True) -> DecisionPollResult:
            del evaluate_lanes
            return DecisionPollResult(input_results=(), lane_results={}, cursors={})

    async def factory(*, reason: str, generation_id: int) -> DecisionRuntimeGeneration:
        del reason
        runtime = _NoLaneRuntime()
        generations.append(generation_id)
        return DecisionRuntimeGeneration(
            generation_id=generation_id,
            created_at=datetime.now(UTC),
            startup=startup,
            live_runtime=runtime,
        )

    service = DecisionService(
        generation_factory=factory,
        lifecycle_reader=lifecycle,
        configured_asset_count=len(inventory.assets),
        configured_lane_count=0,
        block_ms=1000,
    )
    await service.start()
    task_after_start = _task_count()
    task_peak = task_after_start
    paused = await service.pause()
    for _ in range(100):
        await asyncio.sleep(0.001)
        task_peak = max(task_peak, _task_count())
        if task_peak == 2:
            break
    lifecycle.request_rebuild()
    for _ in range(100):
        await asyncio.sleep(0.001)
        task_peak = max(task_peak, _task_count())
        if len(generations) >= 2:
            break
    lifecycle_snapshot = service.snapshot()
    resumed = await service.resume()
    task_peak = max(task_peak, _task_count())
    stopped = await service.stop()
    task_count_after_stop = _task_count()
    threads_after = threading.active_count()
    return {
        "scenario": "service_lifecycle_boundedness",
        "generations_built": generations,
        "paused_state": paused.service_state,
        "paused_desired_state": paused.desired_state,
        "lifecycle_generation_state": lifecycle_snapshot.service_state,
        "resumed_state": resumed.service_state,
        "stopped_state": stopped.service_state,
        "task_count_after_start": task_after_start,
        "task_peak": task_peak,
        "task_count_after_stop": task_count_after_stop,
        "market_task_after_stop": service.market_task is not None,
        "lifecycle_task_after_stop": service.lifecycle_task is not None,
        "thread_count_before_after": (threads_before, threads_after),
        "correct": (
            paused.service_state == "PAUSED"
            and paused.desired_state == "PAUSED"
            and lifecycle_snapshot.generation_id == 2
            and lifecycle_snapshot.service_state == "PAUSED"
            and resumed.service_state == "RUNNING"
            and stopped.service_state == "STOPPED"
            and service.market_task is None
            and service.lifecycle_task is None
            and task_after_start == 2
            and task_peak == 2
            and task_count_after_stop == 0
            and threads_after == threads_before
        ),
    }


async def run_sr_reference(*, steps: int = 1000) -> dict[str, Any]:
    """Measure the reviewed SR adapter seam, never as final model capacity."""

    from libs.models.sr.adapters.decision_plugin import SRDecisionPlugin

    if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
        raise ValueError("SR reference steps must be a positive integer")

    sr_config = {
        "version": "1",
        "defaults": {
            "detection": {"pivot_span_bars": 1, "zone_half_width_atr": 0.0},
            "association": {"merge_distance_atr": 0.5},
            "lifecycle": {
                "touch_tolerance_atr": 0.25,
                "break_buffer_atr": 0.5,
                "break_confirm_closes": 2,
                "max_age_bars": 10,
            },
            "runtime": {"max_active_zones": 8},
        },
    }
    plugin = SRDecisionPlugin({"sr_config": sr_config})
    state: object | None = None
    encoded_sizes: list[int] = []
    internal_zone_counts: list[int] = []
    projected_zone_counts: list[int] = []
    for index in range(steps):
        opened = BASE_TIME + timedelta(hours=index)
        closed = opened + timedelta(hours=1)
        value = Decimal(100 + (index % 17))
        bar = CausalBarView(
            timeframe="1h",
            bar_open_at=opened,
            bar_close_at=closed,
            market_as_of=closed,
            open=value,
            high=value + Decimal(1),
            low=value - Decimal(1),
            close=value + Decimal("0.25"),
            volume=Decimal(10),
            taker_buy_base=Decimal(5),
            closed=True,
        )
        context = DecisionContext(
            asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            lane_id="BTCUSDT:d10-sr-reference",
            binding_id="d10-sr-reference",
            market_as_of=closed,
            trigger_timeframe="1h",
            decision_timeframe="1h",
            trigger_mode="on_bar_close",
            decision_bar=bar,
            decision_bar_closed=True,
            shared_features={
                "ATR": FeatureSnapshot(
                    name="ATR",
                    version="1",
                    market_as_of=closed,
                    value=1.0,
                    provenance={"source": "d10-reference"},
                )
            },
        )
        outcome = plugin.evaluate(context, state_snapshot=state)
        state = outcome.proposed_next_state
        if not isinstance(state, str):
            raise TypeError("SR adapter must propose an encoded state string")
        value_payload = outcome.artifact.value
        if not isinstance(value_payload, Mapping):
            raise TypeError("SR adapter artifact value must be a mapping")
        encoded_sizes.append(len(state.encode("utf-8")))
        internal_zone_counts.append(int(value_payload["zone_count"]))
        projected_zone_counts.append(int(value_payload["projected_zone_count"]))

    configured_max_active_zones = 8
    projected_zone_max = max(projected_zone_counts)
    return {
        "scenario": "sr_reference_1000_steps",
        "status": "REFERENCE_ONLY",
        "correct": (
            len(encoded_sizes) == steps
            and projected_zone_max <= configured_max_active_zones
        ),
        "steps": steps,
        "encoded_state_bytes_start": encoded_sizes[0],
        "encoded_state_bytes_end": encoded_sizes[-1],
        "encoded_state_bytes_max": max(encoded_sizes),
        "internal_zone_count_max": max(internal_zone_counts),
        "projected_artifact_zone_count_max": projected_zone_max,
        "configured_max_active_zones": configured_max_active_zones,
        "model_mix_recertification_required": True,
        "note": (
            "Existing SRDecisionPlugin artifact projection diagnostic only; "
            "not a final model-mix claim."
        ),
    }


def structural_boundedness_scan(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    source_root = root / "src/apps/decision_app"
    files = sorted(source_root.rglob("*.py"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    forbidden = {
        "ThreadPoolExecutor": "ThreadPoolExecutor",
        "ProcessPoolExecutor": "ProcessPoolExecutor",
        "asyncio.to_thread": "asyncio.to_thread",
        "run_in_executor": "run_in_executor",
        "XREADGROUP": "XREADGROUP",
        "XACK": "XACK",
        "XAUTOCLAIM": "XAUTOCLAIM",
        "FeatureVector": "FeatureVector",
        "ModelManager": "ModelManager",
        "signal_app": "signal_app",
        "strategy_app": "strategy_app",
        "multiprocessing": "multiprocessing",
        "joblib": "joblib",
    }
    matches = {
        name: text.count(pattern)
        for name, pattern in forbidden.items()
        if pattern in text
    }
    create_task_sites = text.count("asyncio.create_task(")
    return {
        "python_file_count": len(files),
        "create_task_sites": create_task_sites,
        "expected_long_lived_task_sites": 2,
        "forbidden_matches": matches,
        "decision_runtime_has_no_executor_fanout": not any(
            name in matches
            for name in (
                "ThreadPoolExecutor",
                "ProcessPoolExecutor",
                "asyncio.to_thread",
                "run_in_executor",
                "multiprocessing",
                "joblib",
            )
        ),
        "correct": create_task_sites == 2 and not matches,
    }


def _git_sha(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_safe(payload), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("D10 artifact cannot contain NaN or Infinity")
        return value
    return value


def _deterministic_identity_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable D10 identity inputs, excluding run-specific metadata."""

    return {
        "schema_version": artifact["schema_version"],
        "inventory": artifact["current_inventory"],
        "resource_target": artifact["resource_target"],
        "scenario_ids": [item["id"] for item in artifact["scenarios"]],
    }


def _measurement_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Return all certified evidence covered by the measurement digest."""

    return {
        "schema_version": artifact["schema_version"],
        "status": artifact["status"],
        "resource_target": artifact["resource_target"],
        "current_inventory": artifact["current_inventory"],
        "scenarios": artifact["scenarios"],
        "structural_boundedness": artifact["structural_boundedness"],
        "static_guards": artifact["static_guards"],
        "validation": artifact["validation"],
        "limitations": artifact["limitations"],
        "carry_forward": artifact["carry_forward"],
    }


def deterministic_identity_sha256(artifact: Mapping[str, Any]) -> str:
    """Hash stable D10 identity inputs, excluding run metadata."""

    return _canonical_digest(_deterministic_identity_payload(artifact))


def measurement_payload_sha256(artifact: Mapping[str, Any]) -> str:
    """Hash the canonical scenario measurements and certification evidence."""

    return _canonical_digest(_measurement_payload(artifact))


def evaluate_resource_gates(
    scenarios: Sequence[Mapping[str, Any]],
    *,
    structural_correct: bool,
) -> dict[str, Any]:
    """Evaluate D10 resource gates without manufacturing observations."""

    if len(scenarios) < 2:
        raise ValueError("D10 requires service and SR resource scenarios")
    scenario_correct = all(
        item["evidence"].get("correct") is True for item in scenarios
    )
    service_measurement = scenarios[0]["measurement"]
    normal_rss_ok = (
        service_measurement["process_peak_rss_bytes"] < NORMAL_RSS_TARGET_BYTES
    )
    hard_rss_ok = all(
        item["measurement"]["process_peak_rss_bytes"] < HARD_RSS_TARGET_BYTES
        for item in scenarios
    )
    cpu_ok = all(
        item["measurement"]["cpu_core_equivalent"] <= CPU_TARGET_CORES
        for item in scenarios
    )
    return {
        "scenario_correct": scenario_correct,
        "normal_rss_below_5_gib": normal_rss_ok,
        "all_scenarios_below_8_gib": hard_rss_ok,
        "hard_rss_below_8_gib_all_scenarios": hard_rss_ok,
        "cpu_core_equivalent_at_most_4": cpu_ok,
        "status": (
            "APPROVED"
            if structural_correct
            and scenario_correct
            and normal_rss_ok
            and hard_rss_ok
            and cpu_ok
            else "BLOCKED_RESOURCE_ENVELOPE"
            if not normal_rss_ok or not hard_rss_ok or not cpu_ok
            else "BLOCKED_INVARIANT"
        ),
    }


def write_artifact(artifact: Mapping[str, Any], path: Path = ARTIFACT_PATH) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _json_safe(dict(artifact))
    payload = json.dumps(normalized, sort_keys=True, indent=2, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def run_certification(root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    inventory = load_canonical_inventory(root)
    static = structural_boundedness_scan(root)
    risk_timeframes = _risk_timeframes(inventory, root)

    async def measured(name: str, function: Any) -> dict[str, Any]:
        value, measurement = await _measure_async(function)
        return {
            "id": name,
            "measurement": _measurement_dict(measurement),
            "evidence": value,
        }

    scenarios = [
        await measured(
            "service_lifecycle_boundedness",
            lambda: run_service_scenario(inventory),
        ),
        await measured("sr_reference_1000_steps", run_sr_reference),
    ]
    env_status = (
        "LOCAL_INFRASTRUCTURE_RESOURCE_PROBE_BLOCKED_ENVIRONMENT"
        if not (root / ".env").exists()
        else "NOT_RUN_OFFLINE_CERTIFICATION_ONLY"
    )
    normal_risk_routes = tuple(
        (inventory.decision_symbols[asset], timeframe)
        for asset in sorted(risk_timeframes)
        for timeframe in risk_timeframes[asset]
    )
    inventory_evidence = {
        "enabled_assets": inventory.assets,
        "timeframes": inventory.timeframes,
        "canonical_series_count": inventory.series_count,
        "canonical_series": [
            {
                "asset": key.asset,
                "venue": key.venue,
                "instrument_id": key.instrument_id,
                "timeframe": key.timeframe,
            }
            for key in inventory.series
        ],
        "normal_risk_routes": normal_risk_routes,
        "normal_risk_route_count": len(normal_risk_routes),
        "live_batch_size": LIVE_BATCH_SIZE,
    }
    resource_gates = evaluate_resource_gates(
        scenarios,
        structural_correct=static["correct"],
    )
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": resource_gates["status"],
        "created_at": datetime.now(UTC),
        "source_base": _git_sha(root),
        "worktree": str(root),
        "python": sys.version,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "host": {
            "blas_thread_environment": {
                name: os.environ.get(name)
                for name in (
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                    "NUMEXPR_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS",
                )
                if os.environ.get(name) is not None
            }
        },
        "resource_target": {
            "normal_working_set_bytes": NORMAL_RSS_TARGET_BYTES,
            "hard_memory_bytes": HARD_RSS_TARGET_BYTES,
            "cpu_cores": CPU_TARGET_CORES,
        },
        "current_inventory": inventory_evidence,
        "scenarios": scenarios,
        "structural_boundedness": static,
        "static_guards": {
            "decision_create_task_sites": static["create_task_sites"],
            "no_executor_or_process_fanout": static[
                "decision_runtime_has_no_executor_fanout"
            ],
            "resource_ownership": "one lifespan Valkey client; reader and writer DB pools",
        },
        "validation": {
            "offline_core_gates": {
                "scenario_correct": resource_gates["scenario_correct"],
                "normal_rss_below_5_gib": resource_gates["normal_rss_below_5_gib"],
                "all_scenarios_below_8_gib": resource_gates[
                    "all_scenarios_below_8_gib"
                ],
                "hard_rss_below_8_gib_all_scenarios": resource_gates[
                    "hard_rss_below_8_gib_all_scenarios"
                ],
                "cpu_core_equivalent_at_most_4": resource_gates[
                    "cpu_core_equivalent_at_most_4"
                ],
            },
            "optional_local_infrastructure_probe": env_status,
        },
        "limitations": [
            env_status,
            "Current representative SR is diagnostic only, not a final model-mix claim.",
        ],
        "carry_forward": [
            "FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED",
            "MODEL_STATE_RESOURCE_REVIEW_REQUIRED_DURING_MODEL_REFACTOR",
        ],
    }
    artifact["deterministic_identity_sha256"] = deterministic_identity_sha256(artifact)
    artifact["measurement_payload_sha256"] = measurement_payload_sha256(artifact)
    return artifact


async def _async_main(root: Path) -> int:
    try:
        artifact = await run_certification(root)
    except Exception as exc:  # noqa: BLE001 - fail closed with bounded evidence
        artifact = {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCKED_INVARIANT",
            "created_at": datetime.now(UTC),
            "source_base": _git_sha(root),
            "worktree": str(root),
            "error": f"D10 certification failed before artifact completion: {exc}",
            "carry_forward": [
                "FINAL_MODEL_MIX_RESOURCE_RECERTIFICATION_REQUIRED",
            ],
        }
    digest = write_artifact(artifact, ARTIFACT_PATH)
    print(artifact["status"])
    print(f"artifact={ARTIFACT_PATH}")
    print(f"sha256={digest}")
    return 0 if artifact["status"] == "APPROVED" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()
    return asyncio.run(_async_main(args.root.resolve()))


if __name__ == "__main__":
    raise SystemExit(main())
