from __future__ import annotations

import json
import warnings
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from apps.ingestion_app.settings import load_ingestion_settings
from libs.common.config import ConfigManager


def _global_config() -> dict:
    return {
        "ingestion": {
            "base_timeframe": "1m",
            "calendar": {
                "type": "continuous",
                "timezone": "UTC",
                "alignment_origin": "1970-01-05T00:00:00Z",
            },
            "recovery": {
                "max_concurrency": 4,
                "page_limit": 500,
                "max_attempts_per_provider": 2,
                "retry_backoff_seconds": 1,
                "rest_finalization_grace_seconds": 5,
            },
            "websocket": {
                "stream_url": "wss://fstream.binance.com/market",
                "queue_maxsize": 1000,
            },
            "runtime": {
                "reconnect_backoff_seconds": 5,
            },
            "server": {
                "host": "0.0.0.0",
                "port": 8003,
            },
            "publication": {
                "batch_size": 500,
                "idle_sleep_seconds": 1,
                "error_backoff_seconds": 1,
                "stream_maxlen": 1000,
                "stream_approximate": True,
            },
            "retention": {
                "candle_days": 90,
                "published_outbox_days": 7,
                "cleanup_interval_seconds": 86400,
                "error_backoff_seconds": 60,
                "outbox_delete_batch_size": 10000,
                "outbox_max_batches_per_run": 100,
            },
            "timeframes": {
                "1m": {"duration_seconds": 60},
                "1h": {"duration_seconds": 3600},
            },
            "providers": {
                "binance_native": {"enabled": True},
                "ccxt_binance": {"enabled": True, "exchange_id": "binanceusdm"},
            },
        }
    }


def _asset_config() -> dict:
    return {
        "asset": "BTC",
        "enabled": True,
        "instruments": {
            "BTC-USDT-PERP": {
                "venue": "binance",
                "market_type": "perpetual",
                "base_asset": "BTC",
                "quote_asset": "USDT",
                "settlement_asset": "USDT",
                "live_provider": "binance_native",
                "historical_providers": ["binance_native", "ccxt_binance"],
                "provider_symbols": {
                    "binance_native": "BTCUSDT",
                    "ccxt_binance": "BTC/USDT:USDT",
                },
                "timeframes": ["1m", "1h"],
            }
        },
    }


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


@pytest.fixture
def temp_ingestion_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ConfigManager:
    monkeypatch.chdir(tmp_path)
    config_root = tmp_path / "configs"
    _write_yaml(config_root / "ingestion" / "global.yaml", _global_config())
    _write_yaml(config_root / "ingestion" / "assets" / "BTC.yaml", _asset_config())

    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(config_root))
    yield manager
    manager.shutdown()
    ConfigManager.reset_singleton()


def test_real_global_and_asset_configuration_load_successfully() -> None:
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(repository_root / "configs"))
    try:
        settings = load_ingestion_settings(manager)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()

    assert settings.base_timeframe == "1m"
    assert settings.calendar.type == "continuous"
    assert settings.calendar.timezone == "UTC"
    assert settings.calendar.alignment_origin == datetime(1970, 1, 5, tzinfo=UTC)
    assert settings.recovery.max_concurrency == 4
    assert settings.recovery.page_limit == 500
    assert settings.recovery.max_attempts_per_provider == 2
    assert settings.recovery.retry_backoff_seconds == 1
    assert settings.recovery.rest_finalization_grace_seconds == 5
    assert settings.websocket.stream_url == "wss://fstream.binance.com/market"
    assert settings.websocket.queue_maxsize == 1000
    assert settings.runtime.reconnect_backoff_seconds == 5
    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 8003
    assert settings.publication.batch_size == 500
    assert settings.publication.idle_sleep_seconds == 1
    assert settings.publication.error_backoff_seconds == 1
    assert settings.publication.stream_maxlen == 1000
    assert settings.publication.stream_approximate is True
    assert settings.retention.candle_days == 91
    assert settings.retention.published_outbox_days == 7
    assert settings.retention.cleanup_interval_seconds == 86400
    assert settings.retention.error_backoff_seconds == 60
    assert settings.retention.outbox_delete_batch_size == 10000
    assert settings.retention.outbox_max_batches_per_run == 100
    assert settings.providers["ccxt_binance"].exchange_id == "binanceusdm"
    assert settings.assets["BTC"].instruments["BTC-USDT-PERP"].base_asset == "BTC"


