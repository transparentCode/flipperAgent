import os
import tempfile
import threading
import time
from pathlib import Path

import pytest
import yaml

from libs.common.config import ConfigManager


@pytest.fixture
def temp_config_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        base_content = {
            "app": {"name": "flipper", "port": 8000},
            "db": {"host": "localhost"},
        }
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
        f.write("app:\n  port: [1, 2,\n")  # invalid yaml unclosed list

    # We can't wait on a callback since it drops it, so we sleep to pass debounce
    time.sleep(1.0)

    # Verify state didn't crash and is intact
    assert config_manager.get("app.port") == old_port


def test_hot_reload_triggers_callback(config_manager, temp_config_dir):
    """Register a subscriber on a config key, simulate a file change, verify callback fires."""
    callback_event = threading.Event()
    received_val = {}

    def on_db_host_change(new_val):
        received_val["val"] = new_val
        callback_event.set()

    config_manager.subscribe("db.host", on_db_host_change)

    # Modify local.yaml to change db.host
    path = Path(temp_config_dir) / "local.yaml"
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    data["db"] = data.get("db", {})
    data["db"]["host"] = "new-db-host.example.com"
    with open(path, "w") as f:
        yaml.dump(data, f)

    callback_event.wait(timeout=2.0)

    assert callback_event.is_set(), "Subscriber callback not triggered"
    assert received_val["val"] == "new-db-host.example.com"
    assert config_manager.get("db.host") == "new-db-host.example.com"


def test_uses_flipper_env_when_env_not_explicit(temp_config_dir):
    ConfigManager.reset_singleton()
    path = Path(temp_config_dir) / "prod.yaml"
    with open(path, "w") as f:
        yaml.dump({"app": {"port": 9100}}, f)

    original_env = os.environ.get("FLIPPER_ENV")
    os.environ["FLIPPER_ENV"] = "prod"
    try:
        manager = ConfigManager(config_dir=temp_config_dir)
        assert manager.get("app.port") == 9100
        assert manager._env == "prod"
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()
        if original_env is not None:
            os.environ["FLIPPER_ENV"] = original_env
        else:
            os.environ.pop("FLIPPER_ENV", None)


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_register_directory_namespaces_files_and_filters_pattern(
    config_manager, temp_config_dir
):
    assets_dir = Path(temp_config_dir) / "assets"
    assets_dir.mkdir()
    (assets_dir / "BTC.yaml").write_text("asset: BTC\n", encoding="utf-8")
    (assets_dir / "SOL.yaml").write_text("asset: SOL\n", encoding="utf-8")
    (assets_dir / "ignored.yml").write_text("asset: IGNORED\n", encoding="utf-8")

    config_manager.register_directory(
        assets_dir,
        namespace="ingestion.assets",
        pattern="*.yaml",
    )

    assert config_manager.get("ingestion.assets.BTC") == {"asset": "BTC"}
    assert config_manager.get("ingestion.assets.SOL") == {"asset": "SOL"}
    assert config_manager.get("ingestion.assets.ignored") is None
    assert {entry["fileName"] for entry in config_manager.get_all_file_states()} >= {
        "BTC",
        "SOL",
    }


def test_register_directory_loads_files_deterministically_and_independently(
    config_manager,
    temp_config_dir,
):
    assets_dir = Path(temp_config_dir) / "assets"
    assets_dir.mkdir()
    (assets_dir / "SOL.yaml").write_text("asset: SOL\nvalue: sol\n", encoding="utf-8")
    (assets_dir / "BTC.yaml").write_text("asset: BTC\nvalue: btc\n", encoding="utf-8")

    config_manager.register_directory(assets_dir, namespace="assets")

    assets = config_manager.get("assets")
    assert list(assets) == ["BTC", "SOL"]
    assert assets["BTC"] == {"asset": "BTC", "value": "btc"}
    assert assets["SOL"] == {"asset": "SOL", "value": "sol"}


def test_register_directory_rejects_duplicate_logical_keys(
    config_manager, temp_config_dir
):
    first_dir = Path(temp_config_dir) / "assets_a"
    second_dir = Path(temp_config_dir) / "assets_b"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "BTC.yaml").write_text("asset: BTC\n", encoding="utf-8")
    (second_dir / "BTC.yaml").write_text("asset: BTC\n", encoding="utf-8")

    config_manager.register_directory(first_dir, namespace="assets")

    with pytest.raises(ValueError, match="Duplicate logical config key"):
        config_manager.register_directory(second_dir, namespace="assets")


def test_register_directory_additions_and_removals_reload_state(
    config_manager, temp_config_dir
):
    assets_dir = Path(temp_config_dir) / "assets"
    assets_dir.mkdir()
    btc_file = assets_dir / "BTC.yaml"
    btc_file.write_text("asset: BTC\n", encoding="utf-8")
    config_manager.register_directory(assets_dir, namespace="assets")

    sol_file = assets_dir / "SOL.yaml"
    sol_file.write_text("asset: SOL\n", encoding="utf-8")
    assert _wait_until(lambda: config_manager.get("assets.SOL") == {"asset": "SOL"})
    assert any(
        entry["fileName"] == "SOL" for entry in config_manager.get_all_file_states()
    )

    btc_file.unlink()
    assert _wait_until(lambda: config_manager.get("assets.BTC") is None)
    assert not any(
        entry["fileName"] == "BTC" for entry in config_manager.get_all_file_states()
    )


