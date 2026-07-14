"""
Universe S/R Router
====================
Dispatches ``SRv2Pipeline`` instances across multiple assets and
timeframes.  Manages per-(asset, timeframe) pipeline instances,
applies the 3-tier config cascade, and supports parallel execution.

Usage::

    router = UniverseSRRouter(universe_config, config_resolver, regime_gate)
    result = router.process(data_map, bar_index=100, timestamp=now)

Where ``data_map`` is ``Dict[str, Dict[str, pd.DataFrame]]`` keyed
by ``{symbol: {timeframe: df}}``.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from app.sr.config_resolver import SRConfigResolver
from app.sr.config_schema import SRResolvedConfig
from app.sr.pipeline import PipelineResult, SRv2Pipeline
from app.sr.regime_gate import RegimeGate
from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

logger = logging.getLogger(__name__)


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    import yaml

    with path.open() as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *overlay* into *base* without mutating inputs."""
    result = copy.deepcopy(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


@dataclass
class AssetTimeframeResult:
    """Result for one (asset, timeframe) pair."""
    asset: str
    timeframe: str
    result: PipelineResult
    elapsed_ms: float


@dataclass
class UniverseResult:
    """Result for the entire universe."""
    results: Dict[str, Dict[str, AssetTimeframeResult]] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def all_results(self) -> List[AssetTimeframeResult]:
        """Flat list of all results."""
        return [
            r
            for per_tf in self.results.values()
            for r in per_tf.values()
        ]

    def get(self, asset: str, timeframe: str) -> Optional[AssetTimeframeResult]:
        """Get result for a specific (asset, timeframe)."""
        return self.results.get(asset, {}).get(timeframe)


class UniverseSRRouter:
    """
    Universe-wide S/R router.

    Manages per-(asset, tf) pipeline instances and dispatches bar
    updates in parallel.
    """

    def __init__(
        self,
        config: UniverseSRConfig,
        config_resolver: Optional[SRConfigResolver] = None,
        regime_gate: Optional[RegimeGate] = None,
    ):
        self._config = config
        self._resolver = config_resolver or SRConfigResolver()
        self._regime_gate = regime_gate or RegimeGate()
        self._pipeline_lock = threading.RLock()
        self._pipelines: Dict[str, SRv2Pipeline] = {}  # key: "asset:tf"
        self._raw_configs: Dict[str, Dict[str, Any]] = {}  # key: "asset:tf" → raw_config for re-resolution
        self._profile_request_at: Dict[str, datetime] = {}
        self._config_path = self._resolve_config_path()
        self._sidecar_queue = None
        self._config_observer = None
        self._last_config_mtime_ns: Optional[int] = None

        if self._config.sidecar_enabled:
            from app.sr.sidecar.queue import create_profile_task_queue

            self._sidecar_queue = create_profile_task_queue(
                backend=self._config.sidecar_queue_backend,
                queue_path=self._resolve_queue_path(),
            )
            if self._config.sidecar_watch_config:
                self._start_config_watcher()

    def _resolve_config_path(self) -> Path:
        if self._config.sidecar_config_path:
            return Path(self._config.sidecar_config_path).expanduser().resolve()
        return Path(__file__).resolve().parents[1] / "config" / "sr.yaml"

    def _resolve_queue_path(self) -> str:
        if self._config.sidecar_queue_path:
            return self._config.sidecar_queue_path
        return str(self._config_path.with_name("sr_sidecar.sqlite3"))

    def _load_sidecar_config(self) -> Dict[str, Any]:
        return _load_yaml_file(self._config_path)

    def _build_raw_config(
        self,
        symbol: str,
        timeframe: str,
        asset_config: Optional[AssetSRConfig] = None,
    ) -> Dict[str, Any]:
        raw_global = {}
        if self._config.sidecar_enabled:
            raw_global = self._load_sidecar_config()
        raw_global = _deep_merge(raw_global, copy.deepcopy(self._config.global_config))

        raw_config: Dict[str, Any] = {
            "asset_metadata": copy.deepcopy(raw_global.get("asset_metadata", {})),
            "sr": copy.deepcopy(raw_global.get("sr", {})),
            "per_tf": copy.deepcopy(raw_global.get("per_tf", {})),
            "assets": copy.deepcopy(raw_global.get("assets", {})),
        }

        top_level_global = {
            key: value
            for key, value in raw_global.items()
            if key not in {"asset_metadata", "sr", "per_tf", "assets"}
        }
        if top_level_global:
            raw_config["sr"] = _deep_merge(raw_config["sr"], top_level_global)

        tf_overrides = self._config.timeframe_overrides.get(timeframe, {})
        if tf_overrides:
            existing_tf = raw_config["per_tf"].get(timeframe, {})
            raw_config["per_tf"][timeframe] = _deep_merge(existing_tf, tf_overrides)

        asset_bucket = copy.deepcopy(raw_config["assets"].get(symbol, {}))
        asset_defaults = copy.deepcopy(asset_bucket.get("defaults", {}))

        if asset_config and asset_config.config_overrides:
            asset_defaults = _deep_merge(asset_defaults, asset_config.config_overrides)

        if asset_config and asset_config.enabled_kernels is not None:
            asset_defaults = _deep_merge(
                asset_defaults,
                {"pipeline": {"enabled_kernels": asset_config.enabled_kernels}},
            )
        elif self._config.default_enabled_kernels is not None:
            asset_defaults = _deep_merge(
                asset_defaults,
                {"pipeline": {"enabled_kernels": self._config.default_enabled_kernels}},
            )

        if asset_defaults:
            asset_bucket["defaults"] = asset_defaults
        if asset_bucket:
            raw_config["assets"][symbol] = asset_bucket
        return raw_config

    def _profile_is_stale(self, resolved: SRResolvedConfig) -> bool:
        profiler_meta = resolved.profiler_meta
        if not profiler_meta:
            return True

        last_profiled_at = profiler_meta.get("last_profiled_at")
        if not isinstance(last_profiled_at, str) or not last_profiled_at:
            return True

        try:
            normalized = last_profiled_at.replace("Z", "+00:00")
            profiled_at = datetime.fromisoformat(normalized)
        except ValueError:
            return True

        if profiled_at.tzinfo is None:
            profiled_at = profiled_at.replace(tzinfo=UTC)
        return profiled_at < datetime.now(UTC) - timedelta(days=self._config.sidecar_stale_after_days)

    def _enqueue_profile_task_if_needed(
        self,
        symbol: str,
        timeframe: str,
        resolved: SRResolvedConfig,
    ) -> None:
        if not self._config.sidecar_enabled or self._sidecar_queue is None:
            return

        reason = None
        if resolved.requires_sidecar_derivation:
            reason = "missing_microstructure_profile"
        elif self._profile_is_stale(resolved):
            reason = "stale_microstructure_profile"

        if reason is None:
            return

        key = f"{symbol}:{timeframe}"
        now = datetime.now(UTC)
        last_requested = self._profile_request_at.get(key)
        if last_requested and (now - last_requested).total_seconds() < 3600:
            return

        from app.sr.sidecar.queue import ProfileTask

        self._sidecar_queue.enqueue(
            ProfileTask(
                symbol=symbol,
                timeframe=timeframe,
                reason=reason,
                timestamp=now.isoformat(),
            ),
        )
        self._profile_request_at[key] = now

    def _start_config_watcher(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("watchdog is not installed; SR hot reload is disabled")
            return

        if self._config_observer is not None:
            return

        router = self

        class _SRConfigReloadHandler(FileSystemEventHandler):
            def on_modified(self, event) -> None:
                if event.is_directory:
                    return
                if Path(event.src_path).expanduser().resolve() != router._config_path:
                    return
                router._handle_config_change()

            def on_created(self, event) -> None:
                self.on_modified(event)

        observer = Observer()
        observer.daemon = True
        observer.schedule(_SRConfigReloadHandler(), str(self._config_path.parent), recursive=False)
        observer.start()
        self._config_observer = observer

    def _handle_config_change(self) -> None:
        try:
            mtime_ns = self._config_path.stat().st_mtime_ns
        except FileNotFoundError:
            return

        if self._last_config_mtime_ns == mtime_ns:
            return

        self._last_config_mtime_ns = mtime_ns
        self._reload_pipelines_from_config()

    def _reload_pipelines_from_config(self) -> None:
        asset_lookup = {asset.symbol: asset for asset in self._config.assets}
        with self._pipeline_lock:
            existing_items = list(self._pipelines.items())

        for key, existing_pipeline in existing_items:
            symbol, timeframe = key.split(":", 1)
            asset_config = asset_lookup.get(symbol)
            raw_config = self._build_raw_config(symbol, timeframe, asset_config)
            resolved = self._resolver.resolve(
                symbol=symbol,
                timeframe=timeframe,
                raw_config=raw_config,
            )
            resolved = self._apply_disabled_kernels(resolved, asset_config)
            if resolved == existing_pipeline._config:
                with self._pipeline_lock:
                    self._raw_configs[key] = raw_config
                continue

            new_pipeline = SRv2Pipeline(
                config=resolved,
                regime_gate=self._regime_gate,
                asset=symbol,
                timeframe=timeframe,
            )
            new_pipeline._candidate_cache = dict(existing_pipeline._candidate_cache)
            with self._pipeline_lock:
                self._pipelines[key] = new_pipeline
                self._raw_configs[key] = raw_config
            self._enqueue_profile_task_if_needed(symbol, timeframe, resolved)
            logger.info("Hot-reloaded SR pipeline for %s", key)

    def close(self) -> None:
        if self._config_observer is not None:
            self._config_observer.stop()
            self._config_observer.join(timeout=1.0)
            self._config_observer = None
        if self._sidecar_queue is not None:
            self._sidecar_queue.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _configured_timeframes(
        self,
        asset_config: Optional[AssetSRConfig],
    ) -> List[str]:
        """Resolve the allowed timeframes for one asset."""
        configured = (
            asset_config.timeframes
            if asset_config and asset_config.timeframes is not None
            else self._config.default_timeframes
        )
        return list(dict.fromkeys(configured))

    def _apply_disabled_kernels(
        self,
        resolved: SRResolvedConfig,
        asset_config: Optional[AssetSRConfig],
    ) -> SRResolvedConfig:
        """Filter disabled kernels after the config cascade has resolved defaults."""
        if asset_config is None or not asset_config.disabled_kernels:
            return resolved

        disabled = set(asset_config.disabled_kernels)
        enabled = [
            kernel_name
            for kernel_name in resolved.pipeline.enabled_kernels
            if kernel_name not in disabled
        ]
        if enabled == resolved.pipeline.enabled_kernels:
            return resolved

        pipeline = replace(resolved.pipeline, enabled_kernels=enabled)
        return replace(resolved, pipeline=pipeline)

    def _get_or_create_pipeline(
        self,
        symbol: str,
        timeframe: str,
        asset_config: Optional[AssetSRConfig] = None,
        df: Optional[pd.DataFrame] = None,
    ) -> SRv2Pipeline:
        """Get cached pipeline or create a new one."""
        key = f"{symbol}:{timeframe}"
        with self._pipeline_lock:
            cached = self._pipelines.get(key)
        if cached is not None:
            self._enqueue_profile_task_if_needed(symbol, timeframe, cached._config)
            return cached

        raw_config = self._build_raw_config(symbol, timeframe, asset_config)

        resolved = self._resolver.resolve(
            symbol=symbol,
            timeframe=timeframe,
            raw_config=raw_config,
        )
        resolved = self._apply_disabled_kernels(resolved, asset_config)

        pipeline = SRv2Pipeline(
            config=resolved,
            regime_gate=self._regime_gate,
            asset=symbol,
            timeframe=timeframe,
        )
        with self._pipeline_lock:
            self._pipelines[key] = pipeline
            self._raw_configs[key] = raw_config
        self._enqueue_profile_task_if_needed(symbol, timeframe, resolved)
        return pipeline

    def _process_one(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        bar_index: int,
        timestamp: datetime,
        asset_config: Optional[AssetSRConfig],
    ) -> AssetTimeframeResult:
        """Run pipeline for one (asset, tf) pair."""
        t0 = time.monotonic()
        pipeline = self._get_or_create_pipeline(
            symbol,
            timeframe,
            asset_config,
        )

        result = pipeline.run(df, bar_index=bar_index, timestamp=timestamp)
        elapsed = (time.monotonic() - t0) * 1000
        return AssetTimeframeResult(
            asset=symbol,
            timeframe=timeframe,
            result=result,
            elapsed_ms=elapsed,
        )

    def process(
        self,
        data_map: Dict[str, Dict[str, pd.DataFrame]],
        bar_index: int = 0,
        timestamp: Optional[datetime] = None,
    ) -> UniverseResult:
        """
        Process all assets and timeframes.

        Args:
            data_map: ``{symbol: {timeframe: df}}``
            bar_index: Current bar index for lifecycle tracking.
            timestamp: Current timestamp.

        Returns:
            ``UniverseResult`` with per-(asset, tf) results.
        """
        if timestamp is None:
            timestamp = datetime.now(tz=None)

        t0 = time.monotonic()
        asset_lookup = {a.symbol: a for a in self._config.assets}
        errors: Dict[str, str] = {}

        # Build work items
        work_items = []
        for symbol, tf_data in data_map.items():
            asset_cfg = asset_lookup.get(symbol)
            allowed_timeframes = self._configured_timeframes(asset_cfg)
            allowed_timeframe_set = set(allowed_timeframes)
            for tf, df in tf_data.items():
                if tf not in allowed_timeframe_set:
                    if df is not None and len(df) > 0:
                        errors[f"{symbol}:{tf}"] = (
                            f"timeframe '{tf}' is not configured for {symbol}; "
                            f"allowed timeframes: {', '.join(allowed_timeframes)}"
                        )
                    continue
                if df is not None and len(df) > 0:
                    work_items.append((symbol, tf, df, asset_cfg))

        results: Dict[str, Dict[str, AssetTimeframeResult]] = {}

        if self._config.max_workers <= 1 or len(work_items) <= 1:
            # Sequential
            for symbol, tf, df, acfg in work_items:
                try:
                    r = self._process_one(symbol, tf, df, bar_index, timestamp, acfg)
                    results.setdefault(symbol, {})[tf] = r
                except Exception as e:
                    logger.error("SR pipeline error %s:%s — %s", symbol, tf, e)
                    errors[f"{symbol}:{tf}"] = str(e)
        else:
            # Parallel
            with ThreadPoolExecutor(max_workers=self._config.max_workers) as pool:
                futures = {
                    pool.submit(
                        self._process_one, symbol, tf, df, bar_index, timestamp, acfg,
                    ): (symbol, tf)
                    for symbol, tf, df, acfg in work_items
                }
                pending = set(futures)
                timeout_s = self._config.timeout_per_asset_s * len(work_items)
                try:
                    for future in as_completed(futures, timeout=timeout_s):
                        pending.discard(future)
                        symbol, tf = futures[future]
                        try:
                            r = future.result()
                            results.setdefault(symbol, {})[tf] = r
                        except Exception as e:
                            logger.error("SR pipeline error %s:%s — %s", symbol, tf, e)
                            errors[f"{symbol}:{tf}"] = str(e)
                except FuturesTimeoutError:
                    for future in pending:
                        symbol, tf = futures[future]
                        future.cancel()
                        logger.error(
                            "SR pipeline timeout %s:%s after %.3fs",
                            symbol,
                            tf,
                            timeout_s,
                        )
                        errors[f"{symbol}:{tf}"] = (
                            f"processing timed out after {timeout_s:.3f}s"
                        )

        elapsed = (time.monotonic() - t0) * 1000
        return UniverseResult(results=results, errors=errors, elapsed_ms=elapsed)

    def reset(self, symbol: Optional[str] = None) -> None:
        """Clear cached pipelines. If symbol given, clear only that asset."""
        with self._pipeline_lock:
            if symbol:
                keys = [k for k in self._pipelines if k.startswith(f"{symbol}:")]
                for k in keys:
                    self._pipelines.pop(k, None)
                    self._raw_configs.pop(k, None)
                    self._profile_request_at.pop(k, None)
            else:
                self._pipelines.clear()
                self._raw_configs.clear()
                self._profile_request_at.clear()