def test_production_yaml_timeframes_are_authoritative() -> None:
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(repository_root / "configs"))
    try:
        settings = load_ingestion_settings(manager)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()

    instrument = settings.assets["BTC"].instruments["BTC-USDT-PERP"]
    assert instrument.timeframes[-4:] == ("6h", "12h", "1d", "1w")
    assert settings.timeframes["6h"].duration_seconds == 21_600
    assert settings.timeframes["12h"].duration_seconds == 43_200
    assert settings.timeframes["1d"].duration_seconds == 86_400
    assert settings.timeframes["1w"].duration_seconds == 604_800


def test_validated_settings_mappings_are_immutable(
    temp_ingestion_manager: ConfigManager,
) -> None:
    settings = load_ingestion_settings(temp_ingestion_manager)
    instrument = settings.assets["BTC"].instruments["BTC-USDT-PERP"]

    with pytest.raises(TypeError):
        settings.timeframes["1m"] = settings.timeframes["1m"]
    with pytest.raises(TypeError):
        settings.providers["binance_native"] = settings.providers["binance_native"]
    with pytest.raises(TypeError):
        settings.assets["BTC"] = settings.assets["BTC"]
    with pytest.raises(TypeError):
        settings.assets["BTC"].instruments["BTC-USDT-PERP"] = instrument
    with pytest.raises(TypeError):
        instrument.provider_symbols["binance_native"] = "BTCUSDT"


def test_settings_model_dump_is_warning_free_and_serializable(
    temp_ingestion_manager: ConfigManager,
) -> None:
    settings = load_ingestion_settings(temp_ingestion_manager)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dumped = settings.model_dump()

    assert not caught
    assert isinstance(dumped["timeframes"], dict)
    assert isinstance(dumped["providers"], dict)
    assert isinstance(dumped["assets"], dict)
    assert dumped["recovery"]["page_limit"] == 500
    assert dumped["retention"]["candle_days"] == 90
    assert dumped["calendar"]["alignment_origin"] == "1970-01-05T00:00:00Z"
    assert isinstance(dumped["assets"]["BTC"], dict)
    assert isinstance(dumped["assets"]["BTC"]["instruments"], dict)
    assert isinstance(
        dumped["assets"]["BTC"]["instruments"]["BTC-USDT-PERP"]["provider_symbols"],
        dict,
    )
    assert json.dumps(dumped, sort_keys=True)


def test_settings_model_dump_json_succeeds(
    temp_ingestion_manager: ConfigManager,
) -> None:
    settings = load_ingestion_settings(temp_ingestion_manager)

    serialized = settings.model_dump_json()
    decoded = json.loads(serialized)

    assert decoded["base_timeframe"] == "1m"
    assert decoded["calendar"]["alignment_origin"] == "1970-01-05T00:00:00Z"
    assert decoded["recovery"]["max_concurrency"] == 4
    assert decoded["recovery"]["rest_finalization_grace_seconds"] == 5
    assert decoded["websocket"]["queue_maxsize"] == 1000
    assert decoded["runtime"]["reconnect_backoff_seconds"] == 5
    assert decoded["server"] == {"host": "0.0.0.0", "port": 8003}
    assert decoded["publication"] == {
        "batch_size": 500,
        "idle_sleep_seconds": 1,
        "error_backoff_seconds": 1,
        "stream_maxlen": 1000,
        "stream_approximate": True,
    }
    assert decoded["retention"] == {
        "candle_days": 90,
        "published_outbox_days": 7,
        "cleanup_interval_seconds": 86400,
        "error_backoff_seconds": 60,
        "outbox_delete_batch_size": 10000,
        "outbox_max_batches_per_run": 100,
    }
    assert decoded["timeframes"]["1h"]["duration_seconds"] == 3600
    assert (
        decoded["assets"]["BTC"]["instruments"]["BTC-USDT-PERP"]["provider_symbols"][
            "ccxt_binance"
        ]
        == "BTC/USDT:USDT"
    )


