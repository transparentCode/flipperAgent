"""Queue-driven sidecar daemon for SR microstructure profiling."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from app.sr.config_resolver import RuleDerivedParamsCalculator, SRConfigResolver
from app.sr.config_schema import PipelineConfig
from app.sr.scripts._utils import build_characteristics, fetch_data, get_optimal_lookback_days
from app.sr.sidecar.queue import ProfileTask, create_profile_task_queue

logger = logging.getLogger(__name__)


class SRSidecarDaemon:
    """Drain profile tasks, compute microstructure, and materialize YAML overrides."""

    def __init__(
        self,
        config_path: str,
        *,
        queue_backend: str = "sqlite",
        queue_path: Optional[str] = None,
        fetcher: Optional[Callable[..., Any]] = None,
        lookback_days: Optional[int] = None,
        backup: bool = False,
    ) -> None:
        self._config_path = Path(config_path).expanduser().resolve()
        self._queue = create_profile_task_queue(queue_backend, queue_path)
        self._fetcher = fetcher or fetch_data
        self._lookback_days_override = lookback_days
        self._backup = backup
        self._resolver = SRConfigResolver()

    def _load_config(self) -> Dict[str, Any]:
        if not self._config_path.exists():
            return {}
        with self._config_path.open() as handle:
            loaded = yaml.safe_load(handle) or {}
        return loaded if isinstance(loaded, dict) else {}

    def run_once(self) -> int:
        tasks = self._queue.dequeue(limit=1)
        if not tasks:
            return 0

        processed = 0
        for task in tasks:
            try:
                self._process_task(task)
            except Exception:
                if task.id is not None:
                    self._queue.requeue(task.id)
                raise

            if task.id is not None:
                self._queue.ack(task.id)
            processed += 1
        return processed

    def run_forever(self, poll_interval_s: float = 1.0, max_backoff_s: float = 60.0) -> None:
        consecutive_errors = 0
        while True:
            try:
                processed = self.run_once()
                consecutive_errors = 0
                if processed == 0:
                    time.sleep(poll_interval_s)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                consecutive_errors += 1
                backoff = min(poll_interval_s * (2 ** consecutive_errors), max_backoff_s)
                logger.exception("SR sidecar task failed (attempt %d, backoff %.1fs): %s", consecutive_errors, backoff, exc)
                time.sleep(backoff)

    def close(self) -> None:
        self._queue.close()

    def _process_task(self, task: ProfileTask) -> None:
        raw_config = self._load_config()
        metadata = self._resolver.resolve_metadata(
            task.symbol,
            raw_config.get("asset_metadata", {}),
        )
        merged = self._resolver.cascade_merge(task.symbol, task.timeframe, raw_config)
        atr_period = int(merged.get("pipeline", {}).get("atr_period", PipelineConfig.atr_period))
        rule_derived_config = self._resolver.build_rule_derived_config(merged.get("rule_derived", {}))
        lookback_days = self._lookback_days_override
        if lookback_days is None:
            lookback_days = get_optimal_lookback_days(task.timeframe)

        df = self._fetcher(
            task.symbol,
            task.timeframe,
            lookback_days=lookback_days,
            quiet=True,
        )
        if df is None or len(df) == 0:
            raise ValueError(f"No OHLCV data available for {task.symbol} {task.timeframe}")

        characteristics = build_characteristics(
            df,
            task.symbol,
            task.timeframe,
            metadata,
            atr_period=atr_period,
        )
        derived = RuleDerivedParamsCalculator(rule_derived_config).compute(characteristics)
        self._write_profile(task, characteristics, derived)

    def _write_profile(self, task: ProfileTask, characteristics, derived) -> None:
        if self._backup and self._config_path.exists():
            shutil.copy2(self._config_path, self._config_path.with_suffix(self._config_path.suffix + ".bak"))

        yaml_handler = None
        yaml_doc: Any = None
        try:
            from ruamel.yaml import YAML

            yaml_handler = YAML()
            yaml_handler.preserve_quotes = True
            if self._config_path.exists():
                with self._config_path.open() as handle:
                    yaml_doc = yaml_handler.load(handle) or {}
            else:
                yaml_doc = {}
        except ImportError:
            yaml_doc = self._load_config()

        if not isinstance(yaml_doc, dict):
            yaml_doc = {}

        assets = yaml_doc.setdefault("assets", {})
        asset_bucket = assets.setdefault(task.symbol, {})
        tf_bucket = asset_bucket.setdefault(task.timeframe, {})

        tf_bucket["_profiler_meta"] = {
            "last_profiled_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "wick_p75_atr": float(characteristics.wick_p75_atr),
            "body_p50_atr": float(characteristics.body_p50_atr),
            "mean_volume": float(characteristics.volume_mean),
        }

        pipeline_cfg = tf_bucket.setdefault("pipeline", {})
        pipeline_cfg["merge_threshold_pct_atr"] = float(derived.merge_threshold_pct_atr)
        pipeline_cfg["dedup_proximity_atr"] = float(derived.dedup_proximity_atr)
        pipeline_cfg["zone_half_width_atr"] = float(derived.zone_half_width_atr)

        lifecycle_cfg = tf_bucket.setdefault("lifecycle", {})
        lifecycle_cfg["breakout_atr_threshold"] = float(derived.breakout_atr_threshold)
        lifecycle_cfg["touch_proximity_atr"] = float(derived.touch_proximity_atr)
        lifecycle_cfg["false_breakout_recovery_bars"] = int(derived.false_breakout_recovery_bars)

        enhancement_cfg = tf_bucket.setdefault("enhancement", {})
        enhancement_cfg["volume_spike_threshold"] = float(derived.volume_spike_threshold)

        self._atomic_dump(yaml_doc, yaml_handler)

    def _atomic_dump(self, payload: Dict[str, Any], yaml_handler) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=self._config_path.stem + ".",
            suffix=self._config_path.suffix,
            dir=str(self._config_path.parent),
        )
        os.close(fd)
        try:
            with open(tmp_path, "w") as handle:
                if yaml_handler is not None:
                    yaml_handler.dump(payload, handle)
                else:
                    yaml.safe_dump(payload, handle, sort_keys=False)
            os.replace(tmp_path, self._config_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)