def test_register_directory_malformed_reload_retains_previous_state(
    config_manager, temp_config_dir
):
    assets_dir = Path(temp_config_dir) / "assets"
    assets_dir.mkdir()
    btc_file = assets_dir / "BTC.yaml"
    btc_file.write_text("asset: BTC\n", encoding="utf-8")
    config_manager.register_directory(assets_dir, namespace="assets")

    btc_file.write_text("asset: [BTC\n", encoding="utf-8")
    time.sleep(1.0)

    assert config_manager.get("assets.BTC") == {"asset": "BTC"}


def test_register_file_deep_merge_remains_unchanged(config_manager, temp_config_dir):
    extra_file = Path(temp_config_dir) / "extra.yaml"
    extra_file.write_text(
        "app:\n  name: changed\nextra:\n  enabled: true\n", encoding="utf-8"
    )

    config_manager.register_file(extra_file)

    assert config_manager.get("app.name") == "changed"
    assert config_manager.get("extra.enabled") is True


def _registered_assets(config_manager, temp_config_dir):
    assets_dir = Path(temp_config_dir) / "assets"
    assets_dir.mkdir()
    btc_file = assets_dir / "BTC.yaml"
    btc_file.write_text("asset: BTC\nenabled: true\n", encoding="utf-8")
    config_manager.register_directory(
        assets_dir,
        namespace="ingestion.assets",
        pattern="*.yaml",
    )
    return assets_dir, btc_file


def test_registered_directory_yaml_writer_creates_and_reloads(
    config_manager,
    temp_config_dir,
):
    assets_dir, _ = _registered_assets(config_manager, temp_config_dir)

    config_manager.write_registered_directory_yaml(
        namespace="ingestion.assets",
        filename="SOL",
        contents={"asset": "SOL", "enabled": False},
        create_only=True,
    )

    assert config_manager.get("ingestion.assets.SOL") == {
        "asset": "SOL",
        "enabled": False,
    }
    assert (assets_dir / "SOL.yaml").exists()
    assert not list(assets_dir.glob(".SOL.yaml.*.tmp"))


@pytest.mark.parametrize(
    "filename", ["", ".", "..", "../SOL", "nested/SOL", "SOL.yaml"]
)
def test_registered_directory_yaml_writer_rejects_unsafe_filename(
    config_manager,
    temp_config_dir,
    filename,
):
    _registered_assets(config_manager, temp_config_dir)

    with pytest.raises((TypeError, ValueError)):
        config_manager.write_registered_directory_yaml(
            namespace="ingestion.assets",
            filename=filename,
            contents={"asset": "SOL"},
            create_only=True,
        )


def test_registered_directory_yaml_writer_enforces_create_and_replace_modes(
    config_manager,
    temp_config_dir,
):
    _registered_assets(config_manager, temp_config_dir)

    with pytest.raises(FileExistsError):
        config_manager.write_registered_directory_yaml(
            namespace="ingestion.assets",
            filename="BTC",
            contents={"asset": "BTC", "enabled": False},
            create_only=True,
        )
    with pytest.raises(FileNotFoundError):
        config_manager.write_registered_directory_yaml(
            namespace="ingestion.assets",
            filename="SOL",
            contents={"asset": "SOL"},
            create_only=False,
        )


def test_registered_directory_yaml_writer_rolls_back_reload_failure(
    config_manager,
    temp_config_dir,
    monkeypatch,
):
    assets_dir, btc_file = _registered_assets(config_manager, temp_config_dir)
    previous_contents = btc_file.read_text(encoding="utf-8")
    original_read_yaml = config_manager._read_yaml

    def fail_for_target(file_path):
        if Path(file_path).resolve() == btc_file.resolve():
            raise ValueError("synthetic reload failure")
        return original_read_yaml(file_path)

    monkeypatch.setattr(config_manager, "_read_yaml", fail_for_target)

    with pytest.raises(RuntimeError, match="reload did not observe"):
        config_manager.write_registered_directory_yaml(
            namespace="ingestion.assets",
            filename="BTC",
            contents={"asset": "BTC", "enabled": False},
            create_only=False,
        )

    assert btc_file.read_text(encoding="utf-8") == previous_contents
    assert config_manager.get("ingestion.assets.BTC") == {
        "asset": "BTC",
        "enabled": True,
    }
    assert not list(assets_dir.glob(".BTC.yaml.*.tmp"))


def test_registered_directory_yaml_writer_create_rollback_removes_file(
    config_manager,
    temp_config_dir,
    monkeypatch,
):
    assets_dir, _ = _registered_assets(config_manager, temp_config_dir)
    target = assets_dir / "SOL.yaml"
    original_read_yaml = config_manager._read_yaml

    def fail_for_target(file_path):
        if Path(file_path).resolve() == target.resolve():
            raise ValueError("synthetic reload failure")
        return original_read_yaml(file_path)

    monkeypatch.setattr(config_manager, "_read_yaml", fail_for_target)

    with pytest.raises(RuntimeError, match="reload did not observe"):
        config_manager.write_registered_directory_yaml(
            namespace="ingestion.assets",
            filename="SOL",
            contents={"asset": "SOL"},
            create_only=True,
        )

    assert not target.exists()
    assert config_manager.get("ingestion.assets.SOL") is None
    assert not list(assets_dir.glob(".SOL.yaml.*.tmp"))
