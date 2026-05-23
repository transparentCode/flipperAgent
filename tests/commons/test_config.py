import os
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import pytest
import yaml

from flipper_agent.commons.config import ConfigManager


@pytest.fixture
def temp_config_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        base_content = {"app": {"name": "flipper", "port": 8000}, "db": {"host": "localhost"}}
        dev_content = {"app": {"port": 8080}, "db": {"password": "dev_password"}}
        local_content = {"db": {"host": "127.0.0.1"}}
        
        with open(Path(temp_dir) / "base.yaml", "w") as f:
            yaml.dump(base_content, f)
        with open(Path(temp_dir) / "dev.yaml", "w") as f:
            yaml.dump(dev_content, f)
        with open(Path(temp_dir) / "local.yaml", "w") as f:
            yaml.dump(local_content, f)
            
        yield temp_dir


@pytest.fixture
def config_manager(temp_config_dir):
    # Ensure fresh instance
    ConfigManager.reset_singleton()
    
    # Set FLIPPER_ENV
    original_env = os.environ.get("FLIPPER_ENV")
    os.environ["FLIPPER_ENV"] = "dev"
    
    manager = ConfigManager(config_dir=temp_config_dir)
    
    yield manager
    
    manager.shutdown()
    if original_env is not None:
        os.environ["FLIPPER_ENV"] = original_env
    else:
        os.environ.pop("FLIPPER_ENV", None)


def test_hierarchical_merging(config_manager):
    # base port 8000 is overwritten by dev 8080
    assert config_manager.get("app.port") == 8080
    # base host localhost is overwritten by local 127.0.0.1
    assert config_manager.get("db.host") == "127.0.0.1"
    # dev password is kept
    assert config_manager.get("db.password") == "dev_password"
    # base name is kept
    assert config_manager.get("app.name") == "flipper"
    
    # Test fallback default
    assert config_manager.get("app.not_exist", "default") == "default"


def test_hot_reload_debounced(config_manager, temp_config_dir):
    callback_event = threading.Event()
    received_val = {}
    
    def on_change(new_val):
        received_val["val"] = new_val
        callback_event.set()
        
    config_manager.subscribe("app.port", on_change)
    
    # modify local.yaml
    path = Path(temp_config_dir) / "local.yaml"
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    
    data["app"] = {"port": 9000}
    with open(path, "w") as f:
        yaml.dump(data, f)
        
    # Wait for file system event and debounce timer
    callback_event.wait(timeout=2.0)
    
    assert callback_event.is_set(), "Reload event not triggered"
    assert received_val["val"] == 9000
    assert config_manager.get("app.port") == 9000


def test_poison_pill_handling(config_manager, temp_config_dir):
    old_port = config_manager.get("app.port")
    
    # Write invalid YAML
    path = Path(temp_config_dir) / "local.yaml"
    with open(path, "w") as f:
        f.write("app:\n  port: [1, 2,\n") # invalid yaml unclosed list
        
    # We can't wait on a callback since it drops it, so we sleep to pass debounce
    time.sleep(1.0)
    
    # Verify state didn't crash and is intact
    assert config_manager.get("app.port") == old_port
