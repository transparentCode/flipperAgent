import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

import yaml
from pydantic import BaseModel, ValidationError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from flipper_agent.commons.env import get_env
from flipper_agent.commons.logging.logger_utils import SystemComponent, bind_logger

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

    def __init__(self, config_dir: Optional[str] = None):
        with self._lock:
            if getattr(self, "_initialized", False):
                return
            
            self._config_dir = Path(config_dir) if config_dir else Path(os.getcwd()) / "configs"
            self._env = get_env("FLIPPER_ENV", "dev")
            self._state: Dict[str, Any] = {}
            self._subscribers: Dict[str, list[Callable[[Any], None]]] = {}
            self._subscription_lock = threading.Lock()
            
            self._observer: Optional[Observer] = None
            self._debounce_timer: Optional[threading.Timer] = None
            self._debounce_lock = threading.Lock()
            self._debounce_delay = 0.5  # 500ms debounce
            
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
            base_data = self._read_yaml(self._config_dir / "base.yaml")
            env_data = self._read_yaml(self._config_dir / f"{self._env}.yaml")
            local_data = self._read_yaml(self._config_dir / "local.yaml")
            
            new_state = self._merge_dicts(base_data, env_data)
            new_state = self._merge_dicts(new_state, local_data)
            
            old_state = self._state
            self._state = new_state  # Atomic pointer swap for thread safety
            
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
                    
        self._observer = Observer()
        self._observer.schedule(ConfigHandler(self), str(self._config_dir), recursive=False)
        self._observer.start()

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
            cls._instance = None
