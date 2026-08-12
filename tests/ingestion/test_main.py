from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest


def test_import_has_no_resource_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.ingestion_app import bootstrap

    config_manager = MagicMock()
    monkeypatch.setattr(bootstrap, "ConfigManager", config_manager)

    module = importlib.import_module("apps.ingestion_app.main")
    importlib.reload(module)

    config_manager.assert_not_called()
    assert module.app is None


def test_main_uses_yaml_server_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import apps.ingestion_app.main as module

    config_manager = MagicMock()
    config_manager.get.side_effect = lambda key, default=None: {
        "ingestion": {
            "server": {"host": "127.0.0.1", "port": 8123},
        },
        "logging.level": "INFO",
        "logging.console_format": "json",
        "logging.log_file": None,
    }.get(key, default)
    application = object()
    monkeypatch.setattr(module, "ConfigManager", lambda: config_manager)
    monkeypatch.setattr(module, "create_application", lambda **kwargs: application)
    configure_logging = MagicMock()
    monkeypatch.setattr(module, "configure_logging", configure_logging)
    run = MagicMock()
    monkeypatch.setattr(module.uvicorn, "run", run)

    module.main()

    config_manager.register_file.assert_called_once_with(
        "configs/ingestion/global.yaml"
    )
    run.assert_called_once_with(application, host="127.0.0.1", port=8123)
    configure_logging.assert_called_once()
    config_manager.shutdown.assert_called_once_with()


def test_main_closes_config_manager_when_uvicorn_fails_before_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import apps.ingestion_app.main as module

    config_manager = MagicMock()
    config_manager.get.side_effect = lambda key, default=None: {
        "ingestion": {
            "server": {"host": "127.0.0.1", "port": 8123},
        },
        "logging.level": "INFO",
        "logging.console_format": "json",
        "logging.log_file": None,
    }.get(key, default)
    application = object()
    create_application = MagicMock(return_value=application)
    monkeypatch.setattr(module, "ConfigManager", lambda: config_manager)
    monkeypatch.setattr(module, "create_application", create_application)
    monkeypatch.setattr(module, "configure_logging", MagicMock())

    def fail_before_lifespan(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("uvicorn failed before lifespan")

    monkeypatch.setattr(module.uvicorn, "run", fail_before_lifespan)

    with pytest.raises(RuntimeError, match="uvicorn failed before lifespan"):
        module.main()

    create_application.assert_called_once_with(config_manager=config_manager)
    config_manager.shutdown.assert_called_once_with()
