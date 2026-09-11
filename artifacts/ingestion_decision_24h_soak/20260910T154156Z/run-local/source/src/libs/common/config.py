import os
import tempfile
import threading
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

import yaml
from pydantic import BaseModel, ValidationError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from libs.common.constants import (
    CONFIG_BASE_FILENAME,
    CONFIG_DEBOUNCE_DELAY_SEC,
    CONFIG_LOCAL_FILENAME,
    DEFAULT_CONFIG_DIR_NAME,
    DEFAULT_ENV,
)
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

T = TypeVar("T", bound=BaseModel)


class _ConfigFileEventHandler(FileSystemEventHandler):
    def __init__(self, manager: "ConfigManager"):
        self.manager = manager

    @staticmethod
    def _is_config_file(path: str) -> bool:
        return Path(path).suffix.lower() in {".yaml", ".yml"}

    def _reload_for_event(self, event: Any) -> None:
        if event.is_directory:
            return
        paths = [event.src_path]
        destination = getattr(event, "dest_path", None)
        if destination:
            paths.append(destination)
        if any(self._is_config_file(path) for path in paths):
            self.manager._trigger_reload()

    def on_modified(self, event: Any) -> None:
        self._reload_for_event(event)

    def on_created(self, event: Any) -> None:
        self._reload_for_event(event)

    def on_deleted(self, event: Any) -> None:
        self._reload_for_event(event)

    def on_moved(self, event: Any) -> None:
        self._reload_for_event(event)


class ConfigManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_dir: Optional[str] = None, env: Optional[str] = None):
        with self._lock:
            if getattr(self, "_initialized", False):
                return
            
            self._config_dir = Path(config_dir) if config_dir else Path(os.getcwd()) / DEFAULT_CONFIG_DIR_NAME
            self._env = env or os.getenv("FLIPPER_ENV") or DEFAULT_ENV
            self._state: Dict[str, Any] = {}
            self._file_states: Dict[str, Dict[str, Any]] = {}
            self._file_paths: Dict[str, str] = {}
            self._file_names: dict[str, str] = {}
            self._registered_files: set[Path] = set()
            self._registered_directories: list[tuple[Path, str, str]] = []
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
            new_file_names: dict[str, str] = {}

            # Load base first
            base_file = self._config_dir / CONFIG_BASE_FILENAME
            if base_file.exists():
                base_data = self._read_yaml(base_file)
                new_file_states[base_file.stem] = base_data
                new_file_paths[base_file.stem] = str(base_file)
                new_file_names[base_file.stem] = base_file.stem
                new_state = self._merge_dicts(new_state, base_data)

            env_file = self._config_dir / f"{self._env}.yaml"
            local_file = self._config_dir / CONFIG_LOCAL_FILENAME

            # Load explicitly registered files (e.g. features.yaml)
            for registered_file in self._registered_files:
                if registered_file.exists():
                    file_data = self._read_yaml(registered_file)
                    new_file_states[registered_file.stem] = file_data
                    new_file_paths[registered_file.stem] = str(registered_file)
                    new_file_names[registered_file.stem] = registered_file.stem
                    new_state = self._merge_dicts(new_state, file_data)

            # Load registered directories as independent namespace entries.
            # Files within one directory are never merged into one another.
            directory_keys: set[str] = set()
            for directory, namespace, pattern in sorted(
                self._registered_directories,
                key=lambda item: (str(item[0]), item[1], item[2]),
            ):
                namespace_parts = namespace.split(".")
                for directory_file in self._directory_files(directory, pattern):
                    logical_key = f"{namespace}.{directory_file.stem}"
                    if logical_key in directory_keys:
                        raise ValueError(f"Duplicate logical config key: {logical_key}")
                    directory_keys.add(logical_key)

                    file_data = self._read_yaml(directory_file)
                    if not isinstance(file_data, dict):
                        raise ValueError(  # noqa: TRY004
                            f"Config file must contain a mapping: {directory_file}"
                        )

                    namespace_state = new_state
                    for namespace_part in namespace_parts:
                        existing = namespace_state.get(namespace_part)
                        if existing is None:
                            existing = {}
                            namespace_state[namespace_part] = existing
                        elif not isinstance(existing, dict):
                            raise ValueError(
                                f"Config namespace is not a mapping: {namespace_part}"
                            )
                        namespace_state = existing
                    if directory_file.stem in namespace_state:
                        raise ValueError(f"Duplicate logical config key: {logical_key}")
                    namespace_state[directory_file.stem] = file_data

                    new_file_states[logical_key] = file_data
                    new_file_paths[logical_key] = str(directory_file)
                    new_file_names[logical_key] = directory_file.stem

            # Load env and local last for overrides
            if env_file.exists():
                env_data = self._read_yaml(env_file)
                new_file_states[env_file.stem] = env_data
                new_file_paths[env_file.stem] = str(env_file)
                new_file_names[env_file.stem] = env_file.stem
                new_state = self._merge_dicts(new_state, env_data)
            if local_file.exists():
                local_data = self._read_yaml(local_file)
                new_file_states[local_file.stem] = local_data
                new_file_paths[local_file.stem] = str(local_file)
                new_file_names[local_file.stem] = local_file.stem
                new_state = self._merge_dicts(new_state, local_data)

            old_state = self._state
            self._state = new_state  # Atomic pointer swap for thread safety
            self._file_states = new_file_states
            self._file_paths = new_file_paths
            self._file_names = new_file_names

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

    # ------------------------------------------------------------------
    # Cross-config validation
    # ------------------------------------------------------------------

    def validate_feature_model_alignment(self) -> list[str]:
        """Cross-validate features.yaml vs models.yaml at startup.

        Returns a list of warning strings describing:
        1. Models whose required_indicators are missing from features.yaml.
        2. Feature asset/timeframe combos with no active model consumer.
        """
        warnings: list[str] = []

        models_config = self.get("models", {})
        models_assets = models_config.get("assets", {})

        features_config = self.get("features", {})
        features_assets = features_config.get("assets", {})

        # ---- Helper: resolve available feature names for a given asset/tf ----
        def _resolve_features(asset: str, timeframe: str) -> set[str]:
            """Replicate the fallback chain for features."""
            fa = features_assets.get(asset, {})
            da = features_assets.get("default", {})

            tf_node = fa.get("timeframes", {}).get(timeframe, {})
            asset_def_tf = fa.get("timeframes", {}).get("default", {})
            def_tf = da.get("timeframes", {}).get(timeframe, {})
            def_def_tf = da.get("timeframes", {}).get("default", {})

            merged: dict[str, Any] = {}
            for node in (def_def_tf, def_tf, asset_def_tf, tf_node):
                merged.update(node)

            names = set(merged.keys())
            for key, cfg in merged.items():
                if isinstance(cfg, dict) and "type" in cfg:
                    names.add(cfg["type"])
            return names

        # ---- 1. Check each enabled model's required_indicators ----
        # This validator is a standalone legacy model/feature boundary. Keep
        # the bootstrap lazy so importing ConfigManager remains side-effect-free.
        from libs.models.legacy_bootstrap import bootstrap_legacy_model_registries
        from libs.models.registry import ModelRegistry

        bootstrap_legacy_model_registries()

        model_consumer_combos: set[tuple[str, str]] = set()

        for asset, asset_node in models_assets.items():
            if asset == "default":
                continue
            for tf, tf_node in asset_node.get("timeframes", {}).items():
                if tf == "default":
                    continue
                has_enabled = False
                for model_name, model_cfg in tf_node.items():
                    if not isinstance(model_cfg, dict):
                        continue
                    if not model_cfg.get("enabled", True):
                        continue
                    has_enabled = True

                    try:
                        model_cls = ModelRegistry.get(model_name)
                    except KeyError:
                        continue  # unknown model — already warned elsewhere
                    required = getattr(model_cls.meta, "required_indicators", [])
                    available = _resolve_features(asset, tf)
                    missing = [ind for ind in required if ind not in available]
                    if missing:
                        warnings.append(
                            f"Model '{model_name}' for {asset}/{tf} requires "
                            f"{missing} but features.yaml does not provide them."
                        )
                if has_enabled:
                    model_consumer_combos.add((asset, tf))

        # ---- 2. Features with no model consumer ----
        for asset, asset_node in features_assets.items():
            if asset == "default":
                continue
            for tf in asset_node.get("timeframes", {}).keys():
                if tf == "default":
                    continue
                if (asset, tf) not in model_consumer_combos:
                    warnings.append(
                        f"Features configured for {asset}/{tf} but no "
                        f"enabled model consumes them (standby)."
                    )

        for w in warnings:
            logger.warning(w)

        return warnings

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

    @staticmethod
    def _directory_files(directory: Path, pattern: str) -> list[Path]:
        return sorted(
            (path for path in directory.glob(pattern) if path.is_file()),
            key=lambda path: path.name,
        )

    def _schedule_watch(self, directory: Path) -> None:
        if self._observer and directory.exists():
            self._observer.schedule(
                _ConfigFileEventHandler(self),
                str(directory),
                recursive=False,
            )

    def _start_watchdog(self) -> None:
        if not self._config_dir.exists():
            self._config_dir.mkdir(parents=True, exist_ok=True)
            
        try:
            self._observer = Observer()
            for directory in sorted(self._watched_dirs, key=str):
                self._schedule_watch(directory)
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
                self._schedule_watch(parent_dir)
        # trigger a reload to bring the new file in
        self._load_configs(trigger_callbacks=True)

    def register_directory(
        self,
        path: str | Path,
        *,
        namespace: str,
        pattern: str = "*.yaml",
    ) -> None:
        """Register a directory of YAML files under independent namespace keys."""
        resolved = Path(path).resolve()
        namespace_parts = tuple(part.strip() for part in str(namespace).split("."))
        if not namespace_parts or any(not part for part in namespace_parts):
            raise ValueError("namespace must contain non-empty dot-separated parts")
        pattern = str(pattern).strip()
        if not pattern:
            raise ValueError("pattern must be non-empty")
        normalized_namespace = ".".join(namespace_parts)
        registration = (resolved, normalized_namespace, pattern)

        with self._subscription_lock:
            if registration in self._registered_directories:
                return

            candidate_keys = [
                f"{normalized_namespace}.{directory_file.stem}"
                for directory_file in self._directory_files(resolved, pattern)
            ]
            if len(candidate_keys) != len(set(candidate_keys)):
                raise ValueError("Duplicate logical config key in registered directory")

            registered_keys = {
                f"{registered_namespace}.{directory_file.stem}"
                for registered_directory, registered_namespace, registered_pattern in self._registered_directories
                for directory_file in self._directory_files(
                    registered_directory,
                    registered_pattern,
                )
            }
            duplicate_keys = registered_keys.intersection(candidate_keys)
            if duplicate_keys:
                raise ValueError(f"Duplicate logical config key: {min(duplicate_keys)}")

            self._registered_directories.append(registration)
            if resolved not in self._watched_dirs:
                self._watched_dirs.add(resolved)
                self._schedule_watch(resolved)

        self._load_configs(trigger_callbacks=True)

    def get_all_file_states(self) -> list[Dict[str, Any]]:
        """Return per-file config info as a list of entries.

        Each entry has shape: ``{"fileName": str, "filePath": str, "contents": dict}``
        so callers can identify the source file, display it, and POST updates using fileName.
        """
        return [
            {
                "fileName": self._file_names.get(source_key, source_key),
                "filePath": self._file_paths.get(source_key, ""),
                "contents": data,
            }
            for source_key, data in self._file_states.items()
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

    @staticmethod
    def _validate_registered_yaml_stem(filename: str) -> str:
        if not isinstance(filename, str):
            raise TypeError("filename must be a string")
        stem = filename.strip()
        if not stem or stem in {".", ".."}:
            raise ValueError("filename must be a non-empty YAML stem")
        if stem != filename or "\x00" in stem:
            raise ValueError("filename must be a clean YAML stem")
        if "/" in stem or "\\" in stem or Path(stem).name != stem:
            raise ValueError("filename must not contain path separators")
        if stem.casefold().endswith((".yaml", ".yml")):
            raise ValueError("filename must be a stem without a YAML suffix")
        return stem

    def _registered_directory_for_namespace(
        self,
        namespace: str,
    ) -> tuple[Path, str, str]:
        namespace_parts = tuple(part.strip() for part in str(namespace).split("."))
        if not namespace_parts or any(not part for part in namespace_parts):
            raise ValueError("namespace must contain non-empty dot-separated parts")
        normalized_namespace = ".".join(namespace_parts)
        with self._subscription_lock:
            matches = [
                registration
                for registration in self._registered_directories
                if registration[1] == normalized_namespace
            ]
        if not matches:
            raise ValueError(
                f"registered directory namespace not found: {normalized_namespace}"
            )
        if len(matches) > 1:
            raise ValueError(
                f"registered directory namespace is ambiguous: {normalized_namespace}"
            )
        return matches[0]

    def _registered_directory_target(
        self,
        *,
        namespace: str,
        filename: str,
    ) -> tuple[Path, str, str]:
        stem = self._validate_registered_yaml_stem(filename)
        directory, normalized_namespace, pattern = (
            self._registered_directory_for_namespace(namespace)
        )
        target = directory / f"{stem}.yaml"
        if not fnmatchcase(target.name, pattern):
            raise ValueError(
                f"filename '{stem}' is outside the registered directory pattern"
            )
        if target.parent != directory:
            raise ValueError("registered YAML target escaped its directory")
        return target, normalized_namespace, pattern

    def write_registered_directory_yaml(
        self,
        *,
        namespace: str,
        filename: str,
        contents: dict[str, Any],
        create_only: bool,
    ) -> None:
        """Atomically replace one file in an already registered YAML directory."""
        if not isinstance(contents, dict):
            raise TypeError("contents must be a mapping")
        if not isinstance(create_only, bool):
            raise TypeError("create_only must be a bool")

        target, normalized_namespace, _ = self._registered_directory_target(
            namespace=namespace,
            filename=filename,
        )
        if not target.parent.exists():
            raise FileNotFoundError(
                f"registered config directory does not exist: {target.parent}"
            )
        if create_only and target.exists():
            raise FileExistsError(f"registered config file already exists: {target}")
        if not create_only and not target.exists():
            raise FileNotFoundError(f"registered config file does not exist: {target}")

        previous_exists = target.exists()
        previous_bytes = target.read_bytes() if previous_exists else None
        logical_key = f"{normalized_namespace}.{target.stem}"
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary:
                yaml.safe_dump(contents, temporary, sort_keys=False)
                temporary.flush()
                os.fsync(temporary.fileno())
                temp_path = Path(temporary.name)
            os.replace(temp_path, target)
            temp_path = None

            self._load_configs(trigger_callbacks=True)
            loaded_contents = self._file_states.get(logical_key)
            loaded_path = self._file_paths.get(logical_key)
            if loaded_contents != contents or loaded_path is None:
                raise RuntimeError(
                    f"ConfigManager reload did not observe {logical_key}"
                )
            if Path(loaded_path).resolve() != target.resolve():
                raise RuntimeError(
                    f"ConfigManager reload observed the wrong file for {logical_key}"
                )
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            try:
                if previous_exists and previous_bytes is not None:
                    rollback_path: Path | None = None
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        prefix=f".{target.name}.rollback.",
                        suffix=".tmp",
                        dir=target.parent,
                        delete=False,
                    ) as rollback_file:
                        rollback_file.write(previous_bytes)
                        rollback_file.flush()
                        os.fsync(rollback_file.fileno())
                        rollback_path = Path(rollback_file.name)
                    os.replace(rollback_path, target)
                else:
                    target.unlink(missing_ok=True)
                self._load_configs(trigger_callbacks=True)
            except Exception as rollback_exc:
                raise RuntimeError(
                    f"failed to roll back registered config file {target}"
                ) from rollback_exc
            raise

        logger.info("Registered config file updated: %s", target)

    def _remove_registered_directory_yaml_for_rollback(
        self,
        *,
        namespace: str,
        filename: str,
    ) -> None:
        """Remove a newly-created registered file during mutation rollback."""
        target, normalized_namespace, _ = self._registered_directory_target(
            namespace=namespace,
            filename=filename,
        )
        if not target.exists():
            return
        previous_bytes = target.read_bytes()
        try:
            target.unlink()
            self._load_configs(trigger_callbacks=True)
            if f"{normalized_namespace}.{target.stem}" in self._file_states:
                raise RuntimeError(
                    f"ConfigManager reload retained removed file {target}"
                )
        except Exception:
            try:
                rollback_path: Path | None = None
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{target.name}.rollback.",
                    suffix=".tmp",
                    dir=target.parent,
                    delete=False,
                ) as rollback_file:
                    rollback_file.write(previous_bytes)
                    rollback_file.flush()
                    os.fsync(rollback_file.fileno())
                    rollback_path = Path(rollback_file.name)
                os.replace(rollback_path, target)
                self._load_configs(trigger_callbacks=True)
            except Exception as rollback_exc:
                raise RuntimeError(
                    f"failed to roll back removal of registered config file {target}"
                ) from rollback_exc
            raise

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
