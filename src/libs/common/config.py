import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

import yaml
from pydantic import BaseModel, ValidationError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent
from libs.common.constants import (
    DEFAULT_ENV,
    DEFAULT_CONFIG_DIR_NAME,
    CONFIG_BASE_FILENAME,
    CONFIG_LOCAL_FILENAME,
    CONFIG_DEBOUNCE_DELAY_SEC,
)

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

T = TypeVar("T", bound=BaseModel)

class ConfigManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_dir: Optional[str] = None, env: str = DEFAULT_ENV):
        with self._lock:
            if getattr(self, "_initialized", False):
                return
            
            self._config_dir = Path(config_dir) if config_dir else Path(os.getcwd()) / DEFAULT_CONFIG_DIR_NAME
            self._env = env
            self._state: Dict[str, Any] = {}
            self._file_states: Dict[str, Dict[str, Any]] = {}
            self._file_paths: Dict[str, str] = {}
            self._registered_files: set[Path] = set()
            self._watched_dirs = set()
            self._watched_dirs.add(self._config_dir)
            self._subscribers: Dict[str, list[Callable[[Any], None]]] = {}
            self._subscription_lock = threading.Lock()
            
            self._observer: Optional[Observer] = None
            self._debounce_timer: Optional[threading.Timer] = None
            self._debounce_lock = threading.Lock()
            self._debounce_delay = CONFIG_DEBOUNCE_DELAY_SEC
            
            self._load_configs(trigger_callbacks=False)
            self._start_watchdog()
            self._initialized = True

    def _merge_dicts(self, dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge dict2 into dict1."""
        merged = dict1.copy()
        for k, v in dict2.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = self._merge_dicts(merged[k], v)
            else:
                merged[k] = v
        return merged

    def _read_yaml(self, file_path: Path) -> Dict[str, Any]:
        if not file_path.exists():
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data is not None else {}
        except Exception as e:
            logger.error(f"Failed to parse YAML file {file_path}", extra={"exception": str(e)}, exc_info=True)
            raise

    def _load_configs(self, trigger_callbacks: bool = True) -> None:
        logger.info(f"Loading configs from {self._config_dir} for env={self._env}")
        try:
            new_state = {}
            new_file_states: Dict[str, Dict[str, Any]] = {}
            new_file_paths: Dict[str, str] = {}

            # Load base first
            base_file = self._config_dir / CONFIG_BASE_FILENAME
            if base_file.exists():
                base_data = self._read_yaml(base_file)
                new_file_states[base_file.stem] = base_data
                new_file_paths[base_file.stem] = str(base_file)
                new_state = self._merge_dicts(new_state, base_data)

            env_file = self._config_dir / f"{self._env}.yaml"
            local_file = self._config_dir / CONFIG_LOCAL_FILENAME

            # Load explicitly registered files (e.g. features.yaml)
            for registered_file in self._registered_files:
                if registered_file.exists():
                    file_data = self._read_yaml(registered_file)
                    new_file_states[registered_file.stem] = file_data
                    new_file_paths[registered_file.stem] = str(registered_file)
                    new_state = self._merge_dicts(new_state, file_data)

            # Load env and local last for overrides
            if env_file.exists():
                env_data = self._read_yaml(env_file)
                new_file_states[env_file.stem] = env_data
                new_file_paths[env_file.stem] = str(env_file)
                new_state = self._merge_dicts(new_state, env_data)
            if local_file.exists():
                local_data = self._read_yaml(local_file)
                new_file_states[local_file.stem] = local_data
                new_file_paths[local_file.stem] = str(local_file)
                new_state = self._merge_dicts(new_state, local_data)

            old_state = self._state
            self._state = new_state  # Atomic pointer swap for thread safety
            self._file_states = new_file_states
            self._file_paths = new_file_paths

            if trigger_callbacks:
                self._notify_subscribers(old_state, new_state)
        except Exception as e:
            logger.error("Poison pill detected in config reloading. Retaining old state.", extra={"exception": str(e)}, exc_info=True)

    def _get_nested(self, state: Dict[str, Any], key_path: str, default: Any = None) -> Any:
        if not key_path:
            return state
            
        keys = key_path.split('.')
        current = state
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get a value by dot-separated key_path, e.g., 'ingestion.binance.rate_limit'"""
        return self._get_nested(self._state, key_path, default)

    def get_feature_params(self, asset: str, timeframe: str, indicator_name: str) -> Dict[str, Any]:
        """
        Retrieves feature (indicator) parameters with fallback to 'default' timeframe or 'default' asset.
        """
        features_config = self.get("features", {})
        assets_config = features_config.get("assets", {})
        
        # Look for specific asset; if not found, fallback to 'default' asset
        asset_node = assets_config.get(asset, assets_config.get("default", {}))
        
        timeframes_config = asset_node.get("timeframes", {})
        
        # Look for specific timeframe; if not found, fallback to 'default' timeframe
        timeframe_node = timeframes_config.get(timeframe, timeframes_config.get("default", {}))
        
        # First priority: exactly matched asset & exactly matched timeframe (or its defaults)
        if indicator_name in timeframe_node:
            return timeframe_node[indicator_name]
        
        # Second priority: Attempt deep fallback to global 'default' asset and 'default' timeframe
        default_asset_node = assets_config.get("default", {})
        default_timeframe_node = default_asset_node.get("timeframes", {}).get("default", {})
        
        if indicator_name in default_timeframe_node:
            return default_timeframe_node[indicator_name]
            
        return {}

    def get_parsed(self, key_path: str, model_class: type[T]) -> Optional[T]:
        """Get a value parsed into a Pydantic model. Logs a warning on failure."""
        val = self.get(key_path)
        if val is None:
            return None
        try:
            return model_class.model_validate(val)
        except ValidationError as e:
            logger.error(f"Config validation error for key '{key_path}'", extra={"exception": str(e)}, exc_info=True)
            return None

    def subscribe(self, key_path: str, callback: Callable[[Any], None]) -> None:
        """Subscribe block-level callback for changes in a specific key path."""
        with self._subscription_lock:
            if key_path not in self._subscribers:
                self._subscribers[key_path] = []
            self._subscribers[key_path].append(callback)

    def _notify_subscribers(self, old_state: Dict[str, Any], new_state: Dict[str, Any]) -> None:
        with self._subscription_lock:
            subs = dict(self._subscribers)
            
        for key_path, callbacks in subs.items():
            old_val = self._get_nested(old_state, key_path)
            new_val = self._get_nested(new_state, key_path)
            if old_val != new_val:
                for cb in callbacks:
                    try:
                        cb(new_val)
                    except Exception as e:
                        logger.error(f"Error in config subscriber callback for '{key_path}'", extra={"exception": str(e)}, exc_info=True)

    def _trigger_reload(self) -> None:
        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self._debounce_delay, self._load_configs)
            self._debounce_timer.start()

    def _start_watchdog(self) -> None:
        if not self._config_dir.exists():
            self._config_dir.mkdir(parents=True, exist_ok=True)
            
        class ConfigHandler(FileSystemEventHandler):
            def __init__(self, manager: 'ConfigManager'):
                self.manager = manager
                
            def on_modified(self, event: Any) -> None:
                if event.is_directory:
                    return
                if event.src_path.endswith('.yaml') or event.src_path.endswith('.yml'):
                    self.manager._trigger_reload()
                    
        try:
            self._observer = Observer()
            for d in self._watched_dirs:
                if d.exists():
                    self._observer.schedule(ConfigHandler(self), str(d), recursive=False)
            self._observer.daemon = True
            self._observer.start()
        except Exception:
            logger.warning("Watchdog file monitoring unavailable \u2014 config hot-reload disabled")
            self._observer = None

    def register_file(self, file_path: str | Path) -> None:
        resolved = Path(file_path).resolve()
        with self._subscription_lock:
            if resolved in self._registered_files:
                return  # already registered
            self._registered_files.add(resolved)
            parent_dir = resolved.parent
            if parent_dir not in self._watched_dirs:
                self._watched_dirs.add(parent_dir)
                if self._observer and parent_dir.exists():
                    # We use a localized handler for the new directory
                    class LocalConfigHandler(FileSystemEventHandler):
                        def __init__(self, manager):
                            self.manager = manager
                        def on_modified(self, event):
                            if not event.is_directory and (event.src_path.endswith('.yaml') or event.src_path.endswith('.yml')):
                                self.manager._trigger_reload()
                    self._observer.schedule(LocalConfigHandler(self), str(parent_dir), recursive=False)
        # trigger a reload to bring the new file in
        self._load_configs(trigger_callbacks=True)

    def get_all_file_states(self) -> list[Dict[str, Any]]:
        """Return per-file config info as a list of entries.

        Each entry has shape: ``{"fileName": str, "filePath": str, "contents": dict}``
        so callers can identify the source file, display it, and POST updates using fileName.
        """
        return [
            {
                "fileName": stem,
                "filePath": self._file_paths.get(stem, ""),
                "contents": data,
            }
            for stem, data in self._file_states.items()
        ]

    def update_yaml_file(self, filename: str, updates: Dict[str, Any]) -> None:
        """Deep-merge *updates* into the on-disk YAML file identified by *filename* stem.

        Only files that are already tracked (registered or base) are writable.
        The watchdog detects the write and triggers a reload in all containers.
        Raises ValueError for unknown or path-traversal filenames.
        Raises FileNotFoundError if the resolved file does not exist on disk.
        """
        # Allowlist: base + every registered file stem
        allowed_stems = {Path(CONFIG_BASE_FILENAME).stem} | {f.stem for f in self._registered_files}
        if filename not in allowed_stems:
            raise ValueError(
                f"Unknown config file '{filename}'. Allowed: {sorted(allowed_stems)}"
            )

        # Resolve path strictly within _config_dir or registered file dirs
        candidate: Optional[Path] = None
        if filename == Path(CONFIG_BASE_FILENAME).stem:
            candidate = self._config_dir / CONFIG_BASE_FILENAME
        else:
            for reg in self._registered_files:
                if reg.stem == filename:
                    candidate = reg
                    break

        if candidate is None or not candidate.exists():
            raise FileNotFoundError(f"Config file for '{filename}' not found on disk.")

        # Read → deep-merge → write atomically via temp file
        existing = self._read_yaml(candidate)
        merged = self._merge_dicts(existing, updates)

        tmp_path = candidate.with_suffix(".yaml.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                yaml.dump(merged, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
            tmp_path.replace(candidate)  # atomic on POSIX
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        logger.info(f"Config file updated on disk: {candidate.name} — watchdog reload will follow.")

    def shutdown(self) -> None:
        """Clean shutdown of watchdog and timers."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        
        with self._debounce_lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

    @classmethod
    def reset_singleton(cls):
        """Used mainly for testing to allow fresh instantiation."""
        with cls._lock:
            if cls._instance is not None:
                if hasattr(cls._instance, '_observer') and cls._instance._observer is not None:
                    cls._instance._observer.stop()
                    cls._instance._observer.join(timeout=2)
                with cls._instance._debounce_lock:
                    if cls._instance._debounce_timer is not None:
                        cls._instance._debounce_timer.cancel()
                        cls._instance._debounce_timer = None
            cls._instance = None