@pytest.mark.parametrize("invalid_duration", ["60", 60.0])
def test_duration_seconds_rejects_scalar_coercion(
    temp_ingestion_manager: ConfigManager,
    invalid_duration: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["timeframes"]["1h"]["duration_seconds"] = (
        invalid_duration
    )
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize("invalid_enabled", ["false", 1])
def test_provider_enabled_rejects_scalar_coercion(
    temp_ingestion_manager: ConfigManager,
    invalid_enabled: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["providers"]["binance_native"]["enabled"] = (
        invalid_enabled
    )
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize("invalid_enabled", ["false", 1])
def test_asset_enabled_rejects_scalar_coercion(
    temp_ingestion_manager: ConfigManager,
    invalid_enabled: object,
) -> None:
    asset = _asset_config()
    asset["enabled"] = invalid_enabled
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_concurrency", 0),
        ("page_limit", "500"),
        ("max_attempts_per_provider", False),
        ("retry_backoff_seconds", -1),
        ("rest_finalization_grace_seconds", -1),
    ],
)
def test_recovery_settings_reject_invalid_values(
    temp_ingestion_manager: ConfigManager,
    field: str,
    value: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["recovery"][field] = value
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    "field",
    [
        "max_concurrency",
        "page_limit",
        "max_attempts_per_provider",
        "retry_backoff_seconds",
        "rest_finalization_grace_seconds",
    ],
)
def test_recovery_settings_reject_bool_coercion(
    temp_ingestion_manager: ConfigManager,
    field: str,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["recovery"][field] = True
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stream_url", "https://fstream.binance.com"),
        ("stream_url", ""),
        ("queue_maxsize", 0),
        ("queue_maxsize", False),
        ("queue_maxsize", "1000"),
    ],
)
def test_websocket_settings_reject_invalid_values(
    temp_ingestion_manager: ConfigManager,
    field: str,
    value: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["websocket"][field] = value
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    "value",
    [-1, False, "5"],
)
def test_runtime_settings_reject_invalid_backoff(
    temp_ingestion_manager: ConfigManager,
    value: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["runtime"]["reconnect_backoff_seconds"] = value
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", ""),
        ("host", "   "),
        ("port", 0),
        ("port", 65_536),
        ("port", False),
        ("port", "8003"),
    ],
)
def test_server_settings_reject_invalid_values(
    temp_ingestion_manager: ConfigManager,
    field: str,
    value: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["server"][field] = value
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


def test_server_settings_trim_host(temp_ingestion_manager: ConfigManager) -> None:
    global_config = _global_config()
    global_config["ingestion"]["server"]["host"] = " 127.0.0.1 "
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    settings = load_ingestion_settings(temp_ingestion_manager)

    assert settings.server.host == "127.0.0.1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("batch_size", 0),
        ("batch_size", "500"),
        ("idle_sleep_seconds", 0),
        ("idle_sleep_seconds", -1),
        ("idle_sleep_seconds", "1"),
        ("error_backoff_seconds", 0),
        ("error_backoff_seconds", -1),
        ("error_backoff_seconds", "1"),
        ("stream_maxlen", 0),
        ("stream_maxlen", False),
        ("stream_approximate", "true"),
    ],
)
def test_publication_settings_reject_invalid_values(
    temp_ingestion_manager: ConfigManager,
    field: str,
    value: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["publication"][field] = value
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    "field",
    [
        "batch_size",
        "idle_sleep_seconds",
        "error_backoff_seconds",
        "stream_maxlen",
    ],
)
def test_publication_integer_settings_reject_bool_coercion(
    temp_ingestion_manager: ConfigManager,
    field: str,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["publication"][field] = True
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candle_days", 0),
        ("candle_days", -1),
        ("published_outbox_days", 0),
        ("cleanup_interval_seconds", 0),
        ("error_backoff_seconds", -1),
        ("outbox_delete_batch_size", 0),
        ("outbox_max_batches_per_run", 0),
        ("candle_days", "90"),
    ],
)
def test_retention_settings_reject_invalid_values(
    temp_ingestion_manager: ConfigManager,
    field: str,
    value: object,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["retention"][field] = value
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    "field",
    [
        "candle_days",
        "published_outbox_days",
        "cleanup_interval_seconds",
        "error_backoff_seconds",
        "outbox_delete_batch_size",
        "outbox_max_batches_per_run",
    ],
)
def test_retention_integer_settings_reject_bool_coercion(
    temp_ingestion_manager: ConfigManager,
    field: str,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["retention"][field] = True
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError):
        load_ingestion_settings(temp_ingestion_manager)


def test_filename_and_declared_asset_must_match(
    temp_ingestion_manager: ConfigManager,
) -> None:
    asset = _asset_config()
    asset["asset"] = "ETH"
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    with pytest.raises(ValidationError, match="filename stem"):
        load_ingestion_settings(temp_ingestion_manager)


def test_unknown_provider_fails(temp_ingestion_manager: ConfigManager) -> None:
    asset = _asset_config()
    instrument = asset["instruments"]["BTC-USDT-PERP"]
    instrument["live_provider"] = "unknown_provider"
    instrument["provider_symbols"]["unknown_provider"] = "BTCUSDT"
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    with pytest.raises(ValidationError, match="unknown provider"):
        load_ingestion_settings(temp_ingestion_manager)


