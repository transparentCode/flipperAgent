import re

with open('src/libs/common/config.py', 'r') as f:
    text = f.read()

# Add _registered_files and _watched_dirs to __init__
text = text.replace(
    "self._state: Dict[str, Any] = {}",
    "self._state: Dict[str, Any] = {}\n            self._registered_files = []\n            self._watched_dirs = set()\n            self._watched_dirs.add(self._config_dir)"
)

# Update _start_watchdog to track _config_dir using the new variables
old_watchdog = """        if not self._config_dir.exists():
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
        self._observer.start()"""

new_watchdog = """        if not self._config_dir.exists():
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
        for d in self._watched_dirs:
            if d.exists():
                self._observer.schedule(ConfigHandler(self), str(d), recursive=False)
        self._observer.start()

    def register_file(self, file_path: str | Path) -> None:
        path_obj = Path(file_path)
        with self._subscription_lock:
            if path_obj not in self._registered_files:
                self._registered_files.append(path_obj)
                parent_dir = path_obj.parent
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
        self._load_configs(trigger_callbacks=True)"""

text = text.replace(old_watchdog, new_watchdog)

# update _load_configs
old_load = """    def _load_configs(self, trigger_callbacks: bool = True) -> None:
        logger.info(f"Loading configs from {self._config_dir} for env={self._env}")
        try:
            new_state = {}
            
            # Load base first
            base_file = self._config_dir / CONFIG_BASE_FILENAME
            if base_file.exists():
                new_state = self._merge_dicts(new_state, self._read_yaml(base_file))
                
            # Load all other .yaml files (like features.yaml) except base, env, and local
            env_file = self._config_dir / f"{self._env}.yaml"
            local_file = self._config_dir / CONFIG_LOCAL_FILENAME
            
            for yaml_file in self._config_dir.glob("*.yaml"):
                if yaml_file not in (base_file, env_file, local_file):
                    new_state = self._merge_dicts(new_state, self._read_yaml(yaml_file))
                    
            # Load env and local last for overrides
            if env_file.exists():
                new_state = self._merge_dicts(new_state, self._read_yaml(env_file))
            if local_file.exists():
                new_state = self._merge_dicts(new_state, self._read_yaml(local_file))
            
            old_state = self._state
            self._state = new_state  # Atomic pointer swap for thread safety"""

new_load = """    def _load_configs(self, trigger_callbacks: bool = True) -> None:
        logger.info(f"Loading configs from {self._config_dir} for env={self._env}")
        try:
            new_state = {}
            
            # Load base first
            base_file = self._config_dir / CONFIG_BASE_FILENAME
            if base_file.exists():
                new_state = self._merge_dicts(new_state, self._read_yaml(base_file))
                
            env_file = self._config_dir / f"{self._env}.yaml"
            local_file = self._config_dir / CONFIG_LOCAL_FILENAME
            
            # Load explicitly registered files (e.g. features.yaml)
            for registered_file in self._registered_files:
                if registered_file.exists():
                    new_state = self._merge_dicts(new_state, self._read_yaml(registered_file))
                    
            # Load env and local last for overrides
            if env_file.exists():
                new_state = self._merge_dicts(new_state, self._read_yaml(env_file))
            if local_file.exists():
                new_state = self._merge_dicts(new_state, self._read_yaml(local_file))
            
            old_state = self._state
            self._state = new_state  # Atomic pointer swap for thread safety"""

text = text.replace(old_load, new_load)

with open('src/libs/common/config.py', 'w') as f:
    f.write(text)

