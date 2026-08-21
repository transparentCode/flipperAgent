from pathlib import Path

import yaml

from apps.alert_app.settings import (
    AlertAppSettings,
    create_alert_config_manager,
    route_configs_from_config,
)
from libs.common.config import ConfigManager


def test_ingestion_health_config_uses_ready_status() -> None:
    config_path = Path(__file__).parents[2] / "configs" / "alerts.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config["alerts"]["health_checks"]["ingestion_runtime"][
        "healthy_statuses"
    ] == ["ready"]


def test_decision_health_config_uses_ready_status() -> None:
    config_path = Path(__file__).parents[2] / "configs" / "alerts.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    health = config["alerts"]["health_checks"]["decision_runtime"]

    assert health["source_app"] == "decision"
    assert health["url"] == "http://decision:8004/health/ready"
    assert health["healthy_statuses"] == ["ready"]


def test_alert_settings_load_from_config() -> None:
    settings = AlertAppSettings.from_config()
    assert settings.consumer_group == "alert_app_group"
    assert settings.lifecycle_stream == "asset:lifecycle"
    assert settings.execution_failure_prefix == "execution:failures:"


def test_alert_route_configs_load() -> None:
    manager = create_alert_config_manager()
    routes = route_configs_from_config(manager)
    assert "system_alerts" in routes
    assert routes["system_alerts"]["transport"] == "webhook"


def test_alert_route_configs_hydrate_telegram_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ALERTS_TELEGRAM_BOT_TOKEN", "token-123")
    monkeypatch.setenv("ALERTS_TELEGRAM_OPS_CHAT_ID", "-10001")
    alerts_config = {
        "alerts": {
            "routes": {
                "ops_alerts": {
                    "enabled": True,
                    "transport": "telegram",
                    "destination": "ops",
                    "bot_token": "",
                    "bot_token_env": "ALERTS_TELEGRAM_BOT_TOKEN",
                    "chat_id": "",
                    "chat_id_env": "ALERTS_TELEGRAM_OPS_CHAT_ID",
                },
            },
        },
    }
    config_dir = Path(tmp_path)
    (config_dir / "alerts.yaml").write_text(
        yaml.safe_dump(alerts_config, sort_keys=False),
        encoding="utf-8",
    )

    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(config_dir), env="dev")
    register_file = getattr(manager, "register_file", None)
    assert callable(register_file)
    register_file(config_dir / "alerts.yaml")

    routes = route_configs_from_config(manager)

    assert routes["ops_alerts"]["enabled"] is True
    assert routes["ops_alerts"]["bot_token"] == "token-123"
    assert routes["ops_alerts"]["chat_id"] == "-10001"

    manager.shutdown()
    ConfigManager.reset_singleton()