def test_disabled_live_provider_fails(temp_ingestion_manager: ConfigManager) -> None:
    global_config = _global_config()
    global_config["ingestion"]["providers"]["binance_native"]["enabled"] = False
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError, match="disabled"):
        load_ingestion_settings(temp_ingestion_manager)


def test_missing_provider_symbol_fails(temp_ingestion_manager: ConfigManager) -> None:
    asset = _asset_config()
    del asset["instruments"]["BTC-USDT-PERP"]["provider_symbols"]["ccxt_binance"]
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    with pytest.raises(ValidationError, match="missing a symbol"):
        load_ingestion_settings(temp_ingestion_manager)


def test_unknown_timeframe_fails(temp_ingestion_manager: ConfigManager) -> None:
    asset = _asset_config()
    asset["instruments"]["BTC-USDT-PERP"]["timeframes"].append("2h")
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    with pytest.raises(ValidationError, match="unknown timeframe"):
        load_ingestion_settings(temp_ingestion_manager)


def test_missing_base_timeframe_in_asset_fails(
    temp_ingestion_manager: ConfigManager,
) -> None:
    asset = _asset_config()
    asset["instruments"]["BTC-USDT-PERP"]["timeframes"].remove("1m")
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    with pytest.raises(ValidationError, match="does not include base timeframe"):
        load_ingestion_settings(temp_ingestion_manager)


def test_invalid_duration_fails(temp_ingestion_manager: ConfigManager) -> None:
    global_config = _global_config()
    global_config["ingestion"]["timeframes"]["1h"]["duration_seconds"] = 0
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError, match="greater than 0"):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize("duplicate_field", ["historical_providers", "timeframes"])
def test_duplicate_provider_or_timeframe_references_fail(
    temp_ingestion_manager: ConfigManager,
    duplicate_field: str,
) -> None:
    asset = _asset_config()
    values = asset["instruments"]["BTC-USDT-PERP"][duplicate_field]
    values.append(values[0])
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        load_ingestion_settings(temp_ingestion_manager)


def test_arbitrary_fixed_duration_timeframe_requires_no_python_change(
    temp_ingestion_manager: ConfigManager,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["timeframes"]["2h"] = {"duration_seconds": 7200}
    asset = _asset_config()
    asset["instruments"]["BTC-USDT-PERP"]["timeframes"].append("2h")
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)
    _write_yaml(Path("configs/ingestion/assets/BTC.yaml"), asset)

    settings = load_ingestion_settings(temp_ingestion_manager)

    assert settings.timeframes["2h"].duration_seconds == 7200
    assert "2h" in settings.assets["BTC"].instruments["BTC-USDT-PERP"].timeframes


def test_unknown_ingestion_settings_field_fails(
    temp_ingestion_manager: ConfigManager,
) -> None:
    global_config = deepcopy(_global_config())
    global_config["ingestion"]["unexpected"] = True
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError, match="unexpected"):
        load_ingestion_settings(temp_ingestion_manager)


def test_missing_alignment_origin_fails(temp_ingestion_manager: ConfigManager) -> None:
    global_config = _global_config()
    del global_config["ingestion"]["calendar"]["alignment_origin"]
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError, match="alignment_origin"):
        load_ingestion_settings(temp_ingestion_manager)


def test_unsupported_calendar_type_fails(temp_ingestion_manager: ConfigManager) -> None:
    global_config = _global_config()
    global_config["ingestion"]["calendar"]["type"] = "session"
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError, match="calendar type"):
        load_ingestion_settings(temp_ingestion_manager)


def test_non_utc_calendar_timezone_fails(temp_ingestion_manager: ConfigManager) -> None:
    global_config = _global_config()
    global_config["ingestion"]["calendar"]["timezone"] = "Asia/Kolkata"
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError, match="calendar timezone"):
        load_ingestion_settings(temp_ingestion_manager)


@pytest.mark.parametrize(
    "alignment_origin",
    ["1970-01-05T00:00:00", "1970-01-05T05:30:00+05:30"],
)
def test_alignment_origin_must_be_utc_aware(
    temp_ingestion_manager: ConfigManager,
    alignment_origin: str,
) -> None:
    global_config = _global_config()
    global_config["ingestion"]["calendar"]["alignment_origin"] = alignment_origin
    _write_yaml(Path("configs/ingestion/global.yaml"), global_config)

    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        load_ingestion_settings(temp_ingestion_manager)
